import base64
import hashlib
from decimal import Decimal
from unittest import mock

from django.test import override_settings

from apps.orders import services
from apps.orders.models import Order
from apps.payments.models import ClickTransaction, PaymeTransaction

from . import factories as f
from .base import BaseTestCase

ADDRESS = {"address": "ул. Навои 1", "lat": Decimal("41.311"), "lng": Decimal("69.279")}


def make_order(method="payme"):
    f.zone()
    b = f.branch()
    p = f.product("TOV001", price="100000")
    f.stock(p, b, 5)
    with mock.patch("apps.orders.services.refresh_stock"):
        return services.create_order(f.customer(), [{"product_id": p.id, "quantity": 1}], ADDRESS, method)


@override_settings(PAYME_KEY="payme-test-key")
class PaymeTests(BaseTestCase):
    def setUp(self):
        self.order = make_order()
        self.auth = "Basic " + base64.b64encode(b"Paycom:payme-test-key").decode()

    def rpc(self, method, params, auth=None):
        r = self.client.post("/api/payments/payme/", {"id": 1, "method": method, "params": params},
                             content_type="application/json", HTTP_AUTHORIZATION=auth or self.auth)
        return r.json()

    def params(self, **kw):
        return {"amount": self.order.amount_tiyin, "account": {"order_id": str(self.order.pk)}, **kw}

    def test_auth(self):
        self.assertEqual(self.rpc("CheckPerformTransaction", self.params(), auth="Basic eDp5")["error"]["code"], -32504)

    def test_full_payment(self):
        self.assertEqual(self.rpc("CheckPerformTransaction", self.params())["result"], {"allow": True})
        self.assertEqual(self.rpc("CheckPerformTransaction", self.params(amount=1))["error"]["code"], -31001)

        r = self.rpc("CreateTransaction", self.params(id="tx1", time=1))
        self.assertEqual(r["result"]["state"], 1)
        # repeated create is idempotent, another transaction for the same order is refused
        self.assertEqual(self.rpc("CreateTransaction", self.params(id="tx1", time=1))["result"]["state"], 1)
        self.assertEqual(self.rpc("CreateTransaction", self.params(id="tx2", time=1))["error"]["code"], -31051)

        r = self.rpc("PerformTransaction", {"id": "tx1"})
        self.assertEqual(r["result"]["state"], 2)
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), ("paid", "paid"))
        self.assertEqual(self.rpc("PerformTransaction", {"id": "tx1"})["result"]["state"], 2)
        self.assertEqual(self.rpc("CheckTransaction", {"id": "tx1"})["result"]["state"], 2)
        st = self.rpc("GetStatement", {"from": 0, "to": 10**14})["result"]["transactions"]
        self.assertEqual([t["id"] for t in st], ["tx1"])

        # refund from the Payme cabinet before delivery
        r = self.rpc("CancelTransaction", {"id": "tx1", "reason": 5})
        self.assertEqual(r["result"]["state"], -2)
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), ("canceled", "refunded"))

    def test_cancel_before_perform(self):
        self.rpc("CreateTransaction", self.params(id="tx1", time=1))
        self.assertEqual(self.rpc("CancelTransaction", {"id": "tx1", "reason": 3})["result"]["state"], -1)
        self.assertEqual(self.rpc("PerformTransaction", {"id": "tx1"})["error"]["code"], -31008)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "canceled")

    def test_expired_transaction_is_cancelled_and_persisted(self):
        self.rpc("CreateTransaction", self.params(id="tx1", time=1))
        PaymeTransaction.objects.filter(payme_id="tx1").update(create_time=1)
        self.assertEqual(self.rpc("PerformTransaction", {"id": "tx1"})["error"]["code"], -31008)
        tx = PaymeTransaction.objects.get(payme_id="tx1")
        self.assertEqual((tx.state, tx.reason), (-1, 4))

    def test_unknown(self):
        self.assertEqual(self.rpc("PerformTransaction", {"id": "nope"})["error"]["code"], -31003)
        self.assertEqual(self.rpc("Foo", {})["error"]["code"], -32601)
        r = self.rpc("CheckPerformTransaction", {"amount": 1, "account": {"order_id": "999"}})
        self.assertEqual(r["error"]["code"], -31050)


@override_settings(CLICK_SECRET_KEY="click-secret", CLICK_SERVICE_ID="77")
class ClickTests(BaseTestCase):
    def setUp(self):
        self.order = make_order("click")

    def signed(self, action, prepare_id="", **kw):
        p = {"click_trans_id": "555", "service_id": "77", "click_paydoc_id": "1",
             "merchant_trans_id": str(self.order.pk), "amount": f"{self.order.total:.2f}", "action": action,
             "error": "0", "error_note": "Success", "sign_time": "2026-11-06 12:00:00", **kw}
        if prepare_id:
            p["merchant_prepare_id"] = str(prepare_id)
        raw = p["click_trans_id"] + p["service_id"] + "click-secret" + p["merchant_trans_id"] + \
            (str(prepare_id) if prepare_id else "") + p["amount"] + p["action"] + p["sign_time"]
        p["sign_string"] = hashlib.md5(raw.encode()).hexdigest()
        return p

    def test_prepare_complete(self):
        r = self.client.post("/api/payments/click/prepare/", self.signed("0")).json()
        self.assertEqual(r["error"], 0, r)
        r = self.client.post("/api/payments/click/complete/", self.signed("1", r["merchant_prepare_id"])).json()
        self.assertEqual(r["error"], 0, r)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "paid")
        r = self.client.post("/api/payments/click/complete/",
                             self.signed("1", ClickTransaction.objects.get().pk)).json()
        self.assertEqual(r["error"], -4)

    def test_bad_sign_and_amount(self):
        p = self.signed("0")
        p["sign_string"] = "x"
        self.assertEqual(self.client.post("/api/payments/click/prepare/", p).json()["error"], -1)
        self.assertEqual(self.client.post("/api/payments/click/prepare/", self.signed("0", amount="1.00")).json()["error"], -2)

    def test_click_reports_failure(self):
        prep = self.client.post("/api/payments/click/prepare/", self.signed("0")).json()
        r = self.client.post("/api/payments/click/complete/", self.signed("1", prep["merchant_prepare_id"], error="-5017")).json()
        self.assertEqual(r["error"], -9)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.NEW)
