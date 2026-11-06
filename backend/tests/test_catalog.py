from decimal import Decimal

from apps.catalog.models import Branch, Product, ProductImage, Stock, SyncState
from apps.catalog.sync import refresh_stock, sync_branches, sync_products, sync_stock

from . import factories as f
from .base import BaseTestCase


class FakeStockApi:
    def __init__(self, products, branches=None):
        self.products = products
        self._branches = branches or [{"external_id": "BR001", "name": "Чиланзар", "is_active": True}]
        self.calls = []

    def branches(self):
        return self._branches

    def iter_products(self, **params):
        self.calls.append(("iter", params))
        yield from self.products

    def products_by_ids(self, ids, branch=None):
        self.calls.append(("ids", tuple(ids)))
        return [p for p in self.products if p["external_id"] in ids]


def api_product(ext, price="15000.00", real=7, active=True):
    return {
        "external_id": ext, "code": "001", "barcode": "478000", "name": f"Товар {ext}", "unit": "шт",
        "price": price, "is_active": active,
        "stocks": [{"branch": {"external_id": "BR001", "name": "Чиланзар"}, "quantity": 10, "sold": 3,
                    "real_quantity": real}],
    }


class SyncTests(BaseTestCase):
    def test_full_sync_creates_products_with_real_stock(self):
        api = FakeStockApi([api_product("A"), api_product("B", real=0)])
        sync_branches(api)
        res = sync_products(api)
        self.assertEqual(res["received"], 2)
        a = Product.objects.get(external_id="A")
        self.assertEqual(a.price, Decimal("15000.00"))
        self.assertEqual(Stock.objects.get(product=a).real_quantity, Decimal("7"))  # real, not 1C quantity
        self.assertTrue(SyncState.get("products_since"))

    def test_second_run_uses_updated_since_and_keeps_local_content(self):
        api = FakeStockApi([api_product("A")])
        sync_branches(api)
        sync_products(api)
        p = Product.objects.get(external_id="A")
        p.variant_label, p.old_price = "2 кг", Decimal("20000")
        p.save()
        api.products = [api_product("A", price="16000")]
        sync_products(api)
        self.assertIn("updated_since", api.calls[-1][1])
        p.refresh_from_db()
        self.assertEqual((p.price, p.variant_label, p.old_price), (Decimal("16000"), "2 кг", Decimal("20000")))

    def test_stock_sync_only_for_linked_products(self):
        b = f.branch()
        linked = f.product("TOV1")
        Product.objects.create(external_id="LOOSE", name="x", price=1)
        api = FakeStockApi([api_product("TOV1", real=4)], branches=[{"external_id": b.external_id}])
        sync_stock(api)
        self.assertEqual(api.calls[-1], ("ids", ("TOV1",)))
        self.assertEqual(Stock.objects.get(product=linked, branch=b).real_quantity, 4)

    def test_refresh_updates_price_and_active(self):
        f.branch()
        p = f.product("TOV1", price="100")
        refresh_stock(["TOV1"], client=FakeStockApi([api_product("TOV1", price="150", active=False)]))
        p.refresh_from_db()
        self.assertEqual((p.price, p.is_active), (Decimal("150"), False))


class ImageTests(BaseTestCase):
    def test_upload_converted_to_webp_with_thumb(self):
        p = f.product("TOV1")
        img = ProductImage.objects.get(group=p.group)
        self.assertTrue(img.image.name.endswith(".webp"))
        self.assertTrue(img.thumb.name.endswith(".webp"))
        self.assertLessEqual(max(img.image.width, img.image.height), 1200)
        self.assertLessEqual(max(img.thumb.width, img.thumb.height), 400)


class CatalogApiTests(BaseTestCase):
    def setUp(self):
        self.b = f.branch()
        self.p1 = f.product("TOV001", price="50000", attributes={"age": "puppy"})
        self.p2 = f.product("TOV002", price="90000", attributes={"age": "adult"})
        self.hidden = f.product("TOV003", publish=False)
        f.stock(self.p1, self.b, 5)

    def test_list_hides_unpublished_and_reports_stock(self):
        r = self.api().get("/api/catalog/products/")
        self.assertEqual(r.status_code, 200)
        names = {i["id"]: i for i in r.data["results"]}
        self.assertEqual(set(names), {self.p1.group_id, self.p2.group_id})
        self.assertTrue(names[self.p1.group_id]["variants"][0]["in_stock"])
        self.assertFalse(names[self.p2.group_id]["variants"][0]["in_stock"])

    def test_filters(self):
        c = self.api()
        ids = lambda r: {i["id"] for i in r.data["results"]}  # noqa: E731
        self.assertEqual(ids(c.get("/api/catalog/products/?in_stock=true")), {self.p1.group_id})
        self.assertEqual(ids(c.get("/api/catalog/products/?attr_age=adult")), {self.p2.group_id})
        self.assertEqual(ids(c.get("/api/catalog/products/?price_min=60000")), {self.p2.group_id})
        self.assertEqual(ids(c.get("/api/catalog/products/?q=478001")), {self.p1.group_id})
        r = c.get("/api/catalog/products/?ordering=-price")
        self.assertEqual([i["id"] for i in r.data["results"]], [self.p2.group_id, self.p1.group_id])

    def test_detail(self):
        r = self.api().get(f"/api/catalog/products/{self.p1.group.slug}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["images"]), 1)
        self.assertEqual(self.api().get(f"/api/catalog/products/{self.hidden.group.slug}/").status_code, 404)

    def test_branch_list(self):
        r = self.api().get("/api/catalog/branches/")
        self.assertEqual([b["name"] for b in r.data], [Branch.objects.get().name])
