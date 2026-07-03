import concurrent.futures
import hashlib
import json
import logging
import re

from django.conf import settings
from django.test import RequestFactory

from . import views as crm_views
from .models import IntegrationEvent

logger = logging.getLogger(__name__)

# Playwright's sync API leaves a running asyncio event loop registered on the
# calling thread, which makes Django's ORM refuse synchronous DB access
# ("SynchronousOnlyOperation"). Route webhook calls through a plain worker
# thread (no event loop attached) to sidestep that entirely.
_webhook_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='shop_sync_webhook')

_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)

# WooCommerce/WoodMart order status slug (without the "wc-" prefix) -> CRM Order.Status.
# None means the order is not a real/finalised order and should be skipped entirely.
STATUS_MAP = {
    'draft': None,
    'auto-draft': None,
    'checkout-draft': None,
    'pending': 'new',
    'on-hold': 'new',
    'under-approval': 'new',
    'at-pickup-point': 'new',
    'pre-order': 'new',
    'no-contact': 'new',
    'processing': 'in_progress',
    'prepared': 'assembled',
    'partially-prepared': 'assembled',
    'completed': 'delivered',
    'cancelled': 'cancelled',
    'failed': 'cancelled',
    'refunded': 'cancelled',
}


def _map_status(raw_slug: str):
    slug = re.sub(r'^wc-', '', str(raw_slug or '').strip().lower())
    if slug in STATUS_MAP:
        return STATUS_MAP[slug]
    for key, value in STATUS_MAP.items():
        if key in slug:
            return value
    return 'new'


def _get_credentials():
    base_url = getattr(settings, 'SHOP_ADMIN_URL', 'https://shop.lsgarden.ru').rstrip('/')
    username = getattr(settings, 'SHOP_ADMIN_USERNAME', '')
    password = getattr(settings, 'SHOP_ADMIN_PASSWORD', '')
    return base_url, username, password


def _new_context(browser):
    return browser.new_context(
        user_agent=_USER_AGENT,
        viewport={'width': 1600, 'height': 1000},
        locale='ru-RU',
        timezone_id='Europe/Moscow',
    )


def _goto(page, url, retries=2, timeout=45000):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            return
        except Exception as e:
            last_exc = e
            logger.warning('goto attempt %d failed for %s: %s', attempt + 1, url, e)
            page.wait_for_timeout(2000)
    raise last_exc


def _login(page, base_url, username, password) -> bool:
    _goto(page, f'{base_url}/wp-admin/')
    if page.locator('#user_login').count():
        page.fill('#user_login', username)
        page.fill('#user_pass', password)
        page.click('#wp-submit')
        try:
            page.wait_for_load_state('domcontentloaded', timeout=20000)
        except Exception as e:
            logger.warning('Shop login navigation warning: %s', e)
        page.wait_for_timeout(1500)

    skip = page.locator('a:has-text("Пропустить")').first
    try:
        visible = skip.is_visible(timeout=2000)
    except Exception:
        visible = False
    if visible:
        try:
            skip.click()
        except Exception as e:
            logger.warning('Shop 2FA-skip click warning: %s', e)
        page.wait_for_timeout(2500)

    if 'wp-admin' not in page.url or 'wp-login.php' in page.url:
        _goto(page, f'{base_url}/wp-admin/')
        page.wait_for_timeout(800)

    return 'wp-admin' in page.url and 'wp-login.php' not in page.url


def _call_webhook_impl(event_type: str, payload: dict) -> dict:
    request = RequestFactory().post(
        '/api/site/webhook/',
        data=json.dumps(payload),
        content_type='application/json',
        HTTP_X_CRM_TOKEN=getattr(settings, 'SITE_WEBHOOK_TOKEN', ''),
    )
    response = crm_views.site_webhook(request)
    return json.loads(response.content.decode('utf-8'))


def _call_webhook(event_type: str, payload: dict) -> dict:
    payload = dict(payload)
    payload['type'] = event_type
    # Run on a plain worker thread — see _webhook_executor comment above.
    future = _webhook_executor.submit(_call_webhook_impl, event_type, payload)
    return future.result()


def _run_db(fn, *args, **kwargs):
    """Run any ORM-touching callable on the plain worker thread (see
    _webhook_executor comment above) — needed for ANY DB access made while
    inside the `with sync_playwright()` block, not just webhook calls."""
    future = _webhook_executor.submit(fn, *args, **kwargs)
    return future.result()


def _fetch_synced_order_ids(order_ids: list[int]) -> set[str]:
    return set(
        IntegrationEvent.objects.filter(
            source='wordpress', event_type='order', external_id__in=[str(oid) for oid in order_ids],
        ).values_list('external_id', flat=True)
    )


def _fetch_last_wishlist_counts() -> dict:
    last_synced_count: dict[int, int] = {}
    for external_id, payload in (
        IntegrationEvent.objects.filter(source='wordpress', event_type='wishlist')
        .order_by('-created_at')
        .values_list('external_id', 'payload')
    ):
        m = re.match(r'^wishlist:(\d+):', external_id)
        if not m:
            continue
        wl_id = int(m.group(1))
        if wl_id in last_synced_count:
            continue  # already have the most recent one (query is newest-first)
        last_synced_count[wl_id] = len((payload or {}).get('wishlist') or [])
    return last_synced_count


def _collect_order_ids(page, base_url) -> list[int]:
    order_ids = []
    page_num = 1
    while True:
        url = f'{base_url}/wp-admin/admin.php?page=wc-orders&paged={page_num}'
        try:
            _goto(page, url)
        except Exception as e:
            logger.warning('Shop sync: giving up collecting order list at page %d: %s', page_num, e)
            break
        page.wait_for_timeout(500)
        hrefs = page.eval_on_selector_all('a.order-view', 'els => els.map(e => e.href)')
        ids = []
        for href in hrefs:
            m = re.search(r'[?&]id=(\d+)', href)
            if m:
                ids.append(int(m.group(1)))
        if not ids:
            break
        order_ids.extend(ids)
        if len(ids) < 20:
            break
        page_num += 1
    return order_ids


def _extract_order(page, base_url, order_id: int) -> dict | None:
    url = f'{base_url}/wp-admin/admin.php?page=wc-orders&action=edit&id={order_id}'
    _goto(page, url)
    page.wait_for_timeout(400)
    if not page.locator('#order_data').count():
        return None

    status_raw = page.eval_on_selector('#order_status', 'el => el.value') or ''
    email = (page.eval_on_selector('#_billing_email', 'el => el.value') or '').strip()
    phone = (page.eval_on_selector('#_billing_phone', 'el => el.value') or '').strip()
    first_name = (page.eval_on_selector('#_billing_first_name', 'el => el.value') or '').strip()
    last_name = (page.eval_on_selector('#_billing_last_name', 'el => el.value') or '').strip()
    name = f'{first_name} {last_name}'.strip()

    date_parts = page.eval_on_selector_all(
        '#order_data input[name="order_date"], #order_data input[name="order_date_hour"], '
        '#order_data input[name="order_date_minute"], #order_data input[name="order_date_second"]',
        'els => els.map(e => e.value)',
    )
    order_date = ''
    if len(date_parts) == 4 and date_parts[0]:
        order_date = f'{date_parts[0]}T{date_parts[1]}:{date_parts[2]}:{date_parts[3]}'

    box_text = page.inner_text('#order_data')

    district = ''
    m = re.search(r'Район проживания:\s*\n\s*(.+)', box_text)
    if m:
        district = m.group(1).strip()

    discount_card = ''
    m = re.search(r'Укажите номер карты[^\n]*:\s*\n\s*(\d+)', box_text)
    if m:
        discount_card = m.group(1).strip()

    birth_date = ''
    m = re.search(r'Дата рождения:\s*\n\s*(\d{4}-\d{2}-\d{2})', box_text)
    if m:
        birth_date = m.group(1).strip()

    note = ''
    m = re.search(r'Примечание от клиента:\s*\n\s*(.+)', box_text)
    if m:
        note = m.group(1).strip()

    return {
        'external_id': str(order_id),
        'name': name,
        'email': email,
        'phone': phone,
        'site_status': _map_status(status_raw),
        'order_date': order_date,
        'district': district,
        'discount_card': discount_card,
        'birth_date': birth_date,
        'comment': note,
        'items': [],
    }


def sync_orders(limit: int | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    base_url, username, password = _get_credentials()
    stats = {'total': 0, 'created': 0, 'duplicate': 0, 'skipped_draft': 0, 'errors': 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = _new_context(browser)
        page = context.new_page()

        if not _login(page, base_url, username, password):
            browser.close()
            return {'status': 'error', 'message': 'Не удалось авторизоваться в wp-admin магазина', **stats}

        order_ids = _collect_order_ids(page, base_url)
        if limit:
            order_ids = order_ids[:limit]
        stats['total'] = len(order_ids)
        logger.info('Shop sync: found %d orders', len(order_ids))

        # Incremental optimisation: orders we've already imported never change
        # their external_id (it's just the WooCommerce order id), so skip the
        # expensive page load entirely for anything we've already seen. This
        # is what makes periodic re-runs (for near-real-time sync of NEW
        # orders) fast instead of re-crawling all 266+ orders every time.
        already_synced = _run_db(_fetch_synced_order_ids, order_ids)

        for order_id in order_ids:
            if str(order_id) in already_synced:
                stats['duplicate'] += 1
                continue
            try:
                data = _extract_order(page, base_url, order_id)
                if data is None:
                    stats['errors'] += 1
                    continue
                if data['site_status'] is None:
                    stats['skipped_draft'] += 1
                    continue
                if not data['email'] and not data['phone']:
                    stats['errors'] += 1
                    continue
                result = _call_webhook('order', data)
                if not result.get('ok'):
                    logger.error('Shop sync: order %s webhook rejected: %s', order_id, result)
                    stats['errors'] += 1
                elif result.get('status') == 'duplicate':
                    stats['duplicate'] += 1
                else:
                    stats['created'] += 1
            except Exception as e:
                logger.exception('Shop sync: order %s failed: %s', order_id, e)
                stats['errors'] += 1

        browser.close()

    return {'status': 'ok', 'message': 'Синхронизация заказов завершена', **stats}


def _collect_wishlists(page, base_url) -> list[dict]:
    wishlists = []
    page_num = 1
    while True:
        url = (
            f'{base_url}/wp-admin/edit.php?post_type=product'
            f'&page=xts-wishlist-settings-page&paged={page_num}'
        )
        try:
            _goto(page, url)
        except Exception as e:
            logger.warning('Shop sync: giving up collecting wishlist list at page %d: %s', page_num, e)
            break
        page.wait_for_timeout(500)
        rows = page.query_selector_all('table.wp-list-table tbody tr')
        if not rows:
            break
        for row in rows:
            checkbox = row.query_selector('input[name="wishlist[]"]')
            user_link = row.query_selector('.user_name a')
            count_cell = row.query_selector('.product_count')
            if not checkbox or not user_link:
                continue
            wishlist_id = checkbox.get_attribute('value')
            m = re.search(r'user_id=(\d+)', user_link.get_attribute('href') or '')
            if not wishlist_id or not m:
                continue
            try:
                count = int((count_cell.inner_text() if count_cell else '0').strip())
            except ValueError:
                count = 0
            wishlists.append({
                'wishlist_id': int(wishlist_id),
                'user_id': int(m.group(1)),
                'count': count,
            })
        if len(rows) < 20:
            break
        page_num += 1
    return wishlists


def _get_user_email(page, base_url, user_id: int, cache: dict) -> str:
    if user_id in cache:
        return cache[user_id]
    url = f'{base_url}/wp-admin/user-edit.php?user_id={user_id}'
    _goto(page, url)
    page.wait_for_timeout(300)
    email = (page.eval_on_selector('#email', 'el => el.value') or '').strip() if page.locator('#email').count() else ''
    cache[user_id] = email
    return email


def _get_wishlist_items(page, base_url, wishlist_id: int) -> list[str]:
    url = f'{base_url}/wishlist/{wishlist_id}/'
    _goto(page, url)
    page.wait_for_timeout(400)
    names = [
        (el.get_attribute('aria-label') or '').strip()
        for el in page.query_selector_all('.wd-products-element a.product-image-link')
    ]
    return [name for name in names if name]


def sync_wishlists(limit: int | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    base_url, username, password = _get_credentials()
    stats = {'total': 0, 'created': 0, 'duplicate': 0, 'skipped_empty': 0, 'skipped_no_email': 0, 'errors': 0}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = _new_context(browser)
        page = context.new_page()

        if not _login(page, base_url, username, password):
            browser.close()
            return {'status': 'error', 'message': 'Не удалось авторизоваться в wp-admin магазина', **stats}

        entries = _collect_wishlists(page, base_url)
        if limit:
            entries = entries[:limit]
        stats['total'] = len(entries)
        logger.info('Shop sync: found %d wishlists', len(entries))

        # Incremental optimisation: the wishlist listing page gives us each
        # wishlist's current item count for free. If that count matches what
        # we synced last time, the wishlist almost certainly hasn't changed,
        # so skip the expensive per-wishlist page loads (user email + item
        # names) entirely. A changed count (including a brand-new wishlist,
        # which has no prior count) always gets re-checked.
        last_synced_count = _run_db(_fetch_last_wishlist_counts)

        email_cache: dict[int, str] = {}
        for entry in entries:
            try:
                if entry['count'] <= 0:
                    stats['skipped_empty'] += 1
                    continue
                if last_synced_count.get(entry['wishlist_id']) == entry['count']:
                    stats['duplicate'] += 1
                    continue
                email = _get_user_email(page, base_url, entry['user_id'], email_cache)
                if not email:
                    stats['skipped_no_email'] += 1
                    continue
                items = _get_wishlist_items(page, base_url, entry['wishlist_id'])
                if not items:
                    stats['skipped_empty'] += 1
                    continue
                item_key = ','.join(sorted(items))
                item_hash = hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:16]
                external_id = f"wishlist:{entry['wishlist_id']}:{item_hash}"
                result = _call_webhook('wishlist', {
                    'email': email,
                    'wishlist': items,
                    'external_id': external_id,
                })
                if not result.get('ok'):
                    logger.error('Shop sync: wishlist %s webhook rejected: %s', entry.get('wishlist_id'), result)
                    stats['errors'] += 1
                elif result.get('status') == 'duplicate':
                    stats['duplicate'] += 1
                else:
                    stats['created'] += 1
            except Exception as e:
                logger.exception('Shop sync: wishlist %s failed: %s', entry.get('wishlist_id'), e)
                stats['errors'] += 1

        browser.close()

    return {'status': 'ok', 'message': 'Синхронизация wishlist завершена', **stats}
