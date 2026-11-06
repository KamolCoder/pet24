"""Payme Merchant API (JSON-RPC). https://developer.help.paycom.uz/protokol-merchant-api/"""
import base64
import binascii
import hmac
import time

from django.conf import settings
from django.db import transaction

from apps.orders.models import Order
from apps.orders.services import mark_paid

from .models import PaymeTransaction as Tx

TIMEOUT_MS = 12 * 60 * 60 * 1000  # Payme: unperformed transaction expires in 12h

ERR_PARSE = -32700
ERR_METHOD = -32601
ERR_AUTH = -32504
ERR_AMOUNT = -31001
ERR_TX_NOT_FOUND = -31003
ERR_CANT_CANCEL = -31007
ERR_CANT_PERFORM = -31008
ERR_ORDER_NOT_FOUND = -31050
ERR_ORDER_BUSY = -31051  # account error range -31050..-31099


class PaymeError(Exception):
    def __init__(self, code: int, message: str, data: str | None = None, commit: bool = False):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data
        self.commit = commit  # keep DB changes made before the error (e.g. expiry cancel)

    def as_dict(self):
        err = {"code": self.code, "message": {"ru": self.message, "uz": self.message, "en": self.message}}
        if self.data:
            err["data"] = self.data
        return err


def now_ms() -> int:
    return int(time.time() * 1000)


def check_auth(header: str) -> bool:
    if not header.startswith("Basic ") or not settings.PAYME_KEY:
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    login, _, key = decoded.partition(":")
    return login == "Paycom" and hmac.compare_digest(key, settings.PAYME_KEY)


def _order(params: dict, lock=False) -> Order:
    order_id = str((params.get("account") or {}).get("order_id", ""))
    qs = Order.objects.select_for_update() if lock else Order.objects
    order = qs.filter(pk=order_id).first() if order_id.isdigit() else None
    if order is None:
        raise PaymeError(ERR_ORDER_NOT_FOUND, "Заказ не найден", "order_id")
    return order


def _check_order(order: Order, amount: int) -> None:
    if order.status != Order.Status.NEW or order.payment_status != Order.PaymentStatus.PENDING:
        raise PaymeError(ERR_ORDER_BUSY, "Заказ уже оплачен или отменён", "order_id")
    if order.amount_tiyin != int(amount):
        raise PaymeError(ERR_AMOUNT, "Неверная сумма")


def _tx(params: dict, lock=True) -> Tx:
    qs = Tx.objects.select_for_update() if lock else Tx.objects
    tx = qs.filter(payme_id=params.get("id")).select_related("order").first()
    if tx is None:
        raise PaymeError(ERR_TX_NOT_FOUND, "Транзакция не найдена")
    return tx


def _cancel(tx: Tx, reason: int) -> None:
    tx.state = Tx.State.CANCELED_AFTER_PERFORM if tx.state == Tx.State.PERFORMED else Tx.State.CANCELED
    tx.reason = reason
    tx.cancel_time = now_ms()
    tx.save()
    order = tx.order
    if tx.state == Tx.State.CANCELED_AFTER_PERFORM:
        order.payment_status = Order.PaymentStatus.REFUNDED
        order.save(update_fields=["payment_status"])
    if order.status in Order.CUSTOMER_CANCELABLE:
        order.set_status(Order.Status.CANCELED, note=f"Payme: отмена транзакции, reason={reason}")
        if order.payment_status == Order.PaymentStatus.REFUND_REQUIRED:
            order.payment_status = Order.PaymentStatus.REFUNDED
            order.save(update_fields=["payment_status"])


def _tx_view(tx: Tx) -> dict:
    return {
        "create_time": tx.create_time, "perform_time": tx.perform_time, "cancel_time": tx.cancel_time,
        "transaction": str(tx.pk), "state": tx.state, "reason": tx.reason,
    }


def check_perform(params):
    _check_order(_order(params), params.get("amount", 0))
    return {"allow": True}


def create_transaction(params):
    existing = Tx.objects.select_for_update().filter(payme_id=params.get("id")).first()
    if existing:
        if existing.state != Tx.State.CREATED:
            raise PaymeError(ERR_CANT_PERFORM, "Транзакция уже завершена")
        if now_ms() - existing.create_time > TIMEOUT_MS:
            _cancel(existing, 4)
            raise PaymeError(ERR_CANT_PERFORM, "Транзакция просрочена", commit=True)
        return {"create_time": existing.create_time, "transaction": str(existing.pk), "state": existing.state}

    order = _order(params, lock=True)
    _check_order(order, params.get("amount", 0))
    if Tx.objects.filter(order=order, state=Tx.State.CREATED).exists():
        raise PaymeError(ERR_ORDER_BUSY, "По заказу уже идёт оплата", "order_id")
    tx = Tx.objects.create(
        payme_id=params["id"], order=order, amount=int(params["amount"]),
        payme_time=int(params.get("time", 0)), create_time=now_ms(),
    )
    return {"create_time": tx.create_time, "transaction": str(tx.pk), "state": tx.state}


def perform_transaction(params):
    tx = _tx(params)
    if tx.state == Tx.State.CREATED:
        if now_ms() - tx.create_time > TIMEOUT_MS:
            _cancel(tx, 4)
            raise PaymeError(ERR_CANT_PERFORM, "Транзакция просрочена", commit=True)
        tx.state = Tx.State.PERFORMED
        tx.perform_time = now_ms()
        tx.save()
        mark_paid(Order.objects.select_for_update().get(pk=tx.order_id))
    elif tx.state != Tx.State.PERFORMED:
        raise PaymeError(ERR_CANT_PERFORM, "Транзакция отменена")
    return {"transaction": str(tx.pk), "perform_time": tx.perform_time, "state": tx.state}


def cancel_transaction(params):
    tx = _tx(params)
    if tx.state in (Tx.State.CREATED, Tx.State.PERFORMED):
        if tx.state == Tx.State.PERFORMED and tx.order.status == Order.Status.DELIVERED:
            raise PaymeError(ERR_CANT_CANCEL, "Заказ уже доставлен")
        _cancel(tx, int(params.get("reason") or 0))
    return {"transaction": str(tx.pk), "cancel_time": tx.cancel_time, "state": tx.state}


def check_transaction(params):
    return _tx_view(_tx(params, lock=False))


def get_statement(params):
    txs = Tx.objects.filter(create_time__gte=params.get("from", 0), create_time__lte=params.get("to", 0))
    return {"transactions": [
        {"id": t.payme_id, "time": t.payme_time, "amount": t.amount, "account": {"order_id": str(t.order_id)},
         **_tx_view(t)}
        for t in txs.order_by("create_time")
    ]}


METHODS = {
    "CheckPerformTransaction": check_perform,
    "CreateTransaction": create_transaction,
    "PerformTransaction": perform_transaction,
    "CancelTransaction": cancel_transaction,
    "CheckTransaction": check_transaction,
    "GetStatement": get_statement,
}


def dispatch(method: str, params: dict):
    handler = METHODS.get(method)
    if handler is None:
        raise PaymeError(ERR_METHOD, "Метод не найден")
    error = None
    with transaction.atomic():
        try:
            return handler(params or {})
        except PaymeError as e:
            if not e.commit:
                raise
            error = e
    raise error
