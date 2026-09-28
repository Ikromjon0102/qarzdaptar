"""
Click SHOP API (Prepare / Complete) - obuna to'lovlari uchun.
Hujjat: https://docs.click.uz/click-api-request/

Click bizning /billing/click/ manzilimizga ikki bosqichda POST yuboradi:
  action=0 (Prepare)  - buyurtmani tekshirish
  action=1 (Complete) - to'lov yakunlandi (yoki error < 0 bo'lsa bekor bo'ldi)
merchant_trans_id = SubscriptionPayment.id
"""
import hashlib
import hmac
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings

from .models import SubscriptionPayment

SUCCESS = 0
SIGN_FAILED = -1
WRONG_AMOUNT = -2
ACTION_NOT_FOUND = -3
ALREADY_PAID = -4
ORDER_NOT_FOUND = -5
TRANSACTION_NOT_FOUND = -6
BAD_REQUEST = -8
CANCELLED = -9

NOTES = {
    SUCCESS: 'Success',
    SIGN_FAILED: 'SIGN CHECK FAILED!',
    WRONG_AMOUNT: 'Incorrect parameter amount',
    ACTION_NOT_FOUND: 'Action not found',
    ALREADY_PAID: 'Already paid',
    ORDER_NOT_FOUND: 'Order does not exist',
    TRANSACTION_NOT_FOUND: 'Transaction does not exist',
    BAD_REQUEST: 'Error in request from click',
    CANCELLED: 'Transaction cancelled',
}


def pay_url(payment, return_url):
    query = urlencode({
        'service_id': settings.CLICK_SERVICE_ID,
        'merchant_id': settings.CLICK_MERCHANT_ID,
        'amount': f"{payment.amount:.2f}",
        'transaction_param': payment.id,
        'return_url': return_url,
    })
    return f"https://my.click.uz/services/pay?{query}"


def expected_sign(data):
    parts = [data.get('click_trans_id', ''), data.get('service_id', ''), settings.CLICK_SECRET_KEY,
             data.get('merchant_trans_id', '')]
    if data.get('action') == '1':
        parts.append(data.get('merchant_prepare_id', ''))
    parts += [data.get('amount', ''), data.get('action', ''), data.get('sign_time', '')]
    return hashlib.md5(''.join(str(p) for p in parts).encode()).hexdigest()


def handle(data):
    """data - Click yuborgan POST maydonlari (dict). Javob - dict (JSON qilib qaytariladi)."""
    response = {
        'click_trans_id': data.get('click_trans_id'),
        'merchant_trans_id': data.get('merchant_trans_id'),
    }

    def reply(code, **extra):
        return dict(response, error=code, error_note=NOTES[code], **extra)

    required = ('click_trans_id', 'service_id', 'merchant_trans_id', 'amount', 'action', 'sign_time', 'sign_string')
    if not settings.CLICK_SECRET_KEY or any(not data.get(k) and data.get(k) != '0' for k in required):
        return reply(BAD_REQUEST)
    if not hmac.compare_digest(expected_sign(data), str(data.get('sign_string'))):
        return reply(SIGN_FAILED)
    if data.get('action') not in ('0', '1'):
        return reply(ACTION_NOT_FOUND)

    order_id = str(data.get('merchant_trans_id'))
    payment = SubscriptionPayment.objects.filter(id=int(order_id), provider='click').first() if order_id.isdigit() else None
    if not payment:
        return reply(ORDER_NOT_FOUND)
    try:
        amount = Decimal(str(data.get('amount')))
    except InvalidOperation:
        return reply(WRONG_AMOUNT)
    if amount != payment.amount:
        return reply(WRONG_AMOUNT)
    if payment.status == 'paid':
        return reply(ALREADY_PAID)
    if payment.status == 'cancelled':
        return reply(CANCELLED)

    if data.get('action') == '0':  # Prepare
        payment.provider_trans_id = str(data.get('click_trans_id'))
        payment.status = 'pending'
        payment.save(update_fields=['provider_trans_id', 'status'])
        return reply(SUCCESS, merchant_prepare_id=payment.id)

    # Complete
    if str(data.get('merchant_prepare_id')) != str(payment.id) or payment.provider_trans_id != str(data.get('click_trans_id')):
        return reply(TRANSACTION_NOT_FOUND)
    try:
        click_error = int(data.get('error') or 0)
    except ValueError:
        click_error = 0
    if click_error < 0:
        payment.status = 'cancelled'
        payment.save(update_fields=['status'])
        return reply(CANCELLED)
    payment.mark_paid()
    return reply(SUCCESS, merchant_confirm_id=payment.id)
