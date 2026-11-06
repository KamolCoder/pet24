from django.conf import settings

from .base import CourierProvider, ProviderError
from .manual import ManualProvider
from .yandex import YandexProvider

PROVIDERS: dict[str, type[CourierProvider]] = {
    ManualProvider.name: ManualProvider,
    YandexProvider.name: YandexProvider,
}


def get_provider(name: str | None = None) -> CourierProvider:
    return PROVIDERS[name or settings.COURIER_PROVIDER]()


__all__ = ["CourierProvider", "ProviderError", "get_provider"]
