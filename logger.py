"""
JARVIS Logger — farbige Console-Ausgabe + RAM-Ringpuffer für Frontend-Konsole.
"""
import threading, time, collections
from datetime import datetime

# ANSI
_R  = "\033[0m"
_B  = "\033[1m"
_GR = "\033[92m"   # grün   = SUCCESS
_RD = "\033[91m"   # rot    = ERROR
_YL = "\033[93m"   # gelb   = WARN
_CY = "\033[96m"   # cyan   = INFO
_GY = "\033[90m"   # grau   = DEBUG
_MG = "\033[95m"   # magenta = EVAL

# Ringpuffer: letzte 500 Log-Zeilen
_buffer: collections.deque = collections.deque(maxlen=500)
_lock   = threading.Lock()

# Level-Mapping
_LEVELS = {
    "INFO":    (_CY,  "INFO   "),
    "SUCCESS": (_GR,  "OK     "),
    "WARN":    (_YL,  "WARN   "),
    "ERROR":   (_RD,  "ERROR  "),
    "DEBUG":   (_GY,  "DEBUG  "),
    "EVAL":    (_MG,  "EVAL   "),
    "SCRAPE":  ("\033[38;5;214m", "SCRAPE "),  # orange
}

def _log(level: str, worker: str, msg: str) -> None:
    col, tag = _LEVELS.get(level, (_GY, level.ljust(7)))
    ts  = datetime.now().strftime("%H:%M:%S")
    # Console
    print(f"  {_GY}[{ts}]{_R} {col}{_B}{tag}{_R} {_GY}[{worker}]{_R}  {msg}")
    # Buffer
    entry = {"ts": ts, "level": level, "worker": worker, "msg": msg}
    with _lock:
        _buffer.append(entry)

def info   (worker: str, msg: str) -> None: _log("INFO",    worker, msg)
def success(worker: str, msg: str) -> None: _log("SUCCESS", worker, msg)
def warn   (worker: str, msg: str) -> None: _log("WARN",    worker, msg)
def error  (worker: str, msg: str) -> None: _log("ERROR",   worker, msg)
def debug  (worker: str, msg: str) -> None: _log("DEBUG",   worker, msg)
def eval_  (worker: str, msg: str) -> None: _log("EVAL",    worker, msg)
def scrape (worker: str, msg: str) -> None: _log("SCRAPE",  worker, msg)

def get_recent(limit: int = 100) -> list[dict]:
    with _lock:
        entries = list(_buffer)
    return entries[-limit:]

def get_since(ts_after: str, limit: int = 200) -> list[dict]:
    """Gibt alle Log-Einträge nach einem bestimmten Timestamp zurück."""
    with _lock:
        entries = list(_buffer)
    if ts_after:
        entries = [e for e in entries if e["ts"] > ts_after]
    return entries[-limit:]
