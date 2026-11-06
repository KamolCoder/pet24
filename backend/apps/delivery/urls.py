from django.urls import path

from . import views

urlpatterns = [
    path("zones/", views.ZoneList.as_view()),
    path("yandex/callback/", views.YandexCallback.as_view()),
]
