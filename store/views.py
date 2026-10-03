# store/views.py
"""
Mijoz uchun do'kon: o'z do'konining mahsulotlarini tanlaydi va buyurtma beradi.
Buyurtma do'kon jamoasiga Telegram orqali boradi; qabul qilinsa nasiyaga yoziladi.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Client
from core import plans
from core.permissions import plan_feature_required, shop_admin_required
from core.utils import parse_amount
from .models import Category, Order, OrderItem, Product
from .utils import send_order_to_shop


def current_client(request):
    """Sessiyadagi mijoz (Telegram orqali kirgan) yoki None."""
    client_id = request.session.get('client_id')
    if not client_id:
        return None
    return Client.objects.select_related('shop').filter(id=client_id).first()


def shop_products(client):
    if not plans.has_feature(client.shop, plans.STORE):  # tarifda onlayn do'kon yo'q - buyurtma ham yo'q
        return Product.objects.none()
    return Product.objects.filter(shop=client.shop, is_active=True)


def get_cart(request, client):
    """Savat: {product_id(str): qty}. Boshqa do'kon mahsulotlari tozalanadi."""
    cart = request.session.get('cart', {})
    valid_ids = set(str(pk) for pk in shop_products(client).filter(id__in=cart.keys()).values_list('id', flat=True))
    cleaned = {pid: qty for pid, qty in cart.items() if pid in valid_ids and qty > 0}
    if cleaned != cart:
        request.session['cart'] = cleaned
    return cleaned


def cart_response(request, client, product_id):
    cart = get_cart(request, client)
    products = {str(p.id): p for p in shop_products(client).filter(id__in=cart.keys())}
    total = sum(products[pid].price * qty for pid, qty in cart.items())
    return JsonResponse({
        'status': 'ok',
        'qty': cart.get(str(product_id), 0),
        'total_items': sum(cart.values()),
        'total_price': int(total),
    })


def shop_home(request):
    client = current_client(request)
    if not client:
        return redirect('telegram_auth')
    if not plans.has_feature(client.shop, plans.STORE):
        messages.info(request, "Bu do'konda onlayn buyurtma hozircha yoqilmagan.")
        return redirect('client_cabinet')

    products = shop_products(client).select_related('category').order_by('category__name', 'name')
    categories = Category.objects.filter(shop=client.shop, product__in=products).distinct().order_by('name')
    cart = get_cart(request, client)
    total = sum(p.price * cart[str(p.id)] for p in products if str(p.id) in cart)

    return render(request, 'store/product_list.html', {
        'shop': client.shop,
        'products': products,
        'categories': categories,
        'cart': cart,
        'cart_items': sum(cart.values()),
        'cart_total': total,
        'back_url': 'client_cabinet',
    })


@require_POST
def add_to_cart(request, product_id):
    client = current_client(request)
    if not client:
        return JsonResponse({'status': 'error'}, status=403)
    get_object_or_404(Product, id=product_id, shop=client.shop, is_active=True)
    cart = get_cart(request, client)
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    request.session['cart'] = cart
    return cart_response(request, client, product_id)


@require_POST
def decrease_cart(request, product_id):
    client = current_client(request)
    if not client:
        return JsonResponse({'status': 'error'}, status=403)
    cart = get_cart(request, client)
    pid = str(product_id)
    if pid in cart:
        cart[pid] -= 1
        if cart[pid] <= 0:
            del cart[pid]
    request.session['cart'] = cart
    return cart_response(request, client, product_id)


def cart_detail(request):
    client = current_client(request)
    if not client:
        return redirect('telegram_auth')

    cart = get_cart(request, client)
    items = []
    total_price = 0
    for product in shop_products(client).filter(id__in=cart.keys()).order_by('name'):
        qty = cart[str(product.id)]
        total = product.price * qty
        total_price += total
        items.append({'product': product, 'qty': qty, 'total': total})

    return render(request, 'store/cart.html', {
        'items': items,
        'total_price': total_price,
        'back_url': 'shop_home',
    })


@require_POST
def clear_cart(request):
    request.session.pop('cart', None)
    return redirect('shop_home')


@require_POST
def checkout(request):
    client = current_client(request)
    if not client:
        return redirect('telegram_auth')

    cart = get_cart(request, client)
    products = list(shop_products(client).filter(id__in=cart.keys()))
    if not products:
        messages.warning(request, "Savat bo'sh.")
        return redirect('shop_home')

    order = Order.objects.create(shop=client.shop, client=client, total_price=0)
    items = []
    for product in products:
        items.append(OrderItem.objects.create(order=order, product=product,
                                              qty=cart[str(product.id)], price=product.price))
    order.total_price = sum(item.total for item in items)
    order.save(update_fields=['total_price'])

    send_order_to_shop(order, items)
    request.session.pop('cart', None)

    return render(request, 'store/order_success.html', {'order': order, 'items': items})


# --- DO'KON RAHBARI: MAHSULOTLARNI BOSHQARISH ---


def _staff_shop(request):
    from core.views import get_current_shop
    return get_current_shop(request)


@shop_admin_required
@plan_feature_required(plans.STORE)
def manage_products(request):
    shop = _staff_shop(request)
    products = Product.objects.filter(shop=shop).select_related('category').order_by('-is_active', 'name')
    return render(request, 'store/manage_products.html', {
        'products': products,
        'orders': Order.objects.filter(shop=shop).select_related('client').order_by('-created_at')[:20],
        'back_url': 'main_menu',
    })


@shop_admin_required
@plan_feature_required(plans.STORE)
def product_form(request, product_id=None):
    shop = _staff_shop(request)
    product = get_object_or_404(Product, id=product_id, shop=shop) if product_id else None

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        price = parse_amount(request.POST.get('price'))
        if not name or price <= 0:
            messages.error(request, "Mahsulot nomi va narxini kiriting.")
        else:
            product = product or Product(shop=shop)
            product.name = name[:200]
            product.price = round(price)
            product.description = (request.POST.get('description') or '').strip()
            product.is_active = request.POST.get('is_active') == 'on'
            cat_name = (request.POST.get('category') or '').strip()
            product.category = Category.objects.get_or_create(shop=shop, name=cat_name[:100])[0] if cat_name else None
            if request.FILES.get('image'):
                product.image = request.FILES['image']
            product.save()
            messages.success(request, f"✅ «{product.name}» saqlandi.")
            return redirect('manage_products')

    return render(request, 'store/product_form.html', {
        'product': product,
        'categories': Category.objects.filter(shop=shop).order_by('name'),
        'back_url': 'manage_products',
    })
