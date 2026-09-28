import base64
import hashlib
import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Shop, UserProfile
from .models import SubscriptionPayment

PAYME = dict(PAYME_MERCHANT_ID='merchant123', PAYME_KEY='secret-key', PAYME_TEST_MODE=True)
CLICK = dict(CLICK_SERVICE_ID='111', CLICK_MERCHANT_ID='222', CLICK_SECRET_KEY='click-secret')


def make_shop():
    user = User.objects.create_user(username='555555')
    shop = Shop.objects.create(name='Baraka', owner=user, subscription_ends_at=timezone.now())
    UserProfile.objects.create(user=user, shop=shop, role='admin')
    return user, shop


@override_settings(SUBSCRIPTION_PRICE=100000, **PAYME, **CLICK)
@mock.patch('core.telegram.send_message')
class StartPaymentTests(TestCase):
    def setUp(self):
        self.user, self.shop = make_shop()
        self.client.force_login(self.user)

    def test_payme_redirect(self, _send):
        resp = self.client.post(reverse('start_payment'), {'provider': 'payme', 'months': 3})
        payment = SubscriptionPayment.objects.get()
        self.assertEqual((payment.amount, payment.months, payment.status), (300000, 3, 'new'))
        self.assertTrue(resp['Location'].startswith('https://checkout.test.paycom.uz/'))
        decoded = base64.b64decode(resp['Location'].rsplit('/', 1)[1]).decode()
        self.assertIn(f'ac.order_id={payment.id};a=30000000', decoded)

    def test_click_redirect(self, _send):
        resp = self.client.post(reverse('start_payment'), {'provider': 'click', 'months': 1})
        self.assertIn('my.click.uz/services/pay', resp['Location'])
        self.assertIn('amount=100000.00', resp['Location'])

    def test_disabled_provider_and_bad_plan(self, _send):
        with override_settings(PAYME_KEY=''):
            self.client.post(reverse('start_payment'), {'provider': 'payme', 'months': 1})
        self.client.post(reverse('start_payment'), {'provider': 'click', 'months': 5})
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_pricing_shows_buttons_only_when_configured(self, _send):
        self.assertContains(self.client.get(reverse('pricing_page')), 'Payme orqali')
        with override_settings(PAYME_KEY='', CLICK_SECRET_KEY=''):
            self.assertNotContains(self.client.get(reverse('pricing_page')), 'Payme orqali')


@override_settings(SUBSCRIPTION_PRICE=100000, **PAYME)
@mock.patch('core.telegram.send_message')
class PaymeTests(TestCase):
    def setUp(self):
        _, self.shop = make_shop()
        self.payment = SubscriptionPayment.objects.create(shop=self.shop, provider='payme', months=1, amount=100000)
        self.auth = 'Basic ' + base64.b64encode(b'Paycom:secret-key').decode()

    def rpc(self, method, params, auth=None):
        resp = self.client.post(reverse('payme_endpoint'), data=json.dumps({'method': method, 'params': params, 'id': 7}),
                                content_type='application/json', HTTP_AUTHORIZATION=auth or self.auth)
        return resp.json()

    def account(self, amount=10000000, order=None):
        return {'amount': amount, 'account': {'order_id': str(order or self.payment.id)}}

    def test_auth_required(self, _send):
        self.assertEqual(self.rpc('CheckPerformTransaction', self.account(), auth='Basic xxx')['error']['code'], -32504)

    def test_check_perform(self, _send):
        self.assertEqual(self.rpc('CheckPerformTransaction', self.account())['result'], {'allow': True})
        self.assertEqual(self.rpc('CheckPerformTransaction', self.account(amount=5))['error']['code'], -31001)
        self.assertEqual(self.rpc('CheckPerformTransaction', self.account(order=999))['error']['code'], -31050)

    def test_full_payment_flow(self, send):
        before = self.shop.subscription_ends_at
        created = self.rpc('CreateTransaction', dict(self.account(), id='pm-1', time=1))['result']
        self.assertEqual(created['state'], 1)
        # Takroriy CreateTransaction - o'sha javob
        self.assertEqual(self.rpc('CreateTransaction', dict(self.account(), id='pm-1', time=1))['result'], created)
        # Boshqa tranzaksiya shu buyurtmaga - rad
        self.assertEqual(self.rpc('CreateTransaction', dict(self.account(), id='pm-2', time=1))['error']['code'], -31051)

        performed = self.rpc('PerformTransaction', {'id': 'pm-1'})['result']
        self.assertEqual(performed['state'], 2)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'pm-1'})['result'], performed)  # idempotent

        self.payment.refresh_from_db()
        self.shop.refresh_from_db()
        self.assertEqual(self.payment.status, 'paid')
        self.assertGreaterEqual((self.shop.subscription_ends_at - before).days, 29)
        send.assert_called_once()  # egasiga bir marta xabar

        self.assertEqual(self.rpc('CancelTransaction', {'id': 'pm-1', 'reason': 5})['error']['code'], -31007)
        check = self.rpc('CheckTransaction', {'id': 'pm-1'})['result']
        self.assertEqual((check['state'], check['transaction']), (2, str(self.payment.id)))
        statement = self.rpc('GetStatement', {'from': 0, 'to': 10 ** 14})['result']['transactions']
        self.assertEqual([t['id'] for t in statement], ['pm-1'])

    def test_cancel_before_perform(self, send):
        self.rpc('CreateTransaction', dict(self.account(), id='pm-1', time=1))
        result = self.rpc('CancelTransaction', {'id': 'pm-1', 'reason': 3})['result']
        self.assertEqual(result['state'], -1)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'pm-1'})['error']['code'], -31008)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'cancelled')
        send.assert_not_called()

    def test_expired_transaction_cannot_be_performed(self, _send):
        self.rpc('CreateTransaction', dict(self.account(), id='pm-1', time=1))
        SubscriptionPayment.objects.filter(id=self.payment.id).update(payme_create_time=1)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'pm-1'})['error']['code'], -31008)
        self.assertEqual(self.rpc('CheckTransaction', {'id': 'pm-1'})['result']['state'], -1)

    def test_unknown_transaction_and_method(self, _send):
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'nope'})['error']['code'], -31003)
        self.assertEqual(self.rpc('Hack', {})['error']['code'], -32601)


@override_settings(**CLICK)
@mock.patch('core.telegram.send_message')
class ClickTests(TestCase):
    def setUp(self):
        _, self.shop = make_shop()
        self.payment = SubscriptionPayment.objects.create(shop=self.shop, provider='click', months=1, amount=100000)

    def call(self, action, amount='100000.00', prepare_id='', error='0', secret='click-secret', trans='9001'):
        data = {'click_trans_id': trans, 'service_id': '111', 'click_paydoc_id': '1',
                'merchant_trans_id': str(self.payment.id), 'amount': amount, 'action': str(action),
                'error': error, 'error_note': '', 'sign_time': '2026-09-28 10:00:00'}
        if action == 1:
            data['merchant_prepare_id'] = str(prepare_id)
        raw = (data['click_trans_id'] + data['service_id'] + secret + data['merchant_trans_id'] +
               (data.get('merchant_prepare_id', '') if action == 1 else '') + amount + str(action) + data['sign_time'])
        data['sign_string'] = hashlib.md5(raw.encode()).hexdigest()
        return self.client.post(reverse('click_endpoint'), data).json()

    def test_prepare_and_complete(self, send):
        prepared = self.call(0)
        self.assertEqual(prepared['error'], 0)
        completed = self.call(1, prepare_id=prepared['merchant_prepare_id'])
        self.assertEqual((completed['error'], completed['merchant_confirm_id']), (0, self.payment.id))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'paid')
        self.assertEqual(self.call(1, prepare_id=self.payment.id)['error'], -4)  # qayta - allaqachon to'langan
        send.assert_called_once()

    def test_bad_sign_and_amount(self, _send):
        self.assertEqual(self.call(0, secret='wrong')['error'], -1)
        self.assertEqual(self.call(0, amount='5.00')['error'], -2)

    def test_click_reported_failure_cancels(self, _send):
        self.call(0)
        self.assertEqual(self.call(1, prepare_id=self.payment.id, error='-5017')['error'], -9)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'cancelled')
