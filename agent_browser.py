"""
Browser-Tool für den Claude-Dashboard-Agenten — echtes Öffnen/Scrollen/Klicken.

Playwright muss in EINEM festen Thread laufen (sync-API ist nicht thread-übergreifend
nutzbar). Darum: ein dedizierter Worker-Thread besitzt Browser + Seite; Tool-Aufrufe
schicken Befehle über eine Queue und warten auf das Ergebnis. So kann der Agent aus
beliebigen Flask-Worker-Threads den Browser steuern.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from queue import Queue

_MEDIA = Path(__file__).parent / "workspace" / "media"


def _headless() -> bool:
    return os.environ.get("JARVIS_BROWSER_HEADLESS", "false").strip().lower() == "true"


class _BrowserWorker:
    def __init__(self) -> None:
        self._cmd_q: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._page = None

    # ── Lebenszyklus ─────────────────────────────────────────────────────────
    def _ensure(self) -> str:
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return ""
            ready: dict = {"err": None, "ev": threading.Event()}
            self._thread = threading.Thread(target=self._run, args=(ready,),
                                            name="AgentBrowser", daemon=True)
            self._thread.start()
            ready["ev"].wait(timeout=60)
            return ready["err"] or ""

    def _run(self, ready: dict) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            ready["err"] = "Playwright fehlt — `pip install playwright` + `playwright install chromium`."
            ready["ev"].set()
            return
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    headless=_headless(),
                    args=["--disable-blink-features=AutomationControlled",
                          "--no-sandbox", "--disable-dev-shm-usage"],
                )
                ctx = browser.new_context(
                    locale="de-DE", viewport={"width": 1366, "height": 900},
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
                )
                self._page = ctx.new_page()
                ready["ev"].set()
                while True:
                    cmd = self._cmd_q.get()
                    if cmd is None:
                        break
                    action, kwargs, box = cmd
                    try:
                        box["result"] = self._dispatch(action, kwargs)
                    except Exception as e:
                        box["result"] = f"Browser-Fehler: {type(e).__name__}: {str(e)[:160]}"
                    box["done"].set()
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception as e:
            ready["err"] = f"Browser-Start fehlgeschlagen: {type(e).__name__}: {str(e)[:160]}"
            ready["ev"].set()
        finally:
            self._page = None

    # ── Öffentliche API ──────────────────────────────────────────────────────
    def do(self, action: str, timeout: float = 60, **kwargs) -> str:
        err = self._ensure()
        if err:
            return err
        box = {"done": threading.Event(), "result": ""}
        self._cmd_q.put((action, kwargs, box))
        if not box["done"].wait(timeout=timeout):
            return "Browser-Zeitüberschreitung (Befehl dauerte zu lange)."
        return box["result"]

    # ── Befehle (laufen IM Worker-Thread) ────────────────────────────────────
    def _dispatch(self, action: str, kw: dict) -> str:
        p = self._page
        if p is None:
            return "Browser nicht bereit."

        if action == "open":
            url = (kw.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            p.goto(url, timeout=30000, wait_until="domcontentloaded")
            p.wait_for_timeout(1200)
            return f"Geöffnet: {p.title()} — {p.url}\n\n" + self._visible_text(p, 1500)

        if action == "click":
            self._locate(p, kw.get("target", "")).click(timeout=8000)
            p.wait_for_timeout(1000)
            return f"Geklickt. Jetzt: {p.title()} — {p.url}"

        if action == "type":
            loc = self._locate(p, kw.get("target", ""))
            loc.fill(kw.get("text", ""), timeout=8000)
            if kw.get("enter"):
                loc.press("Enter")
                p.wait_for_timeout(1200)
            return f"Text eingegeben. Jetzt: {p.title()} — {p.url}"

        if action == "scroll":
            d = (kw.get("direction") or "down").lower()
            amt = {"down": 900, "up": -900, "bottom": 5000, "top": -5000}.get(d, 900)
            p.mouse.wheel(0, amt)
            p.wait_for_timeout(700)
            return f"Gescrollt ({d}).\n\n" + self._visible_text(p, 1500)

        if action == "read":
            return f"{p.title()} — {p.url}\n\n" + self._visible_text(p, 4000)

        if action == "links":
            flt = (kw.get("filter") or "").lower()
            out = []
            for a in p.query_selector_all("a[href]")[:200]:
                href = a.get_attribute("href") or ""
                txt = (a.inner_text() or "").strip().replace("\n", " ")[:80]
                if href.startswith(("http", "/")) and txt:
                    if not flt or flt in txt.lower() or flt in href.lower():
                        out.append(f"- {txt} → {href}")
                if len(out) >= 40:
                    break
            return "\n".join(out) or "Keine passenden Links."

        if action == "back":
            p.go_back(timeout=15000)
            p.wait_for_timeout(800)
            return f"Zurück. Jetzt: {p.title()} — {p.url}"

        if action == "screenshot":
            _MEDIA.mkdir(parents=True, exist_ok=True)
            fn = f"agent_{int(time.time())}.png"
            p.screenshot(path=str(_MEDIA / fn), full_page=False)
            return f"Screenshot gespeichert: /workspace/media/{fn}"

        return f"Unbekannte Aktion: {action}"

    # ── Helfer ───────────────────────────────────────────────────────────────
    @staticmethod
    def _locate(p, target: str):
        """CSS-Selektor wenn er wie einer aussieht, sonst sichtbarer Text."""
        t = (target or "").strip()
        if t and (t[0] in ".#[" or t.startswith(("//", "css=", "text=")) or
                  any(t.lower().startswith(tag) for tag in
                      ("button", "input", "a ", "div", "span", "select", "textarea"))):
            return p.locator(t).first
        return p.get_by_text(t, exact=False).first

    @staticmethod
    def _visible_text(p, limit: int) -> str:
        try:
            txt = p.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            txt = ""
        txt = "\n".join(line.strip() for line in txt.splitlines() if line.strip())
        return txt[:limit]


_worker = _BrowserWorker()


def do(action: str, **kwargs) -> str:
    return _worker.do(action, **kwargs)


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False
