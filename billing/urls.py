from django.urls import path

from . import views

urlpatterns = [
    # /pricing/ ostida - obunasi tugagan foydalanuvchi ham kira oladi (SubscriptionMiddleware)
    path('pricing/pay/', views.start_payment, name='start_payment'),
    # To'lov tizimlari chaqiradigan manzillar (kabinetlarida shu URL larni ko'rsating)
    path('billing/payme/', views.payme_endpoint, name='payme_endpoint'),
    path('billing/click/', views.click_endpoint, name='click_endpoint'),
]
