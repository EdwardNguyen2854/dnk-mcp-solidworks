"""Install the repository's workflow skills into an agent's skills directory.

The skills under ``skills/<name>/SKILL.md`` are the orchestration layer that
turns the typed tools into a repeatable procedure (for example the ISO
engineering-drawing workflow). They are markdown, versioned with the server,
and installed into whichever directory the target agent scans for skills.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .errors import PathNotFoundError


def _skills_root() -> Path | None:
    """Locate the skills source: env override, repo checkout, package data."""
    candidates: list[Path] = []
    override = os.environ.get("SW_MCP_SKILLS_DIR")
    if override:
        candidates.append(Path(override).expanduser())
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / "skills")
    candidates.append(Path(__file__).resolve().parent / "skills")
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*/SKILL.md")):
            return candidate
    return None


def install_skills(destination: str | Path) -> list[Path]:
    """Copy every skill folder into ``destination``.

    Returns the installed ``SKILL.md`` paths. Existing files with the same
    name are overwritten so an updated server refreshes the procedure.
    """
    source = _skills_root()
    if source is None:
        raise PathNotFoundError(
            "no skills folder found next to the package",
            hint="Run from the repository checkout, or set SW_MCP_SKILLS_DIR "
            "to the folder that contains <skill>/SKILL.md directories.",
        )
    target_root = Path(destination).expanduser()
    target_root.mkdir(parents=True, exist_ok=True)
    installed: list[Path] = []
    for skill_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        manifest = skill_dir / "SKILL.md"
        if not manifest.is_file():
            continue
        target = target_root / skill_dir.name
        shutil.copytree(skill_dir, target, dirs_exist_ok=True)
        installed.append(target / "SKILL.md")
    if not installed:
        raise PathNotFoundError(f"no skills found under {source}")
    return installed
