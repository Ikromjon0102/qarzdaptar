# core/middleware.py
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse
from store.models import Shop


class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Tizimga kirmagan bo'lsa yoki Superadmin bo'lsa - tekshirmaymiz
        if not request.user.is_authenticated or request.user.is_superuser:
            return self.get_response(request)

        # 2. Istisno sahifalar (Bu yerlarga puli tugasa ham kira olishi kerak)
        # 'logout', 'pricing', 'webhook' va statik fayllar ochiq bo'lishi kerak
        allowed_paths = [
            '/logout/',
            '/admin/',
            '/pricing/',  # Buni keyin yasaymiz
            '/api/webhook/',
            '/static/',
            '/media/'
        ]

        for path in allowed_paths:
            if request.path.startswith(path):
                return self.get_response(request)

        # 3. Foydalanuvchining do'konini aniqlash
        shop = None
        if hasattr(request.user, 'shops') and request.user.shops.exists():
            shop = request.user.shops.first()  # Do'kon egasi
        elif hasattr(request.user, 'profile'):
            shop = request.user.profile.shop  # Xodim

        # 4. TEKSHIRUV: Vaqti tugaganmi?
        if shop:
            # Agar obuna vaqti belgilanmagan bo'lsa (eski do'konlar), o'tkazib yuboramiz (yoki avtomat yoqamiz)
            if shop.subscription_ends_at:
                if shop.subscription_ends_at < timezone.now():
                    # Vaqti tugagan! Pricing sahifasiga otamiz
                    # Hozircha 'pricing' url yo'q, shuning uchun vaqtincha settingsga otib turamiz
                    # Keyinroq alohida 'To'lov' sahifasi qilamiz.
                    return redirect('pricing_page')

        return self.get_response(request)