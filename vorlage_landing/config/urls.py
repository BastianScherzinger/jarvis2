"""URL-Konfiguration — eine Landing-Page unter '/'."""
from django.urls import path

from landing import views

urlpatterns = [
    path("", views.index, name="index"),
    path("health", views.health, name="health"),
]
