"""
Django-Settings — schlanke, datenbankfreie Landing-Page.

Bewusst minimal: keine Auth, keine Sessions, keine Migrationen, kein Admin.
Dadurch deployt die Seite ohne Datenbank-Plugin sofort auf Railway.
Alle umgebungsabhängigen Werte kommen aus Umgebungsvariablen (Railway).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SECRET_KEY MUSS in Produktion via Umgebungsvariable gesetzt werden (Railway).
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-nur-lokal-bitte-ueberschreiben")

DEBUG = os.environ.get("DEBUG", "False").strip().lower() in ("1", "true", "yes")

# ALLOWED_HOSTS: kommagetrennt aus Env; default '*' (öffentliche Landing-Page).
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# CSRF-Trusted-Origins (Railway-Domain), kommagetrennt, müssen mit https:// beginnen.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "landing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Keine Datenbank — die Landing-Page nutzt das ORM nicht.
DATABASES = {}

LANGUAGE_CODE = "de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Nicht-Manifest-Storage: vergebene /static/-Pfade bleiben unverändert (robust
# bei dynamisch eingebauten Lead-Fotos), Komprimierung trotzdem aktiv.
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Hinter Railways HTTPS-Proxy korrektes Schema erkennen.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
