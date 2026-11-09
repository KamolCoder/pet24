import json

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.category_import import import_tree


class Command(BaseCommand):
    help = "Import category tree from a dumpdata JSON file (MPTT category model). Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument("path", help="categories_backup.json")
        parser.add_argument("--prefix", default="inv", help="source id prefix, keep the same for re-imports")

    def handle(self, path, prefix, **opts):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                items = json.load(fh)
        except (OSError, ValueError) as e:
            raise CommandError(f"Cannot read {path}: {e}") from e
        res = import_tree(items, prefix=prefix)
        self.stdout.write(self.style.SUCCESS(f"created: {res.created}, already existed: {res.existing}"))
        for m in res.merged:
            self.stdout.write(f"merged: {m}")
        for s in res.skipped:
            self.stdout.write(f"skipped: {s}")
