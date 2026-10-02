"""Bounded, document-scoped entity references for Datum selection.

Selection-only extraction from the sibling working tree, based on the measured
SW2026 SP0.0 persist-reference spike. Tokens are opaque to Datum.
All functions touching CAD run on the existing COM STA worker.
"""
from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..com import binding
from ..errors import (
    ComCallError,
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
    if (scope.get("title") != current["title"] or scope.get("path") != current["path"]
            or scope.get("type") != current["type"]):
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
            details = TOPOLOGY_DESCRIBERS[kind](entity)
        except Exception as error:
            raise ComCallError("cannot enumerate complete reference candidates") from error
        # The listing helpers suppress some COM getter errors. Do not mistake
        # a partial measurement for a confidently excluded identity candidate.
        if kind == "face":
            area = details.get("area_mm2")
            box = details.get("box_mm")
            if (not isinstance(area, (int, float)) or not math.isfinite(area)
                    or not isinstance(box, dict)
                    or not _finite_vector(box.get("min"))
                    or not _finite_vector(box.get("max"))
                    or (details.get("surface") == "plane"
                        and not _finite_vector(details.get("normal")))):
                raise ComCallError("a reference candidate has incomplete face geometry")
        elif kind == "edge":
            length = details.get("length_mm")
            if (not isinstance(length, (int, float)) or not math.isfinite(length)
                    or not _finite_vector(details.get("start_mm"))
                    or not _finite_vector(details.get("end_mm"))):
                raise ComCallError("a reference candidate has incomplete edge geometry")
        elif not _finite_vector(details.get("point_mm")):
            raise ComCallError("a reference candidate has incomplete vertex geometry")
        rows.append((index, entity, details))
    return rows


def _finite_vector(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(item, (int, float)) and math.isfinite(item) for item in value))


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
    except Exception as error:
        raise ComCallError("cannot verify persistent identity") from error
    matches = []
    for index, entity, _details in rows:
        candidate = _persist_of(doc, entity)
        if not candidate:
            raise ComCallError("cannot read a candidate's persistent identity")
        try:
            same = extension.IsSamePersistentID(persist, candidate)
            if same is None:
                raise ComCallError("persistent identity comparison returned no result")
            if same:
                matches.append(index)
        except Exception as error:
            raise ComCallError("persistent identity comparison failed") from error
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


def resolve_offset_face(doc, reference: str) -> dict:
    """Resolve the reviewed face and its captured geometry in the caller's CAD job.

    Persistent identity alone is insufficient: changed geometry needs re-selection.
    No caller-supplied topology index is accepted by this workflow.
    """
    payload = decode_reference(reference)
    _check_scope(doc, payload)
    fp = payload.get("fp") or {}
    if (payload["kind"] != "face" or fp.get("surface") != "plane"
            or not _finite_vector(fp.get("normal"))
            or not isinstance(fp.get("box_mm"), dict)
            or not _finite_vector(fp["box_mm"].get("min"))
            or not _finite_vector(fp["box_mm"].get("max"))
            or not isinstance(fp.get("area_mm2"), (int, float))
            or not math.isfinite(fp["area_mm2"])):
        raise InvalidParameterError("the offset-plane workflow needs a captured planar face")
    resolved = _resolve(doc, payload)
    if not _face_matches(resolved["details"], fp):
        raise ReferenceNotFoundError("the referenced face geometry changed; re-select and review it")
    return resolved


def resolve_entity_reference(reference: str, for_offset_plane: bool = False) -> dict:
    _, doc, _ = session.active_doc(("part",))
    payload = decode_reference(reference)
    _check_scope(doc, payload)
    resolved = resolve_offset_face(doc, reference) if for_offset_plane else _resolve(doc, payload)
    kind, details = resolved["kind"], resolved["details"]
    return {"kind": kind, "index": resolved["index"],
            "label": _label(kind, details), "measurements": _measurements(kind, details),
            "details": details, "ref": _build_ref(doc, resolved["entity"], kind, details)}


@dataclass
class _Highlight:
    doc: Any
    mark: int
    added: list[bytes] = field(default_factory=list)
    uncertain: bool = False


_highlights: dict[str, _Highlight] = {}
_closed_owners: set[str] = set()
_next_mark = 65536
MAX_HIGHLIGHT_OWNERS = 4096


def _selection_entries(doc) -> list[tuple[int, Any, int, bytes]]:
    manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
    count = int(binding.value(manager.GetSelectedObjectCount2(-1)) or 0)
    if count > 256:
        raise SelectionError("selection is too large to establish highlight ownership")
    entries = []
    for position in range(1, count + 1):
        entity = manager.GetSelectedObject6(position, -1)
        persist = _persist_of(doc, entity)
        if persist is None:
            raise SelectionError("cannot establish ownership of the current selection")
        entries.append((position, entity, int(manager.GetSelectedObjectMark(position)), persist))
    return entries


def _same_persist(doc, first: bytes, second: bytes) -> bool:
    extension = binding.wrap(doc.Extension, "IModelDocExtension")
    result = extension.IsSamePersistentID(first, second)
    if result is None:
        raise ComCallError("cannot verify highlight identity")
    return bool(result)


def _clear_highlight(owner: str) -> dict:
    # A clear arriving before an apply permanently fences that owner in this run.
    _closed_owners.add(owner)
    lease = _highlights.get(owner)
    if lease is not None:
        try:
            manager = binding.wrap(lease.doc.SelectionManager, "ISelectionMgr")
            for position, _entity, mark, persist in reversed(_selection_entries(lease.doc)):
                if mark == lease.mark and any(_same_persist(lease.doc, persist, item) for item in lease.added):
                    manager.DeSelect2(position, -1)
            if any(mark == lease.mark and any(_same_persist(lease.doc, persist, item) for item in lease.added)
                   for _position, _entity, mark, persist in _selection_entries(lease.doc)):
                raise SelectionError("owned selection could not be removed")
            if lease.uncertain and any(any(_same_persist(lease.doc, persist, item) for item in lease.added)
                                       for _position, _entity, _mark, persist in _selection_entries(lease.doc)):
                raise SelectionError("CAD selected an entity without a verifiable ownership mark")
        except Exception:
            return {"owner": owner, "status": "cleanup_unknown", "highlighted": 0}
        del _highlights[owner]
    return {"owner": owner, "status": "cleared", "highlighted": 0}


def highlight_entities(refs: list[str], clear: bool = False, owner: str | None = None) -> dict:
    """Append only absent references; clear only entries carrying our mark and identity.

    Existing engineer selections (including their marks) are never reassigned.
    Caller-owned tokens are single-use: delayed applies cannot revive a cleared review.
    Cleanup operates on the captured COM document, never whichever document is now active.
    """
    global _next_mark
    if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
        raise InvalidParameterError("highlight requires a bounded owner token")
    if owner not in _closed_owners and owner not in _highlights and len(_closed_owners) + len(_highlights) >= MAX_HIGHLIGHT_OWNERS:
        raise SelectionError("highlight ownership capacity exhausted; restart the backend")
    if clear:
        return _clear_highlight(owner)
    if owner in _closed_owners:
        return {"owner": owner, "status": "cleared", "highlighted": 0}
    if owner in _highlights:
        raise SelectionError("highlight owner is already in use")
    if not isinstance(refs, list) or not 1 <= len(refs) <= MAX_SELECTION:
        raise InvalidParameterError("highlight needs a bounded, non-empty reference list")
    _, doc, _ = session.active_doc(("part",))
    resolved = []
    for reference in refs:
        payload = decode_reference(reference)
        _check_scope(doc, payload)
        item = _resolve(doc, payload)
        if item["kind"] not in TOPOLOGY_KINDS or item["index"] is None:
            raise SelectionError("cannot highlight this reference kind")
        resolved.append(item)
    entries = _selection_entries(doc)
    marks = {entry[2] for entry in entries} | {lease.mark for lease in _highlights.values()}
    while _next_mark in marks:
        _next_mark += 1
    lease = _Highlight(doc, _next_mark)
    _next_mark += 1
    _highlights[owner] = lease
    try:
        manager = binding.wrap(doc.SelectionManager, "ISelectionMgr")
        for item in resolved:
            persist = _persist_of(doc, item["entity"])
            if persist is None:
                raise SelectionError("cannot track the highlighted entity")
            if any(_same_persist(doc, persist, entry[3]) for entry in _selection_entries(doc)):
                continue
            data = manager.CreateSelectData()
            data.Mark = lease.mark
            # Strict marked Select4: the unmarked Select fallback is not ownable.
            lease.added.append(persist)
            entity = binding.wrap(item["entity"], "IEntity")
            lease.uncertain = True
            if not entity.Select4(True, data):
                raise SelectionError("could not apply the owned highlight")
            if not any(mark == lease.mark and _same_persist(doc, selected, persist)
                       for _position, _entity, mark, selected in _selection_entries(doc)):
                raise SelectionError("CAD did not retain the highlight ownership mark")
            lease.uncertain = False
    except Exception:
        cleanup = _clear_highlight(owner)
        if cleanup["status"] != "cleared":
            return cleanup
        raise
    return {"owner": owner, "status": "applied", "highlighted": len(resolved), "owned": len(lease.added)}
