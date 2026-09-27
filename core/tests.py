import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Client, Debt, Shop, UserProfile


def make_shop(tg_id='111111', name="Test Do'kon"):
    user = User.objects.create_user(username=tg_id, password='1')
    shop = Shop.objects.create(name=name, owner=user)
    UserProfile.objects.create(user=user, shop=shop, role='admin')
    return user, shop


@mock.patch('requests.post')
class SignupTests(TestCase):
    def test_signup_starts_trial(self, _post):
        self.client.post(reverse('signup'), {
            'shop_name': 'Baraka', 'admin_name': 'Ali', 'telegram_id': '123456789',
        })
        shop = Shop.objects.get(name='Baraka')
        self.assertTrue(shop.is_trial_used)
        self.assertGreaterEqual(shop.days_left, 13)

    def test_signup_rejects_phone_number(self, _post):
        resp = self.client.post(reverse('signup'), {
            'shop_name': 'Baraka', 'admin_name': 'Ali', 'telegram_id': '998901234567',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Shop.objects.exists())

    def test_menu_hides_banner_without_subscription_date(self, _post):
        user, _shop = make_shop()
        self.client.force_login(user)
        resp = self.client.get(reverse('main_menu'))
        self.assertNotContains(resp, 'Obuna tugashiga')


@mock.patch('core.views.send_tg_msg')
@mock.patch('core.views.send_menu')
class WebhookTests(TestCase):
    def post_text(self, text, chat_id=555):
        return self.client.post(
            reverse('telegram_webhook'),
            data=json.dumps({'message': {'chat': {'id': chat_id}, 'text': text}}),
            content_type='application/json',
        )

    def test_start_login_sends_menu_not_error(self, send_menu, send_msg):
        self.post_text('/start login')
        send_menu.assert_called_once()
        send_msg.assert_not_called()

    def test_start_id_sends_telegram_id(self, send_menu, send_msg):
        self.post_text('/start id', chat_id=777)
        self.assertIn('777', send_msg.call_args[0][1])

    def test_invite_token_links_client(self, send_menu, send_msg):
        _user, shop = make_shop()
        c = Client.objects.create(shop=shop, full_name='Vali', phone='+998901112233')
        self.post_text(f'/start {c.invite_token}', chat_id=999)
        c.refresh_from_db()
        self.assertEqual(c.telegram_id, 999)


@mock.patch('requests.post')
class ClientAndDebtTests(TestCase):
    def setUp(self):
        self.user, self.shop = make_shop()
        self.client.force_login(self.user)

    def sale(self, **extra):
        data = {
            'sale_mode': 'debt', 'payment_type': 'cash',
            'product_name[]': ['Non'], 'quantity[]': ['2'], 'price[]': ['5000'], 'currency[]': ['uzs'],
        }
        data.update(extra)
        return self.client.post(reverse('create_debt'), data)

    def test_same_phone_allowed_in_two_shops(self, _post):
        _u2, shop2 = make_shop(tg_id='222222', name='Ikkinchi')
        Client.objects.create(shop=self.shop, full_name='A', phone='000000000')
        Client.objects.create(shop=shop2, full_name='B', phone='000000000')
        self.assertEqual(Client.objects.filter(phone='000000000').count(), 2)

    def test_cash_sale_works_in_second_shop(self, _post):
        Client.objects.create(shop=self.shop, full_name='Kassa', phone='000000000')
        u2, _shop2 = make_shop(tg_id='222222', name='Ikkinchi')
        self.client.force_login(u2)
        resp = self.sale(sale_mode='cash')
        self.assertEqual(resp.status_code, 302)

    def test_unlinked_client_debt_confirmed_by_choice(self, _post):
        c = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')
        resp = self.sale(client=c.id, no_tg_action='confirm')
        self.assertRedirects(resp, reverse('admin_client_detail', args=[c.id]))
        self.assertEqual(Debt.objects.get(client=c).status, 'confirmed')

    def test_unlinked_client_debt_can_stay_pending(self, _post):
        c = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')
        self.sale(client=c.id, no_tg_action='pending')
        self.assertEqual(Debt.objects.get(client=c).status, 'pending')

    def test_linked_client_debt_stays_pending(self, _post):
        c = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233', telegram_id=42)
        self.sale(client=c.id, no_tg_action='confirm')
        self.assertEqual(Debt.objects.get(client=c).status, 'pending')

    def test_status_page_shows_message(self, _post):
        c = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')
        d = Debt.objects.create(shop=self.shop, client=c, amount_uzs=1000, items='x', status='pending')
        resp = self.client.post(reverse('debt_detail', args=[d.uuid]), {'action': 'confirm'})
        self.assertContains(resp, 'Siz nasiyani tasdiqladingiz')

    def test_confirmed_debt_card_uses_theme_background(self, _post):
        c = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')
        Debt.objects.create(shop=self.shop, client=c, amount_uzs=1000, items='x', status='confirmed')
        session = self.client.session
        session['client_id'] = c.id
        session.save()
        resp = self.client.get(reverse('client_cabinet'))
        self.assertNotContains(resp, '#232E3C')
        self.assertContains(resp, 'var(--tg-secondary)')


class ParseAmountTests(TestCase):
    def test_formats(self):
        from .utils import parse_amount
        self.assertEqual(parse_amount('1 500 000'), 1500000)
        self.assertEqual(parse_amount('1,500,000'), 1500000)
        self.assertEqual(parse_amount('12,5'), 12.5)
        self.assertEqual(parse_amount('abc'), 0)
        self.assertEqual(parse_amount('-5'), 0)


@mock.patch('requests.post')
class SaleAndPaymentFormTests(TestCase):
    def setUp(self):
        self.user, self.shop = make_shop()
        self.client.force_login(self.user)
        self.vali = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')

    def sale(self, **extra):
        data = {
            'sale_mode': 'debt', 'payment_type': 'cash', 'no_tg_action': 'confirm',
            'product_name[]': ['Shakar'], 'quantity[]': ['2'], 'price[]': ['1 500 000'], 'currency[]': ['uzs'],
        }
        data.update(extra)
        return self.client.post(reverse('create_debt'), data)

    def test_formatted_price_is_parsed(self, _post):
        self.sale(client=self.vali.id)
        self.assertEqual(Debt.objects.get(client=self.vali).amount_uzs, 3000000)

    def test_missing_client_keeps_entered_items(self, _post):
        resp = self.sale(client='')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "mijozni tanlang")
        self.assertContains(resp, 'Shakar')  # prefill JSON ichida
        self.assertFalse(Debt.objects.exists())

    def test_sale_without_items_is_rejected(self, _post):
        resp = self.sale(client=self.vali.id, **{'price[]': ['']})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Debt.objects.exists())

    def test_cash_sale_is_separate_from_credit_stats(self, _post):
        from .views import shop_stats
        self.sale(sale_mode='cash', payment_type='transfer')
        self.sale(client=self.vali.id)
        stats = shop_stats(self.shop)
        self.assertEqual(stats['sales_uzs'], 3000000)   # faqat nasiya
        self.assertEqual(stats['income_uzs'], 0)
        self.assertEqual(stats['cash_uzs'], 3000000)
        self.assertEqual(stats['cash_count'], 1)
        self.assertTrue(Debt.objects.filter(is_cash_sale=True, payment_method='transfer').exists())

    def test_cash_client_hidden_from_lists(self, _post):
        self.sale(sale_mode='cash')
        resp = self.client.get(reverse('create_payment'))
        self.assertNotContains(resp, 'Naqd Savdo (Kassa)')
        resp = self.client.get(reverse('dashboard'))
        self.assertNotContains(resp, 'Naqd Savdo (Kassa)')

    def test_payment_with_formatted_amount(self, _post):
        resp = self.client.post(reverse('create_payment'), {
            'client_id': self.vali.id, 'amount_uzs': '250 000', 'payment_method': 'transfer', 'note': 'avans',
        })
        self.assertRedirects(resp, reverse('admin_client_detail', args=[self.vali.id]))
        payment = Debt.objects.get(client=self.vali)
        self.assertEqual(payment.amount_uzs, -250000)
        self.assertEqual(payment.payment_method, 'transfer')
        self.assertIn('avans', payment.items)

    def test_payment_error_keeps_input(self, _post):
        resp = self.client.post(reverse('create_payment'), {'client_id': '', 'amount_uzs': '250 000'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '250 000')
        self.assertFalse(Debt.objects.exists())

    def test_mark_cash_sales_command(self, _post):
        from django.core.management import call_command
        sale = Debt.objects.create(shop=self.shop, client=self.vali, amount_uzs=100, items='Non', status='confirmed')
        Debt.objects.create(shop=self.shop, client=self.vali, amount_uzs=-100, transaction_type='payment',
                            items=f"To'lov: Non (ID: {sale.id})", status='confirmed')
        call_command('mark_cash_sales', stdout=mock.Mock())
        self.assertEqual(Debt.objects.filter(is_cash_sale=True).count(), 2)


def make_worker(shop, tg_id='333333'):
    from .models import AllowedAdmin
    user = User.objects.create_user(username=tg_id)
    UserProfile.objects.create(user=user, shop=shop, role='worker')
    AllowedAdmin.objects.create(shop=shop, name='Xodim', telegram_id=tg_id)
    return user


@mock.patch('requests.post')
class NavigationAndRoleTests(TestCase):
    def setUp(self):
        self.owner, self.shop = make_shop()
        self.worker = make_worker(self.shop)
        self.vali = Client.objects.create(shop=self.shop, full_name='Vali', phone='+998901112233')

    def test_worker_blocked_from_admin_sections(self, _post):
        self.client.force_login(self.worker)
        for name in ('settings', 'broadcast', 'admin_control'):
            resp = self.client.get(reverse(name))
            self.assertRedirects(resp, reverse('main_menu'), msg_prefix=name)

    def test_worker_menu_hides_admin_links(self, _post):
        self.client.force_login(self.worker)
        resp = self.client.get(reverse('main_menu'))
        self.assertContains(resp, 'Xodim ·')
        self.assertNotContains(resp, reverse('settings'))
        self.assertNotContains(resp, reverse('admin_control'))
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('main_menu'))
        self.assertContains(resp, reverse('admin_control'))
        self.assertContains(resp, reverse('logout'))

    def test_worker_cannot_delete_transactions(self, _post):
        debt = Debt.objects.create(shop=self.shop, client=self.vali, amount_uzs=100, items='x', status='confirmed')
        self.client.force_login(self.worker)
        self.client.get(reverse('manage_debt', args=[debt.uuid, 'delete']))
        self.assertTrue(Debt.objects.filter(id=debt.id).exists())
        self.client.force_login(self.owner)
        self.client.get(reverse('manage_debt', args=[debt.uuid, 'delete']))
        self.assertFalse(Debt.objects.filter(id=debt.id).exists())

    def test_cannot_touch_other_shop_debt(self, _post):
        other_owner, other_shop = make_shop(tg_id='444444', name='Boshqa')
        other_client = Client.objects.create(shop=other_shop, full_name='X', phone='+998900000001')
        debt = Debt.objects.create(shop=other_shop, client=other_client, amount_uzs=1, items='x')
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('manage_debt', args=[debt.uuid, 'delete']))
        self.assertEqual(resp.status_code, 404)

    def test_owner_cannot_be_removed_from_staff(self, _post):
        from .models import AllowedAdmin
        owner_admin = AllowedAdmin.objects.create(shop=self.shop, name='Egasi', telegram_id=int(self.owner.username))
        worker_admin = AllowedAdmin.objects.get(telegram_id=333333)
        self.client.force_login(self.owner)
        self.client.get(reverse('manage_admins_id', args=['delete', owner_admin.id]))
        self.assertTrue(User.objects.filter(id=self.owner.id).exists())
        self.client.get(reverse('manage_admins_id', args=['delete', worker_admin.id]))
        self.assertFalse(User.objects.filter(id=self.worker.id).exists())

    def test_logout_requires_post(self, _post):
        self.client.force_login(self.owner)
        self.client.get(reverse('logout'))
        self.assertIn('_auth_user_id', self.client.session)
        resp = self.client.post(reverse('logout'))
        self.assertRedirects(resp, reverse('landing_page'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_back_button_uses_real_url(self, _post):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('create_debt'))
        self.assertContains(resp, f'href="{reverse("main_menu")}"')
        self.assertNotContains(resp, 'history.back()')
        resp = self.client.get(reverse('client_edit', args=[self.vali.id]))
        self.assertContains(resp, f'href="{reverse("admin_client_detail", args=[self.vali.id])}"')

    def test_client_list_and_new_client_flow(self, _post):
        Debt.objects.create(shop=self.shop, client=self.vali, amount_uzs=500000, items='x', status='confirmed')
        Client.objects.create(shop=self.shop, full_name='Naqd Savdo (Kassa)', phone='000000000')
        self.client.force_login(self.worker)
        resp = self.client.get(reverse('client_list'))
        self.assertContains(resp, '500 000')
        self.assertNotContains(resp, 'Kassa')

        resp = self.client.post(reverse('client_add'), {'full_name': 'Ali', 'phone': '90 123 45 67'})
        ali = Client.objects.get(full_name='Ali')
        self.assertEqual(ali.phone, '+998901234567')
        self.assertRedirects(resp, reverse('admin_client_detail', args=[ali.id]))
        resp = self.client.get(reverse('admin_client_detail', args=[ali.id]))
        self.assertContains(resp, str(Client.objects.get(id=ali.id).invite_token))

    def test_dashboard_shows_top_debtors_only(self, _post):
        Debt.objects.create(shop=self.shop, client=self.vali, amount_uzs=500000, items='x', status='confirmed')
        Client.objects.create(shop=self.shop, full_name='Toza Mijoz', phone='+998900000002')
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'Vali')
        self.assertNotContains(resp, 'Toza Mijoz')
