import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.models import Branch, Category, PetType, Product, ProductGroup, ProductImage, Stock
from apps.customers.models import User
from apps.delivery.models import DeliveryZone

# square around central Tashkent
TASHKENT = [[41.20, 69.10], [41.20, 69.40], [41.40, 69.40], [41.40, 69.10]]
HOME = {"lat": Decimal("41.311"), "lng": Decimal("69.279")}


def png_upload(name="photo.png", size=(1600, 1000)):
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 115, 0)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def zone(**kw):
    return DeliveryZone.objects.create(
        name=kw.pop("name", "Ташкент"), polygon=kw.pop("polygon", TASHKENT),
        price=kw.pop("price", Decimal("15000")), free_from=kw.pop("free_from", Decimal("300000")),
        min_order=kw.pop("min_order", Decimal("50000")), **kw,
    )


def branch(ext="BR001", lat="41.300", lng="69.270", **kw):
    return Branch.objects.create(
        external_id=ext, name=kw.pop("name", f"Филиал {ext}"), lat=Decimal(lat), lng=Decimal(lng),
        delivery_enabled=kw.pop("delivery_enabled", True), phone="998901112233", address="ул. Тестовая 1", **kw,
    )


def product(ext="TOV001", price="100000", publish=True, **kw):
    pet = PetType.objects.get_or_create(slug="dogs", defaults={"name": "Собаки"})[0]
    cat = Category.objects.get_or_create(slug="dog-food", defaults={"name": "Корм", "pet_type": pet})[0]
    group = ProductGroup.objects.create(
        name=kw.pop("group_name", f"Корм {ext}"), slug=f"g-{ext.lower()}", category=cat, is_published=publish,
        attributes=kw.pop("attributes", {}),
    )
    group.pet_types.add(pet)
    if publish:
        ProductImage.objects.create(group=group, image=png_upload())
    return Product.objects.create(
        external_id=ext, group=group, name=f"Корм {ext}", price=Decimal(price), variant_label="2 кг",
        barcode=f"478{ext[-3:]}", **kw,
    )


def stock(p, b, qty):
    return Stock.objects.update_or_create(product=p, branch=b, defaults={"real_quantity": Decimal(qty)})[0]


def customer(phone="998901234567", **kw):
    return User.objects.create_user(phone, first_name=kw.pop("first_name", "Камол"), **kw)
