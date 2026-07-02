"""
JARVIS Updater
==============
Zieht die neueste Version von GitHub und installiert neue Pakete.
Aufruf (fuer Kunden):  python update.py
"""
import subprocess
import sys
import os
from pathlib import Path

# Konsole auf UTF-8 zwingen -- ohne das crasht install.py's Unicode-Rahmen (z.B. '─')
# mit UnicodeEncodeError unter der Windows-Alt-Kodierung cp1252 (Kunden-Konsole ohne
# UTF-8-Terminal), und update.py bricht ab, BEVOR der Ordner-Umzug/Deploy-Check je
# laeuft. Gleiches Muster wie start.py (dort schon vorhanden).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"]       = "1"
os.system("")
R  = "\033[0m"; B = "\033[1m"
GR = "\033[92m"; RD = "\033[91m"; YL = "\033[93m"; CY = "\033[96m"; GY = "\033[90m"

HERE = Path(__file__).parent


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE), **kw)


def main() -> None:
    print()
    print(f"  {CY}================================================={R}")
    print(f"  {CY}  {B}JARVIS  Update{R}")
    print(f"  {CY}================================================={R}")
    print()

    # ── Git vorhanden? ────────────────────────────────────────────
    git_check = _run(["git", "--version"])
    if git_check.returncode != 0:
        print(f"  {RD}[X]{R}  Git nicht installiert.")
        print(f"  {GY}     -> https://git-scm.com/download/win{R}")
        sys.exit(1)

    # ── Lokale Aenderungen pruefen ────────────────────────────────
    status = _run(["git", "status", "--porcelain"])
    if status.stdout.strip():
        print(f"  {YL}[!]{R}  Lokale Aenderungen gefunden:")
        for line in status.stdout.strip().splitlines()[:5]:
            print(f"  {GY}     {line}{R}")
        print(f"  {YL}     Diese werden NICHT ueberschrieben.{R}")
        print()

    # ── git fetch (Aenderungen holen ohne anwenden) ───────────────
    print(f"  {CY}[>]{R}  Pruefe GitHub auf Updates...", end="", flush=True)
    fetch = _run(["git", "fetch", "origin"])
    if fetch.returncode != 0:
        print(f"\r  {RD}[X]{R}  Verbindung zu GitHub fehlgeschlagen.")
        print(f"  {GY}     {fetch.stderr.strip()[:100]}{R}")
        sys.exit(1)

    # ── Vergleichen: lokal vs. remote ─────────────────────────────
    behind = _run(["git", "rev-list", "HEAD..origin/main", "--count"])
    count  = behind.stdout.strip()

    if count == "0":
        print(f"\r  {GR}[OK]{R}  Bereits aktuell (keine neuen Updates).")
    else:
        print(f"\r  {CY}[>]{R}  {count} neue Commit(s) verfuegbar -- ziehe Updates...")

        pull = _run(["git", "pull", "origin", "main", "--ff-only"])
        if pull.returncode == 0:
            print(f"  {GR}[OK]{R}  Update erfolgreich.")
            # Zeige was neu ist
            log = _run(["git", "log", f"HEAD~{count}..HEAD", "--oneline"])
            if log.stdout.strip():
                print(f"  {GY}  Neu:{R}")
                for line in log.stdout.strip().splitlines():
                    print(f"  {GY}    - {line}{R}")
            # KRITISCH: dieser Prozess hat den ALTEN update.py-Code noch im Speicher --
            # Python kompiliert das Skript einmal beim Start, git pull aendert nur die
            # Datei auf der Platte. Ohne Neustart wuerden neue Schritte HIER IM SKRIPT
            # (z.B. die Ordner-Aufraeumung unten) beim ALLERERSTEN Lauf nach einem Update
            # schlicht nie ausgefuehrt werden -- Henne-Ei-Problem, bestaetigt am
            # migrate_legacy_website_folders()-Schritt (02.07.2026). Fix: frischen
            # Interpreter-Prozess mit dem NEUEN Code starten; der laeuft dann komplett
            # durch (inkl. "bereits aktuell"-Zweig danach, kein Endlos-Neustart).
            print(f"  {CY}[>]{R}  Starte Update-Skript neu (frischer Code)...")
            print()
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            print(f"  {RD}[X]{R}  Merge-Konflikt oder Fehler:")
            print(f"  {GY}     {pull.stderr.strip()[:100]}{R}")
            print(f"  {YL}     Tipp: python update.py --force (verwirft lokale Aenderungen){R}")
            if "--force" in sys.argv:
                _run(["git", "reset", "--hard", "origin/main"])
                print(f"  {GR}[OK]{R}  Erzwungenes Update durchgefuehrt.")

    # ── Neue Pakete installieren ──────────────────────────────────
    print()
    print(f"  {CY}[>]{R}  Pruefe Abhaengigkeiten...")
    import install
    install.run()

    # ── Alte Webseiten-Ordner vom Desktop aufraeumen ───────────────
    # Fasst verstreute Alt-Ordner (Desktop/web_*, vor der Tagesordner-Struktur) nach
    # Desktop/jarvis_websites/<Datum>/ zusammen -- vor allem relevant beim ersten Update
    # auf einem zweiten PC. Neue Seiten landen ohnehin schon immer nur dort.
    print()
    print(f"  {CY}[>]{R}  Pruefe auf verstreute Webseiten-Ordner auf dem Desktop...")
    try:
        import config            # laedt .env in os.environ
        import website_builder
        res = website_builder.migrate_legacy_website_folders()
        moved  = res.get("moved") or []
        errors = res.get("errors") or []
        if moved:
            print(f"  {GR}[OK]{R}  {len(moved)} Alt-Ordner nach jarvis_websites/ umgezogen:")
            for m in moved[:10]:
                print(f"  {GY}     {Path(m['from']).name} -> jarvis_websites/{Path(m['to']).parent.name}/{R}")
            if len(moved) > 10:
                print(f"  {GY}     ... und {len(moved) - 10} weitere{R}")
        else:
            print(f"  {GR}[OK]{R}  Keine verstreuten Alt-Ordner gefunden (schon aufgeraeumt).")
        if errors:
            print(f"  {YL}[!]{R}  {len(errors)} Ordner konnten nicht umgezogen werden (siehe Log).")
    except Exception as e:
        print(f"  {YL}[!]{R}  Ordner-Aufraeumen uebersprungen: {str(e)[:80]}")

    # ── Webseiten-Deploy-Bereitschaft (GitHub + Railway + git) ────
    print()
    print(f"  {CY}[>]{R}  Pruefe Webseiten-Deploy (GitHub + Railway)...")
    try:
        import config            # laedt .env in os.environ (idempotent, evtl. schon geladen)
        import website_builder
        for line in website_builder.deploy_status_text().splitlines():
            if line.startswith("[OK]") or line.startswith("Deploy bereit"):
                col = GR
            elif line.startswith("[!]") or line.startswith("Deploy NICHT"):
                col = YL
            else:
                col = GY
            print(f"     {col}{line}{R}")
    except Exception as e:
        print(f"     {YL}Deploy-Check uebersprungen: {str(e)[:80]}{R}")

    print()
    print(f"  {GR}{B}Update abgeschlossen -- starte JARVIS mit: python start.py{R}")
    print()


if __name__ == "__main__":
    main()
