from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class CoreSitemap(Sitemap):
    protocol = 'https'

    pages = [
        ('core:home',             1.0, 'weekly'),
        ('core:dienstleistungen', 0.9, 'monthly'),
        ('core:standorte',        0.9, 'monthly'),
        ('core:anfrage',          0.8, 'monthly'),
        ('core:ueber_uns',        0.7, 'monthly'),
    ]

    def items(self):
        return self.pages

    def location(self, item):
        return reverse(item[0])

    def priority(self, item):
        return item[1]

    def changefreq(self, item):
        return item[2]
