from .permissions import is_shop_admin


def shop_role(request):
    """Shablonlarda rahbarga tegishli tugmalarni yashirish uchun."""
    return {'is_shop_admin': is_shop_admin(request.user)}
