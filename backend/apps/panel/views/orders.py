from datetime import date

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.catalog.models import Branch
from apps.customers.models import User
from apps.delivery.models import Shipment
from apps.delivery.tasks import request_courier
from apps.orders import services
from apps.orders.models import Order

from .base import operator_required, page, render_panel
from .dashboard import _csv

S = Order.Status


def filtered_orders(request):
    g = request.GET
    qs = Order.objects.select_related("branch", "zone").annotate(n_items=Count("items"))
    if g.get("status"):
        qs = qs.filter(status=g["status"])
    if g.get("payment_status"):
        qs = qs.filter(payment_status=g["payment_status"])
    if g.get("payment_method"):
        qs = qs.filter(payment_method=g["payment_method"])
    if g.get("branch", "").isdigit():
        qs = qs.filter(branch_id=g["branch"])
    for key, lookup in (("from", "created_at__date__gte"), ("to", "created_at__date__lte")):
        try:
            qs = qs.filter(**{lookup: date.fromisoformat(g.get(key, ""))})
        except ValueError:
            pass
    if q := g.get("q", "").strip():
        digits = "".join(c for c in q if c.isdigit())
        cond = Q(number=q.zfill(6)) | Q(customer_name__icontains=q) | Q(address__icontains=q)
        if len(digits) >= 4:
            cond |= Q(customer_phone__contains=digits)
        qs = qs.filter(cond)
    return qs


@operator_required
def orders(request):
    qs = filtered_orders(request)
    if request.GET.get("export") == "csv":
        rows = [[o.number, o.created_at.strftime("%Y-%m-%d %H:%M"), o.branch.name, o.get_status_display(),
                 o.payment_method, o.get_payment_status_display(), o.items_total, o.delivery_price, o.total,
                 o.customer_phone, o.zone.name if o.zone else ""] for o in qs.order_by("created_at")[:50000]]
        return _csv("orders", ["number", "created", "branch", "status", "payment", "payment_status",
                               "items_total", "delivery", "total", "phone", "zone"], rows)
    totals = qs.aggregate(n=Count("id"), s=Sum("total"))
    return render_panel(
        request, "panel/orders.html", "orders",
        page=page(request, qs.order_by("-created_at")), totals=totals,
        statuses=S.choices, payment_statuses=Order.PaymentStatus.choices,
        payment_methods=Order.PaymentMethod.choices, branches=Branch.objects.all(),
    )


@operator_required
def order(request, pk):
    o = get_object_or_404(
        Order.objects.select_related("branch", "zone", "user", "picker").prefetch_related("items", "events__user"),
        pk=pk,
    )
    return render_panel(
        request, "panel/order.html", "orders", o=o, S=S,
        shipments=Shipment.objects.filter(order=o),
        payme=o.payme_transactions.all(), click=o.click_transactions.all(),
    )


@operator_required
@require_POST
def order_action(request, pk):
    action, note, user = request.POST.get("action"), request.POST.get("note", "").strip(), request.user
    with transaction.atomic():
        o = get_object_or_404(Order.objects.select_for_update(), pk=pk)
        try:
            if action == "cancel":
                services.cancel_order(o, user, note or "отменён оператором")
            elif action == "problem":
                services.report_problem(o, user, note or "отмечено оператором")
            elif action == "resume" and o.status == S.PROBLEM and not o.assembled_at:
                o.set_status(S.ASSEMBLING if o.assembling_at else S.PAID, by=user, note=note or "проблема решена")
            elif action == "retry_courier" and o.status == S.PROBLEM and o.assembled_at:
                o.set_status(S.COURIER_SEARCH, by=user, note="повторный вызов курьера")
                transaction.on_commit(lambda: request_courier.delay(o.pk))
            elif action == "delivered":
                o.set_status(S.DELIVERED, by=user, note=note or "отмечен вручную")
            elif action == "refunded" and o.payment_status == Order.PaymentStatus.REFUND_REQUIRED:
                o.payment_status = Order.PaymentStatus.REFUNDED
                o.save(update_fields=["payment_status"])
                o.events.create(from_status=o.status, to_status=o.status, user=user, note=f"возврат сделан. {note}"[:500])
            else:
                messages.error(request, "Действие недоступно для этого заказа")
                return redirect("panel:order", pk=pk)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect("panel:order", pk=pk)
    messages.success(request, f"Заказ {o.number}: {o.get_status_display()}, оплата: {o.get_payment_status_display()}")
    return redirect("panel:order", pk=pk)


@operator_required
def shipments(request):
    qs = Shipment.objects.select_related("order", "order__branch")
    st = request.GET.get("status")
    if st == "searching":
        qs = qs.filter(status__in=(Shipment.Status.CREATED, Shipment.Status.SEARCHING))
    elif st:
        qs = qs.filter(status=st)
    return render_panel(request, "panel/shipments.html", "delivery", page=page(request, qs), statuses=Shipment.Status.choices)


@operator_required
def customers(request):
    qs = User.objects.filter(role=User.Role.CUSTOMER).annotate(
        n_orders=Count("orders", filter=Q(orders__paid_at__isnull=False) & ~Q(orders__status=S.CANCELED)),
        spent=Sum("orders__total", filter=Q(orders__paid_at__isnull=False) & ~Q(orders__status=S.CANCELED)),
    )
    if q := request.GET.get("q", "").strip():
        digits = "".join(c for c in q if c.isdigit())
        cond = Q(first_name__icontains=q) | Q(last_name__icontains=q)
        if digits:
            cond |= Q(phone__contains=digits)
        qs = qs.filter(cond)
    sort = {"spent": "-spent", "orders": "-n_orders"}.get(request.GET.get("sort"), "-date_joined")
    return render_panel(request, "panel/customers.html", "customers", page=page(request, qs.order_by(sort, "-id")))


@operator_required
def customer(request, pk):
    c = get_object_or_404(User, pk=pk, role=User.Role.CUSTOMER)
    if request.method == "POST" and request.POST.get("action") == "toggle":
        c.is_active = not c.is_active
        c.save(update_fields=["is_active"])
        messages.success(request, "Клиент разблокирован" if c.is_active else "Клиент заблокирован")
        return redirect("panel:customer", pk=pk)
    orders_qs = c.orders.select_related("branch").order_by("-created_at")
    stats = orders_qs.filter(paid_at__isnull=False).exclude(status=S.CANCELED).aggregate(n=Count("id"), s=Sum("total"))
    return render_panel(
        request, "panel/customer.html", "customers", c=c, orders=orders_qs[:100], stats=stats,
        pets=c.pets.select_related("pet_type"), addresses=c.addresses.all(),
    )
