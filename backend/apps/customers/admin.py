from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Address, Pet, User


class PetInline(admin.TabularInline):
    model = Pet
    extra = 0


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("phone",)


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    ordering = ["-date_joined"]
    list_display = ["phone", "first_name", "last_name", "role", "branch", "is_active", "date_joined"]
    list_filter = ["role", "branch", "is_active", "is_staff"]
    search_fields = ["phone", "first_name", "last_name"]
    inlines = [PetInline, AddressInline]
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Профиль", {"fields": ("first_name", "last_name")}),
        ("Доступ", {"fields": ("role", "branch", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "password1", "password2", "role", "branch")}),)
