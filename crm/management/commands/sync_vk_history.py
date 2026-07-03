from django.core.management.base import BaseCommand

from crm.vk_integration import sync_vk_history


class Command(BaseCommand):
    help = 'Import full VK conversation history into CRM, excluding bot auto-replies and group chats'

    def add_arguments(self, parser):
        parser.add_argument('--conversation-limit', type=int, default=None)
        parser.add_argument('--history-limit', type=int, default=None)

    def handle(self, *args, **options):
        self.stdout.write('Syncing full VK history...')
        result = sync_vk_history(
            conversation_limit=options.get('conversation_limit'),
            history_limit=options.get('history_limit'),
        )
        status = result.get('status', 'error')
        message = result.get('message', 'Unknown error')
        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))
