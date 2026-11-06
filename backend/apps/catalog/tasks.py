from celery import shared_task

from . import sync
from .models import SyncLog


@shared_task
def sync_branches():
    return sync.logged(SyncLog.Kind.BRANCHES, sync.sync_branches)


@shared_task
def sync_stock():
    # delta of products first (new SKUs, prices), then stock of all linked products
    sync.logged(SyncLog.Kind.PRODUCTS, sync.sync_products)
    return sync.logged(SyncLog.Kind.STOCK, sync.sync_stock)


@shared_task
def sync_all(full=False):
    return sync.run_all(full=full)
