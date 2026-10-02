#!/usr/bin/env python
"""Live probe 3: note text-format call path.

The strict `set_annotation_text` found a Type mismatch that `add_note`'s
silent try/except has been hiding. Isolate the failing call:

- re-fetched note -> INote.SetText
- IAnnotation.GetTextFormat shape
- CharHeight assignment on the raw dispatch
- the same on `binding.wrap(text_format, "ITextFormat")`
- IAnnotation.SetTextFormat(0, False, ...)

Creates a scratch part + drawing and discards both.
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
        value = fn()
        RESULTS.append({"probe": name, "ok": True, "result": value})
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(
            {
                "probe": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=4),
            }
        )
    return RESULTS[-1]


def main() -> int:
    application = session.app()
    created: list[str] = []
    documents.new_document("part")
    part_doc = session.active_doc(("part",))[1]
    part_info = session.doc_info(part_doc)
    model_reference = part_info.get("path") or part_info["title"]
    configuration = part_info.get("active_configuration") or "Default"
    created.append(part_info["title"])
    sketch.create_sketch("Front Plane")
    sketch.rectangle(0.0, 0.0, 120.0, 80.0)
    sketch.circle(30.0, 40.0, 5.0)
    sketch.circle(90.0, 40.0, 5.0)
    sketch.exit_sketch()
    features.boss_extrude(depth_mm=20.0)
    drawings.create_drawing(paper_size="A3", scale=1.0, first_angle=True)
    doc = session.active_doc(("drawing",))[1]
    created.insert(0, str(binding.value(doc.GetTitle)))
    drawings.insert_standard_views(model_reference, configuration)

    drawings.add_note("EDIT ME", 180.0, 230.0)
    note_annotation = None
    for view in drawings._views(doc):
        for annotation in drawings._view_annotations(view):
            try:
                if int(annotation.GetType()) != 6:
                    continue
                note = binding.wrap(annotation.GetSpecificAnnotation(), "INote")
                if str(binding.value(note.GetText) or "") == "EDIT ME":
                    note_annotation = annotation
                    break
            except Exception:
                continue
        if note_annotation is not None:
            break
    if note_annotation is None:
        raise SystemExit("note not found")

    note = binding.wrap(note_annotation.GetSpecificAnnotation(), "INote")
    probe("note_set_text", lambda: (note.SetText("EDITED"), str(binding.value(note.GetText)))[1])

    def format_shape():
        shapes = {}
        try:
            shapes["annotation_indexed"] = repr(
                note_annotation.GetTextFormat(0)
            )[:80]
        except Exception as exc:  # noqa: BLE001
            shapes["annotation_indexed"] = f"{type(exc).__name__}: {exc}"
        try:
            shapes["annotation_no_args"] = repr(note_annotation.GetTextFormat())[:80]
        except Exception as exc:  # noqa: BLE001
            shapes["annotation_no_args"] = f"{type(exc).__name__}: {exc}"
        try:
            shapes["note_own"] = repr(note.GetTextFormat())[:80]
        except Exception as exc:  # noqa: BLE001
            shapes["note_own"] = f"{type(exc).__name__}: {exc}"
        try:
            shapes["format_count"] = int(binding.value(note_annotation.GetTextFormatCount()))
        except Exception as exc:  # noqa: BLE001
            shapes["format_count"] = f"{type(exc).__name__}: {exc}"
        return shapes

    probe("get_text_format_variants", format_shape)

    def char_height_note_own():
        text_format = binding.wrap(note.GetTextFormat(), "ITextFormat")
        before = float(binding.value(text_format.CharHeight))
        text_format.CharHeight = units.mm_to_m(4.0)
        note.SetTextFormat(0, text_format)
        after = float(binding.value(binding.wrap(note.GetTextFormat(), "ITextFormat").CharHeight))
        return {"before_m": before, "after_m": after}

    probe("char_height_via_note", char_height_note_own)

    def char_height_indexed_annotation():
        text_format = binding.wrap(note_annotation.GetTextFormat(0), "ITextFormat")
        text_format.CharHeight = units.mm_to_m(6.0)
        note_annotation.SetTextFormat(0, False, text_format)
        after = float(
            binding.value(binding.wrap(note_annotation.GetTextFormat(0), "ITextFormat").CharHeight)
        )
        return {"after_m": after}

    probe("char_height_via_annotation_index", char_height_indexed_annotation)

    for title in created:
        try:
            for raw in application.GetDocuments() or []:
                candidate = session.wrap_doc(raw)
                if str(binding.value(candidate.GetTitle)) == title:
                    candidate.SetSaveFlag()
                    application.CloseDoc(title)
        except Exception as exc:  # noqa: BLE001
            RESULTS.append({"probe": f"close:{title}", "ok": False, "error": str(exc)})

    print(json.dumps({"probes": RESULTS}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
