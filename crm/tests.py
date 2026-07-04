import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.test.utils import override_settings
from django.utils import timezone
from openpyxl import Workbook

from .contact_utils import sanitize_client_contacts
from .models import AuditEntry, Client, DictionaryEntry, EmployeeProfile, IntegrationEvent, Message, Order, RolePermission, ScheduleSettings, Task
from .one_c_import import import_nomenclature
from .tg_integration import _find_or_create_tg_client
from .vk_integration import _is_vk_bot_message, _store_vk_message
from .vk_integration import _find_or_create_client


class BankCsvImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username=f'test_admin_{self._testMethodName}',
            password='admin123',
        )
        Client.objects.all().delete()
        IntegrationEvent.objects.all().delete()
        self.client.force_login(self.user)

    def test_imports_bank_csv_and_normalizes_client_data(self):
        csv_content = (
            '+ 1 000 ₽;+7 (984) 193-21-83, МАРИЯ СЕРГЕЕВНА К.;20 ноября 2024, 18:16\n'
        )
        uploaded_file = SimpleUploadedFile('bank.csv', csv_content.encode('utf-8'))

        response = self.client.post(
            reverse('crm:dashboard'),
            {'action': 'sync_bank', 'bank_csv': uploaded_file},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        client = Client.objects.get()
        self.assertEqual(client.phone, '79841932183')
        self.assertEqual(client.name, 'Мария Сергеевна К.')
        self.assertEqual(client.status, Client.Status.BUYER)
        self.assertEqual(len(client.bank_purchases), 1)
        self.assertTrue(client.bank_purchases[0]['matched'])
        self.assertEqual(client.bank_purchases[0]['amount'], 1000.0)

    def test_import_matches_existing_client_by_normalized_phone_and_skips_duplicates(self):
        existing = Client.objects.create(
            name='Старое Имя',
            phone='+7 (984) 193-21-83',
            source='Сайт',
            bank_purchases=[],
            history=[],
        )
        csv_content = (
            '+ 1 000 ₽;+7 (984) 193-21-83, МАРИЯ СЕРГЕЕВНА К.;20 ноября 2024, 18:16\n'
        )

        first_upload = SimpleUploadedFile('bank.csv', csv_content.encode('utf-8'))
        self.client.post(reverse('crm:dashboard'), {'action': 'sync_bank', 'bank_csv': first_upload}, follow=True)

        existing.refresh_from_db()
        self.assertEqual(existing.name, 'Мария Сергеевна К.')
        self.assertEqual(existing.phone, '79841932183')
        self.assertEqual(len(existing.bank_purchases), 1)

        second_upload = SimpleUploadedFile('bank.csv', csv_content.encode('utf-8'))
        self.client.post(reverse('crm:dashboard'), {'action': 'sync_bank', 'bank_csv': second_upload}, follow=True)

        existing.refresh_from_db()
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(len(existing.bank_purchases), 1)


@override_settings(SITE_WEBHOOK_TOKEN='test-site-token')
class SiteWebhookTests(TestCase):
    def setUp(self):
        Client.objects.all().delete()
        IntegrationEvent.objects.all().delete()
        Order.objects.all().delete()

    def test_imports_website_order_and_wishlist(self):
        payload = {
            'type': 'order',
            'submission_id': 'wp-order-1001',
            'name': 'Мария Сергеевна',
            'phone': '+7 (999) 123-45-67',
            'email': 'maria@example.com',
            'items': [
                {'name': 'Фикус Лирата', 'qty': 2, 'price': 3500},
                {'name': 'Монстера', 'qty': 1, 'price': 4200},
            ],
            'wishlist': ['Орхидея Фаленопсис', 'Фикус Лирата'],
            'comment': 'Нужна доставка после 18:00',
        }
        response = self.client.post(
            reverse('crm:site_webhook'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CRM_TOKEN='test-site-token',
        )

        self.assertEqual(response.status_code, 201)
        client = Client.objects.get()
        order = Order.objects.get()
        event = IntegrationEvent.objects.get()

        self.assertEqual(client.phone, '79991234567')
        self.assertEqual(client.email, 'maria@example.com')
        self.assertEqual(client.source, 'Сайт')
        self.assertIn('Орхидея Фаленопсис', client.wish_list)
        self.assertEqual(order.client_id, client.id)
        self.assertEqual(float(order.total), 11200.0)
        self.assertEqual(event.external_id, 'wp-order-1001')

    def test_imports_wishlist_by_email_and_skips_duplicates(self):
        payload = {
            'type': 'wishlist',
            'submission_id': 'wp-wishlist-7',
            'email': 'lead@example.com',
            'nomenclature': ['Сансевиерия', 'Фиттония'],
        }

        first = self.client.post(
            reverse('crm:site_webhook'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CRM_TOKEN='test-site-token',
        )
        second = self.client.post(
            reverse('crm:site_webhook'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CRM_TOKEN='test-site-token',
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(IntegrationEvent.objects.count(), 1)
        client = Client.objects.get()
        self.assertEqual(client.email, 'lead@example.com')
        self.assertEqual(sorted(client.wish_list), ['Сансевиерия', 'Фиттония'])


@override_settings(
    DJANGO_SECRET_KEY='test-secret-key',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class LoginFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            password='admin123',
            first_name='Админ',
            last_name='CRM',
            is_staff=True,
            is_superuser=True,
        )
        self.employee = User.objects.create_user(
            username=f'anna.ts.{self._testMethodName}',
            password='worker123',
            first_name='Анна',
            last_name='Цветкова',
        )
        EmployeeProfile.objects.create(
            user=self.employee,
            role=EmployeeProfile.Role.FRONT,
            work_email='anna@example.com',
        )

    def test_admin_logs_in_with_username_and_password_without_email_code(self):
        response = self.client.post(
            reverse('crm:login'),
            {
                'action': 'submit_credentials',
                'identifier': 'admin',
                'password': 'admin123',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('crm:dashboard'))
        session = self.client.session
        self.assertEqual(session.get('_auth_user_id'), str(self.admin.pk))
        self.assertIsNone(session.get('login_step'))
        self.assertIsNone(session.get('login_code'))

    def test_dashboard_renders_for_profile_without_last_news_seen_at(self):
        EmployeeProfile.objects.create(
            user=self.admin,
            role=EmployeeProfile.Role.ADMIN,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('crm:dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_employee_login_by_display_name_moves_to_code_step(self):
        with patch('crm.views._send_code_email_with_timeout') as send_code:
            response = self.client.post(
                reverse('crm:login'),
                {
                    'action': 'submit_credentials',
                    'identifier': 'Анна Ц',
                    'password': 'worker123',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Код подтверждения')
        session = self.client.session
        self.assertEqual(session.get('login_step'), 'code')
        self.assertEqual(session.get('login_user_id'), self.employee.pk)
        self.assertEqual(session.get('login_display_name'), 'Анна Ц')
        self.assertEqual(session.get('login_email'), 'anna@example.com')
        self.assertRegex(session.get('login_code', ''), r'^\d{6}$')
        self.assertIsNone(session.get('_auth_user_id'))
        send_code.assert_called_once_with('anna@example.com', session['login_code'])

    def test_employee_can_complete_login_with_email_code(self):
        with patch('crm.views._send_code_email_with_timeout'):
            self.client.post(
                reverse('crm:login'),
                {
                    'action': 'submit_credentials',
                    'identifier': 'Анна Ц',
                    'password': 'worker123',
                },
            )

        session = self.client.session
        code = session['login_code']

        response = self.client.post(
            reverse('crm:login'),
            {
                'action': 'verify_code',
                'code': code,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('crm:dashboard'))
        session = self.client.session
        self.assertEqual(session.get('_auth_user_id'), str(self.employee.pk))
        self.assertIsNone(session.get('login_step'))
        self.assertIsNone(session.get('login_code'))


@override_settings(
    DJANGO_SECRET_KEY='test-secret-key',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES={
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    },
)
class UserAdminUpdateTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='owner',
            password='owner123',
            first_name='Owner',
            is_staff=True,
            is_superuser=True,
        )
        self.user = User.objects.create_user(
            username='anna',
            password='worker123',
            first_name='Анна',
            last_name='Старая',
            email='old@example.com',
        )
        EmployeeProfile.objects.create(
            user=self.user,
            role=EmployeeProfile.Role.FRONT,
            schedule='09:00-18:00',
            work_email='old@example.com',
        )
        self.client.force_login(self.admin)

    def test_update_user_allows_clearing_names_and_syncs_admin_flags(self):
        response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'update_user',
                'user_id': self.user.pk,
                'first_name': '',
                'last_name': '',
                'email': 'anna@example.com',
                'role': 'admin',
                'schedule': '10:00-19:00',
                'is_active': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, '')
        self.assertEqual(self.user.last_name, '')
        self.assertEqual(self.user.email, 'anna@example.com')
        self.assertTrue(self.user.is_staff)
        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.profile.role, EmployeeProfile.Role.ADMIN)
        self.assertEqual(self.user.profile.schedule, '10:00-19:00')
        self.assertEqual(self.user.profile.work_email, 'anna@example.com')


class RolePermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='rights_owner',
            password='owner123',
            is_staff=True,
            is_superuser=True,
        )
        EmployeeProfile.objects.create(user=self.admin, role=EmployeeProfile.Role.ADMIN)
        self.back = User.objects.create_user(username='warehouse', password='worker123')
        EmployeeProfile.objects.create(user=self.back, role=EmployeeProfile.Role.BACK)

    def test_role_without_section_access_is_redirected(self):
        self.client.force_login(self.back)

        response = self.client.get(reverse('crm:dashboard') + '?page=clients')

        self.assertEqual(response.status_code, 302)
        self.assertIn('?page=dashboard', response['Location'])

    def test_role_without_write_permission_cannot_create_client(self):
        self.client.force_login(self.back)

        response = self.client.post(
            reverse('crm:dashboard') + '?page=clients',
            {
                'action': 'create_client',
                'name': 'Закрытый Клиент',
                'phone': '+7 999 111-22-33',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Client.objects.filter(name='Закрытый Клиент').exists())

    def test_admin_can_update_role_permission(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('crm:dashboard') + '?page=admin',
            {
                'action': 'save_permission',
                'role': EmployeeProfile.Role.FRONT,
                'resource': RolePermission.Resource.PRODUCTS,
                'can_read': 'on',
                'can_write': 'on',
            },
        )

        self.assertEqual(response.status_code, 302)
        permission = RolePermission.objects.get(
            role=EmployeeProfile.Role.FRONT,
            resource=RolePermission.Resource.PRODUCTS,
        )
        self.assertTrue(permission.can_read)
        self.assertTrue(permission.can_write)
        self.assertFalse(permission.can_delete)

    def test_admin_role_and_analytics_pages_render_operational_blocks(self):
        self.client.force_login(self.admin)

        admin_response = self.client.get(reverse('crm:dashboard') + '?page=admin')
        analytics_response = self.client.get(reverse('crm:dashboard') + '?page=analytics')

        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, 'Матрица прав')
        self.assertEqual(analytics_response.status_code, 200)
        self.assertContains(analytics_response, 'Эффективность каналов')


class ContactNormalizationTests(TestCase):
    def test_moves_email_out_of_phone_field(self):
        phone, email, aliases = sanitize_client_contacts('lead@example.com', '', [])
        self.assertIsNone(phone)
        self.assertEqual(email, 'lead@example.com')
        self.assertIn('email:lead@example.com', aliases)

    def test_moves_vk_link_to_aliases_instead_of_phone(self):
        phone, email, aliases = sanitize_client_contacts('vk.com/id12345', '', [])
        self.assertIsNone(phone)
        self.assertEqual(email, '')
        self.assertIn('vk.com/id12345', aliases)

    def test_vk_client_is_created_without_social_link_in_phone(self):
        client = _find_or_create_client('Тест VK', 'vk.com/id12345', 12345)
        self.assertIsNone(client.phone)
        self.assertEqual(client.preferred_channel, 'VK')
        self.assertIn('vk.com/id12345', client.contact_aliases)

    def test_tg_client_is_created_without_chat_id_in_phone(self):
        client = _find_or_create_tg_client('Тест TG', 'tg://user?id=777', 777)
        self.assertIsNone(client.phone)
        self.assertEqual(client.preferred_channel, 'Telegram')
        self.assertIn('tg://user?id=777', client.contact_aliases)


class ClientSchemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='manager', password='manager123')
        self.client.force_login(self.user)

    def test_create_client_saves_spec_fields(self):
        response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'create_client',
                'last_name': 'Иванова',
                'first_name': 'Анна',
                'patronymic': 'Сергеевна',
                'birth_date': '1995-04-12',
                'phone': '+7 (999) 123-45-67',
                'second_phone': '8 912 000 00 01',
                'email': 'anna@example.com',
                'one_c_id': '1C-777',
                'vk_url': 'vk.com/id777',
                'telegram_url': 'tg://user?id=777',
                'whatsapp_url': 'wa.me/79991234567',
                'district': 'Центральный',
                'source': 'VK',
                'discount_card': 'CARD-777',
                'preferred_channel': 'Telegram',
                'tags': '',
                'interests': '',
                'wish_list': '',
                'wait_list': '',
                'internal_note': '',
                'quality': 'B',
            },
        )

        self.assertEqual(response.status_code, 302)
        client = Client.objects.get()
        self.assertEqual(client.name, 'Иванова Анна Сергеевна')
        self.assertEqual(client.last_name, 'Иванова')
        self.assertEqual(client.first_name, 'Анна')
        self.assertEqual(client.patronymic, 'Сергеевна')
        self.assertEqual(str(client.birth_date), '1995-04-12')
        self.assertEqual(client.phone, '79991234567')
        self.assertEqual(client.second_phone, '79120000001')
        self.assertEqual(client.vk_url, 'vk.com/id777')
        self.assertEqual(client.telegram_url, 'tg://user?id=777')
        self.assertEqual(client.whatsapp_url, 'wa.me/79991234567')
        self.assertEqual(client.district, 'Центральный')
        self.assertEqual(client.discount_card, 'CARD-777')
        self.assertIn('CARD-777', client.discount_cards)
        self.assertEqual(client.preferred_channel, 'Telegram')

    def test_bank_import_sets_first_purchase_at(self):
        csv_content = '+ 1 000 ₽;+7 (984) 193-21-83, МАРИЯ СЕРГЕЕВНА К.;20 ноября 2024, 18:16\n'
        uploaded_file = SimpleUploadedFile('bank.csv', csv_content.encode('utf-8'))

        self.client.post(
            reverse('crm:dashboard'),
            {'action': 'sync_bank', 'bank_csv': uploaded_file},
            follow=True,
        )

        client = Client.objects.get()
        self.assertIsNotNone(client.first_purchase_at)


class ScheduleSettingsTests(TestCase):
    def test_should_send_auto_reply_respects_channel_author_and_chat_type(self):
        sched = ScheduleSettings.objects.create(
            working_days='1,2,3,4,5',
            auto_reply_vk_enabled=True,
            auto_reply_tg_enabled=False,
            ignored_author_names='Secret Garden\nЛокация Secret Garden',
        )

        self.assertFalse(sched.should_send_auto_reply('Telegram', author_name='Client', chat_type='private'))
        self.assertFalse(sched.should_send_auto_reply('VK', author_name='Secret Garden', chat_type='private'))
        self.assertFalse(sched.should_send_auto_reply('VK', author_name='Client', chat_type='chat'))

    def test_should_send_auto_reply_respects_emergency_disable(self):
        sched = ScheduleSettings.objects.create(
            working_days='1,2,3,4,5',
            auto_reply_vk_enabled=True,
            auto_reply_tg_enabled=True,
            auto_reply_emergency_disabled=True,
        )

        with patch.object(ScheduleSettings, 'is_open', return_value=False):
            self.assertFalse(sched.should_send_auto_reply('VK', author_name='Client', chat_type='private'))
            self.assertFalse(sched.should_send_auto_reply('Telegram', author_name='Client', chat_type='private'))

    def test_is_open_uses_custom_working_days(self):
        ScheduleSettings.objects.create(
            workday_start='11:00',
            workday_end='20:00',
            working_days='1,2,3,4,5',
        )

        with patch('crm.models.timezone.now', return_value=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.get_current_timezone())):
            self.assertTrue(ScheduleSettings.is_open())

        with patch('crm.models.timezone.now', return_value=datetime(2026, 6, 29, 12, 0, tzinfo=timezone.get_current_timezone())):
            self.assertFalse(ScheduleSettings.is_open())


class NomenclatureImportTests(TestCase):
    def test_import_replaces_demo_products_with_real_nomenclature(self):
        from .models import Product

        Product.objects.create(
            name='Фикус Лирата',
            parent='Комнатные растения',
            sku='PL-001',
            kind=Product.ProductKind.PLANT,
            stock=4,
            reserve=0,
            price=100,
            in_production=0,
            status=Product.StockStatus.OK,
        )

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'номенклатура Т'
        sheet.append([2642, 'Антуриум (Anthurium) Emma', 'Комнатные растения'])
        sheet.append([2643, 'Гимнокалициум (Gymnocalycium) Spineless Island', 'Комнатные растения'])

        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            workbook.save(tmp_path)
            stats = import_nomenclature(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(stats.deleted_demo, 1)
        self.assertEqual(stats.created, 2)
        self.assertFalse(Product.objects.filter(name='Фикус Лирата').exists())
        self.assertTrue(Product.objects.filter(sku='2642', name__icontains='Антуриум').exists())


class VkImportTests(TestCase):
    def test_detects_secret_bot_messages(self):
        self.assertTrue(_is_vk_bot_message({
            'from_id': -218777467,
            'text': 'Добрый день! Вам отвечает Secret-бот. В данный момент сотрудники отдыхают.',
        }, group_id=218777467))

    def test_stores_real_vk_message_with_integration_event(self):
        client = Client.objects.create(
            name='Вероника Петрушова',
            source='VK',
            preferred_channel='VK',
            contact_aliases=['vk.com/id9337162'],
        )
        stored = _store_vk_message(
            peer_id=9337162,
            message={
                'id': 123,
                'date': 1782931228,
                'from_id': 9337162,
                'text': 'Здравствуйте, подскажите по наличию.',
                'conversation_message_id': 5,
            },
            client=client,
            group_id=218777467,
            user_profiles={9337162: {'id': 9337162, 'first_name': 'Вероника', 'last_name': 'Петрушова'}},
            existing_event_ids=set(),
        )

        self.assertTrue(stored)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(IntegrationEvent.objects.filter(source='VK', event_type='message', external_id='9337162:123').count(), 1)


class DashboardEnhancementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username=f'admin_{self._testMethodName}',
            password='admin123',
            is_staff=True,
            is_superuser=True,
        )
        EmployeeProfile.objects.create(
            user=self.admin,
            role=EmployeeProfile.Role.ADMIN,
            work_email='admin@example.com',
        )
        self.employee = User.objects.create_user(
            username=f'employee_{self._testMethodName}',
            password='worker123',
            first_name='Ирина',
        )
        EmployeeProfile.objects.create(
            user=self.employee,
            role=EmployeeProfile.Role.FRONT,
            work_email='irina@example.com',
        )
        self.client.force_login(self.admin)

    def test_duplicate_candidates_render_and_manual_merge_moves_related_data(self):
        primary = Client.objects.create(
            name='Анна Листова',
            phone='+7 (999) 111-22-33',
            source='Telegram',
            tags=['vip'],
            history=[],
        )
        duplicate = Client.objects.create(
            name='Анна Листова дубль',
            second_phone='+7 (999) 111-22-33',
            source='Telegram',
            history=[],
        )
        message = Message.objects.create(
            channel='Telegram',
            direction=Message.Direction.INBOUND,
            client=duplicate,
            author_name='Анна',
            text='Хочу оформить заказ',
            assigned_to=self.admin,
        )
        task = Task.objects.create(
            title='Связаться с клиентом',
            due_at=timezone.now() + timedelta(days=1),
            origin=Task.Origin.CLIENTS,
            assigned_to=self.admin,
            client=duplicate,
        )
        order = Order.objects.create(
            client=duplicate,
            items=[{'name': 'Монстера', 'qty': 1, 'price': 5000}],
            total=5000,
            notes='test',
            history=[],
        )

        response = self.client.get(f"{reverse('crm:dashboard')}?page=clients")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Подозрение на дубли')
        self.assertContains(response, 'Объединить вручную')

        merge_response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'merge_clients',
                'primary_client_id': primary.id,
                'duplicate_client_id': duplicate.id,
            },
            follow=True,
        )

        self.assertEqual(merge_response.status_code, 200)
        self.assertEqual(Client.objects.count(), 1)
        primary.refresh_from_db()
        message.refresh_from_db()
        task.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(message.client_id, primary.id)
        self.assertEqual(task.client_id, primary.id)
        self.assertEqual(order.client_id, primary.id)
        self.assertTrue(any(item.get('type') == 'merge' for item in (primary.history or [])))
        self.assertTrue(AuditEntry.objects.filter(action='Merge clients').exists())

    def test_export_analytics_csv_respects_selected_period(self):
        period_start = timezone.make_aware(datetime(2024, 1, 1, 9, 0))
        period_mid = timezone.make_aware(datetime(2024, 1, 10, 10, 0))
        period_end = timezone.make_aware(datetime(2024, 1, 31, 18, 0))
        outside_period = timezone.make_aware(datetime(2023, 12, 20, 12, 0))

        inside_client = Client.objects.create(
            name='Покупатель января',
            source='Telegram',
            status=Client.Status.BUYER,
            history=[],
        )
        outside_client = Client.objects.create(
            name='Покупатель декабря',
            source='Telegram',
            status=Client.Status.BUYER,
            history=[],
        )
        Client.objects.filter(pk=inside_client.pk).update(created_at=period_mid)
        Client.objects.filter(pk=outside_client.pk).update(created_at=outside_period)

        inbound = Message.objects.create(
            channel='Telegram',
            direction=Message.Direction.INBOUND,
            client=inside_client,
            author_name='Покупатель января',
            text='Здравствуйте',
            assigned_to=self.admin,
        )
        outbound = Message.objects.create(
            channel='Telegram',
            direction=Message.Direction.OUTBOUND,
            client=inside_client,
            author_name='Менеджер',
            text='Добрый день',
            assigned_to=self.admin,
        )
        outside_message = Message.objects.create(
            channel='Telegram',
            direction=Message.Direction.INBOUND,
            client=outside_client,
            author_name='Покупатель декабря',
            text='Старое сообщение',
            assigned_to=self.admin,
        )
        Message.objects.filter(pk=inbound.pk).update(created_at=period_mid)
        Message.objects.filter(pk=outbound.pk).update(created_at=period_end)
        Message.objects.filter(pk=outside_message.pk).update(created_at=outside_period)

        task = Task.objects.create(
            title='Закрыть январскую сделку',
            due_at=period_end,
            origin=Task.Origin.CLIENTS,
            assigned_to=self.admin,
            client=inside_client,
            status=Task.Status.DONE,
        )
        Task.objects.filter(pk=task.pk).update(created_at=period_mid)

        order = Order.objects.create(
            client=inside_client,
            items=[{'name': 'Фикус', 'qty': 1, 'price': 4500}],
            total=4500,
            notes='Январский заказ',
            history=[],
        )
        old_order = Order.objects.create(
            client=outside_client,
            items=[{'name': 'Старый заказ', 'qty': 1, 'price': 2000}],
            total=2000,
            notes='Декабрьский заказ',
            history=[],
        )
        Order.objects.filter(pk=order.pk).update(created_at=period_mid)
        Order.objects.filter(pk=old_order.pk).update(created_at=outside_period)

        response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'export_analytics_csv',
                'analytics_start': '2024-01-01',
                'analytics_end': '2024-01-31',
            },
        )

        self.assertEqual(response.status_code, 200)
        csv_body = response.content.decode('utf-8-sig')
        self.assertIn('01.01.2024 - 31.01.2024', csv_body)
        self.assertIn('Telegram,1,1,1,1', csv_body)
        self.assertIn('Покупатели,1', csv_body)
        self.assertNotIn('Покупатель декабря', csv_body)

    def test_admin_tools_toggle_user_and_update_dictionary_entry(self):
        entry = DictionaryEntry.objects.create(
            dict_type=DictionaryEntry.DictType.TAG,
            key='vip',
            label='VIP',
            sort_order=1,
        )

        toggle_response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'toggle_user',
                'user_id': self.employee.id,
            },
            follow=True,
        )
        self.assertEqual(toggle_response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.is_active)

        update_response = self.client.post(
            reverse('crm:dashboard'),
            {
                'action': 'dict_update',
                'entry_id': entry.id,
                'key': 'priority',
                'label': 'Приоритетный',
                'sort_order': 7,
            },
            follow=True,
        )
        self.assertEqual(update_response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.key, 'priority')
        self.assertEqual(entry.label, 'Приоритетный')
        self.assertEqual(entry.sort_order, 7)

        admin_page = self.client.get(f"{reverse('crm:dashboard')}?page=admin")
        self.assertContains(admin_page, 'Заблокированные сотрудники')
        self.assertContains(admin_page, self.employee.username)
        self.assertContains(admin_page, 'История изменений прав')
