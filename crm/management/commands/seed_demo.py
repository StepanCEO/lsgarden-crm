from django.core.management.base import BaseCommand

from crm.seed import seed_demo_data


class Command(BaseCommand):
    help = 'Populate the database with demo CRM data.'

    def handle(self, *args, **options):
        seed_demo_data()
        self.stdout.write(self.style.SUCCESS('Demo data seeded.'))
