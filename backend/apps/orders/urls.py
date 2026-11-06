from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("", views.OrderViewSet, basename="order")

urlpatterns = [path("quote/", views.QuoteView.as_view())] + router.urls
