from django.contrib import admin, messages
from django.db.models import Count, Sum
from django.utils.html import format_html
from django.utils.text import slugify
from unidecode import unidecode

from .models import Branch, Brand, Category, PetType, Product, ProductGroup, ProductImage, Stock


def unique_slug(model, base: str) -> str:
    base = slugify(unidecode(base))[:300] or "item"
    slug, n = base, 1
    while model.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "external_id", "is_active", "delivery_enabled", "has_coords", "work_from", "work_to"]
    list_editable = ["delivery_enabled"]
    list_filter = ["is_active", "delivery_enabled"]
    search_fields = ["name", "external_id", "address"]
    readonly_fields = ["external_id", "is_active", "synced_at"]

    @admin.display(boolean=True, description="Координаты")
    def has_coords(self, obj):
        return obj.lat is not None and obj.lng is not None


@admin.register(PetType)
class PetTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "sort"]
    list_editable = ["sort"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "pet_type", "sort", "is_active"]
    list_editable = ["sort", "is_active"]
    list_filter = ["pet_type", "is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 3
    fields = ["preview", "image", "sort"]
    readonly_fields = ["preview"]

    @admin.display(description="")
    def preview(self, obj):
        return format_html('<img src="{}" style="height:80px">', obj.thumb.url) if obj.thumb else ""


class VariantInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ["name", "external_id", "variant_label", "variant_sort", "price", "old_price", "weight_g", "is_active"]
    readonly_fields = ["name", "external_id", "price", "is_active"]
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False  # SKUs come from stockapi; attach them via the SKU list action


@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ["name", "brand", "category", "is_published", "photos", "skus", "updated_at"]
    list_filter = ["is_published", "category", "brand", "pet_types"]
    list_editable = ["is_published"]
    search_fields = ["name", "variants__barcode", "variants__external_id"]
    prepopulated_fields = {"slug": ["name"]}
    autocomplete_fields = ["brand", "category"]
    filter_horizontal = ["pet_types"]
    inlines = [VariantInline, ImageInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _photos=Count("images", distinct=True), _skus=Count("variants", distinct=True)
        )

    @admin.display(description="Фото", ordering="_photos")
    def photos(self, obj):
        return obj._photos

    @admin.display(description="SKU", ordering="_skus")
    def skus(self, obj):
        return obj._skus


class LinkedFilter(admin.SimpleListFilter):
    title = "Карточка"
    parameter_name = "linked"

    def lookups(self, request, model_admin):
        return [("no", "Без карточки (очередь)"), ("yes", "С карточкой")]

    def queryset(self, request, qs):
        if self.value() == "no":
            return qs.filter(group__isnull=True)
        if self.value() == "yes":
            return qs.filter(group__isnull=False)
        return qs


class StockInline(admin.TabularInline):
    model = Stock
    extra = 0
    fields = ["branch", "real_quantity", "updated_at"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "external_id", "barcode", "price", "is_active", "group", "variant_label", "total_stock"]
    list_filter = [LinkedFilter, "is_active"]
    search_fields = ["name", "external_id", "barcode", "code", "article"]
    readonly_fields = ["external_id", "name", "code", "article", "barcode", "unit", "price", "is_active", "synced_at"]
    autocomplete_fields = ["group"]
    actions = ["create_card"]
    inlines = [StockInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("group").annotate(_stock=Sum("stocks__real_quantity"))

    @admin.display(description="Остаток", ordering="_stock")
    def total_stock(self, obj):
        return obj._stock

    @admin.action(description="Создать карточку из выбранных SKU (фасовки одного товара)")
    def create_card(self, request, queryset):
        queryset = queryset.filter(group__isnull=True).order_by("price")
        first = queryset.first()
        if first is None:
            self.message_user(request, "Все выбранные SKU уже привязаны к карточкам", messages.WARNING)
            return
        group = ProductGroup.objects.create(name=first.name, slug=unique_slug(ProductGroup, first.name))
        n = queryset.update(group=group)
        self.message_user(request, format_html(
            'Создана карточка <a href="{}">{}</a>, привязано SKU: {}. Добавьте фото, категорию и опубликуйте.',
            f"../productgroup/{group.pk}/change/", group.name, n,
        ))
