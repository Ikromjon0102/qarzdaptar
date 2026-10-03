"""
Mijozga ishonch belgisi - faqat SHU do'konning o'z tarixidan (boshqa do'konlarga hech narsa ko'rinmaydi).

To'lovlar eng eski nasiyani birinchi yopadi (FIFO, so'm va dollar alohida). Shu orqali har bir muddatli
nasiya qachon to'liq yopilganini topamiz va muddat bilan solishtiramiz:
  - o'z vaqtida yopilgan / kechikib yopilgan (necha kun)
  - hozir muddati o'tganlar (core.dues)
Rahbar qo'lda «Ehtiyot bo'ling» belgisi va yopiq izoh ham qo'ya oladi.
"""
from collections import defaultdict, deque
from dataclasses import dataclass

from django.utils import timezone

from . import dues
from .models import Client, Debt

RISK_OVERDUE_DAYS = 30   # shuncha kundan ko'p muddati o'tgan bo'lsa - xavfli
RISK_LATE_COUNT = 3      # shuncha marta kechiktirgan bo'lsa - xavfli
GOOD_ON_TIME = 3         # kamida shuncha marta o'z vaqtida to'lagan va kechiktirmagan - ishonchli


@dataclass
class Trust:
    level: str = 'new'            # good / new / warn / risk
    on_time: int = 0
    late: int = 0
    avg_delay: int = 0            # kechikkanlarida o'rtacha necha kun
    overdue_days: int = 0
    flagged: bool = False
    note: str = ''

    @property
    def label(self):
        return {'good': "Ishonchli", 'new': "Ma'lumot kam", 'warn': "E'tibor bering",
                'risk': "Ehtiyot bo'ling"}[self.level]

    @property
    def summary(self):
        parts = []
        if self.overdue_days:
            parts.append(f"hozir {self.overdue_days} kundan beri muddati o'tgan")
        if self.late:
            parts.append(f"{self.late} marta kechiktirgan (o'rtacha {self.avg_delay} kun)")
        if self.on_time:
            parts.append(f"{self.on_time} marta o'z vaqtida to'lagan")
        if self.flagged:
            parts.insert(0, "rahbar belgilagan")
        return ", ".join(parts) or "Muddatli nasiyalar hali yo'q"

    @property
    def warning(self):
        """Nasiya yozishda ko'rsatiladigan ogohlantirish (kerak bo'lmasa bo'sh)."""
        if self.level not in ('warn', 'risk'):
            return ''
        return f"{self.label}: {self.summary}." + (f" Izoh: {self.note}" if self.note else '')


def _paid_dates(rows):
    """rows: (id, type, uzs, usd, created_at, due_date) eskisidan. -> {nasiya id: to'liq yopilgan sana yoki None}"""
    paid, still_open = {}, set()
    for col in (2, 3):  # so'm, dollar
        queue = deque()
        for row in rows:
            amount = row[col]
            if row[1] == 'debt' and amount > 0:
                queue.append([row[0], amount])
            elif row[1] == 'payment' and amount < 0:
                pool = -amount
                while pool > 0 and queue:
                    take = min(pool, queue[0][1])
                    queue[0][1] -= take
                    pool -= take
                    if queue[0][1] <= 0:
                        debt_id = queue.popleft()[0]
                        day = timezone.localtime(row[4]).date()
                        paid[debt_id] = max(paid.get(debt_id, day), day)
        still_open.update(debt_id for debt_id, _ in queue)  # bu valyutada hali yopilmagan
    for debt_id in still_open:
        paid[debt_id] = None
    return paid


def _evaluate(rows, due_status, client):
    trust = Trust(flagged=client.risk_flag, note=client.risk_note)
    paid = _paid_dates(rows)
    delays = []
    for debt_id, kind, _uzs, _usd, _created, due in rows:
        if kind != 'debt' or not due or debt_id not in paid or paid[debt_id] is None:
            continue
        delay = (paid[debt_id] - due).days
        if delay > 0:
            delays.append(delay)
        else:
            trust.on_time += 1
    trust.late = len(delays)
    trust.avg_delay = round(sum(delays) / len(delays)) if delays else 0
    trust.overdue_days = due_status.overdue_days if due_status and due_status.is_overdue else 0

    if trust.flagged or trust.overdue_days > RISK_OVERDUE_DAYS or trust.late >= RISK_LATE_COUNT:
        trust.level = 'risk'
    elif trust.overdue_days or trust.late:
        trust.level = 'warn'
    elif trust.on_time >= GOOD_ON_TIME:
        trust.level = 'good'
    return trust


def _rows(queryset):
    return (queryset.filter(status='confirmed', is_cash_sale=False).order_by('created_at', 'id')
            .values_list('client_id', 'id', 'transaction_type', 'amount_uzs', 'amount_usd', 'created_at', 'due_date'))


def client_trust(client):
    rows = [row for _, *row in _rows(Debt.objects.filter(client=client))]
    return _evaluate(rows, dues.client_due_status(client), client)


def shop_trust_map(shop):
    """{client_id: Trust} - butun do'kon uchun (ro'yxatlar va mijoz tanlash uchun)."""
    grouped = defaultdict(list)
    for client_id, *row in _rows(Debt.objects.filter(shop=shop)):
        grouped[client_id].append(row)
    due_map = dues.shop_due_map(shop)
    result = {}
    for client in Client.objects.filter(shop=shop).only('id', 'risk_flag', 'risk_note'):
        result[client.id] = _evaluate(grouped.get(client.id, []), due_map.get(client.id), client)
    return result


def trust_or_none(shop, client=None):
    """Tarifda bo'lmasa None (Bepul tarifda ishonch belgisi yo'q)."""
    from . import plans
    if not plans.has_feature(shop, plans.TRUST):
        return None
    return client_trust(client) if client else shop_trust_map(shop)
