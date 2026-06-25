"""
site_meta.py — zentrale Versions-/Level-Angabe der gebauten Webseiten.

SITE_VERSION ist das „Update-Level", auf dem eine Seite gebaut/makeovert wurde. Es wird in
content.json gestempelt (beim Bauen und bei jeder Makeover-Stufe) und im Dashboard je Seite als
Badge „Update X.Y" angezeigt — so ist sofort sichtbar, welche Seiten auf dem aktuellen Stand sind.

Bei einem größeren Bau-/Makeover-Update hier erhöhen (und ggf. overnight_makeover._MAKEOVER_VERSION,
damit heutige Seiten automatisch neu gemakeovert werden).
"""
from __future__ import annotations

import os

SITE_VERSION = (os.environ.get("JARVIS_SITE_VERSION") or "0.9").strip()
