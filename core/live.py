from django.db.models import Count, Max, Q

from .models import Client, Debt


def shop_version(shop):
    """
    Do'kon ma'lumotlarining qisqa "izi". Nasiya qo'shilsa, o'chirilsa, tasdiqlansa yoki rad etilsa,
    mijoz qo'shilsa yoki botga ulansa - qiymat o'zgaradi. Sahifalar shu orqali o'zini yangilaydi.
    """
    if shop is None:
        return ''
    d = Debt.objects.filter(shop=shop).aggregate(
        n=Count('id'), last=Max('id'),
        pending=Count('id', filter=Q(status='pending')),
        confirmed=Count('id', filter=Q(status='confirmed')),
    )
    c = Client.objects.filter(shop=shop).aggregate(
        n=Count('id'), last=Max('id'), tg=Count('id', filter=Q(telegram_id__isnull=False)),
    )
    return '-'.join(str(x or 0) for x in (d['n'], d['last'], d['pending'], d['confirmed'],
                                          c['n'], c['last'], c['tg']))
