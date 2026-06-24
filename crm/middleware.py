from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.utils import timezone

from .models import FraudEvent


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
            if profile:
                profile.last_activity = timezone.now()
                profile.save(update_fields=['last_activity'])
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
                FraudEvent.objects.create(
                    employee=request.user,
                    ip_address=request.META.get('REMOTE_ADDR', ''),
                    action='Page view flood',
                    detail=f'{len(history)} views in {self.window_minutes} min',
                    blocked=True,
                )
                session['page_view_history'] = []
                logout(request)
                return HttpResponseForbidden('Доступ заблокирован за аномальную активность.')
        return self.get_response(request)
