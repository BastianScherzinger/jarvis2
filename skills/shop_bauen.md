# Skill: Shop / Django-Seite bauen (Dashboard-Agent)

So baust du eine komplette, **Railway-ready Django-Seite** im Dashboard. Grundlage ist
die mitgelieferte Vorlage `shop_vorlage/` — eine bewährte, lauffähige Struktur (aus
`firma_website_neu`). Du **kopierst** sie und **passt** sie an, statt alles neu zu schreiben.

## Werkzeuge
- `shop_skill` — diese Anleitung laden.
- `shop_new(name)` — kopiert `shop_vorlage/` nach `<Desktop>/<name>` (neuer Ordner).
- `shop_list(pfad)` / `shop_read(pfad)` / `shop_write(pfad, inhalt)` — Dateien im Projekt
  lesen/schreiben (Pfad relativ zum Desktop, z.B. `meinshop/config/settings.py`).
- `shop_git(name, repo_url)` — git init + commit + push nach GitHub (letzter Schritt).

## Workflow
1. **Name + Theme klären** (kurz fragen, wenn nicht genannt): Projektname, Akzentfarbe,
   Branche/Inhalt.
2. **`shop_new(name)`** — legt das Projekt in einem NEUEN Ordner aus der Vorlage an.
3. **Neu designen & anpassen** (mit `shop_read`/`shop_write`) — modernes, eigenständiges
   Design statt 0815-Vorlage:
   - `<name>/config/settings.py` → `SITE_NAME`, `SITE_URL`.
   - `<name>/static/css/variables.css` → Akzentfarbe/Theme.
   - `<name>/templates/base.html` + `templates/components/navbar.html` → Navbar/Branding.
   - `<name>/templates/home.html` → Hero/Begrüßung, Inhalte.
   - `<name>/apps/core/models.py` + `views.py` → Inhalte/Logik nach Bedarf.
4. **Prüfen** (lokal durch Sir): `python manage.py check` muss „0 issues" zeigen.
5. **Sir nach der GitHub-Repo-URL fragen**, dann `shop_git(name, repo_url)` → Push. Danach
   auf Railway „Deploy from GitHub" (Env-Variablen unten).

## Vorlagen-Struktur (in `shop_vorlage/`)
```
config/         settings.py (Railway-ready, python-decouple), urls, wsgi, asgi
apps/core/      views, urls, models, admin, migrations
apps/accounts/  Login/Profil (django-axes)
apps/dashboard/ Beispiel-Dashboard
templates/      base.html (Tailwind+Alpine, Sticky-Navbar, Mobile-Bottom-Nav), Seiten, components/
static/css/     variables.css (Theme), base, navbar, footer, responsive …
Dockerfile · start.sh (LF!) · Procfile · railway.json · runtime.txt · requirements.txt · docker-compose.yml · .env.example
```

## Railway-Env-Variablen
```
SECRET_KEY     = <generiert: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
DEBUG          = False
ALLOWED_HOSTS  = <domain>.up.railway.app
SITE_NAME      = <Name>
SITE_URL       = https://<domain>.up.railway.app
ADMIN_URL      = <zufälliger-pfad>/
DATABASE_URL   = (Railway PostgreSQL-Plugin setzt das automatisch)
```

## Fallstricke
- `start.sh` **muss LF-Zeilenenden** haben (shop_write speichert .sh automatisch mit LF).
- `whitenoise` direkt nach `SecurityMiddleware`; `django-axes` braucht `AxesMiddleware` +
  `AxesStandaloneBackend`.
- `STATICFILES_DIRS` ≠ `STATIC_ROOT`.
- `DEBUG=False` → `ALLOWED_HOSTS` setzen, sonst 400.
- Vor erstem Commit `.gitattributes` mit `*.sh text eol=lf`.

> Der Dashboard-Agent kann **kopieren + gezielt anpassen**. Den vollständigen Neu-Aufbau
> mit parallelen Agenten macht Claude Code (`/shop-bauen`) — die Vorlage ist dieselbe.
