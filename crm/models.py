from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .contact_utils import normalize_email, normalize_phone


class EmployeeProfile(models.Model):
    class Role(models.TextChoices):
        FRONT = 'front', 'Фронт'
        BACK = 'back', 'Бек'
        HYBRID = 'hybrid', 'Гибрид'
        CONTENT = 'content', 'Контент'
        LOCOMOTIVE = 'locomotive', 'Локомотив'
        ADMIN = 'admin', 'Администратор'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.FRONT)
    work_email = models.EmailField(blank=True)
    access_code = models.CharField(max_length=16, blank=True)
    schedule = models.CharField(max_length=64, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)
    last_news_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'


class Client(models.Model):
    class Status(models.TextChoices):
        BUYER = 'buyer', 'Покупатель'
        LEAD = 'lead', 'Лид'
        UNKNOWN = 'unknown', 'Нераспознанный'

    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True, null=True, unique=True)
    last_name = models.CharField(max_length=128, blank=True)
    first_name = models.CharField(max_length=128, blank=True)
    patronymic = models.CharField(max_length=128, blank=True)
    birth_date = models.DateField(blank=True, null=True)
    second_phone = models.CharField(max_length=32, blank=True, null=True, unique=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    one_c_id = models.CharField(max_length=64, blank=True)
    first_purchase_at = models.DateTimeField(blank=True, null=True)
    vk_url = models.CharField(max_length=255, blank=True)
    telegram_url = models.CharField(max_length=255, blank=True)
    whatsapp_url = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=128, blank=True)
    source = models.CharField(max_length=64, blank=True)
    discount_card = models.CharField(max_length=128, blank=True)
    preferred_channel = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LEAD)
    tags = models.JSONField(default=list, blank=True)
    interests = models.JSONField(default=list, blank=True)
    discount_cards = models.JSONField(default=list, blank=True)
    contact_aliases = models.JSONField(default=list, blank=True)
    wish_list = models.JSONField(default=list, blank=True)
    wish_products = models.ManyToManyField('Product', related_name='wishers', blank=True)
    wait_list = models.JSONField(default=list, blank=True)
    purchases = models.JSONField(default=list, blank=True)
    bank_purchases = models.JSONField(default=list, blank=True)
    internal_note = models.TextField(blank=True)
    quality = models.CharField(max_length=8, blank=True, default='B')
    black_list = models.BooleanField(default=False)
    green_list = models.BooleanField(default=False)
    history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', 'name']

    def __str__(self) -> str:
        return self.name

    @property
    def full_name(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        normalized_phone = normalize_phone(self.phone or '')
        self.phone = normalized_phone or None

        normalized_second_phone = normalize_phone(self.second_phone or '')
        self.second_phone = normalized_second_phone or None
        if self.second_phone == self.phone:
            self.second_phone = None

        normalized_email = normalize_email(self.email or '')
        self.email = normalized_email or None

        self.discount_card = str(self.discount_card or '').strip()
        if self.discount_card:
            cards = {str(item or '').strip() for item in (self.discount_cards or [])}
            cards.discard('')
            cards.add(self.discount_card)
            self.discount_cards = sorted(cards)
        elif self.discount_cards:
            self.discount_card = str(self.discount_cards[0] or '').strip()

        super().save(*args, **kwargs)

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    @property
    def purchase_count(self) -> int:
        return len(self.purchases or [])

    @property
    def unread_message_count(self) -> int:
        return self.messages.filter(unread=True).count()


class Message(models.Model):
    class Direction(models.TextChoices):
        INBOUND = 'in', 'Входящее'
        OUTBOUND = 'out', 'Исходящее'

    channel = models.CharField(max_length=64)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    author_name = models.CharField(max_length=255)
    contact = models.CharField(max_length=255, blank=True)
    text = models.TextField()
    unread = models.BooleanField(default=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_messages')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.channel} · {self.author_name}'


class Task(models.Model):
    class Priority(models.IntegerChoices):
        P1 = 1, 'P1'
        P2 = 2, 'P2'
        P3 = 3, 'P3'
        P4 = 4, 'P4'

    class Status(models.TextChoices):
        NEW = 'new', 'Новая'
        IN_PROGRESS = 'in_progress', 'В работе'
        WAITING = 'waiting', 'Ожидание'
        DONE = 'done', 'Готово'

    class Origin(models.TextChoices):
        LEADERSHIP = 'От руководства', 'От руководства'
        INTERNAL = 'Внутренние', 'Внутренние'
        CLIENTS = 'Клиенты', 'Клиенты'
        SYSTEM = 'Системные', 'Системные'

    title = models.CharField(max_length=255)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.P3)
    urgency = models.CharField(max_length=32, default='normal')
    due_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    origin = models.CharField(max_length=64, choices=Origin.choices, default=Origin.INTERNAL)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks')
    comments = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'due_at', '-created_at']

    def __str__(self) -> str:
        return self.title


class Product(models.Model):
    class ProductKind(models.TextChoices):
        PLANT = 'plant', 'Комнатное растение'
        OTHER = 'other', 'Прочее'

    class StockStatus(models.TextChoices):
        OK = 'ok', 'В норме'
        LOW = 'low', 'Низкий'
        CRITICAL = 'critical', 'Критический'

    name = models.CharField(max_length=255)
    parent = models.CharField(max_length=255)
    sku = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=ProductKind.choices, default=ProductKind.PLANT)
    stock = models.PositiveIntegerField(default=0)
    reserve = models.PositiveIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    in_production = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=StockStatus.choices, default=StockStatus.OK)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['parent', 'name']

    def __str__(self) -> str:
        return self.name


class KnowledgeArticle(models.Model):
    role = models.CharField(max_length=32)
    title = models.CharField(max_length=255)
    body = models.TextField()

    class Meta:
        ordering = ['role', 'title']

    def __str__(self) -> str:
        return self.title


class NewsItem(models.Model):
    title = models.CharField(max_length=255)
    body = models.TextField()
    published_at = models.DateTimeField()

    class Meta:
        ordering = ['-published_at']

    def __str__(self) -> str:
        return self.title


class AuditEntry(models.Model):
    actor = models.CharField(max_length=255)
    ip_address = models.CharField(max_length=64)
    action = models.CharField(max_length=255)
    before = models.TextField(blank=True)
    after = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.actor}: {self.action}'


class FraudEvent(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fraud_events')
    ip_address = models.CharField(max_length=64)
    action = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.employee.username}: {self.action}'


class DictionaryEntry(models.Model):
    class DictType(models.TextChoices):
        TAG = 'tag', 'Тег'
        STATUS = 'status', 'Статус'
        INTEREST = 'interest', 'Интерес'

    dict_type = models.CharField(max_length=32, choices=DictType.choices)
    key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['dict_type', 'sort_order', 'key']
        unique_together = [('dict_type', 'key')]

    def __str__(self) -> str:
        return f'{self.get_dict_type_display()}: {self.label}'


class RolePermission(models.Model):
    class Resource(models.TextChoices):
        DASHBOARD = 'dashboard', 'Дашборд'
        INBOX = 'inbox', 'Единое окно'
        CLIENTS = 'clients', 'Клиенты'
        TASKS = 'tasks', 'Тикеты'
        PRODUCTS = 'products', 'Склад'
        KNOWLEDGE = 'knowledge', 'Обучение'
        ANALYTICS = 'analytics', 'Аналитика'
        ADMIN = 'admin', 'Админка'
        USERS = 'users', 'Пользователи'
        ORDERS = 'orders', 'Заказы'
        MESSAGES = 'messages', 'Сообщения'
        DICTIONARIES = 'dictionaries', 'Словари'
        FILES = 'files', 'Файлы'
        SCRIPTS = 'scripts', 'Скрипты'
        SCHEDULE = 'schedule', 'График'
        AUDIT = 'audit', 'Аудит'
        FRAUD = 'fraud', 'Антифрод'

    role = models.CharField(max_length=32, choices=EmployeeProfile.Role.choices)
    resource = models.CharField(max_length=32, choices=Resource.choices)
    can_read = models.BooleanField(default=True)
    can_write = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', 'resource']
        unique_together = [('role', 'resource')]

    def __str__(self) -> str:
        return f'{self.get_role_display()} · {self.get_resource_display()}'


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Новый'
        IN_PROGRESS = 'in_progress', 'В работе'
        ASSEMBLED = 'assembled', 'Собран'
        SHIPPED = 'shipped', 'Отправлен'
        DELIVERED = 'delivered', 'Завершён'
        CANCELLED = 'cancelled', 'Отменён'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='orders')
    items = models.JSONField(default=list, blank=True, help_text='Список {name, sku, qty, price}')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'Заказ №{self.pk} · {self.client.name}'


class ScriptRule(models.Model):
    trigger = models.CharField(max_length=255)
    answer = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['trigger']

    def __str__(self) -> str:
        return self.trigger


class ClockEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clock_events')
    clock_in = models.DateTimeField(default=timezone.now)
    clock_out = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-clock_in']

    def __str__(self) -> str:
        return f'{self.user.username} · {self.clock_in.strftime("%d.%m %H:%M")}'


class ScheduleSettings(models.Model):
    workday_start = models.TimeField(default='11:00')
    workday_end = models.TimeField(default='20:00')
    weekend_start = models.TimeField(default='10:00')
    weekend_end = models.TimeField(default='18:00')
    working_days = models.CharField(
        max_length=32,
        default='1,2,3,4,5',
        help_text='Дни работы: 0=пн, 1=вт, 2=ср, 3=чт, 4=пт, 5=сб, 6=вс',
    )
    auto_reply_vk_enabled = models.BooleanField(default=True)
    auto_reply_tg_enabled = models.BooleanField(default=False)
    auto_reply_emergency_disabled = models.BooleanField(
        'Аварийно отключить автоответ',
        default=False,
        help_text='Полностью отключает автоответ на всех каналах. Сбор сообщений при этом продолжается.',
    )
    ignored_author_names = models.TextField(
        blank=True,
        default='Secret Garden\nЛокация Secret Garden\nSecret-chat\nSecret Garden - своя атмосфера',
        help_text='Имена авторов, которым бот не должен отвечать. По одному на строку.',
    )
    address = models.CharField(max_length=512, blank=True, help_text='Адрес магазина')
    message_template = models.TextField(
        default='Добрый день! Вам отвечает Secret-бот. В данный момент сотрудники Локации отдыхают и не могут ответить на ваши вопросы. Мы обязательно ответим вам в наше рабочее время. Оффлайн-магазин имеет график работы: вт-сб, 11.00-20.00. вск-пн. выходной. Если вам нужны советы по негарантийному уходу за растением или помощь в подборе - напишите прямо сейчас в наш чат цветоводов. https://vk.me/join/DYjimx3ETkwCpNraK718A2MmNIlygdsebXM Вам обязательно помогут! Нажмите на колокольчик в шапке группы, чтобы не пропускать поставки и выгодные предложения! Основную информацию о нас можно найти на сайте lsgarden.ru. Растения онлайн с доставкой и подписка на растениях Голландии доступны в интернет-магазине shop.lsgarden.ru. Заказывайте!',
        help_text='{workday_start}, {workday_end}, {weekend_start}, {weekend_end}, {address} — подставляются автоматически',
    )

    class Meta:
        verbose_name = 'Настройки расписания'
        verbose_name_plural = 'Настройки расписания'

    def __str__(self):
        return f'Расписание: будни {self.workday_start}–{self.workday_end}, выходные {self.weekend_start}–{self.weekend_end}'

    def parsed_working_days(self) -> set[int]:
        result: set[int] = set()
        for item in str(self.working_days or '').split(','):
            item = item.strip()
            if item.isdigit():
                value = int(item)
                if 0 <= value <= 6:
                    result.add(value)
        return result

    def ignored_authors(self) -> set[str]:
        return {line.strip().casefold() for line in str(self.ignored_author_names or '').splitlines() if line.strip()}

    def is_channel_enabled(self, channel: str) -> bool:
        if self.auto_reply_emergency_disabled:
            return False
        normalized = str(channel or '').strip().casefold()
        if normalized == 'vk':
            return self.auto_reply_vk_enabled
        if normalized == 'telegram':
            return self.auto_reply_tg_enabled
        return False

    def should_send_auto_reply(self, channel: str, *, author_name: str = '', chat_type: str = 'private', is_outbound: bool = False) -> bool:
        if is_outbound:
            return False
        if not self.is_channel_enabled(channel):
            return False
        if str(chat_type or '').strip().lower() != 'private':
            return False
        if author_name and author_name.strip().casefold() in self.ignored_authors():
            return False
        return not self.is_open()

    def format_message(self):
        fmt = {
            'workday_start': self.workday_start.strftime('%H:%M') if self.workday_start else '09:00',
            'workday_end': self.workday_end.strftime('%H:%M') if self.workday_end else '21:00',
            'weekend_start': self.weekend_start.strftime('%H:%M') if self.weekend_start else '10:00',
            'weekend_end': self.weekend_end.strftime('%H:%M') if self.weekend_end else '18:00',
            'address': self.address or 'Москва, ул. Листовая, 17',
        }
        return self.message_template.format(**fmt)

    @staticmethod
    def is_open():
        now = timezone.localtime(timezone.now())
        weekday = now.weekday()
        try:
            sched = ScheduleSettings.objects.first()
            if not sched:
                return True
        except Exception:
            return True

        working_days = sched.parsed_working_days()
        if working_days and weekday not in working_days:
            return False
        current = now.time()
        start = sched.workday_start
        end = sched.workday_end
        return start <= current <= end

    @staticmethod
    def get_auto_reply():
        try:
            sched = ScheduleSettings.objects.first()
            if not sched:
                return ''
        except Exception:
            return ''
        return sched.format_message()


class UploadedFile(models.Model):
    original_name = models.CharField(max_length=512)
    s3_key = models.CharField(max_length=512, blank=True)
    s3_bucket = models.CharField(max_length=255, blank=True)
    s3_url = models.URLField(blank=True)
    file_size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=128, blank=True)
    tag = models.CharField(max_length=255, blank=True, help_text='Название товара или номер заказа')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self) -> str:
        return self.original_name


class IntegrationEvent(models.Model):
    source = models.CharField(max_length=64)
    event_type = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [('source', 'event_type', 'external_id')]

    def __str__(self) -> str:
        return f'{self.source}:{self.event_type}:{self.external_id}'


class ShiftAssignment(models.Model):
    """Сменный график: роль привязана к дате и сотруднику, а не к учётке.
    Например, «Анна 3-го июня — на фронте». Роль прав доступа (EmployeeProfile.role)
    при этом остаётся отдельной."""
    date = models.DateField()
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shift_assignments')
    role = models.CharField(max_length=32, choices=EmployeeProfile.Role.choices)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', 'role']
        unique_together = [('date', 'employee', 'role')]

    def __str__(self) -> str:
        who = self.employee.get_full_name() or self.employee.username
        return f'{self.date:%d.%m.%Y} · {who} · {self.get_role_display()}'


class TelegramLoginSession(models.Model):
    """Singleton-состояние флоу QR-логина Telegram-аккаунта (crm/tg_integration.py).
    Хранится в БД, а не в памяти процесса, т.к. gunicorn работает с несколькими
    воркерами и опрос статуса может попасть на другой воркер, чем тот, что держит
    открытое MTProto-соединение."""

    class Status(models.TextChoices):
        IDLE = 'idle', 'Не запущен'
        WAITING = 'waiting', 'Ждём скан QR'
        PASSWORD_REQUIRED = 'password_required', 'Нужен пароль 2FA'
        SUCCESS = 'success', 'Успешно'
        ERROR = 'error', 'Ошибка'
        EXPIRED = 'expired', 'Истекло время ожидания'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IDLE)
    qr_data_uri = models.TextField(blank=True, default='')
    message = models.CharField(max_length=255, blank=True, default='')
    pending_password = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'QR-логин Telegram'
        verbose_name_plural = 'QR-логин Telegram'

    def __str__(self) -> str:
        return f'TG QR-логин: {self.get_status_display()}'

    @classmethod
    def load(cls) -> 'TelegramLoginSession':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
