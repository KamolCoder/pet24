from django.core.management.base import BaseCommand

from apps.catalog import sync


class Command(BaseCommand):
    help = "Pull branches, products and stock from stockapi"

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Ignore updated_since, re-read all products")

    def handle(self, *args, full=False, **opts):
        self.stdout.write(f"branches: {sync.sync_branches()}")
        self.stdout.write(f"products: {sync.sync_products(full=full)}")
        self.stdout.write(f"stock rows: {sync.sync_stock()}")
