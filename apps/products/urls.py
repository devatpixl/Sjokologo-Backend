from django.urls import path
from .views import product_list, product_detail, product_slugs, truffle_list

urlpatterns = [
    path('products/', product_list, name='product_list'),
    path('products/slugs/', product_slugs, name='product_slugs'),
    path('products/<slug:slug>/', product_detail, name='product_detail'),
    path('truffles/', truffle_list, name='truffle_list'),
]
