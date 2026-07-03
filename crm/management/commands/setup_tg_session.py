from django.core.management.base import BaseCommand

from crm.tg_integration import setup_tg_account_session


class Command(BaseCommand):
    help = 'Setup Telegram account session via API ID/API Hash and phone code'

    def handle(self, *args, **options):
        self.stdout.write('Setting up Telegram account session...')
        setup_tg_account_session()
