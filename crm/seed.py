from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from .models import AuditEntry, Client, EmployeeProfile, KnowledgeArticle, Message, NewsItem, Order, Product, Task


def seed_demo_data():
    now = timezone.now()

    if Client.objects.exists():
        _seed_orders(now)
        return



    users = {}

    def create_user(username, password, first_name, last_name, role, email, code='', schedule=''):
        user, _ = User.objects.get_or_create(username=username, defaults={'email': email, 'first_name': first_name, 'last_name': last_name})
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.set_password(password)
        user.is_active = True
        if role == EmployeeProfile.Role.ADMIN:
            user.is_staff = True
            user.is_superuser = True
        user.save()
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={
                'role': role,
                'work_email': email,
                'access_code': code,
                'schedule': schedule,
            },
        )
        users[username] = user
        return user

    admin = create_user('admin', 'admin123', 'Алина', 'Морозова', EmployeeProfile.Role.ADMIN, 'admin@plants.local')
    create_user('front', 'front123', 'Мария', 'Лебедева', EmployeeProfile.Role.FRONT, 'maria@plants.local', '246810', '10:00-19:00')
    create_user('hybrid', 'hybrid123', 'Илья', 'Котов', EmployeeProfile.Role.HYBRID, 'ilya@plants.local', '246810', '09:30-18:30')
    create_user('back', 'back123', 'Сергей', 'Орлов', EmployeeProfile.Role.BACK, 'sergey@plants.local', '246810', '08:00-17:00')
    create_user('content', 'content123', 'Екатерина', 'Сахарова', EmployeeProfile.Role.CONTENT, 'katya@plants.local', '246810', '11:00-20:00')
    create_user('locomotive', 'drive123', 'Денис', 'Сорокин', EmployeeProfile.Role.LOCOMOTIVE, 'denis@plants.local', '246810', '08:30-17:30')

    clients = {
        'c1': Client.objects.create(
            name='Елена Иванова',
            phone='+79990000001',
            email='elena@example.com',
            one_c_id='1C-1001',
            source='Telegram',
            preferred_channel='Telegram',
            status=Client.Status.BUYER,
            tags=['доставка', 'орхидеи'],
            interests=['Комнатные растения', 'Суккуленты'],
            discount_cards=['VIP-12'],
            wish_list=['Фикус Лирата', 'Монстера Адансона'],
            wait_list=['Фикус Лирата'],
            purchases=[{'source': '1С', 'amount': 8900, 'at': (now - timedelta(days=6)).isoformat()}],
            bank_purchases=[{'amount': 4200, 'at': (now - timedelta(days=11)).isoformat(), 'matched': True}],
            internal_note='Зеленый список. Любит быструю доставку.',
            quality='A',
            green_list=True,
            history=[
                {'type': 'purchase', 'text': 'Покупка на 8 900 ₽ через 1С', 'at': (now - timedelta(days=6)).isoformat()},
                {'type': 'message', 'text': 'Запрос на фикус лирата', 'at': (now - timedelta(hours=1)).isoformat()},
            ],
        ),
        'c2': Client.objects.create(
            name='Светлана Кравцова',
            phone='+79990000002',
            email='svetlana@example.com',
            one_c_id='1C-1002',
            source='Сайт',
            preferred_channel='Email',
            status=Client.Status.LEAD,
            tags=['орхидеи'],
            interests=['Орхидеи', 'Удобрения'],
            wish_list=['Орхидея Фаленопсис'],
            wait_list=['Орхидея Фаленопсис'],
            internal_note='Качество лида: теплый. Перезвонить после обеда.',
            quality='B',
            history=[
                {'type': 'message', 'text': 'Задала вопрос по уходу за орхидеей', 'at': (now - timedelta(days=2, hours=2)).isoformat()},
            ],
        ),
        'c3': Client.objects.create(
            name='Андрей Мельников',
            phone='+79990000003',
            email='andrey@studio.ru',
            one_c_id='1C-1003',
            source='VK',
            preferred_channel='VK',
            status=Client.Status.LEAD,
            tags=['подарок', 'корпоратив'],
            interests=['Комнатные растения', 'Горшки'],
            discount_cards=['STUDIO-5'],
            wish_list=['Фикус Бенджамина', 'Кактус микс'],
            wait_list=['Фикус Бенджамина'],
            internal_note='Можно апсейл на уход и кашпо.',
            quality='A',
            green_list=True,
            history=[
                {'type': 'message', 'text': 'Ищет подарок для офиса до 5000 ₽', 'at': (now - timedelta(hours=2)).isoformat()},
            ],
        ),
        'c4': Client.objects.create(
            name='Антон Сергеев',
            phone='+79990000004',
            email='anton@company.ru',
            one_c_id='1C-1004',
            source='Email',
            preferred_channel='Email',
            status=Client.Status.BUYER,
            tags=['корпоратив'],
            interests=['Комнатные растения', 'Букеты'],
            discount_cards=['CORP-20'],
            wish_list=['Фиттония', 'Сансевиерия'],
            internal_note='Считать как опт. Нужен счет и КП.',
            quality='A',
            green_list=True,
            history=[
                {'type': 'purchase', 'text': 'Счет и поставка на 38 000 ₽', 'at': (now - timedelta(days=9, hours=3)).isoformat()},
            ],
        ),
        'c5': Client.objects.create(
            name='Марина Белова',
            phone='+79990000005',
            email='marina@example.com',
            source='Авито',
            preferred_channel='WhatsApp',
            status=Client.Status.BUYER,
            tags=['самовывоз'],
            interests=['Суккуленты', 'Горшки'],
            wish_list=['Алоэ вера'],
            purchases=[],
            bank_purchases=[{'amount': 2400, 'at': (now - timedelta(days=4)).isoformat(), 'matched': False}],
            internal_note='Проверить адрес самовывоза.',
            quality='B',
            history=[
                {'type': 'purchase', 'text': 'Неподтвержденная покупка через банк', 'at': (now - timedelta(days=4)).isoformat()},
            ],
        ),
        'c6': Client.objects.create(
            name='Новый контакт',
            phone='+79990000006',
            email='unknown@vk.local',
            source='VK',
            preferred_channel='VK',
            status=Client.Status.UNKNOWN,
            wish_list=['Композиция для стойки'],
            wait_list=['Композиция для стойки'],
            quality='C',
            history=[
                {'type': 'message', 'text': 'Новый контакт без телефона', 'at': (now - timedelta(days=1, hours=3)).isoformat()},
            ],
        ),
    }

    Message.objects.bulk_create([
        Message(channel='Telegram', direction=Message.Direction.INBOUND, client=clients['c1'], author_name='Елена', contact='+79990000001', text='Здравствуйте! Подскажите, есть ли фикус лирата в наличии?', unread=True, assigned_to=users['front']),
        Message(channel='VK', direction=Message.Direction.INBOUND, client=clients['c3'], author_name='Андрей', contact='vk.com/andrey', text='Ищу подарок для офиса. Что посоветуете до 5000?', unread=True, assigned_to=users['front']),
        Message(channel='WhatsApp', direction=Message.Direction.OUTBOUND, client=clients['c5'], author_name='Менеджер', contact='+79990000005', text='Напоминаю про доставку сегодня с 18:00 до 20:00.', unread=False, assigned_to=users['hybrid']),
        Message(channel='Email', direction=Message.Direction.INBOUND, client=clients['c4'], author_name='Антон', contact='anton@company.ru', text='Пришлите, пожалуйста, КП на 24 растения для ресепшн.', unread=True, assigned_to=users['content']),
        Message(channel='Авито', direction=Message.Direction.INBOUND, client=None, author_name='Марина', contact='avito:green-loft', text='Работаете ли в выходные и как добраться до магазина?', unread=True, assigned_to=users['front']),
    ])

    Task.objects.bulk_create([
        Task(title='Срочный ответ по остаткам фикуса лирата', priority=1, urgency='urgent', due_at=now + timedelta(minutes=45), status=Task.Status.NEW, origin=Task.Origin.LEADERSHIP, assigned_to=users['front'], client=clients['c1'], comments=[{'author': 'Руководитель', 'text': 'Нужен ответ до 12:30.', 'at': now.isoformat()}]),
        Task(title='Ответить на ночную заявку от Flowwow', priority=3, urgency='normal', due_at=now + timedelta(hours=1), status=Task.Status.IN_PROGRESS, origin=Task.Origin.CLIENTS, assigned_to=users['hybrid'], client=clients['c2'], comments=[{'author': 'Мария', 'text': 'Взято в работу.', 'at': now.isoformat()}]),
        Task(title='Сверка остатков и лист "Ушедшего в производство"', priority=4, urgency='system', due_at=now + timedelta(hours=3), status=Task.Status.WAITING, origin=Task.Origin.SYSTEM, assigned_to=users['back'], comments=[]),
        Task(title='КП для корпоративного клиента Антона Сергева', priority=2, urgency='normal', due_at=now + timedelta(days=1), status=Task.Status.NEW, origin=Task.Origin.INTERNAL, assigned_to=users['content'], client=clients['c4'], comments=[]),
        Task(title='Авто follow-up по клиентам без ответа 48 часов', priority=4, urgency='system', due_at=now + timedelta(hours=2), status=Task.Status.DONE, origin=Task.Origin.SYSTEM, assigned_to=users['locomotive'], client=clients['c2'], comments=[{'author': 'CRM', 'text': 'Напоминание отправлено.', 'at': now.isoformat()}]),
        Task(title='Передать заявку по самовывозу в магазин', priority=2, urgency='normal', due_at=now + timedelta(minutes=90), status=Task.Status.NEW, origin=Task.Origin.INTERNAL, assigned_to=users['front'], client=clients['c5'], comments=[]),
    ])

    Product.objects.bulk_create([
        Product(name='Фикус Лирата', parent='Комнатные растения', sku='PL-001', kind=Product.ProductKind.PLANT, stock=4, reserve=2, price=5890, in_production=1, status=Product.StockStatus.LOW),
        Product(name='Монстера Адансона', parent='Комнатные растения', sku='PL-002', kind=Product.ProductKind.PLANT, stock=10, reserve=1, price=3190, in_production=0, status=Product.StockStatus.OK),
        Product(name='Орхидея Фаленопсис', parent='Комнатные растения', sku='PL-003', kind=Product.ProductKind.PLANT, stock=2, reserve=1, price=2290, in_production=2, status=Product.StockStatus.CRITICAL),
        Product(name='Керамический горшок 20 см', parent='Горшки и кашпо', sku='AC-010', kind=Product.ProductKind.OTHER, stock=28, reserve=6, price=890, in_production=4, status=Product.StockStatus.OK),
        Product(name='Удобрение универсальное', parent='Удобрения', sku='AC-011', kind=Product.ProductKind.OTHER, stock=18, reserve=3, price=520, in_production=0, status=Product.StockStatus.OK),
        Product(name='Букет "Весенний ветер"', parent='Букеты', sku='BK-022', kind=Product.ProductKind.OTHER, stock=6, reserve=1, price=2790, in_production=2, status=Product.StockStatus.LOW),
    ])

    _seed_orders(now)

    KnowledgeArticle.objects.bulk_create([
        KnowledgeArticle(role='front', title='Стандарт ответа по наличию', body='Сначала проверяем остаток в 1С, затем даем краткий ответ, предлагая альтернативу и время доставки.'),
        KnowledgeArticle(role='hybrid', title='Скрипт для отсутствующего товара', body='Если товара нет, уточняем срочность, предлагаем под заказ и ставим follow-up через 24 часа.'),
        KnowledgeArticle(role='content', title='Корпоративный КП', body='Используем шаблон с ассортиментом, сроками, условиями оплаты и фото-референсами.'),
        KnowledgeArticle(role='back', title='Приемка из 1С', body='После импорта проверяем расхождения по остаткам, себестоимости и листу производства.'),
        KnowledgeArticle(role='locomotive', title='Чат-бот выходного дня', body='Сообщает адрес, график и предлагает оставить контакт для обратной связи в рабочее время.'),
        KnowledgeArticle(role='admin', title='Режим "Быстрый тест"', body='Администратор может заблокировать экран для мини-теста по ассортименту или стандартам сервиса.'),
        KnowledgeArticle(role='front', title='Как приветствовать клиента', body='Здороваемся, представляемся и сразу задаем один уточняющий вопрос по запросу.'),
        KnowledgeArticle(role='front', title='Возражение по цене', body='Сравниваем не просто цену, а ценность: свежесть, подбор, упаковку и доставку.'),
        KnowledgeArticle(role='hybrid', title='Работа с жалобой', body='Не спорим с клиентом, фиксируем проблему и сразу предлагаем конкретный следующий шаг.'),
        KnowledgeArticle(role='back', title='Что делать при расхождении остатков', body='Проверяем справочник, сверку из 1С и историю изменений, затем пересчитываем остатки.'),
        KnowledgeArticle(role='content', title='Как оформлять КП', body='В КП должны быть состав, цена, сроки, доставка, условия оплаты и контакты ответственного.'),
        KnowledgeArticle(role='locomotive', title='Ответ в нерабочее время', body='Сообщаем график и просим оставить номер телефона для обратной связи.'),
    ])

    NewsItem.objects.bulk_create([
        NewsItem(title='Импорт 1С обновлен', body='Новая синхронизация остатков и продаж проходит каждые 15 минут.', published_at=now - timedelta(hours=2)),
        NewsItem(title='Запущен бот выходного дня', body='Авито и VK отвечают по графику и адресу магазина.', published_at=now - timedelta(days=1, hours=2)),
        NewsItem(title='Добавлен быстрый тест', body='Администратор может блокировать рабочий экран для мини-экзамена.', published_at=now - timedelta(days=2)),
    ])

    AuditEntry.objects.create(
        actor=admin.get_full_name() or admin.username,
        ip_address='127.0.0.1',
        action='Seed demo data',
        before='empty',
        after='demo workspace populated',
    )


def _seed_orders(now):
    if Order.objects.exists():
        return
    c1 = Client.objects.filter(phone='+79990000001').first()
    c3 = Client.objects.filter(phone='+79990000003').first()
    c4 = Client.objects.filter(phone='+79990000004').first()
    if not (c1 and c3 and c4):
        return
    Order.objects.bulk_create([
        Order(client=c1, items=[{'name': 'Фикус Лирата', 'qty': 1, 'price': 5890, 'sku': 'PL-001'}, {'name': 'Керамический горшок 20 см', 'qty': 1, 'price': 890, 'sku': 'AC-010'}], total=6780, status=Order.Status.IN_PROGRESS, notes='Срочная доставка', history=[{'from': 'new', 'to': 'in_progress', 'at': now.isoformat()}]),
        Order(client=c3, items=[{'name': 'Фикус Бенджамина', 'qty': 3, 'price': 3200, 'sku': 'PL-005'}, {'name': 'Кактус микс', 'qty': 5, 'price': 450, 'sku': 'PL-008'}], total=11850, status=Order.Status.NEW, notes='Подарок для офиса', history=[]),
        Order(client=c4, items=[{'name': 'Сансевиерия', 'qty': 10, 'price': 1500, 'sku': 'PL-012'}, {'name': 'Фиттония', 'qty': 14, 'price': 980, 'sku': 'PL-013'}], total=28720, status=Order.Status.SHIPPED, notes='Опт, нужен чек', history=[{'from': 'new', 'to': 'assembled', 'at': (now - timedelta(hours=6)).isoformat()}, {'from': 'assembled', 'to': 'shipped', 'at': (now - timedelta(hours=2)).isoformat()}]),
    ])
