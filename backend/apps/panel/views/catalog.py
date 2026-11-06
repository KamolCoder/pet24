from collections import defaultdict

from django import forms as dj_forms
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.catalog import sync as stock_sync
from apps.catalog.models import Brand, Category, Product, ProductGroup, ProductImage, Stock, SyncLog
from apps.catalog.stockapi import StockApiError
from apps.catalog.tasks import sync_all

from ..forms import ProductGroupForm, unique_slug
from .base import operator_required, page, render_panel

VariantFormSet = dj_forms.modelformset_factory(
    Product, fields=["variant_label", "variant_sort", "old_price", "weight_g"], extra=0,
    widgets={"variant_label": dj_forms.TextInput(attrs={"placeholder": "2 кг"})},
)


@operator_required
def products(request):
    g = request.GET
    qs = ProductGroup.objects.select_related("category", "brand").annotate(
        n_img=Count("images", distinct=True), n_sku=Count("variants", distinct=True),
        min_price=Min("variants__price"),
    )
    if q := g.get("q", "").strip():
        qs = qs.filter(Q(name__icontains=q) | Q(variants__barcode=q) | Q(variants__external_id=q)).distinct()
    if g.get("published") == "yes":
        qs = qs.filter(is_published=True)
    elif g.get("published") == "no":
        qs = qs.filter(is_published=False)
    if g.get("photo") == "no":
        qs = qs.filter(n_img=0)
    if g.get("category", "").isdigit():
        qs = qs.filter(category_id__in=Category.objects.get(pk=g["category"]).descendant_ids()) \
            if Category.objects.filter(pk=g["category"]).exists() else qs.none()
    if g.get("brand", "").isdigit():
        qs = qs.filter(brand_id=g["brand"])
    return render_panel(
        request, "panel/products.html", "products", page=page(request, qs.order_by("-updated_at")),
        categories=Category.objects.select_related("parent"), brands=Brand.objects.all(),
    )


@operator_required
def product_edit(request, pk=None):
    group = get_object_or_404(ProductGroup, pk=pk) if pk else None
    action = request.POST.get("action", "save")

    if request.method == "POST" and group and action != "save":
        return _product_action(request, group, action)

    form = ProductGroupForm(request.POST if action == "save" and request.method == "POST" else None, instance=group)
    variants = VariantFormSet(
        request.POST if request.method == "POST" and group else None,
        queryset=group.variants.all() if group else Product.objects.none(), prefix="v",
    )
    if request.method == "POST" and form.is_valid() and (not group or variants.is_valid()):
        with transaction.atomic():
            group = form.save()
            if variants.is_bound:
                variants.save()
        messages.success(request, "Карточка сохранена")
        return redirect("panel:product", pk=group.pk)

    stocks = defaultdict(list)
    if group:
        for st in Stock.objects.filter(product__group=group, real_quantity__gt=0).select_related("branch"):
            stocks[st.product_id].append((st.branch.name, st.real_quantity))
    return render_panel(
        request, "panel/product.html", "products", g=group, form=form, variants=variants,
        images=group.images.all() if group else [],
        variant_rows=[(fm, stocks.get(fm.instance.pk, [])) for fm in variants.forms],
    )


def _product_action(request, group, action):
    P = request.POST
    if action == "upload":
        files = request.FILES.getlist("images")
        start = (group.images.order_by("-sort").values_list("sort", flat=True).first() or 0) + 1
        ok = 0
        for i, fl in enumerate(files):
            try:
                ProductImage.objects.create(group=group, image=fl, sort=start + i)
                ok += 1
            except Exception as e:  # broken / unsupported file
                messages.error(request, f"{fl.name}: не удалось обработать ({e.__class__.__name__})")
        if ok:
            messages.success(request, f"Загружено фото: {ok}")
    elif action == "image_sort":
        for img in group.images.all():
            v = P.get(f"sort_{img.pk}", "")
            if v.isdigit():
                img.sort = int(v)
                img.save(update_fields=["sort"])
        messages.success(request, "Порядок фото сохранён")
    elif action == "image_delete":
        img = group.images.filter(pk=P.get("image_id")).first()
        if img:
            img.delete()
            if group.is_published and not group.images.exists():
                group.is_published = False
                group.save(update_fields=["is_published"])
                messages.warning(request, "Фото не осталось — карточка снята с публикации")
            messages.success(request, "Фото удалено")
    elif action == "unlink":
        n = group.variants.filter(pk=P.get("product_id")).update(group=None)
        messages.success(request, "SKU отвязан и вернулся в очередь" if n else "SKU не найден")
    elif action == "attach":
        q = P.get("q", "").strip()
        found = Product.objects.filter(group__isnull=True).filter(
            Q(external_id=q) | Q(barcode=q) | Q(code=q) | Q(article=q)
        )
        n = found.update(group=group)
        messages.success(request, f"Привязано SKU: {n}") if n else messages.error(
            request, "Свободный SKU с таким ID / штрихкодом / кодом не найден")
    elif action == "toggle_publish":
        if not group.is_published and (not group.images.exists() or not group.category_id):
            messages.error(request, "Для публикации нужны фото и категория")
        else:
            group.is_published = not group.is_published
            group.save(update_fields=["is_published", "updated_at"])
            messages.success(request, "Опубликовано" if group.is_published else "Снято с публикации")
    elif action == "delete":
        group.variants.update(group=None)
        for img in group.images.all():
            img.delete()
        group.delete()
        messages.success(request, "Карточка удалена, SKU вернулись в очередь")
        return redirect("panel:products")
    return redirect("panel:product", pk=group.pk)


@operator_required
def queue(request):
    qs = (Product.objects.filter(group__isnull=True)
          .annotate(stock=Sum("stocks__real_quantity")))
    if request.GET.get("all") != "1":
        qs = qs.filter(is_active=True)
    if q := request.GET.get("q", "").strip():
        qs = qs.filter(Q(name__icontains=q) | Q(external_id=q) | Q(barcode=q) | Q(code=q) | Q(article=q))
    if request.GET.get("in_stock") == "1":
        qs = qs.filter(stock__gt=0)
    sort = {"stock": "-stock", "price": "-price"}.get(request.GET.get("sort"), "name")
    return render_panel(request, "panel/queue.html", "queue", page=page(request, qs.order_by(sort, "id"), 100))


@operator_required
@require_POST
def queue_action(request):
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    selected = Product.objects.filter(pk__in=ids, group__isnull=True).order_by("price")
    if not selected.exists():
        messages.error(request, "Ничего не выбрано")
        return redirect(request.META.get("HTTP_REFERER") or "panel:queue")
    target = request.POST.get("target", "").strip()
    if request.POST.get("action") == "attach":
        group = ProductGroup.objects.filter(Q(slug=target) | Q(pk=target if target.isdigit() else 0)).first()
        if not group:
            messages.error(request, "Карточка с таким ID или slug не найдена")
            return redirect(request.META.get("HTTP_REFERER") or "panel:queue")
    else:
        first = selected.first()
        name = request.POST.get("name", "").strip() or first.name
        group = ProductGroup.objects.create(name=name, slug=unique_slug(ProductGroup, name))
    n = selected.update(group=group)
    messages.success(request, f"{group.name}: привязано SKU {n}. Добавьте фасовки, фото и категорию.")
    return redirect("panel:product", pk=group.pk)


@operator_required
def sync_page(request):
    if request.method == "POST":
        full = request.POST.get("full") == "1"
        if not settings.CELERY_TASK_ALWAYS_EAGER:
            sync_all.delay(full=full)
            messages.success(request, "Синк запущен в фоне, результат появится в журнале через минуту")
            return redirect("panel:sync")
        try:
            res = stock_sync.run_all(full=full)
            messages.success(request, f"Синк выполнен: товаров {res['products'].get('received')}, строк остатков {res['stock']}")
        except StockApiError as e:
            messages.error(request, f"stockapi: {e}")
        return redirect("panel:sync")
    return render_panel(request, "panel/sync.html", "sync", page=page(request, SyncLog.objects.all(), 100))
