from django.core.management.base import BaseCommand

from apps.catalog import sync


class Command(BaseCommand):
    help = "Pull branches, products and stock from stockapi"

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Ignore updated_since, re-read all products")

    def handle(self, *args, full=False, **opts):
        for step, result in sync.run_all(full=full).items():
            self.stdout.write(f"{step}: {result}")
