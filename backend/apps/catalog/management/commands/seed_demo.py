"""Fill an EMPTY dev database with demo data: branches, catalog with photos, customers, ~260 orders over 45 days.

    python manage.py seed_demo            # refuses if there are orders already or DEBUG is off
    python manage.py seed_demo --force    # run anyway (never on production!)

Operator login afterwards: phone 998900000000, password admin12345.
"""
import io
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image

from apps.catalog.models import Branch, Brand, Category, PetType, Product, ProductGroup, ProductImage, Stock, SyncLog
from apps.customers.models import User
from apps.delivery.models import DeliveryZone, Shipment
from apps.orders.models import Order, OrderEvent, OrderItem

TASHKENT = [[41.20, 69.10], [41.20, 69.40], [41.40, 69.40], [41.40, 69.10]]
BAG_COLORS = [(215, 38, 61), (123, 79, 214), (42, 120, 214), (27, 175, 122), (237, 161, 0)]


def bag_image(name: str, color) -> SimpleUploadedFile:
    img = Image.new("RGB", (900, 900), (247, 247, 249))
    bag = Image.new("RGB", (460, 620), color)
    img.paste(bag, (220, 140))
    img.paste(Image.new("RGB", (300, 180), (255, 255, 255)), (300, 380))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class Command(BaseCommand):
    help = "Fill an empty dev database with demo data"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    @transaction.atomic
    def handle(self, *args, force=False, **opts):
        if not force and (not settings.DEBUG or Order.objects.exists() or Branch.objects.exists()):
            raise CommandError("Only for an empty dev DB with DEBUG=1 (use --force to override)")
        rnd = random.Random(7)
        now = timezone.now()

        if not User.objects.filter(phone="998900000000").exists():
            User.objects.create_superuser("998900000000", "admin12345", first_name="Оператор")
        dogs = PetType.objects.create(name="Собаки", slug="dogs", sort=1)
        cats = PetType.objects.create(name="Кошки", slug="cats", sort=2)
        PetType.objects.create(name="Грызуны", slug="rodents", sort=3)
        dog_food = Category.objects.create(name="Корм для собак", slug="dog-food", pet_type=dogs)
        cat_food = Category.objects.create(name="Корм для кошек", slug="cat-food", pet_type=cats)
        brands = [Brand.objects.create(name=n, slug=n.lower().replace(" ", "-"))
                  for n in ("Acana", "Royal Canin", "Brit", "Pro Plan")]

        branches = []
        for i, (name, lat, lng) in enumerate([("Чиланзар", 41.285, 69.204), ("Юнусабад", 41.364, 69.288),
                                              ("Мирзо-Улугбек", 41.326, 69.335), ("Сергели", 41.226, 69.221)]):
            branches.append(Branch.objects.create(
                external_id=f"BR00{i + 1}", name=name, lat=lat, lng=lng, delivery_enabled=i < 3,
                phone="998712000000", address=f"{name}, ул. Тестовая {i + 1}", synced_at=now,
            ))
        Branch.objects.create(external_id="BR099", name="Центральный склад")
        zone = DeliveryZone.objects.create(name="Ташкент", polygon=TASHKENT, price=15000, free_from=300000, min_order=50000)

        skus = []
        for i in range(14):
            line = ["Adult", "Puppy", "Light", "Sterilised"][i % 4]
            group = ProductGroup.objects.create(
                name=f"{brands[i % 4].name} {line} {i}", slug=f"demo-{i}", category=dog_food if i % 2 else cat_food,
                brand=brands[i % 4], is_published=i < 11, description="Полнорационный сухой корм.",
            )
            group.pet_types.add(dogs if i % 2 else cats)
            if i < 12:
                ProductImage.objects.create(group=group, image=bag_image(f"demo{i}.png", BAG_COLORS[i % 5]))
            for j, (label, mult) in enumerate([("2 кг", 1), ("7 кг", 3)]):
                p = Product.objects.create(
                    external_id=f"TOV{i:03d}{j}", group=group, name=f"{group.name} {label}", variant_label=label,
                    price=Decimal(80000 + i * 9000) * mult, barcode=f"4780{i:03d}{j}", unit="шт", weight_g=2100 * mult,
                )
                skus.append(p)
                for b in branches:
                    Stock.objects.create(product=p, branch=b, real_quantity=rnd.randint(0, 12))
        for i in range(23):
            Product.objects.create(external_id=f"Q{i:03d}", name=f"Наполнитель древесный {5 + i % 3 * 5} л, вар. {i}",
                                   price=25000 + i * 1000, barcode=f"47811{i:03d}", unit="шт")

        customers = [User.objects.create_user(f"99890{1000000 + i:07d}",
                                              first_name=rnd.choice(["Азиз", "Нодира", "Дилшод", "Малика", "Жасур"]))
                     for i in range(40)]
        for k in range(260):
            created = now - timedelta(days=rnd.random() * 45, hours=rnd.random() * 3)
            branch = rnd.choice(branches[:3])
            lines = rnd.sample(skus, rnd.randint(1, 3))
            items_total = sum(p.price for p in lines)
            delivery = Decimal(0) if items_total >= 300000 else Decimal(15000)
            user = rnd.choice(customers[: rnd.choice([10, 40])])
            status = rnd.choices(["delivered", "canceled", "problem", "paid", "new"], [80, 8, 3, 5, 4])[0]
            if created > now - timedelta(hours=6) and status == "delivered":
                status = rnd.choice(["paid", "assembling", "courier_assigned", "delivering"])
            order = Order.objects.create(
                user=user, branch=branch, zone=zone, status=status, payment_method=rnd.choice(["payme", "payme", "click"]),
                items_total=items_total, delivery_price=delivery, total=items_total + delivery,
                customer_name=user.first_name, customer_phone=user.phone, address="ул. Навои, 12",
                lat=Decimal("41.311"), lng=Decimal("69.279"),
            )
            paid = None
            if status != "new" and not (status == "canceled" and rnd.random() < 0.6):
                paid = created + timedelta(minutes=rnd.randint(1, 8))
            assembled = (paid + timedelta(minutes=rnd.randint(8, 45))
                         if paid and status in ("delivered", "courier_assigned", "delivering") else None)
            delivered = assembled + timedelta(minutes=rnd.randint(20, 70)) if assembled and status == "delivered" else None
            payment_status = "paid" if paid and status != "canceled" else ("refunded" if paid else "pending")
            Order.objects.filter(pk=order.pk).update(
                created_at=created, paid_at=paid, assembled_at=assembled, delivered_at=delivered,
                payment_status=payment_status, problem_note="нет на полке" if status == "problem" else "",
            )
            for p in lines:
                OrderItem.objects.create(order=order, product=p, external_id=p.external_id, name=p.display_name,
                                         barcode=p.barcode, price=p.price, quantity=1)
            if assembled:
                Shipment.objects.create(order=order, provider="yandex", external_id=f"demo-{k}",
                                        status="delivered" if delivered else "assigned",
                                        cost=Decimal(rnd.randint(14, 26) * 1000), courier_name="Алишер")
            if status == "problem":
                OrderEvent.objects.create(order=order, from_status="paid", to_status="problem", note="нет на полке")
        for kind in ("branches", "products", "stock"):
            SyncLog.objects.create(kind=kind, started_at=now - timedelta(minutes=3),
                                   finished_at=now - timedelta(minutes=3) + timedelta(seconds=4), ok=True, result={"count": 120})
        self.stdout.write(self.style.SUCCESS(
            f"Demo data: {Order.objects.count()} orders, {Product.objects.count()} SKU. "
            "Panel login: 998900000000 / admin12345"))
