from django.urls import path

from . import views

urlpatterns = [
    path("payme/", views.PaymeView.as_view()),
    path("click/prepare/", views.ClickPrepareView.as_view()),
    path("click/complete/", views.ClickCompleteView.as_view()),
]
