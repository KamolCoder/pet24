from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Order


@shared_task
def expire_unpaid_orders():
    """Release reservations of orders that were not paid in time."""
    from apps.payments.models import PaymeTransaction

    limit = timezone.now() - timedelta(minutes=settings.ORDER_PAYMENT_TIMEOUT_MIN)
    n = 0
    for order in Order.objects.filter(status=Order.Status.NEW, created_at__lt=limit):
        # Payme may hold a created (not yet performed) transaction: don't cancel under it
        if PaymeTransaction.objects.filter(order=order, state=PaymeTransaction.State.CREATED).exists():
            continue
        order.set_status(Order.Status.CANCELED, note="не оплачен вовремя")
        n += 1
    return n
