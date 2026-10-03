"""Obuna to'lovlari (Payme / Click)."""
import logging

from django.db import models, transaction
from django.utils import timezone

from core import plans
from core.models import Shop

logger = logging.getLogger(__name__)


class SubscriptionPayment(models.Model):
    PROVIDERS = (('payme', 'Payme'), ('click', 'Click'))
    STATUSES = (
        ('new', 'Yangi'),            # to'lov sahifasiga yuborildi
        ('pending', 'Jarayonda'),    # to'lov tizimi tranzaksiya ochdi
        ('paid', "To'langan"),
        ('cancelled', 'Bekor qilingan'),
    )

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='subscription_payments')
    provider = models.CharField(max_length=10, choices=PROVIDERS)
    plan = models.CharField(max_length=20, choices=plans.CHOICES, default=plans.STANDARD, verbose_name="Tarif")
    months = models.PositiveSmallIntegerField(default=1)  # 1 - oylik, 12 - yillik
    amount = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Summa (so'm)")
    status = models.CharField(max_length=10, choices=STATUSES, default='new')

    # To'lov tizimidagi tranzaksiya ID si (Payme: params.id, Click: click_trans_id)
    provider_trans_id = models.CharField(max_length=64, blank=True, db_index=True)
    # Payme holati: 1 yaratilgan, 2 bajarilgan, -1 yaratilgandan keyin bekor, -2 bajarilgandan keyin bekor
    payme_state = models.SmallIntegerField(default=0)
    payme_create_time = models.BigIntegerField(default=0)   # millisekund
    payme_perform_time = models.BigIntegerField(default=0)
    payme_cancel_time = models.BigIntegerField(default=0)
    cancel_reason = models.SmallIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Obuna to'lovi"
        verbose_name_plural = "Obuna to'lovlari"
        ordering = ['-created_at']

    def __str__(self):
        return f"#{self.id} {self.shop.name} — {self.amount} so'm ({self.get_provider_display()}, {self.get_status_display()})"

    @property
    def amount_tiyin(self):
        return int(self.amount) * 100

    def mark_paid(self):
        """To'lov tasdiqlandi: obunani uzaytirish va do'kon egasini xabardor qilish (bir marta)."""
        with transaction.atomic():
            payment = SubscriptionPayment.objects.select_for_update().get(pk=self.pk)
            if payment.status == 'paid':
                return False
            payment.status = 'paid'
            payment.paid_at = timezone.now()
            payment.save(update_fields=['status', 'paid_at'])
            shop = payment.shop
            shop.plan = payment.plan
            # Ishga tushirish muddatida Standart'ni to'lagan do'kon shu narxni saqlab qoladi
            if payment.plan == plans.STANDARD and plans.launch_price_active(timezone.localdate(payment.created_at)):
                shop.launch_price_locked = True
            shop.save(update_fields=['plan', 'launch_price_locked'])
            ends = shop.extend_subscription(plans.period_days(payment.months))
        self.status, self.paid_at = payment.status, payment.paid_at
        logger.info("Obuna to'lovi #%s qabul qilindi: %s, %s so'm", self.pk, self.shop.name, self.amount)

        from core import telegram
        owner_id = self.shop.owner.username
        if owner_id.isdigit():
            telegram.send_message(int(owner_id),
                                  f"✅ <b>To'lov qabul qilindi — {plans.PLANS[self.plan].name} tarif</b>\n"
                                  f"💰 {int(self.amount):,} so'm ({self.get_provider_display()})\n".replace(',', ' ') +
                                  f"📅 Tarif {timezone.localtime(ends):%d.%m.%Y} gacha faol. Rahmat!")
        return True
