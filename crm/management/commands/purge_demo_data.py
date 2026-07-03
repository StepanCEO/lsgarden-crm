from django.core.management.base import BaseCommand

from crm.demo_data import purge_demo_records


class Command(BaseCommand):
    help = 'Remove demo showcase data seeded by crm.seed from the database'

    def handle(self, *args, **options):
        deleted_counts = purge_demo_records()
        self.stdout.write(self.style.SUCCESS(f'Purged demo data: {deleted_counts}'))
