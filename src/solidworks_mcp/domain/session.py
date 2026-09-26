"""Shared SOLIDWORKS session helpers used by every domain module."""
from __future__ import annotations

from typing import Iterator

import pythoncom
import win32com.client

from ..com import binding
from ..com.connect import attach, revision
from ..errors import (
    NoActiveDocumentError,
    SelectionError,
    WrongDocumentTypeError,
)

DOC_TYPES = {1: "part", 2: "assembly", 3: "drawing"}
KIND_TYPES = {kind: value for value, kind in DOC_TYPES.items()}
PLANE_PREFERENCE = ("Front Plane", "Top Plane", "Right Plane")
PLANE_ALIASES = {"front": "Front Plane", "top": "Top Plane", "right": "Right Plane"}
VIEW_NAMES = {
    "front": "*Front",
    "back": "*Back",
    "left": "*Left",
    "right": "*Right",
    "top": "*Top",
    "bottom": "*Bottom",
    "isometric": "*Isometric",
    "trimetric": "*Trimetric",
    "dimetric": "*Dimetric",
}


def app():
    return attach()


def wrap_doc(raw):
    return binding.wrap(raw, "IModelDoc2")


def active_doc(kind: str | tuple[str, ...] | None = None):
    application = app()
    raw = application.ActiveDoc
    if raw is None:
        raise NoActiveDocumentError("SOLIDWORKS has no active document")
    doc = wrap_doc(raw)
    doc_kind = DOC_TYPES.get(int(doc.GetType()), "unknown")
    if kind is not None:
        wanted = (kind,) if isinstance(kind, str) else tuple(kind)
        if doc_kind not in wanted:
            raise WrongDocumentTypeError(
                f"active document is a {doc_kind}, expected {' or '.join(wanted)}"
            )
    return application, doc, doc_kind


def doc_info(doc) -> dict:
    return {
        "title": str(binding.value(doc.GetTitle)),
        "path": str(binding.value(doc.GetPathName)),
        "type": DOC_TYPES.get(int(doc.GetType()), "unknown"),
        "dirty": bool(binding.value(doc.GetSaveFlag)),
    }


def iter_features(doc) -> Iterator:
    feature = doc.FirstFeature()
    while feature:
        wrapped = binding.wrap(feature, "IFeature")
        yield wrapped
        feature = wrapped.GetNextFeature()


def feature_info(feature) -> dict:
    name = str(binding.value(feature.Name))
    try:
        kind = str(feature.GetTypeName2())
    except Exception:
        kind = "Unknown"
    return {"name": name, "type": kind}


def list_feature_infos(doc) -> list[dict]:
    infos = []
    for feature in iter_features(doc):
        try:
            infos.append(feature_info(feature))
        except Exception:
            continue
    return infos


def _feature_names_of_type(doc, type_names: tuple[str, ...]) -> list[str]:
    names = []
    for feature in iter_features(doc):
        try:
            if feature.GetTypeName2() in type_names:
                names.append(str(binding.value(feature.Name)))
        except Exception:
            continue
    return names


def plane_names(doc) -> list[str]:
    return _feature_names_of_type(doc, ("RefPlane",))


def axis_names(doc) -> list[str]:
    return _feature_names_of_type(doc, ("RefAxis",))


def sketch_names(doc) -> list[str]:
    # Sketch features report ProfileFeature on this typelib; Sketch is kept as
    # a fallback for builds that name them literally.
    return _feature_names_of_type(doc, ("ProfileFeature", "Sketch"))


def resolve_name(name: str, names: list[str], kind: str) -> str:
    token = name.strip().lower()
    if name in names:
        return name
    for candidate in names:
        if candidate.lower() == token:
            return candidate
    raise SelectionError(f"{kind} {name!r} not found", available=names)


def clear_selection(doc) -> None:
    doc.ClearSelection2(True)


def resolve_plane_name(name: str | None, names: list[str]) -> str:
    if name is None:
        return next(
            (item for item in PLANE_PREFERENCE if item in names), names[0]
        )
    token = name.strip().lower()
    if name in names:
        return name
    for candidate in names:
        if candidate.lower() == token:
            return candidate
    if token in PLANE_ALIASES:
        alias = PLANE_ALIASES[token]
        if alias in names:
            return alias
        position = ("front", "top", "right").index(token)
        if len(names) > position:
            return names[position]
    raise SelectionError(f"plane {name!r} not found", available=names)


def select_plane(doc, name: str | None = None, mark: int = 0, append: bool = False) -> str:
    names = plane_names(doc)
    if not names:
        raise SelectionError("no reference planes found in the document")
    chosen = resolve_plane_name(name, names)
    if not append:
        clear_selection(doc)
    if not doc.Extension.SelectByID2(chosen, "PLANE", 0, 0, 0, append, mark, None, 0):
        raise SelectionError(f"could not select plane {chosen!r}")
    return chosen


def select_feature(doc, name: str, append: bool = False, mark: int = 0) -> None:
    if not doc.Extension.SelectByID2(
        name, "BODYFEATURE", 0, 0, 0, append, mark, None, 0
    ):
        raise SelectionError(f"could not select feature {name!r}")


def select_sketch(doc, name: str, append: bool = False, mark: int = 0) -> str:
    """Select a sketch feature by name (the type token is SKETCH)."""
    resolved = resolve_name(name, sketch_names(doc), "sketch")
    if not doc.Extension.SelectByID2(
        resolved, "SKETCH", 0, 0, 0, append, mark, None, 0
    ):
        raise SelectionError(f"could not select sketch {resolved!r}")
    return resolved


def com_result(result, out_count: int):
    """Split a makepy call result into (retval, [out params]).

    makepy-generated methods with [in,out] parameters must be called with
    plain values (never ``VARIANT`` objects) and return the out values
    appended to the return value.
    """
    values = list(result) if isinstance(result, tuple) else [result]
    values += [None] * (out_count + 1 - len(values))
    return values[0], values[1 : out_count + 1]


def set_view(doc, view: str) -> None:
    name = VIEW_NAMES.get(view.lower())
    if name is None:
        raise SelectionError(
            f"unknown view {view!r}", available=sorted(VIEW_NAMES)
        )
    doc.ShowNamedView2(name, -1)
    doc.ViewZoomtofit2()
