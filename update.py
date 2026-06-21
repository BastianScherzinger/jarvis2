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

    # ── Webseiten-Deploy-Bereitschaft (GitHub + Railway + git) ────
    print()
    print(f"  {CY}[>]{R}  Pruefe Webseiten-Deploy (GitHub + Railway)...")
    try:
        import config            # laedt .env in os.environ
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
