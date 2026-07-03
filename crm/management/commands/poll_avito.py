from django.core.management.base import BaseCommand

from crm.avito_parser import poll_avito_mailbox


class Command(BaseCommand):
    help = 'Poll Avito email notifications and import messages'

    def handle(self, *args, **options):
        self.stdout.write('Polling Avito email mailbox...')
        result = poll_avito_mailbox()
        status = result.get('status', 'error')
        message = result.get('message', 'Unknown error')
        imported = result.get('imported', 0)

        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))

        if imported > 0:
            self.stdout.write(self.style.SUCCESS(f'Imported {imported} messages from Avito'))
