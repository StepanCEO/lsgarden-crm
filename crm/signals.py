from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .seed import seed_demo_data


@receiver(post_migrate)
def populate_demo_data(sender, **kwargs):
    if sender.name == 'crm':
        seed_demo_data()
