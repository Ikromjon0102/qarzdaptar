"""
Qarzdorlarga eslatma.

Avtomatik: `python manage.py send_reminders` (cron orqali kuniga bir marta).
Qo'lda: mijoz sahifasidagi «Eslatma yuborish» tugmasi.
"""
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db.models import Q, Sum
from django.utils import timezone

from . import dues, plans, telegram
from .models import Client, Debt, Settings


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
    due = dues.client_due_status(client)
    overdue = ""
    if due.is_overdue:
        overdue = (f"⚠️ Muddati o'tgan: <b>{balance_line(due.overdue_uzs, due.overdue_usd)}</b> "
                   f"({due.overdue_since:%d.%m.%Y} dan)\n")
    text = (
        f"🔔 <b>{client.shop.name}</b>\n\n"
        f"Hurmatli {client.full_name}, do'konimizdagi qarzingiz:\n"
        f"💰 <b>{balance_line(bal_uzs, bal_usd)}</b>\n"
        f"{overdue}\n"
        "Imkon bo'lganda to'lab qo'yishingizni so'raymiz. Rahmat!"
    )
    telegram.send_message(client.telegram_id, text, reply_markup=cabinet_button(), background=background)
    Client.objects.filter(id=client.id).update(last_reminded_at=timezone.now())
    return True


def cabinet_button():
    button = {"text": "📒 Hisobimni ko'rish",
              "web_app": {"url": f"https://{dj_settings.SITE_DOMAIN}/auth/telegram-login/"}}
    return {"inline_keyboard": [[button]]}


# ---------- To'lov muddati eslatmalari ----------

DUE_TOMORROW, DUE_TODAY = 1, 2


def due_date_reminders(today=None):
    """
    Muddati ertaga (1) yoki bugun (2) bo'lgan, hali to'lanmagan nasiyalar:
    [(mijoz, bosqich, muddat, qolgan so'm, qolgan $, [nasiya id lar])]. Har bosqich bir marta yuboriladi.
    Muddatni do'kon o'zi qo'ygani uchun umumiy eslatma sozlamasidan qat'i nazar ishlaydi (tarifda bo'lsa).
    """
    today = today or timezone.localdate()
    candidates = (Debt.objects.filter(transaction_type='debt', status='confirmed', is_cash_sale=False,
                                      due_date__in=[today, today + timedelta(days=1)],
                                      client__telegram_id__isnull=False)
                  .select_related('client', 'shop'))
    by_shop = {}
    for debt in candidates:
        stage = DUE_TODAY if debt.due_date == today else DUE_TOMORROW
        if debt.due_stage < stage and debt.shop and plans.has_feature(debt.shop, plans.REMINDERS):
            by_shop.setdefault(debt.shop, []).append((debt, stage))

    result = []
    for shop, items in by_shop.items():
        due_map = dues.shop_due_map(shop, today)
        grouped = {}
        for debt, stage in items:
            left = due_map.get(debt.client_id, dues.DueStatus()).open_debts.get(debt.id)
            if not left:  # allaqachon to'langan
                Debt.objects.filter(id=debt.id).update(due_stage=DUE_TODAY)
                continue
            key = (debt.client_id, stage)
            entry = grouped.setdefault(key, [debt.client, stage, debt.due_date, 0, 0, []])
            entry[3] += left[0]
            entry[4] += left[1]
            entry[5].append(debt.id)
        result.extend(tuple(entry) for entry in grouped.values())
    return result


def send_due_reminder(client, stage, due_date, left_uzs, left_usd, debt_ids, background=None):
    when = "Bugun" if stage == DUE_TODAY else "Ertaga"
    text = (
        f"📅 <b>{client.shop.name}</b>\n\n"
        f"Hurmatli {client.full_name}, {when.lower()} ({due_date:%d.%m.%Y}) to'lov muddati:\n"
        f"💰 <b>{balance_line(left_uzs, left_usd)}</b>\n\n"
        "Imkon bo'lganda to'lab qo'yishingizni so'raymiz. Rahmat!"
    )
    telegram.send_message(client.telegram_id, text, reply_markup=cabinet_button(), background=background)
    Debt.objects.filter(id__in=debt_ids, due_stage__lt=stage).update(due_stage=stage)


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
        if not shop or not plans.has_feature(shop, plans.REMINDERS):
            continue
        cutoff = now - timedelta(days=max(cfg.reminder_days, 1))
        clients = clients_with_debt(shop, cfg.reminder_min_debt).filter(
            Q(last_reminded_at__isnull=True) | Q(last_reminded_at__lte=cutoff))
        for client in clients:
            yield client, client.bal_uzs or 0, client.bal_usd or 0
