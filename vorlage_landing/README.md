# Landing-Vorlage (JARVIS Website-Builder)

Schlanke, **datenbankfreie** Django-Landing-Page. Wird vom JARVIS-Website-Builder
kopiert und über `content.json` mit echten Lead-Daten + Fotos gefüllt.

## Anpassen
Der gesamte Inhalt steckt in **`content.json`** (Texte, Telefon, E-Mail, Fotos,
Akzentfarbe `akzent`). Das Layout liegt in `templates/index.html`, das Design in
`static/css/style.css`.

## Lokal starten
```bash
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py runserver
```
→ http://127.0.0.1:8000

## Deploy (Railway)
Nixpacks erkennt Django automatisch. Wichtige Umgebungsvariablen:

| Variable             | Wert                                   |
|----------------------|----------------------------------------|
| `SECRET_KEY`         | generierter Django-Key                 |
| `DEBUG`              | `False`                                |
| `ALLOWED_HOSTS`      | `<projekt>.up.railway.app`             |
| `CSRF_TRUSTED_ORIGINS` | `https://<projekt>.up.railway.app`   |

Kein Datenbank-Plugin nötig — die Seite nutzt das ORM nicht.
