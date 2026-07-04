from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import TelegramLoginSession
from .tg_integration import start_tg_qr_login, submit_tg_qr_password, tg_account_auth_status


def _superuser_required(view):
    return user_passes_test(lambda u: u.is_superuser)(view)


@_superuser_required
def telegram_qr_login_view(request):
    session = TelegramLoginSession.load()
    auth_status = tg_account_auth_status()
    return render(request, 'admin/telegram_qr_login.html', {
        'title': 'QR-вход в Telegram-аккаунт',
        'session': session,
        'auth_status': auth_status,
        'statuses': TelegramLoginSession.Status,
    })


@_superuser_required
def telegram_qr_login_start(request):
    if request.method != 'POST':
        return HttpResponseForbidden()
    start_tg_qr_login()
    return redirect(reverse('admin:telegram_qr_login'))


@_superuser_required
def telegram_qr_login_status(request):
    session = TelegramLoginSession.load()
    return JsonResponse({
        'status': session.status,
        'status_display': session.get_status_display(),
        'qr_data_uri': session.qr_data_uri,
        'message': session.message,
    })


@_superuser_required
def telegram_qr_login_password(request):
    if request.method != 'POST':
        return HttpResponseForbidden()
    submit_tg_qr_password(request.POST.get('password', ''))
    return redirect(reverse('admin:telegram_qr_login'))
