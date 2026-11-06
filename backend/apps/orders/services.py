import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.catalog.models import Branch, Product, Stock
from apps.catalog.stockapi import StockApiError
from apps.catalog.sync import refresh_stock
from apps.delivery.geo import haversine_km
from apps.delivery.models import DeliveryZone

from .models import Order, OrderItem

log = logging.getLogger(__name__)


class OrderError(Exception):
    def __init__(self, message, code="invalid", extra=None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


@dataclass
class Line:
    product: Product
    quantity: int


@dataclass
class Quote:
    zone: DeliveryZone
    branch: Branch
    lines: list[Line]
    items_total: Decimal
    delivery_price: Decimal
    missing: list[dict] = field(default_factory=list)  # [{product_id, requested, available}]

    @property
    def total(self) -> Decimal:
        return self.items_total + self.delivery_price

    @property
    def min_order_ok(self) -> bool:
        return self.items_total >= self.zone.min_order


def load_lines(raw: list[dict]) -> list[Line]:
    """[{product_id, quantity}] -> merged Lines of sellable products."""
    qty = defaultdict(int)
    for r in raw:
        qty[int(r["product_id"])] += int(r["quantity"])
    products = {p.id: p for p in Product.objects.sellable().select_related("group").filter(id__in=qty)}
    unknown = [pid for pid in qty if pid not in products]
    if unknown:
        raise OrderError("Некоторые товары больше не продаются", "unavailable_products", {"product_ids": unknown})
    return [Line(products[pid], q) for pid, q in qty.items() if q > 0]


def available(product_ids, branch_ids) -> dict[tuple[int, int], Decimal]:
    """(product_id, branch_id) -> real stock from stockapi minus our active reservations."""
    stock = {
        (s["product_id"], s["branch_id"]): s["real_quantity"]
        for s in Stock.objects.filter(product_id__in=product_ids, branch_id__in=branch_ids)
        .values("product_id", "branch_id", "real_quantity")
    }
    reserved = (
        OrderItem.objects.filter(product_id__in=product_ids, order__branch_id__in=branch_ids)
        .filter(Order.reserving_q("order__"))
        .values("product_id", "order__branch_id")
        .annotate(q=Sum("quantity"))
    )
    for r in reserved:
        key = (r["product_id"], r["order__branch_id"])
        stock[key] = stock.get(key, Decimal("0")) - r["q"]
    return stock


def pick_branch(lat, lng, zone: DeliveryZone, lines: list[Line]) -> tuple[Branch, list[dict]]:
    """Nearest delivery branch that has every line in stock. If none has everything, the nearest one with
    the best coverage is returned together with what is missing."""
    branches = [b for b in Branch.objects.filter(is_active=True, delivery_enabled=True) if b.can_deliver]
    branches = sorted(
        ((haversine_km(lat, lng, b.lat, b.lng), b) for b in branches), key=lambda t: t[0],
    )
    branches = [b for d, b in branches if d <= float(zone.max_branch_km)]
    if not branches:
        raise OrderError("Нет филиала, который доставляет по этому адресу", "no_branch")
    avail = available([ln.product.id for ln in lines], [b.id for b in branches])
    best, best_missing = None, None
    for b in branches:
        missing = []
        for ln in lines:
            have = avail.get((ln.product.id, b.id), Decimal("0"))
            if have < ln.quantity:
                missing.append({"product_id": ln.product.id, "requested": ln.quantity, "available": max(int(have), 0)})
        if not missing:
            return b, []
        if best is None or len(missing) < len(best_missing):
            best, best_missing = b, missing
    return best, best_missing


def make_quote(raw_items: list[dict], lat, lng, live: bool = False) -> Quote:
    lines = load_lines(raw_items)
    if not lines:
        raise OrderError("Корзина пуста", "empty_cart")
    zone = DeliveryZone.find(lat, lng)
    if zone is None:
        raise OrderError("Мы пока не доставляем по этому адресу", "out_of_zone")
    if live:
        try:
            refresh_stock([ln.product.external_id for ln in lines])
            for ln in lines:
                ln.product.refresh_from_db(fields=["price", "is_active"])
        except StockApiError as e:  # cached stock is still a reasonable answer
            log.warning("live stock refresh failed: %s", e)
    branch, missing = pick_branch(lat, lng, zone, lines)
    items_total = sum((ln.product.price * ln.quantity for ln in lines), Decimal("0"))
    return Quote(zone, branch, lines, items_total, zone.delivery_price(items_total), missing)


def create_order(user, raw_items: list[dict], address: dict, payment_method: str, comment: str = "") -> Order:
    quote = make_quote(raw_items, address["lat"], address["lng"], live=True)
    if quote.missing:
        raise OrderError("Не все товары есть в наличии", "out_of_stock", {"missing": quote.missing})
    if not quote.min_order_ok:
        raise OrderError(f"Минимальная сумма заказа {quote.zone.min_order:.0f} сум", "min_order")
    if any(not ln.product.is_active or ln.product.price <= 0 for ln in quote.lines):
        raise OrderError("Некоторые товары больше не продаются", "unavailable_products")

    with transaction.atomic():
        # serialize order creation per branch so two customers cannot reserve the same last item (PostgreSQL)
        Branch.objects.select_for_update().get(pk=quote.branch.pk)
        avail = available([ln.product.id for ln in quote.lines], [quote.branch.id])
        short = [
            {"product_id": ln.product.id, "requested": ln.quantity,
             "available": max(int(avail.get((ln.product.id, quote.branch.id), 0)), 0)}
            for ln in quote.lines if avail.get((ln.product.id, quote.branch.id), Decimal("0")) < ln.quantity
        ]
        if short:
            raise OrderError("Не все товары есть в наличии", "out_of_stock", {"missing": short})
        order = Order.objects.create(
            user=user,
            branch=quote.branch,
            zone=quote.zone,
            payment_method=payment_method,
            items_total=quote.items_total,
            delivery_price=quote.delivery_price,
            total=quote.total,
            customer_name=user.full_name,
            customer_phone=user.phone,
            comment=comment,
            **{k: address.get(k, "") for k in ("address", "entrance", "floor", "apartment")},
            lat=address["lat"],
            lng=address["lng"],
            address_comment=address.get("comment", ""),
        )
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order, product=ln.product, external_id=ln.product.external_id,
                name=ln.product.display_name, barcode=ln.product.barcode,
                price=ln.product.price, quantity=ln.quantity,
            )
            for ln in quote.lines
        ])
    return order


def mark_paid(order: Order) -> None:
    """Called by payment providers when money is captured."""
    order.payment_status = Order.PaymentStatus.PAID
    if order.status == Order.Status.NEW:
        order.set_status(Order.Status.PAID, note="оплата получена")
    elif order.status == Order.Status.CANCELED:
        # paid after auto-cancel: keep it canceled, money must go back
        order.payment_status = Order.PaymentStatus.REFUND_REQUIRED
        order.save(update_fields=["payment_status"])
    else:
        order.save(update_fields=["payment_status"])


def start_assembly(order: Order, user) -> None:
    order.picker = user
    order.set_status(Order.Status.ASSEMBLING, by=user)


def finish_assembly(order: Order, user) -> None:
    """Picker confirms all goods collected and the receipt is printed at the till -> courier is requested."""
    from apps.delivery.tasks import request_courier

    order.set_status(Order.Status.COURIER_SEARCH, by=user, note="собрано, чек пробит")
    transaction.on_commit(lambda: request_courier.delay(order.pk))


def report_problem(order: Order, user, note: str) -> None:
    order.set_status(Order.Status.PROBLEM, by=user, note=note or "проблема при сборке")


def cancel_order(order: Order, user, reason: str) -> None:
    order.set_status(Order.Status.CANCELED, by=user, note=reason)
    shipment = order.active_shipment
    if shipment and shipment.is_active:
        from apps.delivery.services import cancel_shipment

        cancel_shipment(shipment)
