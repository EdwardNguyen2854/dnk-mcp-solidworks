"""File-level checkpoints: snapshot before mutations, restore on demand."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from ..com import binding
from ..config import get_config
from ..domain import documents, session
from ..errors import ComCallError, PathNotFoundError

CHECKPOINT_SUFFIX_BY_KIND = {
    "part": ".sldprt",
    "assembly": ".sldasm",
    "drawing": ".slddrw",
}

_last_checkpoint_at = 0.0
_last_checkpoint_path: Path | None = None


def checkpoints_dir() -> Path:
    directory = get_config().checkpoint_root / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _saved_path(doc) -> Path:
    """The active document's path; ``Path("")`` is ``.``, so callers must use
    ``is_file()`` rather than ``exists()`` when testing whether it is saved.

    GetPathName returns an empty string for a document that was never saved
    (the previous ``exists()`` check treated it as a real file and tried to
    copy the ``.`` directory).
    """
    return Path(str(binding.value(doc.GetPathName) or ""))


def _open_type_for(path: Path) -> int:
    """OpenDoc6 document type; auto-detect (0) fails on this build."""
    return documents.OPEN_TYPE_BY_SUFFIX.get(path.suffix.lower(), 0)


def create_checkpoint(label: str | None = None) -> dict:
    global _last_checkpoint_at, _last_checkpoint_path
    _, doc, kind = session.active_doc(("part", "assembly", "drawing"))
    source = _saved_path(doc)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    label_suffix = f"-{label}" if label else ""
    if source.is_file():
        target = checkpoints_dir() / f"{source.stem}{label_suffix}-{stamp}{source.suffix}"
        shutil.copy2(source, target)
        mode = "copy"
    else:
        extension = CHECKPOINT_SUFFIX_BY_KIND.get(kind, ".sldprt")
        target = checkpoints_dir() / f"unsaved{label_suffix}-{stamp}{extension}"
        result = doc.Extension.SaveAs3(str(target), 0, 3, None, None, 0, 0)
        ok, (errors, _warnings) = session.com_result(result, 2)
        if not ok or not target.is_file():
            raise ComCallError(
                "could not write a checkpoint for the unsaved document",
                error_code=int(errors or 0),
            )
        mode = "save-a-copy"
    _last_checkpoint_at = time.time()
    _last_checkpoint_path = target
    return {
        "checkpoint": str(target),
        "source": str(source) if source.is_file() else None,
        "mode": mode,
    }


def maybe_auto_checkpoint() -> dict | None:
    config = get_config()
    if not config.auto_checkpoint:
        return None
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    source = _saved_path(doc)
    if not source.is_file():
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
    # Auto-detect (type 0) fails for checkpoint copies on this build
    # (swInvalidFileTypeError / error_code 1024); derive the type from the
    # extension, exactly as open_document does.
    result = application.OpenDoc6(
        str(target), _open_type_for(target), 1, "", 0, 0
    )
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
