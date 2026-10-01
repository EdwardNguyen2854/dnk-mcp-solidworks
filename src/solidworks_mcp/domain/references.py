"""Bounded, document-scoped entity references for Datum selection.

Selection-only extraction from the sibling working tree, based on the measured
SW2026 SP0.0 persist-reference spike. Tokens are opaque to Datum.
All functions touching CAD run on the existing COM STA worker.
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
AREA_TOL_MM2 = 1e-3
LENGTH_TOL_MM = 1e-3
COORD_TOL_MM = 0.05
NORMAL_TOL = 0.9999
SELECT_TYPE_KINDS = {
    1: "edge", 2: "face", 3: "vertex", 4: "plane", 5: "axis",
    9: "feature", 20: "component", 22: "feature",
}
TOPOLOGY_KINDS = ("face", "edge", "vertex")
TOPOLOGY_INTERFACES = {"face": "IFace2", "edge": "IEdge", "vertex": "IVertex"}
TOPOLOGY_DESCRIBERS = {
    "face": inspect.face_details,
    "edge": inspect.edge_details,
    "vertex": inspect.vertex_details,
}
SELECT_TYPE_LABELS = {
    4: "plane", 5: "axis", 9: "sketch", 20: "component",
    22: "feature", 39: "cosmetic thread",
}


def _as_bytes(reference: Any) -> bytes | None:
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
    if not isinstance(reference, str) or not reference:
        raise InvalidParameterError("entity reference must be a non-empty string")
    if len(reference) > MAX_TOKEN_CHARS:
        raise InvalidParameterError("entity reference is too long")
    try:
        payload = json.loads(base64.urlsafe_b64decode(reference.encode("ascii")))
    except Exception:
        raise InvalidParameterError("entity reference is not a valid token") from None
    if not isinstance(payload, dict) or payload.get("v") != TOKEN_VERSION:
        raise InvalidParameterError("entity reference has an unknown token version")
    if payload.get("kind") not in (*TOPOLOGY_KINDS, "plane", "axis", "feature", "component", "other"):
        raise InvalidParameterError("entity reference has an unknown kind")
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
        resolved, out = session.com_result(extension.GetObjectByPersistReference3(persist, 0), 1)
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
        raise ReferenceDocumentMismatchError("the reference was captured in a different document")


def _build_ref(doc, entity, kind: str, details: dict) -> str:
    payload: dict[str, Any] = {"v": TOKEN_VERSION, "doc": _document_scope(doc), "kind": kind}
    persist = _persist_of(doc, entity)
    if persist:
        payload["persist"] = base64.b64encode(persist).decode("ascii")
    if details:
        payload["fp"] = details
    return _encode(payload)


def _label(kind: str, details: dict, select_type: int | None = None) -> str:
    if kind == "face":
        surface, area = details.get("surface", "unknown"), details.get("area_mm2")
        return f"{surface} face, {area:g} mm2" if area is not None else f"{surface} face"
    if kind == "edge":
        curve, length = details.get("curve", "unknown"), details.get("length_mm")
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
    rows = []
    for index, entity in enumerate(inspect.topology_entities(doc, kind)):
        try:
            rows.append((index, entity, TOPOLOGY_DESCRIBERS[kind](entity)))
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
    point, other = fp.get("point_mm"), candidate.get("point_mm")
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
    try:
        extension = binding.wrap(doc.Extension, "IModelDocExtension")
    except Exception:
        return None
    matches = []
    for index, entity, _details in rows:
        candidate = _persist_of(doc, entity)
        if not candidate:
            continue
        try:
            if extension.IsSamePersistentID(persist, candidate):
                matches.append(index)
        except Exception:
            continue
    if len(matches) > 1:
        raise ReferenceAmbiguousError("multiple current entities share the persistent identity")
    return matches[0] if matches else None


def _resolve(doc, payload: dict) -> dict:
    kind, fp = payload["kind"], payload.get("fp") or {}
    persist = base64.b64decode(payload["persist"]) if payload.get("persist") else None
    if kind not in TOPOLOGY_KINDS:
        entity = _resolve_persist(doc, persist) if persist else None
        if entity is None:
            raise ReferenceNotFoundError("the referenced entity could not be resolved")
        return {"kind": kind, "index": None, "entity": entity, "details": {}}
    rows = _entities_with_details(doc, kind)
    # Identity outranks geometric resemblance: another face can acquire the
    # old fingerprint after the captured face changes during a rebuild.
    if persist is not None:
        index = _index_by_persist(doc, kind, persist, rows)
        if index is not None:
            row = next(row for row in rows if row[0] == index)
            return {"kind": kind, "index": index, "entity": row[1], "details": row[2]}
    matches = [row for row in rows if _matches(kind, row[2], fp)]
    if len(matches) == 1:
        index, entity, details = matches[0]
        return {"kind": kind, "index": index, "entity": entity, "details": details}
    if len(matches) > 1:
        raise ReferenceAmbiguousError("multiple current entities match the reference")
    raise ReferenceNotFoundError("no current entity matches the reference")


def capture_selection() -> dict:
    _, doc, _ = session.active_doc(("part",))
    manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
    count = int(binding.value(manager.GetSelectedObjectCount2(-1)) or 0)
    entities = []
    for position in range(1, count + 1):
        entity = manager.GetSelectedObject6(position, -1)
        if entity is None:
            continue
        select_type = int(binding.value(manager.GetSelectedObjectType3(position, -1)) or -1)
        kind, details = SELECT_TYPE_KINDS.get(select_type, "other"), {}
        if kind in TOPOLOGY_KINDS:
            try:
                details = TOPOLOGY_DESCRIBERS[kind](binding.wrap(entity, TOPOLOGY_INTERFACES[kind]))
            except Exception:
                kind = "other"
        entities.append({
            "ref": _build_ref(doc, entity, kind, details), "kind": kind,
            "label": _label(kind, details, select_type),
            "measurements": _measurements(kind, details),
        })
        if len(entities) >= MAX_SELECTION:
            break
    return {"document": session.doc_info(doc), "count": count,
            "truncated": count > len(entities), "entities": entities}


def resolve_entity_reference(reference: str) -> dict:
    _, doc, _ = session.active_doc(("part",))
    payload = decode_reference(reference)
    _check_scope(doc, payload)
    resolved = _resolve(doc, payload)
    kind, details = resolved["kind"], resolved["details"]
    return {"kind": kind, "index": resolved["index"],
            "label": _label(kind, details), "measurements": _measurements(kind, details),
            "details": details, "ref": _build_ref(doc, resolved["entity"], kind, details)}


def highlight_entities(refs: list[str], clear: bool = False) -> dict:
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
            raise SelectionError("cannot highlight this reference kind")
        if kind == "face":
            inspect.select_faces(doc, [index], append=highlighted > 0)
        elif kind == "edge":
            inspect.select_edges(doc, [index], append=highlighted > 0)
        else:
            inspect.select_vertices(doc, [index], append=highlighted > 0)
        highlighted += 1
    return {"highlighted": highlighted}
