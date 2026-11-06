from celery import shared_task

from . import sync


@shared_task
def sync_branches():
    return sync.sync_branches()


@shared_task
def sync_stock():
    # delta of products first (new SKUs, prices), then stock of all linked products
    sync.sync_products()
    return sync.sync_stock()
