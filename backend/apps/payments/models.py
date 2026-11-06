from django.db import models


class PaymeTransaction(models.Model):
    class State(models.IntegerChoices):
        CREATED = 1, "Создана"
        PERFORMED = 2, "Проведена"
        CANCELED = -1, "Отменена до проведения"
        CANCELED_AFTER_PERFORM = -2, "Отменена после проведения"

    payme_id = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payme_transactions")
    amount = models.BigIntegerField("Сумма, тийин")
    state = models.SmallIntegerField(choices=State.choices, default=State.CREATED)
    reason = models.SmallIntegerField(null=True, blank=True)
    payme_time = models.BigIntegerField()
    create_time = models.BigIntegerField()
    perform_time = models.BigIntegerField(default=0)
    cancel_time = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = "Транзакция Payme"
        verbose_name_plural = "Транзакции Payme"
        ordering = ["-create_time"]


class ClickTransaction(models.Model):
    class Status(models.TextChoices):
        PREPARED = "prepared", "Подготовлена"
        COMPLETED = "completed", "Проведена"
        CANCELED = "canceled", "Отменена"

    click_trans_id = models.CharField(max_length=50, unique=True)
    click_paydoc_id = models.CharField(max_length=50, blank=True)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="click_transactions")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREPARED)
    error = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Транзакция Click"
        verbose_name_plural = "Транзакции Click"
        ordering = ["-created_at"]
