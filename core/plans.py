"""
Tariflar: imkoniyatlar, cheklovlar va narxlar - hammasi shu yerda.

  Bepul     - 30 tagacha mijoz, xodimsiz. Nasiya, to'lov, mijoz tasdiqlashi, Telegram xabarlar.
  Standart  - cheksiz mijoz, 2 xodim, avtomatik eslatma, xabar yuborish, Excel.
  Biznes    - cheksiz xodim + onlayn do'kon.

Narxlar settings (.env) da: PLAN_STANDARD_PRICE, PLAN_BUSINESS_PRICE, PLAN_STANDARD_LAUNCH_PRICE,
LAUNCH_PRICE_UNTIL, LAUNCH_PRICE_LOCK. Yillik to'lov = 10 oylik narx (2 oy bepul).

Pullik tarif muddati tugasa do'kon Bepul tarifga tushadi: hech narsa bloklanmaydi va o'chmaydi,
faqat yangi mijoz qo'shish (limitdan keyin) va pullik imkoniyatlar yopiladi.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.conf import settings
from django.utils import timezone

FREE, STANDARD, BUSINESS = 'free', 'standard', 'business'
CHOICES = ((FREE, 'Bepul'), (STANDARD, 'Standart'), (BUSINESS, 'Biznes'))
PAID = (STANDARD, BUSINESS)

# Imkoniyatlar
REMINDERS, BROADCAST, EXPORT, STORE, TRUST = 'reminders', 'broadcast', 'export', 'store', 'trust'
FEATURE_NAMES = {
    REMINDERS: "Avtomatik eslatma",
    BROADCAST: "Xabar yuborish",
    EXPORT: "Excel eksport",
    STORE: "Onlayn do'kon",
    TRUST: "Mijoz ishonch belgisi",
}

# To'lov davri -> oy soni. Yillik narx = YEAR_PRICED_MONTHS oylik narx.
PERIODS = {'month': 1, 'year': 12}
YEAR_PRICED_MONTHS = 10


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    max_clients: Optional[int]  # None - cheksiz
    max_staff: Optional[int]
    features: frozenset

    @property
    def is_paid(self):
        return self.code in PAID


PLANS = {
    FREE: Plan(FREE, 'Bepul', 30, 0, frozenset()),
    STANDARD: Plan(STANDARD, 'Standart', None, 2, frozenset({REMINDERS, BROADCAST, EXPORT, TRUST})),
    BUSINESS: Plan(BUSINESS, 'Biznes', None, None, frozenset({REMINDERS, BROADCAST, EXPORT, STORE, TRUST})),
}


def minimal_plan_for(feature):
    """Shu imkoniyat bor eng arzon tarif."""
    return next(p for p in (PLANS[STANDARD], PLANS[BUSINESS]) if feature in p.features)


# ---------- Do'konning joriy tarifi ----------

def current_plan(shop):
    """
    Amaldagi tarif. Pullik tarif muddati tugagan bo'lsa - Bepul.
    subscription_ends_at bo'sh bo'lsa - muddatsiz (masalan, bir umrlik litsenziya).
    """
    if shop is None:
        return PLANS[FREE]
    if shop.plan in PAID:
        ends = shop.subscription_ends_at
        if ends is None or ends > timezone.now():
            return PLANS[shop.plan]
    return PLANS[FREE]


def has_feature(shop, feature):
    return feature in current_plan(shop).features


def client_count(shop):
    from .models import CASH_CLIENT_PHONE, Client
    return Client.objects.filter(shop=shop).exclude(phone=CASH_CLIENT_PHONE).count()


def staff_count(shop):
    from .models import UserProfile
    return UserProfile.objects.filter(shop=shop, role='worker').count()


def can_add_client(shop):
    limit = current_plan(shop).max_clients
    return limit is None or client_count(shop) < limit


def can_add_staff(shop):
    limit = current_plan(shop).max_staff
    return limit is None or staff_count(shop) < limit


# ---------- Narxlar ----------

def launch_price_active(day=None):
    """Ishga tushirish narxi amaldami (LAUNCH_PRICE_UNTIL kuni ham kiradi)?"""
    return (day or timezone.localdate()) <= date.fromisoformat(settings.LAUNCH_PRICE_UNTIL)


def list_price(plan_code):
    """Oddiy oylik narx (ishga tushirish chegirmasisiz)."""
    return {STANDARD: settings.PLAN_STANDARD_PRICE, BUSINESS: settings.PLAN_BUSINESS_PRICE}.get(plan_code, 0)


def monthly_price(plan_code, shop=None):
    """Shu do'kon uchun hozirgi oylik narx."""
    if plan_code == STANDARD and (
            launch_price_active() or (settings.LAUNCH_PRICE_LOCK and shop is not None and shop.launch_price_locked)):
        return settings.PLAN_STANDARD_LAUNCH_PRICE
    return list_price(plan_code)


def period_price(plan_code, period, shop=None):
    months = YEAR_PRICED_MONTHS if period == 'year' else 1
    return monthly_price(plan_code, shop) * months


def period_days(months):
    return 365 if months == 12 else 30 * months


def price_table(shop=None):
    """Narx sahifalari uchun: har bir pullik tarifning oylik/yillik narxi va chizib qo'yiladigan narxi."""
    rows = {}
    for code in PAID:
        month = monthly_price(code, shop)
        regular = list_price(code)
        rows[code] = {
            'month': month,
            'year': month * YEAR_PRICED_MONTHS,
            'year_per_month': int(round(month * YEAR_PRICED_MONTHS / 12, -2)),
            'old_month': regular if regular > month else None,
            'old_year': regular * YEAR_PRICED_MONTHS if regular > month else None,
        }
    return rows
