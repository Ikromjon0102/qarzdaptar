import html
import re
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.urls import reverse
from .models import Client, UserProfile
from .reminders import balance_line
from . import telegram
from .views import get_current_shop
from .permissions import plan_feature_required, shop_admin_required
from . import plans
from django.db import transaction
from django.db.models import Q, Sum
from .models import AllowedAdmin, StaffInvite



def personalize(text, client, bal_uzs, bal_usd):
    """{ism} va {qarz} o'rniga mijozning ismi va qarzini qo'yadi. Matn HTML sifatida xavfsizlanadi."""
    debt = balance_line(bal_uzs, bal_usd) or "0 so'm"
    return (html.escape(text)
            .replace('{ism}', html.escape(client.full_name))
            .replace('{qarz}', debt))


@shop_admin_required
@plan_feature_required(plans.BROADCAST)
def broadcast_view(request):
    shop = get_current_shop(request)
    # Botga ulangan mijozlar, qarzi bilan (katta qarz tepada)
    linked = list(
        Client.objects.filter(shop=shop, telegram_id__isnull=False).exclude(telegram_id=0)
        .annotate(bal_uzs=Sum('debt__amount_uzs', filter=Q(debt__status='confirmed')),
                  bal_usd=Sum('debt__amount_usd', filter=Q(debt__status='confirmed')))
        .order_by('-bal_uzs', 'full_name')
    )
    for c in linked:
        c.bal_uzs, c.bal_usd = c.bal_uzs or 0, c.bal_usd or 0
        c.is_debtor = c.bal_uzs > 0 or c.bal_usd > 0

    if request.method == 'POST':
        text = (request.POST.get('message') or '').strip()
        mode = request.POST.get('mode')
        if mode == 'debtors':
            recipients = [c for c in linked if c.is_debtor]
        elif mode == 'selected':
            chosen = set(request.POST.getlist('client_ids'))
            recipients = [c for c in linked if str(c.id) in chosen]  # faqat o'z do'koni mijozlari
        else:
            recipients = linked

        if not text:
            messages.error(request, "Xabar matnini yozing.")
        elif not recipients:
            messages.error(request, "Hech kim tanlanmagan.")
        else:
            sent_to = set()
            for c in recipients:
                if c.telegram_id in sent_to:  # bitta odam bir necha yozuvda bo'lsa
                    continue
                sent_to.add(c.telegram_id)
                telegram.send_message(c.telegram_id, personalize(text, c, c.bal_uzs, c.bal_usd))
            messages.success(request, f"📨 Xabar {len(sent_to)} ta mijozga yuborilmoqda.")
            return redirect('main_menu')

    return render(request, 'broadcast.html', {
        'back_url': 'main_menu',
        'shop': shop,
        'clients': linked,
        'debtor_count': sum(c.is_debtor for c in linked),
        'initial_mode': request.GET.get('to') if request.GET.get('to') in ('debtors', 'selected') else 'all',
        'preselected': request.GET.getlist('id'),
    })


@shop_admin_required
def manage_admins_view(request, action=None, admin_id=None):
    shop = get_current_shop(request)
    # Taklif havolasi yaratish (asosiy usul - Telegram ID so'ralmaydi)
    if action in ('invite', 'add') and request.method == 'POST' and not plans.can_add_staff(shop):
        limit = plans.current_plan(shop).max_staff
        messages.error(request, f"🔒 {plans.current_plan(shop).name} tarifida "
                                + (f"{limit} tagacha xodim." if limit else "xodim qo'shib bo'lmaydi.")
                                + " Ko'proq xodim uchun tarifni oshiring.")
        return redirect(f"{reverse('pricing_page')}?need=staff")

    if action == 'invite' and request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, "❌ Xodim ismini kiriting.")
        else:
            StaffInvite.objects.create(shop=shop, name=name[:100])
            messages.success(request, f"✅ {name} uchun taklif havolasi tayyor. Uni xodimga yuboring.")

    # Taklifni bekor qilish
    elif action == 'cancel_invite' and admin_id and request.method == 'POST':
        StaffInvite.objects.filter(id=admin_id, shop=shop, used_at__isnull=True).delete()
        messages.info(request, "Taklif bekor qilindi.")

    # Xodimni Telegram ID bilan qo'shish (zaxira usul)
    elif action == 'add' and request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        tg_id = (request.POST.get('telegram_id') or '').strip()
        if not name or not re.fullmatch(r'\d{5,15}', tg_id):
            messages.error(request, "❌ Ism va to'g'ri Telegram ID (faqat raqam) kiriting.")
        elif User.objects.filter(username=tg_id).exists():
            messages.error(request, "❌ Bu Telegram ID allaqachon ro'yxatda bor!")
        else:
            with transaction.atomic():
                user = User.objects.create_user(username=tg_id, password=None)
                AllowedAdmin.objects.create(shop=shop, name=name, telegram_id=tg_id)
                UserProfile.objects.create(user=user, shop=shop, role='worker')
            messages.success(request, f"✅ {name} xodimlarga qo'shildi.")

    # Xodimni o'chirish (faqat o'z do'konidan, o'zini emas)
    elif action == 'delete' and admin_id and request.method == 'POST':
        admin = AllowedAdmin.objects.filter(id=admin_id, shop=shop).first()
        if not admin:
            messages.error(request, "❌ Xodim topilmadi.")
        elif str(admin.telegram_id) == request.user.username or shop.owner.username == str(admin.telegram_id):
            messages.error(request, "❌ Do'kon egasini o'chirib bo'lmaydi.")
        else:
            User.objects.filter(username=str(admin.telegram_id), profile__shop=shop).delete()
            admin.delete()
            messages.warning(request, f"🗑 {admin.name} xodimlardan o'chirildi.")

    return redirect('admin_control')


@shop_admin_required
def admin_control(request):
    shop = get_current_shop(request)
    allowed_admins = AllowedAdmin.objects.filter(shop=shop).order_by('-created_at')
    invites = [inv for inv in StaffInvite.objects.filter(shop=shop, used_at__isnull=True).order_by('-created_at')
               if inv.is_valid]
    return render(request, 'admin_control.html', {
        'back_url': 'main_menu',
        'allowed_admins': allowed_admins,
        'invites': invites,
        'owner_tg_id': shop.owner.username if shop else '',
        'plan': plans.current_plan(shop),
        'staff_count': plans.staff_count(shop),
        'staff_limit': plans.current_plan(shop).max_staff,
    })
