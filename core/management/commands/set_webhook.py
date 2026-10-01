import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Telegram webhook'ini SITE_DOMAIN va TELEGRAM_WEBHOOK_SECRET bilan o'rnatadi."

    def handle(self, *args, **options):
        if not settings.BOT_TOKEN:
            raise CommandError("BOT_TOKEN sozlanmagan (.env).")

        payload = {'url': f"https://{settings.SITE_DOMAIN}/webhook/"}
        if settings.TELEGRAM_WEBHOOK_SECRET:
            payload['secret_token'] = settings.TELEGRAM_WEBHOOK_SECRET

        try:
            resp = requests.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/setWebhook", json=payload, timeout=15)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"Telegram'ga ulanib bo'lmadi: {exc.__class__.__name__}")
        if not data.get('ok'):
            raise CommandError(f"Telegram xatosi: {data}")
        self.stdout.write(self.style.SUCCESS(f"Webhook o'rnatildi: {payload['url']}"
                                             f"{' (secret bilan)' if 'secret_token' in payload else ''}"))
