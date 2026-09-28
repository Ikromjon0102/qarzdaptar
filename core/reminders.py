"""
Qarzdorlarga eslatma.

Avtomatik: `python manage.py send_reminders` (cron orqali kuniga bir marta).
Qo'lda: mijoz sahifasidagi «Eslatma yuborish» tugmasi.
"""
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db.models import Q, Sum
from django.utils import timezone

from . import telegram
from .models import Client, Settings


def balance_line(bal_uzs, bal_usd):
    parts = []
    if bal_uzs > 0:
        parts.append(f"{bal_uzs:,.0f} so'm".replace(',', ' '))
    if bal_usd > 0:
        parts.append(f"${bal_usd:,.2f}")
    return " + ".join(parts)


def send_reminder(client, bal_uzs, bal_usd, background=None):
    """Mijozga qarz haqida eslatma yuboradi. Qarz bo'lmasa yoki bot ulanmagan bo'lsa - False."""
    if not client.telegram_id or (bal_uzs <= 0 and bal_usd <= 0):
        return False
    text = (
        f"🔔 <b>{client.shop.name}</b>\n\n"
        f"Hurmatli {client.full_name}, do'konimizdagi qarzingiz:\n"
        f"💰 <b>{balance_line(bal_uzs, bal_usd)}</b>\n\n"
        "Imkon bo'lganda to'lab qo'yishingizni so'raymiz. Rahmat!"
    )
    button = {"text": "📒 Hisobimni ko'rish",
              "web_app": {"url": f"https://{dj_settings.SITE_DOMAIN}/auth/telegram-login/"}}
    telegram.send_message(client.telegram_id, text, reply_markup={"inline_keyboard": [[button]]},
                          background=background)
    Client.objects.filter(id=client.id).update(last_reminded_at=timezone.now())
    return True


def clients_with_debt(shop, min_debt=0):
    """Botga ulangan va qarzi bor mijozlar (balans bilan)."""
    return (
        Client.objects.filter(shop=shop, telegram_id__isnull=False)
        .annotate(bal_uzs=Sum('debt__amount_uzs', filter=Q(debt__status='confirmed')),
                  bal_usd=Sum('debt__amount_usd', filter=Q(debt__status='confirmed')))
        .filter(Q(bal_uzs__gt=max(min_debt, 0)) | Q(bal_usd__gt=0))
        .select_related('shop')
    )


def due_reminders(now=None):
    """Eslatma vaqti kelgan (mijoz, qarz so'm, qarz $) ro'yxati - faqat eslatmani yoqqan va obunasi faol do'konlar."""
    now = now or timezone.now()
    shop_settings = Settings.objects.filter(reminder_enabled=True).select_related('shop')
    for cfg in shop_settings:
        shop = cfg.shop
        if not shop or (shop.subscription_ends_at and shop.subscription_ends_at < now):
            continue
        cutoff = now - timedelta(days=max(cfg.reminder_days, 1))
        clients = clients_with_debt(shop, cfg.reminder_min_debt).filter(
            Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lte=cutoff))
        for client in clients:
            yield client, client.bal_uzs or 0, client.bal_usd or 0
