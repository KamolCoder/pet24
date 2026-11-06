import base64
from urllib.parse import urlencode

from django.conf import settings


def payment_url(order) -> str:
    """Link the app opens in a browser / webview to pay the order."""
    if order.payment_method == "payme":
        params = f"m={settings.PAYME_MERCHANT_ID};ac.order_id={order.pk};a={order.amount_tiyin};c={settings.PAYMENT_RETURN_URL}"
        return f"{settings.PAYME_CHECKOUT_URL}/{base64.b64encode(params.encode()).decode()}"
    if order.payment_method == "click":
        return "https://my.click.uz/services/pay?" + urlencode({
            "service_id": settings.CLICK_SERVICE_ID,
            "merchant_id": settings.CLICK_MERCHANT_ID,
            "amount": f"{order.total:.2f}",
            "transaction_param": order.pk,
            "return_url": settings.PAYMENT_RETURN_URL,
        })
    raise ValueError(order.payment_method)
