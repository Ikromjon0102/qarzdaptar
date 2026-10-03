"""
Botda do'kon ochish (ro'yxatdan o'tish).

  /start signup  ->  1/2 do'kon nomi (matn)  ->  2/2 do'kon turi (tugmalar)  ->  do'kon tayyor

Telegram ID ni hech kim qo'lda kiritmaydi: u botga yozgan akkauntdan olinadi.
Jarayon holati bazada (BotSignup) saqlanadi - gunicorn'ning bir nechta workeri bo'lsa ham ishlaydi.
"""
import html
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from . import plans, telegram
from .models import AllowedAdmin, BotSignup, Settings, Shop, UserProfile

TRIAL_DAYS = 14
DEFAULT_USD_RATE = 12800

CATEGORY_EMOJI = {
    'grocery': '🛒', 'construction': '🧱', 'plumbing': '🚰', 'tech': '🔌',
    'electronics': '📱', 'clothing': '👕', 'household': '🧺', 'auto': '🚗',
    'pharmacy': '💊', 'cosmetics': '💄', 'furniture': '🛋', 'other': '🏪',
}


def category_label(code):
    return f"{CATEGORY_EMOJI.get(code, '🏪')} {dict(Shop.CATEGORY_CHOICES).get(code, '')}"


def create_shop(telegram_id, shop_name, admin_name, category='other'):
    """Yangi do'kon: egasi (User), profil, ruxsat va sozlamalar. Sinov muddati bilan."""
    with transaction.atomic():
        user = User.objects.create_user(username=str(telegram_id), password=None,  # kirish faqat Telegram orqali
                                        first_name=admin_name[:150])
        shop = Shop.objects.create(
            name=shop_name,
            owner=user,
            category=category,
            plan=plans.STANDARD,  # sinov muddati Standart imkoniyatlari bilan, keyin - Bepul
            is_trial_used=True,
            subscription_ends_at=timezone.now() + timedelta(days=TRIAL_DAYS),
        )
        UserProfile.objects.create(user=user, shop=shop, role='admin')
        AllowedAdmin.objects.update_or_create(telegram_id=telegram_id,
                                              defaults={'shop': shop, 'name': admin_name or shop_name})
        Settings.objects.create(shop=shop, usd_rate=DEFAULT_USD_RATE)
    return shop


def already_registered(chat_id):
    return User.objects.filter(username=str(chat_id)).exists()


def start(chat_id, tg_from):
    """1-qadam: do'kon nomini so'rash."""
    BotSignup.objects.update_or_create(
        telegram_id=chat_id,
        defaults={'step': 'name', 'shop_name': '', 'first_name': (tg_from.get('first_name') or '')[:150]},
    )
    telegram.send_message(
        chat_id,
        "🏪 <b>Do'kon ochamiz!</b> Atigi 2 ta savol.\n\n"
        "<b>1/2.</b> Do'koningiz nomini yozing:\n"
        "<i>Masalan: Baraka Market</i>\n\n"
        "Bekor qilish: /cancel",
    )


def category_keyboard():
    codes = [code for code, _ in Shop.CATEGORY_CHOICES]
    rows = [codes[i:i + 2] for i in range(0, len(codes), 2)]
    return {"inline_keyboard": [
        [{"text": category_label(code), "callback_data": f"signup_cat:{code}"} for code in row] for row in rows
    ]}


def handle_text(chat_id, text):
    """Do'kon nomi kutilayotgan bo'lsa - qabul qiladi. Xabar shu jarayonga tegishli bo'lsa True."""
    signup = BotSignup.objects.filter(telegram_id=chat_id).first()
    if not signup:
        return False

    if signup.step != 'name':
        telegram.send_message(chat_id, "👆 Yuqoridagi tugmalardan do'kon turini tanlang. Bekor qilish: /cancel")
        return True

    name = re.sub(r'\s+', ' ', text or '').strip()
    if not (2 <= len(name) <= 60):
        telegram.send_message(chat_id, "✏️ Do'kon nomini matn bilan yozing (2–60 belgi).\n<i>Masalan: Baraka Market</i>")
        return True

    signup.shop_name = name
    signup.step = 'category'
    signup.save(update_fields=['shop_name', 'step', 'updated_at'])
    telegram.send_message(
        chat_id,
        f"👍 <b>{html.escape(name)}</b>\n\n<b>2/2.</b> Do'koningiz qaysi turdagi?",
        reply_markup=category_keyboard(),
    )
    return True


def handle_category(chat_id, message_id, code):
    """2-qadam: tur tanlandi - do'konni yaratamiz va ochish tugmasini beramiz."""
    signup = BotSignup.objects.filter(telegram_id=chat_id, step='category').first()
    if not signup or code not in dict(Shop.CATEGORY_CHOICES):
        telegram.edit_message(chat_id, message_id, "⌛ Bu so'rov eskirgan. Qaytadan boshlash: /start")
        return

    if already_registered(chat_id):
        signup.delete()
        telegram.edit_message(chat_id, message_id, "ℹ️ Bu Telegram akkauntda do'kon allaqachon ochilgan.",
                              reply_markup=open_shop_keyboard())
        return

    shop = create_shop(chat_id, signup.shop_name, signup.first_name, category=code)
    signup.delete()
    telegram.edit_message(
        chat_id, message_id,
        f"🎉 <b>«{html.escape(shop.name)}» do'koni ochildi!</b>\n"
        f"{category_label(code)}\n\n"
        f"🎁 {TRIAL_DAYS} kun Standart tarif bepul. Keyin Bepul tarifda davom etasiz yoki tarif tanlaysiz — "
        "ma'lumotlar hech qachon o'chmaydi.\n\n"
        "<b>Keyingi qadamlar:</b>\n"
        "1. Mijoz qo'shing va unga havola yuboring\n"
        "2. Nasiya yozing — mijoz Telegramda tasdiqlaydi\n\n"
        "Boshlash uchun pastdagi tugmani bosing 👇",
        reply_markup=open_shop_keyboard(),
    )


def cancel(chat_id):
    if BotSignup.objects.filter(telegram_id=chat_id).delete()[0]:
        telegram.send_message(chat_id, "❌ Ro'yxatdan o'tish bekor qilindi. Qaytadan: /start")
        return True
    return False


def open_shop_keyboard():
    url = f"https://{settings.SITE_DOMAIN}/auth/telegram-login/"
    return {"inline_keyboard": [[{"text": "🏪 Do'konni ochish", "web_app": {"url": url}}]]}
