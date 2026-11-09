import json
import tempfile

from django.core.management import call_command

from apps.catalog.category_import import import_tree
from apps.catalog.models import Category

from .base import BaseTestCase


def node(pk, name, parent=None, index=1, lft=0, active=True):
    return {"model": "inventory.category", "pk": pk,
            "fields": {"name": name, "parent": parent, "index": index, "lft": lft, "is_active": active}}


TREE = [
    node(1, "Кошки", index=1),
    node(2, "Еда", 1, index=1, lft=2), node(3, "Сухой корм", 2), node(4, "Игрушки", 1, index=2, lft=5),
    node(5, "До 199 ₽", 4), node(6, "Мячики", 4, lft=7),
    node(10, "Собаки", index=2),
    node(11, "Аксессуары", 10), node(12, "Ошейники", 11),
    node(20, "Котята и щенки", index=3), node(21, "Для котят", 20, lft=1), node(22, "Еда", 21),
    node(23, "Для щенков", 20, lft=5),
    node(30, "Аксессуары", index=8), node(31, "Шлейки", 30),
    node(40, "Акции", index=9, active=False), node(41, "Список акций", 40),
]


class CategoryImportTests(BaseTestCase):
    def test_rules(self):
        res = import_tree(TREE)
        names = set(Category.objects.values_list("name", flat=True))
        self.assertNotIn("До 199 ₽", names)
        self.assertNotIn("Акции", names)
        self.assertNotIn("Список акций", names)
        self.assertEqual(res.created, 13)  # 5 cats + 3 dogs + 4 kittens/puppies + merged "Шлейки"

        cats = Category.objects.get(name="Кошки", parent=None)
        self.assertEqual(cats.pet_type.slug, "cats")
        self.assertEqual(Category.objects.get(name="Сухой корм").pet_type.slug, "cats")  # inherited

        # "Котята и щенки" is its own branch, children typed by animal
        kp = Category.objects.get(name="Котята и щенки", parent=None)
        self.assertIsNone(kp.pet_type)
        self.assertEqual(Category.objects.get(name="Для котят").pet_type.slug, "cats")
        self.assertEqual(Category.objects.get(name="Для щенков").pet_type.slug, "dogs")
        self.assertEqual(Category.objects.get(name="Еда", parent__name="Для котят").pet_type.slug, "cats")

        # stray root "Аксессуары" merged into Собаки / Аксессуары
        acc = Category.objects.get(name="Аксессуары", parent__name="Собаки")
        self.assertEqual(set(acc.children.values_list("name", flat=True)), {"Ошейники", "Шлейки"})
        self.assertFalse(Category.objects.filter(name="Аксессуары", parent=None).exists())

        # order follows index/lft
        self.assertEqual(list(cats.children.order_by("sort").values_list("name", flat=True)), ["Еда", "Игрушки"])
        # slugs are unique and readable
        self.assertEqual(Category.objects.get(name="Сухой корм").slug, "koshki-eda-sukhoi-korm")

    def test_rerun_keeps_panel_edits(self):
        import_tree(TREE)
        total = Category.objects.count()
        cat = Category.objects.get(name="Мячики")
        cat.name, cat.is_active = "Мячи", False
        cat.save()
        res = import_tree(TREE)
        self.assertEqual((res.created, Category.objects.count()), (0, total))
        cat.refresh_from_db()
        self.assertEqual((cat.name, cat.is_active), ("Мячи", False))

    def test_command(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as fh:
            json.dump(TREE, fh, ensure_ascii=False)
            fh.flush()
            call_command("import_categories", fh.name, stdout=open("/dev/null", "w"))
        self.assertTrue(Category.objects.filter(name="Шлейки").exists())
