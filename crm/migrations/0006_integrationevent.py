from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0005_schedule_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='IntegrationEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=64)),
                ('event_type', models.CharField(max_length=64)),
                ('external_id', models.CharField(max_length=255)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('source', 'event_type', 'external_id')},
            },
        ),
    ]
