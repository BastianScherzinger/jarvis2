from django.conf import settings


def global_context(request):
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'Meine Firma'),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
        'DEBUG': settings.DEBUG,
        'ADMIN_EMAIL': getattr(settings, 'ADMIN_EMAIL', ''),
    }
