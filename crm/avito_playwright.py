import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.utils import timezone

from .models import Client, EmployeeProfile, Message, NewsItem

logger = logging.getLogger(__name__)

AVITO_CHANNEL = 'Авито'

AUTH_FILE = Path(settings.BASE_DIR) / getattr(settings, 'AVITO_AUTH_FILE', 'avito_auth.json')
COOKIES_FILE = Path(settings.BASE_DIR) / getattr(settings, 'AVITO_COOKIES_FILE', 'avito_cookies.json')
PENDING_AUTH_FILE = Path(settings.BASE_DIR) / 'avito_pending_auth.json'
PENDING_META_FILE = Path(settings.BASE_DIR) / 'avito_pending_meta.json'

_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)


def _get_credentials():
    username = getattr(settings, 'AVITO_USERNAME', '')
    password = getattr(settings, 'AVITO_PASSWORD', '')
    return username, password


def _browser_context(browser):
    if AUTH_FILE.exists():
        return browser.new_context(
            storage_state=str(AUTH_FILE),
            user_agent=_USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU',
            timezone_id='Europe/Moscow',
        )
    return browser.new_context(
        user_agent=_USER_AGENT,
        viewport={'width': 1920, 'height': 1080},
        locale='ru-RU',
        timezone_id='Europe/Moscow',
    )


def _goto(page, url: str):
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
    except Exception as e:
        logger.warning('Avito navigation warning for %s: %s', url, e)
    page.wait_for_timeout(2500)


def _admin_emails() -> list[str]:
    role_admins = list(User.objects.filter(profile__role=EmployeeProfile.Role.ADMIN).values_list('email', flat=True))
    superusers = list(User.objects.filter(is_superuser=True).values_list('email', flat=True))
    emails: list[str] = []
    for email in role_admins + superusers:
        normalized = str(email or '').strip()
        if normalized and normalized not in emails:
            emails.append(normalized)
    return emails


def _notify_avito_auth_issue(detail: str):
    now = timezone.now()
    title = 'Avito: требуется повторный вход'
    if not NewsItem.objects.filter(title=title, published_at__gte=now - timezone.timedelta(minutes=30)).exists():
        NewsItem.objects.create(title=title, body=detail, published_at=now)

    admin_emails = _admin_emails()
    if not admin_emails:
        return
    try:
        send_mail(
            subject=title,
            message=detail,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=admin_emails,
            fail_silently=True,
        )
    except Exception as e:
        logger.warning('Failed to send Avito notification email: %s', e)


def _save_session(context):
    context.storage_state(path=str(AUTH_FILE))
    cookies = context.cookies()
    COOKIES_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
    logger.info('Session saved to %s', AUTH_FILE)


def _save_pending_session(context, page):
    context.storage_state(path=str(PENDING_AUTH_FILE))
    PENDING_META_FILE.write_text(json.dumps({
        'url': page.url,
        'updated_at': timezone.now().isoformat(),
    }, ensure_ascii=False, indent=2))
    logger.info('Pending Avito session saved to %s', PENDING_AUTH_FILE)


def _clear_pending_session():
    for path in (PENDING_AUTH_FILE, PENDING_META_FILE):
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning('Failed to remove pending Avito auth file %s: %s', path, e)


def _pending_target_url() -> str:
    if PENDING_META_FILE.exists():
        try:
            payload = json.loads(PENDING_META_FILE.read_text(encoding='utf-8'))
            url = str(payload.get('url') or '').strip()
            if url:
                return url
        except Exception as e:
            logger.warning('Failed to read pending Avito auth meta: %s', e)
    return 'https://www.avito.ru/messages'


def _code_locator(page):
    selectors = [
        'input[name="code"]',
        'input[name*="otp" i]',
        'input[name*="sms" i]',
        'input[id*="code" i]',
        'input[id*="otp" i]',
        'input[data-marker*="code" i]',
        'input[data-marker*="otp" i]',
        'input[autocomplete="one-time-code"]',
        'input[placeholder*="код" i]',
        'input[inputmode="numeric"]',
        'input[type="tel"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None


def _page_text(page, limit: int = 6000) -> str:
    try:
        text = str(page.locator('body').inner_text(timeout=2000) or '')
    except Exception:
        try:
            text = str(page.inner_text('body', timeout=2000) or '')
        except Exception:
            return ''
    normalized = re.sub(r'\s+', ' ', text).strip()
    return normalized[:limit]


def _confirmation_required(page) -> bool:
    if _code_locator(page):
        return True

    url = page.url.casefold()
    url_tokens = [
        'code', 'otp', 'verify', 'verification', 'confirm', 'confirmation',
        'checkpoint', 'challenge', '2fa', 'sms', 'security-check', 'phone-confirm',
    ]
    if any(token in url for token in url_tokens):
        return True

    text = _page_text(page).casefold()
    phrases = [
        'введите код',
        'код подтверждения',
        'код из смс',
        'код из sms',
        'sms-код',
        'смс-код',
        'мы отправили код',
        'код отправлен',
        'отправили код',
        'пришлем код',
        'пришлём код',
        'одноразовый код',
        'проверочный код',
        'подтверждение входа',
        'подтвердите вход',
        'подтвердите, что это вы',
        'подтвердите номер телефона',
        'подтвердите номер',
        'подтвердите личность',
        'подтвердите телефон',
        'на ваш номер',
        'на ваш телефон',
        'на вашу почту',
        'на указанный номер',
        'позвоним и продиктуем',
        'выберите способ подтверждения',
        'способ получения кода',
        'получить код',
        'отправить код',
        'прислать код',
        'новое устройство',
        'необычный вход',
        'вход с нового устройства',
        'проверьте телефон',
        'проверьте почту',
        'we sent a code',
        'enter the code',
        'enter code',
        'verification code',
        'one-time code',
    ]
    return any(phrase in text for phrase in phrases)


def _captcha_required(page) -> bool:
    text = _page_text(page).casefold()
    phrases = [
        'капч',
        'captcha',
        'не робот',
        'подтвердите, что вы не робот',
        'необходима проверка',
        'подозрительн',
        'access denied',
        'unusual traffic',
        'доступ ограничен',
        'проблема с ip',
        'проблема с вашим ip',
        'слишком много запросов',
        'антибот',
        'anti-bot',
        'antibot',
        'заблокирован ip',
        'ограничен доступ',
    ]
    if any(phrase in text for phrase in phrases):
        return True
    try:
        return page.locator(
            'iframe[src*="captcha" i], iframe[title*="captcha" i], [class*="captcha" i], #captcha'
        ).first.is_visible(timeout=800)
    except Exception:
        return False


def _classify_auth_stage(page) -> str:
    """Returns 'code', 'captcha', or '' (no intermediate stage detected).

    An actual code input on the page is checked first since it is
    unambiguous. URL tokens like 'checkpoint'/'challenge' are shared between
    code-confirmation and captcha/robot-check flows, so captcha text/markup
    is checked before the broader code-phrase heuristics to avoid a captcha
    screen being misreported as a code step.
    """
    if _code_locator(page):
        return 'code'
    if _captcha_required(page):
        return 'captcha'
    if _confirmation_required(page):
        return 'code'
    return ''


def _auth_step_hint(page) -> str:
    stage = _classify_auth_stage(page)
    if stage == 'code':
        return 'Avito запросил код подтверждения.'
    if stage == 'captcha':
        return 'Avito запросил дополнительную проверку (капча/проверка на робота). Повторите вход позже или откройте его вручную.'
    return ''


def _first_visible_locator(page, selectors, timeout: int = 1200):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=timeout):
                return locator
        except Exception:
            continue
    return None


def _login_input_locator(page):
    selectors = [
        'input[name="login"]',
        'input[name="identifier"]',
        'input[autocomplete="username"]',
        'input[type="email"]',
        'input[inputmode="email"]',
        'input[placeholder*="телефон"]',
        'input[placeholder*="почт"]',
        'input[placeholder*="+7"]',
        'input[inputmode="tel"]',
    ]
    return _first_visible_locator(page, selectors)


def _password_input_locator(page):
    selectors = [
        'input[name="password"]',
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    ]
    return _first_visible_locator(page, selectors)


def _open_login_form(page) -> bool:
    if _login_input_locator(page) or _password_input_locator(page):
        return True

    selectors = [
        '[data-marker="header/login-button"]',
        'a[href*="/login"]',
        'button:has-text("Войти")',
        'button:has-text("Вход")',
        'a:has-text("Войти")',
        'a:has-text("Вход")',
    ]

    for selector in selectors:
        button = page.locator(selector).first
        try:
            if button.is_visible(timeout=1200):
                button.click()
                page.wait_for_timeout(2500)
                if _login_input_locator(page) or _password_input_locator(page):
                    return True
        except Exception:
            continue

    return _login_input_locator(page) is not None or _password_input_locator(page) is not None


def _submit_credentials(page, username: str, password: str) -> tuple[bool, str, str]:
    """Returns (submitted, message, stage). stage is 'code', 'captcha', or ''."""
    stage = _classify_auth_stage(page)
    if stage == 'captcha':
        return False, (
            'Avito запросил дополнительную проверку (капча или блокировка по IP). '
            'Попробуйте войти вручную или повторите попытку позже.'
        ), 'captcha'
    if stage == 'code':
        return False, 'Avito запросил код подтверждения.', 'code'

    if not _open_login_form(page):
        # The login form may be missing because Avito is showing an
        # anti-bot/IP-block interstitial or a confirmation step rather
        # than because the page markup actually changed — re-check before
        # blaming a broken form.
        stage = _classify_auth_stage(page)
        if stage == 'captcha':
            return False, (
                'Avito запросил дополнительную проверку (капча или блокировка по IP). '
                'Попробуйте войти вручную или повторите попытку позже.'
            ), 'captcha'
        if stage == 'code':
            return False, 'Avito запросил код подтверждения.', 'code'
        return False, 'CRM не нашла форму входа Avito. Возможно, Avito изменил страницу входа.', ''

    login_input = _login_input_locator(page)
    password_input = _password_input_locator(page)

    if login_input is not None:
        try:
            login_input.click()
            login_input.fill(username, timeout=4000)
        except Exception:
            return False, 'CRM не смогла заполнить логин Avito. Возможно, страница входа изменилась.', ''

    if password_input is None:
        _click_submit(page)
        page.wait_for_timeout(2000)
        password_input = _password_input_locator(page)

    if password_input is None:
        # Avito may show a "choose verification method" screen with no code
        # input yet — try to trigger sending the code before giving up.
        if _click_send_code_button(page):
            page.wait_for_timeout(2000)

        stage = _classify_auth_stage(page)
        if stage == 'code':
            return False, 'Avito запросил код подтверждения.', 'code'
        if stage == 'captcha':
            return False, (
                'Avito запросил дополнительную проверку (капча/проверка на робота). '
                'Повторите вход позже или откройте его вручную.'
            ), 'captcha'

        auth_error = _extract_auth_error(page)
        if auth_error:
            return False, auth_error, ''
        return False, 'CRM не нашла поле пароля Avito. Возможно, страница входа изменилась.', ''

    try:
        password_input.click()
        password_input.fill(password, timeout=4000)
    except Exception:
        return False, 'CRM не смогла заполнить пароль Avito. Возможно, страница входа изменилась.', ''

    _click_submit(page)
    page.wait_for_timeout(5000)
    return True, '', ''


def _extract_auth_error(page) -> str:
    selectors = [
        '[data-marker*="error"]',
        '[class*="error"]',
        '[role="alert"]',
        '[data-testid*="error"]',
    ]
    error_texts: list[str] = []
    for selector in selectors:
        try:
            locators = page.locator(selector)
            count = min(locators.count(), 8)
            for index in range(count):
                text = str(locators.nth(index).inner_text() or '').strip()
                if text and text not in error_texts:
                    error_texts.append(text)
        except Exception:
            continue

    combined = ' '.join(error_texts).strip()
    lower = combined.casefold()
    if not combined:
        return ''
    if 'невер' in lower and 'парол' in lower:
        return 'Неверный пароль Avito.'
    if 'невер' in lower and ('логин' in lower or 'телефон' in lower or 'почт' in lower):
        return 'Неверный логин Avito.'
    if 'невер' in lower and 'код' in lower:
        return 'Неверный код подтверждения Avito.'
    if 'слишком часто' in lower:
        return 'Avito временно ограничил попытки входа. Попробуйте позже.'
    if 'заблок' in lower:
        return 'Avito сообщает о блокировке или ограничении входа.'
    return combined


def _click_submit(page):
    selectors = [
        'button[type="submit"]',
        'button:has-text("Продолжить")',
        'button:has-text("Войти")',
        'button:has-text("Подтвердить")',
    ]
    for selector in selectors:
        button = page.locator(selector).first
        try:
            if button.is_visible(timeout=1000):
                button.click()
                return
        except Exception:
            continue


def _click_send_code_button(page) -> bool:
    """Clicks a 'choose verification method' style button (SMS/call/get code).

    Avito sometimes shows an interstitial screen after the login step asking
    how to receive the confirmation code, before any code input is rendered.
    """
    selectors = [
        'button:has-text("Получить код")',
        'button:has-text("Отправить код")',
        'button:has-text("Прислать код")',
        'button:has-text("Выслать код")',
        'button:has-text("По SMS")',
        'button:has-text("По СМС")',
        'button:has-text("Позвоните мне")',
        'a:has-text("Получить код")',
        'a:has-text("Отправить код")',
        '[data-marker*="sms"]',
        '[data-marker*="code"]',
    ]
    for selector in selectors:
        button = page.locator(selector).first
        try:
            if button.is_visible(timeout=1000):
                button.click()
                return True
        except Exception:
            continue
    return False


def _messages_page_open(page) -> bool:
    url = page.url.lower()
    if '/messages' in url:
        return True
    try:
        return page.locator('a[href*="/messages/"]').count() > 0
    except Exception:
        return False


def _login(page, username, password):
    _goto(page, 'https://www.avito.ru')
    submitted, submit_message, stage = _submit_credentials(page, username, password)
    if not submitted:
        if stage == 'code':
            logger.warning('SMS code required — cannot proceed automatically')
        elif stage == 'captcha':
            logger.warning('Avito captcha/challenge required — cannot proceed automatically')
        elif submit_message:
            logger.error('Avito login preparation error: %s', submit_message)
        return False, submit_message or 'Avito не подтвердил вход.'

    auth_error = _extract_auth_error(page)
    if auth_error:
        logger.error('Avito login error: %s', auth_error)
        return False, auth_error

    stage = _classify_auth_stage(page)
    if stage == 'code':
        logger.warning('SMS code required — cannot proceed automatically')
        return False, 'Avito запросил код подтверждения.'
    if stage == 'captcha':
        logger.warning('Avito captcha/challenge required — cannot proceed automatically')
        return False, (
            'Avito запросил дополнительную проверку (капча/проверка на робота). '
            'Повторите вход позже или откройте его вручную.'
        )

    if page.locator('[data-marker="header/login-button"]').is_visible():
        logger.warning('Login not confirmed — still on login page, no explicit Avito error or known stage detected')
        return False, (
            'Avito не завершил вход автоматически, явной ошибки логина/пароля нет. '
            'Возможно, требуется дополнительное подтверждение — попробуйте войти вручную.'
        )
    return True, ''


def _need_relogin(page):
    url = page.url.lower()
    return any(x in url for x in ['login', 'auth'])


def start_avito_web_login() -> dict:
    username, password = _get_credentials()
    if not username or not password:
        return {'status': 'error', 'message': 'Не настроены логин и пароль Avito.'}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'status': 'error', 'message': 'Playwright не установлен на сервере.'}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--headless=new',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                ],
            )
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={'width': 1920, 'height': 1080},
                locale='ru-RU',
                timezone_id='Europe/Moscow',
            )
            page = context.new_page()
            _goto(page, 'https://www.avito.ru')
            submitted, submit_message, stage = _submit_credentials(page, username, password)
            if not submitted:
                if stage == 'code':
                    _save_pending_session(context, page)
                    browser.close()
                    return {'status': 'code_required', 'message': 'Код отправлен. Введите код из СМС в CRM.'}
                if stage == 'captcha':
                    browser.close()
                    return {
                        'status': 'captcha_required',
                        'message': submit_message or (
                            'Avito запросил дополнительную проверку (капча/проверка на робота). '
                            'Повторите вход позже или откройте его вручную.'
                        ),
                    }
                browser.close()
                return {
                    'status': 'error',
                    'message': submit_message or 'CRM не смогла отправить логин и пароль Avito.',
                }

            auth_error = _extract_auth_error(page)
            if auth_error:
                browser.close()
                return {'status': 'error', 'message': auth_error}

            stage = _classify_auth_stage(page)
            if stage == 'code':
                _save_pending_session(context, page)
                browser.close()
                return {'status': 'code_required', 'message': 'Код отправлен. Введите код из СМС в CRM.'}
            if stage == 'captcha':
                browser.close()
                return {
                    'status': 'captcha_required',
                    'message': (
                        'Avito запросил дополнительную проверку (капча/проверка на робота). '
                        'Повторите вход позже или откройте его вручную.'
                    ),
                }

            if _messages_page_open(page) or not _need_relogin(page):
                _save_session(context)
                _clear_pending_session()
                browser.close()
                return {'status': 'ok', 'message': 'Avito успешно авторизован.'}

            # Вход не завершён, но и явной ошибки логина/пароля от Avito нет —
            # сохраняем сессию как pending на случай, если код придёт позже
            # или потребуется досмотреть/повторить подтверждение вручную.
            _save_pending_session(context, page)
            browser.close()
            return {
                'status': 'code_required',
                'message': (
                    'Avito не завершил вход автоматически. Явной ошибки логина/пароля нет — '
                    'похоже, требуется дополнительное подтверждение. Если пришёл код, введите его в CRM, '
                    'иначе войдите вручную.'
                ),
            }
    except Exception as e:
        logger.error('Avito web login start error: %s', e)
        return {'status': 'error', 'message': str(e)}


def confirm_avito_web_login(code: str) -> dict:
    verification_code = str(code or '').strip()
    if not verification_code:
        return {'status': 'error', 'message': 'Введите код из СМС.'}
    if not PENDING_AUTH_FILE.exists():
        return {'status': 'error', 'message': 'Нет активного запроса кода. Сначала нажмите «Запросить код Avito».'}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'status': 'error', 'message': 'Playwright не установлен на сервере.'}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--headless=new',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                ],
            )
            context = browser.new_context(
                storage_state=str(PENDING_AUTH_FILE),
                user_agent=_USER_AGENT,
                viewport={'width': 1920, 'height': 1080},
                locale='ru-RU',
                timezone_id='Europe/Moscow',
            )
            page = context.new_page()
            _goto(page, _pending_target_url())

            code_input = _code_locator(page)
            if code_input is None:
                # Pending session may have landed back on a "choose method"
                # screen — try to trigger the code field before giving up.
                if _click_send_code_button(page):
                    page.wait_for_timeout(2000)
                    code_input = _code_locator(page)

            if code_input is None:
                auth_error = _extract_auth_error(page)
                if auth_error:
                    browser.close()
                    return {'status': 'error', 'message': auth_error}
                if _captcha_required(page):
                    browser.close()
                    return {
                        'status': 'captcha_required',
                        'message': (
                            'Avito запросил дополнительную проверку (капча/проверка на робота). '
                            'Повторите вход позже или откройте его вручную.'
                        ),
                    }
                if _messages_page_open(page) or not _need_relogin(page):
                    _save_session(context)
                    _clear_pending_session()
                    browser.close()
                    return {'status': 'ok', 'message': 'Avito успешно подключён.'}
                browser.close()
                return {'status': 'error', 'message': 'Поле для кода Avito не найдено. Запросите код заново.'}

            code_input.fill(verification_code)
            _click_submit(page)
            page.wait_for_timeout(5000)

            auth_error = _extract_auth_error(page)
            if auth_error:
                browser.close()
                return {'status': 'error', 'message': auth_error}

            if _captcha_required(page):
                browser.close()
                return {
                    'status': 'captcha_required',
                    'message': (
                        'Avito запросил дополнительную проверку (капча/проверка на робота). '
                        'Повторите вход позже или откройте его вручную.'
                    ),
                }

            if _code_locator(page):
                browser.close()
                return {'status': 'error', 'message': 'Avito не принял код подтверждения.'}

            if _messages_page_open(page) or not _need_relogin(page):
                _save_session(context)
                _clear_pending_session()
                browser.close()
                return {'status': 'ok', 'message': 'Avito успешно подключён.'}

            browser.close()
            return {'status': 'error', 'message': 'Не удалось завершить вход в Avito. Попробуйте запросить код заново.'}
    except Exception as e:
        logger.error('Avito web login confirm error: %s', e)
        return {'status': 'error', 'message': str(e)}


def _parse_conversations(page):
    items = page.locator('[data-marker*="message"]:not([data-marker*="item"])').all()
    if not items:
        items = page.locator('a[href*="/messages/"]').all()

    conversations = []
    for item in items:
        try:
            href = item.get_attribute('href') or ''
            name_el = item.locator('[class*="name"], [class*="title"], [class*="user"]').first()
            text_el = item.locator('[class*="text"], [class*="message"], [class*="preview"]').first()
            time_el = item.locator('time, [class*="time"], [class*="date"]').first()

            conv = {
                'url': 'https://www.avito.ru' + href if href.startswith('/') else href,
                'name': name_el.inner_text().strip() if name_el.is_visible() else '',
                'preview': text_el.inner_text().strip() if text_el.is_visible() else '',
                'time': time_el.get_attribute('datetime') or time_el.inner_text().strip() if time_el.is_visible() else '',
            }
            if conv['url'] and 'messages' in conv['url']:
                conversations.append(conv)
        except Exception as e:
            logger.debug('Skipping conversation item: %s', e)

    return conversations


def _extract_messages(page):
    messages = []
    msg_elements = page.locator('[data-marker*="message"]').all()

    if not msg_elements:
        msg_elements = page.locator('[class*="message"]').all()

    for el in msg_elements:
        try:
            text = el.inner_text().strip()
            if not text or len(text) < 2:
                continue
            sender_el = el.locator('[class*="sender"], [class*="author"], [class*="from"]').first()
            sender = sender_el.inner_text().strip() if sender_el.is_visible() else ''
            time_el = el.locator('time, [class*="time"], [class*="date"]').first()
            ts = time_el.get_attribute('datetime') or '' if time_el.is_visible() else ''
            messages.append({'text': text, 'sender': sender, 'time': ts})
        except Exception as e:
            logger.debug('Skipping message element: %s', e)

    return messages


def _locate_conversation_input(page):
    selectors = [
        'textarea',
        '[contenteditable="true"]',
        'input[type="text"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            if locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None


def _open_conversation(page, conversation_ref: str, recipient_name: str = '') -> bool:
    if conversation_ref and conversation_ref.startswith('http'):
        _goto(page, conversation_ref)
        return True

    _goto(page, 'https://www.avito.ru/messages')
    if recipient_name:
        links = page.locator('a[href*="/messages/"]')
        count = min(links.count(), 30)
        for index in range(count):
            link = links.nth(index)
            try:
                text = link.inner_text().strip().lower()
                href = link.get_attribute('href') or ''
                if recipient_name.lower() in text and href:
                    _goto(page, 'https://www.avito.ru' + href if href.startswith('/') else href)
                    return True
            except Exception:
                continue
    return False


def send_avito_message(conversation_ref: str, text: str, recipient_name: str = '') -> dict:
    username, password = _get_credentials()
    if not username or not password:
        return {'status': 'error', 'message': 'Avito credentials not configured'}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'status': 'error', 'message': 'Playwright not installed'}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--headless=new',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                ],
            )
            context = _browser_context(browser)
            page = context.new_page()
            _goto(page, 'https://www.avito.ru/messages')

            if _need_relogin(page):
                logger.info('Avito session expired, re-logging in for outbound message')
                login_ok, login_message = _login(page, username, password)
                if not login_ok:
                    _notify_avito_auth_issue(
                        'CRM не смогла повторно войти в Avito для отправки сообщения. Нужен ручной вход и подтверждение сессии.'
                    )
                    browser.close()
                    return {'status': 'error', 'message': login_message or 'Avito login failed or SMS code required'}
                _save_session(context)

            opened = _open_conversation(page, conversation_ref, recipient_name=recipient_name)
            if not opened:
                browser.close()
                return {'status': 'error', 'message': 'Avito conversation not found'}

            input_locator = _locate_conversation_input(page)
            if input_locator is None:
                browser.close()
                return {'status': 'error', 'message': 'Avito message input not found'}

            try:
                tag_name = input_locator.evaluate('(el) => el.tagName.toLowerCase()')
            except Exception:
                tag_name = 'textarea'

            if tag_name == 'textarea' or tag_name == 'input':
                input_locator.fill(text)
            else:
                input_locator.click()
                input_locator.fill(text)

            send_selectors = [
                'button[type="submit"]',
                'button:has-text("Отправить")',
                '[data-marker*="send"]',
            ]
            sent = False
            for selector in send_selectors:
                button = page.locator(selector).last
                try:
                    if button.is_visible(timeout=1000):
                        button.click()
                        sent = True
                        break
                except Exception:
                    continue
            if not sent:
                input_locator.press('Enter')

            page.wait_for_timeout(2000)
            _save_session(context)
            browser.close()
            return {'status': 'ok', 'message': 'Avito message sent'}
    except Exception as e:
        logger.error('Avito send message error: %s', e)
        return {'status': 'error', 'message': str(e)}


def _find_or_create_client(name, contact=''):
    if contact:
        if '@' in contact:
            client = Client.objects.filter(email__iexact=contact).first()
        else:
            client = Client.objects.filter(phone=contact).first()
        if client:
            return client

    existing = Client.objects.filter(name__iexact=name).first()
    if existing:
        return existing

    client = Client.objects.create(
        name=name or 'Клиент с Авито',
        phone=contact if contact and '@' not in contact else '',
        email=contact if contact and '@' in contact else '',
        source='Авито',
        status=Client.Status.UNKNOWN,
    )
    client.history = [{'type': 'import', 'text': 'Создан через Avito Playwright', 'at': timezone.now().isoformat()}]
    client.save(update_fields=['history', 'updated_at'])
    return client


def _is_duplicate(client, text):
    return Message.objects.filter(
        client=client, channel=AVITO_CHANNEL, text__iexact=text
    ).exists()


def poll_avito_playwright():
    username, password = _get_credentials()
    if not username or not password:
        logger.warning('Avito Playwright credentials not configured')
        return {'status': 'error', 'message': 'Avito credentials not configured', 'imported': 0}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {'status': 'error', 'message': 'Playwright not installed. Run: pip install playwright && playwright install chromium', 'imported': 0}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--headless=new',
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                ],
            )
            context = _browser_context(browser)
            page = context.new_page()
            _goto(page, 'https://www.avito.ru/messages')

            if _need_relogin(page):
                logger.info('Session expired, re-logging in')
                login_ok, login_message = _login(page, username, password)
                if not login_ok:
                    _notify_avito_auth_issue(
                        'CRM не смогла автоматически обновить сессию Avito. Нужен ручной вход в Avito через CRM или на рабочей машине.'
                    )
                    browser.close()
                    return {'status': 'error', 'message': login_message or 'Login failed or SMS code required', 'imported': 0}
                _save_session(context)
                _goto(page, 'https://www.avito.ru/messages')

            conversations = _parse_conversations(page)
            logger.info('Found %d conversations', len(conversations))

            imported = 0
            errors = 0
            seen_ids = set()

            for conv in conversations[:getattr(settings, 'AVITO_POLL_LIMIT', 20)]:
                try:
                    conv_url = conv.get('url', '')
                    conv_name = conv.get('name', 'Клиент с Авито')
                    conv_preview = conv.get('preview', '')

                    if conv_url in seen_ids:
                        continue
                    seen_ids.add(conv_url)

                    client = _find_or_create_client(conv_name)

                    _goto(page, conv_url)

                    msgs = _extract_messages(page)
                    for msg in msgs:
                        text = msg.get('text', '')
                        if not text:
                            continue
                        if _is_duplicate(client, text):
                            continue
                        Message.objects.create(
                            channel=AVITO_CHANNEL,
                            direction=Message.Direction.INBOUND,
                            client=client,
                            author_name=msg.get('sender', '') or conv_name,
                            contact=conv_url,
                            text=text,
                            unread=True,
                        )
                        imported += 1

                    if msgs:
                        client.history = (client.history or []) + [
                            {'type': 'message', 'text': f'Авито ({len(msgs)} сообщений)', 'at': timezone.now().isoformat()}
                        ]
                        client.source = 'Авито'
                        client.save(update_fields=['history', 'source', 'updated_at'])

                except Exception as e:
                    logger.error('Failed to process conversation %s: %s', conv.get('url', ''), e)
                    errors += 1

            _save_session(context)
            browser.close()

            return {
                'status': 'ok' if imported > 0 else 'ok',
                'message': f'Imported {imported} messages from {len(seen_ids)} conversations ({errors} errors)',
                'imported': imported,
                'errors': errors,
            }

    except Exception as e:
        logger.error('Playwright Avito error: %s', e)
        return {'status': 'error', 'message': str(e), 'imported': 0}


def setup_avito_session():
    username, password = _get_credentials()
    if not username or not password:
        print('ERROR: AVITO_USERNAME and AVITO_PASSWORD not set in .env')
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('ERROR: Playwright not installed')
        return

    print('Opening browser...')
    print('1. Log in to Avito manually in the browser window')
    print('2. If SMS code is requested, enter it from your phone')
    print('3. Navigate to https://www.avito.ru/messages')
    print('4. Return here and press Enter to save the session')
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            locale='ru-RU',
            timezone_id='Europe/Moscow',
        )
        page = context.new_page()
        _goto(page, 'https://www.avito.ru')

        input('Press Enter after logging in and reaching the messages page...')

        _save_session(context)
        print(f'Saved to {AUTH_FILE}')
        print('Upload this file to the server in the project root (same folder as manage.py)')
        browser.close()
        print('Done.')


def launch_avito_setup() -> dict:
    username, password = _get_credentials()
    if not username or not password:
        return {'status': 'error', 'message': 'Avito credentials not configured'}

    cmd = [sys.executable, 'manage.py', 'avito_playwright_setup']
    env = os.environ.copy()
    env['AVITO_USERNAME'] = username
    env['AVITO_PASSWORD'] = password
    kwargs = {
        'cwd': str(settings.BASE_DIR),
        'env': env,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs['start_new_session'] = True

    try:
        subprocess.Popen(cmd, **kwargs)
        return {'status': 'ok', 'message': 'Avito manual login started'}
    except Exception as e:
        logger.error('Failed to launch Avito manual setup: %s', e)
        return {'status': 'error', 'message': str(e)}
