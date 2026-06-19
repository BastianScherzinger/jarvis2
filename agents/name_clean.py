"""
Firmennamen-Säuberung für die von Scrapern gefundenen Roh-Namen.

Scraper liefern oft hässliche Namen mit SEO-Codes, Marketing-Spam und
Wort-Wiederholungen, z.B.:
    "C.W Service Hamburg Tag & Nacht Rolladen Reparatur Service Rolladenreparatur"
    "F0507 Robin Look GmbH"

Dieses Modul bietet zwei Funktionen:
  * quick_clean(name)        — rein deterministisch, kein Netz, keine KI.
  * ai_clean(name, branche, stadt) — best-effort Feinschliff via lokalem Ollama,
                              fällt bei jedem Fehler auf quick_clean zurück.

Die Integration (Scraper/Pipeline/DB) macht jemand anderes — hier nur die
reinen Funktionen.
"""
import re

# ── Konstanten ────────────────────────────────────────────────────────────────

# Maximale Länge nach dem Kürzen (an Wortgrenze).
_MAX_LEN = 55

# Trenner, nach denen ein evtl. Marketing-Anhängsel abgeschnitten wird.
_SEPARATORS = (" - ", " | ", " · ", " — ", " / ")

# Führende SEO-/Artikelnummer-Codes am Stringanfang, z.B. "F0507 ", "A1234 ",
# "B-123 ", "B12 ". Buchstabe(n) gefolgt von Ziffern, getrennt durch Whitespace
# oder Bindestrich.
_LEAD_CODE = re.compile(r"^[A-Za-z]{1,2}[\-]?\d{2,}[\s\-]+")

# Reine Satzzeichen-/Symbol-Wörter (z.B. "&", "+") werden bei der Dedup nie
# als Wiederholung verworfen.
_PUNCT_ONLY = re.compile(r"^[^\w]+$", re.UNICODE)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _normalize_ws(s: str) -> str:
    """Trimmt und faltet mehrfache Leerzeichen zu einem zusammen."""
    return re.sub(r"\s+", " ", s).strip()


def _strip_lead_code(s: str) -> str:
    """Entfernt einen führenden SEO-/Artikelnummer-Code."""
    return _LEAD_CODE.sub("", s, count=1).strip()


def _word_stem(word: str) -> str:
    """Grober Wort-Stamm für die Wiederholungs-Erkennung (case-insensitive).

    "Rolladenreparatur" und "Rolladen" sollen als verwandt gelten, damit der
    Spam ("... Rolladen ... Rolladenreparatur") als Wiederholung erkannt wird.
    Heuristik: nur Buchstaben/Ziffern, kleinschreiben; lange Wörter auf den
    Präfix kürzen.
    """
    w = re.sub(r"[^\w]", "", word, flags=re.UNICODE).lower()
    # Lange Komposita auf einen Präfix reduzieren, damit "rolladenreparatur"
    # denselben Stamm wie "rolladen" bekommt.
    if len(w) > 6:
        return w[:6]
    return w


def _dedup_tokens(s: str) -> str:
    """Entfernt wiederholte Wort-Stämme (case-insensitive).

    Arbeitet auf Leerzeichen-getrennten Wörtern (erhält so "C.W" als ein Wort),
    behält die erste Vorkommnis jedes Stamms und verwirft spätere
    Wiederholungen. Reine Satzzeichen-Wörter (&, +, …) bleiben immer erhalten.
    """
    seen: set[str] = set()
    out: list[str] = []
    for word in s.split():
        if _PUNCT_ONLY.match(word):
            out.append(word)
            continue
        stem = _word_stem(word)
        if not stem:                  # nur Satzzeichen mit Buchstaben-Rest 0
            out.append(word)
            continue
        if stem in seen:
            continue                  # Wiederholung → überspringen
        seen.add(stem)
        out.append(word)
    return " ".join(out)


def _cut_marketing(s: str) -> str:
    """Schneidet ein Marketing-Anhängsel nach einem Trenner ab,
    wenn der erste Teil ein plausibler Name ist (Länge > 3)."""
    for sep in _SEPARATORS:
        idx = s.find(sep)
        if idx != -1:
            head = s[:idx].strip()
            if len(head) > 3:
                return head
    return s


def _truncate_wordsafe(s: str, max_len: int = _MAX_LEN) -> str:
    """Kürzt auf max_len an einer Wortgrenze (nie mitten im Wort)."""
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.strip()


def _fix_case(s: str) -> str:
    """Komplett groß oder komplett klein → Title-Case; gemischt unverändert."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return s
    if all(c.isupper() for c in letters) or all(c.islower() for c in letters):
        return s.title()
    return s


# ── Öffentliche API ───────────────────────────────────────────────────────────

def quick_clean(name: str) -> str:
    """Säubert einen Roh-Firmennamen rein deterministisch (kein Netz, keine KI).

    Regeln (in dieser Reihenfolge):
      1. Whitespace trimmen / mehrfache Leerzeichen falten.
      2. Führende SEO-/Artikelnummer-Codes entfernen ("F0507 " → "").
      3. Aufeinanderfolgende Wort-Wiederholungen entfernen (case-insensitive).
      4. Marketing-Anhängsel nach Trenner abschneiden (wenn Kopf plausibel).
      5. Auf ~55 Zeichen an einer Wortgrenze kürzen.
      6. Komplett groß/klein → Title-Case; gemischt unverändert.
      7. Nie leer — Fallback auf den getrimmten Originalnamen.

    Idempotent und deterministisch: quick_clean(quick_clean(x)) == quick_clean(x).
    """
    if not name:
        return ""
    original_trimmed = _normalize_ws(name)

    s = original_trimmed
    s = _strip_lead_code(s)
    s = _dedup_tokens(s)
    s = _cut_marketing(s)
    s = _truncate_wordsafe(s)
    s = _fix_case(s)
    s = _normalize_ws(s)

    # Nie leer zurückgeben.
    if not s:
        return original_trimmed
    return s


def ai_clean(name: str, branche: str = "", stadt: str = "") -> str:
    """Best-effort Feinschliff via lokalem Ollama-Modell.

    Versucht, den offiziellen Firmennamen ohne Marketing/Wiederholungen zu
    bekommen. Bei JEDEM Fehler (Ollama weg, leer, ungültig, Exception) →
    Fallback auf quick_clean(name). Wirft niemals.
    """
    try:
        from scrapers import _http  # lazy: kein I/O-Import auf Modulebene

        roh = _normalize_ws(name)
        system = (
            "Du gibst NUR den sauberen offiziellen Firmennamen zurück, "
            "ohne Marketing, ohne Wiederholungen, als JSON "
            '{"name": "..."}'
        )
        prompt = (
            f"Roher Firmenname: {roh}\n"
            f"Branche: {branche}\n"
            f"Stadt: {stadt}\n"
            "Gib den sauberen offiziellen Firmennamen zurück."
        )
        antwort = _http.ask_ollama(prompt, system)
        daten = _http.extract_json(antwort)
        clean = daten.get("name", "")

        if not isinstance(clean, str):
            return quick_clean(name)
        clean = clean.strip()
        # Validieren: Länge 2..60, kein Zeilenumbruch.
        if not (2 <= len(clean) <= 60) or "\n" in clean or "\r" in clean:
            return quick_clean(name)
        return clean
    except Exception:
        return quick_clean(name)
