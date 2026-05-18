from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.users.admin_views import admin_stats, admin_user_list, admin_user_detail
from apps.products.admin_views import admin_product_list, admin_product_detail, admin_truffle_list, admin_truffle_detail
from apps.orders.admin_views import admin_order_list, admin_order_detail
from apps.utils.admin_views import admin_waitlist, admin_waitlist_detail, admin_contact_list, admin_contact_detail
from apps.coupons.admin_views import admin_coupon_list, admin_coupon_detail
from apps.bundles.admin_views import admin_bundle_list, admin_bundle_detail

admin_patterns = [
    path('stats/', admin_stats, name='admin_stats'),
    path('products/', admin_product_list, name='admin_product_list'),
    path('products/<int:pk>/', admin_product_detail, name='admin_product_detail'),
    path('truffles/', admin_truffle_list, name='admin_truffle_list'),
    path('truffles/<str:pk>/', admin_truffle_detail, name='admin_truffle_detail'),
    path('orders/', admin_order_list, name='admin_order_list'),
    path('orders/<str:order_number>/', admin_order_detail, name='admin_order_detail'),
    path('users/', admin_user_list, name='admin_user_list'),
    path('users/<str:pk>/', admin_user_detail, name='admin_user_detail'),
    path('waitlist/', admin_waitlist, name='admin_waitlist'),
    path('waitlist/<int:pk>/', admin_waitlist_detail, name='admin_waitlist_detail'),
    path('contact/', admin_contact_list, name='admin_contact_list'),
    path('contact/<int:pk>/', admin_contact_detail, name='admin_contact_detail'),
    path('coupons/', admin_coupon_list, name='admin_coupon_list'),
    path('coupons/<int:pk>/', admin_coupon_detail, name='admin_coupon_detail'),
    path('bundles/', admin_bundle_list, name='admin_bundle_list'),
    path('bundles/<int:pk>/', admin_bundle_detail, name='admin_bundle_detail'),
]

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/', include('apps.users.urls')),
    path('api/', include('apps.products.urls')),
    path('api/', include('apps.orders.urls')),
    path('api/', include('apps.utils.urls')),
    path('api/', include('apps.payments_vipps.urls')),
    path('api/', include('apps.coupons.urls')),
    path('api/', include('apps.bundles.urls')),
    path('api/admin/', include(admin_patterns)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
