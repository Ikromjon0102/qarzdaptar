from django.contrib import admin

from .models import SubscriptionPayment


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'shop', 'provider', 'months', 'amount', 'status', 'created_at', 'paid_at')
    list_filter = ('provider', 'status')
    search_fields = ('shop__name', 'provider_trans_id')
    readonly_fields = [f.name for f in SubscriptionPayment._meta.fields]
