from celery import shared_task

from . import services
from .models import Shipment


@shared_task(autoretry_for=(Exception,), retry_backoff=30, max_retries=5)
def request_courier(order_id):
    from apps.orders.models import Order

    order = Order.objects.select_related("branch").get(pk=order_id)
    if order.status == Order.Status.COURIER_SEARCH:
        services.request_courier(order)


@shared_task
def refresh_shipment(shipment_id):
    shipment = Shipment.objects.filter(pk=shipment_id).first()
    if shipment and shipment.is_active:
        services.refresh_shipment(shipment)


@shared_task
def refresh_active_shipments():
    # safety net for lost callbacks
    for sid in Shipment.objects.filter(status__in=Shipment.ACTIVE).exclude(provider="manual").values_list("id", flat=True):
        refresh_shipment.delay(str(sid))
    services.check_search_timeouts()
