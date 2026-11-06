"""Yandex Delivery (B2B cargo claims API v2).

Flow: claims/create -> (estimating) -> ready_for_approval -> claims/accept -> performer_lookup -> ...
Yandex calls callback_url on every status change; we then re-read the claim via claims/info.
Docs: https://yandex.ru/support2/delivery-profile/ru/api/express/ — check field names against your contract.
"""
import hashlib
import hmac
import logging
from decimal import Decimal

import requests
from django.conf import settings

from .base import CourierProvider, ProviderError

log = logging.getLogger(__name__)

API = "/b2b/cargo/integration/v2"

STATUS_MAP = {
    "new": "searching",
    "estimating": "searching",
    "ready_for_approval": "searching",
    "accepted": "searching",
    "performer_lookup": "searching",
    "performer_draft": "searching",
    "performer_found": "assigned",
    "pickup_arrived": "assigned",
    "ready_for_pickup_confirmation": "assigned",
    "pickuped": "picked_up",
    "delivery_arrived": "picked_up",
    "ready_for_delivery_confirmation": "picked_up",
    "pay_waiting": "picked_up",
    "delivered": "delivered",
    "delivered_finish": "delivered",
    "returning": "failed",
    "return_arrived": "failed",
    "ready_for_return_confirmation": "failed",
    "returned": "failed",
    "returned_finish": "failed",
    "failed": "failed",
    "estimating_failed": "failed",
    "performer_not_found": "failed",
    "cancelled_by_taxi": "failed",
    "cancelled_with_items_on_hands": "failed",
    "cancelled": "canceled",
    "cancelled_with_payment": "canceled",
}


def callback_signature(shipment_id) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"yandex:{shipment_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _phone(raw: str) -> str:
    digits = "".join(c for c in raw or "" if c.isdigit())
    return f"+{digits}" if digits else ""


class YandexProvider(CourierProvider):
    name = "yandex"

    def __init__(self):
        if not settings.YANDEX_DELIVERY_TOKEN:
            raise ProviderError("YANDEX_DELIVERY_TOKEN is not configured")
        self.base = settings.YANDEX_DELIVERY_URL.rstrip("/") + API
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.YANDEX_DELIVERY_TOKEN}",
            "Accept-Language": "ru",
        })

    def _post(self, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        try:
            r = self.session.post(f"{self.base}{path}", params=params, json=json or {}, timeout=20)
        except requests.RequestException as e:
            raise ProviderError(f"yandex unreachable: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"yandex {path} -> {r.status_code}: {r.text[:500]}")
        return r.json()

    # --- payload ---

    def build_claim(self, shipment) -> dict:
        order = shipment.order
        branch = order.branch
        items = [
            {
                "title": item.name[:250],
                "quantity": max(1, int(item.quantity)),
                "cost_value": str(item.price),
                "cost_currency": "UZS",
                "pickup_point": 1,
                "droppof_point": 2,
                **({"weight": round(item.product.weight_g / 1000, 3)} if item.product and item.product.weight_g else {}),
            }
            for item in order.items.select_related("product")
        ]
        callback = (
            f"{settings.PUBLIC_BASE_URL}/api/delivery/yandex/callback/"
            f"?sid={shipment.id}&sig={callback_signature(shipment.id)}"
        )
        return {
            "items": items,
            "route_points": [
                {
                    "point_id": 1,
                    "visit_order": 1,
                    "type": "source",
                    "skip_confirmation": True,
                    "contact": {"name": f"Pet24 {branch.name}", "phone": _phone(branch.phone)},
                    "address": {
                        "fullname": branch.address or branch.name,
                        "coordinates": [float(branch.lng), float(branch.lat)],
                    },
                },
                {
                    "point_id": 2,
                    "visit_order": 2,
                    "type": "destination",
                    "skip_confirmation": True,
                    "external_order_id": order.number,
                    "contact": {"name": order.customer_name or "Клиент", "phone": _phone(order.customer_phone)},
                    "address": {
                        "fullname": order.address,
                        "coordinates": [float(order.lng), float(order.lat)],
                        "porch": order.entrance,
                        "sfloor": order.floor,
                        "sflat": order.apartment,
                        "comment": order.address_comment,
                    },
                },
            ],
            "client_requirements": {"taxi_class": settings.YANDEX_TAXI_CLASS},
            "callback_properties": {"callback_url": callback},
            "emergency_contact": {"name": f"Pet24 {branch.name}", "phone": _phone(branch.phone)},
            "comment": f"Заказ {order.number}. {order.address_comment}".strip(),
        }

    # --- interface ---

    def create(self, shipment) -> None:
        data = self._post("/claims/create", {"request_id": str(shipment.id)}, self.build_claim(shipment))
        shipment.external_id = data["id"]
        self._apply(shipment, data)

    def refresh(self, shipment) -> None:
        data = self._post("/claims/info", {"claim_id": shipment.external_id})
        if data.get("status") == "ready_for_approval":
            # price estimated -> confirm the claim, otherwise no courier is searched
            data = self._post("/claims/accept", {"claim_id": shipment.external_id}, {"version": data["version"]})
            data = self._post("/claims/info", {"claim_id": shipment.external_id})
        self._apply(shipment, data)
        if shipment.status == shipment.Status.ASSIGNED and not shipment.courier_phone:
            self._load_courier_phone(shipment)

    def cancel(self, shipment) -> None:
        info = self._post("/claims/cancel-info", {"claim_id": shipment.external_id})
        state = info.get("cancel_state", "free")
        if state == "unavailable":
            raise ProviderError("Яндекс не даёт отменить заявку на этом этапе")
        data = self._post(
            "/claims/cancel", {"claim_id": shipment.external_id},
            {"version": shipment.version, "cancel_state": state},
        )
        self._apply(shipment, data)

    # --- helpers ---

    def _apply(self, shipment, data: dict) -> None:
        raw = data.get("status", "")
        shipment.raw_status = raw
        shipment.status = STATUS_MAP.get(raw, shipment.status)
        shipment.version = data.get("version", shipment.version)
        pricing = data.get("pricing") or {}
        price = pricing.get("final_price") or (pricing.get("offer") or {}).get("price")
        if price:
            shipment.cost = Decimal(str(price))
        performer = data.get("performer_info") or {}
        if performer.get("courier_name"):
            shipment.courier_name = performer["courier_name"]
        if data.get("error_messages"):
            shipment.error = str(data["error_messages"])[:2000]
        shipment.save()

    def _load_courier_phone(self, shipment) -> None:
        try:
            data = self._post("/driver-voiceforwarding", json={"claim_id": shipment.external_id})
        except ProviderError as e:
            log.warning("courier phone for %s: %s", shipment.external_id, e)
            return
        ext = f" доб. {data['ext']}" if data.get("ext") else ""
        shipment.courier_phone = f"{data.get('phone', '')}{ext}"
        shipment.save(update_fields=["courier_phone", "updated_at"])
