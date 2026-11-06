from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Ожидает оплаты"
        PAID = "paid", "Оплачен, ждёт сборки"
        ASSEMBLING = "assembling", "Собирается"
        COURIER_SEARCH = "courier_search", "Собран, ищем курьера"
        COURIER_ASSIGNED = "courier_assigned", "Курьер едет в филиал"
        DELIVERING = "delivering", "В пути к клиенту"
        DELIVERED = "delivered", "Доставлен"
        PROBLEM = "problem", "Проблема (нужен оператор)"
        CANCELED = "canceled", "Отменён"

    class PaymentMethod(models.TextChoices):
        PAYME = "payme", "Payme"
        CLICK = "click", "Click"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Не оплачен"
        PAID = "paid", "Оплачен"
        REFUND_REQUIRED = "refund_required", "Нужен возврат"
        REFUNDED = "refunded", "Возвращён"

    S = Status
    # status -> statuses it may move to
    TRANSITIONS = {
        S.NEW: {S.PAID, S.CANCELED},
        S.PAID: {S.ASSEMBLING, S.PROBLEM, S.CANCELED},
        S.ASSEMBLING: {S.COURIER_SEARCH, S.PROBLEM, S.CANCELED},
        S.COURIER_SEARCH: {S.COURIER_ASSIGNED, S.DELIVERING, S.DELIVERED, S.PROBLEM, S.CANCELED},
        S.COURIER_ASSIGNED: {S.COURIER_SEARCH, S.DELIVERING, S.DELIVERED, S.PROBLEM, S.CANCELED},
        S.DELIVERING: {S.DELIVERED, S.PROBLEM},
        S.PROBLEM: {S.PAID, S.ASSEMBLING, S.COURIER_SEARCH, S.DELIVERING, S.DELIVERED, S.CANCELED},
        S.DELIVERED: set(),
        S.CANCELED: set(),
    }
    CUSTOMER_CANCELABLE = {S.NEW, S.PAID}
    PRE_ASSEMBLY = {S.NEW, S.PAID, S.ASSEMBLING}

    number = models.CharField("Номер", max_length=20, unique=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    branch = models.ForeignKey("catalog.Branch", on_delete=models.PROTECT, related_name="orders", verbose_name="Филиал")
    zone = models.ForeignKey("delivery.DeliveryZone", null=True, on_delete=models.SET_NULL, verbose_name="Зона")
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    payment_method = models.CharField("Оплата", max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(
        "Статус оплаты", max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
    )

    items_total = models.DecimalField("Товары", max_digits=12, decimal_places=2)
    delivery_price = models.DecimalField("Доставка", max_digits=10, decimal_places=2)
    total = models.DecimalField("Итого", max_digits=12, decimal_places=2)

    customer_name = models.CharField("Имя", max_length=200, blank=True)
    customer_phone = models.CharField("Телефон", max_length=20)
    address = models.CharField("Адрес", max_length=500)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    entrance = models.CharField("Подъезд", max_length=20, blank=True)
    floor = models.CharField("Этаж", max_length=20, blank=True)
    apartment = models.CharField("Квартира", max_length=20, blank=True)
    address_comment = models.CharField("Комментарий курьеру", max_length=500, blank=True)
    comment = models.TextField("Комментарий к заказу", blank=True)

    picker = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="picked_orders", verbose_name="Сборщик",
    )
    problem_note = models.TextField("Описание проблемы", blank=True)
    cancel_reason = models.CharField("Причина отмены", max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    assembling_at = models.DateTimeField(null=True, blank=True)
    assembled_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Заказ {self.number}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"{self.pk:06d}"
            super().save(update_fields=["number"])

    @property
    def amount_tiyin(self) -> int:
        return int(self.total * 100)

    @property
    def active_shipment(self):
        return self.shipments.order_by("-created_at").first()

    def can_move_to(self, new_status) -> bool:
        return new_status in self.TRANSITIONS[self.status]

    def set_status(self, new_status, by=None, note: str = "") -> None:
        if new_status == self.status:
            return
        if not self.can_move_to(new_status):
            raise ValueError(f"Нельзя перевести заказ из «{self.get_status_display()}» в «{new_status}»")
        now = timezone.now()
        old = self.status
        self.status = new_status
        stamp = {
            self.S.PAID: "paid_at", self.S.ASSEMBLING: "assembling_at", self.S.COURIER_SEARCH: "assembled_at",
            self.S.DELIVERED: "delivered_at", self.S.CANCELED: "canceled_at",
        }.get(new_status)
        if stamp and getattr(self, stamp) is None:
            setattr(self, stamp, now)
        if new_status == self.S.PROBLEM:
            self.problem_note = note
        if new_status == self.S.CANCELED:
            self.cancel_reason = note
            if self.payment_status == self.PaymentStatus.PAID:
                self.payment_status = self.PaymentStatus.REFUND_REQUIRED
        self.save()
        OrderEvent.objects.create(order=self, from_status=old, to_status=new_status, user=by, note=note[:500])

    @classmethod
    def reserving_q(cls, prefix: str = "") -> Q:
        """Orders whose goods must be held back from stockapi's real stock.

        Before assembly the goods are on the shelf -> reserved. After the receipt is printed ("assembled")
        stockapi learns about the sale only after the till sync, so we keep the reservation for
        SALES_SYNC_LAG_MIN minutes to avoid selling the same item twice.
        """
        p = prefix
        lag_from = timezone.now() - timedelta(minutes=settings.SALES_SYNC_LAG_MIN)
        return (
            Q(**{f"{p}status__in": list(cls.PRE_ASSEMBLY)})
            | Q(**{f"{p}status": cls.S.PROBLEM, f"{p}assembled_at__isnull": True})
            | (Q(**{f"{p}assembled_at__gte": lag_from}) & ~Q(**{f"{p}status": cls.S.CANCELED}))
        )


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", null=True, on_delete=models.SET_NULL)
    external_id = models.CharField(max_length=100)
    name = models.CharField(max_length=500)
    barcode = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Позиция"
        verbose_name_plural = "Позиции"

    @property
    def amount(self) -> Decimal:
        return self.price * self.quantity


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
