from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


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

    def __str__(self) -> str:
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'


class Client(models.Model):
    class Status(models.TextChoices):
        BUYER = 'buyer', 'Покупатель'
        LEAD = 'lead', 'Лид'
        UNKNOWN = 'unknown', 'Нераспознанный'

    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=32, blank=True, null=True, unique=True)
    email = models.EmailField(blank=True)
    one_c_id = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=64, blank=True)
    preferred_channel = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LEAD)
    tags = models.JSONField(default=list, blank=True)
    interests = models.JSONField(default=list, blank=True)
    discount_cards = models.JSONField(default=list, blank=True)
    wish_list = models.JSONField(default=list, blank=True)
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
