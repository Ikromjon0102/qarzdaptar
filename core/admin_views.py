from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Client, Debt, Shop

superuser_required = user_passes_test(lambda u: u.is_superuser, login_url='/admin/login/')


@superuser_required
def super_dashboard(request):
    """Platforma egasi uchun: barcha do'konlar, obuna holati va umumiy ko'rsatkichlar."""
    now = timezone.now()
    shops = Shop.objects.select_related('owner').annotate(
        client_count=Count('clients', distinct=True),
        # To'lovlar bazada manfiy saqlanadi; Debt.shop orqali hisoblaymiz (mijozlar bilan join qilinmaydi)
        debt_uzs=Sum('debts__amount_uzs', filter=Q(debts__status='confirmed', debts__transaction_type='debt',
                                                   debts__is_cash_sale=False)),
        paid_uzs=Sum('debts__amount_uzs', filter=Q(debts__status='confirmed', debts__transaction_type='payment',
                                                   debts__is_cash_sale=False)),
    ).order_by('subscription_ends_at')

    rows = []
    for shop in shops:
        ends = shop.subscription_ends_at
        status = 'unlimited' if not ends else ('expired' if ends < now else ('soon' if shop.days_left <= 3 else 'active'))
        rows.append({'shop': shop, 'status': status,
                     'outstanding': (shop.debt_uzs or 0) + (shop.paid_uzs or 0)})

    turnover = Debt.objects.filter(transaction_type='debt', status='confirmed', is_cash_sale=False) \
        .aggregate(s=Sum('amount_uzs'))['s'] or 0

    return render(request, 'super_dashboard.html', {
        'rows': rows,
        'total_shops': len(rows),
        'active_shops': sum(r['status'] in ('active', 'soon', 'unlimited') for r in rows),
        'expired_shops': sum(r['status'] == 'expired' for r in rows),
        'total_clients': Client.objects.count(),
        'global_turnover': turnover,
        'new_this_month': Shop.objects.filter(created_at__gte=now.replace(day=1, hour=0, minute=0, second=0)).count(),
    })


@superuser_required
@require_POST
def extend_subscription(request, shop_id):
    """To'lov qabul qilingach obunani 30 kunga uzaytirish (muddat tugagan bo'lsa - bugundan)."""
    shop = get_object_or_404(Shop, id=shop_id)
    now = timezone.now()
    start = shop.subscription_ends_at if shop.subscription_ends_at and shop.subscription_ends_at > now else now
    shop.subscription_ends_at = start + timedelta(days=30)
    shop.is_active = True
    shop.save(update_fields=['subscription_ends_at', 'is_active'])
    messages.success(request, f"✅ «{shop.name}» obunasi {shop.subscription_ends_at:%d.%m.%Y} gacha uzaytirildi.")
    return redirect('super_dashboard')
