"""Engineering drawings: sheets and model views."""
from __future__ import annotations

from pathlib import Path

from ..com import binding, units
from ..config import get_config
from ..errors import ComCallError, PathNotFoundError, SelectionError
from . import session

STANDARD_VIEWS = {
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


def _drawing(doc):
    return binding.wrap(doc, "IDrawingDoc")


def create_drawing(model: str | None = None, template: str | None = None) -> dict:
    config = get_config()
    application = session.app()
    if model is None:
        raw_active = application.ActiveDoc
        if raw_active is None:
            raise SelectionError(
                "no model is available",
                hint="Open a part or assembly, or pass model explicitly.",
            )
        active = session.wrap_doc(raw_active)
        model = str(binding.value(active.GetPathName) or binding.value(active.GetTitle))
    template_path = (
        Path(template).expanduser() if template else config.find_template("drawing")
    )
    if not template_path.exists():
        raise PathNotFoundError(f"drawing template not found: {template_path}")
    raw = application.NewDocument(str(template_path), 0, 0, 0)
    if raw is None:
        raw = application.ActiveDoc
    if raw is None:
        raise ComCallError("SOLIDWORKS did not create a drawing")
    doc = session.wrap_doc(raw)
    return {"document": session.doc_info(doc), "model": model}


def insert_model_view(
    view: str,
    x_mm: float = 100.0,
    y_mm: float = 150.0,
    model: str | None = None,
) -> dict:
    if view.lower() not in STANDARD_VIEWS:
        raise SelectionError(
            f"unknown standard view {view!r}", available=sorted(STANDARD_VIEWS)
        )
    _, doc, _ = session.active_doc(("drawing",))
    drawing = _drawing(doc)
    models = []
    if model:
        models.append(model)
    else:
        models.append("")
    view_name = STANDARD_VIEWS[view.lower()]
    created = None
    for candidate in models:
        raw = drawing.CreateDrawViewFromModelView3(
            candidate, view_name, units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0
        )
        if raw is not None:
            created = raw
            break
    if created is None:
        raise ComCallError(
            f"could not create {view!r} view",
            hint="Pass the model path or title explicitly.",
        )
    return {"view": view, "created": True}


def insert_standard_views(
    model: str | None = None,
    front_mm: list[float] | None = None,
    spacing_mm: float = 120.0,
) -> dict:
    front = front_mm or [120.0, 160.0]
    placements = [
        ("front", front[0], front[1]),
        ("top", front[0], front[1] - spacing_mm),
        ("right", front[0] + spacing_mm, front[1]),
    ]
    created = []
    for view, x, y in placements:
        insert_model_view(view, x, y, model)
        created.append(view)
    return {"views": created, "model": model}


def _view_name(view) -> str:
    for member in ("Name", "GetName2", "GetName"):
        try:
            value = getattr(view, member)
            return str(binding.value(value))
        except Exception:
            continue
    return "<unnamed>"


def _flatten_views(items) -> list:
    flat: list = []
    for item in items or []:
        if isinstance(item, (tuple, list)):
            flat.extend(_flatten_views(item))
        else:
            flat.append(item)
    return flat


def list_drawing_views() -> dict:
    _, doc, _ = session.active_doc(("drawing",))
    drawing = _drawing(doc)
    views = []
    for raw in _flatten_views(drawing.GetViews()):
        try:
            view = binding.wrap(raw, "IView")
        except Exception:
            continue
        info = {"name": _view_name(view)}
        try:
            outline = binding.value(view.GetOutline())
            if outline and len(outline) >= 4:
                info["outline_mm"] = {
                    "min": [round(units.m_to_mm(v), 2) for v in outline[0:2]],
                    "max": [round(units.m_to_mm(v), 2) for v in outline[2:4]],
                }
        except Exception:
            pass
        views.append(info)
    return {"views": views, "count": len(views)}
