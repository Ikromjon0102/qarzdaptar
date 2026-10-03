"""
To'lov muddati: qaysi nasiyalar hali to'lanmagan va muddati o'tgan.

To'lovlar aniq bir nasiyaga bog'lanmaydi, shuning uchun ular eng eski nasiyalarni birinchi yopadi (FIFO),
so'm va dollar alohida. Qolgan (to'lanmagan) qismi bor nasiya - "ochiq". Ochiq nasiyaning muddati
bugundan oldin bo'lsa - muddati o'tgan.

Naqd savdolar (savdo + darhol to'lov juftligi) hisobga olinmaydi.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from .models import Debt

MAX_DUE_DAYS = 730  # muddat 2 yildan uzoq bo'lmaydi


@dataclass
class DueStatus:
    overdue_uzs: Decimal = Decimal(0)
    overdue_usd: Decimal = Decimal(0)
    overdue_since: Optional[date] = None   # eng eski o'tib ketgan muddat
    next_due: Optional[date] = None        # eng yaqin kelayotgan muddat (bugun ham)
    next_due_uzs: Decimal = Decimal(0)
    next_due_usd: Decimal = Decimal(0)
    open_debts: dict = field(default_factory=dict)  # {nasiya id: (qolgan so'm, qolgan $)}

    @property
    def is_overdue(self):
        return self.overdue_since is not None

    @property
    def overdue_days(self):
        return (timezone.localdate() - self.overdue_since).days if self.overdue_since else 0

    @property
    def days_to_next(self):
        return (self.next_due - timezone.localdate()).days if self.next_due else None


def _allocate(rows, today):
    """rows: bitta mijozning (id, type, uzs, usd, due_date) yozuvlari, eskisidan yangisiga."""
    status = DueStatus()
    paid_uzs = sum(-r[2] for r in rows if r[1] == 'payment')
    paid_usd = sum(-r[3] for r in rows if r[1] == 'payment')
    for debt_id, kind, uzs, usd, due in rows:
        if kind != 'debt':
            continue
        cover_uzs = min(max(paid_uzs, 0), uzs)
        cover_usd = min(max(paid_usd, 0), usd)
        paid_uzs -= cover_uzs
        paid_usd -= cover_usd
        left_uzs, left_usd = uzs - cover_uzs, usd - cover_usd
        if left_uzs <= 0 and left_usd <= 0:
            continue
        status.open_debts[debt_id] = (left_uzs, left_usd)
        if not due:
            continue
        if due < today:
            status.overdue_uzs += left_uzs
            status.overdue_usd += left_usd
            status.overdue_since = min(filter(None, [status.overdue_since, due]))
        elif status.next_due is None or due < status.next_due:
            status.next_due, status.next_due_uzs, status.next_due_usd = due, left_uzs, left_usd
        elif due == status.next_due:
            status.next_due_uzs += left_uzs
            status.next_due_usd += left_usd
    return status


def _rows(queryset):
    return (queryset.filter(status='confirmed', is_cash_sale=False)
            .order_by('created_at', 'id')
            .values_list('client_id', 'id', 'transaction_type', 'amount_uzs', 'amount_usd', 'due_date'))


def shop_due_map(shop, today=None):
    """{client_id: DueStatus} - do'konning barcha mijozlari uchun bitta so'rov bilan."""
    today = today or timezone.localdate()
    grouped = defaultdict(list)
    for client_id, *row in _rows(Debt.objects.filter(shop=shop)):
        grouped[client_id].append(row)
    return {client_id: _allocate(rows, today) for client_id, rows in grouped.items()}


def client_due_status(client, today=None):
    rows = [row for _, *row in _rows(Debt.objects.filter(client=client))]
    return _allocate(rows, today or timezone.localdate())


def overdue_summary(shop, today=None):
    """Bosh sahifa uchun: muddati o'tgan mijozlar soni va jami summa."""
    statuses = [s for s in shop_due_map(shop, today).values() if s.is_overdue]
    return {
        'count': len(statuses),
        'uzs': sum((s.overdue_uzs for s in statuses), Decimal(0)),
        'usd': sum((s.overdue_usd for s in statuses), Decimal(0)),
    }


def parse_due_date(raw, today=None):
    """Formadagi sanani (YYYY-MM-DD) tekshirish: bugundan oldin yoki 2 yildan keyin bo'lmasin."""
    today = today or timezone.localdate()
    try:
        value = date.fromisoformat((raw or '').strip())
    except ValueError:
        return None
    if value < today or (value - today).days > MAX_DUE_DAYS:
        return None
    return value
