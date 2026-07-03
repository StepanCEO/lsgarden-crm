from django.contrib import admin

from .models import AuditEntry, Client, DictionaryEntry, EmployeeProfile, FraudEvent, KnowledgeArticle, Message, NewsItem, Order, Product, RolePermission, ScheduleSettings, ShiftAssignment, Task, UploadedFile


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'work_email', 'schedule')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'work_email')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'second_phone', 'email', 'status', 'source', 'preferred_channel', 'updated_at')
    search_fields = ('name', 'last_name', 'first_name', 'patronymic', 'phone', 'second_phone', 'email', 'one_c_id', 'vk_url', 'telegram_url', 'whatsapp_url', 'contact_aliases')
    list_filter = ('status', 'source', 'preferred_channel', 'green_list', 'black_list')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('channel', 'direction', 'author_name', 'client', 'unread', 'created_at')
    search_fields = ('author_name', 'contact', 'text')
    list_filter = ('channel', 'direction', 'unread')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'priority', 'status', 'origin', 'assigned_to', 'due_at')
    search_fields = ('title',)
    list_filter = ('priority', 'status', 'origin')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'sku', 'kind', 'stock', 'reserve', 'price', 'status')
    search_fields = ('name', 'parent', 'sku')
    list_filter = ('kind', 'status')


@admin.register(KnowledgeArticle)
class KnowledgeArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'role')
    search_fields = ('title', 'body')
    list_filter = ('role',)


@admin.register(NewsItem)
class NewsItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'published_at')
    search_fields = ('title', 'body')


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ('actor', 'ip_address', 'action', 'created_at')
    search_fields = ('actor', 'action', 'before', 'after')
    readonly_fields = ('actor', 'ip_address', 'action', 'before', 'after', 'created_at')


@admin.register(FraudEvent)
class FraudEventAdmin(admin.ModelAdmin):
    list_display = ('employee', 'action', 'ip_address', 'blocked', 'created_at')
    list_filter = ('blocked', 'action')


@admin.register(DictionaryEntry)
class DictionaryEntryAdmin(admin.ModelAdmin):
    list_display = ('dict_type', 'key', 'label', 'sort_order')
    list_filter = ('dict_type',)
    search_fields = ('key', 'label')


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('role', 'resource', 'can_read', 'can_write', 'can_delete', 'updated_at')
    list_filter = ('role', 'resource', 'can_read', 'can_write', 'can_delete')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'status', 'total', 'created_at')
    search_fields = ('client__name', 'notes')
    list_filter = ('status',)


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'tag', 'file_size', 'uploaded_by', 'uploaded_at')
    search_fields = ('original_name', 'tag')


@admin.register(ScheduleSettings)
class ScheduleSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'workday_start',
        'workday_end',
        'working_days',
        'auto_reply_vk_enabled',
        'auto_reply_tg_enabled',
        'auto_reply_emergency_disabled',
        'reply_mode',
        'address',
    )
    list_filter = ('auto_reply_emergency_disabled', 'auto_reply_vk_enabled', 'auto_reply_tg_enabled')
    fieldsets = (
        ('Рабочее время', {
            'fields': ('working_days', 'workday_start', 'workday_end', 'weekend_start', 'weekend_end'),
        }),
        ('Управление автоответом', {
            'fields': (
                'auto_reply_emergency_disabled',
                'auto_reply_vk_enabled',
                'auto_reply_tg_enabled',
                'ignored_author_names',
            ),
            'description': 'Аварийное отключение останавливает только автоответ. Сбор сообщений продолжает работать.',
        }),
        ('Сообщение', {
            'fields': ('address', 'message_template'),
        }),
    )

    @admin.display(description='Режим')
    def reply_mode(self, obj):
        return 'Аварийно отключен' if obj.auto_reply_emergency_disabled else 'По расписанию'

    def has_add_permission(self, request):
        if ScheduleSettings.objects.exists():
            return False
        return super().has_add_permission(request)


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ('date', 'employee', 'role', 'note')
    list_filter = ('role', 'date')
    search_fields = ('employee__username', 'employee__first_name', 'employee__last_name', 'note')
    date_hierarchy = 'date'
