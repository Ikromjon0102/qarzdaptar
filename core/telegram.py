"""
Telegram Bot API bilan ishlash uchun yagona joy.

- Har bir so'rovda timeout bor: Telegram sekin javob bersa, server qotib qolmaydi.
- Xabarlar fonda (thread pool) yuboriladi: foydalanuvchi sahifani Telegram javobini kutmasdan oladi.
- Xatolar `logging` orqali yoziladi (logs/qarzdaptar.log).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # soniya

# Bir vaqtda ko'pi bilan shuncha so'rov; qolganlari navbatda kutadi
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='telegram')


def _post(method, payload):
    """Telegram API ga so'rov (sinxron). Natija: javob JSON yoki None."""
    if not settings.BOT_TOKEN:
        logger.warning("BOT_TOKEN sozlanmagan, %s yuborilmadi", method)
        return None
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Telegram %s xatosi (chat=%s): %s", method, payload.get('chat_id'), exc)
        return None
    if not data.get('ok'):
        logger.warning("Telegram %s rad etdi (chat=%s): %s", method, payload.get('chat_id'), data.get('description'))
    return data


def call(method, payload, background=None):
    """
    Telegram API metodini chaqirish.
    background=None bo'lsa settings.TELEGRAM_ASYNC ga qaraladi (testlarda sinxron).
    """
    if background is None:
        background = settings.TELEGRAM_ASYNC
    if background:
        _executor.submit(_post, method, payload)
        return None
    return _post(method, payload)


def send_message(chat_id, text, reply_markup=None, background=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return call("sendMessage", payload, background)


def edit_message(chat_id, message_id, text, background=None):
    return call("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                    "text": text, "parse_mode": "HTML"}, background)


def answer_callback(callback_id, text=None, show_alert=False, background=None):
    payload = {"callback_query_id": callback_id}
    if text:
        payload.update(text=text, show_alert=show_alert)
    return call("answerCallbackQuery", payload, background)
