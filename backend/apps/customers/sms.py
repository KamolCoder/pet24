import logging

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

ESKIZ_URL = "https://notify.eskiz.uz/api"


def send_sms(phone: str, text: str) -> None:
    if settings.SMS_BACKEND == "eskiz":
        _eskiz_send(phone, text)
    else:
        log.warning("SMS to +%s: %s", phone, text)


def _eskiz_token(force: bool = False) -> str:
    token = None if force else cache.get("eskiz_token")
    if token:
        return token
    r = requests.post(
        f"{ESKIZ_URL}/auth/login",
        data={"email": settings.ESKIZ_EMAIL, "password": settings.ESKIZ_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    token = r.json()["data"]["token"]
    cache.set("eskiz_token", token, 60 * 60 * 24 * 25)  # token lives 30 days
    return token


def _eskiz_send(phone: str, text: str) -> None:
    payload = {"mobile_phone": phone, "message": text, "from": settings.ESKIZ_FROM}
    for force in (False, True):
        r = requests.post(
            f"{ESKIZ_URL}/message/sms/send",
            data=payload,
            headers={"Authorization": f"Bearer {_eskiz_token(force)}"},
            timeout=15,
        )
        if r.status_code != 401:
            r.raise_for_status()
            return
    r.raise_for_status()
