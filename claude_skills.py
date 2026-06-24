"""
claude_skills.py — installiert die mitgelieferten Claude-Code-Skills.

Die Makeover-Stufen (overnight_makeover) lassen den HEADLESS Claude Code
(`claude_coder.run_prompt`) IM Webseiten-Ordner laufen. Claude Code findet dort nur
**user-globale** Skills (`~/.claude/skills/`) — Skills im jarvis2-Projektordner sind für
einen Lauf in `…/jarvis_websites/<datum>/web_<slug>` NICHT sichtbar.

Damit die echten Skills (taste = `design-taste-frontend`, `ui-ux-pro-max`) auf JEDEM PC
„immer da" sind, liegen sie versioniert im Repo unter `skills/<name>/SKILL.md` und werden
beim Start nach `~/.claude/skills/<name>/` gespiegelt (nur wenn fehlend oder verändert).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import logger

_SRC = Path(__file__).parent / "skills"
_DST = Path.home() / ".claude" / "skills"


def _mirror_dir(src_dir: Path, dst_dir: Path) -> None:
    """Spiegelt einen Skill-Ordner (SKILL.md + evtl. references/scripts) nach dst."""
    for item in src_dir.rglob("*"):
        rel = item.relative_to(src_dir)
        target = dst_dir / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def ensure_installed() -> list:
    """Kopiert jeden Repo-Skill (skills/<name>/SKILL.md) nach ~/.claude/skills/<name>/,
    sofern dort die SKILL.md fehlt oder sich unterscheidet. Best-effort, idempotent.
    Gibt die Liste der installierten/aktualisierten Skill-Namen zurück."""
    installed: list = []
    if not _SRC.is_dir():
        return installed
    for skill_dir in _SRC.iterdir():
        if not skill_dir.is_dir():
            continue
        src_skill = skill_dir / "SKILL.md"
        if not src_skill.is_file():
            continue
        name      = skill_dir.name
        dst_dir   = _DST / name
        dst_skill = dst_dir / "SKILL.md"
        try:
            changed = (not dst_skill.is_file()
                       or dst_skill.read_bytes() != src_skill.read_bytes())
            if changed:
                dst_dir.mkdir(parents=True, exist_ok=True)
                _mirror_dir(skill_dir, dst_dir)
                installed.append(name)
        except Exception as e:
            logger.warn("Skills", f"{name}: Installation fehlgeschlagen: {type(e).__name__}")
    if installed:
        logger.info("Skills", f"Claude-Skills nach ~/.claude/skills installiert: {', '.join(installed)}")
    return installed


if __name__ == "__main__":
    print("Installiert:", ensure_installed() or "nichts (alles aktuell)")
