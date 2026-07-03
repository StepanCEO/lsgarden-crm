import io
import logging
import os
import subprocess
import tempfile
from datetime import datetime

import boto3
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backup PostgreSQL DB to Yandex Object Storage (S3)'

    def handle(self, *args, **options):
        db_name = os.getenv('POSTGRES_DB', 'plant_crm')
        db_user = os.getenv('POSTGRES_USER', 'plant_crm')
        db_host = os.getenv('POSTGRES_HOST', 'db')
        db_port = os.getenv('POSTGRES_PORT', '5432')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{db_name}_{timestamp}.sql.gz'
        s3_key = f'db_backups/{filename}'

        with tempfile.NamedTemporaryFile(suffix='.sql.gz', delete=False) as tmp:
            dump_path = tmp.name

        try:
            db_password = os.getenv('POSTGRES_PASSWORD', 'plant_crm')
            pg_env = {**os.environ, 'PGPASSWORD': db_password}
            pg_dump_cmd = [
                'pg_dump',
                f'--dbname=postgresql://{db_user}@{db_host}:{db_port}/{db_name}',
                '--no-owner',
                '--no-acl',
            ]
            with open(dump_path, 'wb') as f:
                proc = subprocess.Popen(pg_dump_cmd, stdout=subprocess.PIPE, env=pg_env)
                gzip_proc = subprocess.Popen(['gzip'], stdin=proc.stdout, stdout=f)
                proc.stdout.close()
                gzip_proc.communicate()
                proc.wait()

            if proc.returncode != 0 or gzip_proc.returncode != 0:
                logger.error('pg_dump failed')
                self.stdout.write(self.style.ERROR('Backup failed: pg_dump error'))
                return

            client = boto3.client(
                's3',
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                region_name=settings.AWS_S3_REGION_NAME,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )

            with open(dump_path, 'rb') as f:
                client.upload_fileobj(f, settings.AWS_STORAGE_BUCKET_NAME, s3_key)

            file_size = os.path.getsize(dump_path)
            self.stdout.write(self.style.SUCCESS(
                f'Backup {filename} ({file_size / 1024:.0f} KB) uploaded to s3://{settings.AWS_STORAGE_BUCKET_NAME}/{s3_key}'
            ))
            logger.info('DB backup uploaded to S3: %s', s3_key)

        except Exception as e:
            logger.error('Backup failed: %s', e)
            self.stdout.write(self.style.ERROR(f'Backup failed: {e}'))
        finally:
            if os.path.exists(dump_path):
                os.unlink(dump_path)
