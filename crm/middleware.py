from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.utils import timezone

from .models import AuditEntry, FraudEvent, NewsItem, Task


class AutoLogoutMiddleware:
    max_inactivity = timedelta(hours=5)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            if profile:
                if profile.last_activity and (timezone.now() - profile.last_activity) > self.max_inactivity:
                    logout(request)
                    return self.get_response(request)
        response = self.get_response(request)
        if request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            if profile and profile.pk:
                type(profile).objects.filter(pk=profile.pk).update(last_activity=timezone.now())
        return response


class RequestAuditMiddleware:
    ignored_prefixes = ('/static/', '/media/', '/favicon', '/admin/jsi18n/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if not getattr(user, 'is_authenticated', False):
            return response
        if any(request.path.startswith(prefix) for prefix in self.ignored_prefixes):
            return response
        if request.method not in {'GET', 'POST'}:
            return response

        if request.method == 'GET':
            action = f'Open {request.path}'
            after = request.GET.urlencode()[:500]
        else:
            post_data = request.POST.copy()
            if 'csrfmiddlewaretoken' in post_data:
                post_data.pop('csrfmiddlewaretoken')
            if 'password' in post_data:
                post_data['password'] = '***'
            action = f'POST {request.POST.get("action", request.path)}'
            after = '&'.join(f'{k}={v}' for k, v in post_data.items())[:500]

        AuditEntry.objects.create(
            actor=user.get_full_name() or user.username,
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            action=action,
            before=request.path[:255],
            after=after,
        )
        return response


class FraudDetectionMiddleware:
    page_threshold = 30
    window_minutes = 10

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.method == 'GET':
            session = request.session
            raw = session.get('page_view_history', [])
            now = timezone.now()
            cutoff = now - timedelta(minutes=self.window_minutes)
            history = []
            for ts in raw:
                if isinstance(ts, str):
                    try:
                        parsed = datetime.fromisoformat(ts)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=dt_timezone.utc)
                    except (ValueError, TypeError):
                        continue
                else:
                    parsed = ts
                if parsed > cutoff:
                    history.append(parsed)
            history.append(now)
            session['page_view_history'] = [h.isoformat() for h in history]
            if len(history) > self.page_threshold:
                user = request.user
                FraudEvent.objects.create(
                    employee=user,
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    action='Page view flood',
                    detail=f'{len(history)} views in {self.window_minutes} min',
                    blocked=True,
                )
                user.is_active = False
                user.save(update_fields=['is_active'])
                admin_user = User.objects.filter(is_staff=True, is_active=True).exclude(pk=user.pk).order_by('id').first()
                if admin_user:
                    Task.objects.create(
                        title=f'Антифрод: разблокировать {user.get_full_name() or user.username}',
                        priority=1,
                        urgency='urgent',
                        due_at=now,
                        status=Task.Status.NEW,
                        origin=Task.Origin.SYSTEM,
                        assigned_to=admin_user,
                        comments=[{
                            'author': 'CRM',
                            'text': f'Пользователь заблокирован за {len(history)} просмотров за {self.window_minutes} минут.',
                            'at': now.isoformat(),
                        }],
                    )
                NewsItem.objects.create(
                    title='Антифрод: сотрудник заблокирован',
                    body=(
                        f'Сотрудник {user.get_full_name() or user.username} автоматически заблокирован. '
                        f'Причина: {len(history)} просмотров за {self.window_minutes} минут. '
                        f'IP: {request.META.get("REMOTE_ADDR", "")}'
                    ),
                    published_at=now,
                )
                AuditEntry.objects.create(
                    actor='system',
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    action='Fraud auto block',
                    before=user.username,
                    after=f'blocked after {len(history)} views/{self.window_minutes}m',
                )
                session['page_view_history'] = []
                logout(request)
                return HttpResponseForbidden('Доступ заблокирован за аномальную активность.')
        return self.get_response(request)
