from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def money(value):
    try:
        return f"{int(value or 0):,}".replace(',', ' ') + ' ₽'
    except Exception:
        return '0 ₽'


@register.filter
def dt(value):
    if not value:
        return ''
    try:
        return timezone.localtime(value).strftime('%d.%m, %H:%M')
    except Exception:
        return str(value)


@register.filter
def status_class(value):
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
        'in': 'warn',
        'out': 'good',
    }
    return mapping.get(str(value), 'info')
