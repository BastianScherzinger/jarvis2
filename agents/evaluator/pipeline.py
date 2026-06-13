"""
Evaluator-Pipeline — 3 Agenten-Threads lesen aus DB1, schreiben in DB2.
"""
import threading
import time
import json
import datetime

from agents.evaluator.web_analyst        import analyze
from agents.evaluator.social_researcher  import research
from agents.evaluator.score_writer       import evaluate
import db_raw
import db_evaluated
import logger


def run_continuous(on_update, stop_event, n_threads: int = 3) -> None:
    threads = []
    for i in range(n_threads):
        t = threading.Thread(
            target=_eval_loop,
            args=(i, on_update, stop_event),
            name=f"Evaluator-{i}",
            daemon=True,
        )
        t.start()
        threads.append(t)


def _eval_loop(worker_id: int, on_update, stop_event) -> None:
    while not stop_event.is_set():
        lead = db_raw.claim_next_pending()
        if not lead:
            time.sleep(5)
            continue

        raw_id = lead["id"]
        try:
            logger.eval_("Evaluator", f"Prüfe: {lead.get('name')} ({lead.get('stadt')})")
            # Agent 1: Website TIEF analysieren (findet Website aktiv, EINE Suche)
            web    = analyze(lead)
            # Agent 2: Social + Firmengröße — nutzt die Treffer von Agent 1 (keine 2. Suche)
            social = research(lead, web.get("search_hits"))
            logger.debug("SocialRes", f"Social: {list(social.get('social_media',{}).keys())}")
            # Agent 3: differenzierter Score + Ollama-Feinschliff + Pitch
            scored = evaluate(lead, web, social)

            # web überschreibt die (oft falschen) Scraper-Werte
            has_website = int(web.get("has_website", 0))
            bilder      = int(web.get("bilder_vorhanden", 0))

            # verify_log: nachvollziehbare Schritt-für-Schritt-Liste
            verify_log = list(web.get("verify_steps", []))
            verify_log.append(f"Score: {scored.get('score')} ({scored.get('lead_typ')})")

            # DB2 befüllen
            row = {
                # Basis aus DB1
                "raw_id":      raw_id,
                "schluessel":  lead.get("schluessel", ""),
                "name":        lead.get("name", ""),
                "adresse":     lead.get("adresse", ""),
                "stadt":       lead.get("stadt", ""),
                "bundesland":  lead.get("bundesland", ""),
                "branche":     lead.get("branche", ""),
                "telefon":     lead.get("telefon", ""),
                "fotos_in_maps": lead.get("bilder_maps", 0),
                "bewertet_am": datetime.datetime.now().isoformat(timespec="seconds"),
                # Agent 1 — überschreibt Scraper-Werte
                "has_website":         has_website,
                "website_url":         web.get("website_url", ""),
                "discovered_website":  web.get("discovered_website", ""),
                "bilder_vorhanden":    bilder,
                "foto_url":            web.get("foto_url") or lead.get("foto_url", ""),
                "email_vorhanden":     web.get("email_vorhanden", 0),
                "email_adresse":       web.get("email_adresse", ""),
                "telefon_verifiziert": web.get("telefon_verifiziert", 0),
                "website_veraltet":    web.get("website_veraltet", 0),
                "website_alter_jahre": web.get("website_alter_jahre", -1),
                "website_probleme":    json.dumps(web.get("website_probleme", []), ensure_ascii=False),
                "verify_log":          json.dumps(verify_log, ensure_ascii=False),
                "verifiziert":         1,
                # Agent 2
                "social_media":   json.dumps(social.get("social_media", {}), ensure_ascii=False),
                "hat_nur_social": social.get("hat_nur_social", 0),
                # Agent 3 (enthält score_breakdown, discovered_website, bilder_vorhanden)
                **scored,
            }

            db_evaluated.insert_evaluated(row)
            db_raw.update_eval_status(raw_id, "done")

            # Sofort in Supabase pushen (async, fire-and-forget)
            try:
                from cloud_sync import push_lead
                push_lead(row)
            except Exception:
                pass

            logger.success(
                "Evaluator",
                f"✓ {lead.get('name')}: Score {row.get('score')} ({row.get('lead_typ')}) | "
                f"Website: {'gefunden' if has_website else 'KEINE'} | "
                f"Bilder: {'ja' if bilder else 'nein'} | {row.get('potenzial_euro')}€",
            )
            on_update({"type": "evaluated", "data": row})

        except Exception as e:
            db_raw.update_eval_status(raw_id, "failed")
            logger.error("Evaluator", f"Fehler bei {lead.get('name')}: {e}")
            on_update({"_error": f"Evaluator-{worker_id} ({lead.get('name')}): {e}"})
