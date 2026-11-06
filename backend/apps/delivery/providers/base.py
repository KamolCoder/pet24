class ProviderError(Exception):
    pass


class CourierProvider:
    """Interface of an external courier service. Methods mutate and save the Shipment."""

    name = ""

    def create(self, shipment) -> None:
        raise NotImplementedError

    def refresh(self, shipment) -> None:
        raise NotImplementedError

    def cancel(self, shipment) -> None:
        raise NotImplementedError
