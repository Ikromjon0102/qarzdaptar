from django.urls import path
from . import views

urlpatterns = [
    path('', views.shop_home, name='shop_home'),
    path('add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/', views.cart_detail, name='cart_detail'),
    path('clear/', views.clear_cart, name='clear_cart'),
    path('decrease/<int:product_id>/', views.decrease_cart, name='decrease_cart'),
    path('checkout/', views.checkout, name='checkout'),
    # Do'kon rahbari uchun
    path('manage/', views.manage_products, name='manage_products'),
    path('manage/new/', views.product_form, name='product_add'),
    path('manage/<int:product_id>/', views.product_form, name='product_edit'),
]