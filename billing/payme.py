"""
Payme Merchant API (JSON-RPC 2.0) - obuna to'lovlari uchun.
Hujjat: https://developer.help.paycom.uz/metody-merchant-api/

Payme bizning /billing/payme/ manzilimizga so'rov yuboradi. Hisob maydoni: account.order_id
(= SubscriptionPayment.id). Summalar tiyinda (1 so'm = 100 tiyin), vaqtlar millisekundda.
"""
import base64
import binascii
import hmac
import time

from django.conf import settings
from django.db import transaction

from .models import SubscriptionPayment

# Yaratilgan tranzaksiya shuncha vaqtdan keyin bajarib bo'lmaydi (Payme talabi: 12 soat)
TRANSACTION_TIMEOUT_MS = 12 * 60 * 60 * 1000

# Xato kodlari
AUTH_ERROR = -32504
METHOD_NOT_FOUND = -32601
PARSE_ERROR = -32700
WRONG_AMOUNT = -31001
TRANSACTION_NOT_FOUND = -31003
CANNOT_CANCEL = -31007
CANNOT_PERFORM = -31008
ORDER_NOT_FOUND = -31050
ORDER_UNAVAILABLE = -31051

MESSAGES = {
    AUTH_ERROR: "Avtorizatsiya xatosi",
    METHOD_NOT_FOUND: "Metod topilmadi",
    PARSE_ERROR: "So'rov noto'g'ri",
    WRONG_AMOUNT: "Summa noto'g'ri",
    TRANSACTION_NOT_FOUND: "Tranzaksiya topilmadi",
    CANNOT_CANCEL: "Buyurtma bajarilgan, bekor qilib bo'lmaydi",
    CANNOT_PERFORM: "Bu amalni bajarib bo'lmaydi",
    ORDER_NOT_FOUND: "Buyurtma topilmadi",
    ORDER_UNAVAILABLE: "Buyurtma to'langan yoki boshqa to'lov kutilmoqda",
}


class PaymeError(Exception):
    def __init__(self, code, data=None):
        super().__init__(code)
        self.code = code
        self.data = data


def now_ms():
    return int(time.time() * 1000)


def error_response(request_id, code, data=None):
    text = MESSAGES.get(code, "Xato")
    error = {"code": code, "message": {"uz": text, "ru": text, "en": text}}
    if data:
        error["data"] = data
    return {"error": error, "id": request_id}


def check_auth(header):
    """Authorization: Basic base64("Paycom:<KEY>")"""
    if not settings.PAYME_KEY or not header or not header.startswith('Basic '):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    login, _, key = decoded.partition(':')
    return login == 'Paycom' and hmac.compare_digest(key, settings.PAYME_KEY)


def checkout_url(payment, return_url):
    params = f"m={settings.PAYME_MERCHANT_ID};ac.order_id={payment.id};a={payment.amount_tiyin};c={return_url}"
    host = 'https://checkout.test.paycom.uz' if settings.PAYME_TEST_MODE else 'https://checkout.paycom.uz'
    return f"{host}/{base64.b64encode(params.encode()).decode()}"


# --- Yordamchilar ---

def _order_for(params):
    """account.order_id bo'yicha to'lanishi mumkin bo'lgan buyurtma."""
    order_id = str((params.get('account') or {}).get('order_id', ''))
    if not order_id.isdigit():
        raise PaymeError(ORDER_NOT_FOUND, 'order_id')
    payment = SubscriptionPayment.objects.filter(id=int(order_id), provider='payme').first()
    if not payment:
        raise PaymeError(ORDER_NOT_FOUND, 'order_id')
    if params.get('amount') != payment.amount_tiyin:
        raise PaymeError(WRONG_AMOUNT, 'amount')
    return payment


def _transaction(params):
    payment = SubscriptionPayment.objects.filter(provider='payme', provider_trans_id=str(params.get('id'))).first()
    if not payment:
        raise PaymeError(TRANSACTION_NOT_FOUND)
    return payment


def _cancel(payment, reason, state):
    payment.payme_state = state
    payment.payme_cancel_time = now_ms()
    payment.cancel_reason = reason
    payment.status = 'cancelled'
    payment.save(update_fields=['payme_state', 'payme_cancel_time', 'cancel_reason', 'status'])


def _state(payment):
    return {
        "create_time": payment.payme_create_time,
        "perform_time": payment.payme_perform_time,
        "cancel_time": payment.payme_cancel_time,
        "transaction": str(payment.id),
        "state": payment.payme_state,
        "reason": payment.cancel_reason,
    }


# --- Metodlar ---

def check_perform_transaction(params):
    payment = _order_for(params)
    if payment.status not in ('new', 'pending') or payment.payme_state not in (0,):
        raise PaymeError(ORDER_UNAVAILABLE, 'order_id')
    return {"allow": True}


@transaction.atomic
def create_transaction(params):
    trans_id = str(params.get('id'))
    existing = SubscriptionPayment.objects.select_for_update().filter(provider='payme', provider_trans_id=trans_id).first()
    if existing:
        if existing.payme_state != 1:
            raise PaymeError(CANNOT_PERFORM)
        if now_ms() - existing.payme_create_time > TRANSACTION_TIMEOUT_MS:
            _cancel(existing, reason=4, state=-1)
            raise PaymeError(CANNOT_PERFORM)
        return {"create_time": existing.payme_create_time, "transaction": str(existing.id), "state": 1}

    payment = _order_for(params)
    payment = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
    # Buyurtmaga boshqa tranzaksiya ochilgan yoki u allaqachon yakunlangan
    if payment.status not in ('new',) or payment.provider_trans_id:
        raise PaymeError(ORDER_UNAVAILABLE, 'order_id')

    payment.provider_trans_id = trans_id
    payment.payme_state = 1
    payment.payme_create_time = now_ms()
    payment.status = 'pending'
    payment.save(update_fields=['provider_trans_id', 'payme_state', 'payme_create_time', 'status'])
    return {"create_time": payment.payme_create_time, "transaction": str(payment.id), "state": 1}


def perform_transaction(params):
    payment = _transaction(params)
    if payment.payme_state == 1:
        if now_ms() - payment.payme_create_time > TRANSACTION_TIMEOUT_MS:
            _cancel(payment, reason=4, state=-1)
            raise PaymeError(CANNOT_PERFORM)
        payment.payme_state = 2
        payment.payme_perform_time = now_ms()
        payment.save(update_fields=['payme_state', 'payme_perform_time'])
        payment.mark_paid()
    elif payment.payme_state != 2:
        raise PaymeError(CANNOT_PERFORM)
    return {"transaction": str(payment.id), "perform_time": payment.payme_perform_time, "state": 2}


def cancel_transaction(params):
    payment = _transaction(params)
    if payment.payme_state == 1:
        _cancel(payment, reason=params.get('reason'), state=-1)
    elif payment.payme_state == 2:
        # Obuna allaqachon uzaytirilgan - qaytarish admin orqali qo'lda qilinadi
        raise PaymeError(CANNOT_CANCEL)
    return {"transaction": str(payment.id), "cancel_time": payment.payme_cancel_time, "state": payment.payme_state}


def check_transaction(params):
    return _state(_transaction(params))


def get_statement(params):
    payments = SubscriptionPayment.objects.filter(
        provider='payme', payme_create_time__gte=params.get('from', 0),
        payme_create_time__lte=params.get('to', 0)).exclude(provider_trans_id='').order_by('payme_create_time')
    return {"transactions": [
        dict(_state(p), id=p.provider_trans_id, time=p.payme_create_time, amount=p.amount_tiyin,
             account={"order_id": str(p.id)})
        for p in payments
    ]}


METHODS = {
    'CheckPerformTransaction': check_perform_transaction,
    'CreateTransaction': create_transaction,
    'PerformTransaction': perform_transaction,
    'CancelTransaction': cancel_transaction,
    'CheckTransaction': check_transaction,
    'GetStatement': get_statement,
}


def handle(body, auth_header):
    """JSON-RPC so'rovni bajaradi va javob (dict) qaytaradi."""
    request_id = body.get('id') if isinstance(body, dict) else None
    if not check_auth(auth_header):
        return error_response(request_id, AUTH_ERROR)
    if not isinstance(body, dict):
        return error_response(request_id, PARSE_ERROR)
    method = METHODS.get(body.get('method'))
    if not method:
        return error_response(request_id, METHOD_NOT_FOUND, body.get('method'))
    try:
        return {"result": method(body.get('params') or {}), "id": request_id}
    except PaymeError as exc:
        return error_response(request_id, exc.code, exc.data)
