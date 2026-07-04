from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import random
import re
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from itertools import combinations

import boto3
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .contact_utils import (
    compose_client_name,
    normalize_contact_alias as shared_normalize_contact_alias,
    normalize_email as shared_normalize_email,
    normalize_phone as shared_normalize_phone,
    parse_contact_aliases as shared_parse_contact_aliases,
    sanitize_client_contacts,
    split_client_name,
)
from .models import AuditEntry, Client, ClockEvent, DictionaryEntry, EmployeeProfile, FraudEvent, IntegrationEvent, KnowledgeArticle, Message, NewsItem, Order, Product, RolePermission, ScheduleSettings, ScriptRule, ShiftAssignment, Task, UploadedFile
from .one_c_import import import_nomenclature

logger = logging.getLogger(__name__)

ROLE_SECTIONS = {
    EmployeeProfile.Role.ADMIN: ['dashboard', 'inbox', 'clients', 'tasks', 'products', 'knowledge', 'analytics', 'admin'],
    EmployeeProfile.Role.FRONT: ['dashboard', 'inbox', 'clients', 'tasks', 'knowledge', 'analytics'],
    EmployeeProfile.Role.BACK: ['dashboard', 'inbox', 'tasks', 'products', 'knowledge', 'analytics'],
    EmployeeProfile.Role.HYBRID: ['dashboard', 'inbox', 'clients', 'tasks', 'products', 'knowledge', 'analytics'],
    EmployeeProfile.Role.CONTENT: ['dashboard', 'inbox', 'knowledge', 'analytics'],
    EmployeeProfile.Role.LOCOMOTIVE: ['dashboard', 'inbox', 'tasks', 'products', 'knowledge', 'analytics'],
}

NAV_LABELS = {
    'dashboard': 'Дашборд',
    'inbox': 'Единое окно',
    'clients': 'Клиенты',
    'tasks': 'Тикеты',
    'products': 'Склад и 1С',
    'knowledge': 'Обучение',
    'analytics': 'Аналитика',
    'admin': 'Админка',
}

PAGE_TO_RESOURCE = {
    'dashboard': RolePermission.Resource.DASHBOARD,
    'inbox': RolePermission.Resource.INBOX,
    'clients': RolePermission.Resource.CLIENTS,
    'tasks': RolePermission.Resource.TASKS,
    'products': RolePermission.Resource.PRODUCTS,
    'knowledge': RolePermission.Resource.KNOWLEDGE,
    'analytics': RolePermission.Resource.ANALYTICS,
    'admin': RolePermission.Resource.ADMIN,
}

ALL_PERMISSION_RESOURCES = [choice for choice, _ in RolePermission.Resource.choices]

DEFAULT_ROLE_PERMISSIONS = {
    EmployeeProfile.Role.ADMIN: {
        resource: {'read': True, 'write': True, 'delete': True}
        for resource in ALL_PERMISSION_RESOURCES
    },
    EmployeeProfile.Role.FRONT: {
        RolePermission.Resource.DASHBOARD: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.INBOX: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.CLIENTS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.TASKS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.KNOWLEDGE: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ANALYTICS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ORDERS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.MESSAGES: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.PRODUCTS: {'read': True, 'write': False, 'delete': False},
    },
    EmployeeProfile.Role.BACK: {
        RolePermission.Resource.DASHBOARD: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.INBOX: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.TASKS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.PRODUCTS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.KNOWLEDGE: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ANALYTICS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ORDERS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.MESSAGES: {'read': True, 'write': True, 'delete': False},
    },
    EmployeeProfile.Role.HYBRID: {
        RolePermission.Resource.DASHBOARD: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.INBOX: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.CLIENTS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.TASKS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.PRODUCTS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.KNOWLEDGE: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ANALYTICS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ORDERS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.MESSAGES: {'read': True, 'write': True, 'delete': False},
    },
    EmployeeProfile.Role.CONTENT: {
        RolePermission.Resource.DASHBOARD: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.INBOX: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.KNOWLEDGE: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.ANALYTICS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.MESSAGES: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.SCRIPTS: {'read': True, 'write': True, 'delete': False},
    },
    EmployeeProfile.Role.LOCOMOTIVE: {
        RolePermission.Resource.DASHBOARD: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.INBOX: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.TASKS: {'read': True, 'write': True, 'delete': False},
        RolePermission.Resource.PRODUCTS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.KNOWLEDGE: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.ANALYTICS: {'read': True, 'write': False, 'delete': False},
        RolePermission.Resource.MESSAGES: {'read': True, 'write': True, 'delete': False},
    },
}

ACTION_PERMISSIONS = {
    'create_client': (RolePermission.Resource.CLIENTS, 'write'),
    'create_task': (RolePermission.Resource.TASKS, 'write'),
    'send_message': (RolePermission.Resource.MESSAGES, 'write'),
    'sync_1c': (RolePermission.Resource.PRODUCTS, 'write'),
    'poll_avito': (RolePermission.Resource.MESSAGES, 'write'),
    'poll_manual_messages': (RolePermission.Resource.MESSAGES, 'write'),
    'start_avito_web_login': (RolePermission.Resource.MESSAGES, 'write'),
    'confirm_avito_web_login': (RolePermission.Resource.MESSAGES, 'write'),
    'poll_vk': (RolePermission.Resource.MESSAGES, 'write'),
    'poll_tg': (RolePermission.Resource.MESSAGES, 'write'),
    'sync_bank': (RolePermission.Resource.CLIENTS, 'write'),
    'merge_clients': (RolePermission.Resource.CLIENTS, 'write'),
    'create_user': (RolePermission.Resource.USERS, 'write'),
    'update_user': (RolePermission.Resource.USERS, 'write'),
    'toggle_user': (RolePermission.Resource.USERS, 'write'),
    'delete_user': (RolePermission.Resource.USERS, 'delete'),
    'import_csv': (RolePermission.Resource.USERS, 'write'),
    'generate_follow_up': (RolePermission.Resource.TASKS, 'write'),
    'quick_test_start': (RolePermission.Resource.KNOWLEDGE, 'write'),
    'quick_test_answer': (RolePermission.Resource.KNOWLEDGE, 'read'),
    'quick_test_reset': (RolePermission.Resource.KNOWLEDGE, 'read'),
    'simulate_incoming': (RolePermission.Resource.MESSAGES, 'write'),
    'dict_add': (RolePermission.Resource.DICTIONARIES, 'write'),
    'dict_update': (RolePermission.Resource.DICTIONARIES, 'write'),
    'dict_delete': (RolePermission.Resource.DICTIONARIES, 'delete'),
    'upload_file': (RolePermission.Resource.FILES, 'write'),
    'wishlist_trigger': (RolePermission.Resource.TASKS, 'write'),
    'save_article': (RolePermission.Resource.KNOWLEDGE, 'write'),
    'delete_article': (RolePermission.Resource.KNOWLEDGE, 'delete'),
    'clock_in': (RolePermission.Resource.DASHBOARD, 'read'),
    'clock_out': (RolePermission.Resource.DASHBOARD, 'read'),
    'reassign_task': (RolePermission.Resource.TASKS, 'write'),
    'export_analytics_csv': (RolePermission.Resource.ANALYTICS, 'read'),
    'export_clients_csv': (RolePermission.Resource.CLIENTS, 'read'),
    'export_products_csv': (RolePermission.Resource.PRODUCTS, 'read'),
    'save_schedule': (RolePermission.Resource.SCHEDULE, 'write'),
    'save_script': (RolePermission.Resource.SCRIPTS, 'write'),
    'delete_script': (RolePermission.Resource.SCRIPTS, 'delete'),
    'create_order': (RolePermission.Resource.ORDERS, 'write'),
    'update_order_status': (RolePermission.Resource.ORDERS, 'write'),
    'edit_order': (RolePermission.Resource.ORDERS, 'write'),
    'delete_order': (RolePermission.Resource.ORDERS, 'delete'),
    'save_permission': (RolePermission.Resource.ADMIN, 'write'),
    'add_shift': (RolePermission.Resource.ADMIN, 'write'),
    'delete_shift': (RolePermission.Resource.ADMIN, 'delete'),
}

DEFAULT_KNOWLEDGE_LIBRARY = [
    {'role': 'front', 'title': 'Приветствие клиента', 'body': 'Сначала здороваемся, уточняем запрос, канал и желаемый срок. Не перегружаем ответ лишними словами.'},
    {'role': 'front', 'title': 'Если товара нет в наличии', 'body': 'Извиняемся, говорим, что сейчас товара нет, предлагаем под заказ, альтернативу или похожий вариант, а затем фиксируем follow-up.'},
    {'role': 'front', 'title': 'Как отвечать по доставке', 'body': 'Сразу называем доступное окно доставки, стоимость и условия. Если нужно уточнение адреса, задаём один короткий вопрос.'},
    {'role': 'front', 'title': 'Как работать с возражением по цене', 'body': 'Сначала подтверждаем запрос, потом объясняем ценность: свежесть, размер, подбор, упаковка и сервис.'},
    {'role': 'hybrid', 'title': 'Перевод клиента на другой канал', 'body': 'Если вопрос требует фото, счета или долгого согласования, переводим клиента в удобный канал и фиксируем это в карточке.'},
    {'role': 'hybrid', 'title': 'Работа с жалобой', 'body': 'Сначала принимаем эмоцию клиента, потом извиняемся, фиксируем проблему и сразу предлагаем конкретное действие.'},
    {'role': 'content', 'title': 'Сценарий для корпоративного клиента', 'body': 'Уточняем бюджет, срок, формат доставки, состав и нужен ли счёт. После этого собираем КП.'},
    {'role': 'back', 'title': 'Синхронизация с 1С', 'body': 'Проверяем остатки, цены и расхождения. Если есть конфликт, сначала корректируем справочник, потом запускаем повторный импорт.'},
    {'role': 'back', 'title': 'Товар в производстве', 'body': 'Если товар ещё не готов, отмечаем его в листе производства и указываем ожидаемую дату поступления.'},
    {'role': 'locomotive', 'title': 'Ответы в нерабочее время', 'body': 'Сообщаем график, адрес и предлагаем оставить контакт, чтобы вернуться к вопросу в рабочее время.'},
    {'role': 'admin', 'title': 'Как проводить быстрый тест', 'body': 'Администратор запускает тест, сотрудник отвечает коротко и по делу, после чего система фиксирует результат.'},
]

DEFAULT_AUTO_SCRIPTS = [
    {'trigger': 'нет в наличии', 'answer': 'Извините, сейчас этого товара нет в наличии. Могу предложить похожий вариант или оформить под заказ.'},
    {'trigger': 'доставка', 'answer': 'Подскажите адрес, и я сразу сориентирую по времени и стоимости доставки.'},
    {'trigger': 'адрес', 'answer': 'Мы находимся по адресу: Москва, ул. Листовая, 17. Работаем ежедневно с 9:00 до 21:00.'},
    {'trigger': 'цена', 'answer': 'Сейчас уточню актуальную цену и сразу вернусь с ответом.'},
    {'trigger': 'под заказ', 'answer': 'Да, можем оформить под заказ. Напишите удобный срок, и мы уточним наличие у поставщика.'},
]

QUIZ_BANK = [
    {
        'question': 'Какой код нужен сотруднику для входа?',
        'answer': '246810',
        'acceptable': ['246810'],
    },
    {
        'question': 'Что отвечаем, если товара нет в наличии?',
        'answer': 'Извините, сейчас этого товара нет в наличии. Могу предложить похожий вариант или оформить под заказ.',
        'acceptable': ['под заказ', 'извините', 'предложить похожий', 'могу предложить вам другое', 'нет в наличии'],
    },
    {
        'question': 'Что делаем, если клиент просит доставку?',
        'answer': 'Уточняем адрес, время и сразу называем доступное окно доставки.',
        'acceptable': ['уточняем адрес', 'время', 'окно доставки', 'доставку'],
    },
    {
        'question': 'Что делать, если клиент жалуется?',
        'answer': 'Сначала извиняемся, затем фиксируем проблему и предлагаем конкретное решение.',
        'acceptable': ['извиняемся', 'фиксируем проблему', 'предлагаем решение', 'жалуется'],
    },
]


def _fmt_money(value):
    return f"{int(value or 0):,}".replace(',', ' ') + ' ₽'


def _fmt_dt(value):
    if not value:
        return ''
    return timezone.localtime(value).strftime('%d.%m, %H:%M')


RUSSIAN_MONTHS = {
    'января': 1,
    'февраля': 2,
    'марта': 3,
    'апреля': 4,
    'мая': 5,
    'июня': 6,
    'июля': 7,
    'августа': 8,
    'сентября': 9,
    'октября': 10,
    'ноября': 11,
    'декабря': 12,
}


def _status_class(value):
    mapping = {
        'buyer': 'good',
        'lead': 'warn',
        'unknown': 'info',
        'done': 'good',
        'in_progress': 'info',
        'waiting': 'warn',
        'new': 'info',
        'critical': 'danger',
        'low': 'warn',
        'ok': 'good',
    }
    return mapping.get(value, 'info')


def _normalize_phone(value: str) -> str:
    return shared_normalize_phone(value)


def _humanize_name_part(value: str) -> str:
    if not value:
        return ''
    parts = [item for item in value.replace('.', '').split('-') if item]
    humanized = '-'.join(part[:1].upper() + part[1:].lower() for part in parts)
    return humanized


def _normalize_payer_name(value: str) -> str:
    tokens = [token for token in re.split(r'\s+', str(value or '').strip()) if token]
    if not tokens:
        return 'Неизвестный клиент'

    if len(tokens) >= 3:
        first_name = _humanize_name_part(tokens[0])
        middle_name = _humanize_name_part(tokens[1])
        last_initial = tokens[2].replace('.', '')[:1].upper()
        if last_initial:
            return f'{first_name} {middle_name} {last_initial}.'
        return f'{first_name} {middle_name}'

    return ' '.join(_humanize_name_part(token) for token in tokens)


def _parse_bank_amount(value: str) -> float:
    cleaned = str(value or '').replace('\xa0', '').replace('₽', '').replace(' ', '').replace('+', '')
    cleaned = cleaned.replace(',', '.')
    cleaned = re.sub(r'[^0-9.\-]', '', cleaned)
    return float(cleaned or '0')


def _parse_bank_timestamp(value: str) -> datetime | None:
    raw_value = str(value or '').strip()
    if not raw_value:
        return None

    match = re.fullmatch(r'(\d{1,2})\s+([А-Яа-яЁё]+)\s+(\d{4}),\s*(\d{1,2}):(\d{2})', raw_value)
    if match:
        day, month_name, year, hour, minute = match.groups()
        month = RUSSIAN_MONTHS.get(month_name.lower())
        if month:
            parsed = datetime(int(year), month, int(day), int(hour), int(minute))
            return timezone.make_aware(parsed, timezone.get_current_timezone())

    for fmt in ('%d.%m.%Y %H:%M', '%d.%m.%Y, %H:%M', '%Y-%m-%d %H:%M:%S'):
        try:
            parsed = datetime.strptime(raw_value, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue

    return None


def _decode_uploaded_csv(uploaded_file) -> str:
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)
    for encoding in ('utf-8-sig', 'utf-8', 'cp1251', 'cp866'):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode('latin-1')


def _existing_bank_import_keys() -> set[str]:
    keys: set[str] = set()
    for client in Client.objects.all().only('bank_purchases'):
        for item in client.bank_purchases or []:
            key = item.get('import_key')
            if key:
                keys.add(key)
    return keys


def _find_client_by_normalized_phone(phone: str) -> Client | None:
    if not phone:
        return None
    for client in Client.objects.all():
        if _normalize_phone(client.phone or '') == phone or _normalize_phone(client.second_phone or '') == phone:
            return client
    return None


def _build_bank_import_key(phone: str, amount: float, paid_at: datetime | None, payer_name: str, raw_date: str) -> str:
    timestamp = paid_at.isoformat() if paid_at else raw_date.strip()
    return f'{phone}|{amount:.2f}|{timestamp}|{payer_name}'


def _normalize_email(value: str) -> str:
    return shared_normalize_email(value)


def _normalize_contact_alias(value: str) -> str:
    return shared_normalize_contact_alias(value)


def _parse_contact_aliases(value: str | list[str] | tuple[str, ...]) -> list[str]:
    return shared_parse_contact_aliases(value)


def _client_contact_aliases(client: Client) -> set[str]:
    aliases = set(_parse_contact_aliases(client.contact_aliases or []))
    if client.phone:
        aliases.add(f'phone:{_normalize_phone(client.phone)}')
    if client.second_phone:
        aliases.add(f'phone:{_normalize_phone(client.second_phone)}')
    if client.email:
        aliases.add(f'email:{_normalize_email(client.email)}')
    return {alias for alias in aliases if alias}


def _touch_client_aliases(client: Client, *values: str, save: bool = True) -> list[str]:
    aliases = _client_contact_aliases(client)
    aliases.update(_parse_contact_aliases(list(values)))
    normalized = sorted(aliases)
    client.contact_aliases = normalized
    if save and client.pk:
        client.save(update_fields=['contact_aliases', 'updated_at'])
    return normalized


def _find_client_by_alias_match(aliases: set[str], exclude_pk: int | None = None) -> Client | None:
    if not aliases:
        return None
    candidates = Client.objects.exclude(pk=exclude_pk) if exclude_pk else Client.objects.all()
    for client in candidates:
        if aliases.intersection(_client_contact_aliases(client)):
            return client
    for message in Message.objects.exclude(client=None).exclude(client_id=exclude_pk or 0).only('client_id', 'contact'):
        if _normalize_contact_alias(message.contact) in aliases:
            return Client.objects.filter(pk=message.client_id).first()
    return None


def _ensure_role_permissions() -> None:
    existing = {
        (item.role, item.resource)
        for item in RolePermission.objects.only('role', 'resource')
    }
    to_create = []
    for role, resource_map in DEFAULT_ROLE_PERMISSIONS.items():
        for resource in ALL_PERMISSION_RESOURCES:
            flags = resource_map.get(resource, {'read': False, 'write': False, 'delete': False})
            key = (role, resource)
            if key in existing:
                continue
            to_create.append(RolePermission(
                role=role,
                resource=resource,
                can_read=flags['read'],
                can_write=flags['write'],
                can_delete=flags['delete'],
            ))
    if to_create:
        RolePermission.objects.bulk_create(to_create)


def _permission_dict_for_role(role: str | None) -> dict[str, dict[str, bool]]:
    _ensure_role_permissions()
    if not role:
        return {}
    permissions = {
        resource: {'read': False, 'write': False, 'delete': False}
        for resource in ALL_PERMISSION_RESOURCES
    }
    for item in RolePermission.objects.filter(role=role):
        permissions[item.resource] = {
            'read': item.can_read,
            'write': item.can_write,
            'delete': item.can_delete,
        }
    return permissions


def _permission_dict_for_user(user: User | None) -> dict[str, dict[str, bool]]:
    role = _current_role(user)
    return _permission_dict_for_role(role)


def _has_permission(user: User | None, resource: str, operation: str = 'read') -> bool:
    permission = _permission_dict_for_user(user).get(resource, {})
    return bool(permission.get(operation))


def _first_allowed_page(user: User | None) -> str:
    allowed = _allowed_sections(user)
    return allowed[0] if allowed else 'dashboard'


def _parse_optional_date(raw_value: str | None) -> date | None:
    if not raw_value:
        return None
    try:
        return date.fromisoformat(str(raw_value).strip())
    except ValueError:
        return None


def _normalize_analytics_window(start_date: date | None, end_date: date | None, default_days: int = 30) -> tuple[date, date, datetime, datetime]:
    today = timezone.localdate()
    end_date = end_date or today
    start_date = start_date or (end_date - timedelta(days=max(default_days - 1, 0)))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()), tz)
    end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()), tz)
    return start_date, end_date, start_dt, end_dt


def _revenue_between(start_date: date, end_date: date) -> float:
    total = 0.0
    for purchases, bank_purchases in Client.objects.values_list('purchases', 'bank_purchases'):
        for item in (purchases or []):
            at = item.get('at', '')
            if not at or not isinstance(at, str) or len(at) < 10:
                continue
            try:
                item_date = datetime.fromisoformat(at).date()
            except (ValueError, TypeError):
                continue
            if start_date <= item_date <= end_date:
                total += float(item.get('amount', 0) or 0)
        for item in (bank_purchases or []):
            if not item.get('matched'):
                continue
            at = item.get('at', '')
            if not at or not isinstance(at, str) or len(at) < 10:
                continue
            try:
                item_date = datetime.fromisoformat(at).date()
            except (ValueError, TypeError):
                continue
            if start_date <= item_date <= end_date:
                total += float(item.get('amount', 0) or 0)
    for order in Order.objects.exclude(status=Order.Status.CANCELLED).filter(created_at__date__gte=start_date, created_at__date__lte=end_date):
        total += float(order.total or 0)
    return round(total, 2)


def _compute_avg_response_minutes(user: User, start_dt: datetime | None = None, end_dt: datetime | None = None) -> float | None:
    pending_by_client: dict[int, datetime] = {}
    total_minutes = 0.0
    matches = 0
    messages_qs = Message.objects.filter(assigned_to=user, client__isnull=False)
    if start_dt:
        messages_qs = messages_qs.filter(created_at__gte=start_dt)
    if end_dt:
        messages_qs = messages_qs.filter(created_at__lte=end_dt)
    for message in messages_qs.order_by('created_at'):
        client_id = message.client_id
        if message.direction == Message.Direction.INBOUND:
            pending_by_client[client_id] = message.created_at
            continue
        pending_at = pending_by_client.get(client_id)
        if pending_at and message.created_at >= pending_at:
            total_minutes += (message.created_at - pending_at).total_seconds() / 60
            matches += 1
            pending_by_client.pop(client_id, None)
    if not matches:
        return None
    return round(total_minutes / matches, 1)


def _channel_analytics(start_date: date | None = None, end_date: date | None = None, start_dt: datetime | None = None, end_dt: datetime | None = None) -> list[dict]:
    rows = []
    for channel in ['Telegram', 'VK', 'WhatsApp', 'Email', 'Сайт', 'Flowwow', 'Авито']:
        clients_qs = Client.objects.filter(source__iexact=channel)
        inbound_qs = Message.objects.filter(channel=channel, direction=Message.Direction.INBOUND)
        outbound_qs = Message.objects.filter(channel=channel, direction=Message.Direction.OUTBOUND)
        unread_qs = Message.objects.filter(channel=channel, unread=True)
        if start_date:
            clients_qs = clients_qs.filter(created_at__date__gte=start_date)
        if end_date:
            clients_qs = clients_qs.filter(created_at__date__lte=end_date)
        if start_dt:
            inbound_qs = inbound_qs.filter(created_at__gte=start_dt)
            outbound_qs = outbound_qs.filter(created_at__gte=start_dt)
            unread_qs = unread_qs.filter(created_at__gte=start_dt)
        if end_dt:
            inbound_qs = inbound_qs.filter(created_at__lte=end_dt)
            outbound_qs = outbound_qs.filter(created_at__lte=end_dt)
            unread_qs = unread_qs.filter(created_at__lte=end_dt)
        clients_count = clients_qs.count()
        buyers = clients_qs.filter(status=Client.Status.BUYER).count()
        inbound = inbound_qs.count()
        outbound = outbound_qs.count()
        unread = unread_qs.count()
        revenue = 0.0
        # JSON-поля (purchases/bank_purchases) считаем в Python, но тянем ТОЛЬКО
        # эти столбцы одним запросом, без загрузки всей карточки клиента.
        for purchases, bank_purchases in clients_qs.values_list('purchases', 'bank_purchases'):
            for item in (purchases or []):
                at = item.get('at', '')
                if start_date and end_date and isinstance(at, str) and len(at) >= 10:
                    try:
                        item_date = datetime.fromisoformat(at).date()
                    except (ValueError, TypeError):
                        item_date = None
                    if item_date and not (start_date <= item_date <= end_date):
                        continue
                revenue += float(item.get('amount', 0) or 0)
            for item in (bank_purchases or []):
                if item.get('matched'):
                    at = item.get('at', '')
                    if start_date and end_date and isinstance(at, str) and len(at) >= 10:
                        try:
                            item_date = datetime.fromisoformat(at).date()
                        except (ValueError, TypeError):
                            item_date = None
                        if item_date and not (start_date <= item_date <= end_date):
                            continue
                    revenue += float(item.get('amount', 0) or 0)
        # Выручку по заказам берём ОДНИМ агрегатом на канал, а не запросом на клиента.
        orders_qs = Order.objects.exclude(status=Order.Status.CANCELLED).filter(client__in=clients_qs)
        if start_date:
            orders_qs = orders_qs.filter(created_at__date__gte=start_date)
        if end_date:
            orders_qs = orders_qs.filter(created_at__date__lte=end_date)
        revenue += float(orders_qs.aggregate(s=Sum('total'))['s'] or 0)
        conversion = round((buyers / clients_count) * 100, 1) if clients_count else 0
        answer_rate = round((outbound / inbound) * 100, 1) if inbound else 0
        rows.append({
            'channel': channel,
            'clients': clients_count,
            'buyers': buyers,
            'inbound': inbound,
            'outbound': outbound,
            'unread': unread,
            'conversion': conversion,
            'answer_rate': answer_rate,
            'revenue': revenue,
        })
    return rows


def _buyers_growth_for_days(days: int = 7, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        if (end_date - start_date).days >= 31:
            start_date = end_date - timedelta(days=30)
        rows = []
        current = start_date
        while current <= end_date:
            count = Client.objects.filter(status=Client.Status.BUYER, created_at__date=current).count()
            rows.append({'label': current.strftime('%d.%m'), 'count': count})
            current += timedelta(days=1)
        return rows
    now_date = timezone.now().date()
    rows = []
    for offset in range(days - 1, -1, -1):
        day = now_date - timedelta(days=offset)
        count = Client.objects.filter(status=Client.Status.BUYER, created_at__date=day).count()
        rows.append({'label': day.strftime('%d.%m'), 'count': count})
    return rows


def _analytics_snapshot(start_date: date, end_date: date) -> dict:
    start_date, end_date, start_dt, end_dt = _normalize_analytics_window(start_date, end_date)
    clients_period_qs = Client.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
    tasks_period_qs = Task.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)
    orders_period_qs = Order.objects.exclude(status=Order.Status.CANCELLED).filter(created_at__gte=start_dt, created_at__lte=end_dt)
    employee_kpi = []
    avg_response_values = []
    messages_period_qs = Message.objects.filter(created_at__gte=start_dt, created_at__lte=end_dt)

    for user in User.objects.filter(is_active=True).select_related('profile'):
        if getattr(user, 'profile', None):
            user_messages = messages_period_qs.filter(assigned_to=user)
            user_tasks = tasks_period_qs.filter(assigned_to=user)
            avg_response = _compute_avg_response_minutes(user, start_dt=start_dt, end_dt=end_dt)
            handled_client_ids = set(user_messages.exclude(client__isnull=True).values_list('client_id', flat=True))
            handled_client_ids.update(user_tasks.exclude(client__isnull=True).values_list('client_id', flat=True))
            buyers = Client.objects.filter(pk__in=handled_client_ids, status=Client.Status.BUYER).count()
            conversion = round((buyers / len(handled_client_ids)) * 100, 1) if handled_client_ids else 0
            if avg_response is not None:
                avg_response_values.append(avg_response)
            employee_kpi.append({
                'name': user.get_full_name() or user.username,
                'role': user.profile.get_role_display(),
                'messages': user_messages.count(),
                'tasks': user_tasks.count(),
                'done': user_tasks.filter(status=Task.Status.DONE).count(),
                'buyers': buyers,
                'conversion': conversion,
                'avg_response_minutes': avg_response,
            })

    channel_stats = _channel_analytics(start_date=start_date, end_date=end_date, start_dt=start_dt, end_dt=end_dt)
    buyers_growth = _buyers_growth_for_days(start_date=start_date, end_date=end_date)
    open_tasks_period = tasks_period_qs.filter(status__in=[Task.Status.NEW, Task.Status.IN_PROGRESS, Task.Status.WAITING])
    done_tasks_period = tasks_period_qs.filter(status=Task.Status.DONE)
    period_revenue = _revenue_between(start_date, end_date)
    period_clients = clients_period_qs.count()
    buyers_count = clients_period_qs.filter(status=Client.Status.BUYER).count()
    overdue_open = open_tasks_period.filter(due_at__lt=timezone.now()).count()
    analytics_summary = {
        'period_label': f'{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}',
        'period_revenue': period_revenue,
        'period_clients': period_clients,
        'period_buyers': buyers_count,
        'period_orders': orders_period_qs.count(),
        'conversion_rate': round((buyers_count / period_clients) * 100, 1) if period_clients else 0,
        'task_completion_rate': round((done_tasks_period.count() / tasks_period_qs.count()) * 100, 1) if tasks_period_qs.exists() else 0,
        'overdue_rate': round((overdue_open / open_tasks_period.count()) * 100, 1) if open_tasks_period.exists() else 0,
        'avg_response_minutes': round(sum(avg_response_values) / len(avg_response_values), 1) if avg_response_values else None,
        'stock_value': round(sum(max(stock - reserve, 0) * float(price or 0) for stock, reserve, price in Product.objects.values_list('stock', 'reserve', 'price')), 2),
    }
    return {
        'start_date': start_date,
        'end_date': end_date,
        'start_dt': start_dt,
        'end_dt': end_dt,
        'employee_kpi': employee_kpi,
        'channel_stats': channel_stats,
        'buyers_growth': buyers_growth,
        'analytics_summary': analytics_summary,
        'task_status_new': tasks_period_qs.filter(status=Task.Status.NEW).count(),
        'task_status_in_progress': tasks_period_qs.filter(status=Task.Status.IN_PROGRESS).count(),
        'task_status_waiting': tasks_period_qs.filter(status=Task.Status.WAITING).count(),
        'task_status_done': done_tasks_period.count(),
        'order_count': orders_period_qs.count(),
        'order_revenue': round(float(orders_period_qs.aggregate(s=Sum('total'))['s'] or 0), 2),
        'buyers_count': buyers_count,
        'leads_count': clients_period_qs.filter(status=Client.Status.LEAD).count(),
        'unknown_count': clients_period_qs.filter(status=Client.Status.UNKNOWN).count(),
        'total_clients': period_clients,
        'top_channels': sorted(channel_stats, key=lambda item: item['revenue'], reverse=True)[:5],
    }


def _empty_analytics_snapshot() -> dict:
    """Пустой снапшот с теми же ключами — для страниц, где аналитика не нужна
    (чтобы не гонять дорогой _analytics_snapshot на каждый клик)."""
    today = timezone.localdate()
    return {
        'start_date': today,
        'end_date': today,
        'start_dt': None,
        'end_dt': None,
        'employee_kpi': [],
        'channel_stats': [],
        'buyers_growth': [],
        'analytics_summary': {
            'period_label': '', 'period_revenue': 0, 'period_clients': 0, 'period_buyers': 0,
            'period_orders': 0, 'conversion_rate': 0, 'task_completion_rate': 0,
            'overdue_rate': 0, 'avg_response_minutes': None, 'stock_value': 0,
        },
        'task_status_new': 0,
        'task_status_in_progress': 0,
        'task_status_waiting': 0,
        'task_status_done': 0,
        'order_count': 0,
        'order_revenue': 0,
        'buyers_count': 0,
        'leads_count': 0,
        'unknown_count': 0,
        'total_clients': 0,
        'top_channels': [],
    }


def _client_merge_score(client: Client) -> int:
    return sum([
        8 if client.phone else 0,
        6 if client.second_phone else 0,
        6 if client.email else 0,
        4 if client.one_c_id else 0,
        3 if client.discount_card else 0,
        2 if client.vk_url else 0,
        2 if client.telegram_url else 0,
        2 if client.whatsapp_url else 0,
        len(client.tags or []),
        len(client.interests or []),
        len(client.wish_list or []),
        len(client.wait_list or []),
        len(client.purchases or []),
        len(client.bank_purchases or []),
        len(client.history or []),
    ])


def _duplicate_reason_label(token: str) -> str:
    if token.startswith('phone:'):
        return 'Совпадает телефон'
    if token.startswith('email:'):
        return 'Совпадает email'
    if token.startswith('discount:'):
        return 'Совпадает скидочная карта'
    if token.startswith('name_district:'):
        return 'Совпадают ФИО и район'
    if 'vk.com' in token:
        return 'Совпадает VK'
    if token.startswith('tg://'):
        return 'Совпадает Telegram'
    if 'wa.me/' in token or 'whatsapp' in token:
        return 'Совпадает WhatsApp'
    return 'Совпадает контакт'


def _client_duplicate_tokens(client: Client) -> dict[str, str]:
    tokens: dict[str, str] = {}
    if client.phone:
        tokens[f'phone:{client.phone}'] = 'Совпадает телефон'
    if client.second_phone:
        tokens[f'phone:{client.second_phone}'] = 'Совпадает телефон'
    if client.email:
        tokens[f'email:{client.email.lower()}'] = 'Совпадает email'
    if client.discount_card:
        tokens[f'discount:{client.discount_card.strip().lower()}'] = 'Совпадает скидочная карта'
    if client.name and client.district:
        tokens[f'name_district:{client.name.strip().lower()}|{client.district.strip().lower()}'] = 'Совпадают ФИО и район'
    for raw_alias in client.contact_aliases or []:
        alias = shared_normalize_contact_alias(raw_alias)
        if not alias:
            continue
        tokens[alias] = _duplicate_reason_label(alias)
    return tokens


def _client_duplicate_candidates(limit: int = 12) -> list[dict]:
    clients = list(Client.objects.only(
        'id', 'name', 'phone', 'second_phone', 'email', 'source', 'status', 'discount_card', 'district',
        'one_c_id', 'vk_url', 'telegram_url', 'whatsapp_url', 'tags', 'interests', 'wish_list',
        'wait_list', 'purchases', 'bank_purchases', 'history', 'contact_aliases', 'created_at', 'updated_at',
    ).all())
    buckets: dict[str, list[Client]] = defaultdict(list)
    for client in clients:
        for token in _client_duplicate_tokens(client):
            buckets[token].append(client)

    pairs: dict[tuple[int, int], dict] = {}
    for token, matched_clients in buckets.items():
        unique_clients = []
        seen_ids = set()
        for client in matched_clients:
            if client.id in seen_ids:
                continue
            seen_ids.add(client.id)
            unique_clients.append(client)
        if len(unique_clients) < 2:
            continue
        for left, right in combinations(unique_clients, 2):
            pair_key = tuple(sorted((left.id, right.id)))
            record = pairs.setdefault(pair_key, {'left': left, 'right': right, 'reasons': set()})
            record['reasons'].add(_duplicate_reason_label(token))

    ordered_pairs = []
    for record in pairs.values():
        left = record['left']
        right = record['right']
        primary, duplicate = sorted(
            [left, right],
            key=lambda item: (-_client_merge_score(item), item.created_at, item.id),
        )
        ordered_pairs.append({
            'primary': primary,
            'duplicate': duplicate,
            'reasons': sorted(record['reasons']),
        })
    ordered_pairs.sort(key=lambda item: (-len(item['reasons']), -_client_merge_score(item['primary']), -item['primary'].id))
    return ordered_pairs[:limit]


def _create_waitlist_tasks() -> int:
    now = timezone.now()
    assignee = User.objects.filter(profile__role__in=[
        EmployeeProfile.Role.FRONT,
        EmployeeProfile.Role.HYBRID,
        EmployeeProfile.Role.LOCOMOTIVE,
    ], is_active=True).order_by('id').first() or User.objects.filter(is_staff=True, is_active=True).first()
    if assignee is None:
        return 0
    count = 0
    in_stock_names = set(Product.objects.filter(stock__gt=0).values_list('name', flat=True))
    for client in Client.objects.all():
        wanted_items = sorted(set((client.wait_list or []) + (client.wish_list or [])))
        available = [item for item in wanted_items if item in in_stock_names]
        for wanted in available:
            title = f'Товар из листа ожидания в наличии: {wanted} для {client.name}'
            exists = Task.objects.filter(client=client, title=title, status__in=[
                Task.Status.NEW, Task.Status.IN_PROGRESS, Task.Status.WAITING,
            ]).exists()
            if exists:
                continue
            Task.objects.create(
                title=title,
                priority=2,
                urgency='system',
                due_at=now,
                status=Task.Status.NEW,
                origin=Task.Origin.SYSTEM,
                assigned_to=assignee,
                client=client,
                comments=[{'author': 'CRM', 'text': f'Товар «{wanted}» появился в наличии.', 'at': now.isoformat()}],
            )
            count += 1
    return count


def _last_channel_contact(client: Client, channel: str) -> str:
    if not client:
        return ''
    message = client.messages.filter(channel=channel).exclude(contact='').order_by('-created_at').first()
    if message and message.contact:
        return message.contact.strip()

    aliases = client.contact_aliases or []
    for alias in aliases:
        if channel == 'Telegram' and str(alias).startswith('tg://user?id='):
            return str(alias)
        if channel == 'VK' and 'vk.com/id' in str(alias):
            return str(alias)
        if channel == 'Авито' and 'avito.ru/messages' in str(alias):
            return str(alias)
    return ''


def _send_supported_channels() -> list[str]:
    return ['Telegram', 'VK', 'Авито']


def _dispatch_outbound_message(channel: str, client: Client, text: str) -> tuple[bool, str, str]:
    contact = _last_channel_contact(client, channel)
    if channel == 'Telegram':
        from .tg_integration import send_tg_message
        if not contact:
            return False, 'Для Telegram не найден chat id клиента.', ''
        result = send_tg_message(contact, text)
        return result.get('status') == 'ok', result.get('message', ''), contact

    if channel == 'VK':
        from .vk_integration import send_vk_message
        if not contact:
            return False, 'Для VK не найден user id клиента.', ''
        result = send_vk_message(contact, text)
        return result.get('status') == 'ok', result.get('message', ''), contact

    if channel == 'Авито':
        from .avito_playwright import send_avito_message
        if not contact:
            return False, 'Для Авито не найдена ссылка на диалог. Сначала импортируйте переписку из Авито Playwright.', ''
        result = send_avito_message(contact, text, recipient_name=client.name)
        return result.get('status') == 'ok', result.get('message', ''), contact

    return False, f'Канал {channel} пока не поддерживает реальную отправку из CRM.', ''


def _create_follow_up_tasks() -> int:
    now = timezone.now()
    assignee = User.objects.filter(profile__role__in=[
        EmployeeProfile.Role.FRONT,
        EmployeeProfile.Role.HYBRID,
    ], is_active=True).order_by('id').first() or User.objects.filter(is_staff=True, is_active=True).first()
    if assignee is None:
        return 0
    count = 0
    stale_after = now - timedelta(hours=24)
    clients = Client.objects.prefetch_related('messages').filter(status__in=[Client.Status.LEAD, Client.Status.UNKNOWN])
    for client in clients:
        last_inbound = client.messages.filter(direction=Message.Direction.INBOUND).order_by('-created_at').first()
        if last_inbound is None or last_inbound.created_at < stale_after:
            continue
        answered = client.messages.filter(
            direction=Message.Direction.OUTBOUND,
            created_at__gte=last_inbound.created_at,
        ).exists()
        if answered:
            continue
        title = f'Follow-up по клиенту {client.name}'
        exists = Task.objects.filter(
            client=client,
            title=title,
            status__in=[Task.Status.NEW, Task.Status.IN_PROGRESS, Task.Status.WAITING],
        ).exists()
        if exists:
            continue
        Task.objects.create(
            title=title,
            priority=2,
            urgency='system',
            due_at=now,
            status=Task.Status.NEW,
            origin=Task.Origin.SYSTEM,
            assigned_to=assignee,
            client=client,
            comments=[{
                'author': 'CRM',
                'text': f'Клиент молчит после входящего сообщения от {last_inbound.created_at.isoformat()}.',
                'at': now.isoformat(),
            }],
        )
        count += 1
    return count


def _normalize_site_items(value) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [item.strip() for item in re.split(r'[\n,;]+', value) if item.strip()]
        return [{'name': item, 'qty': 1, 'price': 0.0, 'sku': ''} for item in raw_items]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    result.append({'name': stripped, 'qty': 1, 'price': 0.0, 'sku': ''})
                continue
            if isinstance(item, dict):
                name = str(item.get('name') or item.get('title') or item.get('product') or '').strip()
                if not name:
                    continue
                try:
                    qty = int(item.get('qty') or item.get('quantity') or 1)
                except (TypeError, ValueError):
                    qty = 1
                try:
                    price = float(item.get('price') or item.get('amount') or 0)
                except (TypeError, ValueError):
                    price = 0.0
                result.append({
                    'name': name,
                    'qty': max(qty, 1),
                    'price': price,
                    'sku': str(item.get('sku') or '').strip(),
                })
        return result
    return []


def _wishlist_names_from_payload(payload: dict) -> list[str]:
    names = [item['name'] for item in _normalize_site_items(payload.get('wishlist') or payload.get('nomenclature') or payload.get('items')) if item.get('name')]
    return sorted(set(names))


def _find_or_create_site_client(payload: dict) -> tuple[Client, bool]:
    phone = _normalize_phone(payload.get('phone', ''))
    email = _normalize_email(payload.get('email', ''))
    name = str(payload.get('name') or payload.get('customer_name') or payload.get('full_name') or '').strip()
    last_name, first_name, patronymic = split_client_name(name)
    vk_url = str(payload.get('vk') or '').strip()
    telegram_url = str(payload.get('telegram') or '').strip()
    whatsapp_url = str(payload.get('whatsapp') or payload.get('wa') or '').strip()
    phone, email, payload_aliases = sanitize_client_contacts(
        phone,
        email,
        [telegram_url, vk_url, whatsapp_url, payload.get('contact', '')],
    )

    client = None
    if phone:
        client = _find_client_by_normalized_phone(phone)
    if client is None and email:
        client = Client.objects.filter(email__iexact=email).first()
    if client is None and name:
        client = Client.objects.filter(name__iexact=name).first()

    created = client is None
    if client is None:
        client = Client(
            name=name or email or phone or 'Клиент с сайта',
            phone=phone or None,
            email=email or None,
            last_name=last_name,
            first_name=first_name,
            patronymic=patronymic,
            vk_url=vk_url,
            telegram_url=telegram_url,
            whatsapp_url=whatsapp_url,
            source='Сайт',
            preferred_channel='Сайт',
            status=Client.Status.LEAD,
        )
    else:
        if name:
            client.name = name
            if not client.last_name and not client.first_name and not client.patronymic:
                client.last_name = last_name
                client.first_name = first_name
                client.patronymic = patronymic
        if phone:
            client.phone = phone
        if email:
            client.email = email or None
        if vk_url:
            client.vk_url = vk_url
        if telegram_url:
            client.telegram_url = telegram_url
        if whatsapp_url:
            client.whatsapp_url = whatsapp_url
        client.source = client.source or 'Сайт'
        client.preferred_channel = client.preferred_channel or 'Сайт'

    district = str(payload.get('district') or '').strip()
    if district and not client.district:
        client.district = district
    discount_card = str(payload.get('discount_card') or '').strip()
    if discount_card and not client.discount_card:
        client.discount_card = discount_card
    birth_date = parse_date(str(payload.get('birth_date') or ''))
    if birth_date and not client.birth_date:
        client.birth_date = birth_date

    if client.bank_purchases or client.purchases:
        client.status = Client.Status.BUYER
    elif client.phone or client.email:
        client.status = Client.Status.LEAD
    else:
        client.status = Client.Status.UNKNOWN

    aliases = sorted(set(payload_aliases))
    if aliases:
        client.contact_aliases = sorted(set((client.contact_aliases or []) + aliases))

    return client, created


def _site_event_external_id(event_type: str, payload: dict) -> str:
    explicit_id = str(
        payload.get('submission_id')
        or payload.get('external_id')
        or payload.get('id')
        or ''
    ).strip()
    if explicit_id:
        return explicit_id
    raw = json.dumps({'event_type': event_type, 'payload': payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _extract_site_payload(request) -> dict:
    if request.content_type and 'application/json' in request.content_type:
        try:
            return json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    payload = request.POST.dict()
    if 'items' in payload:
        try:
            payload['items'] = json.loads(payload['items'])
        except (json.JSONDecodeError, TypeError):
            pass
    if 'wishlist' in payload:
        try:
            payload['wishlist'] = json.loads(payload['wishlist'])
        except (json.JSONDecodeError, TypeError):
            pass
    if 'nomenclature' in payload:
        try:
            payload['nomenclature'] = json.loads(payload['nomenclature'])
        except (json.JSONDecodeError, TypeError):
            pass
    return payload


def _authorize_site_webhook(request) -> bool:
    expected_token = getattr(settings, 'SITE_WEBHOOK_TOKEN', '')
    if not expected_token:
        return False
    provided_token = (
        request.headers.get('X-CRM-Token', '')
        or request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        or request.GET.get('token', '')
        or request.POST.get('token', '')
    )
    return provided_token == expected_token


def _create_site_order(client: Client, payload: dict, external_id: str) -> Order:
    items = _normalize_site_items(payload.get('items') or payload.get('products') or payload.get('order_items'))
    total = 0.0
    for item in items:
        total += float(item.get('price', 0)) * int(item.get('qty', 1))
    if not total:
        try:
            total = float(payload.get('total') or payload.get('amount') or 0)
        except (TypeError, ValueError):
            total = 0.0

    notes_parts = [
        str(payload.get('comment') or '').strip(),
        str(payload.get('notes') or '').strip(),
        str(payload.get('address') or '').strip(),
    ]
    notes = '\n'.join(part for part in notes_parts if part)

    status = str(payload.get('site_status') or '').strip()
    if status not in {choice[0] for choice in Order.Status.choices}:
        status = Order.Status.NEW

    order = Order.objects.create(
        client=client,
        items=items,
        total=total,
        notes=notes,
        status=status,
        history=[{'action': 'site_import', 'external_id': external_id, 'at': timezone.now().isoformat()}],
    )

    order_date = parse_datetime(str(payload.get('order_date') or ''))
    if order_date is not None:
        if timezone.is_naive(order_date):
            order_date = timezone.make_aware(order_date)
        Order.objects.filter(pk=order.pk).update(created_at=order_date)
        order.created_at = order_date

    client.history = (client.history or []) + [{
        'type': 'order',
        'text': f'Создан заказ с сайта №{order.pk}',
        'at': timezone.now().isoformat(),
    }]
    client.status = Client.Status.BUYER
    if client.first_purchase_at is None or order.created_at < client.first_purchase_at:
        client.first_purchase_at = order.created_at
        client.save(update_fields=['history', 'status', 'first_purchase_at', 'updated_at'])
    else:
        client.save(update_fields=['history', 'status', 'updated_at'])
    return order


def _find_or_create_wishlist_product(name: str):
    """Находим товар в каталоге по названию (без учёта регистра). Если такого
    товара нет — заводим новый (по ТЗ: «добавляется новый товар, если его нет»)."""
    name = (name or '').strip()
    if not name:
        return None
    product = Product.objects.filter(name__iexact=name).first()
    if product:
        return product
    return Product.objects.create(
        name=name,
        parent=name,
        sku='',
        kind=Product.ProductKind.PLANT,
        price=0,
    )


def _merge_site_wishlist(client: Client, payload: dict, external_id: str) -> list[str]:
    names = _wishlist_names_from_payload(payload)
    if not names:
        return []
    client.wish_list = sorted(set((client.wish_list or []) + names))
    client.history = (client.history or []) + [{
        'type': 'wishlist',
        'text': f'Получен wishlist с сайта ({", ".join(names[:5])})',
        'external_id': external_id,
        'at': timezone.now().isoformat(),
    }]
    if client.status == Client.Status.UNKNOWN and (client.email or client.phone):
        client.status = Client.Status.LEAD
    client.save(update_fields=['wish_list', 'history', 'status', 'updated_at'])
    # Привязка вишлиста к карточкам товаров (создаём недостающие).
    products = [p for p in (_find_or_create_wishlist_product(n) for n in names) if p]
    if products:
        client.wish_products.add(*products)
    return names


def _current_role(user: User | None):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    if profile:
        return profile.role
    return EmployeeProfile.Role.ADMIN if user.is_staff else EmployeeProfile.Role.FRONT


def _allowed_sections(user):
    role_sections = ROLE_SECTIONS.get(_current_role(user), [])
    permissions = _permission_dict_for_user(user)
    return [
        section for section in role_sections
        if permissions.get(PAGE_TO_RESOURCE.get(section, ''), {}).get('read')
    ]


def _base_context(request):
    user = request.user
    role = _current_role(user)
    permissions = _permission_dict_for_user(user)
    return {
        'current_role': role,
        'allowed_sections': _allowed_sections(user),
        'nav_labels': NAV_LABELS,
        'current_user_profile': getattr(user, 'profile', None) if user.is_authenticated else None,
        'permissions': permissions,
        'status_class': _status_class,
        'fmt_money': _fmt_money,
        'fmt_dt': _fmt_dt,
    }


def _client_status(client: Client):
    if client.status == Client.Status.BUYER or client.purchase_count > 0 or client.bank_purchases:
        return Client.Status.BUYER
    if client.phone or client.second_phone or client.email:
        return Client.Status.LEAD
    return Client.Status.UNKNOWN


def _selected_id(request, name, fallback=None):
    value = request.GET.get(name) or request.POST.get(name) or fallback
    return value


def _log_action(request, action, before='', after=''):
    actor = 'system'
    user = getattr(request, 'user', None)
    if getattr(user, 'is_authenticated', False):
        actor = getattr(user, 'get_full_name', lambda: '')() or getattr(user, 'username', '') or 'system'
    AuditEntry.objects.create(
        actor=actor,
        ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
        action=action,
        before=str(before)[:8000],
        after=str(after)[:8000],
    )


def _generate_code():
    return str(random.randint(100000, 999999))


def _lookup_user_by_email(email):
    user = User.objects.filter(email__iexact=email).first()
    if user:
        return user
    profile = EmployeeProfile.objects.filter(work_email__iexact=email).select_related('user').first()
    if profile:
        return profile.user
    return None


def _send_code_email(email, code, display_name=''):
    who = f' для {display_name}' if display_name else ''
    send_mail(
        subject=f'Код входа в LSG CRM{who}',
        message=f'Код входа{who}: {code}\n\nКод действителен 5 минут.\n\nЕсли это были не вы — проигнорируйте письмо.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )

def _send_code_email_with_timeout(email, code, display_name='', timeout=15):
    import threading
    result = []
    def _do_send():
        try:
            _send_code_email(email, code, display_name)
            result.append(True)
        except Exception as e:
            result.append(e)
    t = threading.Thread(target=_do_send, daemon=True)
    t.start()
    t.join(timeout)
    if not result:
        logger.warning('Email send timed out after %ss, showing code directly', timeout)
        raise TimeoutError('SMTP timeout')
    if result[0] is not True:
        raise result[0]


def _display_login_name(user: User) -> str:
    first_name = (user.first_name or '').strip()
    last_name = (user.last_name or '').strip()
    if first_name and last_name:
        return f'{first_name} {last_name[:1].upper()}'
    if first_name:
        return first_name
    return user.username


def _login_variants(user: User) -> set[str]:
    variants = {
        user.username.strip().casefold(),
        _display_login_name(user).strip().casefold(),
        user.get_full_name().strip().casefold(),
    }
    return {variant for variant in variants if variant}


def _lookup_login_user(identifier: str) -> User | None:
    normalized = str(identifier or '').strip().casefold()
    if not normalized:
        return None
    exact_username = User.objects.filter(username__iexact=identifier.strip()).first()
    if exact_username:
        return exact_username
    for user in User.objects.filter(is_active=True):
        if normalized in _login_variants(user):
            return user
    return None


def _is_admin_login(user: User) -> bool:
    # Only the dedicated admin account bypasses email-code verification.
    return bool(user.is_superuser)


def login_view(request):
    if request.user.is_authenticated:
        return redirect('crm:dashboard')

    error = None
    raw_step = request.session.get('login_step', 'credentials')
    if raw_step in ('code',):
        step = raw_step
    else:
        step = 'credentials'
        if raw_step != 'credentials':
            request.session['login_step'] = 'credentials'
            request.session.pop('login_user_id', None)
            request.session.pop('login_email', None)
            request.session.pop('login_code', None)
            request.session.pop('login_expiry', None)
            request.session.pop('login_identifier', None)
            request.session.pop('login_display_name', None)
            request.session.pop('login_remember_me', None)
    login_identifier = request.session.get('login_identifier', '')
    login_display_name = request.session.get('login_display_name', '')
    login_email = request.session.get('login_email', '')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action in ('back_to_login', 'back_to_username', 'back_to_credentials'):
            request.session['login_step'] = 'credentials'
            request.session.pop('login_user_id', None)
            request.session.pop('login_email', None)
            request.session.pop('login_code', None)
            request.session.pop('login_expiry', None)
            request.session.pop('login_identifier', None)
            request.session.pop('login_display_name', None)
            request.session.pop('login_remember_me', None)
            step = 'credentials'
            login_identifier = ''
            login_display_name = ''
            login_email = ''

        elif action == 'submit_credentials':
            identifier = request.POST.get('identifier', '').strip()
            password = request.POST.get('password', '')
            remember_me = request.POST.get('remember_me') == 'on'
            user = _lookup_login_user(identifier)
            if not user or not user.is_active:
                error = 'Пользователь не найден.'
            else:
                authenticated_user = authenticate(request, username=user.username, password=password)
                if authenticated_user is None:
                    error = 'Неверный пароль.'
                elif _is_admin_login(authenticated_user):
                    login(request, authenticated_user)
                    request.session.set_expiry(1209600 if remember_me else 0)
                    profile = getattr(authenticated_user, 'profile', None)
                    if profile:
                        profile.last_activity = timezone.now()
                        profile.save(update_fields=['last_activity'])
                    _log_action(request, 'Login (admin)', before='anonymous', after=authenticated_user.username)
                    return redirect('crm:dashboard')
                else:
                    email = authenticated_user.email
                    if not email:
                        profile = getattr(authenticated_user, 'profile', None)
                        if profile and profile.work_email:
                            email = profile.work_email
                    if not email:
                        error = 'У сотрудника не указана почта.'
                    else:
                        code = _generate_code()
                        request.session['login_code'] = code
                        request.session['login_email'] = email
                        request.session['login_user_id'] = authenticated_user.pk
                        request.session['login_identifier'] = identifier
                        request.session['login_display_name'] = _display_login_name(authenticated_user)
                        request.session['login_expiry'] = (timezone.now() + timedelta(minutes=5)).isoformat()
                        request.session['login_remember_me'] = remember_me
                        request.session['login_step'] = 'code'
                        step = 'code'
                        login_identifier = identifier
                        login_display_name = _display_login_name(authenticated_user)
                        try:
                            _send_code_email_with_timeout(email, code, login_display_name)
                        except Exception:
                            error = f'Код для входа: {code} (не удалось отправить на почту)'

        elif action == 'resend_code':
            email = request.session.get('login_email')
            if email:
                code = _generate_code()
                request.session['login_code'] = code
                request.session['login_expiry'] = (timezone.now() + timedelta(minutes=5)).isoformat()
                try:
                    _send_code_email_with_timeout(email, code, request.session.get('login_display_name', ''))
                except Exception:
                        error = f'Код для входа: {code} (не удалось отправить на почту)'
            else:
                error = 'Сессия устарела. Начните заново.'
                request.session['login_step'] = 'credentials'
                step = 'credentials'

        elif action == 'verify_code':
            input_code = request.POST.get('code', '').strip()
            stored_code = request.session.get('login_code')
            stored_email = request.session.get('login_email')
            stored_user_id = request.session.get('login_user_id')
            expiry_str = request.session.get('login_expiry')

            if not stored_code or not stored_email or not expiry_str:
                error = 'Сначала запросите код.'
            elif input_code != stored_code:
                error = 'Неверный код.'
            elif expiry_str and timezone.now() > timezone.datetime.fromisoformat(expiry_str):
                error = 'Код истёк. Запросите новый.'
                request.session.pop('login_code', None)
                request.session.pop('login_expiry', None)
            else:
                user = User.objects.filter(pk=stored_user_id).first()
                if user and user.is_active:
                    remember_me = request.session.get('login_remember_me', False)
                    login(request, user)
                    request.session.set_expiry(1209600 if remember_me else 0)
                    profile = getattr(user, 'profile', None)
                    if profile:
                        profile.last_activity = timezone.now()
                        profile.save(update_fields=['last_activity'])
                    _log_action(request, 'Login (2FA)', before='anonymous', after=user.username)
                    request.session.pop('login_step', None)
                    request.session.pop('login_code', None)
                    request.session.pop('login_user_id', None)
                    request.session.pop('login_email', None)
                    request.session.pop('login_expiry', None)
                    request.session.pop('login_identifier', None)
                    request.session.pop('login_display_name', None)
                    request.session.pop('login_remember_me', None)
                    return redirect('crm:dashboard')
                error = 'Пользователь не найден.'

    return render(request, 'crm/login.html', {
        **_base_context(request),
        'error': error,
        'step': step,
        'login_identifier': login_identifier,
        'login_display_name': login_display_name,
        'login_email': login_email,
    })


def logout_view(request):
    if request.user.is_authenticated:
        _log_action(request, 'Logout', before=request.user.username, after='anonymous')
    logout(request)
    return redirect('crm:login')


def _overdue_working_hours(schedule) -> int:
    """Просрочка по правилу заказчика: в каждый рабочий час должен быть хотя бы
    один ответ сотрудника (исходящее сообщение). Считаем, сколько уже прошедших
    рабочих часов сегодня остались без единого исходящего сообщения."""
    if schedule is None:
        return 0
    now = timezone.localtime(timezone.now())
    working_days = schedule.parsed_working_days()
    if working_days and now.weekday() not in working_days:
        return 0
    start_h = schedule.workday_start.hour if schedule.workday_start else 9
    end_h = schedule.workday_end.hour if schedule.workday_end else 20
    # рассматриваем только уже завершившиеся часы (до текущего)
    last_h = min(now.hour, end_h)
    if last_h <= start_h:
        return 0
    today = now.date()
    overdue = 0
    for hour in range(start_h, last_h):
        hour_start = timezone.make_aware(datetime.combine(today, dt_time(hour, 0)))
        hour_end = hour_start + timedelta(hours=1)
        has_reply = Message.objects.filter(
            direction=Message.Direction.OUTBOUND,
            created_at__gte=hour_start,
            created_at__lt=hour_end,
        ).exists()
        if not has_reply:
            overdue += 1
    return overdue


def _shift_summary():
    """Кто сейчас в смене и сколько времени уже в сети (по открытым ClockEvent)."""
    now = timezone.now()
    rows = []
    for event in ClockEvent.objects.filter(clock_out__isnull=True).select_related('user'):
        minutes = int((now - event.clock_in).total_seconds() // 60)
        rows.append({
            'name': event.user.get_full_name() or event.user.username,
            'since': event.clock_in,
            'hours': minutes // 60,
            'minutes': minutes % 60,
        })
    return rows


def _unanswered_by_channel(start_dt=None):
    """Неотвеченные входящие, разбитые по каналам (за период, если задан)."""
    from django.db.models import Count
    qs = Message.objects.filter(direction=Message.Direction.INBOUND, unread=True)
    if start_dt is not None:
        qs = qs.filter(created_at__gte=start_dt)
    return list(qs.values('channel').annotate(count=Count('id')).order_by('-count'))


@login_required
def dashboard(request):
    page = request.GET.get('page', 'dashboard')
    page_resource = PAGE_TO_RESOURCE.get(page, RolePermission.Resource.DASHBOARD)
    if not _has_permission(request.user, page_resource, 'read'):
        messages.error(request, 'У вас нет доступа к этому разделу.')
        return redirect(f"{reverse('crm:dashboard')}?page={_first_allowed_page(request.user)}")

    if request.method == 'POST':
        action = request.POST.get('action', '')
        required = ACTION_PERMISSIONS.get(action)
        if required and not _has_permission(request.user, required[0], required[1]):
            messages.error(request, 'Недостаточно прав для этого действия.')
            return redirect(f"{reverse('crm:dashboard')}?page={page}")
        handler = {
            'create_client': _create_or_update_client,
            'create_task': _create_task,
            'send_message': _send_message,
            'sync_1c': _sync_1c,
            'poll_avito': _poll_avito,
            'poll_manual_messages': _poll_manual_messages,
            'start_avito_web_login': _start_avito_web_login,
            'confirm_avito_web_login': _confirm_avito_web_login,
            'poll_vk': _poll_vk,
            'poll_tg': _poll_tg,
            'sync_bank': _sync_bank,
            'merge_clients': _merge_clients_manual,
            'create_user': _create_user,
            'update_user': _update_user,
            'toggle_user': _toggle_user,
            'delete_user': _delete_user,
            'import_csv': _import_csv_users,
            'generate_follow_up': _generate_follow_up,
            'quick_test_start': _quick_test_start,
            'quick_test_answer': _quick_test_answer,
            'quick_test_reset': _quick_test_reset,
            'simulate_incoming': _simulate_incoming,
            'dict_add': _dict_add,
            'dict_update': _dict_update,
            'dict_delete': _dict_delete,
            'upload_file': _upload_file,
            'wishlist_trigger': _wishlist_trigger,
            'save_article': _save_article,
            'delete_article': _delete_article,
            'clock_in': _clock_toggle,
            'clock_out': _clock_toggle,
            'reassign_task': _reassign_task,
            'export_analytics_csv': _export_analytics_csv,
            'export_clients_csv': _export_clients_csv,
            'export_products_csv': _export_products_csv,
            'save_schedule': _save_schedule,
            'save_script': _save_script,
            'delete_script': _delete_script,
            'save_permission': _save_permission,
            'create_order': _create_order,
            'update_order_status': _update_order_status,
            'edit_order': _edit_order,
            'delete_order': _delete_order,
            'add_shift': _add_shift,
            'delete_shift': _delete_shift,
        }.get(action)
        if handler:
            try:
                response = handler(request)
                if response:
                    return response
            except Exception as e:
                messages.error(request, f'Ошибка: {e}')
                return redirect(reverse('crm:dashboard'))

    if page == 'knowledge' and getattr(request.user, 'profile', None):
        request.user.profile.last_news_seen_at = timezone.now()
        request.user.profile.save(update_fields=['last_news_seen_at'])

    clients_qs = Client.objects.only(
        'id', 'name', 'last_name', 'first_name', 'patronymic', 'one_c_id',
        'phone', 'second_phone', 'email', 'status', 'source', 'preferred_channel',
        'birth_date', 'district', 'discount_card', 'first_purchase_at',
        'vk_url', 'telegram_url', 'whatsapp_url', 'updated_at',
        'contact_aliases', 'tags', 'interests',
    ).all()
    messages_qs = Message.objects.select_related('client', 'assigned_to').only(
        'id', 'channel', 'direction', 'author_name', 'contact', 'text', 'unread', 'created_at',
        'client__name', 'client__id', 'assigned_to__id', 'assigned_to__username',
    ).all()
    tasks_qs = Task.objects.select_related('client', 'assigned_to').only(
        'id', 'title', 'priority', 'status', 'origin', 'due_at', 'created_at',
        'client__name', 'client__id', 'assigned_to__id', 'assigned_to__username',
    ).all()
    products_qs = Product.objects.only('id', 'name', 'parent', 'sku', 'stock', 'reserve', 'price', 'in_production', 'status', 'kind').all()
    news_qs = NewsItem.objects.all()[:3]
    knowledge_qs = list(KnowledgeArticle.objects.all())
    audit_qs = AuditEntry.objects.all()[:10]

    selected_pk = _selected_id(request, 'client')
    selected_client = None
    if selected_pk:
        selected_client = Client.objects.prefetch_related('messages', 'tasks', 'orders').filter(pk=selected_pk).first()
    if not selected_client:
        selected_client = Client.objects.prefetch_related('messages', 'tasks', 'orders').first()
    selected_task = tasks_qs.filter(pk=_selected_id(request, 'task')).first() or tasks_qs.first()
    selected_product = products_qs.filter(pk=_selected_id(request, 'product')).first() or products_qs.first()
    inbox_channel = request.GET.get('channel', 'all')
    search = request.GET.get('q', '').strip()
    task_filter = request.GET.get('task_filter', 'all')
    knowledge_role = request.GET.get('knowledge_role', 'all')
    status_filter = request.GET.get('client_status', 'all')

    if inbox_channel != 'all':
        messages_qs = messages_qs.filter(channel=inbox_channel)
    if search:
        alias_match_ids = [
            client.id
            for client in Client.objects.all()
            if search.lower() in client.name.lower()
            or search.lower() in (client.source or '').lower()
            or any(search.lower() in item.lower() for item in (client.tags or []))
            or any(search.lower() in item.lower() for item in (client.interests or []))
            or any(search.lower() in alias.lower() for alias in (client.contact_aliases or []))
        ]
        client_filter = (
            Q(name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(first_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(second_phone__icontains=search)
            | Q(email__icontains=search)
            | Q(source__icontains=search)
            | Q(tags__icontains=search)
            | Q(interests__icontains=search)
            | Q(pk__in=alias_match_ids)
        )
        # Поиск по телефону без учёта формата: сводим ввод к цифрам (8→7),
        # чтобы «8 999…», «+7(999)…» и «79 99…» находили один и тот же номер.
        search_digits = ''.join(ch for ch in search if ch.isdigit())
        if len(search_digits) == 11 and search_digits.startswith('8'):
            search_digits = '7' + search_digits[1:]
        if len(search_digits) >= 3:
            client_filter |= Q(phone__icontains=search_digits) | Q(second_phone__icontains=search_digits)
        clients_qs = clients_qs.filter(client_filter)
        messages_qs = messages_qs.filter(
            Q(author_name__icontains=search)
            | Q(contact__icontains=search)
            | Q(text__icontains=search)
            | Q(channel__icontains=search)
        )
        tasks_qs = tasks_qs.filter(
            Q(title__icontains=search)
            | Q(origin__icontains=search)
            | Q(client__name__icontains=search)
        )
        products_qs = products_qs.filter(
            Q(name__icontains=search)
            | Q(parent__icontains=search)
            | Q(sku__icontains=search)
        )
    if status_filter in ['buyer', 'lead', 'unknown']:
        clients_qs = clients_qs.filter(status=status_filter)
    # Клиентов показываем по алфавиту фамилии (заказчик просил именно так).
    clients_qs = clients_qs.order_by('last_name', 'first_name', 'name')

    client_offset = int(request.GET.get('client_offset', '0'))
    if client_offset < 0:
        client_offset = 0
    product_offset = int(request.GET.get('product_offset', '0'))
    if product_offset < 0:
        product_offset = 0

    if task_filter == 'overdue':
        tasks_qs = tasks_qs.filter(status__in=['new', 'in_progress', 'waiting'], due_at__lt=timezone.now())
    elif task_filter in ['new', 'in_progress', 'waiting', 'done']:
        tasks_qs = tasks_qs.filter(status=task_filter)

    if knowledge_role != 'all':
        knowledge_qs = [item for item in knowledge_qs if item.role == knowledge_role]

    knowledge_items = knowledge_qs or []
    if len(knowledge_items) < 8:
        existing_titles = {item.title for item in knowledge_items}
        for item in DEFAULT_KNOWLEDGE_LIBRARY:
            if item['title'] not in existing_titles and (knowledge_role == 'all' or item['role'] == knowledge_role):
                knowledge_items.append(type('KnowledgeItem', (), item)())

    def _sum_amounts(items):
        return sum(float(item.get('amount', 0)) for item in (items or []))

    def _match_scripts(text):
        matched = []
        for rule in ScriptRule.objects.filter(is_active=True):
            if any(word in text.lower() for word in rule.trigger.lower().split()):
                matched.append({'id': rule.pk, 'trigger': rule.trigger, 'answer': rule.answer})
        for item in DEFAULT_AUTO_SCRIPTS:
            if any(word in text.lower() for word in item['trigger'].lower().split()):
                matched.append({'id': None, 'trigger': item['trigger'], 'answer': item['answer']})
        return matched[:3]

    now_date = timezone.now().date()
    leads_count = Client.objects.filter(status=Client.Status.LEAD).count()

    # Период-фильтр дашборда (календарь c/по). По умолчанию — последние 7 дней,
    # чтобы «актуальные неотвеченные» не тянули всю историю.
    dash_start_input = request.GET.get('dash_start', '')
    dash_end_input = request.GET.get('dash_end', '')
    dash_start = _parse_optional_date(dash_start_input) or (now_date - timedelta(days=6))
    dash_end = _parse_optional_date(dash_end_input) or now_date
    if dash_start > dash_end:
        dash_start, dash_end = dash_end, dash_start
    dash_start_dt = timezone.make_aware(datetime.combine(dash_start, dt_time.min))
    dash_end_dt = timezone.make_aware(datetime.combine(dash_end, dt_time.max))

    schedule_settings = ScheduleSettings.objects.first()

    # Тяжёлые вычисления считаем ТОЛЬКО для той страницы, где они реально нужны,
    # иначе каждый клик по любому разделу гонял аналитику по всем сообщениям/
    # пользователям (~3200 запросов, ~5 сек). Дашборд-метрики и разбивка по
    # каналам нужны только на самом дашборде.
    if page == 'dashboard':
        unanswered_by_channel = _unanswered_by_channel(start_dt=dash_start_dt)
        unanswered_total = sum(row['count'] for row in unanswered_by_channel)
        active_chats = Message.objects.filter(direction=Message.Direction.INBOUND, unread=True).count()
        overdue_count = _overdue_working_hours(schedule_settings)
        shift_summary = _shift_summary()
        buyers_count = Client.objects.filter(status=Client.Status.BUYER).count()
        unknown_count = Client.objects.filter(status=Client.Status.UNKNOWN).count()
        total_clients = Client.objects.count()
    else:
        unanswered_by_channel = []
        unanswered_total = 0
        active_chats = 0
        overdue_count = 0
        shift_summary = []
        buyers_count = unknown_count = total_clients = 0

    # Склад-метрики нужны на products и analytics.
    if page in ('products', 'analytics'):
        total_products = Product.objects.count()
        critical_stock = Product.objects.filter(status=Product.StockStatus.CRITICAL).count()
        low_stock = Product.objects.filter(status=Product.StockStatus.LOW).count()
    else:
        total_products = critical_stock = low_stock = 0

    analytics_start_input = request.GET.get('analytics_start', '')
    analytics_end_input = request.GET.get('analytics_end', '')
    # Аналитический снапшот (самая дорогая операция) — только на странице аналитики.
    if page == 'analytics':
        analytics_start = _parse_optional_date(analytics_start_input)
        analytics_end = _parse_optional_date(analytics_end_input)
        analytics_snapshot = _analytics_snapshot(
            analytics_start or (timezone.localdate() - timedelta(days=29)),
            analytics_end or timezone.localdate(),
        )
        analytics_start_input = analytics_snapshot['start_date'].isoformat()
        analytics_end_input = analytics_snapshot['end_date'].isoformat()
    else:
        analytics_snapshot = _empty_analytics_snapshot()

    # Поиск дублей клиентов — только на странице клиентов.
    duplicate_candidates = _client_duplicate_candidates() if page == 'clients' else []

    role = _current_role(request.user)
    god_mode_messages = None
    if role == EmployeeProfile.Role.ADMIN and page == 'admin':
        god_mode_messages = Message.objects.select_related('client', 'assigned_to').all()[:50]

    dict_tags = list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.TAG)[:50])
    dict_statuses = list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.STATUS)[:50])
    dict_interests = list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.INTEREST)[:50])
    dictionary_sections = [
        {
            'dict_type': DictionaryEntry.DictType.TAG,
            'label': 'Теги',
            'entries': list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.TAG)),
        },
        {
            'dict_type': DictionaryEntry.DictType.STATUS,
            'label': 'Статусы',
            'entries': list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.STATUS)),
        },
        {
            'dict_type': DictionaryEntry.DictType.INTEREST,
            'label': 'Интересы',
            'entries': list(DictionaryEntry.objects.filter(dict_type=DictionaryEntry.DictType.INTEREST)),
        },
    ]
    client_sources = sorted({item for item in Client.objects.exclude(source='').values_list('source', flat=True) if item})
    client_districts = sorted({item for item in Client.objects.exclude(district='').values_list('district', flat=True) if item})
    client_discount_cards = sorted({item for item in Client.objects.exclude(discount_card='').values_list('discount_card', flat=True) if item})

    fraud_events = FraudEvent.objects.select_related('employee').all()[:20]
    uploaded_files = UploadedFile.objects.select_related('uploaded_by').all()[:10]
    permission_audit_entries = AuditEntry.objects.filter(action='Update role permission')[:12]
    admin_recent_actions = AuditEntry.objects.filter(
        action__in=['Create user', 'Update user', 'Toggle user', 'Delete user', 'Dictionary add', 'Dictionary update', 'Dictionary delete']
    )[:12]

    in_production_products = [p for p in products_qs if p.in_production > 0]

    # Единое окно: для каждого сообщения считаем статус ответа, чтобы сотрудник
    # сразу видел отвечено / не отвечено / просрочено.
    inbox_list = list(messages_qs[:50])
    overdue_threshold = timezone.now() - timedelta(hours=1)
    for _m in inbox_list:
        if _m.direction == Message.Direction.OUTBOUND:
            _m.reply_state = 'outbound'
        elif not _m.unread:
            _m.reply_state = 'answered'
        elif _m.created_at < overdue_threshold:
            _m.reply_state = 'overdue'
        else:
            _m.reply_state = 'unanswered'

    current_clock_event = ClockEvent.objects.filter(user=request.user, clock_out__isnull=True).first()
    script_search = request.GET.get('script_search', '').strip()
    db_scripts_qs = ScriptRule.objects.filter(is_active=True)
    if script_search:
        db_scripts_qs = db_scripts_qs.filter(Q(trigger__icontains=script_search) | Q(answer__icontains=script_search))
    db_scripts = list(db_scripts_qs)

    matched_scripts = []
    if selected_client:
        last_inbound = selected_client.messages.filter(direction='in').order_by('-created_at').first()
        if last_inbound:
            matched_scripts = _match_scripts(last_inbound.text)
    employee_kpi = analytics_snapshot['employee_kpi']
    channel_stats = analytics_snapshot['channel_stats']
    buyers_growth = analytics_snapshot['buyers_growth']
    analytics_summary = analytics_snapshot['analytics_summary']
    top_channels = analytics_snapshot['top_channels']
    catalog_relation_errors = [
        product for product in Product.objects.filter(kind=Product.ProductKind.PLANT)
        if not (product.parent or '').strip() or (product.parent or '').strip() == (product.name or '').strip()
    ]
    unread_news_items = []
    unread_news_count = 0
    profile = getattr(request.user, 'profile', None)
    if profile:
        unread_since = profile.last_news_seen_at or timezone.make_aware(datetime(1970, 1, 1))
        unread_news_items = list(NewsItem.objects.filter(published_at__gt=unread_since)[:5])
        unread_news_count = len(unread_news_items)

    context = {
        **_base_context(request),
        'page': page,
        'page_label': NAV_LABELS.get(page, 'Дашборд'),
        'now': timezone.now(),
        'selected_client': selected_client,
        'selected_task': selected_task,
        'selected_product': selected_product,
        'clients': clients_qs[client_offset:client_offset + 50],
        'inbox_messages': inbox_list,
        'tasks': tasks_qs[:50],
        'products': products_qs[product_offset:product_offset + 50],
        'client_offset': client_offset,
        'product_offset': product_offset,
        'has_more_clients': len(clients_qs[client_offset + 50:client_offset + 51]) > 0,
        'has_more_products': len(products_qs[product_offset + 50:product_offset + 51]) > 0,
        'duplicate_candidates': duplicate_candidates,
        'knowledge_items': knowledge_items,
        'news_items': news_qs,
        'audit_items': audit_qs,
        'leads_count': leads_count,
        'active_chats': active_chats,
        'overdue_count': overdue_count,
        'unanswered_by_channel': unanswered_by_channel,
        'unanswered_total': unanswered_total,
        'shift_summary': shift_summary,
        'dash_start': dash_start.isoformat(),
        'dash_end': dash_end.isoformat(),
        'message_query': search,
        'task_query': search,
        'client_query': search,
        'channel_filter': inbox_channel,
        'task_filter': task_filter,
        'knowledge_role': knowledge_role,
        'client_status': status_filter,
        'channels': ['all', 'Telegram', 'VK', 'WhatsApp', 'Email', 'Сайт', 'Flowwow', 'Авито'],
        'outbound_channels': _send_supported_channels(),
        'nav_items': [(key, NAV_LABELS[key]) for key in _allowed_sections(request.user)],
        'sections': _allowed_sections(request.user),
        'all_users': User.objects.select_related('profile').order_by('-is_active', 'username'),
        'blocked_users': User.objects.filter(is_active=False).select_related('profile').order_by('username'),
        'scripts': db_scripts + DEFAULT_AUTO_SCRIPTS,
        'quick_test_question': request.session.get('quick_test_question'),
        'quick_test_deadline_at': request.session.get('quick_test_deadline_at'),
        'quick_test_attempts': request.session.get('quick_test_attempts', 0),
        'dict_tags': dict_tags,
        'dict_statuses': dict_statuses,
        'dict_interests': dict_interests,
        'dictionary_sections': dictionary_sections,
        'client_sources': client_sources,
        'client_districts': client_districts,
        'client_discount_cards': client_discount_cards,
        'fraud_events': fraud_events,
        'uploaded_files': uploaded_files,
        'god_mode_messages': god_mode_messages,
        'buyers_count': buyers_count,
        'unknown_count': unknown_count,
        'total_clients': total_clients,
        'total_products': total_products,
        'critical_stock': critical_stock,
        'low_stock': low_stock,
        'in_production_products': in_production_products,
        'employee_kpi': employee_kpi,
        'channel_stats': channel_stats,
        'buyers_growth': buyers_growth,
        'analytics_summary': analytics_summary,
        'top_channels': top_channels,
        'catalog_relation_errors': catalog_relation_errors,
        'unread_news_items': unread_news_items,
        'unread_news_count': unread_news_count,
        'current_clock_event': current_clock_event,
        'matched_scripts': matched_scripts,
        'db_scripts': db_scripts,
        'script_search': script_search,
        'schedule': schedule_settings,
        'role_permissions': RolePermission.objects.order_by('role', 'resource'),
        'shift_assignments': ShiftAssignment.objects.select_related('employee')[:60],
        'today_shifts': ShiftAssignment.objects.select_related('employee').filter(date=timezone.localdate()),
        'role_choices': EmployeeProfile.Role.choices,
        'permission_audit_entries': permission_audit_entries,
        'admin_recent_actions': admin_recent_actions,
        'analytics_start': analytics_start_input,
        'analytics_end': analytics_end_input,
        'task_status_new': analytics_snapshot['task_status_new'],
        'task_status_in_progress': analytics_snapshot['task_status_in_progress'],
        'task_status_waiting': analytics_snapshot['task_status_waiting'],
        'task_status_done': analytics_snapshot['task_status_done'],
        'order_count': analytics_snapshot['order_count'],
        'order_revenue': analytics_snapshot['order_revenue'],
    }

    return render(request, 'crm/dashboard.html', context)


def _create_or_update_client(request):
    fallback_name = request.POST.get('name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    first_name = request.POST.get('first_name', '').strip()
    patronymic = request.POST.get('patronymic', '').strip()
    name = compose_client_name(last_name, first_name, patronymic, fallback_name)
    birth_date_raw = request.POST.get('birth_date', '').strip()
    raw_phone = request.POST.get('phone', '').strip()
    raw_second_phone = request.POST.get('second_phone', '').strip()
    raw_email = request.POST.get('email', '').strip()
    one_c_id = request.POST.get('one_c_id', '').strip()
    vk_url = request.POST.get('vk_url', '').strip()
    telegram_url = request.POST.get('telegram_url', '').strip()
    whatsapp_url = request.POST.get('whatsapp_url', '').strip()
    district = request.POST.get('district', '').strip()
    source = request.POST.get('source', '').strip() or 'Сайт'
    discount_card = request.POST.get('discount_card', '').strip()
    preferred_channel = request.POST.get('preferred_channel', '').strip() or source
    tags = [item.strip() for item in request.POST.get('tags', '').split(',') if item.strip()]
    interests = [item.strip() for item in request.POST.get('interests', '').split(',') if item.strip()]
    contact_aliases = _parse_contact_aliases(request.POST.get('contact_aliases', ''))
    contact_aliases = sorted(set(contact_aliases + _parse_contact_aliases([vk_url, telegram_url, whatsapp_url, raw_second_phone])))
    phone, email, contact_aliases = sanitize_client_contacts(raw_phone, raw_email, contact_aliases)
    second_phone = _normalize_phone(raw_second_phone) or None
    if second_phone == phone:
        second_phone = None
    wish_list = [item.strip() for item in request.POST.get('wish_list', '').split(',') if item.strip()]
    wait_list = [item.strip() for item in request.POST.get('wait_list', '').split(',') if item.strip()]
    internal_note = request.POST.get('internal_note', '').strip()
    quality = request.POST.get('quality', 'B')
    green_list = request.POST.get('green_list') == 'on'
    black_list = request.POST.get('black_list') == 'on'
    client_id = request.POST.get('client_id') or None

    birth_date = None
    if birth_date_raw:
        try:
            birth_date = date.fromisoformat(birth_date_raw)
        except ValueError:
            messages.error(request, 'Дата рождения указана в неверном формате.')
            return redirect(_redirect_to_client(request, client_id))

    if not name:
        messages.error(request, 'Укажите имя клиента.')
        return redirect(_redirect_to_client(request, client_id))

    target = Client.objects.filter(pk=client_id).first() if client_id else None
    lookup_aliases = set(contact_aliases)
    if phone:
        lookup_aliases.add(f'phone:{phone}')
    if second_phone:
        lookup_aliases.add(f'phone:{second_phone}')
    if email:
        lookup_aliases.add(f'email:{_normalize_email(email)}')
    duplicate = _find_client_by_alias_match(lookup_aliases, exclude_pk=getattr(target, 'pk', None))

    if duplicate and target:
        _merge_clients(target, duplicate)
        messages.success(request, f'Карточки {target.name} и {duplicate.name} объединены.')
        return redirect(f"{reverse('crm:dashboard')}?client={target.pk}")

    obj = target or duplicate or Client()
    obj.name = name
    obj.last_name = last_name
    obj.first_name = first_name
    obj.patronymic = patronymic
    obj.birth_date = birth_date
    obj.phone = phone
    obj.second_phone = second_phone
    obj.email = email or None
    obj.one_c_id = one_c_id
    obj.vk_url = vk_url
    obj.telegram_url = telegram_url
    obj.whatsapp_url = whatsapp_url
    obj.district = district
    obj.source = source
    obj.discount_card = discount_card
    obj.preferred_channel = preferred_channel
    obj.tags = tags
    obj.interests = interests
    obj.contact_aliases = sorted(set((obj.contact_aliases or []) + list(lookup_aliases) + contact_aliases))
    if discount_card:
        obj.discount_cards = sorted(set((obj.discount_cards or []) + [discount_card]))
    obj.wish_list = wish_list
    obj.wait_list = wait_list
    obj.internal_note = internal_note
    obj.quality = quality
    obj.green_list = green_list
    obj.black_list = black_list
    obj.status = Client.Status.BUYER if (obj.purchases or obj.bank_purchases) else (Client.Status.LEAD if phone or second_phone or email else Client.Status.UNKNOWN)
    obj.save()
    obj.history = (obj.history or []) + [{'type': 'update', 'text': 'Карточка обновлена вручную', 'at': timezone.now().isoformat()}]
    obj.save(update_fields=['history', 'updated_at'])

    _log_action(request, 'Create/Update client', before=client_id or 'new', after=obj.name)
    messages.success(request, 'Карточка клиента сохранена.')
    return redirect(f"{reverse('crm:dashboard')}?client={obj.pk}")


def _merge_clients(primary: Client, duplicate: Client):
    if not primary or not duplicate or primary.pk == duplicate.pk:
        return

    duplicate_name = duplicate.name
    duplicate_phone = duplicate.phone
    duplicate_second_phone = duplicate.second_phone
    duplicate_email = duplicate.email
    primary.last_name = primary.last_name or duplicate.last_name
    primary.first_name = primary.first_name or duplicate.first_name
    primary.patronymic = primary.patronymic or duplicate.patronymic
    primary.birth_date = primary.birth_date or duplicate.birth_date
    primary.second_phone = primary.second_phone or duplicate.second_phone
    primary.email = primary.email or duplicate.email
    primary.tags = sorted(set((primary.tags or []) + (duplicate.tags or [])))
    primary.interests = sorted(set((primary.interests or []) + (duplicate.interests or [])))
    primary.discount_cards = sorted(set((primary.discount_cards or []) + (duplicate.discount_cards or [])))
    primary.discount_card = primary.discount_card or duplicate.discount_card
    primary.contact_aliases = sorted(set((primary.contact_aliases or []) + (duplicate.contact_aliases or [])))
    primary.wish_list = sorted(set((primary.wish_list or []) + (duplicate.wish_list or [])))
    primary.wait_list = sorted(set((primary.wait_list or []) + (duplicate.wait_list or [])))
    primary.purchases = list((duplicate.purchases or []) + (primary.purchases or []))
    primary.bank_purchases = list((primary.bank_purchases or []) + (duplicate.bank_purchases or []))
    primary.history = list((duplicate.history or []) + (primary.history or []))
    primary.internal_note = '\n'.join(filter(None, [primary.internal_note, duplicate.internal_note]))
    primary.one_c_id = primary.one_c_id or duplicate.one_c_id
    primary.first_purchase_at = primary.first_purchase_at or duplicate.first_purchase_at
    primary.vk_url = primary.vk_url or duplicate.vk_url
    primary.telegram_url = primary.telegram_url or duplicate.telegram_url
    primary.whatsapp_url = primary.whatsapp_url or duplicate.whatsapp_url
    primary.district = primary.district or duplicate.district
    primary.source = primary.source or duplicate.source
    primary.preferred_channel = primary.preferred_channel or duplicate.preferred_channel
    primary.status = _client_status(primary)
    primary.history = list((duplicate.history or []) + (primary.history or [])) + [{
        'type': 'merge',
        'text': f'Объединена карточка {duplicate_name}',
        'at': timezone.now().isoformat(),
    }]
    if duplicate_phone:
        primary.contact_aliases = sorted(set((primary.contact_aliases or []) + [f'phone:{duplicate_phone}']))
    if duplicate_second_phone:
        primary.contact_aliases = sorted(set((primary.contact_aliases or []) + [f'phone:{duplicate_second_phone}']))
    if duplicate_email:
        primary.contact_aliases = sorted(set((primary.contact_aliases or []) + [f'email:{duplicate_email.lower()}']))

    with transaction.atomic():
        Message.objects.filter(client=duplicate).update(client=primary)
        Task.objects.filter(client=duplicate).update(client=primary)
        Order.objects.filter(client=duplicate).update(client=primary)
        duplicate.phone = None
        duplicate.second_phone = None
        duplicate.email = None
        duplicate.save(update_fields=['phone', 'second_phone', 'email'])
        primary.save()
        duplicate.delete()


def _merge_clients_manual(request):
    primary = Client.objects.filter(pk=request.POST.get('primary_client_id')).first()
    duplicate = Client.objects.filter(pk=request.POST.get('duplicate_client_id')).first()
    if not primary or not duplicate or primary.pk == duplicate.pk:
        messages.error(request, 'Не удалось определить пары для объединения.')
        return redirect(f"{reverse('crm:dashboard')}?page=clients")

    primary_name = primary.name
    duplicate_name = duplicate.name
    _merge_clients(primary, duplicate)
    _log_action(request, 'Merge clients', before=duplicate_name, after=primary_name)
    messages.success(request, f'Карточки {primary_name} и {duplicate_name} объединены.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients&client={primary.pk}")


def _create_task(request):
    title = request.POST.get('title', '').strip()
    if not title:
        messages.error(request, 'Введите название тикета.')
        return redirect(reverse('crm:dashboard'))
    due_at = request.POST.get('due_at')
    if due_at:
        due_at = datetime.fromisoformat(due_at)
        if timezone.is_naive(due_at):
            due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
    else:
        due_at = timezone.now() + timedelta(hours=1)
    Task.objects.create(
        title=title,
        priority=int(request.POST.get('priority', '3')),
        urgency=request.POST.get('urgency', 'normal'),
        due_at=due_at,
        status=request.POST.get('status', 'new'),
        origin=request.POST.get('origin', Task.Origin.INTERNAL),
        assigned_to=User.objects.filter(pk=request.POST.get('assigned_to')).first(),
        client=Client.objects.filter(pk=request.POST.get('client_id')).first() if request.POST.get('client_id') else None,
        comments=[],
    )
    _log_action(request, 'Create task', before='new', after=title)
    messages.success(request, 'Тикет создан.')
    return redirect(f"{reverse('crm:dashboard')}?page=tasks")


def _send_message(request):
    client = Client.objects.filter(pk=request.POST.get('client_id')).first() if request.POST.get('client_id') else None
    text = request.POST.get('text', '').strip()
    channel = request.POST.get('channel', '').strip() or (client.preferred_channel if client else 'Telegram')
    if client is None:
        messages.error(request, 'Сначала выберите клиента.')
        return redirect(f"{reverse('crm:dashboard')}?page=inbox")
    if not text:
        messages.error(request, 'Введите текст сообщения.')
        return redirect(_redirect_to_client(request, getattr(client, 'pk', None)))

    ok, result_message, contact = _dispatch_outbound_message(channel, client, text)
    if not ok:
        _log_action(request, 'Send message failed', before=channel, after=result_message)
        messages.error(request, result_message or 'Не удалось отправить сообщение.')
        return redirect(f"{reverse('crm:dashboard')}?page=inbox&client={getattr(client, 'pk', '')}")

    Message.objects.create(
        channel=channel,
        direction=Message.Direction.OUTBOUND,
        client=client,
        author_name=request.user.get_full_name() or request.user.username,
        contact=contact,
        text=text,
        unread=False,
        assigned_to=request.user,
    )
    # Ответив клиенту, помечаем его входящие как прочитанные — иначе счётчик
    # «не отвечено» растёт бесконечно и теряет смысл.
    Message.objects.filter(
        client=client, direction=Message.Direction.INBOUND, unread=True,
    ).update(unread=False)
    client.history = (client.history or []) + [{
        'type': 'message',
        'text': f'Отправлено сообщение через {channel}: {result_message or "успешно"}',
        'at': timezone.now().isoformat(),
    }]
    client.preferred_channel = channel
    client.save(update_fields=['history', 'preferred_channel', 'updated_at'])
    _log_action(request, 'Send message', before=channel, after=text[:120])
    messages.success(request, 'Сообщение отправлено.')
    return redirect(f"{reverse('crm:dashboard')}?page=inbox&client={getattr(client, 'pk', '')}")


def _sync_1c(request):
    uploaded_file = request.FILES.get('one_c_file')
    source = uploaded_file or getattr(settings, 'ONE_C_NOMENCLATURE_PATH', '')
    if not source:
        messages.error(request, 'Загрузите XLSX-файл номенклатуры 1С.')
        return redirect(f"{reverse('crm:dashboard')}?page=products")

    try:
        stats = import_nomenclature(source)
    except Exception as e:
        messages.error(request, f'Не удалось импортировать номенклатуру 1С: {e}')
        return redirect(f"{reverse('crm:dashboard')}?page=products")

    waitlist_count = _create_waitlist_tasks()
    relation_errors = [
        product.name
        for product in Product.objects.filter(kind=Product.ProductKind.PLANT)
        if not (product.parent or '').strip() or (product.parent or '').strip() == (product.name or '').strip()
    ]
    if relation_errors:
        NewsItem.objects.create(
            title='Ошибка связи номенклатуры после синхронизации 1С',
            body='Найдены товары без корректной родительской номенклатуры: ' + ', '.join(relation_errors[:10]),
            published_at=timezone.now(),
        )
    source_name = uploaded_file.name if uploaded_file else os.path.basename(str(source))
    _log_action(
        request,
        'Sync 1C',
        before=source_name,
        after=(
            f'created={stats.created}, updated={stats.updated}, '
            f'skipped={stats.skipped}, demo_deleted={stats.deleted_demo}'
        ),
    )
    messages.success(
        request,
        'Номенклатура 1С импортирована: '
        f'создано {stats.created}, обновлено {stats.updated}, '
        f'без изменений {stats.skipped}, удалено демо {stats.deleted_demo}. '
        f'Автозадач по листу ожидания: {waitlist_count}.'
    )
    return redirect(f"{reverse('crm:dashboard')}?page=products")


def _poll_avito(request):
    from .avito_playwright import poll_avito_playwright
    from .avito_parser import poll_avito_mailbox
    try:
        result = poll_avito_playwright()
    except Exception as e:
        logger.warning('Playwright Avito failed, falling back to email: %s', e)
        result = poll_avito_mailbox()
    status = result.get('status', 'error')
    imported = result.get('imported', 0)
    msg = result.get('message', '')
    if status == 'ok' and imported > 0:
        messages.success(request, f'Авито: импортировано {imported} сообщений.')
        _log_action(request, 'Poll Avito', before='mailbox', after=f'{imported} messages imported')
    elif status == 'ok':
        messages.info(request, 'Авито: новых писем нет.')
    else:
        messages.warning(request, f'Авито: {msg}')
    return redirect(f"{reverse('crm:dashboard')}?page=products")


def _poll_manual_messages(request):
    from .avito_playwright import poll_avito_playwright
    from .avito_parser import poll_avito_mailbox
    from .tg_integration import poll_tg_messages
    from .vk_integration import poll_vk_messages

    results = []

    try:
        avito_result = poll_avito_playwright()
    except Exception as e:
        logger.warning('Playwright Avito failed during manual poll, falling back to email: %s', e)
        avito_result = poll_avito_mailbox()
    results.append(('Авито', avito_result))

    try:
        results.append(('VK', poll_vk_messages()))
    except Exception as e:
        logger.error('Manual VK poll failed: %s', e)
        results.append(('VK', {'status': 'error', 'message': str(e), 'imported': 0}))

    try:
        results.append(('Telegram', poll_tg_messages()))
    except Exception as e:
        logger.error('Manual Telegram poll failed: %s', e)
        results.append(('Telegram', {'status': 'error', 'message': str(e), 'imported': 0}))

    imported_total = 0
    has_error = False
    summary_parts = []

    for channel_name, result in results:
        status = result.get('status', 'error')
        imported = int(result.get('imported', 0) or 0)
        imported_total += imported
        if status == 'ok':
            summary_parts.append(f'{channel_name}: {imported}')
        else:
            has_error = True
            summary_parts.append(f"{channel_name}: {result.get('message', 'ошибка')}")

    summary = '; '.join(summary_parts)
    if imported_total > 0:
        messages.success(request, f'Забор сообщений выполнен. Импортировано: {summary}.')
        _log_action(request, 'Manual message poll', before='channels', after=summary)
    elif has_error:
        messages.warning(request, f'Забор сообщений выполнен с ошибками. {summary}.')
    else:
        messages.info(request, f'Новых сообщений нет. {summary}.')

    return redirect(f"{reverse('crm:dashboard')}?page=inbox")


def _start_avito_web_login(request):
    from .avito_playwright import start_avito_web_login

    result = start_avito_web_login()
    status = result.get('status', 'error')
    msg = result.get('message', '')
    if status == 'ok':
        messages.success(request, f'Авито: {msg}')
    elif status == 'code_required':
        messages.info(request, f'Авито: {msg}')
    elif status == 'captcha_required':
        messages.warning(request, f'Авито: {msg}')
    else:
        messages.warning(request, f'Авито: {msg}')
    return redirect(f"{reverse('crm:dashboard')}?page=products")


def _confirm_avito_web_login(request):
    from .avito_playwright import confirm_avito_web_login

    code = request.POST.get('avito_code', '').strip()
    result = confirm_avito_web_login(code)
    status = result.get('status', 'error')
    msg = result.get('message', '')
    if status == 'ok':
        messages.success(request, f'Авито: {msg}')
    elif status == 'captcha_required':
        messages.warning(request, f'Авито: {msg}')
    else:
        messages.warning(request, f'Авито: {msg}')
    return redirect(f"{reverse('crm:dashboard')}?page=products")



def _poll_vk(request):
    from .vk_integration import poll_vk_messages
    result = poll_vk_messages()
    status = result.get('status', 'error')
    imported = result.get('imported', 0)
    msg = result.get('message', '')
    if status == 'ok' and imported > 0:
        messages.success(request, f'VK: импортировано {imported} сообщений.')
        _log_action(request, 'Poll VK', before='vk', after=f'{imported} messages imported')
    elif status == 'ok':
        messages.info(request, 'VK: новых сообщений нет.')
    else:
        messages.warning(request, f'VK: {msg}')
    return redirect(f"{reverse('crm:dashboard')}?page=products")



def _poll_tg(request):
    from .tg_integration import poll_tg_messages
    result = poll_tg_messages()
    status = result.get('status', 'error')
    imported = result.get('imported', 0)
    msg = result.get('message', '')
    if status == 'ok' and imported > 0:
        messages.success(request, f'Telegram: импортировано {imported} сообщений.')
        _log_action(request, 'Poll TG', before='telegram', after=f'{imported} messages imported')
    elif status == 'ok':
        messages.info(request, 'Telegram: новых сообщений нет.')
    else:
        messages.warning(request, f'Telegram: {msg}')
    return redirect(f"{reverse('crm:dashboard')}?page=products")


def _sync_bank(request):
    uploaded_file = request.FILES.get('bank_csv')
    if not uploaded_file:
        messages.error(request, 'Загрузите CSV-файл банковской выписки.')
        return redirect(f"{reverse('crm:dashboard')}?page=clients")

    raw_csv = _decode_uploaded_csv(uploaded_file).strip()
    if not raw_csv:
        messages.error(request, 'Файл выписки пустой.')
        return redirect(f"{reverse('crm:dashboard')}?page=clients")

    reader = csv.reader(io.StringIO(raw_csv), delimiter=';')
    existing_keys = _existing_bank_import_keys()
    imported = 0
    skipped = 0
    created = 0
    updated = 0

    for row in reader:
        if len(row) < 3:
            skipped += 1
            continue

        amount_raw, payer_raw, paid_at_raw = (item.strip() for item in row[:3])
        if not payer_raw:
            skipped += 1
            continue

        amount = _parse_bank_amount(amount_raw)
        paid_at = _parse_bank_timestamp(paid_at_raw)

        if ',' in payer_raw:
            phone_raw, payer_name_raw = (part.strip() for part in payer_raw.split(',', 1))
        else:
            phone_raw, payer_name_raw = payer_raw, ''

        phone = _normalize_phone(phone_raw)
        payer_name = _normalize_payer_name(payer_name_raw)

        if not phone:
            skipped += 1
            continue

        import_key = _build_bank_import_key(phone, amount, paid_at, payer_name, paid_at_raw)
        if import_key in existing_keys:
            skipped += 1
            continue

        client = _find_client_by_normalized_phone(phone)
        is_new_client = client is None
        last_name, first_name, patronymic = split_client_name(payer_name)
        if client is None:
            client = Client.objects.create(
                name=payer_name,
                last_name=last_name,
                first_name=first_name,
                patronymic=patronymic,
                phone=phone,
                source='Банк CSV',
                preferred_channel='Телефон',
                status=Client.Status.BUYER,
                first_purchase_at=paid_at,
            )
            created += 1
        else:
            if payer_name and client.name != payer_name:
                client.name = payer_name
            if payer_name:
                client.last_name = client.last_name or last_name
                client.first_name = client.first_name or first_name
                client.patronymic = client.patronymic or patronymic
            if client.phone != phone:
                client.phone = phone
            if not client.source:
                client.source = 'Банк CSV'
            if paid_at and (client.first_purchase_at is None or paid_at < client.first_purchase_at):
                client.first_purchase_at = paid_at
            client.status = Client.Status.BUYER
            updated += 1

        bank_purchases = list(client.bank_purchases or [])
        bank_purchases.append({
            'amount': amount,
            'at': paid_at.isoformat() if paid_at else paid_at_raw,
            'matched': True,
            'source': 'bank_csv',
            'phone': phone,
            'payer_name': payer_name,
            'import_key': import_key,
        })
        history = list(client.history or [])
        history.append({
            'type': 'purchase',
            'text': f'Оплата подтверждена по банковской выписке на сумму {_fmt_money(amount)}',
            'at': timezone.now().isoformat(),
        })
        client.bank_purchases = bank_purchases
        client.history = history
        update_fields = ['bank_purchases', 'history', 'status', 'updated_at']
        if payer_name:
            update_fields.extend(['name', 'last_name', 'first_name', 'patronymic'])
        if phone:
            update_fields.append('phone')
        if paid_at:
            update_fields.append('first_purchase_at')
        if is_new_client:
            client.save()
        else:
            if client.source == 'Банк CSV':
                update_fields.append('source')
            client.save(update_fields=sorted(set(update_fields)))
        existing_keys.add(import_key)
        imported += 1

    _log_action(request, 'Sync bank CSV', before=uploaded_file.name, after=f'imported={imported}, skipped={skipped}, created={created}, updated={updated}')
    messages.success(request, f'Выписка обработана: импортировано {imported}, пропущено {skipped}, создано {created}, обновлено {updated}.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients")


def _toggle_user(request):
    user = get_object_or_404(User, pk=request.POST.get('user_id'))
    if user == request.user and user.is_active:
        messages.error(request, 'Нельзя заблокировать текущего администратора.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    _log_action(request, 'Toggle user', before=str(not user.is_active), after=str(user.is_active))
    messages.success(request, 'Статус пользователя изменен.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _update_user(request):
    user = get_object_or_404(User, pk=request.POST.get('user_id'))
    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '').strip()
    role = request.POST.get('role', '').strip()
    schedule = request.POST.get('schedule', '').strip()
    is_active = request.POST.get('is_active') == 'on'
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    if password:
        user.set_password(password)
    user.is_active = is_active
    if role == EmployeeProfile.Role.ADMIN:
        user.is_staff = True
        user.is_superuser = True
    elif role:
        user.is_staff = False
        user.is_superuser = False
    user.save()
    profile, _ = EmployeeProfile.objects.get_or_create(user=user)
    if role:
        profile.role = role
    profile.schedule = schedule
    profile.work_email = email
    profile.save()
    _log_action(request, 'Update user', before=user.username, after=f'role={role}')
    messages.success(request, f'Пользователь {user.username} обновлён.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _create_user(request):
    username = request.POST.get('username', '').strip()
    if not username:
        messages.error(request, 'Имя пользователя обязательно.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    if User.objects.filter(username=username).exists():
        messages.error(request, f'Пользователь {username} уже существует.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    password = request.POST.get('password', 'temp123').strip()
    role = request.POST.get('role', 'front').strip()
    user = User.objects.create_user(username=username, password=password)
    user.first_name = request.POST.get('first_name', '').strip()
    user.last_name = request.POST.get('last_name', '').strip()
    user.email = request.POST.get('email', '').strip()
    if role == EmployeeProfile.Role.ADMIN:
        user.is_staff = True
        user.is_superuser = True
    user.save()
    EmployeeProfile.objects.create(
        user=user,
        role=role,
        schedule='09:00-18:00',
        work_email=user.email,
    )
    _log_action(request, 'Create user', after=username)
    messages.success(request, f'Пользователь {username} создан.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _delete_user(request):
    user = get_object_or_404(User, pk=request.POST.get('user_id'))
    username = user.username
    user.delete()
    _log_action(request, 'Delete user', before=username)
    messages.success(request, f'Пользователь {username} удалён.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _import_csv_users(request):
    raw_csv = request.POST.get('csv_data', '').strip()
    if not raw_csv:
        messages.error(request, 'CSV пустой.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    reader = csv.DictReader(io.StringIO(raw_csv))
    count = 0
    for row in reader:
        username = row.get('login', '').strip()
        if not username:
            continue
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = row.get('name', '').strip().split(' ')[0] if row.get('name') else user.first_name
        user.last_name = ' '.join(row.get('name', '').strip().split(' ')[1:]) if row.get('name') and len(row.get('name', '').split(' ')) > 1 else user.last_name
        user.email = row.get('email', '').strip()
        if row.get('password'):
            user.set_password(row['password'])
        else:
            user.set_password('temp123')
        user.is_active = str(row.get('active', 'true')).lower() == 'true'
        user.save()
        profile, _ = EmployeeProfile.objects.get_or_create(user=user)
        profile.role = row.get('role', EmployeeProfile.Role.FRONT)
        profile.work_email = row.get('email', '').strip()
        profile.schedule = row.get('schedule', '09:00-18:00')
        profile.save()
        count += 1
    _log_action(request, 'CSV import', before='users', after=f'{count} rows')
    messages.success(request, f'Импортировано {count} пользователей.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _generate_follow_up(request):
    count = _create_follow_up_tasks()
    _log_action(request, 'Auto follow-up', before='manual', after=f'{count} tasks')
    messages.success(request, f'Создано {count} follow-up задач.')
    return redirect(f"{reverse('crm:dashboard')}?page=tasks")


def _quick_test_start(request):
    question_data = random.choice(QUIZ_BANK)
    request.session['quick_test_question'] = question_data['question']
    request.session['quick_test_answer'] = question_data['answer']
    request.session['quick_test_accept'] = question_data['acceptable']
    request.session['quick_test_started_at'] = timezone.now().isoformat()
    request.session['quick_test_deadline_at'] = (timezone.now() + timedelta(seconds=45)).isoformat()
    request.session['quick_test_attempts'] = 0
    _log_action(request, 'Quick test start', before='knowledge', after=question_data['question'])
    return redirect(f"{reverse('crm:dashboard')}?page=knowledge")


def _quick_test_answer(request):
    answer = request.POST.get('quick_answer', '').strip().lower()
    expected = request.session.get('quick_test_answer', '').strip().lower()
    acceptable = [item.strip().lower() for item in request.session.get('quick_test_accept', [])]
    deadline_at = request.session.get('quick_test_deadline_at')
    attempts = int(request.session.get('quick_test_attempts', 0)) + 1
    request.session['quick_test_attempts'] = attempts
    if deadline_at:
        try:
            if timezone.now() > datetime.fromisoformat(deadline_at):
                messages.error(request, 'Время на ответ истекло. Тест перезапущен.')
                _log_action(request, 'Quick test timeout', before=deadline_at, after=f'attempts={attempts}')
                return _quick_test_reset(request)
        except ValueError:
            pass
    if answer and (
        answer == expected
        or any(token and token in answer for token in acceptable)
    ):
        request.session.pop('quick_test_question', None)
        request.session.pop('quick_test_answer', None)
        request.session.pop('quick_test_accept', None)
        request.session.pop('quick_test_started_at', None)
        request.session.pop('quick_test_deadline_at', None)
        request.session.pop('quick_test_attempts', None)
        _log_action(request, 'Quick test pass', before='knowledge', after=f'attempts={attempts}')
        messages.success(request, 'Быстрый тест пройден.')
    else:
        _log_action(request, 'Quick test fail', before='knowledge', after=f'attempts={attempts}')
        messages.error(request, 'Неверный ответ.')
    return redirect(f"{reverse('crm:dashboard')}?page=knowledge")


def _simulate_incoming(request):
    client = Client.objects.order_by('?').first()
    channel = random.choice(['Telegram', 'VK', 'WhatsApp', 'Email', 'Сайт', 'Flowwow', 'Авито'])
    Message.objects.create(
        channel=channel,
        direction=Message.Direction.INBOUND,
        client=client,
        author_name=client.name if client else 'Новый контакт',
        contact=client.phone if client else '',
        text=f'Авто-входящее сообщение от {client.name if client else "нового контакта"}',
        unread=True,
        assigned_to=request.user,
    )
    if client:
        client.history = (client.history or []) + [{'type': 'message', 'text': f'Входящее через {channel}', 'at': timezone.now().isoformat()}]
        client.save(update_fields=['history', 'updated_at'])
    _log_action(request, 'Incoming message', before='random', after=channel)
    messages.success(request, 'Смоделировано входящее сообщение.')
    return redirect(f"{reverse('crm:dashboard')}?page=inbox&client={getattr(client, 'pk', '')}")


def _dict_add(request):
    dict_type = request.POST.get('dict_type', '').strip()
    key = request.POST.get('key', '').strip()
    label = request.POST.get('label', '').strip()
    sort_order = int(request.POST.get('sort_order', '0') or 0)
    if dict_type and key:
        DictionaryEntry.objects.update_or_create(
            dict_type=dict_type,
            key=key,
            defaults={'label': label or key, 'sort_order': sort_order},
        )
        _log_action(request, 'Dictionary add', before=dict_type, after=key)
        messages.success(request, f'Элемент «{label or key}» добавлен в словарь.')
    else:
        messages.error(request, 'Укажите тип и ключ словаря.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _dict_update(request):
    entry = DictionaryEntry.objects.filter(pk=request.POST.get('entry_id')).first()
    if not entry:
        messages.error(request, 'Элемент словаря не найден.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    new_key = request.POST.get('key', '').strip()
    new_label = request.POST.get('label', '').strip()
    sort_order = int(request.POST.get('sort_order', '0') or 0)
    if not new_key:
        messages.error(request, 'Ключ словаря не может быть пустым.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    duplicate = DictionaryEntry.objects.filter(dict_type=entry.dict_type, key=new_key).exclude(pk=entry.pk).exists()
    if duplicate:
        messages.error(request, f'Ключ {new_key} уже существует.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    before = str(entry)
    entry.key = new_key
    entry.label = new_label or new_key
    entry.sort_order = sort_order
    entry.save()
    _log_action(request, 'Dictionary update', before=before, after=str(entry))
    messages.success(request, 'Элемент словаря обновлён.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _dict_delete(request):
    entry_id = request.POST.get('entry_id')
    entry = DictionaryEntry.objects.filter(pk=entry_id).first()
    if entry:
        _log_action(request, 'Dictionary delete', before=str(entry), after='removed')
        entry.delete()
        messages.success(request, 'Элемент удалён.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _save_permission(request):
    role = request.POST.get('role', '').strip()
    resource = request.POST.get('resource', '').strip()
    if role not in dict(EmployeeProfile.Role.choices) or resource not in dict(RolePermission.Resource.choices):
        messages.error(request, 'Некорректная роль или ресурс.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    permission, _ = RolePermission.objects.get_or_create(role=role, resource=resource)
    permission.can_read = request.POST.get('can_read') == 'on'
    permission.can_write = request.POST.get('can_write') == 'on'
    permission.can_delete = request.POST.get('can_delete') == 'on'
    permission.save()
    _log_action(
        request,
        'Update role permission',
        before=f'{role}:{resource}',
        after=f'r={permission.can_read},w={permission.can_write},d={permission.can_delete}',
    )
    messages.success(request, 'Права роли обновлены.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _upload_file(request):
    uploaded = request.FILES.get('file')
    tag = request.POST.get('tag', '').strip()
    if not uploaded:
        messages.error(request, 'Выберите файл.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")

    s3_key = ''
    s3_url = ''
    s3_bucket = settings.AWS_STORAGE_BUCKET_NAME

    if settings.AWS_ACCESS_KEY_ID and settings.AWS_STORAGE_BUCKET_NAME:
        try:
            client = boto3.client(
                's3',
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                region_name=settings.AWS_S3_REGION_NAME,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3_key = f'uploads/{timezone.now():%Y/%m/%d}/{uploaded.name}'
            client.upload_fileobj(uploaded, settings.AWS_STORAGE_BUCKET_NAME, s3_key)
            s3_url = f'{settings.AWS_S3_ENDPOINT_URL}/{settings.AWS_STORAGE_BUCKET_NAME}/{s3_key}'
            _log_action(request, 'File upload S3', before='local', after=s3_key)
            messages.success(request, f'Файл «{uploaded.name}» загружен в S3.')
        except Exception as e:
            _log_action(request, 'File upload S3 error', before='error', after=str(e))
            messages.error(request, f'Ошибка загрузки в S3: {e}')
            return redirect(f"{reverse('crm:dashboard')}?page=admin")
    else:
        _log_action(request, 'File upload stub', before='none', after=uploaded.name)
        messages.success(request, f'Файл «{uploaded.name}» загружен локально (S3 не настроено).')

    UploadedFile.objects.create(
        original_name=uploaded.name,
        s3_key=s3_key,
        s3_bucket=s3_bucket,
        s3_url=s3_url,
        file_size=uploaded.size,
        content_type=uploaded.content_type or '',
        tag=tag,
        uploaded_by=request.user if request.user.is_authenticated else None,
    )
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _wishlist_trigger(request):
    count = _create_waitlist_tasks()
    _log_action(request, 'Wishlist trigger', before='check', after=f'{count} tasks')
    messages.success(request, f'Создано {count} автозадач по триггеру wishlist.')
    return redirect(f"{reverse('crm:dashboard')}?page=tasks")


def _create_order(request):
    client = Client.objects.filter(pk=request.POST.get('client_id')).first()
    if not client:
        messages.error(request, 'Выберите клиента.')
        return redirect(f"{reverse('crm:dashboard')}?page=clients")
    items_raw = request.POST.get('items', '')
    items = []
    total = 0
    for line in items_raw.split('\n'):
        line = line.strip()
        if not line:
            continue
        parts = line.split(',')
        if len(parts) >= 3:
            name = parts[0].strip()
            qty = int(parts[1].strip())
            price = float(parts[2].strip())
            items.append({'name': name, 'qty': qty, 'price': price, 'sku': parts[3].strip() if len(parts) > 3 else ''})
            total += qty * price
    notes = request.POST.get('notes', '').strip()
    order = Order.objects.create(client=client, items=items, total=total, notes=notes, history=[])
    client.history = (client.history or []) + [{'type': 'order', 'text': f'Создан заказ №{order.pk} на сумму {_fmt_money(total)}', 'at': timezone.now().isoformat()}]
    client.save(update_fields=['history', 'updated_at'])
    _log_action(request, 'Create order', before='new', after=f'order #{order.pk}')
    messages.success(request, f'Заказ №{order.pk} создан.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients&client={client.pk}")


def _update_order_status(request):
    order = Order.objects.filter(pk=request.POST.get('order_id')).first()
    if order:
        new_status = request.POST.get('status', '')
        if new_status in dict(Order.Status.choices):
            old_status = order.status
            order.status = new_status
            order.history = (order.history or []) + [{'from': old_status, 'to': new_status, 'at': timezone.now().isoformat()}]
            order.save()
            _log_action(request, 'Update order status', before=old_status, after=new_status)
            messages.success(request, f'Статус заказа №{order.pk} изменён.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients")


def _edit_order(request):
    order = Order.objects.filter(pk=request.POST.get('order_id')).first()
    if order:
        items_raw = request.POST.get('items', '')
        items = []
        total = 0
        for line in items_raw.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            if len(parts) >= 3:
                name = parts[0].strip()
                qty = int(parts[1].strip())
                price = float(parts[2].strip())
                items.append({'name': name, 'qty': qty, 'price': price, 'sku': parts[3].strip() if len(parts) > 3 else ''})
                total += qty * price
        notes = request.POST.get('notes', '').strip()
        order.items = items
        order.total = total
        order.notes = notes
        order.history = (order.history or []) + [{'action': 'edit', 'at': timezone.now().isoformat()}]
        order.save()
        _log_action(request, 'Edit order', before=f'order #{order.pk}', after='edited')
        messages.success(request, f'Заказ №{order.pk} обновлён.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients")


def _delete_order(request):
    order = Order.objects.filter(pk=request.POST.get('order_id')).first()
    if order:
        client = order.client
        pk = order.pk
        order.delete()
        if client:
            client.history = (client.history or []) + [{'type': 'order', 'text': f'Заказ №{pk} удалён', 'at': timezone.now().isoformat()}]
            client.save(update_fields=['history', 'updated_at'])
        _log_action(request, 'Delete order', before=f'order #{pk}', after='deleted')
        messages.success(request, f'Заказ №{pk} удалён.')
    return redirect(f"{reverse('crm:dashboard')}?page=clients")


def _save_article(request):
    title = request.POST.get('article_title', '').strip()
    role = request.POST.get('article_role', '').strip()
    body = request.POST.get('article_body', '').strip()
    article_id = request.POST.get('article_id', '').strip()
    if not title or not body:
        messages.error(request, 'Заполните название и текст статьи.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    article = KnowledgeArticle.objects.filter(pk=article_id).first() if article_id else None
    if article:
        article.title = title
        article.role = role
        article.body = body
        article.save()
        _log_action(request, 'Update article', before=str(article.id), after=title)
        messages.success(request, f'Статья «{title}» обновлена.')
    else:
        KnowledgeArticle.objects.create(title=title, role=role, body=body)
        _log_action(request, 'Create article', before='new', after=title)
        messages.success(request, f'Статья «{title}» создана.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _delete_article(request):
    article = KnowledgeArticle.objects.filter(pk=request.POST.get('article_id')).first()
    if article:
        _log_action(request, 'Delete article', before=article.title, after='removed')
        article.delete()
        messages.success(request, 'Статья удалена.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _add_shift(request):
    date_raw = request.POST.get('shift_date', '').strip()
    employee_id = request.POST.get('shift_employee', '').strip()
    role = request.POST.get('shift_role', '').strip()
    shift_date = _parse_optional_date(date_raw)
    employee = User.objects.filter(pk=employee_id).first() if employee_id else None
    valid_roles = {choice[0] for choice in EmployeeProfile.Role.choices}
    if not shift_date or not employee or role not in valid_roles:
        messages.error(request, 'Укажите дату, сотрудника и роль смены.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin#shifts")
    obj, created = ShiftAssignment.objects.get_or_create(
        date=shift_date, employee=employee, role=role,
        defaults={'note': request.POST.get('shift_note', '').strip()},
    )
    if not created:
        obj.note = request.POST.get('shift_note', '').strip()
        obj.save(update_fields=['note'])
    who = employee.get_full_name() or employee.username
    _log_action(request, 'Add shift', before='', after=f'{shift_date} {who} {role}')
    messages.success(request, 'Смена добавлена в график.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin#shifts")


def _delete_shift(request):
    shift = ShiftAssignment.objects.filter(pk=request.POST.get('shift_id')).first()
    if shift:
        _log_action(request, 'Delete shift', before=str(shift), after='removed')
        shift.delete()
        messages.success(request, 'Смена удалена.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin#shifts")


def _quick_test_reset(request):
    request.session.pop('quick_test_question', None)
    request.session.pop('quick_test_answer', None)
    request.session.pop('quick_test_accept', None)
    request.session.pop('quick_test_started_at', None)
    request.session.pop('quick_test_deadline_at', None)
    request.session.pop('quick_test_attempts', None)
    _log_action(request, 'Quick test reset', before='active', after='cancelled')
    messages.success(request, 'Тест сброшен.')
    return redirect(f"{reverse('crm:dashboard')}?page=knowledge")


def _clock_toggle(request):
    event = ClockEvent.objects.filter(user=request.user, clock_out__isnull=True).first()
    if event:
        event.clock_out = timezone.now()
        event.save(update_fields=['clock_out'])
        _log_action(request, 'Clock out', before=event.clock_in.isoformat(), after='clock_out')
        messages.success(request, 'Рабочий день завершён.')
    else:
        ClockEvent.objects.create(user=request.user, clock_in=timezone.now())
        _log_action(request, 'Clock in', before='', after=timezone.now().isoformat())
        messages.success(request, 'Рабочий день начат.')
    return redirect(f"{reverse('crm:dashboard')}?page=dashboard")


def _reassign_task(request):
    task = Task.objects.filter(pk=request.POST.get('task_id')).first()
    if task:
        new_user = User.objects.filter(pk=request.POST.get('assigned_to')).first()
        if new_user:
            old = task.assigned_to.username if task.assigned_to else 'none'
            task.assigned_to = new_user
            task.comments = (task.comments or []) + [{'author': request.user.username, 'text': f'Переназначено на {new_user.username}', 'at': timezone.now().isoformat()}]
            task.save(update_fields=['assigned_to', 'comments'])
            _log_action(request, 'Reassign task', before=old, after=new_user.username)
            messages.success(request, f'Задача переназначена на {new_user.username}.')
    return redirect(f"{reverse('crm:dashboard')}?page=tasks")


def _export_clients_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="clients.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'ID', 'ID 1С', 'Фамилия', 'Имя', 'Отчество', 'Дата рождения', 'Телефон', 'Второй телефон',
        'Email', 'Дата первой покупки', 'Ссылка VK', 'Ссылка Telegram', 'Ссылка WhatsApp',
        'Район', 'Источник', 'Скидочная карта', 'Приоритетный канал', 'Статус', 'Теги', 'Интересы', 'Покупки',
    ])
    for client in Client.objects.all():
        writer.writerow([
            client.id,
            client.one_c_id or '',
            client.last_name or '',
            client.first_name or '',
            client.patronymic or '',
            client.birth_date.isoformat() if client.birth_date else '',
            client.phone or '',
            client.second_phone or '',
            client.email or '',
            client.first_purchase_at.isoformat() if client.first_purchase_at else '',
            client.vk_url or '',
            client.telegram_url or '',
            client.whatsapp_url or '',
            client.district or '',
            client.source or '',
            client.discount_card or '',
            client.preferred_channel or '',
            client.get_status_display(),
            ', '.join(client.tags or []),
            ', '.join(client.interests or []),
            client.purchase_count,
        ])
    _log_action(request, 'Export clients CSV', before='', after=f'{Client.objects.count()} rows')
    return response


def _export_products_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="products.csv"'
    writer = csv.writer(response)
    writer.writerow(['ID', 'Название', 'Родитель', 'SKU', 'Тип', 'Остаток', 'Резерв', 'Цена', 'В производстве', 'Статус'])
    for product in Product.objects.all():
        writer.writerow([product.id, product.name, product.parent, product.sku, product.get_kind_display(),
                         product.stock, product.reserve, product.price, product.in_production, product.get_status_display()])
    _log_action(request, 'Export products CSV', before='', after=f'{Product.objects.count()} rows')
    return response


def _export_analytics_csv(request):
    start_date = _parse_optional_date(request.POST.get('analytics_start')) or (timezone.localdate() - timedelta(days=29))
    end_date = _parse_optional_date(request.POST.get('analytics_end')) or timezone.localdate()
    snapshot = _analytics_snapshot(start_date, end_date)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="analytics_{snapshot["start_date"].isoformat()}_{snapshot["end_date"].isoformat()}.csv"'
    writer = csv.writer(response)
    writer.writerow(['LSG CRM Analytics'])
    writer.writerow(['Период', snapshot['analytics_summary']['period_label']])
    writer.writerow([])
    writer.writerow(['Сводка'])
    writer.writerow(['Показатель', 'Значение'])
    writer.writerow(['Новые клиенты', snapshot['analytics_summary']['period_clients']])
    writer.writerow(['Покупатели', snapshot['analytics_summary']['period_buyers']])
    writer.writerow(['Заказы', snapshot['analytics_summary']['period_orders']])
    writer.writerow(['Выручка', snapshot['analytics_summary']['period_revenue']])
    writer.writerow(['Конверсия, %', snapshot['analytics_summary']['conversion_rate']])
    writer.writerow(['Выполнение задач, %', snapshot['analytics_summary']['task_completion_rate']])
    writer.writerow(['Просрочка, %', snapshot['analytics_summary']['overdue_rate']])
    writer.writerow(['Средний ответ, мин', snapshot['analytics_summary']['avg_response_minutes'] or ''])
    writer.writerow([])
    writer.writerow(['Сотрудники'])
    writer.writerow(['Сотрудник', 'Роль', 'Сообщения', 'Задачи', 'Выполнено', 'Покупатели', 'Конверсия, %', 'Средний ответ, мин'])
    for row in snapshot['employee_kpi']:
        writer.writerow([
            row['name'],
            row['role'],
            row['messages'],
            row['tasks'],
            row['done'],
            row['buyers'],
            row['conversion'],
            row['avg_response_minutes'] or '',
        ])
    writer.writerow([])
    writer.writerow(['Каналы'])
    writer.writerow(['Канал', 'Клиенты', 'Покупатели', 'Входящие', 'Исходящие', 'Непрочитано', 'Конверсия, %', 'Ответы, %', 'Выручка'])
    for row in snapshot['channel_stats']:
        writer.writerow([
            row['channel'],
            row['clients'],
            row['buyers'],
            row['inbound'],
            row['outbound'],
            row['unread'],
            row['conversion'],
            row['answer_rate'],
            row['revenue'],
        ])
    _log_action(
        request,
        'Export analytics CSV',
        before=snapshot['analytics_summary']['period_label'],
        after=f"{len(snapshot['employee_kpi'])} employees",
    )
    return response


def _save_script(request):
    script_id = request.POST.get('script_id', '').strip()
    trigger = request.POST.get('trigger', '').strip()
    answer = request.POST.get('answer', '').strip()
    if not trigger or not answer:
        messages.error(request, 'Заполните триггер и ответ.')
        return redirect(f"{reverse('crm:dashboard')}?page=admin")
    if script_id:
        script = ScriptRule.objects.filter(pk=script_id).first()
        if script:
            script.trigger = trigger
            script.answer = answer
            script.save()
            _log_action(request, 'Update script', before=script.trigger, after=trigger)
            messages.success(request, f'Скрипт «{trigger}» обновлён.')
    else:
        ScriptRule.objects.create(trigger=trigger, answer=answer)
        _log_action(request, 'Create script', before='new', after=trigger)
        messages.success(request, f'Скрипт «{trigger}» создан.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _delete_script(request):
    script = ScriptRule.objects.filter(pk=request.POST.get('script_id')).first()
    if script:
        _log_action(request, 'Delete script', before=script.trigger, after='removed')
        script.delete()
        messages.success(request, 'Скрипт удалён.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _save_schedule(request):
    workday_start = request.POST.get('workday_start', '11:00')
    workday_end = request.POST.get('workday_end', '20:00')
    weekend_start = request.POST.get('weekend_start', '10:00')
    weekend_end = request.POST.get('weekend_end', '18:00')
    working_days = sorted({item for item in request.POST.getlist('working_days') if item in {'0', '1', '2', '3', '4', '5', '6'}})
    auto_reply_vk_enabled = request.POST.get('auto_reply_vk_enabled') == 'on'
    auto_reply_tg_enabled = request.POST.get('auto_reply_tg_enabled') == 'on'
    auto_reply_emergency_disabled = request.POST.get('auto_reply_emergency_disabled') == 'on'
    ignored_author_names = request.POST.get('ignored_author_names', '').strip()
    address = request.POST.get('address', '')
    message_template = request.POST.get('message_template', '')
    sched, _ = ScheduleSettings.objects.get_or_create(pk=1)
    sched.workday_start = workday_start
    sched.workday_end = workday_end
    sched.weekend_start = weekend_start
    sched.weekend_end = weekend_end
    sched.working_days = ','.join(working_days) or '1,2,3,4,5'
    sched.auto_reply_vk_enabled = auto_reply_vk_enabled
    sched.auto_reply_tg_enabled = auto_reply_tg_enabled
    sched.auto_reply_emergency_disabled = auto_reply_emergency_disabled
    sched.ignored_author_names = ignored_author_names
    sched.address = address
    if message_template:
        sched.message_template = message_template
    sched.save()
    _log_action(
        request,
        'Update schedule',
        before='edit',
        after=(
            f'{workday_start}-{workday_end}; days={sched.working_days}; '
            f'vk={sched.auto_reply_vk_enabled}; tg={sched.auto_reply_tg_enabled}; '
            f'emergency={sched.auto_reply_emergency_disabled}'
        ),
    )
    messages.success(request, 'Расписание сохранено.')
    return redirect(f"{reverse('crm:dashboard')}?page=admin")


def _redirect_to_client(request, client_id):
    page = request.GET.get('page', 'clients')
    return f"{reverse('crm:dashboard')}?page={page}&client={client_id or ''}"


@login_required
def client_detail_json(request, client_id):
    client = get_object_or_404(Client.objects.prefetch_related('messages', 'tasks', 'orders'), pk=client_id)
    messages_list = []
    for m in client.messages.all()[:20]:
        messages_list.append({
            'id': m.id,
            'channel': m.channel,
            'direction': m.get_direction_display(),
            'text': m.text,
            'author': m.author_name,
            'created_at': _fmt_dt(m.created_at),
        })
    tasks_list = []
    for t in client.tasks.all()[:10]:
        tasks_list.append({
            'id': t.id,
            'title': t.title,
            'status': t.get_status_display(),
            'priority': t.priority,
            'due_at': _fmt_dt(t.due_at),
        })
    orders_list = []
    for o in client.orders.all()[:10]:
        orders_list.append({
            'id': o.id,
            'status': o.get_status_display(),
            'total': str(o.total),
            'notes': o.notes,
            'items': o.items,
            'created_at': _fmt_dt(o.created_at),
        })
    return JsonResponse({
        'id': client.id,
        'name': client.name,
        'last_name': client.last_name or '',
        'first_name': client.first_name or '',
        'patronymic': client.patronymic or '',
        'birth_date': client.birth_date.isoformat() if client.birth_date else '',
        'phone': client.phone or '',
        'second_phone': client.second_phone or '',
        'email': client.email or '',
        'one_c_id': client.one_c_id or '',
        'source': client.source or '',
        'vk_url': client.vk_url or '',
        'telegram_url': client.telegram_url or '',
        'whatsapp_url': client.whatsapp_url or '',
        'district': client.district or '',
        'discount_card': client.discount_card or '',
        'first_purchase_at': _fmt_dt(client.first_purchase_at),
        'preferred_channel': client.preferred_channel or '',
        'status_label': client.status_label,
        'status_class': _status_class(client.status),
        'tags': client.tags,
        'interests': client.interests,
        'wish_list': client.wish_list,
        'wish_products': [
            {'id': p.id, 'name': p.name, 'stock': p.stock}
            for p in client.wish_products.all()[:50]
        ],
        'internal_note': client.internal_note or '',
        'quality': client.quality,
        'green_list': client.green_list,
        'black_list': client.black_list,
        'purchase_count': client.purchase_count,
        'messages': messages_list,
        'tasks': tasks_list,
        'orders': orders_list,
        'history': client.history[-10:] if client.history else [],
    })


@csrf_exempt
def site_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    if not _authorize_site_webhook(request):
        return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)

    payload = _extract_site_payload(request)
    event_type = str(payload.get('type') or payload.get('event') or '').strip().lower()
    if event_type not in {'order', 'wishlist'}:
        return JsonResponse({'ok': False, 'error': 'invalid_event_type'}, status=400)

    external_id = _site_event_external_id(event_type, payload)
    existing_event = IntegrationEvent.objects.filter(
        source='wordpress',
        event_type=event_type,
        external_id=external_id,
    ).first()
    if existing_event:
        return JsonResponse({'ok': True, 'status': 'duplicate', 'external_id': external_id})

    client, created = _find_or_create_site_client(payload)
    if created:
        client.save()
    else:
        client.save(update_fields=[
            'name', 'last_name', 'first_name', 'patronymic',
            'phone', 'email', 'vk_url', 'telegram_url', 'whatsapp_url',
            'source', 'preferred_channel', 'status', 'district', 'discount_card',
            'discount_cards', 'birth_date', 'updated_at',
        ])

    result = {'client_id': client.pk, 'external_id': external_id}

    if event_type == 'order':
        order = _create_site_order(client, payload, external_id)
        wish_items = _merge_site_wishlist(client, payload, external_id)
        result.update({'order_id': order.pk, 'wishlist_items': wish_items})
        _log_action(request, 'Website order import', before=external_id, after=f'client={client.pk},order={order.pk}')
    else:
        wish_items = _merge_site_wishlist(client, payload, external_id)
        result.update({'wishlist_items': wish_items})
        _log_action(request, 'Website wishlist import', before=external_id, after=f'client={client.pk},items={len(wish_items)}')

    IntegrationEvent.objects.create(
        source='wordpress',
        event_type=event_type,
        external_id=external_id,
        payload=payload,
    )
    return JsonResponse({'ok': True, 'status': 'created', **result}, status=201)
