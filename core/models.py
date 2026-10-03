# core/models.py
import uuid
from datetime import timedelta


from django.db import models
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.utils import timezone

from . import plans

# --- 1. DO'KON MODELI ---
class Shop(models.Model):
    name = models.CharField(max_length=100, verbose_name="Do'kon nomi")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shops', verbose_name="Egasining logini")
    created_at = models.DateTimeField(auto_now_add=True)
    CATEGORY_CHOICES = (
        ('grocery', 'Oziq-ovqat'),
        ('construction', 'Qurilish mollari'),
        ('plumbing', 'Santexnika'),
        ('tech', 'Maishiy texnika'),
        ('electronics', 'Telefon va elektronika'),
        ('clothing', 'Kiyim-kechak'),
        ('household', "Xo'jalik mollari"),
        ('auto', 'Avto ehtiyot qismlar'),
        ('pharmacy', 'Dorixona'),
        ('cosmetics', 'Kosmetika va parfyumeriya'),
        ('furniture', 'Mebel'),
        ('other', 'Boshqa'),
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other', verbose_name="Do'kon turi")

    # TARIF VA OBUNA (core/plans.py). Pullik tarif muddati tugasa - Bepul tarif.
    plan = models.CharField(max_length=20, choices=plans.CHOICES, default=plans.FREE, verbose_name="Tarif")
    is_trial_used = models.BooleanField(default=False, verbose_name="Sinov davri ishlatilganmi?")
    subscription_ends_at = models.DateTimeField(null=True, blank=True, verbose_name="Tarif tugash vaqti",
                                                help_text="Bo'sh - muddatsiz")
    launch_price_locked = models.BooleanField(default=False, verbose_name="Ishga tushirish narxi saqlangan")

    # Sozlamalar
    telegram_bot_token = models.CharField(max_length=100, blank=True, null=True, verbose_name="Bot Token")
    is_active = models.BooleanField(default=True, verbose_name="To'lov qilinganmi?")  # Obuna uchun

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

    def extend_subscription(self, days=30):
        """Obunani uzaytirish: muddat tugagan bo'lsa bugundan, aks holda joriy muddat oxiridan."""
        now = timezone.now()
        start = self.subscription_ends_at if self.subscription_ends_at and self.subscription_ends_at > now else now
        self.subscription_ends_at = start + timedelta(days=days)
        self.is_active = True
        self.save(update_fields=['subscription_ends_at', 'is_active'])
        return self.subscription_ends_at

    @property
    def current_plan(self):
        return plans.current_plan(self)

    @property
    def days_left(self):
        """Qolgan kunlarni hisoblash"""
        if not self.subscription_ends_at:
            return 0
        delta = self.subscription_ends_at - timezone.now()
        return max(delta.days, 0)


# --- 2. ADMIN/XODIM PROFILI (YANGI) ---
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, verbose_name="Do'kon")
    role = models.CharField(max_length=20, choices=(('admin', 'Admin'), ('worker', 'Xodim')), default='admin')

    def __str__(self):
        return f"{self.user.username} - {self.shop.name}"


# Naqd savdolar yoziladigan texnik "Kassa" mijozining telefoni.
# U mijozlar ro'yxatlarida ko'rsatilmaydi.
CASH_CLIENT_PHONE = '000000000'


# --- 3. MIJOZ ---
class Client(models.Model):
    # Har bir mijoz qaysidir do'konga tegishli bo'lishi shart
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='clients', null=True, blank=True)

    full_name = models.CharField(max_length=100, verbose_name="F.I.SH")

    # DIQQAT: unique=True ni olib tashladik. Chunki A do'konda bor mijoz, B do'konda ham bo'lishi mumkin.
    phone = models.CharField(max_length=15, verbose_name="Telefon")
    telegram_id = models.BigIntegerField(null=True, blank=True)

    invite_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, null=True, blank=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True, verbose_name="Oxirgi eslatma")

    class Meta:
        # Bitta do'kon ichida telefon raqam takrorlanmasin (boshqa do'konda bo'lishi mumkin)
        unique_together = ('shop', 'phone')

    def __str__(self):
        status = "✅" if self.telegram_id else "⏳"
        return f"{self.full_name} ({self.phone}) {status}"

    @property
    def balance(self):
        """
        Mijozning haqiqiy qarzi: (Jami Nasiya) - (Jami To'lov)
        """
        debts = self.debt_set.filter(status='confirmed', transaction_type='debt').aggregate(sum=Sum('amount_uzs'))[
                    'sum'] or 0
        payments = \
        self.debt_set.filter(status='confirmed', transaction_type='payment').aggregate(sum=Sum('amount_uzs'))[
            'sum'] or 0

        return debts - payments


# --- 4. RUXSAT ETILGAN ADMINLAR (WHITELIST) ---
class AllowedAdmin(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, null=True, blank=True)  # <-- Qaysi do'konniki?
    name = models.CharField(max_length=100, verbose_name="Xodim Ismi")
    telegram_id = models.BigIntegerField(unique=True, verbose_name="Telegram ID")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.telegram_id})"


# --- 5. QARZ VA TO'LOVLAR ---
class Debt(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='debts', null=True, blank=True)  # <-- Do'kon

    STATUS_CHOICES = (
        ('pending', 'Kutilmoqda'),
        ('confirmed', 'Tasdiqlandi'),
        ('rejected', 'Rad etildi'),
    )
    TYPE_CHOICES = (
        ('debt', 'Nasiya (Qarz)'),
        ('payment', 'To\'lov (Qaytarish)'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('cash', 'Naqd'),
        ('card', 'Plastik (Humo/Uzcard)'),
        ('click', 'Click / Payme'),
        ('transfer', "O'tkazma (Perechislenie)"),
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        null=True,
        blank=True,
        verbose_name="To'lov turi"
    )
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='debt')
    # Naqd savdo (sotuv + darhol to'lov juftligi). Nasiya statistikasiga qo'shilmaydi.
    is_cash_sale = models.BooleanField(default=False, verbose_name="Naqd savdo")
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    amount_uzs = models.DecimalField(max_digits=15, decimal_places=0, default=0, verbose_name="So'm qismi")
    amount_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Dollar qismi")

    items = models.TextField(verbose_name="Tovarlar ro'yxati")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    # Mijoz rad etganda yozgan sababi va do'kon qayta yuborganda qo'shgan izohi
    reject_reason = models.CharField(max_length=200, blank=True, default='', verbose_name="Rad etish sababi")
    shop_note = models.CharField(max_length=200, blank=True, default='', verbose_name="Do'kon izohi")
    # To'lov muddati (faqat nasiya uchun). due_stage: 1 - "ertaga" eslatmasi, 2 - "bugun" eslatmasi yuborilgan
    due_date = models.DateField(null=True, blank=True, verbose_name="To'lov muddati")
    due_stage = models.PositiveSmallIntegerField(default=0, editable=False)
    # Qog'oz daftardan ko'chirilgan boshlang'ich qarz: hisobotlarda yangi savdo sifatida hisoblanmaydi.
    # opening_ack - mijoz botga ulanganda uni tasdiqlaganmi
    is_opening = models.BooleanField(default=False, verbose_name="Daftardan ko'chirilgan")
    opening_ack = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)

    def __str__(self):
        return f"{self.amount_uzs} so'm | $ {self.amount_usd} - {self.client.full_name}"


# --- 6. SOZLAMALAR ---
class Settings(models.Model):
    # Har bir do'konning o'z sozlamasi bo'ladi
    shop = models.OneToOneField(Shop, on_delete=models.CASCADE, related_name='settings', null=True, blank=True)
    usd_rate = models.DecimalField(max_digits=10, decimal_places=2, default=12800, verbose_name="Dollar kursi")

    # Qarzdorlarga avtomatik eslatma (manage.py send_reminders - cron orqali har kuni)
    reminder_enabled = models.BooleanField(default=False, verbose_name="Avtomatik eslatma")
    reminder_days = models.PositiveSmallIntegerField(default=7, verbose_name="Necha kunda bir")
    reminder_min_debt = models.DecimalField(max_digits=15, decimal_places=0, default=0,
                                            verbose_name="Eng kam qarz (so'm)")

    # get_solo va save metodlarini o'chiramiz, chunki endi bu Singleton emas.
    def __str__(self):
        return f"{self.shop.name} Sozlamalari"

# --- 7. XODIMNI TAKLIF QILISH ---
class StaffInvite(models.Model):
    """
    Xodimni Telegram ID so'ramasdan qo'shish: rahbar havola yuboradi,
    xodim botda /start bosganda o'zi ro'yxatga olinadi.
    """
    VALID_DAYS = 7

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='staff_invites')
    name = models.CharField(max_length=100, verbose_name="Xodim ismi")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.shop.name})"

    @property
    def is_valid(self):
        return self.used_at is None and timezone.now() - self.created_at < timedelta(days=self.VALID_DAYS)


class BotSignup(models.Model):
    """Botdagi ro'yxatdan o'tish jarayoni: qaysi qadamda turgani va kiritilgan javoblar."""
    STEP_CHOICES = (
        ('name', "Do'kon nomi kutilmoqda"),
        ('category', "Do'kon turi kutilmoqda"),
    )
    telegram_id = models.BigIntegerField(unique=True)
    step = models.CharField(max_length=20, choices=STEP_CHOICES, default='name')
    shop_name = models.CharField(max_length=100, blank=True, default='')
    first_name = models.CharField(max_length=150, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.telegram_id}: {self.get_step_display()}"
