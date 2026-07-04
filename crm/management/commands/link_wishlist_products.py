from django.core.management.base import BaseCommand

from crm.models import Client, Product


class Command(BaseCommand):
    help = 'Привязать существующие вишлисты клиентов к карточкам товаров (создать недостающие).'

    def _find_or_create(self, name: str, created_counter: list):
        name = (name or '').strip()
        if not name:
            return None
        product = Product.objects.filter(name__iexact=name).first()
        if product:
            return product
        created_counter[0] += 1
        return Product.objects.create(
            name=name, parent=name, sku='', kind=Product.ProductKind.PLANT, price=0,
        )

    def handle(self, *args, **options):
        clients = Client.objects.exclude(wish_list=[])
        created = [0]
        linked = 0
        touched = 0
        for client in clients:
            names = [str(n).strip() for n in (client.wish_list or []) if str(n).strip()]
            if not names:
                continue
            products = [p for p in (self._find_or_create(n, created) for n in names) if p]
            if products:
                client.wish_products.add(*products)
                linked += len(products)
                touched += 1
        self.stdout.write(self.style.SUCCESS(
            f'Готово: обработано клиентов {touched}, связей добавлено {linked}, новых товаров создано {created[0]}.'
        ))
