from django.core.management.base import BaseCommand

from crm.contact_utils import is_placeholder_email, parse_contact_aliases, sanitize_client_contacts
from crm.models import Client


class Command(BaseCommand):
    help = 'Normalize client phones/emails and move social links into contact_aliases'

    def handle(self, *args, **options):
        updated = 0
        for client in Client.objects.prefetch_related('messages').all():
            raw_aliases = list(client.contact_aliases or [])
            raw_aliases.extend(msg.contact for msg in client.messages.all() if msg.contact)
            phone, email, aliases = sanitize_client_contacts(client.phone, client.email, raw_aliases)

            if client.source in {'VK', 'Telegram'} and is_placeholder_email(email):
                aliases = sorted(set(aliases + parse_contact_aliases([email])))
                email = ''

            preferred_channel = client.preferred_channel or client.source or ''
            if client.source in {'VK', 'Telegram'}:
                preferred_channel = client.source

            status = client.status
            if client.bank_purchases or client.purchases:
                status = Client.Status.BUYER
            elif phone or email:
                status = Client.Status.LEAD
            else:
                status = Client.Status.UNKNOWN

            changed = (
                client.phone != phone
                or client.email != email
                or client.preferred_channel != preferred_channel
                or sorted(client.contact_aliases or []) != aliases
                or client.status != status
            )
            if not changed:
                continue

            client.phone = phone
            client.email = email
            client.preferred_channel = preferred_channel
            client.contact_aliases = aliases
            client.status = status
            client.save(update_fields=['phone', 'email', 'preferred_channel', 'contact_aliases', 'status', 'updated_at'])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'Normalized {updated} clients'))
