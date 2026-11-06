from django.contrib.auth import views as auth_views
from django.urls import path

from .views import base, catalog, crud, dashboard, orders

app_name = "panel"

urlpatterns = [
    path("login/", base.PanelLogin.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="/panel/login/"), name="logout"),
    path("", dashboard.home, name="home"),
    path("analytics/", dashboard.analytics_page, name="analytics"),
    path("orders/", orders.orders, name="orders"),
    path("orders/<int:pk>/", orders.order, name="order"),
    path("orders/<int:pk>/action/", orders.order_action, name="order_action"),
    path("shipments/", orders.shipments, name="shipments"),
    path("customers/", orders.customers, name="customers"),
    path("customers/<int:pk>/", orders.customer, name="customer"),
    path("products/", catalog.products, name="products"),
    path("products/new/", catalog.product_edit, name="product_new"),
    path("products/<int:pk>/", catalog.product_edit, name="product"),
    path("queue/", catalog.queue, name="queue"),
    path("queue/action/", catalog.queue_action, name="queue_action"),
    path("sync/", catalog.sync_page, name="sync"),
    path("<slug:key>/", crud.crud_list, name="crud"),
    path("<slug:key>/new/", crud.crud_edit, name="crud_new"),
    path("<slug:key>/<int:pk>/", crud.crud_edit, name="crud_edit"),
]
