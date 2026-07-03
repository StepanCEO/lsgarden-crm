import getpass
import logging
import re
from pathlib import Path

import requests

from django.conf import settings
from django.utils import timezone

from .contact_utils import parse_contact_aliases
from .models import Client, IntegrationEvent, Message, ScheduleSettings

logger = logging.getLogger(__name__)

TG_CHANNEL = 'Telegram'


def _get_auto_reply():
    try:
        sched = ScheduleSettings.objects.first()
    except Exception:
        sched = None
    if sched and sched.should_send_auto_reply('Telegram'):
        return sched.format_message()
    return ''


def _tg_mode() -> str:
    explicit = str(getattr(settings, 'TG_INTEGRATION_MODE', 'bot') or '').strip().lower()
    if explicit in {'bot', 'account'}:
        return explicit
    if getattr(settings, 'TG_API_ID', '') and getattr(settings, 'TG_API_HASH', ''):
        return 'account'
    return 'bot'


def _tg_session_path() -> Path:
    session_name = str(getattr(settings, 'TG_SESSION_NAME', 'telegram_account') or 'telegram_account').strip()
    return Path(settings.BASE_DIR) / session_name


def _load_telethon():
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
        return TelegramClient, SessionPasswordNeededError
    except ImportError:
        return None, None


def _telethon_client():
    TelegramClient, _ = _load_telethon()
    api_id = str(getattr(settings, 'TG_API_ID', '') or '').strip()
    api_hash = str(getattr(settings, 'TG_API_HASH', '') or '').strip()
    if not TelegramClient:
        raise RuntimeError('Telethon not installed. Rebuild the app after updating requirements.')
    if not api_id or not api_hash:
        raise RuntimeError('TG_API_ID and TG_API_HASH are required for Telegram account mode.')
    return TelegramClient(str(_tg_session_path()), int(api_id), api_hash)


def tg_request(method, params=None):
    token = getattr(settings, 'TG_BOT_TOKEN', '')
    if not token:
        logger.warning('TG_BOT_TOKEN not configured')
        return None

    url = f'https://api.telegram.org/bot{token}/{method}'
    try:
        resp = requests.post(url, data=params or {}, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if not result.get('ok'):
            logger.error('TG API error: %s', result)
            return None
        return result.get('result')
    except requests.RequestException as e:
        logger.error('TG request failed: %s', e)
        return None


def _tg_chat_id_from_contact(contact: str) -> str | None:
    raw = str(contact or '').strip()
    if not raw:
        return None
    if raw.startswith('tg://user?id='):
        return raw.split('=', 1)[1].strip() or None
    if raw.startswith('@'):
        return raw
    if 't.me/' in raw:
        return raw.rstrip('/').rsplit('/', 1)[-1].strip() or None
    if raw.lstrip('-').isdigit():
        return raw
    return None


def _telethon_entity(client, contact: str):
    identifier = _tg_chat_id_from_contact(contact)
    if not identifier:
        return None
    if identifier.lstrip('-').isdigit():
        identifier = int(identifier)
    return client.get_entity(identifier)


def _message_exists(source: str, external_id: str) -> bool:
    return IntegrationEvent.objects.filter(source=source, event_type='message', external_id=external_id).exists()


def _record_message(
    *,
    source: str,
    external_id: str,
    client: Client,
    direction: str,
    author_name: str,
    contact: str,
    text: str,
    created_at,
    payload: dict,
    unread: bool,
):
    if _message_exists(source, external_id):
        return False
    db_message = Message.objects.create(
        channel=TG_CHANNEL,
        direction=direction,
        client=client,
        author_name=author_name,
        contact=contact,
        text=text,
        unread=unread,
    )
    Message.objects.filter(pk=db_message.pk).update(created_at=created_at)
    IntegrationEvent.objects.create(
        source=source,
        event_type='message',
        external_id=external_id,
        payload=payload,
    )
    return True


def _update_client_after_import(client: Client, text: str):
    client.history = (client.history or []) + [
        {'type': 'message', 'text': f'Входящее через Telegram: {text[:80]}', 'at': timezone.now().isoformat()}
    ]
    client.source = 'Telegram'
    if not client.preferred_channel:
        client.preferred_channel = 'Telegram'
    client.save(update_fields=['history', 'source', 'preferred_channel', 'updated_at'])


def send_tg_message(contact: str, text: str) -> dict:
    if _tg_mode() == 'account':
        try:
            with _telethon_client() as client:
                if not client.is_user_authorized():
                    return {'status': 'error', 'message': 'Telegram account session is not authorized'}
                entity = _telethon_entity(client, contact)
                if entity is None:
                    return {'status': 'error', 'message': 'Telegram contact not found in account dialogs'}
                result = client.send_message(entity, text)
                return {'status': 'ok', 'message': 'Telegram account message sent', 'result': {'id': result.id}}
        except Exception as e:
            logger.error('Telegram account send error: %s', e)
            return {'status': 'error', 'message': str(e)}

    chat_id = _tg_chat_id_from_contact(contact)
    if not chat_id:
        return {'status': 'error', 'message': 'Telegram chat id not found'}
    result = tg_request('sendMessage', {
        'chat_id': chat_id,
        'text': text,
    })
    if not result:
        return {'status': 'error', 'message': 'Telegram API request failed'}
    return {'status': 'ok', 'message': 'Telegram bot message sent', 'result': result}


def _poll_tg_bot_messages():
    token = getattr(settings, 'TG_BOT_TOKEN', '')
    if not token:
        return {'status': 'error', 'message': 'TG token not configured', 'imported': 0}

    updates = tg_request('getUpdates', {
        'timeout': 5,
        'allowed_updates': ['message'],
    })
    if not updates:
        return {'status': 'ok', 'message': 'No updates', 'imported': 0}

    imported = 0
    errors = 0
    last_update_id = 0

    for update in updates:
        try:
            update_id = update.get('update_id', 0)
            if update_id > last_update_id:
                last_update_id = update_id

            message = update.get('message', {})
            chat = message.get('chat', {})
            chat_id = chat.get('id')
            chat_type = chat.get('type', '')
            if chat_type != 'private':
                continue

            text = str(message.get('text', '') or '').strip()
            if not text:
                continue

            from_user = message.get('from', {})
            user_id = from_user.get('id')
            first_name = from_user.get('first_name', '')
            last_name = from_user.get('last_name', '')
            username = from_user.get('username', '')
            author_name = f'{first_name} {last_name}'.strip() or username or f'Пользователь TG (id{user_id})'
            contact = f'tg://user?id={user_id}' if user_id else (f'@{username}' if username else '')
            client = _find_or_create_tg_client(author_name, contact, user_id)

            if _record_message(
                source='TelegramBot',
                external_id=f'{chat_id}:{message.get("message_id")}',
                client=client,
                direction=Message.Direction.INBOUND,
                author_name=author_name,
                contact=contact,
                text=text,
                created_at=timezone.now(),
                payload={'chat_id': chat_id, 'message_id': message.get('message_id')},
                unread=True,
            ):
                imported += 1
                _update_client_after_import(client, text)

            try:
                sched = ScheduleSettings.objects.first()
            except Exception:
                sched = None
            reply_text = sched.format_message() if sched and sched.should_send_auto_reply(
                'Telegram',
                author_name=author_name,
                chat_type=chat_type,
                is_outbound=False,
            ) else ''
            if reply_text and chat_id:
                tg_request('sendMessage', {'chat_id': chat_id, 'text': reply_text})

        except Exception as e:
            logger.error('Failed to process TG update: %s', e)
            errors += 1

    if last_update_id:
        tg_request('getUpdates', {'offset': last_update_id + 1})

    return {
        'status': 'ok',
        'message': f'Imported {imported} TG bot messages ({errors} errors)',
        'imported': imported,
        'errors': errors,
    }


def _poll_tg_account_messages():
    imported = 0
    errors = 0
    dialog_limit = int(getattr(settings, 'TG_DIALOG_LIMIT', 50) or 50)
    history_limit = int(getattr(settings, 'TG_HISTORY_LIMIT', 40) or 40)

    try:
        with _telethon_client() as client:
            if not client.is_user_authorized():
                return {'status': 'error', 'message': 'Telegram account session is not authorized', 'imported': 0}

            dialogs = client.get_dialogs(limit=dialog_limit)
            for dialog in dialogs:
                if not getattr(dialog, 'is_user', False):
                    continue
                try:
                    contact = f'tg://user?id={dialog.entity.id}'
                    display_name = getattr(dialog, 'name', '') or 'Клиент из Telegram'
                    client_card = _find_or_create_tg_client(display_name, contact, dialog.entity.id)
                    messages = client.get_messages(dialog.entity, limit=history_limit)
                    latest_inbound = None
                    for tg_message in reversed(messages):
                        text = str(getattr(tg_message, 'message', '') or '').strip()
                        if not text:
                            continue
                        external_id = f'{dialog.entity.id}:{tg_message.id}'
                        if _message_exists('TelegramAccount', external_id):
                            continue
                        is_outbound = bool(getattr(tg_message, 'out', False))
                        direction = Message.Direction.OUTBOUND if is_outbound else Message.Direction.INBOUND
                        author_name = 'Рабочий Telegram' if is_outbound else display_name
                        created_at = getattr(tg_message, 'date', None) or timezone.now()
                        if _record_message(
                            source='TelegramAccount',
                            external_id=external_id,
                            client=client_card,
                            direction=direction,
                            author_name=author_name,
                            contact=contact,
                            text=text,
                            created_at=created_at,
                            payload={'chat_id': dialog.entity.id, 'message_id': tg_message.id},
                            unread=not is_outbound,
                        ):
                            imported += 1
                            if not is_outbound:
                                latest_inbound = tg_message
                                _update_client_after_import(client_card, text)

                    try:
                        sched = ScheduleSettings.objects.first()
                    except Exception:
                        sched = None
                    if sched and latest_inbound:
                        reply_text = sched.format_message() if sched.should_send_auto_reply(
                            'Telegram',
                            author_name=display_name,
                            chat_type='private',
                            is_outbound=False,
                        ) else ''
                        if reply_text:
                            auto_event_id = f'auto:{dialog.entity.id}:{latest_inbound.id}'
                            if not _message_exists('TelegramAccountAutoReply', auto_event_id):
                                sent = client.send_message(dialog.entity, reply_text)
                                _record_message(
                                    source='TelegramAccountAutoReply',
                                    external_id=auto_event_id,
                                    client=client_card,
                                    direction=Message.Direction.OUTBOUND,
                                    author_name='LSG CRM',
                                    contact=contact,
                                    text=reply_text,
                                    created_at=getattr(sent, 'date', None) or timezone.now(),
                                    payload={'chat_id': dialog.entity.id, 'message_id': getattr(sent, 'id', None)},
                                    unread=False,
                                )
                except Exception as inner_error:
                    logger.error('Failed to process Telegram dialog %s: %s', getattr(dialog, 'name', ''), inner_error)
                    errors += 1
    except Exception as e:
        logger.error('Telegram account polling error: %s', e)
        return {'status': 'error', 'message': str(e), 'imported': imported, 'errors': errors}

    return {
        'status': 'ok',
        'message': f'Imported {imported} Telegram account messages ({errors} errors)',
        'imported': imported,
        'errors': errors,
    }


def poll_tg_messages():
    if _tg_mode() == 'account':
        return _poll_tg_account_messages()
    return _poll_tg_bot_messages()


def setup_tg_account_session():
    if _tg_mode() != 'account':
        print('Telegram account mode is disabled. Set TG_INTEGRATION_MODE=account.')
        return

    phone = str(getattr(settings, 'TG_PHONE', '') or '').strip()
    if not phone:
        print('TG_PHONE is required for Telegram account authorization.')
        return

    TelegramClient, SessionPasswordNeededError = _load_telethon()
    if not TelegramClient:
        print('Telethon is not installed. Rebuild the project after updating requirements.')
        return

    print(f'Using session file: {_tg_session_path()}')
    with _telethon_client() as client:
        if client.is_user_authorized():
            print('Telegram account session is already authorized.')
            return
        client.send_code_request(phone)
        code = input('Введите код из Telegram: ').strip()
        try:
            client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = getpass.getpass('Введите пароль 2FA Telegram: ')
            client.sign_in(password=password)
        print('Telegram account session saved successfully.')


def _find_or_create_tg_client(name, contact, tg_user_id):
    aliases = parse_contact_aliases([contact])
    for client in Client.objects.all():
        if set(client.contact_aliases or []).intersection(aliases):
            return client

    if tg_user_id:
        existing = Message.objects.filter(contact=contact).exclude(client=None).values('client').first()
        if existing:
            client = Client.objects.filter(pk=existing['client']).first()
            if client:
                return client

    existing = Client.objects.filter(name__iexact=name).first()
    if existing:
        return existing

    parts = [part for part in re.split(r'\s+', str(name or '').strip()) if part]
    first_name = parts[0] if parts else ''
    last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''

    client = Client.objects.create(
        name=name or 'Клиент из Telegram',
        first_name=first_name,
        last_name=last_name,
        phone=None,
        source='Telegram',
        preferred_channel='Telegram',
        telegram_url=contact,
        status=Client.Status.UNKNOWN,
        contact_aliases=aliases,
    )
    client.history = [
        {'type': 'import', 'text': 'Создан из сообщения Telegram', 'at': timezone.now().isoformat()}
    ]
    client.save(update_fields=['history', 'updated_at'])
    return client
