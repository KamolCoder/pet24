from django.urls import path

from . import views

urlpatterns = [
    path("pet-types/", views.PetTypeList.as_view()),
    path("categories/", views.CategoryTree.as_view()),
    path("brands/", views.BrandList.as_view()),
    path("branches/", views.BranchList.as_view()),
    path("products/", views.ProductList.as_view()),
    path("products/<slug:slug>/", views.ProductDetail.as_view()),
]
