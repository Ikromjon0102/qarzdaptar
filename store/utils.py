import requests
from django.conf import settings

from core.utils import shop_staff_ids


def format_sum(value):
    return f"{value:,.0f}".replace(',', ' ')


def send_order_to_shop(order, items):
    """Yangi buyurtmani do'kon jamoasiga (egasi va xodimlar) tugmalar bilan yuboradi."""
    text = f"📦 <b>Yangi buyurtma #{order.id}</b>\n"
    text += f"👤 Mijoz: <b>{order.client.full_name}</b>\n"
    text += f"📞 Tel: {order.client.phone}\n"
    text += "➖➖➖➖➖➖➖➖\n"
    for item in items:
        name = item.product.name if item.product else "O'chirilgan tovar"
        text += f"🔸 {name}\n   {item.qty} x {format_sum(item.price)} = <b>{format_sum(item.total)} so'm</b>\n"
    text += "➖➖➖➖➖➖➖➖\n"
    text += f"💰 <b>JAMI: {format_sum(order.total_price)} so'm</b>"

    reply_markup = {"inline_keyboard": [
        [{"text": "✅ Nasiyaga yozish", "callback_data": f"order_accept_{order.id}"}],
        [{"text": "❌ Bekor qilish", "callback_data": f"order_reject_{order.id}"}],
    ]}

    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    for chat_id in shop_staff_ids(order.shop):
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                     "reply_markup": reply_markup}, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")
