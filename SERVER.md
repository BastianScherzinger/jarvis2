# JARVIS — Server-/Produktionsbetrieb

JARVIS läuft als Flask-App. Für Dauerbetrieb (Server/VPS/Container) den robusten
**waitress**-WSGI-Server nutzen statt des Flask-Dev-Servers.

## Schnellstart (Produktion)
```bash
pip install -r requirements.txt        # enthält waitress
python serve.py                        # 0.0.0.0:5000, waitress, mehrere Threads
```
`serve.py` setzt `JARVIS_SERVER=1`, kein Boot-Screen, kein Browser-Autostart.

## Konfiguration (Environment / .env)
| Variable          | Default            | Zweck                                   |
|-------------------|--------------------|-----------------------------------------|
| `JARVIS_HOST`     | `0.0.0.0`          | Bind-Adresse                            |
| `JARVIS_PORT`/`PORT` | `5000`          | Port                                    |
| `JARVIS_THREADS`  | 2× CPU-Kerne (8–32)| waitress-Worker-Threads                 |
| `JARVIS_SERVER`/`JARVIS_PROD` | –      | `1` = Produktionsserver (waitress)      |

`python app.py` respektiert dieselbe Konfiguration: mit `JARVIS_SERVER=1` → waitress,
sonst Flask-Dev-Server (beide über `app.run_server()`).

## Hinter einem Reverse-Proxy (TLS)
nginx/Caddy davor für HTTPS. **Wichtig für SSE** (`/api/stream`, Chat-Streams):
Proxy-Buffering ausschalten — die App setzt bereits `X-Accel-Buffering: no`, in nginx
zusätzlich:
```nginx
location / {
    proxy_pass         http://127.0.0.1:5000;
    proxy_http_version 1.1;
    proxy_set_header   Connection "";
    proxy_buffering    off;            # SSE/Streaming
    proxy_read_timeout 300s;           # lange Tool-/Medien-Jobs
}
```

## Headless / ohne Desktop
Browser-Automation (Playwright) headless betreiben:
```
JARVIS_BROWSER_HEADLESS=true
```

## Hardware-Hinweise
- **Lokale Bilder:** hardware-adaptiv (CPU→SD-Turbo schnell, GPU→SDXL/FLUX). Default ist
  jetzt **Auto** (`JARVIS_IMAGE_AUTO=1`) — lohnt sich lokal ohne Konfiguration. Mit
  `JARVIS_IMAGE_AUTO=0` gilt `JARVIS_IMAGE_MODEL` aus der .env.
- **Lokale Videos:** brauchen eine **GPU** (Wan 2.1). Auf reiner CPU bricht die lokale
  Videogenerierung mit klarer Meldung ab → Higgsfield Cloud nutzen.
- **32-GB-RAM-PC ohne GPU:** Bilder lokal mit SD-Turbo (Sekunden), CPU-Threads werden
  voll genutzt, SDXL läuft dank attention-slicing/vae-tiling ohne OOM (aber langsamer).
- **Ollama-Profil:** `start.py` empfiehlt anhand RAM/VRAM automatisch (32 GB RAM →
  `qwen2.5:14b`). Modell in der .env als `JARVIS_EVAL_MODEL`.

## Prozess-Manager (Beispiel)
systemd-Unit:
```ini
[Service]
WorkingDirectory=/opt/jarvis
Environment=JARVIS_SERVER=1
Environment=JARVIS_PORT=5000
ExecStart=/usr/bin/python3 serve.py
Restart=always
```
