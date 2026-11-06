from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Branch, Brand, Category, PetType, Product, ProductGroup, ProductImage


class PetTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PetType
        fields = ["id", "name", "slug", "icon"]


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "image", "pet_type", "children"]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_children(self, obj):
        kids = self.context.get("children_map", {}).get(obj.id, [])
        return CategorySerializer(kids, many=True, context=self.context).data


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "slug", "logo"]


class ImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["image", "thumb"]


class VariantSerializer(serializers.ModelSerializer):
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "variant_label", "price", "old_price", "unit", "barcode", "in_stock"]

    def get_in_stock(self, obj) -> bool:
        return obj.id in self.context.get("in_stock_ids", set())


class ProductListSerializer(serializers.ModelSerializer):
    thumb = serializers.SerializerMethodField()
    min_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    brand = serializers.CharField(source="brand.name", default=None)
    variants = serializers.SerializerMethodField()

    class Meta:
        model = ProductGroup
        fields = ["id", "slug", "name", "brand", "thumb", "min_price", "variants"]

    def get_thumb(self, obj) -> str | None:
        imgs = list(obj.images.all())
        if not imgs:
            return None
        request = self.context.get("request")
        url = (imgs[0].thumb or imgs[0].image).url
        return request.build_absolute_uri(url) if request else url

    @extend_schema_field(VariantSerializer(many=True))
    def get_variants(self, obj):
        return VariantSerializer(obj.sellable_variants, many=True, context=self.context).data


class ProductDetailSerializer(ProductListSerializer):
    images = ImageSerializer(many=True)
    category = serializers.CharField(source="category.name", default=None)
    pet_types = PetTypeSerializer(many=True)

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + [
            "category", "pet_types", "description", "composition", "feeding_guide", "attributes", "images",
        ]


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "address", "phone", "lat", "lng", "work_from", "work_to"]
