---
name: stockapi
description: Reference for the stockapi service (KamolCoder/stockapi) that Pet24 reads products, prices and branch stock from. Use when touching apps/catalog/stockapi.py or sync.py, debugging sync, or answering questions about stock numbers.
---

# stockapi in short

Separate FastAPI service (repo `KamolCoder/stockapi`, full docs in its `API_DOCS.md`). 1C and cash registers **write**
into it; Pet24 only **reads** with its own API key (header `X-API-Key`, created in stockapi superadmin →
Организации → Ключи API). Never give Pet24 an organization token — that one can write.

## Endpoints Pet24 uses

- `GET /api/stock/branches` → `{"items": [{external_id, name, is_active, oks_date, stock_updated_at, ...}]}`
- `GET /api/stock/products` → `{"total", "limit", "offset", "items": [...]}`, `limit` ≤ 1000.
  Item: `external_id, code, barcode, barcodes[], article, plu, name, unit, price ("15000.00" string), is_active,
  image/thumb (staff photos — ignore), stocks: [{branch: {external_id, name}, quantity, sold, real_quantity, oks_loaded}]`.
  Filters: `external_ids=a,b,c` (≤ 1000), `branch`, `updated_since` (ISO; use `Z`, a raw `+` breaks the URL),
  `in_stock`, `real`, `q`, `barcode`.

## Stock semantics

`real_quantity = quantity (1C) − till sales not yet posted to 1C (days after the branch oks_date)`.
Pet24 always uses `real_quantity`. It can be negative (sold before the receipt was posted) — treat as 0 available.

## Gotchas

- A product's `updated_at` does **not** change on stock-only updates → stock is refreshed by explicit
  `external_ids` lists (`sync_stock`, every 5 min); product fields by the `updated_since` delta.
- Pagination is by name; a full resync (`stockapi_sync --full`) fixes anything a delta missed.
- Pet24 orders are not sent to stockapi or 1C: the branch prints the receipt at the till and the sale reaches stockapi
  via the cash register sync — that is why reservations outlive "assembled" by `SALES_SYNC_LAG_MIN`.
- Sync runs are logged in `SyncLog` and shown at `/panel/sync/`.
