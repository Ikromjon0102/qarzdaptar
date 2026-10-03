"""
Telegram Mini App `initData` imzosini tekshirish.
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

initData'ni Telegram bot tokeni bilan imzolaydi. Imzo to'g'ri bo'lsa, ichidagi
foydalanuvchi ID siga ishonish mumkin; aks holda ID ni istalgan odam soxtalashtira oladi.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from django.conf import settings

# Imzo shuncha vaqtgacha amal qiladi (Mini App qayta ochilganda yangilanadi)
INIT_DATA_MAX_AGE = 24 * 60 * 60


def verify_init_data(init_data, bot_token=None, max_age=INIT_DATA_MAX_AGE):
    """
    initData to'g'ri imzolangan va eskirmagan bo'lsa, Telegram foydalanuvchisini (dict) qaytaradi.
    Aks holda None.
    """
    bot_token = bot_token if bot_token is not None else settings.BOT_TOKEN
    if not init_data or not bot_token:
        return None

    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None

    received_hash = data.pop('hash', None)
    if not received_hash:
        return None

    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    try:
        auth_date = int(data.get('auth_date', 0))
        user = json.loads(data.get('user', '{}'))
    except (ValueError, TypeError):
        return None
    if max_age and time.time() - auth_date > max_age:
        return None
    if not isinstance(user, dict) or not user.get('id'):
        return None
    return user


def sign_init_data(fields, bot_token=None):
    """Testlar uchun: berilgan maydonlardan to'g'ri imzolangan initData yasaydi."""
    from urllib.parse import urlencode

    bot_token = bot_token if bot_token is not None else settings.BOT_TOKEN
    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    fields = dict(fields, hash=hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest())
    return urlencode(fields)
