from core import telegram
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

    for chat_id in shop_staff_ids(order.shop):
        telegram.send_message(chat_id, text, reply_markup=reply_markup)
