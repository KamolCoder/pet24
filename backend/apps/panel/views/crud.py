"""Generic list/create/edit/delete for simple reference models."""
from dataclasses import dataclass, field
from typing import Callable

from django.contrib import messages
from django.db.models import Count, ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.html import format_html

from apps.catalog.models import Branch, Brand, Category, PetType
from apps.customers.models import User
from apps.delivery.models import DeliveryZone

from .. import forms as f
from ..templatetags.panel import ago, money
from .base import operator_required, page, render_panel


def yes(v):
    return format_html('<span class="b ok">да</span>') if v else format_html('<span class="b off">нет</span>')


@dataclass
class Crud:
    key: str
    title: str
    model: type
    form: type
    columns: list[tuple[str, Callable]]
    active: str
    tabs: str = ""
    search: list[str] = field(default_factory=list)
    can_create: bool = True
    can_delete: bool = True
    queryset: Callable | None = None
    intro: str = ""

    def qs(self):
        return self.queryset() if self.queryset else self.model.objects.all()


REFS_TABS = [("categories", "Категории"), ("brands", "Бренды"), ("pet_types", "Виды животных")]

REGISTRY = {c.key: c for c in [
    Crud("categories", "Категории", Category, f.CategoryForm, [
        ("Название", lambda o: str(o)), ("Вид", lambda o: o.pet_type or "—"), ("Порядок", lambda o: o.sort),
        ("Карточек", lambda o: o.n), ("Активна", lambda o: yes(o.is_active)),
    ], "refs", tabs="refs", search=["name"],
        queryset=lambda: Category.objects.select_related("parent", "pet_type").annotate(n=Count("productgroup"))),
    Crud("brands", "Бренды", Brand, f.BrandForm, [
        ("Название", lambda o: o.name), ("Slug", lambda o: o.slug), ("Карточек", lambda o: o.n),
    ], "refs", tabs="refs", search=["name"], queryset=lambda: Brand.objects.annotate(n=Count("productgroup"))),
    Crud("pet_types", "Виды животных", PetType, f.PetTypeForm, [
        ("Название", lambda o: o.name), ("Slug", lambda o: o.slug), ("Порядок", lambda o: o.sort),
    ], "refs", tabs="refs"),
    Crud("branches", "Филиалы", Branch, f.BranchForm, [
        ("Филиал", lambda o: o.name), ("ID stockapi", lambda o: format_html('<span class="mono">{}</span>', o.external_id)),
        ("Активен", lambda o: yes(o.is_active)), ("Доставка", lambda o: yes(o.delivery_enabled)),
        ("Координаты", lambda o: yes(o.lat is not None)), ("Часы сборки", lambda o: f"{o.work_from:%H:%M}–{o.work_to:%H:%M}"),
        ("Сборщиков", lambda o: o.n_staff), ("Синк", lambda o: ago(o.synced_at)),
    ], "branches", search=["name", "external_id", "address"], can_create=False, can_delete=False,
        queryset=lambda: Branch.objects.annotate(n_staff=Count("staff", filter=Q(staff__role="picker", staff__is_active=True))),
        intro="Филиалы приходят из stockapi. Здесь заполняются адрес, координаты, телефон и включается доставка."),
    Crud("zones", "Зоны доставки", DeliveryZone, f.ZoneForm, [
        ("Зона", lambda o: o.name), ("Цена", lambda o: money(o.price)), ("Бесплатно от", lambda o: money(o.free_from)),
        ("Мин. заказ", lambda o: money(o.min_order)), ("До филиала, км", lambda o: o.max_branch_km),
        ("Приоритет", lambda o: o.priority), ("Активна", lambda o: yes(o.is_active)),
    ], "delivery", tabs="delivery",
        intro="Полигон: [[lat, lng], ...]. Нарисуйте на geojson.io, скопируйте координаты и поменяйте местами lng/lat."),
    Crud("staff", "Сотрудники", User, f.StaffForm, [
        ("Телефон", lambda o: f"+{o.phone}"), ("Имя", lambda o: o.full_name), ("Роль", lambda o: o.get_role_display()),
        ("Филиал", lambda o: o.branch or "все"), ("Активен", lambda o: yes(o.is_active)), ("Вход", lambda o: ago(o.last_login)),
    ], "staff", search=["phone", "first_name", "last_name"], can_delete=False,
        queryset=lambda: User.objects.filter(role__in=[User.Role.PICKER, User.Role.OPERATOR]).select_related("branch"),
        intro="Сборщики входят в /staff/ и видят заказы своего филиала. Операторы — в эту панель и /staff/ по всем филиалам."),
]}


def _crud(key) -> Crud:
    if key not in REGISTRY:
        raise Http404
    return REGISTRY[key]


def _ctx(c: Crud):
    return {"c": c, "tabs": REFS_TABS if c.tabs == "refs" else None}


@operator_required
def crud_list(request, key):
    c = _crud(key)
    qs = c.qs()
    if (q := request.GET.get("q", "").strip()) and c.search:
        cond = Q()
        for fld in c.search:
            cond |= Q(**{f"{fld}__icontains": q})
        qs = qs.filter(cond)
    pg = page(request, qs, 100)
    rows = [(o, [fn(o) for _, fn in c.columns]) for o in pg]
    return render_panel(request, "panel/crud_list.html", c.active, page=pg, rows=rows, **_ctx(c))


@operator_required
def crud_edit(request, key, pk=None):
    c = _crud(key)
    obj = get_object_or_404(c.qs(), pk=pk) if pk else None
    if obj is None and not c.can_create:
        raise Http404
    form = c.form(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST":
        if request.POST.get("delete") and obj and c.can_delete:
            try:
                obj.delete()
            except ProtectedError:
                messages.error(request, "Нельзя удалить: запись используется")
                return redirect("panel:crud_edit", key=key, pk=pk)
            messages.success(request, "Удалено")
            return redirect("panel:crud", key=key)
        if form.is_valid():
            obj = form.save()
            messages.success(request, "Сохранено")
            return redirect("panel:crud", key=key)
    return render_panel(request, "panel/crud_form.html", c.active, form=form, obj=obj, **_ctx(c))
