from datetime import timedelta

from django.conf import settings
from django.utils import timezone
# core/admin.py
from django.contrib import admin
from .models import Client, Debt, AllowedAdmin, Shop

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'telegram_status', 'get_invite_link')
    readonly_fields = ('invite_token',) # Tokenni qo'lda o'zgartirib yubormaslik uchun

    def telegram_status(self, obj):
        return "✅ Ulangan" if obj.telegram_id else "❌ Ulanmagan"
    telegram_status.short_description = "Holati"

    def get_invite_link(self, obj):
        return f"https://t.me/{settings.BOT_USERNAME}?start={obj.invite_token}"
    get_invite_link.short_description = "Taklif ssilkas (Copy)"

@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ('client', 'amount_uzs', 'amount_usd', 'status', 'created_at')
    list_filter = ('status', 'created_at')


admin.site.register(AllowedAdmin)
@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'subscription_ends_at', 'days_left')
    search_fields = ('name', 'owner__username')
    actions = ['extend_30_days']

    @admin.action(description="Obunani 30 kunga uzaytirish (to'lov qabul qilindi)")
    def extend_30_days(self, request, queryset):
        now = timezone.now()
        for shop in queryset:
            start = shop.subscription_ends_at if shop.subscription_ends_at and shop.subscription_ends_at > now else now
            shop.subscription_ends_at = start + timedelta(days=30)
            shop.is_active = True
            shop.save(update_fields=['subscription_ends_at', 'is_active'])
        self.message_user(request, f"{queryset.count()} ta do'kon obunasi 30 kunga uzaytirildi.")



