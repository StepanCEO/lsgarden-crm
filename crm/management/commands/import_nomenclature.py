from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from crm.one_c_import import import_nomenclature


class Command(BaseCommand):
    help = 'Import real product nomenclature from the 1C Excel workbook'

    def add_arguments(self, parser):
        parser.add_argument('--path', dest='path', help='Path to the .xlsx workbook')

    def handle(self, *args, **options):
        path = options.get('path') or getattr(settings, 'ONE_C_NOMENCLATURE_PATH', '')
        if not path:
            raise CommandError('Specify --path or set ONE_C_NOMENCLATURE_PATH')

        stats = import_nomenclature(path)
        self.stdout.write(
            self.style.SUCCESS(
                'Imported nomenclature: '
                f'created={stats.created}, updated={stats.updated}, '
                f'skipped={stats.skipped}, demo_deleted={stats.deleted_demo}'
            )
        )
