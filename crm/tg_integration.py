import asyncio
import base64
import getpass
import io
import logging
import re
import threading
import time
from pathlib import Path

import requests

from django.conf import settings
from django.db import connections
from django.utils import timezone

from .contact_utils import parse_contact_aliases
from .models import Client, IntegrationEvent, Message, ScheduleSettings, TelegramLoginSession

QR_LOGIN_TOTAL_TIMEOUT = 180  # секунд на всю попытку логина
QR_LOGIN_STEP_TIMEOUT = 25  # телеграмовский QR-токен живёт ~30 сек, обновляем чуть раньше
QR_LOGIN_PASSWORD_TIMEOUT = 120  # сколько ждём ввод пароля 2FA из админки

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
        # ВАЖНО: импорт telethon.sync включает синхронные обёртки над async-методами
        # (connect/get_dialogs/send_message и т.д.). Без него методы возвращают
        # корутины, и account-режим не работает.
        import telethon.sync  # noqa: F401
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

    kwargs = {}
    proxy_host = str(getattr(settings, 'TG_PROXY_HOST', '') or '').strip()
    proxy_port = str(getattr(settings, 'TG_PROXY_PORT', '') or '').strip()
    proxy_secret = str(getattr(settings, 'TG_PROXY_SECRET', '') or '').strip()
    # На серверах, где Telegram заблокирован напрямую, ходим через MTProxy.
    if proxy_host and proxy_port and proxy_secret:
        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate
        secret = proxy_secret
        # Telethon для randomized-intermediate ждёт секрет с dd-маркером поверх
        # 16-байтного ключа. Если дали «голый» 16-байтный секрет (32 hex) —
        # добавляем маркер сами.
        if len(secret) == 32:
            secret = 'dd' + secret
        kwargs['connection'] = ConnectionTcpMTProxyRandomizedIntermediate
        kwargs['proxy'] = (proxy_host, int(proxy_port), secret)

    return TelegramClient(str(_tg_session_path()), int(api_id), api_hash, **kwargs)


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


def tg_account_auth_status() -> dict:
    """Быстрая проверка: авторизована ли сейчас сессия аккаунта.

    Важно: нельзя использовать `with _telethon_client() as client:` — Telethon
    на __enter__ синхронного клиента вызывает client.start(), который при
    неавторизованной сессии уходит в интерактивный запрос телефона/кода через
    input() и падает с EOF (нет TTY). Здесь сессия как раз может быть
    неавторизована, поэтому подключаемся вручную через connect().
    """
    if _tg_mode() != 'account':
        return {'authorized': False, 'message': 'Telegram account mode отключен (TG_INTEGRATION_MODE != account).'}

    TelegramClient, _ = _load_telethon()
    if not TelegramClient:
        return {'authorized': False, 'message': 'Telethon не установлен.'}

    client = _telethon_client()
    try:
        client.connect()
        authorized = client.is_user_authorized()
        return {
            'authorized': authorized,
            'message': 'Сессия авторизована.' if authorized else 'Сессия не авторизована — нужен вход.',
        }
    except Exception as e:
        return {'authorized': False, 'message': str(e)}
    finally:
        client.disconnect()


def _qr_data_uri(url: str) -> str:
    import qrcode
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def _set_qr_state(**fields):
    TelegramLoginSession.objects.filter(pk=1).update(**fields)


def start_tg_qr_login() -> dict:
    """Запускает фоновый поток с QR-логином Telegram-аккаунта. Состояние флоу
    хранится в БД (TelegramLoginSession), т.к. gunicorn работает несколькими
    воркерами и опрос статуса может попасть на другой процесс."""
    if _tg_mode() != 'account':
        return {'status': 'error', 'message': 'Telegram account mode отключен (TG_INTEGRATION_MODE != account).'}

    TelegramClient, _ = _load_telethon()
    if not TelegramClient:
        return {'status': 'error', 'message': 'Telethon не установлен.'}

    session = TelegramLoginSession.load()
    if session.status in (TelegramLoginSession.Status.WAITING, TelegramLoginSession.Status.PASSWORD_REQUIRED):
        return {'status': 'already_running', 'message': 'QR-логин уже запущен.'}

    TelegramLoginSession.objects.filter(pk=session.pk).update(
        status=TelegramLoginSession.Status.WAITING,
        qr_data_uri='',
        message='Готовим QR-код...',
        pending_password='',
    )
    threading.Thread(target=_run_tg_qr_login, daemon=True).start()
    return {'status': 'ok', 'message': 'QR-логин запущен.'}


def _wait_for_qr_password(timeout_seconds: int):
    _set_qr_state(
        status=TelegramLoginSession.Status.PASSWORD_REQUIRED,
        message='Введите пароль 2FA Telegram в админке.',
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        session = TelegramLoginSession.objects.filter(pk=1).first()
        if session and session.pending_password:
            _set_qr_state(pending_password='')
            return session.pending_password
        time.sleep(1)
    return None


def submit_tg_qr_password(password: str) -> dict:
    session = TelegramLoginSession.load()
    if session.status != TelegramLoginSession.Status.PASSWORD_REQUIRED:
        return {'status': 'error', 'message': 'Пароль сейчас не запрашивается.'}
    TelegramLoginSession.objects.filter(pk=session.pk).update(pending_password=password)
    return {'status': 'ok', 'message': 'Пароль отправлен.'}


def _run_tg_qr_login():
    # Telethon-синхронная обёртка держит asyncio event loop, привязанный к текущему
    # потоку. У фонового threading.Thread его нет по умолчанию (в отличие от главного
    # потока), поэтому без явного создания loop'а падает "no current event loop".
    asyncio.set_event_loop(asyncio.new_event_loop())
    _, SessionPasswordNeededError = _load_telethon()
    deadline = time.monotonic() + QR_LOGIN_TOTAL_TIMEOUT
    # Нельзя использовать `with _telethon_client() as client:` — __enter__ синхронного
    # клиента Telethon вызывает client.start(), который при неавторизованной сессии
    # уходит в интерактивный запрос телефона/кода через input() и падает с EOF
    # (нет TTY в потоке gunicorn-воркера). Сессия здесь не авторизована по определению
    # (иначе QR-логин был бы не нужен), поэтому подключаемся вручную через connect().
    client = _telethon_client()
    try:
        client.connect()
        login = client.qr_login()
        _set_qr_state(
            status=TelegramLoginSession.Status.WAITING,
            qr_data_uri=_qr_data_uri(login.url),
            message='Отсканируйте QR-код в приложении Telegram (Настройки → Устройства → Подключить устройство).',
        )

        while time.monotonic() < deadline:
            try:
                login.wait(timeout=QR_LOGIN_STEP_TIMEOUT)
                break
            except asyncio.TimeoutError:
                login.recreate()
                _set_qr_state(qr_data_uri=_qr_data_uri(login.url))
                continue
            except SessionPasswordNeededError:
                password = _wait_for_qr_password(QR_LOGIN_PASSWORD_TIMEOUT)
                if password is None:
                    _set_qr_state(
                        status=TelegramLoginSession.Status.EXPIRED,
                        message='Пароль 2FA не был введён вовремя.',
                    )
                    return
                client.sign_in(password=password)
                break
        else:
            _set_qr_state(
                status=TelegramLoginSession.Status.EXPIRED,
                message='Время ожидания скана QR истекло, попробуйте ещё раз.',
            )
            return

        _set_qr_state(
            status=TelegramLoginSession.Status.SUCCESS,
            message='Вход выполнен успешно, сессия обновлена.',
            qr_data_uri='',
        )
    except Exception as e:
        logger.error('Telegram QR login error: %s', e)
        _set_qr_state(status=TelegramLoginSession.Status.ERROR, message=str(e), qr_data_uri='')
    finally:
        client.disconnect()
        connections.close_all()


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
