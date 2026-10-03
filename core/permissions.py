from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse


def is_shop_admin(user):
    """Do'kon rahbarimi? (egasi, 'admin' rolidagi profil yoki superuser)"""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.shops.exists():
        return True
    # Profil bo'lmasa RelatedObjectDoesNotExist (AttributeError) -> None
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.role == 'admin')


def shop_admin_required(view):
    """Faqat do'kon rahbari kira oladigan sahifalar uchun (xodimlar kirmaydi)."""
    @wraps(view)
    @login_required(login_url='/login/')
    def wrapper(request, *args, **kwargs):
        if not is_shop_admin(request.user):
            messages.error(request, "⛔ Bu bo'lim faqat do'kon rahbari uchun.")
            return redirect('main_menu')
        return view(request, *args, **kwargs)
    return wrapper


def plan_feature_required(feature):
    """Imkoniyat joriy tarifda bo'lmasa - tarif sahifasiga, qaysi tarifda borligini aytib."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            from . import plans
            from .views import get_current_shop
            if not plans.has_feature(get_current_shop(request), feature):
                messages.info(request, f"🔒 «{plans.FEATURE_NAMES[feature]}» "
                                       f"{plans.minimal_plan_for(feature).name} tarifida mavjud.")
                return redirect(f"{reverse('pricing_page')}?need={feature}")
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def client_limit_message(shop):
    from . import plans
    limit = plans.current_plan(shop).max_clients
    return (f"🔒 {plans.current_plan(shop).name} tarifida {limit} tagacha mijoz. "
            f"Yangi mijoz qo'shish uchun Standart tarifga o'ting — mavjud mijozlar bilan ishlash davom etadi.")
