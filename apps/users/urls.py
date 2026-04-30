from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    LoginView, register_view, me_view, my_orders_view, change_password_view,
    guest_checkout_view, promote_view,
)

urlpatterns = [
    path('auth/token/', LoginView.as_view(), name='token_obtain'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/register/', register_view, name='register'),
    path('checkout/guest/', guest_checkout_view, name='guest_checkout'),
    path('users/me/', me_view, name='me'),
    path('users/me/orders/', my_orders_view, name='my_orders'),
    path('users/me/password/', change_password_view, name='change_password'),
    path('users/me/promote/', promote_view, name='promote'),
]
