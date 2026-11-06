from django.contrib import admin

from .models import ClickTransaction, PaymeTransaction


@admin.register(PaymeTransaction)
class PaymeTransactionAdmin(admin.ModelAdmin):
    list_display = ["payme_id", "order", "amount", "state", "reason", "create_time", "perform_time"]
    list_filter = ["state"]
    search_fields = ["payme_id", "order__number"]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ClickTransaction)
class ClickTransactionAdmin(admin.ModelAdmin):
    list_display = ["click_trans_id", "order", "amount", "status", "error", "created_at"]
    list_filter = ["status"]
    search_fields = ["click_trans_id", "order__number"]

    def has_change_permission(self, request, obj=None):
        return False
