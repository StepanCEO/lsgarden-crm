from django.core.management.base import BaseCommand

from crm.vk_integration import sync_vk_wall_comments_history


class Command(BaseCommand):
    help = 'Import historical VK wall post comments into CRM'

    def add_arguments(self, parser):
        parser.add_argument('--post-limit', type=int, default=None)
        parser.add_argument('--comment-limit', type=int, default=None)

    def handle(self, *args, **options):
        self.stdout.write('Syncing VK wall comments history...')
        result = sync_vk_wall_comments_history(
            post_limit=options.get('post_limit'),
            comment_limit=options.get('comment_limit'),
        )
        status = result.get('status', 'error')
        message = result.get('message', 'Unknown error')
        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))
