"""
Qarzdorlarga avtomatik eslatma yuborish.

Cron (har kuni soat 10:00):
    0 10 * * * cd /path/to/qarzdaptar && venv/bin/python manage.py send_reminders >> logs/reminders.log 2>&1
"""
import time

from django.core.management.base import BaseCommand

from core.reminders import due_date_reminders, due_reminders, send_due_reminder, send_reminder


class Command(BaseCommand):
    help = "Muddati yaqinlashgan nasiyalar va qarzdorlarga Telegram orqali eslatma yuboradi."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Yubormasdan, kimga borishini ko'rsatish")

    def handle(self, *args, **options):
        # 1. To'lov muddati: ertaga va bugun
        due_sent = 0
        for client, stage, due_date, left_uzs, left_usd, debt_ids in due_date_reminders():
            if options['dry_run']:
                self.stdout.write(f"[muddat {due_date:%d.%m}] {client.shop.name}: {client.full_name} — "
                                  f"{left_uzs} so'm, ${left_usd}")
                continue
            send_due_reminder(client, stage, due_date, left_uzs, left_usd, debt_ids, background=False)
            due_sent += 1
            time.sleep(0.05)

        # 2. Umumiy qarz eslatmasi (har N kunda)
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
            self.stdout.write(self.style.SUCCESS(f"{due_sent} ta muddat eslatmasi, {sent} ta qarz eslatmasi yuborildi."))
