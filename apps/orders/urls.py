from django.urls import path
from .views import create_order, order_detail

urlpatterns = [
    path('orders/', create_order, name='create_order'),
    path('orders/<str:order_number>/', order_detail, name='order_detail'),
]
