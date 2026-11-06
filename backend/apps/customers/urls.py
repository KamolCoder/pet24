from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

router = DefaultRouter()
router.register("pets", views.PetViewSet, basename="pet")
router.register("addresses", views.AddressViewSet, basename="address")

urlpatterns = [
    path("otp/request/", views.OtpRequestView.as_view()),
    path("otp/verify/", views.OtpVerifyView.as_view()),
    path("token/refresh/", TokenRefreshView.as_view()),
    path("me/", views.MeView.as_view()),
] + router.urls
