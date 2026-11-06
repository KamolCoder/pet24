from rest_framework import serializers

from .models import Address, Pet, User, normalize_phone


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        try:
            return normalize_phone(super().to_internal_value(data))
        except ValueError as e:
            raise serializers.ValidationError(str(e)) from e


class OtpRequestSerializer(serializers.Serializer):
    phone = PhoneField()


class OtpVerifySerializer(serializers.Serializer):
    phone = PhoneField()
    code = serializers.CharField(max_length=6)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "phone", "first_name", "last_name", "fcm_token"]
        read_only_fields = ["id", "phone"]
        extra_kwargs = {"fcm_token": {"write_only": True}}


class PetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pet
        fields = ["id", "name", "pet_type", "breed", "sex", "birth_date", "weight_kg", "is_sterilized"]


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ["id", "label", "address", "lat", "lng", "entrance", "floor", "apartment", "comment"]
