import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from .geo import point_in_polygon


def validate_polygon(value):
    if not isinstance(value, list) or len(value) < 3:
        raise ValidationError("Полигон — список минимум из 3 точек [lat, lng]")
    for p in value:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p)):
            raise ValidationError(f"Неверная точка {p!r}, нужен формат [41.31, 69.27]")


class DeliveryZone(models.Model):
    name = models.CharField("Название", max_length=100)
    polygon = models.JSONField(
        "Полигон", validators=[validate_polygon],
        help_text="[[lat, lng], ...] — можно нарисовать на geojson.io и вставить координаты (поменяв местами lng/lat)",
    )
    price = models.DecimalField("Стоимость доставки", max_digits=10, decimal_places=2)
    free_from = models.DecimalField(
        "Бесплатно от суммы", max_digits=12, decimal_places=2, null=True, blank=True,
    )
    min_order = models.DecimalField("Минимальная сумма заказа", max_digits=12, decimal_places=2, default=Decimal("0"))
    max_branch_km = models.DecimalField(
        "Макс. расстояние до филиала, км", max_digits=5, decimal_places=1, default=Decimal("15"),
    )
    priority = models.IntegerField("Приоритет", default=0, help_text="При пересечении зон берётся с большим")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Зона доставки"
        verbose_name_plural = "Зоны доставки"
        ordering = ["-priority", "name"]

    def __str__(self):
        return self.name

    def contains(self, lat, lng) -> bool:
        return point_in_polygon(lat, lng, self.polygon)

    def delivery_price(self, items_total: Decimal) -> Decimal:
        if self.free_from is not None and items_total >= self.free_from:
            return Decimal("0")
        return self.price

    @classmethod
    def find(cls, lat, lng) -> "DeliveryZone | None":
        return next((z for z in cls.objects.filter(is_active=True) if z.contains(lat, lng)), None)


class Shipment(models.Model):
    """Courier job at an external delivery service."""

    class Status(models.TextChoices):
        CREATED = "created", "Создана"
        SEARCHING = "searching", "Поиск курьера"
        ASSIGNED = "assigned", "Курьер назначен"
        PICKED_UP = "picked_up", "Курьер забрал заказ"
        DELIVERED = "delivered", "Доставлено"
        FAILED = "failed", "Не выполнено"
        CANCELED = "canceled", "Отменено"

    ACTIVE = (Status.CREATED, Status.SEARCHING, Status.ASSIGNED, Status.PICKED_UP)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # also idempotency key
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="shipments")
    provider = models.CharField(max_length=30)
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    raw_status = models.CharField(max_length=50, blank=True)
    cost = models.DecimalField("Стоимость у службы", max_digits=10, decimal_places=2, null=True, blank=True)
    courier_name = models.CharField(max_length=200, blank=True)
    courier_phone = models.CharField(max_length=50, blank=True)
    tracking_url = models.URLField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заявка курьеру"
        verbose_name_plural = "Заявки курьерам"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider}:{self.external_id or self.id}"

    @property
    def is_active(self):
        return self.status in self.ACTIVE
