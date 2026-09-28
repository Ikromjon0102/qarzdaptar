from django.conf import settings
from django.views.static import serve
from django.contrib import admin
from django.urls import path, include, re_path
from core.admin_views import super_dashboard

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('shop/', include('store.urls')), # <--- YANGI
    path('super-control/', super_dashboard, name='super_dashboard'),
]


# Statik fayllarni WhiteNoise middleware beradi (config/settings.py).
# static() yordamchisi faqat DEBUG=True da ishlaydi, shuning uchun media uchun serve() ni to'g'ridan-to'g'ri ulaymiz.
if settings.SERVE_MEDIA:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]