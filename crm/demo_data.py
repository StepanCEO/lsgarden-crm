from __future__ import annotations

from django.contrib.auth.models import User

from .models import AuditEntry, Client, KnowledgeArticle, Message, NewsItem, Order, Product, Task


DEMO_CLIENT_SIGNATURES = [
    ('Елена Иванова', 'elena@example.com'),
    ('Светлана Кравцова', 'svetlana@example.com'),
    ('Андрей Мельников', 'andrey@studio.ru'),
    ('Антон Сергеев', 'anton@company.ru'),
    ('Марина Белова', 'marina@example.com'),
    ('Новый контакт', ''),
]

DEMO_MESSAGE_SIGNATURES = [
    ('Telegram', 'Елена', '+79990000001', 'Здравствуйте! Подскажите, есть ли фикус лирата в наличии?'),
    ('VK', 'Андрей', 'vk.com/andrey', 'Ищу подарок для офиса. Что посоветуете до 5000?'),
    ('WhatsApp', 'Менеджер', '+79990000005', 'Напоминаю про доставку сегодня с 18:00 до 20:00.'),
    ('Email', 'Антон', 'anton@company.ru', 'Пришлите, пожалуйста, КП на 24 растения для ресепшн.'),
    ('Авито', 'Марина', 'avito:green-loft', 'Работаете ли в выходные и как добраться до магазина?'),
]

DEMO_TASK_TITLES = [
    'Срочный ответ по остаткам фикуса лирата',
    'Ответить на ночную заявку от Flowwow',
    'Сверка остатков и лист "Ушедшего в производство"',
    'КП для корпоративного клиента Антона Сергева',
    'Авто follow-up по клиентам без ответа 48 часов',
    'Передать заявку по самовывозу в магазин',
]

DEMO_PRODUCT_NAMES = [
    'Фикус Лирата',
    'Монстера Адансона',
    'Орхидея Фаленопсис',
    'Керамический горшок 20 см',
    'Удобрение универсальное',
    'Букет "Весенний ветер"',
]

DEMO_KNOWLEDGE_TITLES = [
    'Стандарт ответа по наличию',
    'Скрипт для отсутствующего товара',
    'Корпоративный КП',
    'Приемка из 1С',
    'Чат-бот выходного дня',
    'Режим "Быстрый тест"',
    'Как приветствовать клиента',
    'Возражение по цене',
    'Работа с жалобой',
    'Что делать при расхождении остатков',
    'Как оформлять КП',
    'Ответ в нерабочее время',
]

DEMO_NEWS_TITLES = [
    'Импорт 1С обновлен',
    'Запущен бот выходного дня',
    'Добавлен быстрый тест',
]

DEMO_USERNAMES = [
    'front',
    'hybrid',
    'back',
    'content',
    'locomotive',
]


def purge_demo_records() -> dict[str, int]:
    demo_client_ids: list[int] = []
    for name, email in DEMO_CLIENT_SIGNATURES:
        qs = Client.objects.filter(name=name)
        if email:
            qs = qs.filter(email=email)
        else:
            qs = qs.filter(email='')
        demo_client_ids.extend(qs.values_list('id', flat=True))
    demo_client_ids = sorted(set(demo_client_ids))

    deleted_counts: dict[str, int] = {}

    message_qs = Message.objects.none()
    for channel, author, contact, text in DEMO_MESSAGE_SIGNATURES:
        message_qs = message_qs | Message.objects.filter(
            channel=channel,
            author_name=author,
            contact=contact,
            text=text,
        )
    deleted_counts['messages'] = message_qs.count()
    message_qs.delete()

    task_qs = Task.objects.filter(title__in=DEMO_TASK_TITLES)
    deleted_counts['tasks'] = task_qs.count()
    task_qs.delete()

    product_qs = Product.objects.filter(name__in=DEMO_PRODUCT_NAMES)
    deleted_counts['products'] = product_qs.count()
    product_qs.delete()

    knowledge_qs = KnowledgeArticle.objects.filter(title__in=DEMO_KNOWLEDGE_TITLES)
    deleted_counts['knowledge'] = knowledge_qs.count()
    knowledge_qs.delete()

    news_qs = NewsItem.objects.filter(title__in=DEMO_NEWS_TITLES)
    deleted_counts['news'] = news_qs.count()
    news_qs.delete()

    audit_qs = AuditEntry.objects.filter(action='Seed demo data')
    deleted_counts['audit'] = audit_qs.count()
    audit_qs.delete()

    order_qs = Order.objects.filter(client_id__in=demo_client_ids)
    deleted_counts['orders'] = order_qs.count()
    order_qs.delete()

    client_qs = Client.objects.filter(id__in=demo_client_ids)
    deleted_counts['clients'] = client_qs.count()
    client_qs.delete()

    user_qs = User.objects.filter(username__in=DEMO_USERNAMES)
    deleted_counts['users'] = user_qs.count()
    user_qs.delete()

    return deleted_counts
