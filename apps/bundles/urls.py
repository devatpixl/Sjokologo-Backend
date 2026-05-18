from django.urls import path
from .views import active_bundles

urlpatterns = [
    path('bundles/active/', active_bundles, name='active_bundles'),
]
