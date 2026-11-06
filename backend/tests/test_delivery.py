from decimal import Decimal
from unittest import mock

from django.test import override_settings

from apps.delivery.geo import point_in_polygon
from apps.delivery.models import DeliveryZone, Shipment
from apps.delivery.providers.yandex import YandexProvider, callback_signature
from apps.delivery.services import check_search_timeouts, refresh_shipment, request_courier
from apps.orders import services
from apps.orders.models import Order

from . import factories as f
from .base import BaseTestCase


class GeoTests(BaseTestCase):
    def test_point_in_polygon(self):
        self.assertTrue(point_in_polygon(41.3, 69.2, f.TASHKENT))
        self.assertFalse(point_in_polygon(41.5, 69.2, f.TASHKENT))

    def test_zone_priority_and_free_delivery(self):
        f.zone(name="Город", priority=0)
        inner = f.zone(name="Центр", priority=10, price=Decimal("10000"),
                       polygon=[[41.30, 69.27], [41.30, 69.29], [41.32, 69.29], [41.32, 69.27]])
        self.assertEqual(DeliveryZone.find(41.31, 69.28), inner)
        self.assertEqual(DeliveryZone.find(41.25, 69.15).name, "Город")
        self.assertEqual(inner.delivery_price(Decimal("400000")), 0)


@override_settings(COURIER_PROVIDER="yandex", YANDEX_DELIVERY_TOKEN="t", PUBLIC_BASE_URL="https://pet24.uz")
class YandexTests(BaseTestCase):
    def setUp(self):
        f.zone()
        b = f.branch()
        p = f.product("TOV001", price="100000", weight_g=2100)
        f.stock(p, b, 5)
        with mock.patch("apps.orders.services.refresh_stock"):
            self.order = services.create_order(
                f.customer(), [{"product_id": p.id, "quantity": 2}],
                {"address": "Навои 1", "lat": Decimal("41.311"), "lng": Decimal("69.279"), "apartment": "5"}, "payme")
        services.mark_paid(self.order)
        self.order.set_status(Order.Status.ASSEMBLING)
        self.order.set_status(Order.Status.COURIER_SEARCH)

    def test_claim_payload(self):
        s = Shipment.objects.create(order=self.order, provider="yandex")
        claim = YandexProvider().build_claim(s)
        src, dst = claim["route_points"]
        self.assertEqual(src["address"]["coordinates"], [69.27, 41.3])  # lon, lat
        self.assertEqual(dst["address"]["sflat"], "5")
        self.assertEqual(dst["contact"]["phone"], "+998901234567")
        self.assertEqual(claim["items"][0]["quantity"], 2)
        self.assertEqual(claim["items"][0]["weight"], 2.1)
        self.assertIn(f"sig={callback_signature(s.id)}", claim["callback_properties"]["callback_url"])

    def test_lifecycle(self):
        calls = []

        def fake_post(self_, path, params=None, json=None):
            calls.append(path)
            responses = {
                "/claims/create": {"id": "claim-1", "status": "new", "version": 1},
                "/claims/accept": {"id": "claim-1", "status": "accepted", "version": 1},
                "/driver-voiceforwarding": {"phone": "+998712000000", "ext": "123"},
            }
            if path == "/claims/info":
                return fake_post.info.pop(0)
            return responses[path]

        fake_post.info = [
            {"status": "ready_for_approval", "version": 1},
            {"status": "performer_lookup", "version": 1},
            {"status": "performer_found", "version": 2, "performer_info": {"courier_name": "Алишер"},
             "pricing": {"final_price": "18000"}},
        ]
        with mock.patch.object(YandexProvider, "_post", fake_post):
            s = request_courier(self.order)
            self.assertEqual((s.external_id, s.status), ("claim-1", "searching"))
            refresh_shipment(s)  # ready_for_approval -> accept
            self.assertIn("/claims/accept", calls)
            refresh_shipment(s)
        s.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual((s.status, s.courier_name, s.cost), ("assigned", "Алишер", Decimal("18000")))
        self.assertEqual(s.courier_phone, "+998712000000 доб. 123")
        self.assertEqual(self.order.status, Order.Status.COURIER_ASSIGNED)

    def test_failure_escalates(self):
        with mock.patch.object(YandexProvider, "_post", return_value={"id": "c", "status": "performer_not_found"}):
            request_courier(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PROBLEM)

    @override_settings(COURIER_SEARCH_TIMEOUT_MIN=0)
    def test_search_timeout(self):
        with mock.patch.object(YandexProvider, "_post", return_value={"id": "c", "status": "new"}):
            request_courier(self.order)
        self.assertEqual(check_search_timeouts(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PROBLEM)

    def test_callback_signature(self):
        s = Shipment.objects.create(order=self.order, provider="yandex", external_id="c", status="searching")
        url = "/api/delivery/yandex/callback/"
        self.assertEqual(self.client.post(f"{url}?sid={s.id}&sig=bad").status_code, 403)
        with mock.patch("apps.delivery.views.refresh_shipment.delay") as d:
            r = self.client.post(f"{url}?sid={s.id}&sig={callback_signature(s.id)}&claim_id=c")
        self.assertEqual(r.status_code, 200)
        d.assert_called_once_with(str(s.id))
