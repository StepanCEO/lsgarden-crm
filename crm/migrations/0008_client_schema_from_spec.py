# Generated manually to align client schema with the CRM spec.

from django.db import migrations, models
from django.utils.dateparse import parse_datetime


def split_client_name(value: str) -> tuple[str, str, str]:
    parts = [part for part in str(value or '').strip().split() if part]
    if not parts:
        return '', '', ''
    if len(parts) == 1:
        return '', parts[0], ''
    if len(parts) == 2:
        return parts[1], parts[0], ''
    return ' '.join(parts[2:]), parts[0], parts[1]


def forwards(apps, schema_editor):
    Client = apps.get_model('crm', 'Client')

    for client in Client.objects.all():
        changed = []

        if client.email == '':
            client.email = None
            changed.append('email')

        if not client.last_name and not client.first_name and not client.patronymic and client.name:
            last_name, first_name, patronymic = split_client_name(client.name)
            client.last_name = last_name
            client.first_name = first_name
            client.patronymic = patronymic
            changed.extend(['last_name', 'first_name', 'patronymic'])

        aliases = list(client.contact_aliases or [])
        if not client.vk_url:
            vk_url = next((alias for alias in aliases if 'vk.com/' in str(alias)), '')
            if vk_url:
                client.vk_url = vk_url
                changed.append('vk_url')
        if not client.telegram_url:
            telegram_url = next((alias for alias in aliases if str(alias).startswith('tg://') or str(alias).startswith('@')), '')
            if telegram_url:
                client.telegram_url = telegram_url
                changed.append('telegram_url')
        if not client.whatsapp_url:
            whatsapp_url = next((alias for alias in aliases if 'wa.me/' in str(alias) or 'whatsapp' in str(alias).lower()), '')
            if whatsapp_url:
                client.whatsapp_url = whatsapp_url
                changed.append('whatsapp_url')

        if not client.discount_card and client.discount_cards:
            client.discount_card = str(client.discount_cards[0] or '').strip()
            if client.discount_card:
                changed.append('discount_card')

        if client.first_purchase_at is None:
            purchase_dates = []
            for item in list(client.purchases or []) + list(client.bank_purchases or []):
                raw_at = item.get('at')
                if isinstance(raw_at, str):
                    parsed = parse_datetime(raw_at)
                    if parsed is not None:
                        purchase_dates.append(parsed)
            if purchase_dates:
                client.first_purchase_at = min(purchase_dates)
                changed.append('first_purchase_at')

        if changed:
            client.save(update_fields=sorted(set(changed)))


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0007_client_contact_aliases_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='birth_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='client',
            name='discount_card',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='client',
            name='district',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='client',
            name='first_name',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='client',
            name='first_purchase_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='client',
            name='last_name',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='client',
            name='patronymic',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='client',
            name='second_phone',
            field=models.CharField(blank=True, max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='client',
            name='telegram_url',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='client',
            name='vk_url',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='client',
            name='whatsapp_url',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='client',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='client',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True),
        ),
    ]
