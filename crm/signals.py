import sys

from django.conf import settings
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .seed import seed_demo_data


@receiver(post_migrate)
def populate_demo_data(sender, **kwargs):
    if sender.name != 'crm':
        return
    if not getattr(settings, 'CRM_AUTO_SEED_DEMO', False):
        return
    if 'test' in sys.argv:
        return
    seed_demo_data()
