from django.core.management.base import BaseCommand
from crm.avito_playwright import poll_avito_playwright


class Command(BaseCommand):
    help = 'Poll Avito messages via Playwright'

    def handle(self, *args, **options):
        self.stdout.write('Polling Avito via Playwright...')
        result = poll_avito_playwright()
        status = result.get('status', 'error')
        message = result.get('message', 'Unknown error')
        imported = result.get('imported', 0)
        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))
        if imported > 0:
            self.stdout.write(self.style.SUCCESS(f'Imported {imported} messages'))
