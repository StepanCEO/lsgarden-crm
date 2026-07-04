import re


PLACEHOLDER_EMAIL_DOMAINS = {
    'vk.local',
    'telegram.local',
}


def normalize_phone(value: str) -> str:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits:
        return ''
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '7' + digits

    if len(digits) != 11 or not digits.startswith('79'):
        return ''

    return digits


def normalize_email(value: str) -> str:
    return str(value or '').strip().lower()


def compose_client_name(last_name: str = '', first_name: str = '', patronymic: str = '', fallback: str = '') -> str:
    parts = [str(last_name or '').strip(), str(first_name or '').strip(), str(patronymic or '').strip()]
    joined = ' '.join(part for part in parts if part)
    return joined or str(fallback or '').strip()


def split_client_name(value: str) -> tuple[str, str, str]:
    parts = [part for part in str(value or '').strip().split() if part]
    if not parts:
        return '', '', ''
    if len(parts) == 1:
        return '', parts[0], ''
    if len(parts) == 2:
        return parts[1], parts[0], ''
    return ' '.join(parts[2:]), parts[0], parts[1]


def is_placeholder_email(value: str) -> bool:
    email = normalize_email(value)
    if '@' not in email:
        return False
    _, domain = email.rsplit('@', 1)
    return domain in PLACEHOLDER_EMAIL_DOMAINS


def normalize_contact_alias(value: str) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    phone = normalize_phone(raw)
    if phone:
        return f'phone:{phone}'
    email = normalize_email(raw)
    if '@' in email:
        return f'email:{email}'
    compact = re.sub(r'\s+', '', raw.lower())
    compact = compact.removeprefix('https://').removeprefix('http://').rstrip('/')
    return compact


def parse_contact_aliases(value: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = re.split(r'[\n,;]+', str(value or ''))
    aliases: list[str] = []
    for item in raw_items:
        alias = normalize_contact_alias(item)
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def sanitize_client_contacts(phone: str, email: str, aliases: list[str] | tuple[str, ...] | None = None) -> tuple[str | None, str, list[str]]:
    raw_phone = str(phone or '').strip()
    raw_email = str(email or '').strip()
    alias_values = list(aliases or [])

    if raw_phone:
        alias_values.append(raw_phone)
    if raw_email:
        alias_values.append(raw_email)

    normalized_email = normalize_email(raw_email)
    if '@' in raw_phone and not normalized_email:
        normalized_email = normalize_email(raw_phone)
        raw_phone = ''

    normalized_phone = normalize_phone(raw_phone)

    normalized_aliases = sorted(set(parse_contact_aliases(alias_values)))
    return normalized_phone or None, normalized_email, normalized_aliases
