import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Branch, Product, Stock, SyncState
from .stockapi import StockApiClient, parse_qty

log = logging.getLogger(__name__)

PRODUCT_FIELDS = ["name", "code", "article", "barcode", "unit", "price", "is_active", "synced_at"]


def sync_branches(client: StockApiClient | None = None) -> int:
    client = client or StockApiClient()
    now = timezone.now()
    n = 0
    for b in client.branches():
        Branch.objects.update_or_create(
            external_id=str(b["external_id"]),
            defaults={"name": b.get("name") or b["external_id"], "is_active": bool(b.get("is_active", True)),
                      "synced_at": now},
        )
        n += 1
    return n


def _apply_stocks(items: list[dict], branches: dict[str, int], products: dict[str, int]) -> int:
    """Upsert real_quantity for every (product, branch) present in the payload."""
    rows = []
    for item in items:
        pid = products.get(str(item["external_id"]))
        if pid is None:
            continue
        for s in item.get("stocks") or []:
            bid = branches.get(str(s["branch"]["external_id"]))
            if bid is None:
                continue
            real = s.get("real_quantity", s.get("quantity"))
            rows.append(Stock(product_id=pid, branch_id=bid, real_quantity=parse_qty(real)))
    if rows:
        Stock.objects.bulk_create(
            rows, update_conflicts=True, unique_fields=["product", "branch"],
            update_fields=["real_quantity", "updated_at"], batch_size=1000,
        )
    return len(rows)


def _upsert_products(items: list[dict]) -> dict[str, int]:
    now = timezone.now()
    rows = [
        Product(
            external_id=str(i["external_id"]),
            name=i.get("name") or "",
            code=i.get("code") or "",
            article=i.get("article") or "",
            barcode=i.get("barcode") or "",
            unit=i.get("unit") or "",
            price=Decimal(str(i.get("price") or 0)),
            is_active=bool(i.get("is_active", True)),
            synced_at=now,
        )
        for i in items
    ]
    Product.objects.bulk_create(
        rows, update_conflicts=True, unique_fields=["external_id"], update_fields=PRODUCT_FIELDS, batch_size=1000,
    )
    ids = [r.external_id for r in rows]
    return dict(Product.objects.filter(external_id__in=ids).values_list("external_id", "id"))


def _branch_map() -> dict[str, int]:
    return dict(Branch.objects.values_list("external_id", "id"))


def sync_products(client: StockApiClient | None = None, full: bool = False) -> dict:
    """Pull products changed since the last run (or everything with full=True)."""
    client = client or StockApiClient()
    started = timezone.now()
    since = "" if full else SyncState.get("products_since")
    params = {"updated_since": since} if since else {}
    branches = _branch_map()
    created_before = Product.objects.count()
    batch, total, stocks = [], 0, 0

    def flush():
        nonlocal stocks
        with transaction.atomic():
            products = _upsert_products(batch)
            stocks += _apply_stocks(batch, branches, products)

    for item in client.iter_products(**params):
        batch.append(item)
        if len(batch) >= 1000:
            flush()
            total += len(batch)
            batch = []
    if batch:
        flush()
        total += len(batch)
    # small overlap so edits made during the run are not lost
    SyncState.put("products_since", (started - timedelta(minutes=2)).isoformat())
    result = {"received": total, "created": Product.objects.count() - created_before, "stocks": stocks}
    log.info("stockapi products sync: %s", result)
    return result


def sync_stock(client: StockApiClient | None = None) -> int:
    """Refresh stock of every product linked to a card. stockapi does not bump updated_at on stock-only
    changes, so stock is pulled by explicit id list rather than by updated_since."""
    client = client or StockApiClient()
    ids = list(Product.objects.filter(group__isnull=False).values_list("external_id", flat=True))
    if not ids:
        return 0
    return refresh_stock(ids, client=client)


def refresh_stock(external_ids: list[str], client: StockApiClient | None = None) -> int:
    client = client or StockApiClient()
    items = client.products_by_ids(list(external_ids))
    by_id = {p.external_id: p for p in Product.objects.filter(external_id__in=external_ids)}
    changed = []
    for i in items:
        p = by_id.get(str(i["external_id"]))
        if p is None:
            continue
        price, active = Decimal(str(i.get("price") or 0)), bool(i.get("is_active", True))
        if p.price != price or p.is_active != active:
            p.price, p.is_active = price, active
            changed.append(p)
    with transaction.atomic():
        # price/active may change between delta runs: keep them fresh too
        Product.objects.bulk_update(changed, ["price", "is_active"], batch_size=1000)
        return _apply_stocks(items, _branch_map(), {k: p.id for k, p in by_id.items()})
