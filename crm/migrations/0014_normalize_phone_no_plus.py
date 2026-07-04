from django.db import migrations


def _strip_plus(value):
    if not value:
        return value
    return str(value).lstrip('+') or None


def forwards(apps, schema_editor):
    Client = apps.get_model('crm', 'Client')
    EmployeeProfile = apps.get_model('crm', 'EmployeeProfile')

    for client in Client.objects.all().order_by('id'):
        phone = _strip_plus(client.phone)
        second_phone = _strip_plus(client.second_phone)
        aliases = [
            alias.replace('phone:+', 'phone:') if alias.startswith('phone:+') else alias
            for alias in (client.contact_aliases or [])
        ]

        updates = []
        if client.phone != phone:
            client.phone = phone
            updates.append('phone')
        if client.second_phone != second_phone:
            client.second_phone = second_phone
            updates.append('second_phone')
        if client.contact_aliases != aliases:
            client.contact_aliases = aliases
            updates.append('contact_aliases')
        if updates:
            client.save(update_fields=updates)

    for profile in EmployeeProfile.objects.all().order_by('id'):
        phone = _strip_plus(profile.phone) or ''
        if profile.phone != phone:
            profile.phone = phone
            profile.save(update_fields=['phone'])


def backwards(apps, schema_editor):
    Client = apps.get_model('crm', 'Client')
    EmployeeProfile = apps.get_model('crm', 'EmployeeProfile')

    for client in Client.objects.all().order_by('id'):
        updates = []
        if client.phone and not client.phone.startswith('+'):
            client.phone = f'+{client.phone}'
            updates.append('phone')
        if client.second_phone and not client.second_phone.startswith('+'):
            client.second_phone = f'+{client.second_phone}'
            updates.append('second_phone')
        aliases = [
            alias.replace('phone:', 'phone:+', 1) if alias.startswith('phone:') and not alias.startswith('phone:+') else alias
            for alias in (client.contact_aliases or [])
        ]
        if client.contact_aliases != aliases:
            client.contact_aliases = aliases
            updates.append('contact_aliases')
        if updates:
            client.save(update_fields=updates)

    for profile in EmployeeProfile.objects.all().order_by('id'):
        if profile.phone and not profile.phone.startswith('+'):
            profile.phone = f'+{profile.phone}'
            profile.save(update_fields=['phone'])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0013_client_wish_products'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
