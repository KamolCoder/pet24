from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.customers.models import Address

from .models import Order, OrderItem


class LineSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=999)


class QuoteRequestSerializer(serializers.Serializer):
    items = LineSerializer(many=True, allow_empty=False)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)


class AddressInputSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=500)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    entrance = serializers.CharField(max_length=20, required=False, allow_blank=True)
    floor = serializers.CharField(max_length=20, required=False, allow_blank=True)
    apartment = serializers.CharField(max_length=20, required=False, allow_blank=True)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


class OrderCreateSerializer(serializers.Serializer):
    items = LineSerializer(many=True, allow_empty=False)
    address_id = serializers.IntegerField(required=False)
    address = AddressInputSerializer(required=False)
    payment_method = serializers.ChoiceField(choices=Order.PaymentMethod.choices)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, data):
        if "address_id" in data:
            addr = Address.objects.filter(pk=data["address_id"], user=self.context["request"].user).first()
            if addr is None:
                raise serializers.ValidationError({"address_id": "Адрес не найден"})
            data["address"] = {
                f: getattr(addr, f) for f in ("address", "lat", "lng", "entrance", "floor", "apartment", "comment")
            }
        elif "address" not in data:
            raise serializers.ValidationError("Нужен address_id или address")
        return data


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ["product_id", "name", "price", "quantity", "amount"]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    status_display = serializers.CharField(source="get_status_display")
    branch = serializers.CharField(source="branch.name")
    courier = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "number", "status", "status_display", "payment_method", "payment_status",
            "items_total", "delivery_price", "total", "address", "entrance", "floor", "apartment",
            "address_comment", "comment", "branch", "courier", "can_cancel", "items",
            "created_at", "paid_at", "delivered_at",
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_courier(self, obj):
        s = obj.active_shipment
        if not s:
            return None
        return {"status": s.status, "name": s.courier_name, "phone": s.courier_phone, "tracking_url": s.tracking_url}

    def get_can_cancel(self, obj) -> bool:
        return obj.status in Order.CUSTOMER_CANCELABLE
