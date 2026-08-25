from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    LoginView, register_view, me_view, my_orders_view, change_password_view,
    guest_checkout_view, promote_view, set_password_view, password_reset_request_view,
)
from .vipps_login import (
    vipps_start_view, vipps_callback_view, vipps_exchange_view,
)
from .loyalty import loyalty_signup_view

urlpatterns = [
    path('auth/token/', LoginView.as_view(), name='token_obtain'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/register/', register_view, name='register'),
    path('auth/set-password/', set_password_view, name='set_password'),
    path('auth/password-reset/', password_reset_request_view, name='password_reset'),
    path('auth/vipps/start/', vipps_start_view, name='vipps_login_start'),
    path('auth/vipps/callback/', vipps_callback_view, name='vipps_login_callback'),
    path('auth/vipps/exchange/', vipps_exchange_view, name='vipps_login_exchange'),
    path('loyalty/signup/', loyalty_signup_view, name='loyalty_signup'),
    path('checkout/guest/', guest_checkout_view, name='guest_checkout'),
    path('users/me/', me_view, name='me'),
    path('users/me/orders/', my_orders_view, name='my_orders'),
    path('users/me/password/', change_password_view, name='change_password'),
    path('users/me/promote/', promote_view, name='promote'),
]
