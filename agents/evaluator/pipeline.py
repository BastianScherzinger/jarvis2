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
            _t0 = time.time()
            _nm = lead.get("name") or "?"
            logger.eval_("Evaluator", f"Prüfe: {_nm} ({lead.get('stadt')})")
            # Jeder der 3 Agenten meldet Start UND Ergebnis mit EIGENEM Worker-Namen —
            # so reagiert im Graph pro Agent eine eigene Station (ANALYSE/RECHERCHE/SCORING)
            # und wirklich jeder Bewertungs-Schritt wird als Punkt sichtbar.
            # Agent 1: Website TIEF analysieren (findet Website aktiv, EINE Suche)
            logger.eval_("WebAnalyst", f"→ Website-Analyse: {_nm}")
            web    = analyze(lead)
            logger.eval_("WebAnalyst",
                         f"✓ {_nm}: Website {'gefunden' if int(web.get('has_website', 0)) else 'KEINE'}"
                         f" · Bilder {'ja' if int(web.get('bilder_vorhanden', 0)) else 'nein'}")
            # Agent 2: Social + Firmengröße — nutzt die Treffer von Agent 1 (keine 2. Suche)
            logger.eval_("SocialRes", f"→ Social-Recherche: {_nm}")
            social = research(lead, web.get("search_hits"))
            logger.eval_("SocialRes",
                         f"✓ {_nm}: {', '.join(social.get('social_media', {}).keys()) or 'kein Social'}")
            # Agent 3: differenzierter Score + Ollama-Feinschliff + Pitch
            logger.eval_("ScoreWriter", f"→ Scoring: {_nm}")
            scored = evaluate(lead, web, social)

            # web überschreibt die (oft falschen) Scraper-Werte
            has_website = int(web.get("has_website", 0))
            bilder      = int(web.get("bilder_vorhanden", 0))

            # verify_log: nachvollziehbare Schritt-für-Schritt-Liste
            verify_log = list(web.get("verify_steps", []))
            verify_log.append(f"Score: {scored.get('score')} ({scored.get('lead_typ')})")

            # Bilder zusammenführen: Website-Bilder (Agent 1) + Maps-Galerie (DB1)
            try:
                maps_urls = json.loads(lead.get("foto_urls") or "[]")
            except Exception:
                maps_urls = []
            alle_bilder = [u for u in (list(web.get("foto_urls", [])) + maps_urls) if u]
            alle_bilder = list(dict.fromkeys(alle_bilder))[:12]

            # Firmenname: db_raw liefert bereits den deterministisch gesäuberten
            # (quick_clean) Namen. Optionaler lokaler-KI-Feinschliff nur bei noch
            # verdächtig langen/wortreichen Namen — best-effort, fällt sicher zurück.
            # WICHTIG: lead_key bleibt STABIL aus dem deterministischen Namen, damit
            # die Cloud-Deduplizierung (Multi-PC) nicht durch KI-Varianz bricht.
            from agents import name_clean
            import leadkey
            roh_name = lead.get("name", "")
            disp_name = roh_name
            if len(roh_name) > 38 or len(roh_name.split()) > 5:
                disp_name = name_clean.ai_clean(roh_name, lead.get("branche", ""),
                                                lead.get("stadt", ""))
            stabiler_key = leadkey.lead_key(roh_name, lead.get("stadt", ""))

            # DB2 befüllen
            row = {
                # Basis aus DB1
                "raw_id":      raw_id,
                "schluessel":  lead.get("schluessel", ""),
                "finder":      lead.get("finder", ""),
                "name":        disp_name,
                "lead_key":    stabiler_key,
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
                "foto_urls":           json.dumps(alle_bilder, ensure_ascii=False),
                "email_vorhanden":     web.get("email_vorhanden", 0),
                "email_adresse":       web.get("email_adresse", ""),
                "email_alle":          json.dumps(web.get("email_alle", []), ensure_ascii=False),
                "ansprechpartner":     web.get("ansprechpartner", ""),
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

            # Archivierte Leads (gute bestehende Website → kein Potenzial) bekommen
            # sofort den Status 'archiviert', damit sie nie als Bau-Kandidaten auftauchen.
            if row.get("lead_typ") == "Archiviert":
                row["status"] = "archiviert"

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
                f"Bilder: {'ja' if bilder else 'nein'} | "
                f"Paket {row.get('erwartungswert_euro')}€",
            )
            try:
                logger.activity("Evaluator", "Lead analysiert",
                                f"{lead.get('name')} · {row.get('lead_typ','?')} · "
                                f"Score {row.get('score',0)} · {row.get('erwartungswert_euro',0)}€",
                                "🔍", "eval")
                import cost_tracker as _ct
                _ct.track_compute(time.time() - _t0, False, "lead_eval", lead.get("name", ""))
            except Exception:
                pass
            on_update({"type": "evaluated", "data": row})

        except Exception as e:
            db_raw.update_eval_status(raw_id, "failed")
            logger.error("Evaluator", f"Fehler bei {lead.get('name')}: {e}")
            on_update({"_error": f"Evaluator-{worker_id} ({lead.get('name')}): {e}"})
