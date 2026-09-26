#!/usr/bin/env python
"""Live probe: Tier-1 drawing edit actuators on SW2026 SP0.0.

Questions this script answers before the tools are written:

1. Can a drawing view be selected by name (``SelectByID2`` type
   ``DRAWINGVIEW``) and removed with ``DeleteSelection2``?
2. Can a note be moved (``IAnnotation.SetPosition``), re-texted
   (``INote.SetText``) and deleted (``IAnnotation.Select3`` +
   ``DeleteSelection2``)?
3. Can ``IModelDoc2.AddDimension2`` create a drawing dimension between two
   picked view edges (distance) and on a single circle (diameter), and does
   the value read back through ``list_dimensions``?
4. Does ``list_annotations`` see a sheet-placed note, and what do
   ``IDisplayDimension.SetText`` / ``GetText`` do?
5. What exceptions do the calls raise when something is unavailable?

Creates a scratch part + drawing and discards both (never saves over
anything). Run with SOLIDWORKS open; save your work first.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding, units  # noqa: E402
from solidworks_mcp.domain import (  # noqa: E402
    documents,
    drawings,
    features,
    session,
    sketch,
)

RESULTS: list[dict] = []
NOTE_TEXT = "PROBE NOTE"


def probe(name, fn):
    try:
        RESULTS.append({"probe": name, "ok": True, "result": fn()})
    except Exception as exc:  # noqa: BLE001 - every failure is a probe result
        RESULTS.append(
            {
                "probe": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4),
            }
        )
    return RESULTS[-1]


def view_outlines(doc) -> dict:
    result = {}
    for view in drawings._views(doc):
        try:
            result[drawings._view_name(view)] = [
                round(units.m_to_mm(value), 3)
                for value in binding.value(view.GetOutline()) or []
            ]
        except Exception:
            continue
    return result


def find_note(doc, text: str):
    for view in drawings._views(doc):
        for annotation in drawings._view_annotations(view):
            try:
                if int(annotation.GetType()) != 6:
                    continue
                note = binding.wrap(annotation.GetSpecificAnnotation(), "INote")
                if str(binding.value(note.GetText) or "") == text:
                    return view, annotation, note
            except Exception:
                continue
    return None, None, None


def summarize_annotations() -> list:
    listed = drawings.list_annotations()
    summary = []
    for view in listed.get("views", []):
        counts: dict[str, int] = {}
        for annotation in view.get("annotations", []):
            kind = annotation.get("type", "?")
            counts[kind] = counts.get(kind, 0) + 1
        summary.append({"view": view.get("name"), "counts": counts})
    return summary


def main() -> int:
    application = session.app()
    created: list[str] = []

    documents.new_document("part")
    part_doc = session.active_doc(("part",))[1]
    created.append(str(binding.value(part_doc.GetTitle)))
    sketch.create_sketch("Front Plane")
    sketch.rectangle(0.0, 0.0, 120.0, 80.0)
    sketch.circle(30.0, 40.0, 5.0)
    sketch.circle(90.0, 40.0, 5.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=20.0)

    drawings.create_drawing(paper_size="A3", scale=1.0, first_angle=True)
    drawing_doc = session.active_doc(("drawing",))[1]
    created.insert(0, str(binding.value(drawing_doc.GetTitle)))
    drawings.insert_standard_views()

    views = drawings.list_drawing_views().get("views", [])
    front = next((v for v in views if v.get("orientation") == "front"), None)
    if front is None:
        raise SystemExit(f"no front view in {views}")
    front_name = front["name"]
    print(f"front view: {front_name}; views: {[v['name'] for v in views]}")

    # --- notes: create, list, move, edit text -----------------------------
    # Capture the raw note/annotation handles: the point of the probe is to
    # test the API calls, not the (separately reported) view iteration.
    handles: dict = {}

    def create_note():
        raw_note = drawing_doc.InsertNote(NOTE_TEXT)
        if raw_note is None:
            raise RuntimeError("InsertNote returned None")
        handles["note"] = binding.wrap(raw_note, "INote")
        handles["annotation"] = binding.wrap(
            handles["note"].GetAnnotation(), "IAnnotation"
        )
        handles["annotation"].SetPosition(
            units.mm_to_m(60.0), units.mm_to_m(60.0), 0.0
        )
        found = find_note(drawing_doc, NOTE_TEXT)[1] is not None
        handles["visible_in_view_iteration"] = found
        return {"visible_in_view_iteration": found}

    probe("note_create", create_note)
    probe("note_list_after_create", summarize_annotations)

    def move_note():
        annotation = handles["annotation"]
        before = list(binding.value(annotation.GetPosition()) or [])
        annotation.SetPosition(units.mm_to_m(92.0), units.mm_to_m(72.0), 0.0)
        after = list(binding.value(annotation.GetPosition()) or [])
        return {
            "before_mm": [round(units.m_to_mm(v), 3) for v in before[:2]],
            "after_mm": [round(units.m_to_mm(v), 3) for v in after[:2]],
        }

    probe("note_move", move_note)

    def edit_note():
        note = handles["note"]
        note.SetText("PROBE EDITED")
        return {
            "read_back": str(binding.value(note.GetText) or ""),
            "visible_in_view_iteration": find_note(drawing_doc, "PROBE EDITED")[1]
            is not None,
        }

    probe("note_set_text", edit_note)

    # --- dimensions: two circles (distance) and one circle (diameter) -----
    view = drawings._model_view(drawing_doc, front_name)
    entities = drawings._view_visible_edges(view)
    edge_info = [drawings._view_edge_info(entity) for entity in entities]
    circle_edges = [
        index for index, info in enumerate(edge_info) if info.get("kind") == "circle"
    ]
    print(f"front view edges: {len(entities)}; circles: {circle_edges}")

    def add_distance_dimension():
        if len(circle_edges) < 2:
            raise RuntimeError(f"expected two circles, got {circle_edges}")
        drawings.activate_view(front_name)
        session.clear_selection(drawing_doc)
        ok_first = bool(view.SelectEntity(entities[circle_edges[0]], False))
        ok_second = bool(view.SelectEntity(entities[circle_edges[1]], True))
        restore = sketch._suppress_dimension_dialog()
        try:
            display = drawing_doc.AddDimension2(
                units.mm_to_m(60.0), units.mm_to_m(12.0), 0.0
            )
        finally:
            sketch._restore_dimension_dialog(restore)
        dimensions = drawings.list_dimensions(front_name)
        return {
            "selected": [ok_first, ok_second],
            "display_created": display is not None,
            "dimensions": dimensions.get("views", []),
        }

    probe("dimension_between_two_circles", add_distance_dimension)

    def add_diameter_dimension():
        drawings.activate_view(front_name)
        session.clear_selection(drawing_doc)
        ok = bool(view.SelectEntity(entities[circle_edges[0]], False))
        restore = sketch._suppress_dimension_dialog()
        try:
            display = drawing_doc.AddDimension2(
                units.mm_to_m(20.0), units.mm_to_m(80.0), 0.0
            )
        finally:
            sketch._restore_dimension_dialog(restore)
        result = {
            "selected": ok,
            "display_created": display is not None,
        }
        if display is not None:
            dimension = binding.wrap(display, "IDisplayDimension")
            result["text_before"] = str(dimension.GetText(0) or "")
            try:
                dimension.SetText(0, "PROBED")
                result["text_after_set"] = str(dimension.GetText(0) or "")
            except Exception as exc:  # noqa: BLE001
                result["set_text_error"] = f"{type(exc).__name__}: {exc}"
        return result

    probe("dimension_single_circle", add_diameter_dimension)

    # --- annotation delete: note ------------------------------------------
    def delete_note():
        annotation = handles["annotation"]
        selected = bool(annotation.Select3(True, None))
        deleted = drawing_doc.Extension.DeleteSelection2(0)
        return {
            "selected": selected,
            "deleted_return": bool(deleted),
            "annotations_after": summarize_annotations(),
        }

    probe("note_delete", delete_note)

    # --- view delete: extra isometric view --------------------------------
    names_before = {v["name"] for v in drawings.list_drawing_views()["views"]}

    def delete_view():
        drawings.insert_model_view("isometric", 340.0, 240.0, None)
        names_after = {v["name"] for v in drawings.list_drawing_views()["views"]}
        new_names = sorted(names_after - names_before)
        if not new_names:
            raise RuntimeError("isometric view did not appear")
        target = new_names[-1]
        session.clear_selection(drawing_doc)
        extension = drawing_doc.Extension
        by_name = bool(
            extension.SelectByID2(target, "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, None, 0)
        )
        fallback = None
        if not by_name:
            view = next(
                v
                for v in drawings._views(drawing_doc)
                if drawings._view_name(v) == target
            )
            outline = list(binding.value(view.GetOutline()) or [])
            if len(outline) >= 4:
                cx = (outline[0] + outline[2]) / 2.0
                cy = (outline[1] + outline[3]) / 2.0
                fallback = bool(
                    extension.SelectByID2(
                        "", "DRAWINGVIEW", cx, cy, 0.0, False, 0, None, 0
                    )
                )
        deleted = extension.DeleteSelection2(0)
        names_end = {v["name"] for v in drawings.list_drawing_views()["views"]}
        return {
            "target": target,
            "selected_by_name": by_name,
            "selected_by_point": fallback,
            "deleted_return": bool(deleted),
            "still_open": sorted(names_end - names_before),
        }

    probe("view_delete", delete_view)

    # --- list_annotations summaries after all edits -----------------------
    probe("annotations_final", summarize_annotations)

    for title in created:
        try:
            for raw in application.GetDocuments() or []:
                doc = session.wrap_doc(raw)
                if str(binding.value(doc.GetTitle)) == title:
                    doc.SetSaveFlag()
                    application.CloseDoc(title)
        except Exception as exc:  # noqa: BLE001
            RESULTS.append(
                {
                    "probe": f"close:{title}",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    print(json.dumps({"probes": RESULTS}, indent=2, default=str))
    failed = [item for item in RESULTS if not item["ok"]]
    print(f"\nPROBE: {len(RESULTS) - len(failed)}/{len(RESULTS)} calls returned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
