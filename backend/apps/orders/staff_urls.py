from django.contrib.auth import views as auth_views
from django.urls import path

from . import staff_views

app_name = "staff"

urlpatterns = [
    path("login/", staff_views.StaffLogin.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="staff:login"), name="logout"),
    path("", staff_views.board, name="board"),
    path("orders/<int:pk>/", staff_views.order_detail, name="order"),
    path("orders/<int:pk>/action/", staff_views.order_action, name="action"),
]
