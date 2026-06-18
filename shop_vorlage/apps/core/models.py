from django.db import models


class Anfrage(models.Model):
    LEISTUNG_CHOICES = [
        ('komplettsanierung', 'Komplettsanierung'),
        ('badsanierung', 'Badsanierung'),
        ('wohnungssanierung', 'Wohnungssanierung'),
        ('fassadensanierung', 'Fassadensanierung'),
        ('malerarbeiten', 'Malerarbeiten'),
        ('boden_fliesen', 'Boden & Fliesen'),
        ('sonstiges', 'Sonstiges / Anfrage'),
    ]

    leistung = models.CharField(max_length=50, choices=LEISTUNG_CHOICES, verbose_name='Leistungsart')
    zusatz_info = models.TextField(blank=True, verbose_name='Zusätzliche Informationen')
    name = models.CharField(max_length=200, verbose_name='Name')
    email = models.EmailField(verbose_name='E-Mail')
    telefon = models.CharField(max_length=50, blank=True, verbose_name='Telefonnummer')
    adresse = models.CharField(max_length=500, blank=True, verbose_name='Adresse')
    erstellt_am = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-erstellt_am']
        verbose_name = 'Anfrage'
        verbose_name_plural = 'Anfragen'

    def __str__(self):
        return f'{self.name} – {self.get_leistung_display()} – {self.erstellt_am:%Y-%m-%d %H:%M}'


class PageVisit(models.Model):
    path = models.CharField(max_length=512)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Seitenaufruf'
        verbose_name_plural = 'Seitenaufrufe'

    def __str__(self):
        return f'{self.path} – {self.timestamp:%Y-%m-%d %H:%M}'
