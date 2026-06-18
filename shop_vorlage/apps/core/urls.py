from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('dienstleistungen/', views.dienstleistungen, name='dienstleistungen'),
    path('ueber-uns/', views.ueber_uns, name='ueber_uns'),
    path('kontakt/', views.kontakt, name='kontakt'),
    path('anfrage/', views.anfrage, name='anfrage'),
    path('leistungen/', views.leistungen, name='leistungen'),
    path('impressum/', views.impressum, name='impressum'),
    path('datenschutz/', views.datenschutz, name='datenschutz'),
    path('agb/', views.agb, name='agb'),
    path('standorte/', views.standorte, name='standorte'),
]
