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
            # Agent 1: Website analysieren
            web    = analyze(lead)
            logger.debug("WebAnalyst", f"Website: {len(web.get('website_probleme',[]))} Probleme | Email: {'ja' if web.get('email_vorhanden') else 'nein'}")
            # Agent 2: Social + Firmengröße recherchieren
            social = research(lead)
            logger.debug("SocialRes", f"Social: {list(social.get('social_media',{}).keys())}")
            # Agent 3: Ollama-Bewertung + Score + Pitch
            scored = evaluate(lead, web, social)
            logger.eval_("ScoreWriter", f"Score: {scored.get('score')} | {scored.get('lead_typ')} | Potenzial: {scored.get('potenzial_euro')}€")

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
                "has_website": lead.get("has_website", 0),
                "website_url": lead.get("website_url", ""),
                "fotos_in_maps": lead.get("bilder_maps", 0),
                "bewertet_am": datetime.datetime.now().isoformat(timespec="seconds"),
                # Agent 1
                "email_vorhanden":     web.get("email_vorhanden", 0),
                "email_adresse":       web.get("email_adresse", ""),
                "telefon_verifiziert": web.get("telefon_verifiziert", 0),
                "website_veraltet":    web.get("website_veraltet", 0),
                "website_alter_jahre": web.get("website_alter_jahre", -1),
                "website_probleme":    json.dumps(web.get("website_probleme", []), ensure_ascii=False),
                # Agent 2
                "social_media":   json.dumps(social.get("social_media", {}), ensure_ascii=False),
                "hat_nur_social": social.get("hat_nur_social", 0),
                # Agent 3
                **scored,
            }

            db_evaluated.insert_evaluated(row)
            db_raw.update_eval_status(raw_id, "done")

            logger.success("Evaluator", f"Bewertet: {lead.get('name')} → {row.get('score')} Pkt ({row.get('lead_typ')})")
            on_update({"type": "evaluated", "data": row})

        except Exception as e:
            db_raw.update_eval_status(raw_id, "failed")
            logger.error("Evaluator", f"Fehler bei {lead.get('name')}: {e}")
            on_update({"_error": f"Evaluator-{worker_id} ({lead.get('name')}): {e}"})
