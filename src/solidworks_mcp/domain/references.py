"""Entity references: opaque, document-scoped handles with a human label.

Datum treats a reference as an opaque token. This module builds references for
the engineer's current selection and resolves them back to live entities at the
moment of use:

1. the token carries a SOLIDWORKS **persist reference** plus a geometric
   **fingerprint** (surface/curve, area/length, normal/endpoints, bounding box);
2. resolution checks the document scope, prefers the persist reference, and
   falls back to a fingerprint match;
3. zero matches and more-than-one match are explicit failures — a reference is
   never resolved to a guessed entity.

Measured on SW2026 SP0.0 / typelib 34.0 (scripts/probe_persist_reference.py):
persist references survived save/close/reopen, a topology-changing rebuild, and
a through-cut of the referenced face itself, with fingerprints unique on the
probe part. The fingerprint fallback is what makes a lost persist reference
recoverable rather than silently wrong.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from ..com import binding
from ..errors import (
    InvalidParameterError,
    ReferenceAmbiguousError,
    ReferenceDocumentMismatchError,
    ReferenceNotFoundError,
    SelectionError,
)
from . import inspect, session

TOKEN_VERSION = 1
MAX_SELECTION = 32
MAX_TOKEN_CHARS = 4096

# Matching tolerances for the fingerprint fallback. Values match the measured
# probe: listing details are rounded, so equality is not reliable.
AREA_TOL_MM2 = 1e-3
LENGTH_TOL_MM = 1e-3
COORD_TOL_MM = 0.05
NORMAL_TOL = 0.9999

# swSelectType_e -> Datum entity kind (see Datum's cad-contract entity schema).
SELECT_TYPE_KINDS = {
    1: "edge",
    2: "face",
    3: "vertex",
    4: "plane",
    5: "axis",
    9: "feature",
    20: "component",
    22: "feature",
}
TOPOLOGY_KINDS = ("face", "edge", "vertex")
TOPOLOGY_INTERFACES = {"face": "IFace2", "edge": "IEdge", "vertex": "IVertex"}
TOPOLOGY_DESCRIBERS = {
    "face": inspect.face_details,
    "edge": inspect.edge_details,
    "vertex": inspect.vertex_details,
}
SELECT_TYPE_LABELS = {
    4: "plane",
    5: "axis",
    9: "sketch",
    20: "component",
    22: "feature",
    39: "cosmetic thread",
}


def _as_bytes(reference: Any) -> bytes | None:
    """Normalise the VARIANT returned by GetPersistReference3 to bytes."""
    if reference is None:
        return None
    if isinstance(reference, (tuple, list)):
        reference = reference[0] if reference else None
    if reference is None:
        return None
    if isinstance(reference, bytes):
        return reference
    if isinstance(reference, str):
        return reference.encode("latin-1")
    try:
        return bytes(bytearray(reference))
    except Exception:
        return None


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_reference(reference: str) -> dict:
    """Decode an opaque token; malformed tokens fail closed."""
    if not isinstance(reference, str) or not reference:
        raise InvalidParameterError("entity reference must be a non-empty string")
    if len(reference) > MAX_TOKEN_CHARS:
        raise InvalidParameterError("entity reference is too long")
    try:
        payload = json.loads(base64.urlsafe_b64decode(reference.encode("ascii")))
    except Exception as error:
        raise InvalidParameterError(
            f"entity reference is not a valid token: {error}"
        ) from None
    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise InvalidParameterError("entity reference has an unknown token version")
    if payload.get("kind") not in (*TOPOLOGY_KINDS, "plane", "axis", "feature", "component", "other"):
        raise InvalidParameterError(f"entity reference has an unknown kind {payload.get('kind')!r}")
    return payload


def _persist_of(doc, entity) -> bytes | None:
    try:
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        return _as_bytes(extension.GetPersistReference3(entity))
    except Exception:
        return None


def _resolve_persist(doc, persist: bytes):
    try:
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
        resolved, out = session.com_result(
            extension.GetObjectByPersistReference3(persist, 0), 1
        )
        if out and out[0] not in (None, 0):
            return None
        return resolved
    except Exception:
        return None


def _document_scope(doc) -> dict:
    info = session.doc_info(doc)
    return {"title": info.get("title"), "path": info.get("path"), "type": info.get("type")}


def _check_scope(doc, payload: dict) -> None:
    scope = payload.get("doc") or {}
    current = _document_scope(doc)
    if scope.get("title") != current["title"] or scope.get("path") != current["path"]:
        raise ReferenceDocumentMismatchError(
            "the reference was captured in a different document",
            reference_document=scope,
            active_document=current,
        )


def _build_ref(doc, entity, kind: str, details: dict) -> str:
    scope = _document_scope(doc)
    persist = _persist_of(doc, entity)
    payload: dict[str, Any] = {
        "v": TOKEN_VERSION,
        "doc": scope,
        "kind": kind,
    }
    if persist:
        payload["persist"] = base64.b64encode(persist).decode("ascii")
    if details:
        payload["fp"] = details
    return _encode(payload)


def _label(kind: str, details: dict, select_type: int | None = None) -> str:
    if kind == "face":
        surface = details.get("surface", "unknown")
        area = details.get("area_mm2")
        return f"{surface} face, {area:g} mm2" if area is not None else f"{surface} face"
    if kind == "edge":
        curve = details.get("curve", "unknown")
        length = details.get("length_mm")
        return f"{curve} edge, {length:g} mm" if length is not None else f"{curve} edge"
    if kind == "vertex":
        point = details.get("point_mm")
        if point and len(point) >= 3:
            return f"Vertex at ({point[0]:g}, {point[1]:g}, {point[2]:g}) mm"
        return "Vertex"
    name = SELECT_TYPE_LABELS.get(select_type)
    return f"Selected {name}" if name else "Selected entity"


def _measurements(kind: str, details: dict) -> list[dict]:
    if kind == "face" and "area_mm2" in details:
        return [{"name": "area", "value": details["area_mm2"], "unit": "mm2"}]
    if kind == "edge" and "length_mm" in details:
        return [{"name": "length", "value": details["length_mm"], "unit": "mm"}]
    return []


def _entities_with_details(doc, kind: str) -> list[tuple[int, Any, dict]]:
    describe = TOPOLOGY_DESCRIBERS[kind]
    rows = []
    for index, entity in enumerate(inspect.topology_entities(doc, kind)):
        try:
            rows.append((index, entity, describe(entity)))
        except Exception:
            continue
    return rows


def _face_matches(candidate: dict, fp: dict) -> bool:
    if candidate.get("surface") != fp.get("surface"):
        return False
    area = fp.get("area_mm2")
    if area is not None and abs(float(candidate.get("area_mm2", -1.0)) - float(area)) > AREA_TOL_MM2:
        return False
    normal = fp.get("normal")
    if normal is not None:
        other = candidate.get("normal")
        if not other or sum(a * b for a, b in zip(normal, other)) < NORMAL_TOL:
            return False
    box = fp.get("box_mm")
    if box is not None and candidate.get("box_mm") is not None:
        for key in ("min", "max"):
            for expected, other in zip(box[key], candidate["box_mm"][key]):
                if abs(float(expected) - float(other)) > COORD_TOL_MM:
                    return False
    return True


def _edge_matches(candidate: dict, fp: dict) -> bool:
    if candidate.get("curve") != fp.get("curve"):
        return False
    length = fp.get("length_mm")
    if length is not None and abs(float(candidate.get("length_mm", -1.0)) - float(length)) > LENGTH_TOL_MM:
        return False
    for key in ("start_mm", "end_mm", "center_mm"):
        expected, other = fp.get(key), candidate.get(key)
        if expected is not None and other is not None:
            if sum(abs(float(a) - float(b)) for a, b in zip(expected, other)) > COORD_TOL_MM:
                return False
    return True


def _vertex_matches(candidate: dict, fp: dict) -> bool:
    point = fp.get("point_mm")
    other = candidate.get("point_mm")
    if point is None or other is None:
        return point is None and other is None
    return sum(abs(float(a) - float(b)) for a, b in zip(point, other)) <= COORD_TOL_MM


def _matches(kind: str, candidate: dict, fp: dict) -> bool:
    if kind == "face":
        return _face_matches(candidate, fp)
    if kind == "edge":
        return _edge_matches(candidate, fp)
    return _vertex_matches(candidate, fp)


def _index_by_persist(doc, kind: str, persist: bytes, rows) -> int | None:
    """Exact index of the entity whose persistent id matches, or None."""
    try:
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
    except Exception:
        return None
    for index, entity, _details in rows:
        candidate = _persist_of(doc, entity)
        if not candidate:
            continue
        try:
            if extension.IsSamePersistentID(persist, candidate):
                return index
        except Exception:
            continue
    return None


def _resolve(doc, payload: dict) -> dict:
    """Resolve a decoded token to (index, entity, details) in the active doc."""
    kind = payload["kind"]
    fp = payload.get("fp") or {}
    persist_b64 = payload.get("persist")
    persist = base64.b64decode(persist_b64) if persist_b64 else None

    if kind not in TOPOLOGY_KINDS:
        # Non-topology references resolve through the persist reference only.
        entity = _resolve_persist(doc, persist) if persist else None
        if entity is None:
            raise ReferenceNotFoundError(f"the referenced {kind} could not be resolved")
        return {"kind": kind, "index": None, "entity": entity, "details": {}}

    rows = _entities_with_details(doc, kind)
    matches = [row for row in rows if _matches(kind, row[2], fp)]
    if len(matches) == 1:
        index, entity, details = matches[0]
        return {"kind": kind, "index": index, "entity": entity, "details": details}
    if len(matches) > 1:
        if persist is not None:
            index = _index_by_persist(doc, kind, persist, matches)
            if index is not None:
                row = next(row for row in matches if row[0] == index)
                return {"kind": kind, "index": index, "entity": row[1], "details": row[2]}
        raise ReferenceAmbiguousError(
            f"{len(matches)} current {kind}s match the reference",
            kind=kind,
            matches=len(matches),
        )
    if persist is not None:
        index = _index_by_persist(doc, kind, persist, rows)
        if index is not None:
            row = next(row for row in rows if row[0] == index)
            return {"kind": kind, "index": index, "entity": row[1], "details": row[2]}
    raise ReferenceNotFoundError(
        f"no current {kind} matches the reference; the geometry may have changed",
        kind=kind,
    )


def capture_selection() -> dict:
    """The engineer's current selection as bounded, labeled references.

    Runs on the COM worker thread. Bounded to ``MAX_SELECTION`` entities; the
    caller sees ``truncated`` instead of an unbounded list.
    """
    _, doc, _ = session.active_doc(("part",))
    manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
    count = int(binding.value(manager.GetSelectedObjectCount2(-1)) or 0)
    entities = []
    for position in range(1, count + 1):
        entity = manager.GetSelectedObject6(position, -1)
        if entity is None:
            continue
        select_type = int(binding.value(manager.GetSelectedObjectType3(position, -1)) or -1)
        kind = SELECT_TYPE_KINDS.get(select_type, "other")
        details: dict = {}
        if kind in TOPOLOGY_KINDS:
            try:
                details = TOPOLOGY_DESCRIBERS[kind](binding.wrap(entity, TOPOLOGY_INTERFACES[kind]))
            except Exception:
                kind = "other"
        entry = {
            "ref": _build_ref(doc, entity, kind, details),
            "kind": kind,
            "label": _label(kind, details, select_type),
            "measurements": _measurements(kind, details),
        }
        entities.append(entry)
        if len(entities) >= MAX_SELECTION:
            break
    return {
        "document": session.doc_info(doc),
        "count": count,
        "truncated": count > len(entities),
        "entities": entities,
    }


def resolve_entity_reference(reference: str) -> dict:
    """Revalidate one reference against the active document.

    Raises ``REFERENCE_DOCUMENT_MISMATCH``/``REFERENCE_NOT_FOUND``/
    ``REFERENCE_AMBIGUOUS`` rather than returning a guessed entity.
    """
    _, doc, _ = session.active_doc(("part",))
    payload = decode_reference(reference)
    _check_scope(doc, payload)
    resolved = _resolve(doc, payload)
    kind = resolved["kind"]
    details = resolved["details"]
    return {
        "kind": kind,
        "index": resolved["index"],
        "label": _label(kind, details),
        "measurements": _measurements(kind, details),
        "details": details,
        "ref": _build_ref(doc, resolved["entity"], kind, details),
    }


def highlight_entities(refs: list[str], clear: bool = False) -> dict:
    """Transiently select referenced entities; a view action, not a mutation."""
    _, doc, _ = session.active_doc(("part",))
    if clear:
        session.clear_selection(doc)
        return {"highlighted": 0, "cleared": True}
    resolved = []
    for reference in refs:
        payload = decode_reference(reference)
        _check_scope(doc, payload)
        resolved.append(_resolve(doc, payload))
    session.clear_selection(doc)
    highlighted = 0
    for item in resolved:
        kind, index = item["kind"], item["index"]
        if kind not in TOPOLOGY_KINDS or index is None:
            raise SelectionError(f"cannot highlight a {kind!r} reference")
        append = highlighted > 0
        if kind == "face":
            inspect.select_faces(doc, [index], append=append)
        elif kind == "edge":
            inspect.select_edges(doc, [index], append=append)
        else:
            inspect.select_vertices(doc, [index], append=append)
        highlighted += 1
    return {"highlighted": highlighted}
