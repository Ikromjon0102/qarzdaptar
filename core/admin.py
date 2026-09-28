from django.conf import settings
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
admin.site.register(Shop)



