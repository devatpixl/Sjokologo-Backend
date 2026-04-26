from django.urls import path
from .views import join_waitlist, contact_form, article_list, article_detail, article_slugs

urlpatterns = [
    path('waitlist/', join_waitlist, name='waitlist'),
    path('contact/', contact_form, name='contact'),
    path('articles/', article_list, name='article_list'),
    path('articles/slugs/', article_slugs, name='article_slugs'),
    path('articles/<slug:slug>/', article_detail, name='article_detail'),
]
