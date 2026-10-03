import hmac
import html
import json
import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from store.models import Order
from . import bot_signup, dues, exports, landing, plans, telegram
from .models import (CASH_CLIENT_PHONE, AllowedAdmin, Client, Debt, Settings, Shop, StaffInvite,
                     UserProfile)
from .permissions import client_limit_message, is_shop_admin, plan_feature_required, shop_admin_required
from .live import shop_version
from .reminders import send_reminder
from .telegram_auth import verify_init_data
from .utils import clean_phone_number, parse_amount, shop_staff_ids

logger = logging.getLogger(__name__)


def get_current_shop(request):
    """
    Tizimga kirgan adminning do'konini qaytaradi.
    """
    if not request.user.is_authenticated:
        return None
    try:
        # UserProfile orqali bog'langan do'konni olamiz
        return request.user.profile.shop
    except Exception:
        # Agar superuser bo'lsa va profili bo'lmasa (Admin panel uchun)
        if request.user.is_superuser:
            # Vaqtincha birinchi do'konni qaytarib turamiz yoki None
            return Shop.objects.first()
        return None


def login_page_view(request):
    # --- 1. SOTUVCHI YOKI ADMINMI? (Django User) ---
    if request.user.is_authenticated:
        # Agar bu admin yoki sotuvchi bo'lsa, asosiy menyuga o'tsin
        is_owner = Shop.objects.filter(owner=request.user).exists()
        is_worker = UserProfile.objects.filter(user=request.user).exists()

        if is_owner or is_worker or request.user.is_superuser:
            return redirect('main_menu')

    # --- 2. MIJOZMI? (Session check) [YANGI QO'SHILGAN QISM] ---
    # telegram_auth_view da biz 'client_id' ni sessiyaga yozgandik.
    # Agar sessiyada client_id bo'lsa, demak bu mijoz!
    elif 'client_id' in request.session:
        # Mijozni o'zining kabinetiga yo'naltiramiz
        return redirect('client_cabinet')  # Urls.py dagi name='client_cabinet' bo'lishi kerak

    # --- 3. HECH KIM EMASMI? ---
    # Demak bu yangi mehmon -> Landing page (reklama)
    return landing.landing(request)


def telegram_auth_view(request):
    """
    Telegram Mini App orqali kirish.
    Foydalanuvchi ID si imzolangan initData'dan olinadi - brauzer yuborgan oddiy
    "telegram_id" ga ishonilmaydi (aks holda istalgan odam boshqa birovning nomidan kira olardi).
    """
    if request.method == 'GET':
        return render(request, 'login_loader.html')

    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except ValueError:
        data = {}
    tg_user = verify_init_data(data.get('init_data', ''))
    if not tg_user:
        return JsonResponse({
            'status': 'error',
            'msg': "Telegram orqali tasdiqlab bo'lmadi. Ilovani botdagi tugma orqali qayta oching.",
        }, status=403)
    telegram_id = int(tg_user['id'])

    # 1. Do'kon egasi yoki xodimi (User.username = telegram_id)
    user = User.objects.filter(username=str(telegram_id), is_active=True).first()
    if user:
        login(request, user)
        request.session.pop('client_id', None)
        return JsonResponse({'status': 'ok', 'redirect_url': reverse('main_menu')})

    # 2. Mijoz (bir nechta do'konda bo'lishi mumkin - oxirgi tanlangani saqlanadi)
    clients = list(Client.objects.filter(telegram_id=telegram_id).order_by('id'))
    if clients:
        previous = request.session.get('client_id')
        if request.user.is_authenticated:
            logout(request)
        client = next((c for c in clients if c.id == previous), clients[0])
        request.session['client_id'] = client.id
        return JsonResponse({'status': 'ok', 'redirect_url': reverse('client_cabinet')})

    # 3. Ro'yxatdan o'tmagan
    return JsonResponse({'status': 'ok', 'redirect_url': reverse('landing_page')})


@login_required(login_url='/login/')
def main_menu_view(request):
    # Faqat o'z do'koniga tegishli narsalar
    shop = get_current_shop(request)
    if not shop:
        return HttpResponse("Sizga do'kon biriktirilmagan!")

    # Bosh ekran: umumiy holat, bugungi natija va so'nggi amallar
    recent = (
        Debt.objects.filter(shop=shop)
        .exclude(is_cash_sale=True, transaction_type='payment')  # naqd savdoning to'lov juftini ko'rsatmaymiz
        .select_related('client')
        .order_by('-created_at')[:8]
    )
    return render(request, 'main_menu.html', {
        'shop': shop,
        'active_tab': 'home',
        'stats': shop_stats(shop),
        'today': shop_stats(shop, created_at__date=timezone.localdate()),
        'pending_count': Debt.objects.filter(shop=shop, status='pending').count(),
        'client_count': plans.client_count(shop),
        'overdue': dues.overdue_summary(shop),
        # Mijoz rad etgan nasiyalar (oxirgi 14 kun): sababi bilan, qayta yuborish uchun
        'rejected': Debt.objects.filter(
            shop=shop, status='rejected',
            created_at__gte=timezone.now() - timedelta(days=14),
        ).select_related('client').order_by('-created_at')[:5],
        'recent': recent,
    })


def logout_view(request):
    """Tizimdan chiqish (xodim ham, mijoz ham). Faqat POST - tasodifiy havola bilan chiqib ketmaslik uchun."""
    if request.method == 'POST':
        logout(request)  # sessiya to'liq tozalanadi (client_id ham)
        messages.info(request, "Tizimdan chiqdingiz.")
        return redirect('landing_page')
    return redirect('main_menu')


PAYMENT_METHODS = {'cash': 'Naqd', 'card': 'Karta', 'click': 'Click', 'transfer': "O'tkazma"}


def picker_clients(shop):
    """Mijoz tanlash komponenti uchun ro'yxat (joriy balans bilan, Kassa mijozisiz)."""
    clients = (
        Client.objects.filter(shop=shop)
        .exclude(phone=CASH_CLIENT_PHONE)
        .annotate(
            bal_uzs=Sum('debt__amount_uzs', filter=Q(debt__status='confirmed')),
            bal_usd=Sum('debt__amount_usd', filter=Q(debt__status='confirmed')),
        )
        .order_by('full_name')
    )
    return [{
        'id': c.id,
        'name': c.full_name,
        'phone': c.phone,
        'tg': bool(c.telegram_id),
        'bal_uzs': float(c.bal_uzs or 0),
        'bal_usd': float(c.bal_usd or 0),
    } for c in clients]


def format_number(value):
    """1500000 -> '1 500 000', 2.5 -> '2.5'"""
    if float(value).is_integer():
        return f"{value:,.0f}".replace(',', ' ')
    return f"{value:,.2f}".replace(',', ' ').rstrip('0').rstrip('.')


@login_required(login_url='/login/')
def create_debt_view(request):
    shop = get_current_shop(request)
    if not shop: return redirect('login_page')

    settings_obj, _ = Settings.objects.get_or_create(shop=shop)
    context = {
        'back_url': 'main_menu',
        'picker_clients': picker_clients(shop),
        'selected_client_id': request.GET.get('client_id', ''),
        'usd_rate': float(settings_obj.usd_rate or 0),
        'payment_methods': PAYMENT_METHODS,
        'sale_mode': 'debt',
        'payment_type': 'cash',
        'prefill_items': [],
        'today_iso': timezone.localdate().isoformat(),
        'due_max_iso': (timezone.localdate() + timedelta(days=dues.MAX_DUE_DAYS)).isoformat(),
    }

    if request.method == 'POST':
        # 1. PARAMETRLARNI OLISH
        sale_mode = 'cash' if request.POST.get('sale_mode') == 'cash' else 'debt'
        payment_type = request.POST.get('payment_type')
        if payment_type not in PAYMENT_METHODS:
            payment_type = 'cash'
        client_id = request.POST.get('client')

        # 2. MAHSULOTLARNI YIG'ISH
        product_names = request.POST.getlist('product_name[]')
        quantities = request.POST.getlist('quantity[]')
        prices = request.POST.getlist('price[]')
        currencies = request.POST.getlist('currency[]')

        total_uzs = 0
        total_usd = 0
        items_list = []
        prefill_items = []

        for i, (name, qty_raw, price_raw, currency) in enumerate(
                zip(product_names, quantities, prices, currencies), start=1):
            name = name.strip()
            currency = 'usd' if currency == 'usd' else 'uzs'
            prefill_items.append({'name': name, 'qty': qty_raw, 'price': price_raw, 'currency': currency})
            qty = parse_amount(qty_raw)
            price = parse_amount(price_raw)

            if qty > 0 and price > 0:
                name = name or f"Tovar #{i}"
                summ = qty * price
                # Formatlash (HTML uchun emas, baza matni uchun)
                if currency == 'uzs':
                    total_uzs += summ
                    items_list.append(f"{name}: {format_number(qty)} x {format_number(price)} = {format_number(summ)} so'm")
                else:
                    total_usd += summ
                    items_list.append(f"{name}: {format_number(qty)} x ${price:.2f} = ${summ:.2f}")

        items_str = "\n".join(items_list)

        client = None
        if client_id:
            client = Client.objects.filter(id=client_id, shop=shop).first()

        # 3. TEKSHIRUV: xato bo'lsa formani kiritilgan ma'lumotlar bilan qaytaramiz
        raw_due = request.POST.get('due_date', '').strip() if sale_mode == 'debt' else ''
        due_date = dues.parse_due_date(raw_due) if raw_due else None

        error = None
        if not items_list:
            error = "Kamida bitta tovarning soni va narxini kiriting."
        elif sale_mode == 'debt' and not client:
            error = "Nasiya uchun ro'yxatdan mijozni tanlang."
        elif raw_due and not due_date:
            error = "To'lov muddati noto'g'ri: bugundan oldin yoki 2 yildan uzoq bo'lmasin."

        if error:
            messages.error(request, error)
            context.update({
                'sale_mode': sale_mode,
                'payment_type': payment_type,
                'selected_client_id': client.id if client else '',
                'prefill_items': prefill_items,
                'no_tg_action': request.POST.get('no_tg_action', 'confirm'),
                'due_date': raw_due,
            })
            return render(request, 'create_debt.html', context)

        # 4. HOLATNI ANIQLASH
        current_status = 'confirmed' if sale_mode == 'cash' else 'pending'

        if sale_mode == 'debt':
            # Botga ulanmagan mijozga tasdiqlash so'rovi yuborib bo'lmaydi.
            # Sotuvchi tanlovi: darhol balansga yozish yoki kutib turish.
            if not client.telegram_id and request.POST.get('no_tg_action') == 'confirm':
                current_status = 'confirmed'
        elif not client:
            # Naqd savdo, mijoz ko'rsatilmagan
            client, _ = Client.objects.get_or_create(
                shop=shop,
                phone=CASH_CLIENT_PHONE,
                defaults={'full_name': 'Naqd Savdo (Kassa)'}
            )

        # 5. BAZAGA YOZISH (SAVDO)
        debt = Debt.objects.create(
            shop=shop,
            transaction_type='debt',
            client=client,
            amount_uzs=total_uzs,
            amount_usd=total_usd,
            items=items_str,
            status=current_status,
            is_cash_sale=(sale_mode == 'cash'),
            due_date=due_date,
        )

        # Naqd savdoda to'lov ham darhol yoziladi (manfiy)
        if sale_mode == 'cash':
            Debt.objects.create(
                shop=shop,
                transaction_type='payment',
                payment_method=payment_type,
                client=client,
                amount_uzs=-total_uzs,
                amount_usd=-total_usd,
                items=f"To'lov: {items_str} (ID: {debt.id})",
                status='confirmed',
                is_cash_sale=True,
            )
            messages.success(request, f"✅ Naqd savdo saqlandi ({PAYMENT_METHODS[payment_type]}).")
            return redirect('create_debt')

        if client.telegram_id:
            messages.success(request, f"✅ Nasiya saqlandi. {client.full_name}ga tasdiqlash so'rovi yuborildi.")
        elif current_status == 'confirmed':
            messages.success(request, f"✅ Nasiya {client.full_name} balansiga yozildi (mijoz botga ulanmagan).")
        else:
            messages.warning(request, f"⏳ Nasiya saqlandi, lekin {client.full_name} botga ulanmagan — "
                                      "tasdiqlash so'rovi yuborilmadi va balansga qo'shilmadi. "
                                      "Pastda «Tasdiqlash» tugmasini bosing yoki mijozga havola yuboring.")
        return redirect('admin_client_detail', client_id=client.id)

    return render(request, 'create_debt.html', context)


def balance_text(bal_uzs, bal_usd):
    """Mijoz balansini matn ko'rinishida: '100 000 so'm (Qarz), $5.00 (Haq)'"""
    parts = []
    if bal_uzs > 0:
        parts.append(f"{bal_uzs:,.0f} so'm (Qarz)".replace(',', ' '))
    elif bal_uzs < 0:
        parts.append(f"{abs(bal_uzs):,.0f} so'm (Haq)".replace(',', ' '))
    if bal_usd > 0:
        parts.append(f"${bal_usd:,.2f} (Qarz)")
    elif bal_usd < 0:
        parts.append(f"${abs(bal_usd):,.2f} (Haq)")
    return ", ".join(parts) if parts else "Hisob toza ✅"


@login_required(login_url='/login/')
def create_payment_view(request):
    shop = get_current_shop(request)
    if not shop: return redirect('login_page')

    context = {
        'back_url': 'main_menu',
        'picker_clients': picker_clients(shop),
        'selected_client_id': request.GET.get('client_id', ''),
        'payment_methods': PAYMENT_METHODS,
        'payment_method': 'cash',
    }

    if request.method == 'POST':
        client_id = request.POST.get('client_id')
        payment_method = request.POST.get('payment_method')
        if payment_method not in PAYMENT_METHODS:
            payment_method = 'cash'
        note = (request.POST.get('note') or '').strip()
        amount_uzs = parse_amount(request.POST.get('amount_uzs'))
        amount_usd = parse_amount(request.POST.get('amount_usd'))

        client = Client.objects.filter(id=client_id, shop=shop).first() if client_id else None

        error = None
        if not client:
            error = "Ro'yxatdan mijozni tanlang."
        elif amount_uzs <= 0 and amount_usd <= 0:
            error = "To'lov summasini kiriting."

        if error:
            messages.error(request, error)
            context.update({
                'selected_client_id': client.id if client else '',
                'payment_method': payment_method,
                'amount_uzs': request.POST.get('amount_uzs', ''),
                'amount_usd': request.POST.get('amount_usd', ''),
                'note': note,
            })
            return render(request, 'create_payment.html', context)

        method_display = PAYMENT_METHODS[payment_method]

        # Tavsifni chiroyli qilish
        parts = []
        if amount_uzs > 0: parts.append(f"{amount_uzs:,.0f} so'm".replace(',', ' '))
        if amount_usd > 0: parts.append(f"${amount_usd:,.2f}")
        amount_str = " + ".join(parts)  # Masalan: "1 000 so'm + $10.00"

        description = f"💵 To'lov: {amount_str} ({method_display})"
        if note: description += f" | {note}"

        # 1. BAZAGA YOZISH (To'lov minus bo'lib tushadi)
        Debt.objects.create(
            shop=shop,
            client=client,
            amount_uzs=-amount_uzs,
            amount_usd=-amount_usd,
            items=description,
            status='confirmed',
            transaction_type='payment',
            payment_method=payment_method
        )

        balance_data = Debt.objects.filter(shop=shop, client=client, status='confirmed').aggregate(
            sum_uzs=Sum('amount_uzs'),
            sum_usd=Sum('amount_usd')
        )
        balance_str = balance_text(balance_data['sum_uzs'] or 0, balance_data['sum_usd'] or 0)

        # 2. TELEGRAM XABAR
        if client.telegram_id:
            try:
                msg = "💸 <b>To'lov qabul qilindi!</b>\n\n"
                msg += f"👤 Mijoz: {client.full_name}\n"
                msg += f"💰 To'landi: <b>{amount_str}</b> ({method_display})\n"
                if note: msg += f"📝 Izoh: {note}\n"
                msg += "➖➖➖➖➖➖➖➖\n"
                msg += f"📉 Joriy holat: <b>{balance_str}</b>"
                send_tg_msg(client.telegram_id, msg)
            except Exception:
                logger.exception("To'lov xabarini yuborishda xato (client=%s)", client.id)

        messages.success(request, f"✅ {client.full_name}dan {amount_str} qabul qilindi. Qoldiq: {balance_str}")
        return redirect('admin_client_detail', client_id=client.id)

    return render(request, 'create_payment.html', context)

@login_required(login_url='/login/')
def manage_debt_view(request, debt_uuid, action):
    shop = get_current_shop(request)
    debt = get_object_or_404(Debt, uuid=debt_uuid, shop=shop)

    if action in ('delete', 'force_confirm') and not is_shop_admin(request.user):
        messages.error(request, "⛔ Yozuvni o'chirish va majburiy tasdiqlash faqat rahbar uchun.")
        return redirect('admin_client_detail', client_id=debt.client.id)

    # 1. QAYTA YUBORISH: xabar bormagan bo'lsa yoki mijoz rad etgan bo'lsa (izoh bilan)
    if action == 'resend':
        if debt.status == 'confirmed':
            messages.info(request, "Bu nasiya allaqachon tasdiqlangan.")
        elif not debt.client.telegram_id:
            messages.error(request, "Mijozning Telegrami ulanmagan!")
        else:
            note = (request.POST.get('note') or '').strip()[:200]
            was_rejected = debt.status == 'rejected'
            debt.status = 'pending'
            if note or was_rejected:
                debt.shop_note = note
            debt.save()
            from .bot_utils import send_confirmation_request
            send_confirmation_request(debt.client.telegram_id, debt, settings.SITE_DOMAIN)
            messages.success(request, "Nasiya mijozga qayta yuborildi!" if was_rejected
                             else "Tasdiqlash so'rovi qayta yuborildi!")

    # 1b. TO'LOV MUDDATINI O'ZGARTIRISH (bo'sh - muddatni olib tashlash)
    elif action == 'due' and request.method == 'POST' and debt.transaction_type == 'debt':
        raw = (request.POST.get('due_date') or '').strip()
        new_due = dues.parse_due_date(raw) if raw else None
        if raw and not new_due:
            messages.error(request, "Sana noto'g'ri: bugundan oldin yoki 2 yildan uzoq bo'lmasin.")
        else:
            debt.due_date = new_due
            debt.due_stage = 0  # yangi muddat uchun eslatmalar qaytadan
            debt.save(update_fields=['due_date', 'due_stage'])
            messages.success(request, f"📅 To'lov muddati: {new_due:%d.%m.%Y}" if new_due else "To'lov muddati olib tashlandi.")
            if new_due and debt.client.telegram_id and debt.status == 'confirmed':
                send_tg_msg(debt.client.telegram_id,
                            f"📅 {html.escape(debt.shop.name)}: to'lov muddati {new_due:%d.%m.%Y} ga o'zgartirildi.\n"
                            f"💰 {amount_text(debt.amount_uzs, debt.amount_usd)} · {debt.created_at:%d.%m.%Y} dagi nasiya")

    # 2. MAJBURIY TASDIQLASH (Admin Override)
    elif action == 'force_confirm':
        debt.status = 'confirmed'
        debt.save()
        messages.success(request, "Qarz majburiy tasdiqlandi (Admin)!")

    # 3. O'CHIRIB TASHLASH (Bekor qilish)
    elif action == 'delete':
        debt.delete()
        messages.warning(request, "Qarz o'chirib tashlandi.")

    # Ish bitgach, yana mijoz profiliga qaytamiz
    return redirect('admin_client_detail', client_id=debt.client.id)

def amount_text(amount_uzs, amount_usd):
    """"150 000 so'm + $20.00" (ishorasiz)"""
    parts = []
    if amount_uzs:
        parts.append(f"{abs(amount_uzs):,.0f} so'm".replace(',', ' '))
    if amount_usd:
        parts.append(f"${abs(amount_usd):,.2f}")
    return " + ".join(parts) or "0 so'm"


def client_balance(client):
    agg = Debt.objects.filter(client=client, status='confirmed').aggregate(
        uzs=Sum('amount_uzs'), usd=Sum('amount_usd'))
    return agg['uzs'] or 0, agg['usd'] or 0


def notify_shop_staff(shop, text, exclude=None):
    """Do'kon jamoasiga Telegram xabar yuborish."""
    for chat_id in shop_staff_ids(shop) - {exclude}:
        send_tg_msg(chat_id, text)


def debt_detail_view(request, debt_uuid):
    """Mijoz nasiyani ko'radi va tasdiqlaydi yoki rad etadi (bot tugmasi orqali ochiladi)."""
    debt = get_object_or_404(Debt.objects.select_related('client', 'shop'), uuid=debt_uuid)
    client = debt.client
    cabinet_url = reverse('telegram_auth')  # Telegram orqali kirib, kabinetga o'tadi

    if debt.status != 'pending':
        done = 'tasdiqlangan' if debt.status == 'confirmed' else 'rad etilgan'
        return render(request, 'status_page.html', {
            'title': f"Bu nasiya allaqachon {done}",
            'message': f"{amount_text(debt.amount_uzs, debt.amount_usd)} · {debt.created_at:%d.%m.%Y}",
            'icon': 'fa-circle-info',
            'color': 'text-primary',
            'cabinet_url': cabinet_url,
        })

    if request.method == 'POST':
        # Faqat shu nasiyaning mijozi hal qila oladi: Telegram imzosi (initData)
        # yoki shu mijozning sessiyasi orqali. Havola boshqa odamga o'tib qolsa ham ishlamaydi.
        tg_user = verify_init_data(request.POST.get('init_data', ''))
        is_owner = (
            (tg_user and client.telegram_id and int(tg_user['id']) == client.telegram_id)
            or request.session.get('client_id') == client.id
        )
        if not is_owner:
            return render(request, 'status_page.html', {
                'title': "Tasdiqlab bo'lmadi",
                'message': "Nasiyani faqat mijozning o'zi, Telegram'dagi bot tugmasi orqali tasdiqlay oladi.",
                'icon': 'fa-lock',
                'color': 'text-danger',
            }, status=403)
        if tg_user and not request.user.is_authenticated:
            request.session['client_id'] = client.id  # "Hisobimni ko'rish" darhol ochilsin

        action = request.POST.get('action')
        amount = amount_text(debt.amount_uzs, debt.amount_usd)

        if action == 'confirm':
            debt.status = 'confirmed'
            debt.save()
            bal_uzs, bal_usd = client_balance(client)
            notify_shop_staff(debt.shop, f"✅ <b>{client.full_name}</b> nasiyani tasdiqladi\n"
                                         f"💰 {amount}\n📉 Joriy qarzi: {balance_text(bal_uzs, bal_usd)}")
            return render(request, 'status_page.html', {
                'title': 'Tasdiqlandi',
                'message': f"{amount} hisobingizga yozildi.\nJoriy holat: {balance_text(bal_uzs, bal_usd)}",
                'icon': 'fa-circle-check',
                'color': 'text-success',
                'cabinet_url': cabinet_url,
            })

        if action == 'reject':
            reason = (request.POST.get('reason') or '').strip()[:200]
            debt.status = 'rejected'
            debt.reject_reason = reason
            debt.save()
            msg = f"❌ <b>{client.full_name}</b> nasiyani rad etdi\n💰 {amount}"
            if reason:
                msg += f"\n📝 Sababi: {html.escape(reason)}"
            msg += "\n\n🔁 Mijoz sahifasida izoh bilan qayta yuborishingiz mumkin."
            notify_shop_staff(debt.shop, msg)
            return render(request, 'status_page.html', {
                'title': 'Rad etildi',
                'message': "Do'konga xabar yuborildi. Savol bo'lsa, do'kon bilan bog'laning.",
                'icon': 'fa-circle-xmark',
                'color': 'text-danger',
                'cabinet_url': cabinet_url,
            })

    bal_uzs, bal_usd = client_balance(client)
    return render(request, 'debt_confirm.html', {
        'debt': debt,
        'item_lines': [line for line in debt.items.splitlines() if line.strip()],
        'balance_now': balance_text(bal_uzs, bal_usd),
        'balance_after': balance_text(bal_uzs + debt.amount_uzs, bal_usd + debt.amount_usd),
    })


@login_required(login_url='/login/')
def live_version_view(request):
    """Sahifalarning avtomatik yangilanishi uchun: do'kon ma'lumotlari o'zgardimi?"""
    return JsonResponse({'v': shop_version(get_current_shop(request))},
                        headers={'Cache-Control': 'no-store'})


def shop_stats(shop, **date_filter):
    """
    Do'kon statistikasi. Naqd savdolar nasiya va undiruvdan alohida hisoblanadi,
    chunki ular darhol to'langan va qarz qoldirmaydi.
    date_filter: masalan created_at__year=2026, created_at__month=9
    """
    confirmed = Debt.objects.filter(shop=shop, status='confirmed', **date_filter)
    credit = confirmed.filter(is_cash_sale=False)

    def total(qs, field):
        return qs.aggregate(s=Sum(field))['s'] or 0

    debts = credit.filter(transaction_type='debt')
    payments = credit.filter(transaction_type='payment')
    cash_sales = confirmed.filter(is_cash_sale=True, transaction_type='debt')

    sales_uzs, sales_usd = total(debts, 'amount_uzs'), total(debts, 'amount_usd')
    income_uzs, income_usd = abs(total(payments, 'amount_uzs')), abs(total(payments, 'amount_usd'))

    return {
        'sales_uzs': sales_uzs,
        'sales_usd': sales_usd,
        'income_uzs': income_uzs,
        'income_usd': income_usd,
        'diff_uzs': sales_uzs - income_uzs,
        'diff_usd': sales_usd - income_usd,
        'cash_uzs': total(cash_sales, 'amount_uzs'),
        'cash_usd': total(cash_sales, 'amount_usd'),
        'cash_count': cash_sales.count(),
    }


@login_required(login_url='/login/')
def dashboard_view(request):
    shop = get_current_shop(request)
    if not shop: return redirect('login_page')

    # 1. DO'KON ADMINLARI
    allowed_admins = AllowedAdmin.objects.filter(shop=shop).order_by('-created_at')

    # 2. ENG KATTA QARZDORLAR (to'liq ro'yxat "Mijozlar" bo'limida)
    debtors = Client.objects.filter(shop=shop).exclude(phone=CASH_CLIENT_PHONE).annotate(
        total_debt_uzs=Sum('debt__amount_uzs', filter=Q(debt__status='confirmed')),
        total_debt_usd=Sum('debt__amount_usd', filter=Q(debt__status='confirmed'))
    ).filter(Q(total_debt_uzs__gt=0) | Q(total_debt_usd__gt=0)).order_by('-total_debt_uzs', '-total_debt_usd')

    # 3. STATISTIKA (JAMI DAVR UCHUN)
    stats = shop_stats(shop)

    return render(request, 'dashboard.html', {
        'top_debtors': debtors[:10],
        'debtor_count': debtors.count(),
        'stats': stats,
        'active_tab': 'stats',
        'allowed_admins': allowed_admins,
        'shop': shop
    })

@login_required(login_url='/login/')
def admin_client_detail_view(request, client_id):
    shop = get_current_shop(request)
    # Faqat o'z mijozini ko'ra olsin
    client = get_object_or_404(Client, id=client_id, shop=shop)

    debts = Debt.objects.filter(client=client).order_by('-created_at')

    confirmed_debts = debts.filter(status='confirmed')
    stats = confirmed_debts.aggregate(sum_uzs=Sum('amount_uzs'), sum_usd=Sum('amount_usd'))

    # Botga ulanmagan mijozga taklif havolasi bo'lishi shart
    if not client.telegram_id and not client.invite_token:
        client.invite_token = uuid.uuid4()
        client.save(update_fields=['invite_token'])

    return render(request, 'admin_client_detail.html', {
        'client': client,
        'debts': debts,
        'due': dues.client_due_status(client),
        'today': timezone.localdate(),
        'total_uzs': stats['sum_uzs'] or 0,
        'total_usd': stats['sum_usd'] or 0,
        'back_url': 'client_list',
    })


def client_cabinet_view(request):
    client_id = request.session.get('client_id')
    if not client_id:
        return redirect('login_page')

    client = get_object_or_404(Client.objects.select_related('shop'), id=client_id)
    confirmed = Debt.objects.filter(client=client, status='confirmed')
    bal_uzs, bal_usd = client_balance(client)

    # Shu kalendar oyi (naqd savdolarsiz - ular darhol to'langan)
    month = confirmed.filter(created_at__date__gte=timezone.localdate().replace(day=1), is_cash_sale=False)
    month_debt = month.filter(transaction_type='debt').aggregate(s=Sum('amount_uzs'))['s'] or 0
    month_paid = abs(month.filter(transaction_type='payment').aggregate(s=Sum('amount_uzs'))['s'] or 0)

    # Shu Telegram akkauntning boshqa do'konlardagi hisoblari
    accounts = []
    if client.telegram_id:
        for acc in Client.objects.filter(telegram_id=client.telegram_id).select_related('shop').order_by('id'):
            acc_uzs, acc_usd = client_balance(acc)
            accounts.append({'id': acc.id, 'shop': acc.shop.name, 'debt_uzs': acc_uzs, 'debt_usd': acc_usd,
                             'active': acc.id == client.id})

    return render(request, 'client_cabinet.html', {
        'client': client,
        'accounts': accounts if len(accounts) > 1 else [],
        'shop_has_products': bool(client.shop and plans.has_feature(client.shop, plans.STORE)
                                  and client.shop.products.filter(is_active=True).exists()),
        'total_uzs': bal_uzs,
        'total_usd': bal_usd,
        'month_debt': month_debt,
        'month_paid': month_paid,
        'pending': Debt.objects.filter(client=client, status='pending', transaction_type='debt').order_by('-created_at'),
        'due': dues.client_due_status(client),
        'history': confirmed.order_by('-created_at')[:100],
    })


def client_switch_view(request, client_id):
    """Mijoz kabinetida boshqa do'kondagi hisobiga o'tish (faqat o'zining Telegram akkauntidagi)."""
    current = Client.objects.filter(id=request.session.get('client_id')).first()
    target = Client.objects.filter(id=client_id).first()
    if current and target and current.telegram_id and target.telegram_id == current.telegram_id:
        request.session['client_id'] = target.id
        request.session.pop('cart', None)  # savat do'konga tegishli
    return redirect('client_cabinet')


@csrf_exempt
def telegram_webhook(request):
    # Telegram har so'rovga setWebhook'da berilgan secret_token ni sarlavhada qo'shadi
    secret = settings.TELEGRAM_WEBHOOK_SECRET
    if secret and not hmac.compare_digest(
            request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), secret):
        return JsonResponse({'status': 'forbidden'}, status=403)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            if 'message' in data:
                chat_id = data['message']['chat']['id']
                text = data['message'].get('text', '')

                tg_from = data['message'].get('from', {})

                if text.startswith('/start '):
                    token = text.split(' ', 1)[1].strip()
                    if token == 'login':
                        # Do'kon egasi ro'yxatdan o'tgach shu yerga keladi
                        send_menu(chat_id, settings.SITE_DOMAIN)
                    elif token == 'signup':
                        # Landing sahifadagi "Telegram orqali boshlash" tugmasi
                        if bot_signup.already_registered(chat_id):
                            send_menu(chat_id, settings.SITE_DOMAIN)
                        else:
                            bot_signup.start(chat_id, tg_from)
                    elif token.startswith('staff_'):
                        accept_staff_invite(chat_id, token[len('staff_'):], tg_from)
                    else:
                        # Token orqali mijozni topamiz (u qaysi do'konda bo'lsa ham)
                        client = None
                        try:
                            client = Client.objects.filter(invite_token=uuid.UUID(token)).first()
                        except ValueError:
                            pass
                        if client:
                            client.telegram_id = chat_id
                            client.invite_token = None
                            client.save()
                            send_tg_msg(chat_id, f"🎉 {client.shop.name}: Xush kelibsiz, {client.full_name}!")
                            send_menu(chat_id, settings.SITE_DOMAIN)
                        else:
                            send_tg_msg(chat_id, "❌ Havola eskirgan yoki noto'g'ri. Do'kondan yangi havola so'rang.")
                elif text == '/start':
                    send_menu(chat_id, settings.SITE_DOMAIN)
                elif text == '/cancel':
                    if not bot_signup.cancel(chat_id):
                        send_menu(chat_id, settings.SITE_DOMAIN)
                elif text in ['/id', '/myid']:
                    send_tg_msg(chat_id, f"🆔 Sizning Telegram ID: <code>{chat_id}</code>")
                elif not text.startswith('/'):
                    # Ro'yxatdan o'tish jarayonidagi javob (do'kon nomi)
                    bot_signup.handle_text(chat_id, text)

            elif 'callback_query' in data:
                callback = data['callback_query']
                data_text = callback['data']
                chat_id = callback['message']['chat']['id']
                message_id = callback['message']['message_id']

                if data_text == 'signup_start':
                    if bot_signup.already_registered(chat_id):
                        send_menu(chat_id, settings.SITE_DOMAIN)
                    else:
                        bot_signup.start(chat_id, callback.get('from', {}))
                elif data_text.startswith('signup_cat:'):
                    bot_signup.handle_category(chat_id, message_id, data_text.split(':', 1)[1])
                elif data_text.startswith('order_accept_'):
                    order_id = data_text.split('_')[2]
                    handle_order_accept(chat_id, message_id, order_id)
                elif data_text.startswith('order_reject_'):
                    order_id = data_text.split('_')[2]
                    handle_order_reject(chat_id, message_id, order_id)

                answer_callback(callback['id'])

            return JsonResponse({'status': 'ok'})
        except Exception:
            logger.exception("Webhook xatosi")
            return JsonResponse({'status': 'error'})
    return JsonResponse({'status': 'error'}, status=405)
# --- LOGIKA FUNKSIYALARI ---

def accept_staff_invite(chat_id, token, tg_from):
    """Xodim taklif havolasini bosdi: foydalanuvchini do'konga xodim qilib qo'shamiz."""
    try:
        invite = StaffInvite.objects.select_related('shop').filter(token=uuid.UUID(token)).first()
    except ValueError:
        invite = None
    if not invite or not invite.is_valid:
        send_tg_msg(chat_id, "❌ Taklif havolasi eskirgan yoki ishlatilgan. Rahbardan yangi havola so'rang.")
        return
    if User.objects.filter(username=str(chat_id)).exists():
        send_tg_msg(chat_id, "ℹ️ Bu Telegram akkaunt allaqachon tizimda ro'yxatdan o'tgan.")
        send_menu(chat_id, settings.SITE_DOMAIN)
        return
    if not plans.can_add_staff(invite.shop):
        send_tg_msg(chat_id, "⛔ Do'konning tarifida xodimlar soni to'lgan. Do'kon rahbariga ayting.")
        return

    with transaction.atomic():
        user = User.objects.create_user(username=str(chat_id), password=None,
                                        first_name=(tg_from.get('first_name') or '')[:150])
        UserProfile.objects.create(user=user, shop=invite.shop, role='worker')
        AllowedAdmin.objects.update_or_create(telegram_id=chat_id,
                                              defaults={'shop': invite.shop, 'name': invite.name})
        invite.used_at = timezone.now()
        invite.save(update_fields=['used_at'])

    send_tg_msg(chat_id, f"🎉 Siz «{invite.shop.name}» do'koniga xodim sifatida qo'shildingiz!")
    send_menu(chat_id, settings.SITE_DOMAIN)
    notify_shop_staff(invite.shop, f"👤 <b>{invite.name}</b> taklifni qabul qildi va xodimlarga qo'shildi.",
                      exclude=chat_id)


def _order_for_staff(chat_id, message_id, order_id):
    """Buyurtmani faqat o'sha do'kon jamoasi a'zosi boshqara oladi."""
    order = Order.objects.select_related('client', 'shop').filter(id=order_id).first()
    if not order:
        edit_tg_message(chat_id, message_id, "❌ Buyurtma topilmadi.")
        return None
    if not order.shop or int(chat_id) not in shop_staff_ids(order.shop):
        send_tg_msg(chat_id, "⛔ Bu buyurtmani boshqarishga ruxsatingiz yo'q.")
        return None
    return order


def handle_order_accept(chat_id, message_id, order_id):
    order = _order_for_staff(chat_id, message_id, order_id)
    if not order:
        return
    # Bir vaqtda ikki xodim bossa ham bir marta yoziladi
    if not Order.objects.filter(id=order.id, status='new').update(status='accepted'):
        order.refresh_from_db()
        edit_tg_message(chat_id, message_id, f"ℹ️ Buyurtma #{order.id} allaqachon {order.get_status_display().lower()}.")
        return

    lines = []
    for item in order.orderitem_set.select_related('product'):
        name = item.product.name if item.product else "Noma'lum tovar"
        lines.append(f"{name}: {format_number(item.qty)} x {format_number(item.price)} = {format_number(item.total)} so'm")

    Debt.objects.create(
        shop=order.shop,
        client=order.client,
        amount_uzs=order.total_price,
        items=f"Buyurtma #{order.id}\n" + "\n".join(lines),
        status='confirmed',  # buyurtmani mijozning o'zi bergan
        transaction_type='debt',
    )

    edit_tg_message(chat_id, message_id, f"✅ Buyurtma #{order.id} nasiyaga yozildi\n👤 {order.client.full_name}\n"
                                         f"💰 {amount_text(order.total_price, 0)}")
    if order.client.telegram_id:
        bal_uzs, bal_usd = client_balance(order.client)
        send_tg_msg(order.client.telegram_id,
                    f"✅ Buyurtmangiz #{order.id} qabul qilindi va nasiyaga yozildi.\n"
                    f"💰 {amount_text(order.total_price, 0)}\n📉 Joriy qarzingiz: {balance_text(bal_uzs, bal_usd)}")


def handle_order_reject(chat_id, message_id, order_id):
    order = _order_for_staff(chat_id, message_id, order_id)
    if not order:
        return
    if not Order.objects.filter(id=order.id, status='new').update(status='rejected'):
        order.refresh_from_db()
        edit_tg_message(chat_id, message_id, f"ℹ️ Buyurtma #{order.id} allaqachon {order.get_status_display().lower()}.")
        return

    edit_tg_message(chat_id, message_id, f"❌ <b>Buyurtma #{order.id} bekor qilindi</b>\n👤 {order.client.full_name}")
    if order.client.telegram_id:
        send_tg_msg(order.client.telegram_id,
                    f"❌ Buyurtmangiz #{order.id} do'kon tomonidan bekor qilindi. Savol bo'lsa, do'kon bilan bog'laning.")


# --- TELEGRAM API YORDAMCHILARI ---

def answer_callback(callback_id):
    """Tugma bosilgandagi "yuklanmoqda" belgisini to'xtatish"""
    telegram.answer_callback(callback_id)


def answer_callback_text(callback_id, text):
    """Ekranda kichik xabar ko'rsatish (toast)"""
    telegram.answer_callback(callback_id, text=text, show_alert=True)


def edit_tg_message(chat_id, message_id, new_text):
    telegram.edit_message(chat_id, message_id, new_text)


def send_tg_msg(chat_id, text):
    telegram.send_message(chat_id, text)


def send_menu(chat_id, domain):
    """
    Foydalanuvchi turiga qarab menyu yuboradi:
    do'kon egasi/xodim, mijoz yoki hali ro'yxatdan o'tmagan odam.
    """
    try:
        login_url = f"https://{domain}/auth/telegram-login/"

        staff_user = User.objects.filter(username=str(chat_id)).first()
        if staff_user:
            shop = Shop.objects.filter(owner=staff_user).first()
            if not shop and hasattr(staff_user, 'profile'):
                shop = staff_user.profile.shop
            shop_name = f" «{shop.name}»" if shop else ""
            welcome_text = (
                f"🏪 <b>Do'koningiz{shop_name} tayyor!</b>\n\n"
                "Savdo, nasiya va to'lovlarni boshqarish uchun pastdagi tugmani bosing 👇"
            )
            button = {"text": "🏪 Do'konni ochish", "web_app": {"url": login_url}}
        elif Client.objects.filter(telegram_id=chat_id).exists():
            welcome_text = (
                "👋 <b>Nasiya Nazorati Tizimi</b>\n\n"
                "Shaxsiy kabinetingizga kirish uchun pastdagi tugmani bosing 👇"
            )
            button = {"text": "🏠 Kabinetga kirish", "web_app": {"url": login_url}}
        else:
            welcome_text = (
                "👋 <b>QarzDaptar</b>ga xush kelibsiz!\n\n"
                "Nasiya daftaringiz endi Telegramda: mijoz har bir nasiyani o'zi tasdiqlaydi.\n\n"
                "• <b>Do'kon egasimisiz?</b> Pastdagi tugmani bosing — 1 daqiqada do'kon ochiladi, "
                f"{bot_signup.TRIAL_DAYS} kun bepul.\n"
                "• <b>Mijozmisiz?</b> Do'kondan shaxsiy havola so'rang."
            )
            button = {"text": "🏪 Do'kon ochish", "callback_data": "signup_start"}

        telegram.send_message(chat_id, welcome_text, reply_markup={"inline_keyboard": [[button]]})
    except Exception:
        logger.exception("send_menu xatosi (chat=%s)", chat_id)


@shop_admin_required
def settings_view(request):
    shop = get_current_shop(request)
    # Do'kon uchun alohida settings olamiz
    settings_obj, created = Settings.objects.get_or_create(shop=shop)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_rate':
            rate = parse_amount(request.POST.get('usd_rate'))
            if 1000 <= rate <= 1000000:
                settings_obj.usd_rate = round(rate)
                settings_obj.save(update_fields=['usd_rate'])
                messages.success(request, f"✅ Kurs saqlandi: 1$ = {format_number(round(rate))} so'm")
            else:
                messages.error(request, "Kursni to'g'ri kiriting (masalan: 12 800).")

        elif action == 'update_reminders':
            settings_obj.reminder_enabled = request.POST.get('reminder_enabled') == 'on'
            try:
                settings_obj.reminder_days = min(max(int(request.POST.get('reminder_days') or 7), 1), 60)
            except ValueError:
                settings_obj.reminder_days = 7
            settings_obj.reminder_min_debt = round(parse_amount(request.POST.get('reminder_min_debt')))
            settings_obj.save(update_fields=['reminder_enabled', 'reminder_days', 'reminder_min_debt'])
            messages.success(request, "✅ Eslatma sozlamalari saqlandi." if settings_obj.reminder_enabled
                             else "Avtomatik eslatma o'chirildi.")

        elif action == 'update_shop':
            name = (request.POST.get('shop_name') or '').strip()
            if name:
                shop.name = name[:100]
                shop.save(update_fields=['name'])
                messages.success(request, "✅ Do'kon nomi saqlandi.")
            else:
                messages.error(request, "Do'kon nomini kiriting.")
        return redirect('settings')

    return render(request, 'settings.html', {
        'shop': shop,
        'settings': settings_obj,
        'back_url': 'main_menu',
    })



@login_required(login_url='/login/')
def client_list_view(request):
    """"Mijozlar" bo'limi: qidiruv, filtrlar va har bir mijozning balansi."""
    shop = get_current_shop(request)
    if not shop: return redirect('login_page')

    clients = (
        Client.objects.filter(shop=shop)
        .exclude(phone=CASH_CLIENT_PHONE)
        .annotate(
            bal_uzs=Sum('debt__amount_uzs', filter=Q(debt__status='confirmed')),
            bal_usd=Sum('debt__amount_usd', filter=Q(debt__status='confirmed')),
            pending_count=Count('debt', filter=Q(debt__status='pending')),
        )
        .order_by('full_name')
    )
    due_map = dues.shop_due_map(shop)
    clients = list(clients)
    for c in clients:
        c.due = due_map.get(c.id)

    return render(request, 'client_list.html', {
        'clients': clients,
        'search_query': request.GET.get('q', ''),
        'active_filter': request.GET.get('filter', 'all'),
        'active_tab': 'clients',
    })


@login_required(login_url='/login/')
def client_form_view(request, client_id=None):
    shop = get_current_shop(request)
    client = None
    if client_id:
        client = get_object_or_404(Client, id=client_id, shop=shop)

    # Tahrirlashda orqaga - mijoz sahifasiga, yangi mijozda - ro'yxatga
    back = {'back_href': reverse('admin_client_detail', args=[client.id])} if client else {'back_url': 'client_list'}

    if request.method == 'POST':
        full_name = (request.POST.get('full_name') or '').strip()
        raw_phone = request.POST.get('phone', '')
        phone = clean_phone_number(raw_phone)

        error = None
        if not client and not plans.can_add_client(shop):
            messages.error(request, client_limit_message(shop))
            return redirect(f"{reverse('pricing_page')}?need=clients")
        if not full_name:
            error = "Mijoz ismini kiriting."
        elif not phone:
            error = "Telefon raqam noto'g'ri. Masalan: +998 90 123 45 67"
        else:
            # Unikallikni faqat SHU DO'KON ichida tekshiramiz
            duplicates = Client.objects.filter(shop=shop, phone=phone)
            if client:
                duplicates = duplicates.exclude(id=client.id)
            if duplicates.exists():
                error = "Bu raqamli mijoz do'koningizda allaqachon bor."

        if error:
            messages.error(request, error)
            form_data = {'full_name': full_name, 'phone': raw_phone}
            return render(request, 'client_form.html', {'client': client, 'form': form_data, **back})

        if client:
            client.full_name = full_name
            client.phone = phone
            client.save()
            messages.success(request, "Mijoz yangilandi!")
        else:
            client = Client.objects.create(shop=shop, full_name=full_name, phone=phone)
            messages.success(request, "Yangi mijoz qo'shildi! Endi uni botga taklif qilishingiz mumkin.")

        return redirect('admin_client_detail', client_id=client.id)

    return render(request, 'client_form.html', {'client': client, **back})


@shop_admin_required
@plan_feature_required(plans.EXPORT)
def export_clients_view(request):
    wb, filename = exports.clients_export(get_current_shop(request))
    return exports.deliver(request, wb, filename, reverse('dashboard'))


@shop_admin_required
@plan_feature_required(plans.EXPORT)
def export_month_view(request):
    try:
        year, month = map(int, (request.GET.get('date') or '').split('-'))
    except ValueError:
        today = timezone.localdate()
        year, month = today.year, today.month
    wb, filename = exports.month_export(get_current_shop(request), year, month)
    return exports.deliver(request, wb, filename, f"{reverse('reports_page')}?date={year}-{month:02d}")


@login_required(login_url='/login/')
@require_POST
def remind_client_view(request, client_id):
    """Mijozga qarz eslatmasini hozir yuborish (bir soatda bir martadan ko'p emas)."""
    shop = get_current_shop(request)
    client = get_object_or_404(Client, id=client_id, shop=shop)
    if client.last_reminded_at and timezone.now() - client.last_reminded_at < timedelta(hours=1):
        messages.info(request, "Bu mijozga yaqinda eslatma yuborilgan. Keyinroq urinib ko'ring.")
    else:
        bal_uzs, bal_usd = client_balance(client)
        if send_reminder(client, bal_uzs, bal_usd):
            messages.success(request, f"🔔 {client.full_name}ga eslatma yuborildi.")
        else:
            messages.error(request, "Eslatma yuborilmadi: mijozning qarzi yo'q yoki botga ulanmagan.")
    return redirect('admin_client_detail', client_id=client.id)


@shop_admin_required
def client_reset_telegram_view(request, client_id):
    shop = get_current_shop(request)
    client = get_object_or_404(Client, id=client_id, shop=shop)
    # Telegram ID ni o'chiramiz va yangi taklif havolasi beramiz
    client.telegram_id = None
    client.invite_token = uuid.uuid4()
    client.save()

    messages.warning(request, "Telegram bog'lanishi uzildi. Mijozga yangi havola yuboring!")
    return redirect('admin_client_detail', client_id=client.id)


@login_required(login_url='/login/')
def reports_view(request):
    shop = get_current_shop(request)
    if not shop: return redirect('login_page')

    # 1. Sanani aniqlash
    selected_date = request.GET.get('date')
    if selected_date:
        year, month = map(int, selected_date.split('-'))
    else:
        now = timezone.now()
        year, month = now.year, now.month
        selected_date = now.strftime('%Y-%m')

    # 2. Umumiy Statistika
    stats = shop_stats(shop, created_at__year=year, created_at__month=month)

    # 3. MIJOZLAR RO'YXATI (YANGI QISM) ⚡️
    # Faqat shu oyda tranzaksiya qilgan mijozlarni olamiz
    active_clients = Client.objects.filter(
        shop=shop,
        debt__is_cash_sale=False,
        debt__status='confirmed',
        debt__created_at__year=year,
        debt__created_at__month=month
    ).distinct().annotate(
        # 1. NASIYA (UZS va USD)
        debt_uzs=Sum('debt__amount_uzs', filter=Q(debt__transaction_type='debt', debt__created_at__year=year,
                                                  debt__created_at__month=month)),
        debt_usd=Sum('debt__amount_usd', filter=Q(debt__transaction_type='debt', debt__created_at__year=year,
                                                  debt__created_at__month=month)),

        # 2. TO'LOV (UZS va USD)
        # Bazada to'lovlar manfiy saqlangan bo'lsa ham Sum qilaveramiz, keyin shablonda abs (modul) olamiz.
        # Agar musbat saqlangan bo'lsa, muammo yo'q.
        pay_uzs=Sum('debt__amount_uzs', filter=Q(debt__transaction_type='payment', debt__created_at__year=year,
                                                 debt__created_at__month=month)),
        pay_usd=Sum('debt__amount_usd', filter=Q(debt__transaction_type='payment', debt__created_at__year=year,
                                                 debt__created_at__month=month))
    ).order_by('-debt_uzs')

    context = {
        'shop': shop,
        'selected_date': selected_date,
        'year': year,
        'month': month,
        'active_clients': active_clients, # <-- Shablonga yuboramiz
        'stats': stats,
        'active_tab': 'stats',
    }
    return render(request, 'reports.html', context)


@csrf_exempt
@login_required
def create_client_ajax(request):
    if request.method == 'POST':
        try:
            shop = get_current_shop(request)
            data = json.loads(request.body)
            raw_phone = data.get('phone', '')
            clean_phone = clean_phone_number(raw_phone)
            if not clean_phone:
                return JsonResponse({'status': 'error', 'message': "Telefon raqam noto'g'ri! (Masalan: 901234567)"})

            full_name = (data.get('full_name') or '').strip()
            if not full_name:
                return JsonResponse({'status': 'error', 'message': "Mijoz ismini kiriting!"})
            phone = clean_phone

            # Tekshiramiz
            if Client.objects.filter(shop=shop, phone=phone).exists():
                return JsonResponse({'status': 'error', 'message': 'Bu raqamli mijoz allaqachon bor!'})
            if not plans.can_add_client(shop):
                return JsonResponse({'status': 'error', 'message': client_limit_message(shop),
                                     'upgrade_url': reverse('pricing_page') + '?need=clients'})


            client = Client.objects.create(
                shop=shop,
                full_name=full_name,
                phone=phone
            )

            return JsonResponse({
                'status': 'ok',
                'client_id': client.id,
                'client_name': client.full_name,
                'phone': client.phone,
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Faqat POST mumkin'})

@login_required(login_url='/login/')
def pricing_view(request):
    from billing.models import SubscriptionPayment
    from billing.views import providers_enabled

    shop = get_current_shop(request)
    returned = None
    if request.GET.get('payment', '').isdigit() and shop:
        returned = SubscriptionPayment.objects.filter(id=int(request.GET['payment']), shop=shop).first()
    plan = plans.current_plan(shop)
    on_trial = bool(shop and plan.is_paid and shop.subscription_ends_at
                    and not shop.subscription_payments.filter(status='paid').exists())
    return render(request, 'subs/pricing.html', {
        'shop': shop,
        'plan': plan,
        'on_trial': on_trial,
        'cards': landing.plan_cards('uz', shop),
        'client_count': plans.client_count(shop) if shop else 0,
        'staff_count': plans.staff_count(shop) if shop else 0,
        'need': request.GET.get('need', ''),
        'launch_active': plans.launch_price_active(),
        'launch_until': landing.placeholders()['launch_until'],
        'providers': providers_enabled(),
        'returned_payment': returned,
        'back_url': 'main_menu',
    })