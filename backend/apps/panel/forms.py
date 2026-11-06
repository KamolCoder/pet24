from django import forms
from django.utils.text import slugify
from unidecode import unidecode

from apps.catalog.models import Branch, Brand, Category, PetType, ProductGroup
from apps.customers.models import User, normalize_phone
from apps.delivery.models import DeliveryZone


def unique_slug(model, base: str, exclude_pk=None) -> str:
    base = slugify(unidecode(base))[:300] or "item"
    slug, n = base, 1
    qs = model.objects.exclude(pk=exclude_pk) if exclude_pk else model.objects.all()
    while qs.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


class AutoSlugForm(forms.ModelForm):
    """slug may be left empty: generated from name (transliterated)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "slug" in self.fields:
            self.fields["slug"].required = False
            self.fields["slug"].help_text = "Можно оставить пустым — заполнится из названия"

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        if slug:
            return slug
        return unique_slug(self._meta.model, self.cleaned_data.get("name") or "", self.instance.pk)


class PetTypeForm(AutoSlugForm):
    class Meta:
        model = PetType
        fields = ["name", "slug", "icon", "sort"]


class CategoryForm(AutoSlugForm):
    class Meta:
        model = Category
        fields = ["name", "slug", "parent", "pet_type", "image", "sort", "is_active"]

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk and parent.pk in self.instance.descendant_ids():
            raise forms.ValidationError("Категория не может быть вложена сама в себя")
        return parent


class BrandForm(AutoSlugForm):
    class Meta:
        model = Brand
        fields = ["name", "slug", "logo"]


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["address", "phone", "lat", "lng", "work_from", "work_to", "delivery_enabled"]
        widgets = {"work_from": forms.TimeInput(attrs={"type": "time"}), "work_to": forms.TimeInput(attrs={"type": "time"})}

    def clean(self):
        data = super().clean()
        if data.get("delivery_enabled") and (data.get("lat") is None or data.get("lng") is None):
            raise forms.ValidationError("Для доставки нужны координаты филиала")
        return data


class ZoneForm(forms.ModelForm):
    class Meta:
        model = DeliveryZone
        fields = ["name", "price", "free_from", "min_order", "max_branch_km", "priority", "is_active", "polygon"]
        widgets = {"polygon": forms.Textarea(attrs={"rows": 6, "class": "mono"})}


class StaffForm(forms.ModelForm):
    phone = forms.CharField(label="Телефон", max_length=30)
    password = forms.CharField(label="Пароль", required=False, widget=forms.PasswordInput(render_value=False),
                               help_text="При редактировании оставьте пустым, чтобы не менять. Минимум 8 символов")

    class Meta:
        model = User
        fields = ["phone", "first_name", "last_name", "role", "branch", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(User.Role.PICKER, "Сборщик филиала"), (User.Role.OPERATOR, "Оператор")]
        if self.instance.pk:
            self.initial["phone"] = self.instance.phone

    def clean_phone(self):
        try:
            phone = normalize_phone(self.cleaned_data["phone"])
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e
        other = User.objects.filter(phone=phone).exclude(pk=self.instance.pk).first()
        if other:
            raise forms.ValidationError("Этот номер уже зарегистрирован" + (" как покупатель" if other.role == "customer" else ""))
        return phone

    def clean(self):
        data = super().clean()
        if data.get("role") == User.Role.PICKER and not data.get("branch"):
            self.add_error("branch", "Сборщику нужен филиал")
        pwd = data.get("password")
        if not self.instance.pk and not pwd:
            self.add_error("password", "Задайте пароль")
        if pwd and len(pwd) < 8:
            self.add_error("password", "Минимум 8 символов")
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class ProductGroupForm(AutoSlugForm):
    attributes = forms.JSONField(label="Атрибуты для фильтров", required=False,
                                 widget=forms.Textarea(attrs={"rows": 3, "class": "mono"}),
                                 help_text='Например: {"age": "adult", "size": "small", "flavor": "chicken"}')

    class Meta:
        model = ProductGroup
        fields = ["name", "slug", "category", "brand", "pet_types", "sort", "is_published",
                  "description", "composition", "feeding_guide", "attributes"]
        widgets = {
            "pet_types": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={"rows": 5}),
            "composition": forms.Textarea(attrs={"rows": 3}),
            "feeding_guide": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_attributes(self):
        v = self.cleaned_data.get("attributes")
        if v in (None, ""):
            return {}
        if not isinstance(v, dict):
            raise forms.ValidationError("Нужен JSON-объект {...}")
        return v

    def clean(self):
        data = super().clean()
        if data.get("is_published"):
            if not data.get("category"):
                self.add_error("category", "Без категории карточку не опубликовать")
            if self.instance.pk and not self.instance.images.exists():
                self.add_error("is_published", "Сначала загрузите хотя бы одно фото")
            if not self.instance.pk:
                self.add_error("is_published", "Сохраните карточку и загрузите фото, затем публикуйте")
        return data
