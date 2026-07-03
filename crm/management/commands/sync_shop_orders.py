from django.core.management.base import BaseCommand

from crm.shop_sync import sync_orders, sync_wishlists


class Command(BaseCommand):
    help = 'Sync orders and wishlists from shop.lsgarden.ru (WooCommerce) into the CRM via Playwright'

    def add_arguments(self, parser):
        parser.add_argument('--orders-only', action='store_true')
        parser.add_argument('--wishlists-only', action='store_true')
        parser.add_argument('--limit', type=int, default=None, help='Limit number of orders/wishlists (smoke test)')

    def handle(self, *args, **options):
        limit = options['limit']
        if not options['wishlists_only']:
            self.stdout.write('Syncing shop orders...')
            result = sync_orders(limit=limit)
            self._report(result)

        if not options['orders_only']:
            self.stdout.write('Syncing shop wishlists...')
            result = sync_wishlists(limit=limit)
            self._report(result)

    def _report(self, result):
        status = result.pop('status', 'error')
        message = result.pop('message', '')
        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(f'OK — {message}'))
        else:
            self.stdout.write(self.style.ERROR(f'Error — {message}'))
        for key, value in result.items():
            self.stdout.write(f'  {key}: {value}')
