---
name: mockup
description: Make or update a mobile app screen mockup for Pet24 as HTML and render it to an iPhone-size PNG. Use when the user asks for a screen design, мобильный скриншот, макет экрана, or wants to change an existing mockup.
---

# Mobile mockups

Mockups live in `design/mockups/` as `NN-name.html` (01-home, 02-catalog, 03-product, 04-cart, 05-checkout,
06-order-status, 07-profile …). Each renders to `NN-name.png` next to it. They are the reference the Flutter app is built from.

## Make a screen

1. Copy `design/mockups/01-home.html` as the starting point: it has the status bar, the bottom nav, the CSS variables
   and the card styles. Keep the canvas 390×844 and the same look:
   - brand `--brand:#ff7300`, darker text-safe orange `--brand-d:#e05f00`, light tint `--soft:#fff3e8`;
   - font Inter, background `#f6f6f8`, white cards with 1px `#eceef2` border and 16px radius;
   - icons as inline SVG (no emoji, no external images except the `../../pet24.jpg` logo);
   - prices in сум with spaces: `952 000 сум`; Russian UI text;
   - bottom nav: Главная, Каталог, Корзина (badge), Заказы, Профиль — highlight the current tab.
2. Use realistic Tashkent content (addresses, brands sold in the chain, real-looking prices).
   Product photos are drawn placeholders (simple SVG bags/boxes) until real photos exist.
3. Render: `node design/mockups/shot.js design/mockups/NN-name.html` (Playwright is preinstalled).
4. Open the PNG and check it yourself before showing: nothing overlaps, no text clipped mid-line,
   key info (prices, buttons) visible above the bottom nav. Fix and re-render if needed.
5. Send the PNG to the user and list what is on the screen in 5–8 short points, then ask what to change.
   Make **one screen at a time** unless asked otherwise.
6. Commit the `.html` and `.png` together when the user approves.

The screen must match backend capabilities — check the API in `backend/README.md` (variants = SKU, delivery quote,
order statuses from `apps/orders/models.py`). If a screen needs data the API does not have, say so.
