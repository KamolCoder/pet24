from functools import wraps

from django.contrib.auth import views as auth_views
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.orders.staff_views import PhoneAuthForm


def is_operator(user) -> bool:
    return user.is_authenticated and user.is_active and (user.is_superuser or user.role == user.Role.OPERATOR)


def operator_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/panel/login/?next={request.path}")
        if not is_operator(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


class PanelLogin(auth_views.LoginView):
    template_name = "panel/login.html"
    authentication_form = PhoneAuthForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return "/panel/"


def page(request, qs, per_page=50):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def render_panel(request, template, active, **ctx):
    return render(request, template, {"active": active, **ctx})
