from django.contrib import admin
from .models import PageVisit, Anfrage


@admin.register(PageVisit)
class PageVisitAdmin(admin.ModelAdmin):
    list_display = ('path', 'ip_address', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('path', 'ip_address')
    readonly_fields = ('path', 'ip_address', 'user_agent', 'timestamp')


@admin.register(Anfrage)
class AnfrageAdmin(admin.ModelAdmin):
    list_display = ('name', 'leistung', 'email', 'telefon', 'erstellt_am')
    list_filter = ('leistung', 'erstellt_am')
    search_fields = ('name', 'email', 'adresse')
    readonly_fields = ('erstellt_am',)
