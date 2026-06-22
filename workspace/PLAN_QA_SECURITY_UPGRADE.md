# Plan 2 — QA / Security / Upgrade-Verfahren (läuft SEPARAT danach)

Ein eigenständiges Prüf- und Upgrade-Verfahren, das nach dem Build separat läuft und das
Programm bugfrei & sicher hält. Umgesetzt als `qa_security.py` (Standardbibliothek, keine
neuen Abhängigkeiten) — als Skript und als Route `/api/qa` nutzbar.

## Ausführen
```
python qa_security.py        # ASCII-Report in der Konsole
GET /api/qa                  # JSON (compile, security, dependencies, summary)
```

## 1. Bug-Check (`compile_all`)
Kompiliert alle Projekt-.py-Dateien rekursiv (`py_compile`, doraise), Ausnahmen:
.git, __pycache__, node_modules, vorlage_landing, shop_vorlage, reference_sites, web_*,
venv/.venv/env. → `{ok, fehler:[{file,error}]}`. Aktuell: **alle OK**.

## 2. Security-Scan (`security_scan`)
Wortgrenzen-Regex + Kontext-Prüfung, überspringt Kommentar-/Prosa-/Listen-Zeilen (so
schlagen die Security-Hinweise INNERHALB der Agenten-Prompts in `team.py` nicht als
Treffer durch). Regeln:
- **HIGH:** echtes `eval(`/`exec(`, `subprocess…(… shell=True)` (nur mit Aufruf-Kontext),
  `pickle.load`, `yaml.load(` ohne SafeLoader.
- **MEDIUM:** `os.system(` (außer leerer ANSI-Idiom `os.system("")`), `verify=False`,
  hardcoded Secrets / `sk-…` (env-Reads + Platzhalter ausgeschlossen).
- **LOW:** Flask `debug=True`.
Aktuell: **0 HIGH / 0 MEDIUM / 0 LOW**.

## 3. Dependency-/Upgrade-Check (`dependency_check`)
Liest `requirements.txt`, löst installierte Versionen via `importlib.metadata` auf,
markiert fehlende/abweichende (netzwerkfrei). Upgrade-Empfehlung manuell:
`pip install -U -r requirements.txt`.

## 4. Integration ins Tagesgeschäft (empfohlen)
- **Vor jedem Deploy / nach jedem Nightly-Lauf** `python qa_security.py` als Gate:
  bei HIGH-Findings oder Compile-Fehlern Deploy stoppen.
- **Cron/Task** (separat vom Build): täglich nach der Nightly-Phase, Report nach
  `workspace/results/qa_<datum>.txt`.
- **CI-Idee:** GitHub Action `python qa_security.py` + `pytest` + `smoke_audit.py` →
  Merge nur bei grün.

## 5. Upgrade-Verfahren (separater Lauf)
1. `qa_security.py` (Bug+Security) — grün?
2. `pip list --outdated` prüfen, gezielt aktualisieren, `pytest` erneut.
3. Modell-/Hardware-Tier neu erkennen (`hardware_profile`) — auf neuem Server passt sich
   alles automatisch an (mehr Parallelität/Bilder).
4. Regressions-Sicherheit: jeder Website-Tiefen-Schritt hat bereits Render-Gate + Rollback;
   QA-Lauf danach bestätigt die Gesamt-Integrität.

## 6. Erweiterungs-Ideen
- `bandit`/`pip-audit` optional ergänzen (echte CVE-DB), wenn Netzwerk erlaubt.
- Secret-Scanning auf `.env`-Leaks in Commits (pre-commit-Hook).
- Lighthouse/Playwright-Smoke gegen eine deployte Beispielseite (Performance/SEO).

## Status
`qa_security.py` läuft, Report grün. Als `/api/qa` im Dashboard abrufbar. Teil der
Test-Suite (Import + run_all + Scan-Sanity).
