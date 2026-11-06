# Pet24 backend

Django-бэкенд мобильного приложения зоомагазина: каталог, доставка, заказы, оплата, панель сборщика для филиалов.

```
stockapi ──(X-API-Key, только чтение)──► pet24 backend ◄── Flutter-приложение
 товары, цены, реальные остатки           карточки, фото, клиенты, заказы,
                                          резервы, доставка, оплата
```

## Модули

| App | Что делает |
|---|---|
| `catalog` | Синк из stockapi: филиалы, SKU, цены, `real_quantity`. Контент: категории, бренды, виды животных, карточки (фасовки = SKU), фото (WebP 1200 px + превью 400 px) |
| `customers` | Вход по телефону через SMS-код (Eskiz), JWT, профиль, питомцы, адреса. Роли: покупатель / сборщик филиала / оператор |
| `delivery` | Зоны доставки (полигоны), заявки курьерам: `yandex` (Яндекс Доставка API) или `manual` (оператор заказывает сам) |
| `orders` | Расчёт корзины, выбор филиала, резервы, статусы заказа, веб-панель сборщика `/staff/` |
| `payments` | Payme Merchant API, Click SHOP API |
| `panel` | Своя админка `/panel/` для операторов: обзор, аналитика, заказы, каталог и фото, очередь SKU, справочники, филиалы, зоны, клиенты, сотрудники, журнал синка |

## Панель `/panel/`

Вход — оператор (роль «Оператор») или суперпользователь, по телефону и паролю. Стандартная `/admin/` остаётся запасной.

**Аналитика** (`/panel/analytics/`, период + филиал, сравнение с предыдущим периодом той же длины, CSV):

| Показатель | Формула |
|---|---|
| Выручка | Σ `total` заказов, которые оплачены и не отменены |
| Заказы | количество таких заказов |
| Средний чек | выручка / заказы |
| Конверсия в оплату | заказы с `paid_at` / созданные |
| Доля отмен | отменённые / созданные |
| Повторные покупатели | покупатели с ≥ 2 заказами в периоде / все покупатели периода |
| Новые покупатели | первый оплаченный заказ — в этом периоде |
| Маржа доставки | Σ `delivery_price` − Σ стоимость курьеров (из заявок службы доставки) |
| Время | медианы: сборка = собран − оплачен, в пути = доставлен − собран |

Разрезы: по дням (график + таблица), по филиалам, по способам оплаты, по зонам доставки, топ товаров.

## Как проходит заказ

```
new ──оплата──► paid ──«Начать сборку»──► assembling ──«Собрано, чек пробит»──► courier_search
                                                                                       │ (курьер вызывается автоматически)
                                       delivered ◄── delivering ◄── courier_assigned ◄─┘
любой этап ──► problem (оператор)          new/paid ──► canceled
```

- **Выбор филиала:** ближайший к адресу филиал с `delivery_enabled` и координатами в пределах `max_branch_km` зоны, где есть **все** позиции.
- **Резерв:** `доступно = real_quantity (stockapi) − Σ заказов в статусах new/paid/assembling`. После «Собрано, чек пробит» продажа приходит в stockapi с задержкой, поэтому резерв держится ещё `SALES_SYNC_LAG_MIN` минут.
- **Регламент филиала:** собрал → пробил чек на кассе → нажал «Собрано». Без чека остатки в stockapi разойдутся.
- **Неоплаченный заказ** отменяется через `ORDER_PAYMENT_TIMEOUT_MIN` минут, резерв освобождается.
- **Отмена оплаченного заказа** → `payment_status = refund_required`, возврат делается в кабинете Payme/Click.
- **Курьер не найден** за `COURIER_SEARCH_TIMEOUT_MIN` минут или служба вернула ошибку → `problem`. Оператор в `/staff/` вызывает курьера повторно.

## Запуск локально

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # DEBUG=1, DATABASE_URL можно удалить → SQLite
python manage.py migrate
python manage.py createsuperuser   # телефон 998XXXXXXXXX + пароль
python manage.py stockapi_sync --full
python manage.py runserver
```

При `DEBUG=1` задачи Celery выполняются синхронно, Redis не нужен. SMS-коды пишутся в лог (`SMS_BACKEND=console`).

Тесты: `python manage.py test`

## Прод (Docker)

```bash
cd backend
cp .env.example .env   # заполнить
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py stockapi_sync --full
```

nginx: проксировать на `127.0.0.1:8020`, `client_max_body_size 20m`. Фото отдавать напрямую:

```nginx
location /media/ { alias /path/to/pet24/backend/media/; expires 30d; }
```

Celery beat: остатки и цены каждые 5 минут, филиалы раз в час, отмена неоплаченных заказов раз в минуту, опрос курьерских заявок раз в 2 минуты (страховка на случай потерянного callback).

## Первичная настройка (панель `/panel/`)

1. **stockapi:** в суперадминке stockapi создать отдельный ключ API для pet24 → `STOCKAPI_KEY`.
2. **Филиалы:** у каждого филиала заполнить адрес, телефон, координаты и включить «Собирает заказы на доставку».
3. **Зоны доставки:** полигон в формате `[[lat, lng], ...]`, цена, «бесплатно от», минимальная сумма, максимальное расстояние до филиала.
4. **Каталог:** виды животных → категории → бренды.
5. **Карточки товаров:** «Очередь SKU» → отметить фасовки одного товара → «Создать карточку». В карточке загрузить фото, выбрать категорию, заполнить описание и нажать «Опубликовать». В приложении видны только опубликованные карточки с фото, активными SKU и ценой больше 0.
6. **Сотрудники:** пользователь с ролью «Сборщик филиала» + филиал + пароль → вход в `/staff/`. Роль «Оператор» видит все филиалы и может отменять заказы и повторно вызывать курьера.
7. **Оплата:** в кабинете Payme endpoint `https://<домен>/api/payments/payme/`, поле счёта `order_id`. В Click: Prepare `…/api/payments/click/prepare/`, Complete `…/api/payments/click/complete/`.
8. **Яндекс Доставка:** OAuth-токен B2B-кабинета → `YANDEX_DELIVERY_TOKEN`, `COURIER_PROVIDER=yandex`. Перед запуском сверить поля заявки с вашим договором (`apps/delivery/providers/yandex.py`).

## API для приложения

Swagger: `/api/docs/`, схема OpenAPI: `/api/schema/` (из неё можно сгенерировать Dart-клиент).

| Метод | Путь | |
|---|---|---|
| POST | `/api/auth/otp/request/` | `{phone}` → SMS-код |
| POST | `/api/auth/otp/verify/` | `{phone, code}` → `access`, `refresh` |
| POST | `/api/auth/token/refresh/` | обновить токен |
| GET/PATCH | `/api/auth/me/` | профиль, `fcm_token` |
| CRUD | `/api/auth/pets/`, `/api/auth/addresses/` | питомцы, адреса |
| GET | `/api/catalog/pet-types/`, `categories/`, `brands/`, `branches/` | справочники |
| GET | `/api/catalog/products/` | `q, pet_type, category, brand, price_min, price_max, in_stock, attr_<name>, ordering` |
| GET | `/api/catalog/products/<slug>/` | карточка |
| GET | `/api/delivery/zones/` | зоны для карты |
| POST | `/api/orders/quote/` | `{items:[{product_id, quantity}], lat, lng}` → филиал, доставка, итог, чего не хватает |
| POST | `/api/orders/` | `{items, address_id \| address, payment_method}` → заказ + `payment_url` |
| GET | `/api/orders/`, `/api/orders/<id>/` | мои заказы, статус, курьер |
| GET | `/api/orders/<id>/pay/` | ссылка на оплату ещё раз |
| POST | `/api/orders/<id>/cancel/` | отмена до начала сборки |
