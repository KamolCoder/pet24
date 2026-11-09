"""Import a category tree from a Django dumpdata file of an MPTT category model.

Expected items: {"model": "...category", "pk": 1, "fields": {"name", "parent", "index", "is_active", "lft", ...}}.

Cleanup rules (see `import_tree`):
  * inactive root branches (e.g. "Акции", "Мерч") are skipped with their whole subtree;
  * price-bucket nodes ("До 199 ₽") are skipped — that is a price filter, not a category;
  * an active root that is not an animal ("Аксессуары" → "Шлейки") is merged into "Собаки" by name;
  * roots are bound to pet types; "Котята и щенки" stays a separate branch, its children
    "Для котят" / "Для щенков" get cats / dogs; every node inherits the pet type of its nearest typed ancestor.

Re-running is safe: nodes are matched by `source_ref` and existing categories are left untouched
(panel edits survive); only missing ones are created.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.text import slugify
from unidecode import unidecode

from .models import Category, PetType

PET_TYPES = {  # root name (lowercase) -> (slug, display name, sort)
    "собаки": ("dogs", "Собаки", 1),
    "кошки": ("cats", "Кошки", 2),
    "грызуны, хорьки": ("rodents", "Грызуны", 3),
    "птицы": ("birds", "Птицы", 4),
    "рыбки": ("fish", "Рыбы", 5),
}
CHILD_PET_TYPES = {"для котят": "cats", "для щенков": "dogs"}
MERGE_STRAY_ROOTS_INTO = "собаки"
PRICE_BUCKET_RE = re.compile(r"^\s*(до|от)\s*[\d\s]+\s*(₽|руб|сум|\$)", re.IGNORECASE)
SLUG_MAX = 120


@dataclass
class ImportResult:
    created: int = 0
    existing: int = 0
    skipped: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)


def _slug(path: list[str]) -> str:
    base = slugify(unidecode("-".join(path)))[:SLUG_MAX].strip("-") or "category"
    slug, n = base, 1
    while Category.objects.filter(slug=slug).exists():
        n += 1
        suffix = f"-{n}"
        slug = base[: SLUG_MAX - len(suffix)] + suffix
    return slug


def _pet_types() -> dict[str, PetType]:
    out = {}
    for slug, name, sort in PET_TYPES.values():
        out[slug] = PetType.objects.get_or_create(slug=slug, defaults={"name": name, "sort": sort})[0]
    return out


@transaction.atomic
def import_tree(items: list[dict], prefix: str = "inv") -> ImportResult:
    nodes = {x["pk"]: x["fields"] for x in items if x.get("model", "").endswith("category")}
    children = defaultdict(list)
    for pk, f in nodes.items():
        children[f.get("parent")].append(pk)
    for kids in children.values():
        kids.sort(key=lambda k: (nodes[k].get("index") or 0, nodes[k].get("lft") or 0))

    pets = _pet_types()
    res = ImportResult()
    roots = children[None]
    by_name = {nodes[r]["name"].strip().lower(): r for r in roots}
    merge_target = by_name.get(MERGE_STRAY_ROOTS_INTO)

    def ensure(pk: int, parent: Category | None, path: list[str], pet: PetType | None, sort: int) -> Category:
        f = nodes[pk]
        ref = f"{prefix}:{pk}"
        cat = Category.objects.filter(source_ref=ref).first()
        if cat:
            res.existing += 1
            return cat
        res.created += 1
        return Category.objects.create(
            source_ref=ref, name=f["name"].strip(), parent=parent, pet_type=pet,
            slug=_slug(path), sort=sort, is_active=bool(f.get("is_active", True)),
        )

    def walk(pk: int, parent: Category | None, path: list[str], pet: PetType | None, sort: int):
        name = nodes[pk]["name"].strip()
        if PRICE_BUCKET_RE.match(name):
            res.skipped.append(" / ".join([*path, name]))
            return
        pet = pets.get(CHILD_PET_TYPES.get(name.lower(), ""), pet)
        cat = ensure(pk, parent, [*path, name], pet, sort)
        for i, child in enumerate(children[pk], start=1):
            walk(child, cat, [*path, name], pet, i)

    stray = []
    for i, root in enumerate(roots, start=1):
        f = nodes[root]
        name = f["name"].strip()
        if not f.get("is_active", True):
            res.skipped.append(f"{name} (выключена)")
            continue
        if name.lower() not in PET_TYPES and name.lower() != "котята и щенки":
            stray.append(root)
            continue
        pet_slug = PET_TYPES.get(name.lower(), (None,))[0]
        walk(root, None, [], pets.get(pet_slug), i)

    # stray roots: put their children under the same-named child of "Собаки" (or create it there)
    for root in stray:
        name = nodes[root]["name"].strip()
        target_root = Category.objects.filter(source_ref=f"{prefix}:{merge_target}").first() if merge_target else None
        if target_root is None:
            res.skipped.append(f"{name} (некуда влить)")
            continue
        target = target_root.children.filter(name__iexact=name).first() or ensure(
            root, target_root, [target_root.name, name], target_root.pet_type, 999)
        base = target.children.count()
        for i, child in enumerate(children[root], start=1):
            cname = nodes[child]["name"].strip()
            if target.children.filter(name__iexact=cname).exclude(source_ref=f"{prefix}:{child}").exists():
                res.skipped.append(f"{name} / {cname} (уже есть в {target_root.name} / {target.name})")
                continue
            walk(child, target, [target_root.name, target.name], target_root.pet_type, base + i)
        res.merged.append(f"{name} → {target_root.name} / {target.name}")
    return res
