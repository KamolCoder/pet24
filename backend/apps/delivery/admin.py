from django.contrib import admin, messages

from .models import DeliveryZone, Shipment
from .services import refresh_shipment, sync_order


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ["name", "price", "free_from", "min_order", "max_branch_km", "priority", "is_active"]
    list_editable = ["price", "free_from", "min_order", "is_active"]


def _set_status(status):
    def action(modeladmin, request, queryset):
        for s in queryset.filter(provider="manual"):
            s.status = status
            s.save()
            sync_order(s)
        modeladmin.message_user(request, "Готово (только для ручных заявок)", messages.SUCCESS)

    action.short_description = f"Ручная заявка → {Shipment.Status(status).label}"
    action.__name__ = f"set_{status}"
    return action


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ["order", "provider", "status", "raw_status", "cost", "courier_name", "courier_phone", "created_at"]
    list_filter = ["status", "provider"]
    search_fields = ["order__number", "external_id"]
    readonly_fields = ["id", "order", "provider", "external_id", "version", "raw_status", "error", "created_at", "updated_at"]
    actions = [
        "refresh",
        _set_status(Shipment.Status.ASSIGNED),
        _set_status(Shipment.Status.PICKED_UP),
        _set_status(Shipment.Status.DELIVERED),
        _set_status(Shipment.Status.FAILED),
    ]

    @admin.action(description="Обновить статус у службы доставки")
    def refresh(self, request, queryset):
        for s in queryset:
            refresh_shipment(s)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if "status" in form.changed_data:
            sync_order(obj)
