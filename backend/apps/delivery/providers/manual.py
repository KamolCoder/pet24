from .base import CourierProvider


class ManualProvider(CourierProvider):
    """Operator orders the courier by phone/app and moves statuses in the admin."""

    name = "manual"

    def create(self, shipment) -> None:
        shipment.status = shipment.Status.SEARCHING
        shipment.save()

    def refresh(self, shipment) -> None:
        pass

    def cancel(self, shipment) -> None:
        shipment.status = shipment.Status.CANCELED
        shipment.save()
