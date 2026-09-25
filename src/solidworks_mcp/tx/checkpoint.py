"""File-level checkpoints: snapshot before mutations, restore on demand."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..com import binding
from ..config import get_config
from ..domain import session
from ..errors import ComCallError, PathNotFoundError

_last_checkpoint_at = 0.0
_last_checkpoint_path: Path | None = None


def checkpoints_dir() -> Path:
    directory = get_config().checkpoint_root / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def create_checkpoint(label: str | None = None) -> dict:
    global _last_checkpoint_at, _last_checkpoint_path
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    source = Path(str(binding.value(doc.GetPathName)))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    if source.exists():
        target = checkpoints_dir() / f"{source.stem}{suffix}-{stamp}{source.suffix}"
        shutil.copy2(source, target)
        mode = "copy"
    else:
        target = checkpoints_dir() / f"unsaved{suffix}-{stamp}.sldprt"
        result = doc.Extension.SaveAs3(str(target), 0, 3, None, None, 0, 0)
        ok, (errors, _warnings) = session.com_result(result, 2)
        if not ok or not target.exists():
            raise ComCallError(
                "could not write a checkpoint for the unsaved document",
                error_code=int(errors or 0),
            )
        mode = "save-a-copy"
    _last_checkpoint_at = time.time()
    _last_checkpoint_path = target
    return {
        "checkpoint": str(target),
        "source": str(source) if source.exists() else None,
        "mode": mode,
    }


def maybe_auto_checkpoint() -> dict | None:
    config = get_config()
    if not config.auto_checkpoint:
        return None
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    source = Path(str(binding.value(doc.GetPathName)))
    if not source.exists():
        return None
    age = time.time() - _last_checkpoint_at
    if _last_checkpoint_path is not None and age < config.checkpoint_debounce_sec:
        return None
    try:
        return create_checkpoint(label="auto")
    except Exception:
        return None


def list_checkpoints() -> list[dict]:
    entries = []
    for path in sorted(checkpoints_dir().glob("*"), reverse=True):
        entries.append(
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime)
                ),
            }
        )
    return entries


def rollback(checkpoint_path: str | None = None) -> dict:
    directory = checkpoints_dir()
    if checkpoint_path:
        target = Path(checkpoint_path)
    else:
        candidates = sorted(directory.glob("*"), reverse=True)
        if not candidates:
            raise PathNotFoundError("no checkpoints exist yet")
        target = candidates[0]
    if not target.is_absolute():
        target = directory / target
    if not target.exists():
        raise PathNotFoundError(f"checkpoint not found: {target}")
    application, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    title = str(binding.value(doc.GetTitle))
    doc.SetSaveFlag()
    application.CloseDoc(title)
    result = application.OpenDoc6(str(target), 0, 1, "", 0, 0)
    raw, (errors, _warnings) = session.com_result(result, 2)
    if raw is None:
        raise ComCallError(
            f"could not reopen checkpoint {target}",
            error_code=int(errors or 0),
        )
    reopened = session.wrap_doc(raw)
    return {
        "restored_from": str(target),
        "opened_document": session.doc_info(reopened),
        "note": "the checkpoint copy is now the active document; save it "
        "over the original if you want to keep the rollback",
    }
