"""
Lead-Verifier — prüft jeden gefundenen Lead per lokaler KI nach.
Website-Analyse + Web-Recherche + Ollama-Bewertung → verified_score + Pitch-Hook.
"""
import re
import time
import threading
from datetime import date

from agents.scorer import combine_score
from scrapers import _http
import db
import logger

# Erkennungs-Muster
_VIEWPORT_RE   = re.compile(r'name=["\']viewport["\']', re.IGNORECASE)
_COPYRIGHT_RE  = re.compile(r'(?:©|&copy;|copyright)\s*(20\d\d)', re.IGNORECASE)
_VERALTET      = ("<font", "<marquee", ".swf", "frameset", "<frameset")

_SOCIAL_DOMAINS = {
    "facebook":  "facebook.com",
    "instagram": "instagram.com",
    "linkedin":  "linkedin.com",
    "youtube":   "youtube.com",
    "twitter":   "twitter.com",
    "tiktok":    "tiktok.com",
}
_PORTALE = ("trustpilot", "11880", "golocal", "provenexpert", "yelp")


# ── Öffentliche Schleifen-API ──────────────────────────────────────────────────

def run_continuous(on_update, stop_event, n_threads: int = 3) -> None:
    """Startet n_threads Verifier-Threads (daemon, werden nicht gejoint)."""
    for i in range(max(1, n_threads)):
        threading.Thread(
            target=_verify_loop, args=(i + 1, on_update, stop_event),
            name=f"Verifier-{i + 1}", daemon=True,
        ).start()


def _verify_loop(worker_id, on_update, stop_event):
    while not stop_event.is_set():
        lead = db.claim_next_pending()
        if not lead:
            time.sleep(5)
            continue
        try:
            logger.info("Verifier", f"Prüfe: {lead.get('name')} ({lead.get('stadt')})")
            result = verify_lead(lead)
            db.update_verification(lead["id"], result)
            lead.update(result)
            logger.success("Verifier", f"Verifiziert: {lead.get('name')} → {result.get('end_score')} Pkt ({result.get('lead_typ')})")
            on_update({"type": "verified", "data": lead})
        except Exception as e:
            logger.error("Verifier", f"Fehler bei {lead.get('name')}: {e}")
            try:
                db.update_verification(lead["id"], {
                    "verify_status": "failed",
                    "verified_score": -1,
                    "end_score": lead.get("score", 0),
                    "lead_typ": lead.get("lead_typ", "Cold"),
                    "verify_begruendung": f"Verifikation fehlgeschlagen: {e}"[:300],
                })
            except Exception:
                pass


# ── Kern ────────────────────────────────────────────────────────────────────

def verify_lead(lead: dict) -> dict:
    has_website = bool(lead.get("has_website")) and bool(lead.get("website_url"))
    web = _analyze_website(lead.get("website_url", "")) if has_website else {
        "issues": ["Keine eigene Website"], "mobile": False, "https": False,
        "copyright_jahr": None, "impressum": False,
    }
    recherche = _web_recherche(lead.get("name", ""), lead.get("stadt", ""))
    bewertung = _ollama_bewertung(lead, web, recherche)

    end_score, typ = combine_score(
        int(lead.get("score", 0) or 0),
        int(bewertung.get("verified_score", 0) or 0),
    )

    return {
        "verified_score":     int(bewertung.get("verified_score", 0)),
        "pitch_hook":         bewertung.get("pitch_hook", ""),
        "verify_begruendung": bewertung.get("begruendung", ""),
        "website_issues":     web.get("issues", []),
        "social_media":       recherche.get("social_media", {}),
        "end_score":          end_score,
        "lead_typ":           typ,
        "verify_status":      "verified",
    }


def _analyze_website(url: str) -> dict:
    out = {"issues": [], "mobile": False, "https": False,
           "copyright_jahr": None, "impressum": False}
    if url and not url.startswith("http"):
        url = "https://" + url

    out["https"] = url.startswith("https://")
    if not out["https"]:
        out["issues"].append("Kein HTTPS")

    html = _http.get(url, timeout=8) if url else ""
    if not html:
        out["issues"].append("Website nicht erreichbar")
        return out

    low = html.lower()

    # Mobile-Viewport
    out["mobile"] = bool(_VIEWPORT_RE.search(html))
    if not out["mobile"]:
        out["issues"].append("Kein Mobile-Viewport")

    # Copyright-Jahr (höchstes gefundenes)
    jahre = [int(m) for m in _COPYRIGHT_RE.findall(html)]
    if jahre:
        jahr = max(jahre)
        out["copyright_jahr"] = jahr
        alt = date.today().year - jahr
        if alt >= 3:
            out["issues"].append(f"Copyright {jahr} — {alt} Jahre alt")

    # Pflicht-Seiten
    out["impressum"] = "impressum" in low
    if not out["impressum"]:
        out["issues"].append("Kein Impressum")
    if "datenschutz" not in low:
        out["issues"].append("Keine Datenschutzerklärung")

    # Veraltete Technik-Signale
    if any(sig in low for sig in _VERALTET):
        out["issues"].append("Veraltete Technik (Flash/Frames/Marquee)")

    return out


def _web_recherche(name: str, stadt: str) -> dict:
    out = {"social_media": {}, "portale": [], "hat_nur_social": False}
    if not name:
        return out

    results = _http.ddg_search(f'"{name}" {stadt}'.strip())
    eigene_seite = False
    for res in results:
        url = (res.get("url") or "").lower()
        if not url:
            continue
        matched_social = False
        for key, domain in _SOCIAL_DOMAINS.items():
            if domain in url and key not in out["social_media"]:
                out["social_media"][key] = res["url"]
                matched_social = True
        if matched_social:
            continue
        for portal in _PORTALE:
            if portal in url and portal not in out["portale"]:
                out["portale"].append(portal)
                matched_social = True
        if not matched_social and url.startswith("http"):
            eigene_seite = True

    out["hat_nur_social"] = bool(out["social_media"]) and not eigene_seite
    return out


def _ollama_bewertung(lead: dict, web: dict, recherche: dict) -> dict:
    heuristik = int(lead.get("score", 0) or 0)

    system = (
        "Du bist ein B2B-Vertriebsanalyst. Bewerte Verkaufschancen für "
        "Webdesign-Dienstleistungen. Antworte NUR mit JSON."
    )
    signale = {
        "branche":         lead.get("branche", ""),
        "stadt":           lead.get("stadt", ""),
        "has_website":     bool(lead.get("has_website")),
        "website_issues":  web.get("issues", []),
        "rating":          lead.get("bewertung", 0),
        "anz_bewertungen": lead.get("anz_bewertungen", 0),
        "telefon":         bool(lead.get("telefon")),
        "nur_social_media": recherche.get("hat_nur_social", False),
        "social_media":    list(recherche.get("social_media", {}).keys()),
    }
    sig_text = "\n".join(f"- {k}: {v}" for k, v in signale.items())
    prompt = (
        f"Betrieb: {lead.get('name', '')}\n"
        f"Signale:\n{sig_text}\n\n"
        "Bewerte die Verkaufschance für eine neue/überarbeitete Website (0-100). "
        "Je mehr Mängel und je aktiver der Betrieb, desto höher die Chance.\n"
        'Antworte NUR mit JSON: {"verified_score": 0-100, '
        '"begruendung": "1-2 Sätze", '
        '"pitch_hook": "1 Satz Verkaufsaufhänger, direkt verwendbar"}'
    )

    raw = _http.ask_ollama(prompt, system)
    data = _http.extract_json(raw)

    if not data:
        # Ollama nicht erreichbar / kein valides JSON → Heuristik übernehmen
        return {
            "verified_score": heuristik,
            "begruendung":    "Ollama nicht verfügbar — Heuristik übernommen",
            "pitch_hook":     "",
        }

    try:
        score = int(float(data.get("verified_score", heuristik)))
    except (TypeError, ValueError):
        score = heuristik
    score = max(0, min(100, score))

    return {
        "verified_score": score,
        "begruendung":    str(data.get("begruendung", ""))[:300],
        "pitch_hook":     str(data.get("pitch_hook", ""))[:300],
    }
