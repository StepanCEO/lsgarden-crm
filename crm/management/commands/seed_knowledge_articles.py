from django.core.management.base import BaseCommand

from crm.models import KnowledgeArticle
from crm.seed import KNOWLEDGE_ARTICLES_SEED


class Command(BaseCommand):
    help = 'Backfill KnowledgeArticle regulations into production (idempotent, safe to re-run)'

    def handle(self, *args, **options):
        created = 0
        for article in KNOWLEDGE_ARTICLES_SEED:
            _, was_created = KnowledgeArticle.objects.get_or_create(
                title=article['title'],
                defaults={'role': article['role'], 'body': article['body']},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f'Done — {created} new articles created, {len(KNOWLEDGE_ARTICLES_SEED) - created} already existed.'
        ))
