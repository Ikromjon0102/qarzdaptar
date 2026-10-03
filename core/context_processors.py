from django.conf import settings

from .permissions import is_shop_admin

# Do'kon jamoasi sahifalari: pastki tab-bar doim ko'rinadi (sahifa nomi -> faol tab).
# Mijoz sahifalari, login va super-control bu ro'yxatda yo'q.
STAFF_TABS = {
    'main_menu': 'home',
    'settings': 'home',
    'pricing_page': 'home',
    'broadcast': 'home',
    'admin_control': 'home',
    'manage_admins': 'home',
    'manage_admins_id': 'home',
    'manage_products': 'home',
    'product_add': 'home',
    'product_edit': 'home',
    'client_list': 'clients',
    'client_add': 'clients',
    'client_edit': 'clients',
    'admin_client_detail': 'clients',
    'create_debt': 'sale',
    'create_payment': 'pay',
    'dashboard': 'stats',
    'reports_page': 'stats',
}

# Bu sahifalar ma'lumot o'zgarganda (masalan mijoz nasiyani tasdiqlasa) o'zi yangilanadi
LIVE_PAGES = {'main_menu', 'client_list', 'admin_client_detail', 'dashboard', 'reports_page'}


def shop_role(request):
    """Shablonlar uchun umumiy qiymatlar: rahbarmi, bot va yordam akkaunti nomi, tab-bar."""
    context = {
        'is_shop_admin': is_shop_admin(request.user),
        'bot_username': settings.BOT_USERNAME,
        'support_username': settings.SUPPORT_USERNAME,
    }
    match = getattr(request, 'resolver_match', None)
    url_name = match.url_name if match else None
    if request.user.is_authenticated and url_name in STAFF_TABS:
        # View o'zi active_tab bersa, o'shanisi ustun turadi
        context['active_tab'] = STAFF_TABS[url_name]
        from . import plans
        from .views import get_current_shop
        # Pullik imkoniyatlar yonida qulf belgisi uchun
        context['plan_features'] = plans.current_plan(get_current_shop(request)).features
        if url_name in LIVE_PAGES:
            from .live import shop_version
            from .views import get_current_shop
            context['live_reload'] = True
            context['live_version_now'] = shop_version(get_current_shop(request))
    return context
