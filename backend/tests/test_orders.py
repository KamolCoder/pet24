from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from apps.catalog.stockapi import StockApiError
from apps.delivery.models import Shipment
from apps.orders import services
from apps.orders.models import Order
from apps.orders.tasks import expire_unpaid_orders

from . import factories as f
from .base import BaseTestCase

ADDRESS = {"address": "ул. Навои 1", "lat": "41.311", "lng": "69.279", "apartment": "5"}

no_live = mock.patch("apps.orders.services.refresh_stock", side_effect=StockApiError("offline"))


@no_live
class QuoteTests(BaseTestCase):
    def setUp(self):
        self.zone = f.zone()
        self.near = f.branch("NEAR", "41.312", "69.280")
        self.far = f.branch("FAR", "41.350", "69.350")
        self.p = f.product("TOV001", price="100000")

    def quote(self, qty=1, lat="41.311", lng="69.279"):
        return self.api().post("/api/orders/quote/", {
            "items": [{"product_id": self.p.id, "quantity": qty}], "lat": lat, "lng": lng,
        }, format="json")

    def test_nearest_branch_with_stock(self, _):
        f.stock(self.p, self.near, 1)
        f.stock(self.p, self.far, 10)
        r = self.quote(1)
        self.assertEqual(r.data["branch"]["id"], self.near.id)
        self.assertEqual(r.data["delivery_price"], Decimal("15000"))
        # near has only 1 -> far branch takes the order
        self.assertEqual(self.quote(3).data["branch"]["id"], self.far.id)
        # free delivery from 300k
        self.assertEqual(self.quote(3).data["delivery_price"], Decimal("0"))

    def test_missing_reported(self, _):
        f.stock(self.p, self.near, 1)
        r = self.quote(5)
        self.assertEqual(r.data["missing"], [{"product_id": self.p.id, "requested": 5, "available": 1}])

    def test_out_of_zone(self, _):
        r = self.quote(1, lat="40.0", lng="70.0")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "out_of_zone")


@no_live
class OrderFlowTests(BaseTestCase):
    def setUp(self):
        f.zone()
        self.b = f.branch()
        self.p = f.product("TOV001", price="100000")
        f.stock(self.p, self.b, 2)
        self.user = f.customer()

    def create(self, qty=1, user=None):
        return self.api(user or self.user).post("/api/orders/", {
            "items": [{"product_id": self.p.id, "quantity": qty}], "address": ADDRESS, "payment_method": "payme",
        }, format="json")

    def test_create_order_reserves_stock(self, _):
        r = self.create(2)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["payment_url"].startswith("https://checkout.paycom.uz/"))
        self.assertEqual(Decimal(r.data["total"]), Decimal("200000") + Decimal("15000"))
        # both units reserved -> nobody else can buy them
        r2 = self.create(1, user=f.customer("998907777777"))
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.data["code"], "out_of_stock")

    def test_cancel_releases_reservation(self, _):
        order = Order.objects.get(pk=self.create(2).data["id"])
        r = self.api().post(f"/api/orders/{order.pk}/cancel/")  # anonymous
        self.assertEqual(r.status_code, 401)
        r = self.api(self.user).post(f"/api/orders/{order.pk}/cancel/")
        self.assertEqual(r.data["status"], "canceled")
        self.assertEqual(self.create(2).status_code, 201)

    def test_min_order(self, _):
        self.p.price = Decimal("1000")
        self.p.save()
        r = self.create(1)
        self.assertEqual(r.data["code"], "min_order")

    def test_reservation_kept_for_sales_lag_after_assembly(self, _):
        order = Order.objects.get(pk=self.create(2).data["id"])
        avail = lambda: services.available([self.p.id], [self.b.id])[(self.p.id, self.b.id)]  # noqa: E731
        self.assertEqual(avail(), 0)
        order.status, order.assembled_at = Order.Status.DELIVERING, timezone.now()
        order.save()
        self.assertEqual(avail(), 0)  # till sale not yet in stockapi
        order.assembled_at = timezone.now() - timedelta(hours=1)
        order.save()
        self.assertEqual(avail(), 2)  # stockapi already reflects the sale

    def test_expire_unpaid(self, _):
        order = Order.objects.get(pk=self.create(1).data["id"])
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(expire_unpaid_orders(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)

    def test_orders_are_private(self, _):
        oid = self.create(1).data["id"]
        other = f.customer("998905555555")
        self.assertEqual(self.api(other).get(f"/api/orders/{oid}/").status_code, 404)


@no_live
class StaffFlowTests(BaseTestCase):
    def setUp(self):
        f.zone()
        self.b = f.branch()
        self.p = f.product("TOV001", price="100000")
        f.stock(self.p, self.b, 5)
        self.order = services.create_order(f.customer(), [{"product_id": self.p.id, "quantity": 1}],
                                           {**ADDRESS, "lat": Decimal("41.311"), "lng": Decimal("69.279")}, "payme")
        services.mark_paid(self.order)
        self.picker = f.customer("998909999999", role="picker", branch=self.b)
        self.picker.set_password("pass12345")
        self.picker.save()

    def act(self, action, **extra):
        return self.client.post(f"/staff/orders/{self.order.pk}/action/", {"action": action, **extra})

    def test_picker_flow_calls_courier(self, _):
        self.client.force_login(self.picker)
        self.assertEqual(self.client.get("/staff/").status_code, 200)
        self.act("start")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.ASSEMBLING)
        with self.captureOnCommitCallbacks(execute=True):
            self.act("assembled")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.COURIER_SEARCH)
        shipment = Shipment.objects.get(order=self.order)
        self.assertEqual(shipment.status, Shipment.Status.SEARCHING)

        # courier statuses move the order
        from apps.delivery.services import sync_order

        for s_status, o_status in [
            (Shipment.Status.ASSIGNED, Order.Status.COURIER_ASSIGNED),
            (Shipment.Status.PICKED_UP, Order.Status.DELIVERING),
            (Shipment.Status.DELIVERED, Order.Status.DELIVERED),
        ]:
            shipment.status = s_status
            shipment.save()
            sync_order(shipment)
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, o_status)
        self.assertEqual(list(self.order.events.values_list("to_status", flat=True))[-1], "delivered")

    def test_picker_sees_only_own_branch(self, _):
        other = f.branch("BR2", "41.33", "69.30")
        self.order.branch = other
        self.order.save()
        self.client.force_login(self.picker)
        self.assertEqual(self.client.get(f"/staff/orders/{self.order.pk}/").status_code, 404)

    def test_picker_cannot_cancel(self, _):
        self.client.force_login(self.picker)
        self.act("cancel")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_operator_cancel_paid_order_requires_refund(self, _):
        op = f.customer("998908888888", role="operator")
        self.client.force_login(op)
        self.act("cancel", note="клиент передумал")
        self.order.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), ("canceled", "refund_required"))

    def test_login_with_formatted_phone(self, _):
        r = self.client.post("/staff/login/", {"username": "+998 90 999 99 99", "password": "pass12345"})
        self.assertEqual(r.status_code, 302)

    def test_customer_has_no_access(self, _):
        self.client.force_login(f.customer("998906666666"))
        self.assertEqual(self.client.get("/staff/").status_code, 403)
