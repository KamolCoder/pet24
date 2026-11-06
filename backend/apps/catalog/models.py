from decimal import Decimal

from django.db import models
from django.db.models import Q

from .images import make_variants


class Branch(models.Model):
    """Shop branch. Identity and is_active come from stockapi, the rest is filled in admin."""

    external_id = models.CharField("ID в stockapi", max_length=100, unique=True)
    name = models.CharField("Название", max_length=255)
    is_active = models.BooleanField("Активен в stockapi", default=True)
    address = models.CharField("Адрес", max_length=500, blank=True)
    phone = models.CharField("Телефон", max_length=20, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_enabled = models.BooleanField(
        "Собирает заказы на доставку", default=False,
        help_text="Включайте только когда заполнены координаты и есть сборщик",
    )
    work_from = models.TimeField("Сборка с", default="09:00")
    work_to = models.TimeField("Сборка до", default="21:00")
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def can_deliver(self):
        return self.is_active and self.delivery_enabled and self.lat is not None and self.lng is not None


class PetType(models.Model):
    name = models.CharField("Название", max_length=100)
    slug = models.SlugField(unique=True)
    icon = models.ImageField(upload_to="pet_types/", blank=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Вид животного"
        verbose_name_plural = "Виды животных"
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name


class Category(models.Model):
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children", verbose_name="Родитель"
    )
    pet_type = models.ForeignKey(PetType, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Вид")
    name = models.CharField("Название", max_length=200)
    slug = models.SlugField(unique=True)
    image = models.ImageField(upload_to="categories/", blank=True)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["sort", "name"]

    def __str__(self):
        return f"{self.parent} / {self.name}" if self.parent_id else self.name

    def descendant_ids(self) -> list[int]:
        ids, frontier = [self.id], [self.id]
        while frontier:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
            ids += frontier
        return ids


class Brand(models.Model):
    name = models.CharField("Название", max_length=200, unique=True)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to="brands/", blank=True)

    class Meta:
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductGroup(models.Model):
    """Product card shown in the app. Holds content; variants (packages) are Products from stockapi."""

    name = models.CharField("Название", max_length=300)
    slug = models.SlugField(max_length=320, unique=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Категория")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Бренд")
    pet_types = models.ManyToManyField(PetType, blank=True, verbose_name="Для кого")
    description = models.TextField("Описание", blank=True)
    composition = models.TextField("Состав", blank=True)
    feeding_guide = models.TextField("Рекомендации по кормлению", blank=True)
    # Free-form filter attributes, e.g. {"age": "adult", "size": "small", "flavor": "chicken"}
    attributes = models.JSONField("Атрибуты", default=dict, blank=True)
    is_published = models.BooleanField("Опубликовано", default=False)
    sort = models.IntegerField("Сортировка", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Карточка товара"
        verbose_name_plural = "Карточки товаров"
        ordering = ["-sort", "name"]

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def sellable(self):
        """Visible in the app: active in stockapi, priced, attached to a published card with a photo."""
        return self.filter(
            is_active=True, price__gt=0, group__is_published=True, group__images__isnull=False,
        ).distinct()


class Product(models.Model):
    """Sellable SKU mirrored from stockapi (name, price, barcode, is_active are overwritten on sync)."""

    external_id = models.CharField("ID в stockapi", max_length=100, unique=True)
    group = models.ForeignKey(
        ProductGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name="variants",
        verbose_name="Карточка",
    )
    variant_label = models.CharField("Фасовка", max_length=100, blank=True, help_text="Например: 2 кг")
    variant_sort = models.IntegerField(default=0)
    name = models.CharField("Название (stockapi)", max_length=500)
    code = models.CharField(max_length=100, blank=True)
    article = models.CharField(max_length=100, blank=True)
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    unit = models.CharField(max_length=50, blank=True)
    price = models.DecimalField("Цена", max_digits=12, decimal_places=2, default=Decimal("0"))
    old_price = models.DecimalField(
        "Старая цена", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Для зачёркнутой цены в акциях",
    )
    weight_g = models.PositiveIntegerField("Вес брутто, г", null=True, blank=True, help_text="Для курьерской службы")
    is_active = models.BooleanField("Активен в stockapi", default=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        verbose_name = "Товар (SKU)"
        verbose_name_plural = "Товары (SKU)"
        ordering = ["variant_sort", "price"]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        if self.group_id:
            return f"{self.group.name} {self.variant_label}".strip()
        return self.name


class ProductImage(models.Model):
    group = models.ForeignKey(ProductGroup, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField("Фото", upload_to="products/")
    thumb = models.ImageField(upload_to="products/thumbs/", blank=True, editable=False)
    sort = models.PositiveIntegerField("Порядок", default=0, help_text="Первое фото — главное")

    class Meta:
        verbose_name = "Фото"
        verbose_name_plural = "Фото"
        ordering = ["sort", "id"]

    def save(self, *args, **kwargs):
        # Normalise every new upload: WebP 1200px + 400px thumbnail.
        if self.image and not self.image._committed:
            full, thumb = make_variants(self.image)
            self.image.save(full.name, full, save=False)
            self.thumb.save(thumb.name, thumb, save=False)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        storage_files = [(f.storage, f.name) for f in (self.image, self.thumb) if f]
        super().delete(*args, **kwargs)
        for storage, name in storage_files:
            storage.delete(name)


class Stock(models.Model):
    """Cached real stock (1C stock minus till sales not yet posted) per branch from stockapi."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stocks")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stocks")
    real_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "branch"], name="uniq_stock")]
        indexes = [models.Index(fields=["branch", "product"], condition=Q(real_quantity__gt=0), name="stock_positive")]


class SyncState(models.Model):
    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key, default=""):
        obj = cls.objects.filter(key=key).first()
        return obj.value if obj else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={"value": value})


class SyncLog(models.Model):
    class Kind(models.TextChoices):
        BRANCHES = "branches", "Филиалы"
        PRODUCTS = "products", "Товары (дельта)"
        PRODUCTS_FULL = "products_full", "Товары (полный)"
        STOCK = "stock", "Остатки"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["kind", "-started_at"])]

    @property
    def duration(self):
        return (self.finished_at - self.started_at) if self.finished_at else None
