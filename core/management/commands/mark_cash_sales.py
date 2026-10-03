import re

from django.core.management.base import BaseCommand

from core.models import Debt

# Naqd savdo to'lovining matni: "To'lov: <tovarlar> (ID: <savdo id>)"
CASH_PAYMENT_RE = re.compile(r"^To'lov: .*\(ID: (\d+)\)$", re.DOTALL)


class Command(BaseCommand):
    help = "Eski naqd savdolarni (is_cash_sale maydoni qo'shilishidan oldingi) belgilab chiqadi."

    def handle(self, *args, **options):
        marked = 0
        payments = Debt.objects.filter(transaction_type='payment', is_cash_sale=False,
                                       items__startswith="To'lov: ")
        for payment in payments:
            match = CASH_PAYMENT_RE.match(payment.items)
            if not match:
                continue
            sale = Debt.objects.filter(id=int(match.group(1)), shop=payment.shop, client=payment.client,
                                       transaction_type='debt').first()
            if not sale:
                continue
            Debt.objects.filter(id__in=[payment.id, sale.id]).update(is_cash_sale=True)
            marked += 1

        self.stdout.write(self.style.SUCCESS(f"{marked} ta naqd savdo belgilandi."))
