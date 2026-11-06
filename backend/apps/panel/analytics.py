"""Sales analytics for the panel.

Definitions (shown in the UI as well):
  period            orders created in [date_from, date_to] (local time, Asia/Tashkent)
  realized order    paid (paid_at set) and not canceled — money stays with us
  revenue           Σ order.total of realized orders            (items + delivery)
  items_revenue     Σ order.items_total
  delivery_revenue  Σ order.delivery_price
  courier_cost      Σ shipment.cost of realized orders          (what the courier service charged)
  delivery_margin   delivery_revenue − courier_cost
  avg_check         revenue / realized_orders
  payment_rate      orders with paid_at / created orders
  cancel_rate       canceled orders / created orders
  repeat_share      customers with ≥ 2 realized orders in period / customers with ≥ 1
  timings           medians: assembly = assembled_at − paid_at, delivery = delivered_at − assembled_at
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.delivery.models import Shipment
from apps.orders.models import Order, OrderEvent, OrderItem

ZERO = Decimal("0")


@dataclass
class Period:
    date_from: date
    date_to: date
    branch_id: int | None = None

    @property
    def start(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.date_from, time.min))

    @property
    def end(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.date_to + timedelta(days=1), time.min))

    @property
    def days(self) -> list[date]:
        return [self.date_from + timedelta(days=i) for i in range((self.date_to - self.date_from).days + 1)]

    def previous(self) -> "Period":
        span = (self.date_to - self.date_from).days + 1
        return Period(self.date_from - timedelta(days=span), self.date_from - timedelta(days=1), self.branch_id)


def _div(a, b):
    return (Decimal(a) / Decimal(b)) if b else None


def _median_td(values: list[timedelta]) -> timedelta | None:
    values = [v for v in values if v is not None and v >= timedelta(0)]
    if not values:
        return None
    return timedelta(seconds=median(v.total_seconds() for v in values))


def orders_qs(p: Period):
    qs = Order.objects.filter(created_at__gte=p.start, created_at__lt=p.end)
    return qs.filter(branch_id=p.branch_id) if p.branch_id else qs


def realized(qs):
    return qs.filter(paid_at__isnull=False).exclude(status=Order.Status.CANCELED)


def kpis(p: Period) -> dict:
    created = orders_qs(p)
    real = realized(created)
    agg = real.aggregate(
        n=Count("id"), revenue=Sum("total"), items=Sum("items_total"), delivery=Sum("delivery_price"),
    )
    n_created = created.count()
    n_paid = created.filter(paid_at__isnull=False).count()
    n_canceled = created.filter(status=Order.Status.CANCELED).count()
    courier_cost = Shipment.objects.filter(order__in=real, cost__isnull=False).aggregate(s=Sum("cost"))["s"] or ZERO
    revenue, delivery = agg["revenue"] or ZERO, agg["delivery"] or ZERO

    per_user = Counter(real.values_list("user_id", flat=True))
    customers = len(per_user)
    repeat = sum(1 for c in per_user.values() if c >= 2)
    first_orders = (
        Order.objects.filter(user_id__in=per_user.keys(), paid_at__isnull=False)
        .exclude(status=Order.Status.CANCELED)
        .values("user_id").annotate(first=Count("id", filter=Q(created_at__lt=p.start)))
    )
    new_customers = sum(1 for r in first_orders if r["first"] == 0)

    timing = list(real.values_list("paid_at", "assembled_at", "delivered_at"))
    return {
        "created": n_created,
        "realized": agg["n"],
        "revenue": revenue,
        "items_revenue": agg["items"] or ZERO,
        "delivery_revenue": delivery,
        "courier_cost": courier_cost,
        "delivery_margin": delivery - courier_cost,
        "avg_check": _div(revenue, agg["n"]),
        "payment_rate": _div(n_paid, n_created),
        "cancel_rate": _div(n_canceled, n_created),
        "canceled": n_canceled,
        "customers": customers,
        "new_customers": new_customers,
        "repeat_share": _div(repeat, customers),
        "assembly_median": _median_td([a - pd for pd, a, _ in timing if pd and a]),
        "delivery_median": _median_td([d - a for _, a, d in timing if a and d]),
        "total_median": _median_td([d - pd for pd, _, d in timing if pd and d]),
    }


def delta(cur, prev):
    """Relative change cur vs prev, None when not comparable."""
    if cur is None or prev in (None, 0):
        return None
    return (Decimal(cur) - Decimal(prev)) / Decimal(prev)


def by_day(p: Period) -> list[dict]:
    created = orders_qs(p)
    rows = {
        r["d"]: r for r in realized(created).annotate(d=TruncDate("created_at"))
        .values("d").annotate(orders=Count("id"), revenue=Sum("total"))
    }
    made = dict(created.annotate(d=TruncDate("created_at")).values("d").annotate(n=Count("id")).values_list("d", "n"))
    out = []
    for d in p.days:
        r = rows.get(d, {})
        orders, revenue = r.get("orders", 0), r.get("revenue") or ZERO
        out.append({"date": d, "created": made.get(d, 0), "orders": orders, "revenue": revenue,
                    "avg_check": _div(revenue, orders)})
    return out


def by_branch(p: Period) -> list[dict]:
    created = orders_qs(p)
    real = realized(created)
    base = {
        r["branch_id"]: r for r in real.values("branch_id", "branch__name")
        .annotate(orders=Count("id"), revenue=Sum("total"))
    }
    canceled = dict(created.filter(status=Order.Status.CANCELED).values("branch_id")
                    .annotate(n=Count("id")).values_list("branch_id", "n"))
    problems = dict(
        OrderEvent.objects.filter(order__in=created, to_status=Order.Status.PROBLEM)
        .values("order__branch_id").annotate(n=Count("order_id", distinct=True))
        .values_list("order__branch_id", "n")
    )
    assembly = defaultdict(list)
    for bid, paid, assembled in real.filter(assembled_at__isnull=False).values_list("branch_id", "paid_at", "assembled_at"):
        assembly[bid].append(assembled - paid)
    total = sum((r["revenue"] or ZERO for r in base.values()), ZERO)
    rows = [
        {
            "branch_id": bid, "name": r["branch__name"], "orders": r["orders"], "revenue": r["revenue"] or ZERO,
            "share": _div(r["revenue"] or ZERO, total) or ZERO, "avg_check": _div(r["revenue"] or ZERO, r["orders"]),
            "assembly_median": _median_td(assembly[bid]), "canceled": canceled.get(bid, 0),
            "problems": problems.get(bid, 0),
        }
        for bid, r in base.items()
    ]
    return sorted(rows, key=lambda r: r["revenue"], reverse=True)


def top_products(p: Period, limit: int = 20) -> list[dict]:
    rows = list(
        OrderItem.objects.filter(order__in=realized(orders_qs(p)))
        .values("product_id", "name")
        .annotate(qty=Sum("quantity"), revenue=Sum(F("price") * F("quantity")), orders=Count("order_id", distinct=True))
        .order_by("-revenue")[:limit]
    )
    top = rows[0]["revenue"] if rows else None
    for r in rows:
        r["bar"] = _div(r["revenue"], top) or ZERO
    return rows


def by_payment(p: Period) -> list[dict]:
    real = realized(orders_qs(p))
    total = real.aggregate(s=Sum("total"))["s"] or ZERO
    labels = dict(Order.PaymentMethod.choices)
    return [
        {"method": labels.get(r["payment_method"], r["payment_method"]), "orders": r["orders"],
         "revenue": r["revenue"], "share": _div(r["revenue"], total)}
        for r in real.values("payment_method").annotate(orders=Count("id"), revenue=Sum("total")).order_by("-revenue")
    ]


def by_zone(p: Period) -> list[dict]:
    real = realized(orders_qs(p))
    cost = dict(
        Shipment.objects.filter(order__in=real, cost__isnull=False).values("order__zone_id")
        .annotate(s=Sum("cost")).values_list("order__zone_id", "s")
    )
    rows = []
    for r in real.values("zone_id", "zone__name").annotate(
        orders=Count("id"), delivery=Sum("delivery_price"),
        free=Count("id", filter=Q(delivery_price=0)),
    ).order_by("-orders"):
        c = cost.get(r["zone_id"]) or ZERO
        rows.append({
            "name": r["zone__name"] or "—", "orders": r["orders"], "delivery_revenue": r["delivery"] or ZERO,
            "courier_cost": c, "margin": (r["delivery"] or ZERO) - c,
            "avg_cost": _div(c, r["orders"]), "free_share": _div(r["free"], r["orders"]),
        })
    return rows


def report(p: Period) -> dict:
    cur, prev = kpis(p), kpis(p.previous())
    return {
        "kpi": cur,
        "prev": prev,
        "delta": {k: delta(cur[k], prev[k]) for k in ("revenue", "realized", "avg_check", "customers")},
        "days": by_day(p),
        "branches": by_branch(p),
        "products": top_products(p),
        "payments": by_payment(p),
        "zones": by_zone(p),
    }
