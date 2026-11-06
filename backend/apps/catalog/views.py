from collections import defaultdict

from django.db.models import Min, Prefetch, Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Branch, Brand, Category, PetType, Product, ProductGroup, Stock
from .serializers import (
    BranchSerializer,
    BrandSerializer,
    CategorySerializer,
    PetTypeSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
)

ORDERINGS = {"price": "min_price", "-price": "-min_price", "new": "-created_at", "name": "name"}


def in_stock_ids(product_ids) -> set[int]:
    """Products with positive real stock in at least one branch that ships orders."""
    return set(
        Stock.objects.filter(
            product_id__in=product_ids, real_quantity__gt=0,
            branch__delivery_enabled=True, branch__is_active=True,
        ).values_list("product_id", flat=True)
    )


def published_groups():
    sellable = Product.objects.sellable()
    return (
        ProductGroup.objects.filter(is_published=True, variants__in=sellable)
        .annotate(min_price=Min("variants__price", filter=Q(variants__in=sellable)))
        .select_related("brand", "category")
        .prefetch_related(
            "images",
            Prefetch("variants", queryset=Product.objects.sellable(), to_attr="sellable_variants"),
        )
        .distinct()
    )


class _StockContextMixin:
    def _stock_context(self, groups):
        ids = [v.id for g in groups for v in g.sellable_variants]
        return {"in_stock_ids": in_stock_ids(ids)}


class PetTypeList(generics.ListAPIView):
    queryset = PetType.objects.all()
    serializer_class = PetTypeSerializer
    pagination_class = None


class BrandList(generics.ListAPIView):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    pagination_class = None


class CategoryTree(APIView):
    """Category tree. ?pet_type=<slug> keeps only that animal's roots."""

    @extend_schema(responses=CategorySerializer(many=True))
    def get(self, request):
        cats = list(Category.objects.filter(is_active=True))
        children = defaultdict(list)
        roots = []
        for c in cats:
            (children[c.parent_id] if c.parent_id else roots).append(c)
        pet = request.query_params.get("pet_type")
        if pet:
            roots = [c for c in roots if c.pet_type and c.pet_type.slug == pet]
        return Response(CategorySerializer(roots, many=True, context={"children_map": children}).data)


class ProductList(_StockContextMixin, generics.ListAPIView):
    """
    Filters: q, pet_type (slug), category (id, includes subcategories), brand (id, comma list),
    price_min, price_max, in_stock=true, attr_<name>=<value>, ordering=price|-price|new|name.
    """

    serializer_class = ProductListSerializer

    def get_queryset(self):
        qs = published_groups()
        p = self.request.query_params
        if q := p.get("q", "").strip():
            qs = qs.filter(
                Q(name__icontains=q) | Q(brand__name__icontains=q) | Q(variants__barcode=q)
            )
        if pet := p.get("pet_type"):
            qs = qs.filter(pet_types__slug=pet)
        if cat := p.get("category"):
            category = Category.objects.filter(pk=cat).first()
            qs = qs.filter(category_id__in=category.descendant_ids()) if category else qs.none()
        if brands := p.get("brand"):
            qs = qs.filter(brand_id__in=[b for b in brands.split(",") if b.isdigit()])
        if pmin := p.get("price_min"):
            qs = qs.filter(min_price__gte=pmin)
        if pmax := p.get("price_max"):
            qs = qs.filter(min_price__lte=pmax)
        for key, value in p.items():
            if key.startswith("attr_"):
                qs = qs.filter(**{f"attributes__{key[5:]}": value})
        if p.get("in_stock") == "true":
            qs = qs.filter(
                variants__stocks__real_quantity__gt=0,
                variants__stocks__branch__delivery_enabled=True,
                variants__stocks__branch__is_active=True,
            )
        return qs.order_by(ORDERINGS.get(p.get("ordering"), "-sort"), "id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        ctx = {**self.get_serializer_context(), **self._stock_context(page)}
        return self.get_paginated_response(self.serializer_class(page, many=True, context=ctx).data)


class ProductDetail(_StockContextMixin, generics.RetrieveAPIView):
    serializer_class = ProductDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return published_groups().prefetch_related("pet_types")

    def retrieve(self, request, *args, **kwargs):
        group = self.get_object()
        ctx = {**self.get_serializer_context(), **self._stock_context([group])}
        return Response(self.serializer_class(group, context=ctx).data)


class BranchList(generics.ListAPIView):
    queryset = Branch.objects.filter(is_active=True)
    serializer_class = BranchSerializer
    pagination_class = None
