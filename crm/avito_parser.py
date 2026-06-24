import email
import imaplib
import logging
import re
from email.header import decode_header
from html.parser import HTMLParser

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

from django.conf import settings
from django.utils import timezone

from .models import Client, Message

logger = logging.getLogger(__name__)

AVITO_EMAIL_FROM = 'avito.ru'
AVITO_CHANNEL = 'Авито'


def _decode_email_header(header_value):
    if not header_value:
        return ''
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or 'utf-8', errors='replace'))
            except LookupError:
                result.append(part.decode('utf-8', errors='replace'))
        else:
            result.append(str(part))
    return ' '.join(result)


def _get_email_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode('utf-8', errors='replace')
            elif content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode('utf-8', errors='replace')
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode('utf-8', errors='replace')
    return ''


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip_tag = False

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'):
            self._skip_tag = True

    def handle_endtag(self, tag):
        if tag in ('style', 'script'):
            self._skip_tag = False

    def handle_data(self, data):
        if not self._skip_tag:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)

    def get_text(self):
        return ' '.join(self._text)


def _html_to_text(html):
    if HAS_BS4:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()
        return soup.get_text(separator=' ', strip=True)
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def parse_avito_email(body_text):
    text = _html_to_text(body_text) if '<html' in body_text.lower() or '<!DOCTYPE' in body_text else body_text

    result = {
        'client_name': '',
        'client_contact': '',
        'message_text': '',
        'ad_title': '',
        'ad_url': '',
    }

    patterns = {
        'client_name': [
            r'(?:Пользователь|Клиент|Продавец|Покупатель)\s*:?\s*([^\n\r]+)',
            r'(?:Имя|Name)\s*:?\s*([^\n\r]+)',
        ],
        'message_text': [
            r'(?:Сообщение|Текст сообщения|Message)\s*:?\s*([^\n\r]+)',
            r'(?:пишет|написал|написала)\s*[:\s]+([^\n\r]+)',
        ],
        'ad_title': [
            r'(?:Товар|Объявление|Ad|Item)\s*:?\s*([^\n\r]+)',
            r'(?:по объявлению)\s+[«"]([^»"]+)[»"]',
        ],
        'ad_url': [
            r'https?://(?:www\.)?avito\.ru[^\s<>"]*',
        ],
    }

    for key, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result[key] = match.group(1).strip()
                break

    contact_match = re.search(r'([\w.+-]+@[\w-]+\.[\w.+-]+)', text)
    if contact_match:
        result['client_contact'] = contact_match.group(1)

    phone_match = re.search(r'(\+7[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})', text)
    if phone_match:
        result['client_contact'] = phone_match.group(1)

    avito_id_match = re.search(r'avito[:\s]*([\w-]+)', text, re.IGNORECASE)
    if avito_id_match:
        if not result['client_contact']:
            result['client_contact'] = avito_id_match.group(1)

    if result['ad_url'] and isinstance(result['ad_url'], list):
        result['ad_url'] = result['ad_url'][0]

    if not result['message_text']:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines:
            decoded = _decode_email_header(line)
            if decoded and len(decoded) > 20 and not decoded.startswith('http'):
                result['message_text'] = decoded
                break

    return result


def _find_or_create_client(name, contact):
    if contact:
        if '@' in contact:
            client = Client.objects.filter(email__iexact=contact).first()
        else:
            client = Client.objects.filter(phone=contact).first()
        if client:
            return client

    existing = Client.objects.filter(name__iexact=name).first()
    if existing:
        return existing

    client = Client.objects.create(
        name=name or 'Клиент с Авито',
        phone=contact if contact and '@' not in contact else '',
        email=contact if contact and '@' in contact else '',
        source='Авито',
        status=Client.Status.UNKNOWN,
    )
    client.history = [{'type': 'import', 'text': 'Создан из email-уведомления Авито', 'at': timezone.now().isoformat()}]
    client.save(update_fields=['history', 'updated_at'])
    return client


def poll_avito_mailbox():
    host = getattr(settings, 'AVITO_EMAIL_HOST', '')
    port = getattr(settings, 'AVITO_EMAIL_PORT', 993)
    user = getattr(settings, 'AVITO_EMAIL_USER', '')
    password = getattr(settings, 'AVITO_EMAIL_PASSWORD', '')

    if not all([host, user, password]):
        logger.warning('Avito email credentials not configured')
        return {'status': 'error', 'message': 'Avito email not configured', 'imported': 0}

    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select('INBOX')
    except Exception as e:
        logger.error(f'IMAP connection failed: {e}')
        return {'status': 'error', 'message': f'IMAP error: {e}', 'imported': 0}

    try:
        status, messages = mail.search(None, 'UNSEEN')
        if status != 'OK':
            mail.logout()
            return {'status': 'ok', 'message': 'No unseen messages', 'imported': 0}

        email_ids = messages[0].split() if messages[0] else []
        imported = 0
        errors = 0

        for eid in email_ids:
            try:
                status, msg_data = mail.fetch(eid, '(RFC822)')
                if status != 'OK':
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                email_from = _decode_email_header(msg.get('From', ''))
                email_subject = _decode_email_header(msg.get('Subject', ''))

                if AVITO_EMAIL_FROM not in email_from.lower():
                    continue

                body = _get_email_body(msg)
                parsed = parse_avito_email(body)

                client_name = parsed.get('client_name') or email_subject or 'Клиент с Авито'
                client_contact = parsed.get('client_contact', '')
                message_text = parsed.get('message_text') or body[:500]

                client = _find_or_create_client(client_name, client_contact)

                Message.objects.create(
                    channel=AVITO_CHANNEL,
                    direction=Message.Direction.INBOUND,
                    client=client,
                    author_name=client_name,
                    contact=client_contact,
                    text=message_text,
                    unread=True,
                )

                client.history = (client.history or []) + [
                    {'type': 'message', 'text': f'Входящее через Авито: {message_text[:80]}', 'at': timezone.now().isoformat()}
                ]
                client.source = 'Авито'
                client.save(update_fields=['history', 'source', 'updated_at'])

                mail.store(eid, '+FLAGS', '\\Seen')
                imported += 1

            except Exception as e:
                logger.error(f'Failed to process email {eid}: {e}')
                errors += 1

        mail.logout()
        return {
            'status': 'ok',
            'message': f'Imported {imported} messages ({errors} errors)',
            'imported': imported,
            'errors': errors,
        }

    except Exception as e:
        try:
            mail.logout()
        except Exception:
            pass
        logger.error(f'Avito polling error: {e}')
        return {'status': 'error', 'message': str(e), 'imported': 0}
