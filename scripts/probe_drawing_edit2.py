#!/usr/bin/env python
"""Live probe 2: annotation selection/delete variants and dimension text.

Follow-up to probe_drawing_edit.py, which showed:

- note move (`IAnnotation.SetPosition`) and re-text (`INote.SetText`) work;
- `AddDimension2` on two picked circle edges creates a linear dimension that
  reads back through `list_dimensions` (value 60.0);
- `IAnnotation.Select3(True, None)` returned false and `DeleteSelection2`
  then left the note in place;
- `IDisplayDimension.SetText(0, "PROBED")` did not change `GetText(0)`;
- the stock sheet reports several dozen `note` annotations on `Sheet1`.

Open questions this probe answers:

1. Which selection call removes an annotation: `Select`, `Select2`,
   `Select3` or `SelectByID2`?
2. What are the stock `Sheet1` notes (title-block cells?) and how many?
3. Does `IDisplayDimension.SetText` need a specific `WhichText` value, and
   which read-back reflects the override?
4. Does `IAnnotation.SetPosition` move a dimension's text?

Creates a scratch part + drawing and discards both. Run with SOLIDWORKS
open; save your work first.
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


def main() -> int:
    application = session.app()
    created: list[str] = []

    documents.new_document("part")
    part_title = str(binding.value(session.active_doc(("part",))[1].GetTitle))
    created.append(part_title)
    sketch.create_sketch("Front Plane")
    sketch.rectangle(0.0, 0.0, 120.0, 80.0)
    sketch.circle(30.0, 40.0, 5.0)
    sketch.circle(90.0, 40.0, 5.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=20.0)

    drawings.create_drawing(paper_size="A3", scale=1.0, first_angle=True)
    doc = session.active_doc(("drawing",))[1]
    created.insert(0, str(binding.value(doc.GetTitle)))
    drawings.insert_standard_views()
    extension = doc.Extension

    def make_note(text: str, x_mm: float, y_mm: float):
        raw = doc.InsertNote(text)
        if raw is None:
            raise RuntimeError("InsertNote returned None")
        note = binding.wrap(raw, "INote")
        annotation = binding.wrap(note.GetAnnotation(), "IAnnotation")
        annotation.SetPosition(units.mm_to_m(x_mm), units.mm_to_m(y_mm), 0.0)
        return note, annotation

    def baseline():
        listed = drawings.list_annotations()
        sheet = next(
            (v for v in listed["views"] if v["name"] == "Sheet1"), None
        )
        notes = [a for a in (sheet or {}).get("annotations", []) if a.get("type") == "note"]
        return {
            "sheet_note_count": len(notes),
            "sample_texts": [a.get("text", "")[:40] for a in notes[:8]],
            "total_annotations": listed.get("total"),
        }

    probe("baseline_sheet_annotations", baseline)

    # --- annotation deletion: one fresh note per strategy -----------------
    def deletion_strategies():
        outcomes = []

        def run(label, select):
            text = f"DEL {label}"
            _note, annotation = make_note(text, 40.0 + len(outcomes) * 30.0, 30.0)
            selected = select(annotation)
            removed = bool(extension.DeleteSelection2(0))
            alive = find_note(doc, text)[1] is not None
            outcomes.append(
                {
                    "strategy": label,
                    "select_return": selected,
                    "delete_return": removed,
                    "note_still_present": alive,
                }
            )

        run("Select(True)", lambda a: bool(a.Select(True)))
        run("Select2(True,0)", lambda a: bool(a.Select2(True, 0)))

        def select_by_id(annotation):
            position = list(binding.value(annotation.GetPosition()) or [])
            if len(position) < 2:
                return False
            return bool(
                extension.SelectByID2(
                    "",
                    "NOTE",
                    float(position[0]),
                    float(position[1]),
                    0.0,
                    False,
                    0,
                    None,
                    0,
                )
            )

        run("SelectByID2(NOTE)", select_by_id)
        run("Select3(True,None)", lambda a: bool(a.Select3(True, None)))
        return outcomes

    probe("annotation_deletion_strategies", deletion_strategies)

    # --- dimension text and position --------------------------------------
    views = drawings.list_drawing_views().get("views", [])
    front = next(v for v in views if v.get("orientation") == "front")
    front_name = front["name"]
    view = drawings._model_view(doc, front_name)
    entities = drawings._view_visible_edges(view)
    edge_info = [drawings._view_edge_info(entity) for entity in entities]
    circles = [
        index for index, info in enumerate(edge_info) if info.get("kind") == "circle"
    ]

    def dimension_text():
        drawings.activate_view(front_name)
        session.clear_selection(doc)
        view.SelectEntity(entities[circles[0]], False)
        restore = sketch._suppress_dimension_dialog()
        try:
            raw_display = doc.AddDimension2(
                units.mm_to_m(20.0), units.mm_to_m(80.0), 0.0
            )
        finally:
            sketch._restore_dimension_dialog(restore)
        if raw_display is None:
            raise RuntimeError("AddDimension2 returned None")
        display = binding.wrap(raw_display, "IDisplayDimension")
        readings = {"initial": str(display.GetText(0) or "")}
        for which, text in ((0, "PROBED"), (1, "PRE"), (2, "SUF"), (5, "PREDEF")):
            try:
                display.SetText(which, text)
                readings[f"set_{which}"] = {
                    "get0": str(display.GetText(0) or ""),
                    "get_self": str(display.GetText(which) or ""),
                }
            except Exception as exc:  # noqa: BLE001
                readings[f"set_{which}"] = f"{type(exc).__name__}: {exc}"
        listed = drawings.list_annotations(front_name)
        dim_texts = [
            annotation.get("text")
            for item in listed["views"]
            for annotation in item.get("annotations", [])
            if annotation.get("type") == "dimension"
        ]
        readings["listed_dimension_texts"] = dim_texts
        return readings

    probe("dimension_set_text", dimension_text)

    def dimension_move():
        annotation = None
        for candidate in drawings._view_annotations(view):
            if int(candidate.GetType()) == 4:
                annotation = candidate
                break
        if annotation is None:
            raise RuntimeError("no dimension annotation in the front view")
        before = list(binding.value(annotation.GetPosition()) or [])
        annotation.SetPosition(units.mm_to_m(135.0), units.mm_to_m(30.0), 0.0)
        after = list(binding.value(annotation.GetPosition()) or [])
        listed = drawings.list_dimensions(front_name)
        return {
            "before_mm": [round(units.m_to_mm(v), 3) for v in before[:2]],
            "after_mm": [round(units.m_to_mm(v), 3) for v in after[:2]],
            "listed": [
                {
                    "value": item.get("value"),
                    "position_mm": item.get("position_mm"),
                }
                for view_item in listed["views"]
                for item in view_item.get("dimensions", [])
            ],
        }

    probe("dimension_move", dimension_move)

    for title in created:
        try:
            for raw in application.GetDocuments() or []:
                candidate = session.wrap_doc(raw)
                if str(binding.value(candidate.GetTitle)) == title:
                    candidate.SetSaveFlag()
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
    print(f"\nPROBE2: {len(RESULTS) - len(failed)}/{len(RESULTS)} calls returned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
