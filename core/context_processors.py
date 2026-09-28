from django.conf import settings

from .permissions import is_shop_admin


def shop_role(request):
    """Shablonlar uchun umumiy qiymatlar: rahbarmi, bot va yordam akkaunti nomi."""
    return {
        'is_shop_admin': is_shop_admin(request.user),
        'bot_username': settings.BOT_USERNAME,
        'support_username': settings.SUPPORT_USERNAME,
    }
