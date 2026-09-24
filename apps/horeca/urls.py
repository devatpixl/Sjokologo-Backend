"""Public HORECA routes, mounted at /api/horeca/ from config/urls.py.

Admin routes are NOT here — this project keeps every admin endpoint in the flat
`admin_patterns` list in config/urls.py, and apps/horeca/admin_views.py follows
that convention rather than starting a second one.
"""
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.horeca_register_view, name='horeca-register'),
    path('me/', views.horeca_me_view, name='horeca-me'),
    path('auth/password-reset/', views.horeca_password_reset_view,
         name='horeca-password-reset'),
    path('auth/set-password/', views.horeca_set_password_view,
         name='horeca-set-password'),

    path('products/', views.horeca_product_list_view, name='horeca-products'),
    path('products/<slug:slug>/', views.horeca_product_detail_view,
         name='horeca-product-detail'),

    path('availability/', views.horeca_availability_view, name='horeca-availability'),

    path('addresses/', views.horeca_address_list_view, name='horeca-addresses'),
    path('addresses/<uuid:pk>/', views.horeca_address_detail_view,
         name='horeca-address-detail'),

    # Literal segments must precede <uuid:pk>, or "logo-file" is read as an id.
    path('logo-file/<str:token>/', views.horeca_logo_token_file_view,
         name='horeca-logo-token-file'),
    path('logos/', views.horeca_logo_list_view, name='horeca-logos'),
    path('logos/<uuid:pk>/', views.horeca_logo_detail_view,
         name='horeca-logo-detail'),
    path('logos/<uuid:pk>/file/', views.horeca_logo_file_view,
         name='horeca-logo-file'),
    path('logos/<uuid:pk>/signed-url/', views.horeca_logo_signed_url_view,
         name='horeca-logo-signed-url'),

    path('members/', views.horeca_member_list_view, name='horeca-members'),
    path('members/<uuid:pk>/', views.horeca_member_detail_view,
         name='horeca-member-detail'),

    path('orders/', views.horeca_order_list_view, name='horeca-orders'),
    path('orders/<uuid:pk>/send/', views.horeca_order_send_view,
         name='horeca-order-send'),
    path('orders/<str:order_number>/', views.horeca_order_detail_view,
         name='horeca-order-detail'),
    path('orders/<str:order_number>/cancel/', views.horeca_order_cancel_view,
         name='horeca-order-cancel'),
    path('orders/<str:order_number>/repeat/', views.horeca_order_repeat_view,
         name='horeca-order-repeat'),
]
