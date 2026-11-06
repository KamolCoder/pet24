"""Read-only client for stockapi (products, prices, real stock per branch)."""
import logging
from decimal import Decimal
from typing import Iterator

import requests
from django.conf import settings

log = logging.getLogger(__name__)

PAGE = 1000


class StockApiError(Exception):
    pass


class StockApiClient:
    def __init__(self, base_url: str | None = None, key: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or settings.STOCKAPI_URL).rstrip("/")
        self.key = key or settings.STOCKAPI_KEY
        self.timeout = timeout or settings.STOCKAPI_TIMEOUT
        if not self.base_url or not self.key:
            raise StockApiError("STOCKAPI_URL / STOCKAPI_KEY are not configured")
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.key, "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            r = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise StockApiError(f"stockapi unreachable: {e}") from e
        if r.status_code != 200:
            raise StockApiError(f"stockapi {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def branches(self) -> list[dict]:
        return self._get("/api/stock/branches")["items"]

    def iter_products(self, **params) -> Iterator[dict]:
        offset = 0
        while True:
            data = self._get("/api/stock/products", {**params, "limit": PAGE, "offset": offset})
            items = data["items"]
            yield from items
            offset += len(items)
            if not items or offset >= data["total"]:
                break

    def products_by_ids(self, external_ids: list[str], branch: str | None = None) -> list[dict]:
        out = []
        for i in range(0, len(external_ids), PAGE):
            chunk = external_ids[i:i + PAGE]
            params = {"external_ids": ",".join(chunk), "limit": PAGE}
            if branch:
                params["branch"] = branch
            out += self._get("/api/stock/products", params)["items"]
        return out


def parse_qty(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.001"))
