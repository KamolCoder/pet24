"""Web panel for branch pickers and operators (tablet at the branch)."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.catalog.models import Branch
from apps.customers.models import normalize_phone
from apps.delivery.tasks import request_courier

from . import services
from .models import Order

S = Order.Status
BOARD_STATUSES = [S.PAID, S.ASSEMBLING, S.PROBLEM, S.COURIER_SEARCH, S.COURIER_ASSIGNED, S.DELIVERING]


class PhoneAuthForm(AuthenticationForm):
    def clean_username(self):
        try:
            return normalize_phone(self.cleaned_data["username"])
        except ValueError as e:
            raise ValidationError(str(e)) from e


class StaffLogin(auth_views.LoginView):
    template_name = "staff/login.html"
    authentication_form = PhoneAuthForm
    redirect_authenticated_user = True


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect("staff:login")
        if not user.is_branch_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def is_operator(user) -> bool:
    return user.role == user.Role.OPERATOR or user.is_superuser


def visible_orders(user):
    qs = Order.objects.select_related("branch")
    if is_operator(user):
        return qs
    return qs.filter(branch_id=user.branch_id) if user.branch_id else qs.none()


@staff_required
def board(request):
    qs = visible_orders(request.user)
    branch_id = request.GET.get("branch")
    if branch_id and is_operator(request.user):
        qs = qs.filter(branch_id=branch_id)
    today = timezone.localdate()
    orders = qs.filter(
        Q(status__in=BOARD_STATUSES) | Q(status__in=[S.DELIVERED, S.CANCELED], created_at__date=today)
    ).prefetch_related("items").order_by("created_at")
    columns = [(s, S(s).label, [o for o in orders if o.status == s]) for s in BOARD_STATUSES]
    done = [o for o in orders if o.status in (S.DELIVERED, S.CANCELED)]
    return render(request, "staff/board.html", {
        "columns": columns, "done": done, "is_operator": is_operator(request.user),
        "branches": Branch.objects.filter(delivery_enabled=True) if is_operator(request.user) else [],
        "branch_id": branch_id,
    })


@staff_required
def order_detail(request, pk):
    order = get_object_or_404(visible_orders(request.user).prefetch_related("items", "events", "shipments"), pk=pk)
    return render(request, "staff/order.html", {
        "order": order, "is_operator": is_operator(request.user), "S": S, "shipment": order.active_shipment,
    })


@staff_required
@require_POST
def order_action(request, pk):
    with transaction.atomic():
        order = get_object_or_404(visible_orders(request.user).select_for_update(), pk=pk)
        action = request.POST.get("action")
        note = request.POST.get("note", "").strip()
        user = request.user
        try:
            if action == "start" and order.status == S.PAID:
                services.start_assembly(order, user)
            elif action == "assembled" and order.status == S.ASSEMBLING:
                services.finish_assembly(order, user)
            elif action == "problem":
                services.report_problem(order, user, note)
            elif action == "cancel" and is_operator(user):
                services.cancel_order(order, user, note or "отменён оператором")
            elif action == "retry_courier" and is_operator(user) and order.status == S.PROBLEM and order.assembled_at:
                order.set_status(S.COURIER_SEARCH, by=user, note="повторный вызов курьера")
                transaction.on_commit(lambda: request_courier.delay(order.pk))
            elif action == "resume" and is_operator(user) and order.status == S.PROBLEM and not order.assembled_at:
                order.set_status(S.ASSEMBLING if order.assembling_at else S.PAID, by=user, note=note or "проблема решена")
            elif action == "delivered" and is_operator(user):
                order.set_status(S.DELIVERED, by=user, note=note or "отмечен вручную")
            else:
                messages.error(request, "Действие недоступно для этого заказа")
                return redirect("staff:order", pk=pk)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("staff:order", pk=pk)
    messages.success(request, f"Заказ {order.number}: {order.get_status_display()}")
    return redirect("staff:order", pk=pk)
