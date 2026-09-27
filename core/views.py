import json
import uuid
import requests
import threading
import time
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Sum, Q
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from .models import Shop, UserProfile
from store.models import Order
# Modellar
from .models import Client, Debt, Settings, AllowedAdmin, Shop, UserProfile, CASH_CLIENT_PHONE
# from store.models import Order, Product  # Agar kerak bo'lsa
import json
import requests
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone

from .utils import clean_phone_number, parse_amount
from .permissions import is_shop_admin, shop_admin_required


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
    return render(request, 'landing.html')


# 1. LOGIN LOGIKASINI SODDALASHTIRAMIZ
@csrf_exempt
def telegram_auth_view(request):
    """
    Telegram orqali kirishni tekshirish (SaaS versiya)
    """
    if request.method == 'GET':
        return render(request, 'login_loader.html')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            telegram_id = int(data.get('telegram_id'))

            # 1. XODIM / ADMIN SIFATIDA KIRISH
            # Biz "Admin qo'shish"da User username=telegram_id qilib ochganmiz
            user = User.objects.filter(username=str(telegram_id)).first()
            if user:
                login(request, user)
                return JsonResponse({'status': 'ok', 'redirect_url': '/'})

            # 2. PLATFORMA EGASI (Superuser)
            admins = AllowedAdmin.objects.filter(telegram_id=telegram_id)
            if telegram_id in admins:
                superuser = User.objects.filter(is_superuser=True).first()
                if superuser:
                    login(request, superuser)
                    return JsonResponse({'status': 'ok', 'redirect_url': '/'})

            # 3. MIJOZ SIFATIDA KIRISH
            # Mijoz qaysi do'konniki bo'lsa ham kiraveradi,
            # lekin client_cabinet faqat o'ziga tegishli narsani ko'rsatadi.
            client = Client.objects.filter(telegram_id=telegram_id).first()
            if client:
                request.session['client_id'] = client.id
                return JsonResponse({'status': 'ok', 'redirect_url': '/my-cabinet/'})

            return JsonResponse({'status': 'ok', 'redirect_url': '/login/'}, status=200)

        except Exception as e:
            print(f"Auth error: {e}")
            return JsonResponse({'status': 'error'}, status=400)
    return JsonResponse({'status': 'error'}, status=405)


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
        error = None
        if not items_list:
            error = "Kamida bitta tovarning soni va narxini kiriting."
        elif sale_mode == 'debt' and not client:
            error = "Nasiya uchun ro'yxatdan mijozni tanlang."

        if error:
            messages.error(request, error)
            context.update({
                'sale_mode': sale_mode,
                'payment_type': payment_type,
                'selected_client_id': client.id if client else '',
                'prefill_items': prefill_items,
                'no_tg_action': request.POST.get('no_tg_action', 'confirm'),
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
                msg = f"💸 <b>To'lov qabul qilindi!</b>\n\n"
                msg += f"👤 Mijoz: {client.full_name}\n"
                msg += f"💰 To'landi: <b>{amount_str}</b> ({method_display})\n"
                if note: msg += f"📝 Izoh: {note}\n"
                msg += "➖➖➖➖➖➖➖➖\n"
                msg += f"📉 Joriy holat: <b>{balance_str}</b>"
                send_tg_msg(client.telegram_id, msg)
            except Exception as e:
                print(f"Telegram Error: {e}")

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

    # 1. QAYTA YUBORISH (Agar xabar bormagan bo'lsa)
    if action == 'resend':
        if debt.status == 'pending':
            # Telegramga signal yuboramiz
            domain = request.get_host()
            # bot_utils dagi funksiyani chaqiramiz
            from .bot_utils import send_confirmation_request
            if debt.client.telegram_id:
                send_confirmation_request(debt.client.telegram_id, debt, domain)
                messages.success(request, "Tasdiqlash so'rovi qayta yuborildi!")
            else:
                messages.error(request, "Mijozning Telegrami ulanmagan!")
    
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

def debt_detail_view(request, debt_uuid):
    debt = get_object_or_404(Debt, uuid=debt_uuid)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if debt.status != 'pending':
            # Agar allaqachon bosib bo'lgan bo'lsa
            return render(request, 'status_page.html', {
                'title': 'Eskirgan havola',
                'message': f"Bu so'rov allaqachon {debt.get_status_display().lower()} bo'lgan.",
                'icon': 'fa-circle-info',
                'color': 'text-warning'
            })

        if action == 'confirm':
            debt.status = 'confirmed'
            debt.save()
            return render(request, 'status_page.html', {
                'title': 'Muvaffaqiyatli!',
                'message': 'Siz nasiyani tasdiqladingiz. Rahmat!',
                'icon': 'fa-circle-check',
                'color': 'text-success'
            })
            
        elif action == 'reject':
            debt.status = 'rejected'
            debt.save()
            return render(request, 'status_page.html', {
                'title': 'Rad etildi',
                'message': 'Siz nasiyani rad etdingiz.',
                'icon': 'fa-circle-xmark',
                'color': 'text-danger'
            })
            
    return render(request, 'debt_confirm.html', {'debt': debt})


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
        'total_uzs': stats['sum_uzs'] or 0,
        'total_usd': stats['sum_usd'] or 0,
        'back_url': 'client_list',
    })


def client_cabinet_view(request):
    client_id = request.session.get('client_id')
    if not client_id: return redirect('login_page')  # Login page nomini tekshiring (telegram_auth bo'lishi mumkin)

    client = get_object_or_404(Client, id=client_id)

    # Sanalar
    now = timezone.now()
    month_start = now - timedelta(days=30)

    # Hamma qarzlari (Bu yerda 'debts' deb nomlangan o'zgaruvchi aslida butun tarix)
    all_history = Debt.objects.filter(client=client, status='confirmed').order_by('-created_at')

    # Jami qarz (Balans)
    totals = all_history.aggregate(sum_uzs=Sum('amount_uzs'), sum_usd=Sum('amount_usd'))

    # YANGI: Shu oydagi xarajatlari
    month_totals = all_history.filter(created_at__gte=month_start).aggregate(
        m_uzs=Sum('amount_uzs'),
        m_usd=Sum('amount_usd')
    )

    search_query = request.GET.get('q', '')

    if search_query:
        all_history = all_history.filter(items__icontains=search_query)

    context = {
        'client': client,

        # --- O'ZGARISH SHU YERDA ---
        # HTML fayl 'history' ni kutmoqda, 'debts' ni emas.
        'history': all_history[:50],  # 20 ta kamlik qilishi mumkin, 50 qildim
        # ---------------------------

        'total_uzs': totals['sum_uzs'] or 0,
        'total_usd': totals['sum_usd'] or 0,
        'month_uzs': month_totals['m_uzs'] or 0,
        'month_usd': month_totals['m_usd'] or 0,
        'search_query': search_query,
    }
    return render(request, 'client_cabinet.html', context)


# Modellarni import qilamiz
from .models import Client, Debt
# Agar Order store app ichida bo'lsa:
# from store.models import Order

@csrf_exempt
def telegram_webhook(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            if 'message' in data:
                chat_id = data['message']['chat']['id']
                text = data['message'].get('text', '')

                if text.startswith('/start '):
                    token = text.split(' ', 1)[1].strip()
                    if token == 'login':
                        # Do'kon egasi ro'yxatdan o'tgach shu yerga keladi
                        send_menu(chat_id, request.get_host())
                    elif token == 'id':
                        # Landing sahifadagi "ID olish" tugmasi
                        send_tg_msg(chat_id, f"🆔 Sizning Telegram ID: <code>{chat_id}</code>\n\n"
                                             "Shu raqamni nusxalab, ro'yxatdan o'tish formasiga kiriting.")
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
                            send_menu(chat_id, request.get_host())
                        else:
                            send_tg_msg(chat_id, "❌ Havola eskirgan yoki noto'g'ri. Do'kondan yangi havola so'rang.")
                elif text == '/start':
                    send_menu(chat_id, request.get_host())
                elif text in ['/id', '/myid']:
                    send_tg_msg(chat_id, f"🆔 Sizning Telegram ID: <code>{chat_id}</code>")

            elif 'callback_query' in data:
                callback = data['callback_query']
                data_text = callback['data']
                chat_id = callback['message']['chat']['id']
                message_id = callback['message']['message_id']

                if data_text.startswith('order_accept_'):
                    order_id = data_text.split('_')[2]
                    handle_order_accept(chat_id, message_id, order_id)
                elif data_text.startswith('order_reject_'):
                    order_id = data_text.split('_')[2]
                    handle_order_reject(chat_id, message_id, order_id)

                answer_callback(callback['id'])

            return JsonResponse({'status': 'ok'})
        except Exception as e:
            print(e)
            return JsonResponse({'status': 'error'})
    return JsonResponse({'status': 'error'}, status=405)
# --- LOGIKA FUNKSIYALARI ---

def handle_order_accept(chat_id, message_id, order_id):
    try:
        order = Order.objects.get(id=order_id)
        if order.status != 'new':
            return

        order.status = 'accepted'
        order.save()

        items_desc = f"🛒 Buyurtma #{order.id}:\n"
        for item in order.orderitem_set.all():
            p_name = item.product.name if item.product else "Noma'lum"
            items_desc += f"- {p_name} ({item.qty}x)\n"

        # DEBT YARATISH (shop ni qo'shamiz)
        Debt.objects.create(
            shop=order.shop,  # <--- MUHIM
            client=order.client,
            amount_uzs=order.total_price,
            items=items_desc,
            status='confirmed',
            transaction_type='debt'
        )

        edit_tg_message(chat_id, message_id, f"✅ Qabul qilindi\n👤 {order.client.full_name}")
        if order.client.telegram_id:
            send_tg_msg(order.client.telegram_id, f"✅ Buyurtmangiz (#{order.id}) qabul qilindi.")

    except Order.DoesNotExist:
        pass
    except Exception as e:
        print(e)


def handle_order_reject(chat_id, message_id, order_id):
    print(f"❌ Order #{order_id} bekor qilinmoqda...")
    try:
        order = Order.objects.get(id=order_id)

        if order.status != 'new':
            edit_tg_message(chat_id, message_id, f"⚠️ Bu buyurtma allaqachon {order.get_status_display()} bo'lgan!")
            return

        # 1. Statusni bekor qilish
        order.status = 'rejected'
        order.save()

        # 2. Xabarni yangilash
        new_text = (
            f"❌ <b>BEKOR QILINDI</b>\n"
            f"👤 {order.client.full_name}\n"
            f"Buyurtma rad etildi."
        )
        edit_tg_message(chat_id, message_id, new_text)

    except Order.DoesNotExist:
        edit_tg_message(chat_id, message_id, "❌ Buyurtma topilmadi.")
    except Exception as e:
        print(f"❌ handle_order_reject ichida xato: {e}")


# --- TELEGRAM API YORDAMCHILARI ---

def answer_callback(callback_id):
    """Loadingni to'xtatish"""
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_id})
    except Exception as e:
        print(f"answer_callback error: {e}")

def answer_callback_text(callback_id, text):
    """Ekranda kichik xabar ko'rsatish (Toast)"""
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/answerCallbackQuery"
        requests.post(url, json={"callback_query_id": callback_id, "text": text, "show_alert": True})
    except Exception as e:
        print(f"answer_callback_text error: {e}")

def edit_tg_message(chat_id, message_id, new_text):
    """Xabarni tahrirlash"""
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": new_text,
            "parse_mode": "HTML"
        }
        res = requests.post(url, json=payload)
        if res.status_code != 200:
            print(f"Telegram Edit Error: {res.text}")
    except Exception as e:
        print(f"edit_tg_message error: {e}")

def send_tg_msg(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram send error: {e}")

def send_menu(chat_id, domain):
    """
    Foydalanuvchi turiga qarab menyu yuboradi:
    do'kon egasi/xodim, mijoz yoki hali ro'yxatdan o'tmagan odam.
    """
    try:
        url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
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
                "Siz hali ro'yxatdan o'tmagansiz.\n"
                "• <b>Do'kon egasimisiz?</b> Pastdagi tugma orqali do'kon oching.\n"
                "• <b>Mijozmisiz?</b> Do'kondan shaxsiy havola so'rang.\n\n"
                f"🆔 Sizning Telegram ID: <code>{chat_id}</code>"
            )
            button = {"text": "🏪 Do'kon ochish", "web_app": {"url": f"https://{domain}/"}}

        payload = {
            "chat_id": chat_id,
            "text": welcome_text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": [[button]]}
        }
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram menu error: {e}")


@shop_admin_required
def settings_view(request):
    shop = get_current_shop(request)
    # Do'kon uchun alohida settings olamiz
    settings_obj, created = Settings.objects.get_or_create(shop=shop)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_rate':
            new_rate = request.POST.get('usd_rate')
            if new_rate:
                settings_obj.usd_rate = new_rate
                settings_obj.save()
                messages.success(request, f"Kurs yangilandi: {new_rate}")

        elif action == 'add_admin':
            # YANGI ADMIN (XODIM) QO'SHISH
            name = request.POST.get('name')
            tg_id = request.POST.get('telegram_id')
            if name and tg_id:
                # 1. User yaratamiz (Login uchun)
                if not User.objects.filter(username=str(tg_id)).exists():
                    user = User.objects.create_user(username=str(tg_id), password='worker_password')
                    # 2. Uni shu do'konga bog'laymiz
                    UserProfile.objects.create(user=user, shop=shop, role='worker')
                    # 3. Ro'yxatga (Whitelist) qo'shamiz
                    AllowedAdmin.objects.create(shop=shop, name=name, telegram_id=tg_id)
                    messages.success(request, f"Xodim {name} qo'shildi!")
                else:
                    messages.error(request, "Bu Telegram ID band!")

    # Shu do'kon adminlari
    allowed_admins = AllowedAdmin.objects.filter(shop=shop)

    return render(request, 'settings.html', {
        'settings': settings_obj,
        'allowed_admins': allowed_admins,
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
    shop = get_current_shop(request)
    return render(request, 'subs/pricing.html', {'shop': shop})