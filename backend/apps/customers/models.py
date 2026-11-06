import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

PHONE_RE = re.compile(r"^998\d{9}$")


def normalize_phone(raw: str) -> str:
    """'+998 (90) 123-45-67' / '901234567' -> '998901234567'. Raises ValueError."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 9:
        digits = "998" + digits
    if not PHONE_RE.match(digits):
        raise ValueError("Неверный номер телефона")
    return digits


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        user = self.model(phone=normalize_phone(phone), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=User.Role.OPERATOR)
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        CUSTOMER = "customer", "Покупатель"
        PICKER = "picker", "Сборщик филиала"
        OPERATOR = "operator", "Оператор"

    phone = models.CharField("Телефон", max_length=12, unique=True)
    first_name = models.CharField("Имя", max_length=100, blank=True)
    last_name = models.CharField("Фамилия", max_length=100, blank=True)
    role = models.CharField("Роль", max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    branch = models.ForeignKey(
        "catalog.Branch", verbose_name="Филиал (для сборщика)", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="staff",
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField("Доступ в админку", default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    fcm_token = models.CharField(max_length=255, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return f"+{self.phone} {self.first_name}".strip()

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_branch_staff(self):
        return self.role in (self.Role.PICKER, self.Role.OPERATOR) or self.is_superuser


class Pet(models.Model):
    class Sex(models.TextChoices):
        MALE = "m", "Мальчик"
        FEMALE = "f", "Девочка"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="pets")
    name = models.CharField("Кличка", max_length=100)
    pet_type = models.ForeignKey("catalog.PetType", on_delete=models.PROTECT, verbose_name="Вид")
    breed = models.CharField("Порода", max_length=100, blank=True)
    sex = models.CharField(max_length=1, choices=Sex.choices, blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    weight_kg = models.DecimalField("Вес, кг", max_digits=5, decimal_places=2, null=True, blank=True)
    is_sterilized = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Питомец"
        verbose_name_plural = "Питомцы"

    def __str__(self):
        return self.name


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField("Название", max_length=50, blank=True)  # Дом, Работа
    address = models.CharField("Адрес", max_length=500)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    entrance = models.CharField("Подъезд", max_length=20, blank=True)
    floor = models.CharField("Этаж", max_length=20, blank=True)
    apartment = models.CharField("Квартира", max_length=20, blank=True)
    comment = models.CharField("Комментарий курьеру", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Адрес"
        verbose_name_plural = "Адреса"
        ordering = ["-created_at"]

    def __str__(self):
        return self.address


def _hash_code(phone: str, code: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{phone}:{code}".encode()).hexdigest()


class OtpCode(models.Model):
    phone = models.CharField(max_length=12, db_index=True)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def issue(cls, phone: str) -> tuple["OtpCode", str]:
        code = f"{secrets.randbelow(10000):04d}"
        cls.objects.filter(phone=phone, used=False).update(used=True)
        otp = cls.objects.create(
            phone=phone,
            code_hash=_hash_code(phone, code),
            expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SEC),
        )
        return otp, code

    @classmethod
    def last_sent_recently(cls, phone: str) -> bool:
        since = timezone.now() - timedelta(seconds=settings.OTP_RESEND_SEC)
        return cls.objects.filter(phone=phone, created_at__gte=since).exists()

    @classmethod
    def verify(cls, phone: str, code: str) -> bool:
        otp = cls.objects.filter(phone=phone, used=False, expires_at__gt=timezone.now()).first()
        if otp is None or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            return False
        if secrets.compare_digest(otp.code_hash, _hash_code(phone, code.strip())):
            otp.used = True
            otp.save(update_fields=["used"])
            return True
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return False
