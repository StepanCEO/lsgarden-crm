from django.core.management.base import BaseCommand

from crm.contact_utils import normalize_email, normalize_phone, parse_contact_aliases
from crm.models import Client, Message
from crm.tg_integration import _find_or_create_tg_client, _tg_chat_id_from_contact
from crm.vk_integration import _find_or_create_client, _vk_user_id_from_contact


def _client_aliases(client: Client) -> set[str]:
    aliases = set(parse_contact_aliases(client.contact_aliases or []))
    if client.phone:
        aliases.add(f'phone:{normalize_phone(client.phone)}')
    if client.email:
        aliases.add(f'email:{normalize_email(client.email)}')
    return {alias for alias in aliases if alias}


class Command(BaseCommand):
    help = 'Backfill client links for inbound messages and enrich client aliases'

    def handle(self, *args, **options):
        linked = 0
        updated_clients = 0

        clients = list(Client.objects.all())
        alias_map = {client.pk: _client_aliases(client) for client in clients}

        for message in Message.objects.select_related('client').all().order_by('id'):
            aliases = set(parse_contact_aliases([message.contact]))
            target = message.client

            if target is None and aliases:
                for client in clients:
                    if aliases.intersection(alias_map.get(client.pk, set())):
                        target = client
                        break

            if target is None and message.channel == 'VK':
                target = _find_or_create_client(
                    message.author_name,
                    message.contact,
                    _vk_user_id_from_contact(message.contact),
                )
            elif target is None and message.channel == 'Telegram':
                target = _find_or_create_tg_client(
                    message.author_name,
                    message.contact,
                    _tg_chat_id_from_contact(message.contact),
                )

            if target and message.client_id != target.pk:
                message.client = target
                message.save(update_fields=['client'])
                linked += 1

            if target and aliases:
                merged = sorted(set((target.contact_aliases or []) + list(aliases)))
                if merged != sorted(target.contact_aliases or []):
                    target.contact_aliases = merged
                    target.save(update_fields=['contact_aliases', 'updated_at'])
                    alias_map[target.pk] = _client_aliases(target)
                    updated_clients += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Relinked messages: linked={linked}, clients_updated={updated_clients}'
            )
        )
