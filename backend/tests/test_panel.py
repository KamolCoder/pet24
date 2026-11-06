from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from apps.catalog.models import Product, ProductGroup, SyncLog
from apps.customers.models import User
from apps.delivery.models import Shipment
from apps.orders import services
from apps.orders.models import Order
from apps.panel import analytics

from . import factories as f
from .base import BaseTestCase

ADDRESS = {"address": "Навои 1", "lat": Decimal("41.311"), "lng": Decimal("69.279")}


def place(user, product, qty=1, paid=True):
    with mock.patch("apps.orders.services.refresh_stock"):
        o = services.create_order(user, [{"product_id": product.id, "quantity": qty}], ADDRESS, "payme")
    if paid:
        services.mark_paid(o)
    return o


class PanelTestCase(BaseTestCase):
    def setUp(self):
        self.zone = f.zone()
        self.branch = f.branch()
        self.p = f.product("TOV001", price="100000")
        f.stock(self.p, self.branch, 50)
        self.op = f.customer("998900000001", role="operator")
        self.client.force_login(self.op)


class AccessTests(BaseTestCase):
    def test_anonymous_redirected_to_login(self):
        r = self.client.get("/panel/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/panel/login/", r["Location"])

    def test_picker_and_customer_forbidden(self):
        b = f.branch()
        for user in (f.customer("998901111111"), f.customer("998902222222", role="picker", branch=b)):
            self.client.force_login(user)
            self.assertEqual(self.client.get("/panel/").status_code, 403)

    def test_login(self):
        u = f.customer("998903333333", role="operator")
        u.set_password("secret123")
        u.save()
        r = self.client.post("/panel/login/", {"username": "90 333 33 33", "password": "secret123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/panel/")


class PagesTests(PanelTestCase):
    def test_all_pages_render(self):
        o = place(f.customer(), self.p)
        urls = [
            "/panel/", "/panel/analytics/", "/panel/analytics/?preset=7", "/panel/analytics/?from=2026-01-01&to=2026-01-31",
            "/panel/orders/", "/panel/orders/?status=paid&q=0001", f"/panel/orders/{o.pk}/", "/panel/shipments/",
            "/panel/customers/", f"/panel/customers/{o.user_id}/", "/panel/products/", "/panel/products/?photo=no",
            f"/panel/products/{self.p.group_id}/", "/panel/products/new/", "/panel/queue/", "/panel/sync/",
        ] + [f"/panel/{k}/" for k in ("categories", "brands", "pet_types", "branches", "zones", "staff")] + [
            "/panel/categories/new/", "/panel/staff/new/", f"/panel/branches/{self.branch.pk}/", f"/panel/zones/{self.zone.pk}/",
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/panel/branches/new/").status_code, 404)  # branches come from stockapi

    def test_csv_exports(self):
        place(f.customer(), self.p)
        r = self.client.get("/panel/orders/?export=csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("000001", r.content.decode("utf-8-sig"))
        self.assertEqual(self.client.get("/panel/analytics/?export=days").status_code, 200)
        self.assertIn("Корм TOV001", self.client.get("/panel/analytics/?export=products").content.decode("utf-8-sig"))


class AnalyticsTests(PanelTestCase):
    def test_kpis(self):
        a, b = f.customer("998904444444"), f.customer("998905555555")
        o1 = place(a, self.p, 1)                 # 100k + 15k delivery
        place(a, self.p, 3)                      # 300k, free delivery
        place(b, self.p, 1, paid=False)          # unpaid -> not revenue
        canceled = place(b, self.p, 1)
        services.cancel_order(canceled, self.op, "test")
        Shipment.objects.create(order=o1, provider="manual", status="delivered", cost=Decimal("20000"))

        today = timezone.localdate()
        k = analytics.kpis(analytics.Period(today, today))
        self.assertEqual(k["created"], 4)
        self.assertEqual(k["realized"], 2)
        self.assertEqual(k["revenue"], Decimal("415000"))          # 115000 + 300000
        self.assertEqual(k["avg_check"], Decimal("207500"))        # 415000 / 2
        self.assertEqual(k["delivery_revenue"], Decimal("15000"))
        self.assertEqual(k["delivery_margin"], Decimal("-5000"))   # 15000 - 20000
        self.assertEqual(k["payment_rate"], Decimal("0.75"))       # 3 paid / 4 created
        self.assertEqual(k["cancel_rate"], Decimal("0.25"))
        self.assertEqual((k["customers"], k["new_customers"]), (1, 1))
        self.assertEqual(k["repeat_share"], Decimal("1"))          # a has 2 orders

        days = analytics.by_day(analytics.Period(today - timedelta(days=2), today))
        self.assertEqual([d["revenue"] for d in days], [0, 0, Decimal("415000")])
        branches = analytics.by_branch(analytics.Period(today, today))
        self.assertEqual((branches[0]["orders"], branches[0]["canceled"]), (2, 1))
        top = analytics.top_products(analytics.Period(today, today))
        self.assertEqual((top[0]["qty"], top[0]["revenue"]), (4, Decimal("400000")))

    def test_previous_period(self):
        p = analytics.Period(timezone.localdate().replace(day=10), timezone.localdate().replace(day=16))
        prev = p.previous()
        self.assertEqual((prev.date_to - prev.date_from).days, 6)
        self.assertEqual(prev.date_to, p.date_from - timedelta(days=1))


class OrderActionTests(PanelTestCase):
    def test_cancel_then_mark_refunded(self):
        o = place(f.customer(), self.p)
        self.client.post(f"/panel/orders/{o.pk}/action/", {"action": "cancel", "note": "нет товара"})
        o.refresh_from_db()
        self.assertEqual((o.status, o.payment_status), ("canceled", "refund_required"))
        self.client.post(f"/panel/orders/{o.pk}/action/", {"action": "refunded", "note": "Payme 123"})
        o.refresh_from_db()
        self.assertEqual(o.payment_status, "refunded")
        self.assertIn("возврат сделан", o.events.last().note)

    def test_problem_and_resume(self):
        o = place(f.customer(), self.p)
        self.client.post(f"/panel/orders/{o.pk}/action/", {"action": "problem", "note": "звонок клиенту"})
        o.refresh_from_db()
        self.assertEqual(o.status, Order.Status.PROBLEM)
        self.client.post(f"/panel/orders/{o.pk}/action/", {"action": "resume"})
        o.refresh_from_db()
        self.assertEqual(o.status, Order.Status.PAID)


class CatalogTests(PanelTestCase):
    def test_queue_create_card_and_publish(self):
        a = Product.objects.create(external_id="Q1", name="Наполнитель 5 л", price=30000)
        b = Product.objects.create(external_id="Q2", name="Наполнитель 10 л", price=50000)
        r = self.client.post("/panel/queue/action/", {"ids": [a.pk, b.pk], "action": "create", "name": "Наполнитель Cat"})
        group = ProductGroup.objects.get(name="Наполнитель Cat")
        self.assertRedirects(r, f"/panel/products/{group.pk}/")
        self.assertEqual(group.slug, "napolnitel-cat")
        self.assertEqual(set(group.variants.values_list("external_id", flat=True)), {"Q1", "Q2"})

        # cannot publish without photo and category
        url = f"/panel/products/{group.pk}/"
        self.client.post(url, {"action": "toggle_publish"})
        group.refresh_from_db()
        self.assertFalse(group.is_published)

        self.client.post(url, {"action": "upload", "images": [f.png_upload("a.png"), f.png_upload("b.png")]})
        self.assertEqual(group.images.count(), 2)
        group.category = self.p.group.category
        group.save()
        self.client.post(url, {"action": "toggle_publish"})
        group.refresh_from_db()
        self.assertTrue(group.is_published)

        # deleting the last photos unpublishes the card
        for img in list(group.images.all()):
            self.client.post(url, {"action": "image_delete", "image_id": img.pk})
        group.refresh_from_db()
        self.assertFalse(group.is_published)

    def test_edit_card_and_variants(self):
        g = self.p.group
        url = f"/panel/products/{g.pk}/"
        data = {
            "action": "save", "name": "Корм Супер", "slug": "", "category": g.category_id, "brand": "",
            "pet_types": [], "sort": 5, "description": "Описание", "composition": "", "feeding_guide": "",
            "attributes": '{"age": "adult"}', "is_published": "on",
            "v-TOTAL_FORMS": 1, "v-INITIAL_FORMS": 1, "v-MIN_NUM_FORMS": 0, "v-MAX_NUM_FORMS": 1000,
            "v-0-id": self.p.pk, "v-0-variant_label": "15 кг", "v-0-variant_sort": 2, "v-0-old_price": "120000",
            "v-0-weight_g": 15500,
        }
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302, r.content.decode()[:2000] if r.status_code == 200 else "")
        g.refresh_from_db()
        self.p.refresh_from_db()
        self.assertEqual((g.name, g.slug, g.attributes), ("Корм Супер", "korm-super", {"age": "adult"}))
        self.assertEqual((self.p.variant_label, self.p.old_price, self.p.weight_g), ("15 кг", Decimal("120000"), 15500))

    def test_unlink_and_attach(self):
        g = self.p.group
        url = f"/panel/products/{g.pk}/"
        self.client.post(url, {"action": "unlink", "product_id": self.p.pk})
        self.p.refresh_from_db()
        self.assertIsNone(self.p.group_id)
        self.client.post(url, {"action": "attach", "q": self.p.barcode})
        self.p.refresh_from_db()
        self.assertEqual(self.p.group_id, g.pk)


class CrudTests(PanelTestCase):
    def test_create_category_with_auto_slug(self):
        r = self.client.post("/panel/categories/new/", {"name": "Игрушки", "slug": "", "sort": 0, "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.client.get("/panel/categories/").content.decode().count("Игрушки"))

    def test_branch_requires_coords_for_delivery(self):
        b = f.branch("BR9", delivery_enabled=False)
        b.lat = None
        b.save()
        r = self.client.post(f"/panel/branches/{b.pk}/", {"delivery_enabled": "on", "work_from": "09:00", "work_to": "21:00"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "нужны координаты")

    def test_create_staff(self):
        r = self.client.post("/panel/staff/new/", {
            "phone": "+998 93 111 22 33", "first_name": "Сборщик", "role": "picker", "branch": self.branch.pk,
            "is_active": "on", "password": "pass12345",
        })
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(phone="998931112233")
        self.assertTrue(u.check_password("pass12345"))
        self.assertEqual(u.branch, self.branch)
        r = self.client.post("/panel/staff/new/", {"phone": "931112233", "role": "picker", "password": "pass12345"})
        self.assertContains(r, "уже зарегистрирован")
        self.assertContains(r, "Сборщику нужен филиал")

    def test_zone_polygon_validation(self):
        r = self.client.post("/panel/zones/new/", {
            "name": "Z", "price": 1, "min_order": 0, "max_branch_km": 10, "priority": 0, "polygon": "[[1, 2]]",
        })
        self.assertContains(r, "минимум из 3 точек")


class SyncPageTests(PanelTestCase):
    def test_manual_sync_logs_error(self):
        r = self.client.post("/panel/sync/")
        self.assertEqual(r.status_code, 302)
        log = SyncLog.objects.first()
        self.assertFalse(log.ok)
        self.assertIn("STOCKAPI_URL", log.error)
