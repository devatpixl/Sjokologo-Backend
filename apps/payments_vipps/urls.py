from django.urls import path

from .views import create_payment_view, status_view, webhook_view

urlpatterns = [
    path('checkout/vipps/create/', create_payment_view, name='vipps_create_payment'),
    path('checkout/vipps/status/', status_view, name='vipps_payment_status'),
    path('webhooks/vipps/', webhook_view, name='vipps_webhook'),
]
