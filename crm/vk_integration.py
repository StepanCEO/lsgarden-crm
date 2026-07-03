import json
import logging
import re
import time
from collections.abc import Iterable
from datetime import timezone as dt_timezone

import requests

from django.conf import settings
from django.utils import timezone

from .contact_utils import parse_contact_aliases, sanitize_client_contacts
from .models import Client, IntegrationEvent, Message, ScheduleSettings

logger = logging.getLogger(__name__)


def _get_auto_reply():
    try:
        sched = ScheduleSettings.objects.first()
    except Exception:
        sched = None
    if sched and sched.should_send_auto_reply('VK'):
        return sched.format_message()
    return ''


VK_API_BASE = 'https://api.vk.com/method/'
VK_API_VERSION = '5.199'
VK_CHANNEL = 'VK'
VK_BOT_PREFIX = 'Добрый день! Вам отвечает Secret-бот.'


def _vk_request(method, params=None):
    token = getattr(settings, 'VK_API_TOKEN', '')
    if not token:
        logger.warning('VK_API_TOKEN not configured')
        return None

    data = {
        'access_token': token,
        'v': VK_API_VERSION,
        **(params or {}),
    }

    try:
        resp = requests.post(f'{VK_API_BASE}{method}', data=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if 'error' in result:
            logger.error(f'VK API error: {result["error"]}')
            return None
        return result.get('response')
    except requests.RequestException as e:
        logger.error(f'VK request failed: {e}')
        return None


def _vk_user_id_from_contact(contact: str) -> int | None:
    match = re.search(r'id(\d+)', str(contact or ''))
    if match:
        return int(match.group(1))
    raw = str(contact or '').strip()
    if raw.isdigit():
        return int(raw)
    return None


def _vk_profile_name(profile: dict | None, fallback: str = 'Пользователь VK') -> str:
    if not profile:
        return fallback
    first_name = str(profile.get('first_name', '')).strip()
    last_name = str(profile.get('last_name', '')).strip()
    return f'{first_name} {last_name}'.strip() or fallback


def _vk_profiles_map(profiles: Iterable[dict] | None) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for profile in profiles or []:
        profile_id = profile.get('id')
        if isinstance(profile_id, int):
            result[profile_id] = profile
    return result


def _vk_attachment_summary(message: dict) -> str:
    attachments = message.get('attachments') or []
    if not attachments:
        return ''
    labels = []
    for item in attachments[:3]:
        attachment_type = str(item.get('type', '')).strip().lower() or 'вложение'
        labels.append(attachment_type)
    suffix = f' +{len(attachments) - len(labels)}' if len(attachments) > len(labels) else ''
    return f"[Вложения: {', '.join(labels)}{suffix}]"


def _vk_message_text(message: dict) -> str:
    text = str(message.get('text', '') or '').strip()
    if text:
        return text
    return _vk_attachment_summary(message)


def _is_vk_bot_message(message: dict, group_id: int | None = None) -> bool:
    from_id = int(message.get('from_id') or 0)
    admin_author_id = message.get('admin_author_id')
    text = _vk_message_text(message)

    if text.startswith(VK_BOT_PREFIX):
        return True
    if from_id < 0 and not admin_author_id:
        if group_id is None:
            return True
        return from_id == -abs(group_id)
    return False


def _vk_message_signature(peer_id: int, message: dict) -> str:
    return f'{peer_id}:{message.get("id")}'


def _vk_message_created_at(message: dict):
    raw_ts = message.get('date')
    if raw_ts:
        return timezone.datetime.fromtimestamp(int(raw_ts), tz=dt_timezone.utc)
    return timezone.now()


def _store_vk_message(
    *,
    peer_id: int,
    message: dict,
    client: Client,
    group_id: int | None,
    user_profiles: dict[int, dict] | None = None,
    existing_event_ids: set[str] | None = None,
) -> bool:
    event_id = _vk_message_signature(peer_id, message)
    if existing_event_ids is not None and event_id in existing_event_ids:
        return False

    if IntegrationEvent.objects.filter(source='VK', event_type='message', external_id=event_id).exists():
        if existing_event_ids is not None:
            existing_event_ids.add(event_id)
        return False

    if _is_vk_bot_message(message, group_id=group_id):
        return False

    text = _vk_message_text(message)
    if not text:
        return False

    from_id = int(message.get('from_id') or 0)
    admin_author_id = message.get('admin_author_id')
    is_outbound = from_id < 0
    direction = Message.Direction.OUTBOUND if is_outbound else Message.Direction.INBOUND

    profile_map = user_profiles or {}
    if is_outbound:
        if admin_author_id and admin_author_id in profile_map:
            author_name = _vk_profile_name(profile_map.get(admin_author_id), 'Менеджер VK')
        elif admin_author_id:
            author_name = f'Менеджер VK (id{admin_author_id})'
        else:
            author_name = 'Сообщество VK'
    else:
        author_name = _vk_profile_name(profile_map.get(from_id), client.name or f'Пользователь VK (id{from_id})')

    contact = f'vk.com/id{peer_id}'

    created_at = _vk_message_created_at(message)
    db_message = Message.objects.create(
        channel=VK_CHANNEL,
        direction=direction,
        client=client,
        author_name=author_name,
        contact=contact,
        text=text,
        unread=direction == Message.Direction.INBOUND,
    )
    Message.objects.filter(pk=db_message.pk).update(created_at=created_at)
    IntegrationEvent.objects.create(
        source='VK',
        event_type='message',
        external_id=event_id,
        payload={
            'peer_id': peer_id,
            'message_id': message.get('id'),
            'conversation_message_id': message.get('conversation_message_id'),
            'from_id': from_id,
        },
    )
    if existing_event_ids is not None:
        existing_event_ids.add(event_id)
    return True


def sync_vk_history(conversation_limit: int | None = None, history_limit: int | None = None) -> dict:
    token = getattr(settings, 'VK_API_TOKEN', '')
    if not token:
        return {'status': 'error', 'message': 'VK token not configured', 'imported': 0, 'clients': 0}

    raw_group_id = str(getattr(settings, 'VK_GROUP_ID', '') or '').strip()
    group_id = int(raw_group_id) if raw_group_id.isdigit() else None

    imported = 0
    created_clients = 0
    skipped_conversations = 0
    errors = 0
    offset = 0
    batch_size = 200
    processed_conversations = 0
    existing_event_ids = set(
        IntegrationEvent.objects.filter(source='VK', event_type='message').values_list('external_id', flat=True)
    )

    while True:
        params = {
            'count': batch_size,
            'offset': offset,
            'filter': 'all',
            'extended': 1,
        }
        if group_id:
            params['group_id'] = group_id

        response = _vk_request('messages.getConversations', params)
        if not response:
            return {
                'status': 'error',
                'message': 'VK API returned no response',
                'imported': imported,
                'clients': created_clients,
                'errors': errors + 1,
            }

        items = response.get('items', [])
        profiles_map = _vk_profiles_map(response.get('profiles'))
        if not items:
            break

        for item in items:
            if conversation_limit is not None and processed_conversations >= conversation_limit:
                break
            processed_conversations += 1
            try:
                conversation = item.get('conversation', {})
                peer = conversation.get('peer', {})
                peer_id = int(peer.get('id') or 0)
                peer_type = peer.get('type')

                if not peer_id or peer_type != 'user':
                    skipped_conversations += 1
                    continue

                profile = profiles_map.get(peer_id)
                client_name = _vk_profile_name(profile, f'Пользователь VK (id{peer_id})')
                contact = f'vk.com/id{peer_id}'
                existing_client = Client.objects.filter(contact_aliases__contains=[contact]).first()
                imported_before = imported
                client = _find_or_create_client(client_name, contact, peer_id)

                history_offset = 0
                history_batch = 200
                loaded = 0
                history_profiles = dict(profiles_map)

                while True:
                    count = history_batch
                    if history_limit is not None:
                        remaining = history_limit - loaded
                        if remaining <= 0:
                            break
                        count = min(history_batch, remaining)

                    history = _vk_request('messages.getHistory', {
                        'peer_id': peer_id,
                        'count': count,
                        'offset': history_offset,
                        'rev': 1,
                        'extended': 1,
                    })
                    if not history:
                        break

                    history_items = history.get('items', [])
                    for message in history_items:
                        from_id = int(message.get('from_id') or 0)
                        if from_id > 0 and from_id not in history_profiles:
                            history_profiles[from_id] = {'id': from_id, 'first_name': '', 'last_name': ''}
                        if _store_vk_message(
                            peer_id=peer_id,
                            message=message,
                            client=client,
                            group_id=group_id,
                            user_profiles=history_profiles,
                            existing_event_ids=existing_event_ids,
                        ):
                            imported += 1

                    loaded += len(history_items)
                    if len(history_items) < count:
                        break
                    history_offset += len(history_items)
                    time.sleep(0.1)

                if existing_client is None and imported == imported_before:
                    client.delete()
                    continue
                if existing_client is None:
                    created_clients += 1

                client.source = 'VK'
                client.preferred_channel = 'VK'
                client.contact_aliases = sorted(set((client.contact_aliases or []) + parse_contact_aliases([contact])))
                client.save(update_fields=['source', 'preferred_channel', 'contact_aliases', 'updated_at'])
                time.sleep(0.05)

            except Exception as e:
                logger.error(f'Failed to sync VK conversation: {e}')
                errors += 1

        if conversation_limit is not None and processed_conversations >= conversation_limit:
            break
        offset += len(items)
        if len(items) < batch_size:
            break

    return {
        'status': 'ok',
        'message': (
            f'Imported {imported} VK messages from {processed_conversations} conversations '
            f'({created_clients} clients, {skipped_conversations} skipped, {errors} errors)'
        ),
        'imported': imported,
        'clients': created_clients,
        'conversations': processed_conversations,
        'skipped': skipped_conversations,
        'errors': errors,
    }


def send_vk_message(contact: str, text: str) -> dict:
    user_id = _vk_user_id_from_contact(contact)
    if not user_id:
        return {'status': 'error', 'message': 'VK user id not found'}
    response = _vk_request('messages.send', {
        'user_id': user_id,
        'message': text,
        'random_id': int(time.time() * 1000),
    })
    if not response:
        return {'status': 'error', 'message': 'VK API request failed'}
    return {'status': 'ok', 'message': 'VK message sent', 'result': response}


def _find_or_create_client(name, contact, vk_user_id=None):
    aliases = parse_contact_aliases([contact, f'vk.com/id{vk_user_id}' if vk_user_id else ''])
    for client in Client.objects.all():
        if set(client.contact_aliases or []).intersection(aliases):
            return client

    if vk_user_id:
        existing = Message.objects.filter(contact=f'vk.com/id{vk_user_id}').exclude(client=None).values('client').first()
        if existing:
            client = Client.objects.filter(pk=existing['client']).first()
            if client:
                return client

    existing = Client.objects.filter(name__iexact=name).first()
    if existing:
        return existing

    phone, email, normalized_aliases = sanitize_client_contacts(contact, '', aliases)
    parts = [part for part in str(name or '').strip().split() if part]
    first_name = parts[0] if parts else ''
    last_name = ' '.join(parts[1:]) if len(parts) > 1 else ''
    client = Client.objects.create(
        name=name or 'Клиент из VK',
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        email=email or None,
        vk_url=f'vk.com/id{vk_user_id}' if vk_user_id else contact,
        source='VK',
        preferred_channel='VK',
        status=Client.Status.UNKNOWN,
        contact_aliases=normalized_aliases,
    )
    client.history = [
        {'type': 'import', 'text': 'Создан из сообщения VK', 'at': timezone.now().isoformat()}
    ]
    client.save(update_fields=['history', 'updated_at'])
    return client


def poll_vk_messages():
    token = getattr(settings, 'VK_API_TOKEN', '')
    if not token:
        return {'status': 'error', 'message': 'VK token not configured', 'imported': 0}

    group_id = getattr(settings, 'VK_GROUP_ID', '')
    params = {'count': 20, 'filter': 'unread', 'extended': 1}
    if group_id:
        params['group_id'] = group_id

    response = _vk_request('messages.getConversations', params)
    if not response:
        return {'status': 'error', 'message': 'VK API returned no response', 'imported': 0}

    items = response.get('items', [])
    if not items:
        return {'status': 'ok', 'message': 'No new conversations', 'imported': 0}

    imported = 0
    errors = 0
    profiles_map = _vk_profiles_map(response.get('profiles'))
    raw_group_id = str(group_id or '').strip()
    numeric_group_id = int(raw_group_id) if raw_group_id.isdigit() else None
    existing_event_ids = set(
        IntegrationEvent.objects.filter(source='VK', event_type='message').values_list('external_id', flat=True)
    )

    for item in items:
        try:
            conversation = item.get('conversation', {})
            peer = conversation.get('peer', {})
            peer_id = peer.get('id')
            peer_type = peer.get('type')

            if not peer_id or peer_type != 'user':
                continue

            contact = f'vk.com/id{peer_id}'
            profile = profiles_map.get(int(peer_id))
            author_name = _vk_profile_name(profile, f'Пользователь VK (id{peer_id})')
            last_msg = item.get('last_message', {})
            if _is_vk_bot_message(last_msg, group_id=numeric_group_id):
                continue

            client = _find_or_create_client(
                name=author_name,
                contact=contact,
                vk_user_id=peer_id,
            )

            imported_now = _store_vk_message(
                peer_id=int(peer_id),
                message=last_msg,
                client=client,
                group_id=numeric_group_id,
                user_profiles=profiles_map,
                existing_event_ids=existing_event_ids,
            )
            if imported_now:
                imported += 1

            try:
                sched = ScheduleSettings.objects.first()
            except Exception:
                sched = None
            reply_text = sched.format_message() if sched and sched.should_send_auto_reply(
                'VK',
                author_name=author_name,
                chat_type='private',
                is_outbound=False,
            ) else ''
            if reply_text and peer_id and imported_now:
                _vk_request('messages.send', {
                    'peer_id': peer_id,
                    'message': reply_text,
                    'random_id': int(time.time() * 1000),
                })
                Message.objects.create(
                    channel=VK_CHANNEL,
                    direction=Message.Direction.OUTBOUND,
                    client=client,
                    author_name='Бот LSG CRM',
                    contact='',
                    text=reply_text,
                    unread=False,
                )

            client.history = (client.history or []) + [
                {
                    'type': 'message',
                    'text': f'Входящее через VK: {_vk_message_text(last_msg)[:80]}',
                    'at': timezone.now().isoformat(),
                }
            ]
            client.source = 'VK'
            client.preferred_channel = client.preferred_channel or 'VK'
            client.contact_aliases = sorted(set((client.contact_aliases or []) + parse_contact_aliases([contact])))
            client.save(update_fields=['history', 'source', 'preferred_channel', 'contact_aliases', 'updated_at'])

            time.sleep(0.5)

        except Exception as e:
            logger.error(f'Failed to process VK conversation: {e}')
            errors += 1

    return {
        'status': 'ok',
        'message': f'Imported {imported} VK messages ({errors} errors)',
        'imported': imported,
        'errors': errors,
    }
