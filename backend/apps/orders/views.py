from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.services import payment_url

from . import services
from .models import Order
from .serializers import OrderCreateSerializer, OrderSerializer, QuoteRequestSerializer


def _error(e: services.OrderError):
    return Response({"detail": str(e), "code": e.code, **e.extra}, status=status.HTTP_400_BAD_REQUEST)


class QuoteView(APIView):
    """Cart check before checkout: zone, branch, delivery price, what is missing."""

    @extend_schema(request=QuoteRequestSerializer, responses=inline_serializer("Quote", {
        "zone": serializers.CharField(), "branch": serializers.DictField(),
        "items_total": serializers.DecimalField(12, 2), "delivery_price": serializers.DecimalField(12, 2),
        "free_from": serializers.DecimalField(12, 2, allow_null=True), "min_order": serializers.DecimalField(12, 2),
        "min_order_ok": serializers.BooleanField(), "total": serializers.DecimalField(12, 2),
        "missing": serializers.ListField(child=serializers.DictField()),
        "lines": serializers.ListField(child=serializers.DictField())}))
    def post(self, request):
        s = QuoteRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            q = services.make_quote(d["items"], d["lat"], d["lng"])
        except services.OrderError as e:
            return _error(e)
        return Response({
            "zone": q.zone.name,
            "branch": {"id": q.branch.id, "name": q.branch.name},
            "items_total": q.items_total,
            "delivery_price": q.delivery_price,
            "free_from": q.zone.free_from,
            "min_order": q.zone.min_order,
            "min_order_ok": q.min_order_ok,
            "total": q.total,
            "missing": q.missing,
            "lines": [{"product_id": ln.product.id, "price": ln.product.price, "quantity": ln.quantity} for ln in q.lines],
        })


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).select_related("branch").prefetch_related("items", "shipments")

    @extend_schema(request=OrderCreateSerializer, responses=OrderSerializer)
    def create(self, request):
        s = OrderCreateSerializer(data=request.data, context={"request": request})
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            order = services.create_order(request.user, d["items"], d["address"], d["payment_method"], d.get("comment", ""))
        except services.OrderError as e:
            return _error(e)
        data = OrderSerializer(order).data
        data["payment_url"] = payment_url(order)
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def pay(self, request, pk=None):
        """Payment link again (if the user closed the payment page)."""
        order = self.get_object()
        if order.status != Order.Status.NEW:
            return Response({"detail": "Заказ уже оплачен или отменён"}, status=400)
        return Response({"payment_url": payment_url(order)})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status not in Order.CUSTOMER_CANCELABLE:
            return Response({"detail": "Заказ уже собирается, отменить можно через оператора"}, status=400)
        services.cancel_order(order, request.user, "отменён покупателем")
        return Response(OrderSerializer(order).data)
