from django.db import migrations


def _normalize_phone(value: str) -> str | None:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '7' + digits
    if len(digits) != 11 or not digits.startswith('79'):
        return None
    return f'+{digits}'


def forwards(apps, schema_editor):
    Client = apps.get_model('crm', 'Client')
    EmployeeProfile = apps.get_model('crm', 'EmployeeProfile')

    seen_client_phones: set[str] = set()
    for client in Client.objects.all().order_by('id'):
        phone = _normalize_phone(client.phone)
        second_phone = _normalize_phone(client.second_phone)

        if phone and phone in seen_client_phones:
            phone = None
        if phone:
            seen_client_phones.add(phone)

        if second_phone == phone or (second_phone and second_phone in seen_client_phones):
            second_phone = None
        if second_phone:
            seen_client_phones.add(second_phone)

        updates: list[str] = []
        if client.phone != phone:
            client.phone = phone
            updates.append('phone')
        if client.second_phone != second_phone:
            client.second_phone = second_phone
            updates.append('second_phone')
        if updates:
            client.save(update_fields=updates)

    for profile in EmployeeProfile.objects.all().order_by('id'):
        phone = _normalize_phone(profile.phone)
        if profile.phone != phone:
            profile.phone = phone or ''
            profile.save(update_fields=['phone'])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0009_schedule_settings_autoreply_controls'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
