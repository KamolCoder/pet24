from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OtpCode, User
from .serializers import (
    AddressSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    PetSerializer,
    UserSerializer,
)
from .sms import send_sms


class OtpRequestView(APIView):
    """Send a 4-digit login code by SMS."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp"

    @extend_schema(request=OtpRequestSerializer, responses=inline_serializer(
        "OtpSent", {"sent": serializers.BooleanField(), "ttl": serializers.IntegerField()}))
    def post(self, request):
        s = OtpRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone = s.validated_data["phone"]
        if OtpCode.last_sent_recently(phone):
            return Response(
                {"detail": "Код уже отправлен, повторите через минуту"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        _, code = OtpCode.issue(phone)
        send_sms(phone, settings.OTP_TEXT.format(code=code))
        return Response({"sent": True, "ttl": settings.OTP_TTL_SEC})


class OtpVerifyView(APIView):
    """Exchange phone + code for JWT pair. Creates the customer on first login."""

    @extend_schema(request=OtpVerifySerializer, responses=inline_serializer("LoginResult", {
        "access": serializers.CharField(), "refresh": serializers.CharField(),
        "is_new": serializers.BooleanField(), "user": UserSerializer()}))
    def post(self, request):
        s = OtpVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone = s.validated_data["phone"]
        if not OtpCode.verify(phone, s.validated_data["code"]):
            return Response({"detail": "Неверный или просроченный код"}, status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(phone=phone).first()
        is_new = user is None
        if is_new:
            user = User.objects.create_user(phone)
        if not user.is_active:
            return Response({"detail": "Аккаунт заблокирован"}, status=status.HTTP_403_FORBIDDEN)
        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_new": is_new,
            "user": UserSerializer(user).data,
        })


class MeView(RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class _OwnedViewSet(viewsets.ModelViewSet):
    lookup_value_regex = r"\d+"
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PetViewSet(_OwnedViewSet):
    serializer_class = PetSerializer


class AddressViewSet(_OwnedViewSet):
    serializer_class = AddressSerializer
