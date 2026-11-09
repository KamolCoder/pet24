# Pet24 — project guide for Claude

Mobile app + backend for a chain of ~30 pet shops in Tashkent: catalog, delivery from the nearest branch,
online payment (Payme / Click), operator panel with sales analytics. Flutter app is the next stage.

## Working with the owner (Kamol)

- Reply in **Russian**; code, code comments, commit messages and technical terms in **English**.
- Lead with the answer, keep it short. Say directly if his logic is wrong or there is a better option.
- **Do not write code until he explicitly says "делай" / "davay" / "сделай"** — at the discussion stage give ideas and a plan only.
- If something is missing, ask **one** clarifying question.
- Finance / analytics: always show formulas and the calculation so he can verify.
- Stack he knows (do not explain basics): Django, FastAPI, Flutter/FlutterFlow, SQLite, Firebase, 1C.

## Architecture

```
stockapi (separate repo KamolCoder/stockapi, FastAPI)
   │  read-only X-API-Key: products, prices, real stock per branch
   ▼
backend/ (Django 5.1 + DRF + Celery)  ◄── Flutter app (JWT)
   catalog    sync from stockapi, product cards (variants = SKU), photos (WebP 1200 + 400 thumb)
   customers  custom User (phone is USERNAME_FIELD), SMS OTP (Eskiz), pets, addresses, roles
   delivery   zones (polygons), courier providers: yandex | manual, Shipment
   orders     quote, reservation, status machine, branch picker panel /staff/
   payments   Payme Merchant API (JSON-RPC, tiyin), Click SHOP API (prepare/complete, md5 sign)
   panel      operator panel /panel/ (overview, analytics, catalog, orders, refs, sync log)
```

There is **no link to 1C** in this project. stockapi is the only source of products, prices and stock.
Photos for the app live only in Django (stockapi photos are for staff, do not import them).

## Business rules that must not break

- **Availability** = stockapi `real_quantity` − Σ quantities of reserving orders (`Order.reserving_q`).
  After "assembled, receipt printed" the reservation is kept `SALES_SYNC_LAG_MIN` more minutes, because the till sale
  reaches stockapi with a delay. Changing this risks overselling.
- Order status changes only via `apps/orders/services.py` / `Order.set_status` (writes `OrderEvent`, timestamps,
  refund flag). Never assign `order.status = ...` directly outside tests/seed.
- One order = one branch: nearest delivery-enabled branch within `zone.max_branch_km` that has **all** lines.
- Courier is requested **automatically** when the picker presses "Собрано" (`finish_assembly` → Celery `request_courier`).
- Money is `Decimal`, never float. Payme amounts are in **tiyin** (`order.amount_tiyin`). UZS has no cents in UI.
- Canceling a paid order sets `payment_status=refund_required`; refunds are done manually in Payme/Click cabinets.
- Analytics "realized order" = `paid_at` set and status ≠ canceled. Keep formulas in `apps/panel/analytics.py`
  docstring and the README table in sync when changing them.

## Commands (run from `backend/`)

```bash
scripts/check.sh                       # ruff + migrations check + OpenAPI schema + all tests — run before every commit
python manage.py test tests.test_orders  # one module
python manage.py makemigrations        # after any model change, commit the migration
python manage.py stockapi_sync [--full]
python manage.py import_categories <dump.json>  # category tree from a dumpdata file; safe to re-run
python manage.py seed_demo             # demo data into an EMPTY dev DB (DEBUG=1); login 998900000000 / admin12345
DEBUG=1 python manage.py runserver
```

In cloud sessions the virtualenv is `backend/.venv` (created by the environment setup script); use `.venv/bin/python`.
With `DEBUG=1` or under `manage.py test` Celery runs tasks eagerly — no Redis needed.

## Conventions

- UI texts (templates, API error messages) in Russian; identifiers and comments in English.
- Panel/staff templates: plain Django templates, no JS frameworks; reuse CSS variables from `templates/panel/base.html`.
- Charts in the panel are server-side SVG (`apps/panel/charts.py`), single series, brand orange.
- Tests live in `backend/tests/`, factories in `tests/factories.py`, base class `tests/base.py` (temp MEDIA_ROOT).
  Mock stockapi (`apps.orders.services.refresh_stock`) — tests must not hit the network.
- Mobile mockups: `design/mockups/NN-name.html` → PNG via `node design/mockups/shot.js` (see the `mockup` skill).
- Docker services: web (gunicorn), worker + beat (Celery), db (Postgres 16), redis. Exactly one `beat`.

## Git

Work on the branch you are given, commit with clear English messages, push with `git push -u origin <branch>`.
Do not open PRs unless asked.
