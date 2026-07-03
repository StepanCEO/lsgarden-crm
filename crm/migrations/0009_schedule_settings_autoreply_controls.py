# Generated manually for per-channel auto-reply controls.

from django.db import migrations, models


CUSTOM_MESSAGE = (
    'Добрый день! Вам отвечает Secret-бот. В данный момент сотрудники Локации отдыхают и не могут ответить на ваши вопросы. '
    'Мы обязательно ответим вам в наше рабочее время. Оффлайн-магазин имеет график работы: вт-сб, 11.00-20.00. '
    'вск-пн. выходной. Если вам нужны советы по негарантийному уходу за растением или помощь в подборе - напишите прямо сейчас '
    'в наш чат цветоводов. https://vk.me/join/DYjimx3ETkwCpNraK718A2MmNIlygdsebXM Вам обязательно помогут! Нажмите на колокольчик '
    'в шапке группы, чтобы не пропускать поставки и выгодные предложения! Основную информацию о нас можно найти на сайте lsgarden.ru. '
    'Растения онлайн с доставкой и подписка на растениях Голландии доступны в интернет-магазине shop.lsgarden.ru. Заказывайте!'
)


def forwards(apps, schema_editor):
    ScheduleSettings = apps.get_model('crm', 'ScheduleSettings')
    for sched in ScheduleSettings.objects.all():
        sched.workday_start = '11:00'
        sched.workday_end = '20:00'
        sched.working_days = '1,2,3,4,5'
        sched.auto_reply_vk_enabled = True
        sched.auto_reply_tg_enabled = False
        if not (sched.ignored_author_names or '').strip():
            sched.ignored_author_names = 'Secret Garden\nЛокация Secret Garden\nSecret-chat\nSecret Garden - своя атмосфера'
        sched.message_template = CUSTOM_MESSAGE
        sched.save(update_fields=[
            'workday_start', 'workday_end', 'working_days',
            'auto_reply_vk_enabled', 'auto_reply_tg_enabled',
            'ignored_author_names', 'message_template',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0008_client_schema_from_spec'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedulesettings',
            name='auto_reply_tg_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='schedulesettings',
            name='auto_reply_vk_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='schedulesettings',
            name='ignored_author_names',
            field=models.TextField(blank=True, default='Secret Garden\nЛокация Secret Garden\nSecret-chat\nSecret Garden - своя атмосфера', help_text='Имена авторов, которым бот не должен отвечать. По одному на строку.'),
        ),
        migrations.AddField(
            model_name='schedulesettings',
            name='working_days',
            field=models.CharField(default='1,2,3,4,5', help_text='Дни работы: 0=пн, 1=вт, 2=ср, 3=чт, 4=пт, 5=сб, 6=вс', max_length=32),
        ),
        migrations.AlterField(
            model_name='schedulesettings',
            name='message_template',
            field=models.TextField(default=CUSTOM_MESSAGE, help_text='{workday_start}, {workday_end}, {weekend_start}, {weekend_end}, {address} — подставляются автоматически'),
        ),
        migrations.AlterField(
            model_name='schedulesettings',
            name='workday_end',
            field=models.TimeField(default='20:00'),
        ),
        migrations.AlterField(
            model_name='schedulesettings',
            name='workday_start',
            field=models.TimeField(default='11:00'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
