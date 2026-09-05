from django.urls import path
from .views import validate_coupon, my_coupons

urlpatterns = [
    path('coupons/validate/', validate_coupon, name='coupon_validate'),
    path('coupons/mine/', my_coupons, name='coupon_mine'),
]
