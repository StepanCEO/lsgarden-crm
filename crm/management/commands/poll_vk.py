from django.core.management.base import BaseCommand

from crm.vk_integration import poll_vk_messages, poll_vk_wall_comments


class Command(BaseCommand):
    help = 'Poll VK messages and wall post comments, importing them into CRM'

    def handle(self, *args, **options):
        self.stdout.write('Polling VK messages...')
        result = poll_vk_messages()
        status = result.get('status', 'error')
        message = result.get('message', 'Unknown error')
        imported = result.get('imported', 0)

        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))

        if imported > 0:
            self.stdout.write(self.style.SUCCESS(f'Imported {imported} messages from VK'))

        self.stdout.write('Polling VK wall comments...')
        wall_result = poll_vk_wall_comments()
        wall_status = wall_result.get('status', 'error')
        wall_message = wall_result.get('message', 'Unknown error')
        wall_imported = wall_result.get('imported', 0)

        if wall_status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {wall_message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {wall_message}'))

        if wall_imported > 0:
            self.stdout.write(self.style.SUCCESS(f'Imported {wall_imported} wall comments from VK'))
