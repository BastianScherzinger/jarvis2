"""
Flask-Routen für das leadpackages-Modul — additiv über register(app) angehängt,
damit app.py nur einen Import + einen Aufruf braucht (kein Eingriff in bestehende
Routen). Entscheidung: manueller Verkauf (kein Payment-Provider) — der Bestell-Flow
markiert Bestellungen intern und erzeugt den Download, Bezahlung läuft außerhalb.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Response, jsonify, request, send_from_directory

from scrapers.regions import BRANCHEN

from leadpackages import (
    db_packages as dbp,
    export_csv_excel,
    ollama_summary,
    package_builder,
    scheduler,
    sources_dach,
    watermark,
)

PHASE = 7
EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "leadpackages_exports"


def register(app):
    @app.route("/api/leadpackages/ping")
    def leadpackages_ping():
        return jsonify({"status": "ok", "module": "leadpackages", "phase": PHASE})

    @app.route("/api/leadpackages/branchen")
    def leadpackages_branchen():
        return jsonify({"branchen": BRANCHEN})

    @app.route("/api/leadpackages/regionen")
    def leadpackages_regionen():
        land = (request.args.get("land") or "DE").upper()
        return jsonify({"land": land, "staedte": sources_dach.staedte_fuer(land)})

    @app.route("/api/leadpackages/stats")
    def leadpackages_stats():
        return jsonify(dbp.stock_stats())

    @app.route("/api/leadpackages/preview")
    def leadpackages_preview():
        branche = request.args.get("branche", "")
        region = request.args.get("region") or None
        land = (request.args.get("land") or "DE").upper()
        pakete = package_builder.verfuegbare_pakete(branche, region=region, land=land)
        sample = package_builder.build(branche, 5, region=region, land=land)["rows"]
        beschreibung = ollama_summary.generate(branche, region or land, sample)
        vorschau = [{"name": r.get("name"), "stadt": r.get("stadt"),
                     "quality_score": r.get("quality_score")} for r in sample]
        return jsonify({"pakete": pakete, "beschreibung": beschreibung, "vorschau": vorschau})

    @app.route("/api/leadpackages/order", methods=["POST"])
    def leadpackages_order():
        data = request.get_json(force=True, silent=True) or {}
        branche = (data.get("branche") or "").strip()
        region = (data.get("region") or "").strip() or None
        land = (data.get("land") or "DE").upper()
        bundle_size = int(data.get("bundle_size") or 0)
        format_ = (data.get("format") or "csv").lower()
        kaeufer = (data.get("kaeufer") or "").strip() or "Unbekannt"

        if not branche or bundle_size <= 0:
            return jsonify({"error": "branche und bundle_size sind Pflichtfelder"}), 400

        scheduler.ensure_stock(branche, land, region=region, min_needed=bundle_size)
        paket = package_builder.build(branche, bundle_size, region=region, land=land)
        if not paket["rows"]:
            return jsonify({"error": "Kein Vorrat für diese Kombination verfügbar"}), 404

        wm_id = watermark.new_watermark_id()
        rows_wm = watermark.embed(paket["rows"], wm_id)

        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        ext = "xlsx" if format_ == "xlsx" else "csv"
        dateiname = f"{wm_id}.{ext}"
        pfad = EXPORT_DIR / dateiname
        if ext == "xlsx":
            pfad.write_bytes(export_csv_excel.to_excel_bytes(rows_wm))
        else:
            pfad.write_text(export_csv_excel.to_csv(rows_wm), encoding="utf-8-sig")

        order_id = dbp.create_order({
            "kaeufer": kaeufer, "branche": branche, "region": region or "", "land": land,
            "bundle_size": bundle_size, "format": ext, "watermark_id": wm_id,
            "preis_euro": paket["preis_euro"],
        })
        return jsonify({
            "order_id": order_id, "watermark_id": wm_id, "geliefert": paket["geliefert"],
            "preis_euro": paket["preis_euro"],
            "download_url": f"/api/leadpackages/order/{order_id}/download",
        })

    @app.route("/api/leadpackages/orders")
    def leadpackages_orders():
        return jsonify({"orders": dbp.get_orders()})

    @app.route("/api/leadpackages/order/<int:order_id>/download")
    def leadpackages_download(order_id: int):
        order = dbp.get_order(order_id)
        if not order:
            return jsonify({"error": "Bestellung nicht gefunden"}), 404
        dateiname = f"{order['watermark_id']}.{order['format']}"
        dbp.mark_order_delivered(order_id)
        return send_from_directory(EXPORT_DIR, dateiname, as_attachment=True)
