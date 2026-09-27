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
