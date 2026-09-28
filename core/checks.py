from django.conf import settings
from django.core.checks import Warning, register


@register()
def secrets_check(app_configs, **kwargs):
    """`manage.py check` / runserver paytida sozlanmagan maxfiy qiymatlar haqida ogohlantiradi."""
    warnings = []
    if not settings.BOT_TOKEN:
        warnings.append(Warning(
            "BOT_TOKEN sozlanmagan: bot xabar yubora olmaydi va Telegram orqali kirish ishlamaydi.",
            hint=".env fayliga BOT_TOKEN=... yozing (namuna: .env.example).",
            id='core.W001',
        ))
    if settings.SECRET_KEY.startswith('django-insecure'):
        warnings.append(Warning(
            "DJANGO_SECRET_KEY sozlanmagan, vaqtinchalik kalit ishlatilmoqda.",
            hint=".env fayliga yangi DJANGO_SECRET_KEY yozing.",
            id='core.W002',
        ))
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        warnings.append(Warning(
            "TELEGRAM_WEBHOOK_SECRET sozlanmagan: /webhook/ ga istalgan odam soxta so'rov yubora oladi.",
            hint=".env ga TELEGRAM_WEBHOOK_SECRET yozing va `python manage.py set_webhook` ni ishga tushiring.",
            id='core.W003',
        ))
    return warnings
