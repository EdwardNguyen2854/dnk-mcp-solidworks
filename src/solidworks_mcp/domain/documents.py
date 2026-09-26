"""Document lifecycle: create, open, save, close, rebuild."""
from __future__ import annotations

import time
from pathlib import Path

from ..com import binding, units  # noqa: F401  (units re-exported for tools)
from ..com.connect import revision
from ..config import get_config
from ..errors import (
    ComCallError,
    InvalidParameterError,
    PathNotFoundError,
    SelectionError,
    VerificationError,
)
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
        # NewDocument can return None while still creating the document; only
        # then is the active document trustworthy.
        raw = application.ActiveDoc
    if raw is None:
        raise ComCallError("SOLIDWORKS did not create a document")
    doc = session.wrap_doc(raw)
    doc_kind = session.DOC_TYPES.get(int(binding.value(doc.GetType)), "unknown")
    if doc_kind != kind:
        raise ComCallError(
            "SOLIDWORKS did not activate a newly created document",
            requested=kind,
            active=doc_kind,
            hint="The session may be busy or low on resources; retry, or "
            "restart SOLIDWORKS with a clean session.",
        )
    return {
        "document": session.doc_info(doc),
        "template": str(template_path),
    }


OPEN_TYPE_BY_SUFFIX = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}


def open_document(path: str) -> dict:
    source = Path(path).expanduser()
    if not source.exists():
        raise PathNotFoundError(f"file not found: {source}")
    application = session.app()
    # Auto-detect (type 0) fails with swInvalidFileTypeError on this build;
    # derive the document type from the extension instead.
    doc_type = OPEN_TYPE_BY_SUFFIX.get(source.suffix.lower(), 0)
    result = application.OpenDoc6(str(source), doc_type, 1, "", 0, 0)
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


CLOSE_POLL_SECONDS = 2.0
CLOSE_POLL_INTERVAL = 0.1


def _open_document_titles() -> list[str]:
    return [item["title"] for item in list_open_documents()]


def close_document(save: bool = False) -> dict:
    application, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    title = str(binding.value(doc.GetTitle))
    path = ""
    try:
        path = str(binding.value(doc.GetPathName) or "")
    except Exception:
        pass
    # Measured on SW2026 SP0.0: CloseDoc cannot close one of two documents
    # that share a title (the full path does not disambiguate either), so
    # report the collision instead of a misleading refusal.
    if _open_document_titles().count(title) > 1:
        raise ComCallError(
            f"more than one open document is titled {title!r}",
            hint="SOLIDWORKS cannot close one copy by name; close the extra "
            "copy in the SOLIDWORKS window first.",
        )
    discarded = False
    save_result = None
    if save:
        save_result = save_document()
    else:
        discarded = bool(binding.value(doc.GetSaveFlag))
        # SetSaveFlag does not change GetSaveFlag on this build, but CloseDoc
        # still discards the changes when the flag was set.
        doc.SetSaveFlag()
    # The full path is unambiguous for saved documents; fall back to the
    # title for never-saved ones.
    application.CloseDoc(path or title)
    deadline = time.monotonic() + CLOSE_POLL_SECONDS
    while time.monotonic() < deadline:
        if title not in _open_document_titles():
            break
        time.sleep(CLOSE_POLL_INTERVAL)
    if title in _open_document_titles():
        raise ComCallError(f"SOLIDWORKS refused to close {title!r}")
    return {
        "closed": title,
        "saved": bool(save_result and save_result.get("ok")),
        "unsaved_changes_discarded": discarded,
    }


def rebuild_document(top_only: bool = False) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    return inspect.rebuild(doc, top_only)


def _property_manager_names(manager) -> list[str]:
    try:
        raw = binding.value(manager.GetNames)
    except Exception:
        raw = None
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw if str(item)]


def set_file_property(name: str, value: str) -> dict:
    """Set one text custom property on the active document and verify it.

    Works on parts, assemblies and drawings. This is how title-block links
    that resolve against the model (`$PRPSHEET:"Description"`,
    `"Material"`, `"Finish"`) are filled: set them on the part, not the
    drawing.
    """
    if not str(name).strip():
        raise InvalidParameterError("property name must not be empty")
    _, doc, kind = session.active_doc(("part", "assembly", "drawing"))
    raw = doc.Extension.CustomPropertyManager("")
    if raw is None:
        raise ComCallError("SOLIDWORKS did not provide a custom-property manager")
    manager = binding.wrap(raw, "ICustomPropertyManager")
    names = _property_manager_names(manager)
    existing = next(
        (candidate for candidate in names if candidate.lower() == str(name).lower()),
        None,
    )
    stored_name = existing or str(name)
    if existing is not None:
        manager.Set2(existing, str(value))
        operation = "set"
    else:
        # swCustomInfoText=30; swCustomPropertyReplaceValue=2 on typelib 34.0.
        manager.Add3(stored_name, 30, str(value), 2)
        operation = "add"
    try:
        measured = str(binding.value(manager.Get(stored_name)) or "")
    except Exception:
        measured = ""
    if measured != str(value):
        raise VerificationError(
            "SOLIDWORKS did not retain the custom property",
            name=stored_name,
            expected=str(value),
            measured=measured,
        )
    return {
        "document": session.doc_info(doc),
        "kind": kind,
        "name": stored_name,
        "value": measured,
        "operation": operation,
    }


# MaterialPropertyValues is (R, G, B, ambient, diffuse, specular, shininess,
# transparency, emission); only RGB is user-facing here.
APPEARANCE_SHADING = (0.30, 1.0, 0.50, 0.40, 0.0, 0.0)
RGB_TOLERANCE = 1.0 / 255.0 + 1e-6


def _read_material_values(obj) -> list[float]:
    try:
        return [float(value) for value in binding.value(obj.MaterialPropertyValues) or []]
    except Exception:
        return []


def set_appearance(
    red: int,
    green: int,
    blue: int,
    face_indices: list[int] | None = None,
) -> dict:
    """Colour the model or individual faces.

    SOLIDWORKS stores the channels at 8-bit precision, so the read-back can
    differ from the request by up to 1/255 even on success.
    """
    _, doc, _ = session.active_doc(("part", "assembly"))
    channels = {"red": red, "green": green, "blue": blue}
    for name, value in channels.items():
        if not 0 <= value <= 255:
            raise InvalidParameterError(f"{name} must be between 0 and 255")
    expected = [red / 255.0, green / 255.0, blue / 255.0]
    values = [*expected, *APPEARANCE_SHADING]
    data: dict = {"rgb": [red, green, blue]}
    if face_indices:
        if session.DOC_TYPES.get(int(doc.GetType())) != "part":
            raise InvalidParameterError("face_indices requires an active part document")
        faces = []
        for body in inspect._bodies(doc):
            faces.extend(inspect._faces(body))
        applied = []
        for index in face_indices:
            if not isinstance(index, int) or index < 0 or index >= len(faces):
                raise SelectionError(
                    f"face index {index} out of range (0..{len(faces) - 1})"
                )
            face = faces[index]
            face.MaterialPropertyValues = binding.r8_array(values)
            applied.append(
                {
                    "face_index": index,
                    "rgb": [round(value, 6) for value in _read_material_values(face)[:3]],
                }
            )
        data["scope"] = "faces"
        data["faces"] = applied
        readback = [item["rgb"] for item in applied]
    else:
        doc.MaterialPropertyValues = binding.r8_array(values)
        readback = [[round(value, 6) for value in _read_material_values(doc)[:3]]]
        data["scope"] = "model"
        data["applied_rgb"] = readback[0]
    for rgb in readback:
        if len(rgb) < 3 or any(
            abs(actual - wanted) > RGB_TOLERANCE
            for actual, wanted in zip(rgb, expected)
        ):
            raise VerificationError(
                "SOLIDWORKS did not retain the requested appearance",
                expected=expected,
                readback=readback,
            )
    return {"data": data, "evidence": {"appearance_rgb": readback}}
