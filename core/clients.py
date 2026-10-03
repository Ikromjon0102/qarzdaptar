"""
Mijoz qo'shish yordamchilari: daftardan ko'chirilgan boshlang'ich qarz va botga kontakt yuborib qo'shish.
"""
import html

from django.conf import settings

from . import plans, telegram
from .models import Client, Debt, Shop, UserProfile
from .reminders import balance_line
from .utils import clean_phone_number, shop_staff_ids

OPENING_ITEMS = "Daftardan ko'chirilgan qarz"
OPENING_REJECT_REASON = "Daftardan ko'chirilgan qarz bilan rozi emas"


def add_opening_balance(client, amount_uzs=0, amount_usd=0):
    """
    Qog'oz daftardagi hozirgi qarz. Darhol balansga yoziladi (mijoz hali botga ulanmagan),
    mijoz botga ulanganda uni bir marta tasdiqlaydi yoki rad etadi.
    """
    if amount_uzs <= 0 and amount_usd <= 0:
        return None
    return Debt.objects.create(shop=client.shop, client=client, transaction_type='debt', status='confirmed',
                               is_opening=True, amount_uzs=amount_uzs, amount_usd=amount_usd, items=OPENING_ITEMS)


def ask_opening_confirmation(client):
    """Botga endi ulangan mijozdan ko'chirilgan qarzni tasdiqlashni so'rash."""
    if not client.telegram_id:
        return
    for debt in Debt.objects.filter(client=client, is_opening=True, opening_ack=False, status='confirmed'):
        telegram.send_message(
            client.telegram_id,
            f"📒 <b>{html.escape(client.shop.name)}</b>\n\n"
            f"Do'kon daftaridan ko'chirilgan qarzingiz:\n💰 <b>{balance_line(debt.amount_uzs, debt.amount_usd)}</b>\n\n"
            "Shu summa to'g'rimi?",
            reply_markup={"inline_keyboard": [[
                {"text": "✅ Ha, to'g'ri", "callback_data": f"opening_ok:{debt.id}"},
                {"text": "❌ Yo'q", "callback_data": f"opening_no:{debt.id}"},
            ]]},
        )


def _notify_staff(shop, text):
    for chat_id in shop_staff_ids(shop):
        telegram.send_message(chat_id, text)


def handle_opening_answer(chat_id, message_id, debt_id, agree):
    """Mijoz ko'chirilgan qarz bo'yicha javob berdi (faqat o'z qarziga, bir marta)."""
    debt = Debt.objects.select_related('client', 'shop').filter(id=debt_id, is_opening=True).first()
    if not debt or debt.client.telegram_id != int(chat_id):
        telegram.edit_message(chat_id, message_id, "❌ So'rov topilmadi.")
        return
    if debt.opening_ack:
        telegram.edit_message(chat_id, message_id, "ℹ️ Bu qarz bo'yicha javob allaqachon berilgan.")
        return

    amount = balance_line(debt.amount_uzs, debt.amount_usd)
    name = html.escape(debt.client.full_name)
    debt.opening_ack = True
    if agree:
        debt.save(update_fields=['opening_ack'])
        telegram.edit_message(chat_id, message_id, f"✅ Tasdiqlandi: {amount}. Rahmat!")
        _notify_staff(debt.shop, f"✅ <b>{name}</b> daftardan ko'chirilgan qarzni tasdiqladi\n💰 {amount}")
    else:
        debt.status = 'rejected'
        debt.reject_reason = OPENING_REJECT_REASON
        debt.save(update_fields=['opening_ack', 'status', 'reject_reason'])
        telegram.edit_message(chat_id, message_id,
                              "Do'konga xabar berildi — summa balansingizdan olib tashlandi. "
                              "Do'kon to'g'rilab, qayta yuboradi.")
        _notify_staff(debt.shop, f"❌ <b>{name}</b> daftardan ko'chirilgan qarz bilan rozi emas\n💰 {amount}\n\n"
                                 "Summa balansdan olib tashlandi. Mijoz sahifasida izoh bilan qayta yuborishingiz mumkin.")


# ---------- Botga kontakt yuborib mijoz qo'shish ----------

def staff_shop(chat_id):
    """Shu Telegram akkaunt qaysi do'kon jamoasida (egasi yoki xodimi)? Bo'lmasa None."""
    shop = Shop.objects.filter(owner__username=str(chat_id)).first()
    if shop:
        return shop
    profile = UserProfile.objects.select_related('shop').filter(user__username=str(chat_id)).first()
    return profile.shop if profile else None


def handle_contact(chat_id, contact):
    """Do'kon xodimi botga kontakt yubordi: mijozlarga qo'shamiz va taklif havolasini beramiz."""
    shop = staff_shop(chat_id)
    if not shop:
        telegram.send_message(chat_id, "ℹ️ Kontakt orqali mijoz qo'shish faqat do'kon egasi va xodimlari uchun.")
        return

    phone = clean_phone_number(contact.get('phone_number', ''))
    name = ' '.join(filter(None, [contact.get('first_name', '').strip(), contact.get('last_name', '').strip()]))
    if not phone:
        telegram.send_message(chat_id, "❌ Kontaktda telefon raqam topilmadi yoki noto'g'ri.")
        return

    existing = Client.objects.filter(shop=shop, phone=phone).first()
    if existing:
        telegram.send_message(chat_id, f"ℹ️ <b>{html.escape(existing.full_name)}</b> ({phone}) allaqachon "
                                       "mijozlaringiz ro'yxatida bor.", reply_markup=_open_keyboard())
        return
    if not plans.can_add_client(shop):
        limit = plans.current_plan(shop).max_clients
        telegram.send_message(chat_id, f"🔒 {plans.current_plan(shop).name} tarifida {limit} tagacha mijoz. "
                                       "Yangi mijoz uchun tarifni oshiring.", reply_markup=_open_keyboard())
        return

    client = Client.objects.create(shop=shop, full_name=(name or phone)[:100], phone=phone)
    invite = f"https://t.me/{settings.BOT_USERNAME}?start={client.invite_token}"
    telegram.send_message(
        chat_id,
        f"✅ <b>{html.escape(client.full_name)}</b> ({phone}) mijozlarga qo'shildi.\n\n"
        f"Mijozga shu havolani yuboring — bossa, botga ulanadi va nasiyalarni o'zi tasdiqlaydi:\n{invite}\n\n"
        "Eski qarzi bo'lsa, ilovada mijoz sahifasidan yozing. Keyingi mijoz uchun yana kontakt yuboring 📎",
        reply_markup=_open_keyboard(),
    )


def _open_keyboard():
    url = f"https://{settings.SITE_DOMAIN}/auth/telegram-login/"
    return {"inline_keyboard": [[{"text": "🏪 Do'konni ochish", "web_app": {"url": url}}]]}
