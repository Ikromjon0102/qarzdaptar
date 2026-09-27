from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


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
