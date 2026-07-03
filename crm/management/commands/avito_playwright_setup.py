from django.core.management.base import BaseCommand
from crm.avito_playwright import setup_avito_session


class Command(BaseCommand):
    help = 'Setup Avito Playwright session (interactive — needs display)'

    def handle(self, *args, **options):
        self.stdout.write('Setting up Avito Playwright session...')
        setup_avito_session()
        self.stdout.write(self.style.SUCCESS('Done'))
