import re
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from .models import Client, UserProfile, Shop, Settings
from . import telegram
from .views import get_current_shop
from .permissions import shop_admin_required
from django.db import transaction
from .models import AllowedAdmin, StaffInvite

# Yangi do'kon uchun bepul sinov muddati (kun)
TRIAL_DAYS = 14


@shop_admin_required
def broadcast_view(request):
    shop = get_current_shop(request)
    if request.method == 'POST':
        text = request.POST.get('message')
        if text:
            # Faqat shu do'kon mijozlariga. ID lar oldindan olinadi - fon oqimi bazaga murojaat qilmaydi,
            # xabarlar esa telegram modulining navbati orqali (bir vaqtda 4 tadan) yuboriladi.
            chat_ids = list(Client.objects.filter(shop=shop, telegram_id__isnull=False)
                            .exclude(telegram_id=0).values_list('telegram_id', flat=True).distinct())
            for chat_id in chat_ids:
                telegram.send_message(chat_id, text)
            messages.success(request, f"📨 Xabar {len(chat_ids)} ta mijozga yuborilmoqda.")
            return redirect('main_menu')

    recipients = (Client.objects.filter(shop=shop, telegram_id__isnull=False).exclude(telegram_id=0)
                  .values('telegram_id').distinct().count())
    return render(request, 'broadcast.html', {'back_url': 'main_menu', 'recipients': recipients, 'shop': shop})


@shop_admin_required
def manage_admins_view(request, action=None, admin_id=None):
    shop = get_current_shop(request)
    # Taklif havolasi yaratish (asosiy usul - Telegram ID so'ralmaydi)
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
    })


def signup_view(request):
    if request.method == 'POST':
        shop_name = request.POST.get('shop_name')
        admin_name = request.POST.get('admin_name')
        telegram_id = (request.POST.get('telegram_id') or '').strip()
        signup_url = reverse('landing_page') + '#start-now'

        # Validatsiya
        if not re.fullmatch(r'\d{5,15}', telegram_id):
            messages.error(request, "Telegram ID faqat raqamlardan iborat bo'lishi kerak. «ID olish» tugmasini bosing.")
            return redirect(signup_url)
        if re.fullmatch(r'998\d{9}', telegram_id):
            messages.error(request, "Bu telefon raqamga o'xshaydi. Telefon emas, Telegram ID kerak — "
                                    "«ID olish» tugmasini bosing, bot sizga ID'ni yuboradi.")
            return redirect(signup_url)
        if User.objects.filter(username=telegram_id).exists():
            messages.error(request, "Bu Telegram ID bilan allaqachon do'kon ochilgan! Botga kirib, «Do'konni ochish» tugmasini bosing.")
            return redirect(signup_url)

        try:
            with transaction.atomic():  # Agar bittasi o'xshamasa, hammasini bekor qiladi
                # 1. User yaratamiz
                user = User.objects.create_user(username=telegram_id, password=None)  # Kirish faqat Telegram orqali

                # 2. Do'kon yaratamiz
                shop = Shop.objects.create(
                    name=shop_name,
                    owner=user,
                    is_trial_used=True,
                    subscription_ends_at=timezone.now() + timedelta(days=TRIAL_DAYS),
                )

                # 3. Profil va Adminlik
                UserProfile.objects.create(user=user, shop=shop, role='admin')
                AllowedAdmin.objects.create(shop=shop, name=admin_name, telegram_id=telegram_id)

                # 4. Sozlamalar
                Settings.objects.create(shop=shop, usd_rate=12800)

            # Muvaffaqiyatli!
            return render(request, 'signup_success.html', {
                'shop_name': shop_name,
                'bot_username': settings.BOT_USERNAME,
                'trial_days': TRIAL_DAYS,
            })

        except Exception as e:
            messages.error(request, f"Xatolik yuz berdi: {e}")
            return redirect(signup_url)

    return redirect('landing_page')


