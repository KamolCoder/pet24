import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Shipment
from .providers import ProviderError, get_provider

log = logging.getLogger(__name__)


def request_courier(order) -> Shipment:
    """Create a courier job for an assembled order (idempotent while one is active)."""
    current = order.shipments.filter(status__in=Shipment.ACTIVE).first()
    if current:
        return current
    shipment = Shipment.objects.create(order=order, provider=settings.COURIER_PROVIDER)
    try:
        get_provider(shipment.provider).create(shipment)
    except ProviderError as e:
        log.error("courier request for order %s failed: %s", order.number, e)
        shipment.status = Shipment.Status.FAILED
        shipment.error = str(e)
        shipment.save()
    sync_order(shipment)
    return shipment


def refresh_shipment(shipment: Shipment) -> None:
    try:
        get_provider(shipment.provider).refresh(shipment)
    except ProviderError as e:
        log.warning("refresh %s: %s", shipment, e)
        return
    sync_order(shipment)


def cancel_shipment(shipment: Shipment) -> None:
    try:
        get_provider(shipment.provider).cancel(shipment)
    except ProviderError as e:
        shipment.error = f"cancel: {e}"
        shipment.save(update_fields=["error", "updated_at"])
        log.error("cancel %s: %s", shipment, e)


def sync_order(shipment: Shipment) -> None:
    """Move the order along with its courier job."""
    from apps.orders.models import Order

    S = Order.Status
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=shipment.order_id)
        if order.status in (S.CANCELED, S.DELIVERED):
            return
        target = {
            Shipment.Status.ASSIGNED: S.COURIER_ASSIGNED,
            Shipment.Status.PICKED_UP: S.DELIVERING,
            Shipment.Status.DELIVERED: S.DELIVERED,
            Shipment.Status.FAILED: S.PROBLEM,
        }.get(shipment.status)
        if target and target != order.status and order.can_move_to(target):
            note = f"курьер: {shipment.get_status_display()}"
            if shipment.status == Shipment.Status.FAILED:
                note += f" ({shipment.raw_status or shipment.error[:200]})"
            order.set_status(target, note=note)


def check_search_timeouts() -> int:
    """Courier not found in time -> escalate to the operator (job stays active, provider may still find one)."""
    from apps.orders.models import Order

    limit = timezone.now() - timedelta(minutes=settings.COURIER_SEARCH_TIMEOUT_MIN)
    n = 0
    for s in Shipment.objects.filter(
        status__in=(Shipment.Status.CREATED, Shipment.Status.SEARCHING), created_at__lt=limit,
        order__status=Order.Status.COURIER_SEARCH,
    ).select_related("order"):
        s.order.set_status(Order.Status.PROBLEM, note=f"курьер не найден за {settings.COURIER_SEARCH_TIMEOUT_MIN} мин")
        n += 1
    return n
