"""
Qarzdorlarga avtomatik eslatma yuborish.

Cron (har kuni soat 10:00):
    0 10 * * * cd /path/to/qarzdaptar && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
"""
import time

from django.core.management.base import BaseCommand

from core.reminders import due_reminders, send_reminder


class Command(BaseCommand):
    help = "Eslatmani yoqqan do'konlarning qarzdorlariga Telegram orqali eslatma yuboradi."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Yubormasdan, kimga borishini ko'rsatish")

    def handle(self, *args, **options):
        sent = 0
        for client, bal_uzs, bal_usd in due_reminders():
            if options['dry_run']:
                self.stdout.write(f"{client.shop.name}: {client.full_name} — {bal_uzs} so'm, ${bal_usd}")
                continue
            # Buyruq tugaguncha hammasi yuborilishi uchun sinxron; Telegram limitidan oshmaslik uchun pauza
            if send_reminder(client, bal_uzs, bal_usd, background=False):
                sent += 1
                time.sleep(0.05)
        if not options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f"{sent} ta eslatma yuborildi."))
