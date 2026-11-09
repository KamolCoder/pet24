---
name: demo-data
description: Spin up the Pet24 backend locally with demo data and show the operator panel or staff panel on screenshots. Use when the user wants to see how the panel / analytics / staff screen looks, or to visually check a template change.
---

# Demo backend + screenshots

1. From `backend/` (use `.venv/bin/python` if present), with a throwaway DB and media dir:
   ```bash
   rm -f db.sqlite3
   export DEBUG=1 MEDIA_ROOT=/tmp/pet24-demo-media
   python manage.py migrate -v0 && python manage.py seed_demo
   setsid nohup python manage.py runserver 8765 --noreload > /tmp/pet24-runserver.log 2>&1 < /dev/null &
   ```
   (`setsid nohup … --noreload` keeps the server alive between shell calls.)
2. Log in with Playwright at `http://127.0.0.1:8765/panel/login/` — phone `900000000`, password `admin12345` —
   then screenshot the pages you need (viewport 1360×900; deviceScaleFactor 2 for images shown to the user,
   1 for your own checks). Staff panel: `/staff/` (the same login works for an operator).
3. Look at every screenshot yourself: overlapping text, clipped numbers, wrong colors, 500 errors
   (check `/tmp/pet24-runserver.log` for tracebacks).
4. When done: `pkill -f "runserver 8765"; rm -f db.sqlite3`. Never commit `db.sqlite3` or media.

Demo data: 4 branches (3 deliver), 1 zone, 14 cards / 28 SKU, 23 SKU in the queue, 40 customers,
260 orders over 45 days (problems, cancels, refunds), courier costs on shipments — every analytics block is non-empty.
