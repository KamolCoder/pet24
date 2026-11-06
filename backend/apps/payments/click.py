"""Click SHOP API (prepare / complete). https://docs.click.uz/click-api-request/"""
import hashlib
import hmac
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction

from apps.orders.models import Order
from apps.orders.services import mark_paid

from .models import ClickTransaction as Tx

OK = 0
SIGN_FAILED = -1
BAD_AMOUNT = -2
BAD_ACTION = -3
ALREADY_PAID = -4
ORDER_NOT_FOUND = -5
TX_NOT_FOUND = -6
BAD_REQUEST = -8
TX_CANCELED = -9

NOTES = {
    OK: "Success", SIGN_FAILED: "SIGN CHECK FAILED!", BAD_AMOUNT: "Incorrect parameter amount",
    BAD_ACTION: "Action not found", ALREADY_PAID: "Already paid", ORDER_NOT_FOUND: "Order not found",
    TX_NOT_FOUND: "Transaction does not exist", BAD_REQUEST: "Error in request from click",
    TX_CANCELED: "Transaction cancelled",
}


def _sign(p: dict, with_prepare_id: bool) -> str:
    parts = [p.get("click_trans_id", ""), p.get("service_id", ""), settings.CLICK_SECRET_KEY,
             p.get("merchant_trans_id", "")]
    if with_prepare_id:
        parts.append(p.get("merchant_prepare_id", ""))
    parts += [p.get("amount", ""), p.get("action", ""), p.get("sign_time", "")]
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _resp(p: dict, error: int, **extra) -> dict:
    return {"click_trans_id": p.get("click_trans_id"), "merchant_trans_id": p.get("merchant_trans_id"),
            "error": error, "error_note": NOTES[error], **extra}


def _common(p: dict, action: str, with_prepare_id: bool):
    required = ["click_trans_id", "service_id", "merchant_trans_id", "amount", "action", "sign_time", "sign_string"]
    if any(not p.get(k) and p.get(k) != "0" for k in required):
        return None, None, BAD_REQUEST
    if not settings.CLICK_SECRET_KEY or not hmac.compare_digest(p["sign_string"], _sign(p, with_prepare_id)):
        return None, None, SIGN_FAILED
    if p["action"] != action:
        return None, None, BAD_ACTION
    try:
        amount = Decimal(p["amount"])
    except InvalidOperation:
        return None, None, BAD_REQUEST
    mid = p["merchant_trans_id"]
    order = Order.objects.select_for_update().filter(pk=mid).first() if mid.isdigit() else None
    if order is None:
        return None, None, ORDER_NOT_FOUND
    if abs(order.total - amount) >= Decimal("0.01"):
        return order, amount, BAD_AMOUNT
    return order, amount, OK


@transaction.atomic
def prepare(p: dict) -> dict:
    order, amount, err = _common(p, "0", with_prepare_id=False)
    if err:
        return _resp(p, err)
    if order.payment_status != Order.PaymentStatus.PENDING:
        return _resp(p, ALREADY_PAID)
    if order.status != Order.Status.NEW:
        return _resp(p, TX_CANCELED)
    tx, _ = Tx.objects.get_or_create(
        click_trans_id=p["click_trans_id"],
        defaults={"order": order, "amount": amount, "click_paydoc_id": p.get("click_paydoc_id", "")},
    )
    return _resp(p, OK, merchant_prepare_id=tx.pk)


@transaction.atomic
def complete(p: dict) -> dict:
    order, amount, err = _common(p, "1", with_prepare_id=True)
    if err in (SIGN_FAILED, BAD_ACTION, BAD_REQUEST, ORDER_NOT_FOUND):
        return _resp(p, err)
    prepare_id = p.get("merchant_prepare_id", "")
    tx = Tx.objects.select_for_update().filter(
        pk=prepare_id if prepare_id.isdigit() else 0, click_trans_id=p["click_trans_id"],
    ).first()
    if tx is None:
        return _resp(p, TX_NOT_FOUND)
    if err == BAD_AMOUNT:
        return _resp(p, BAD_AMOUNT)
    if tx.status == Tx.Status.COMPLETED:
        return _resp(p, ALREADY_PAID, merchant_confirm_id=tx.pk)
    if tx.status == Tx.Status.CANCELED:
        return _resp(p, TX_CANCELED)
    click_error = int(p.get("error") or 0)
    if click_error < 0:
        # Click reports payment failure -> cancel our side
        tx.status, tx.error = Tx.Status.CANCELED, click_error
        tx.save()
        return _resp(p, TX_CANCELED)
    if order.payment_status != Order.PaymentStatus.PENDING:
        return _resp(p, ALREADY_PAID)
    tx.status = Tx.Status.COMPLETED
    tx.save()
    mark_paid(order)
    return _resp(p, OK, merchant_confirm_id=tx.pk)
