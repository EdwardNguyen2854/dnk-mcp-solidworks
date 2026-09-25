"""Document lifecycle: create, open, save, close, rebuild."""
from __future__ import annotations

from pathlib import Path

from ..com import binding, units  # noqa: F401  (units re-exported for tools)
from ..com.connect import revision
from ..config import get_config
from ..errors import ComCallError, PathNotFoundError
from . import inspect, session


def status() -> dict:
    application = session.app()
    result: dict = {
        "revision": revision(application),
        "open_documents": list_open_documents(),
    }
    raw = application.ActiveDoc
    if raw is not None:
        doc = session.wrap_doc(raw)
        result["active_document"] = session.doc_info(doc)
    return result


def list_open_documents() -> list[dict]:
    application = session.app()
    documents = []
    for raw in application.GetDocuments() or []:
        try:
            documents.append(session.doc_info(session.wrap_doc(raw)))
        except Exception:
            continue
    return documents


def new_document(kind: str, template: str | None = None) -> dict:
    config = get_config()
    application = session.app()
    template_path = (
        Path(template).expanduser() if template else config.find_template(kind)
    )
    if not template_path.exists():
        raise PathNotFoundError(f"template not found: {template_path}")
    raw = application.NewDocument(str(template_path), 0, 0, 0)
    if raw is None:
        raw = application.ActiveDoc
    if raw is None:
        raise ComCallError("SOLIDWORKS did not create a document")
    doc = session.wrap_doc(raw)
    return {
        "document": session.doc_info(doc),
        "template": str(template_path),
    }


def open_document(path: str) -> dict:
    source = Path(path).expanduser()
    if not source.exists():
        raise PathNotFoundError(f"file not found: {source}")
    application = session.app()
    result = application.OpenDoc6(str(source), 0, 1, "", 0, 0)
    raw, (errors, warnings) = session.com_result(result, 2)
    if raw is None:
        raise ComCallError(
            f"SOLIDWORKS could not open {source}",
            error_code=int(errors or 0),
            warning_code=int(warnings or 0),
        )
    doc = session.wrap_doc(raw)
    return {
        "document": session.doc_info(doc),
        "error_code": int(errors or 0),
        "warning_code": int(warnings or 0),
    }


def _save_result(result) -> dict:
    ok_value, (errors, warnings) = session.com_result(result, 2)
    return {
        "ok": bool(ok_value),
        "error_code": int(errors or 0),
        "warning_code": int(warnings or 0),
    }


def save_document(path: str | None = None, overwrite: bool = True) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    config = get_config()
    if path:
        target = config.resolve_output_path(path)
        if target.exists() and not overwrite:
            raise ComCallError(
                f"{target} already exists and overwrite is false",
                hint="Pass overwrite=true to replace it.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        result = _save_result(
            doc.Extension.SaveAs3(str(target), 0, 1, None, None, 0, 0)
        )
        if result["ok"] and not target.exists():
            result["ok"] = False
            result.setdefault("hint", "SOLIDWORKS reported success but no file was written")
        result["path"] = str(target)
    else:
        existing = str(binding.value(doc.GetPathName))
        if not existing:
            raise ComCallError(
                "the document has no path yet",
                hint="Call save_document with an explicit path first.",
            )
        result = _save_result(doc.Save3(1, 0, 0))
        result["path"] = existing
    result["document"] = session.doc_info(doc)
    return result


def close_document(save: bool = False) -> dict:
    application, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    title = str(binding.value(doc.GetTitle))
    discarded = False
    save_result = None
    if save:
        save_result = save_document()
    else:
        discarded = bool(binding.value(doc.GetSaveFlag))
        doc.SetSaveFlag()
    application.CloseDoc(title)
    still_open = [item["title"] for item in list_open_documents()]
    if title in still_open:
        raise ComCallError(f"SOLIDWORKS refused to close {title!r}")
    return {
        "closed": title,
        "saved": bool(save_result and save_result.get("ok")),
        "unsaved_changes_discarded": discarded,
    }


def rebuild_document(top_only: bool = False) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    return inspect.rebuild(doc, top_only)
