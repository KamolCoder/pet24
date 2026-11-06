from django.contrib import admin

from .models import Order, OrderEvent, OrderItem


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "external_id", "name", "barcode", "price", "quantity"]
    can_delete = False


class EventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ["created_at", "from_status", "to_status", "user", "note"]
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["number", "created_at", "branch", "status", "payment_method", "payment_status", "total", "customer_phone"]
    list_filter = ["status", "payment_status", "payment_method", "branch", "zone"]
    search_fields = ["number", "customer_phone", "customer_name", "address"]
    date_hierarchy = "created_at"
    inlines = [ItemInline, EventInline]
    readonly_fields = [
        "number", "user", "branch", "zone", "status", "payment_method", "items_total", "delivery_price", "total",
        "customer_phone", "lat", "lng", "picker", "created_at", "paid_at", "assembling_at", "assembled_at",
        "delivered_at", "canceled_at",
    ]
    # status is changed only via the staff panel / services so the history and side effects stay consistent
