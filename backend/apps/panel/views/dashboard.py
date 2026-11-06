from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.catalog.models import Branch, Product, ProductGroup, SyncLog
from apps.delivery.models import Shipment
from apps.orders.models import Order

from .. import analytics
from ..charts import column_chart
from .base import operator_required, render_panel

S = Order.Status


def _last_sync():
    rows = {}
    for kind, label in SyncLog.Kind.choices:
        if kind == SyncLog.Kind.PRODUCTS_FULL:
            continue
        rows[kind] = {
            "label": label,
            "last": SyncLog.objects.filter(kind=kind).first(),
            "last_ok": SyncLog.objects.filter(kind=kind, ok=True).first(),
        }
    return rows


@operator_required
def home(request):
    today = timezone.localdate()
    p_today = analytics.Period(today, today)
    now = timezone.now()
    waiting_long = Order.objects.filter(status=S.PAID, paid_at__lt=now - timedelta(minutes=15))
    days = analytics.by_day(analytics.Period(today - timedelta(days=13), today))
    alerts = {
        "problem": Order.objects.filter(status=S.PROBLEM).count(),
        "waiting_long": waiting_long.count(),
        "refund": Order.objects.filter(payment_status=Order.PaymentStatus.REFUND_REQUIRED).count(),
        "courier_search": Shipment.objects.filter(status__in=(Shipment.Status.CREATED, Shipment.Status.SEARCHING)).count(),
    }
    content = {
        "queue": Product.objects.filter(group__isnull=True, is_active=True).count(),
        "no_photo": ProductGroup.objects.annotate(n=Count("images")).filter(n=0).count(),
        "unpublished": ProductGroup.objects.filter(is_published=False).count(),
        "published": ProductGroup.objects.filter(is_published=True).count(),
        "branches_off": Branch.objects.filter(is_active=True).filter(
            Q(delivery_enabled=False) | Q(lat__isnull=True)).count(),
    }
    pipeline = dict(
        Order.objects.filter(status__in=[S.NEW, S.PAID, S.ASSEMBLING, S.COURIER_SEARCH, S.COURIER_ASSIGNED, S.DELIVERING])
        .values("status").annotate(n=Count("id")).values_list("status", "n")
    )
    return render_panel(
        request, "panel/home.html", "home",
        kpi=analytics.kpis(p_today), alerts=alerts, content=content, sync=_last_sync(),
        pipeline=[(s, S(s).label, pipeline.get(s, 0)) for s in
                  (S.NEW, S.PAID, S.ASSEMBLING, S.COURIER_SEARCH, S.COURIER_ASSIGNED, S.DELIVERING)],
        chart=column_chart(
            [(d["date"].strftime("%d.%m"), d["date"].strftime("%d.%m.%Y"), d["revenue"]) for d in days],
            "Выручка за 14 дней", width=1260,
        ),
        today=today,
    )


def _parse(value, default: date) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@operator_required
def analytics_page(request):
    today = timezone.localdate()
    preset = request.GET.get("preset")
    if preset in ("7", "30", "90"):
        d_from, d_to = today - timedelta(days=int(preset) - 1), today
    elif preset == "month":
        d_from, d_to = today.replace(day=1), today
    else:
        d_to = _parse(request.GET.get("to"), today)
        d_from = _parse(request.GET.get("from"), d_to - timedelta(days=29))
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    d_from = max(d_from, d_to - timedelta(days=366))
    branch = request.GET.get("branch")
    p = analytics.Period(d_from, d_to, int(branch) if branch and branch.isdigit() else None)
    rep = analytics.report(p)

    if request.GET.get("export") == "days":
        return _csv("days", ["date", "created", "orders", "revenue", "avg_check"],
                    [[d["date"], d["created"], d["orders"], d["revenue"], d["avg_check"] or ""] for d in rep["days"]])
    if request.GET.get("export") == "products":
        return _csv("products", ["product_id", "name", "qty", "orders", "revenue"],
                    [[r["product_id"], r["name"], r["qty"], r["orders"], r["revenue"]] for r in analytics.top_products(p, 1000)])

    fmt_day = "%d.%m"
    return render_panel(
        request, "panel/analytics.html", "analytics",
        p=p, prev=p.previous(), rep=rep, branches=Branch.objects.filter(orders__isnull=False).distinct(),
        chart_revenue=column_chart(
            [(d["date"].strftime(fmt_day), d["date"].strftime("%d.%m.%Y"), d["revenue"]) for d in rep["days"]],
            "Выручка по дням"),
        chart_orders=column_chart(
            [(d["date"].strftime(fmt_day), d["date"].strftime("%d.%m.%Y"), d["orders"]) for d in rep["days"]],
            "Заказы по дням", fmt=lambda v: f"{v:.0f}"),
    )


def _csv(name, header, rows):
    import csv

    from django.http import HttpResponse

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="pet24-{name}.csv"'
    resp.write("﻿")  # Excel opens UTF-8 correctly with BOM
    w = csv.writer(resp, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return resp
