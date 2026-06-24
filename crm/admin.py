from django.contrib import admin

from .models import AuditEntry, Client, DictionaryEntry, EmployeeProfile, FraudEvent, KnowledgeArticle, Message, NewsItem, Order, Product, Task, UploadedFile


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'work_email', 'schedule')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'work_email')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'status', 'source', 'preferred_channel', 'updated_at')
    search_fields = ('name', 'phone', 'email', 'one_c_id')
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


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'client', 'status', 'total', 'created_at')
    search_fields = ('client__name', 'notes')
    list_filter = ('status',)


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'tag', 'file_size', 'uploaded_by', 'uploaded_at')
    search_fields = ('original_name', 'tag')
