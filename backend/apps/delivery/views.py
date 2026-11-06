import hmac

from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DeliveryZone, Shipment
from .providers.yandex import callback_signature
from .tasks import refresh_shipment


class ZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryZone
        fields = ["id", "name", "polygon", "price", "free_from", "min_order"]


class ZoneList(generics.ListAPIView):
    """Delivery zones for drawing on the map in the app."""

    queryset = DeliveryZone.objects.filter(is_active=True)
    serializer_class = ZoneSerializer
    pagination_class = None


@extend_schema(exclude=True)
class YandexCallback(APIView):
    """Yandex notifies about a claim change; the claim is re-read from the API, payload is not trusted."""

    authentication_classes = []

    def _handle(self, request):
        sid, sig = request.query_params.get("sid", ""), request.query_params.get("sig", "")
        if not sid or not hmac.compare_digest(sig, callback_signature(sid)):
            return Response({"detail": "bad signature"}, status=403)
        if not Shipment.objects.filter(pk=sid).exists():
            return Response({"detail": "unknown"}, status=404)
        refresh_shipment.delay(sid)
        return Response({"ok": True})

    def post(self, request):
        return self._handle(request)

    def get(self, request):
        return self._handle(request)
