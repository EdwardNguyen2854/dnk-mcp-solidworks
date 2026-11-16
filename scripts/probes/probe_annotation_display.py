#!/usr/bin/env python
"""Live probe: datum-tag and surface-finish display text, tolerance units.

Findings to establish on SW2026 SP0.0:

1. Datum tags: does ``IDatumTag.SetLabel`` produce display text, or does the
   drawn letter come from ``IDatumTag.SetText(0, ...)``?
2. Surface finish: which ``ISFSymbol.SetText`` index renders the roughness,
   and does the current ``InsertSurfaceFinishSymbol3`` MachAllowance value
   show at all?
3. Tolerance units: does ``IDimensionTolerance.SetValues`` take metres
   (system units) while the tools pass millimetres?

Operates on the active drawing, exports a check PNG, and does not save.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault(
    "SW_MCP_OUTPUT_ROOT",
    str(Path(__file__).resolve().parents[1] / "artifacts" / "iso-drawing-demo"),
)

from solidworks_mcp.com import binding  # noqa: E402
from solidworks_mcp.domain import drawings, export, session  # noqa: E402

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "iso-drawing-demo"
    / "probe-display.png"
)
RESULTS: list[dict] = []


def probe(name, fn):
    try:
        RESULTS.append({"probe": name, "ok": True, "result": fn()})
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(
            {
                "probe": name,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3),
            }
        )
    return RESULTS[-1]


def find_annotations(doc, type_code: int):
    found = []
    for view in drawings._views(doc):
        for annotation in drawings._view_annotations(view):
            try:
                if int(annotation.GetType()) == type_code:
                    found.append((view, annotation))
            except Exception:
                continue
    return found


def main() -> int:
    _, doc, kind = session.active_doc(("drawing",))
    print(f"active drawing: {session.doc_info(doc)['title']}")

    datum_entries = find_annotations(doc, 2)
    print(f"datum tags: {len(datum_entries)}")
    for order, (_view, annotation) in enumerate(datum_entries):
        tag = binding.wrap(annotation.GetSpecificAnnotation(), "IDatumTag")
        label = str(binding.value(tag.GetLabel) or "")
        texts = []
        count = 0
        try:
            count = int(binding.value(tag.GetTextCount()))
            texts = [str(tag.GetTextAtIndex(i) or "") for i in range(count)]
        except Exception as exc:  # noqa: BLE001
            texts = [f"{type(exc).__name__}: {exc}"]

        def set_text():
            tag.SetText(0, label)
            return {
                "count": count,
                "texts_before": texts,
                "texts_after": [
                    str(tag.GetTextAtIndex(i) or "") for i in range(max(count, 1))
                ],
            }

        probe(f"datum[{order}] label={label}", set_text)

    sf_entries = find_annotations(doc, 7)
    print(f"surface finishes: {len(sf_entries)}")
    for order, (_view, annotation) in enumerate(sf_entries):
        sf = binding.wrap(annotation.GetSpecificAnnotation(), "ISFSymbol")

        def sf_state():
            count = int(binding.value(sf.GetTextCount()))
            return {
                "count": count,
                "texts": [str(sf.GetText(i) or "") for i in range(count)],
                "symbol_type": int(binding.value(sf.GetSymbolType())),
            }

        probe(f"surface_finish[{order}] state", sf_state)

        def sf_set_zero():
            sf.SetText(0, "Ra 1.6")
            count = int(binding.value(sf.GetTextCount()))
            return [str(sf.GetText(i) or "") for i in range(count)]

        probe(f"surface_finish[{order}] set_text_0", sf_set_zero)

    dim_entries = find_annotations(doc, 4)
    for _view, annotation in dim_entries:
        display = binding.wrap(annotation.GetSpecificAnnotation(), "IDisplayDimension")
        value = drawings._dimension_value(display)
        if value not in (140.0, 10.0):
            continue
        dimension = binding.wrap(display.GetDimension2(0), "IDimension")
        tolerance = binding.wrap(binding.value(dimension.Tolerance), "IDimensionTolerance")
        label = f"dim value={value}"

        if value == 140.0:
            def tol_units():
                tolerance.Type = drawings.TOLERANCE_TYPES["symmetric"]
                tolerance.SetValues(0.0002, 0.0002)
                return {
                    "set_m": [0.0002, 0.0002],
                    "get": [float(tolerance.GetMinValue()), float(tolerance.GetMaxValue())],
                }

            probe(f"{label} tolerance metres", tol_units)
        else:
            def fit_hole_only():
                tolerance.Type = drawings.TOLERANCE_TYPES["fit"]
                ok = bool(tolerance.SetFitValues("H7", ""))
                return {
                    "set": ["H7", ""],
                    "return": ok,
                    "hole": str(tolerance.GetHoleFitValue() or ""),
                    "shaft": str(tolerance.GetShaftFitValue() or ""),
                }

            probe(f"{label} hole-only fit", fit_hole_only)

    # line+circle distance semantics for datum-based locating dimensions
    try:
        from solidworks_mcp.domain.drawings import add_dimension

        result = add_dimension("Drawing View1", [7, 8], [178.0, 220.0])
        RESULTS.append(
            {"probe": "line+circle X distance", "ok": True, "result": result["data"]}
        )
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(
            {
                "probe": "line+circle X distance",
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    try:
        from solidworks_mcp.domain.drawings import add_dimension

        result = add_dimension("Drawing View1", [6, 8], [178.0, 145.0])
        RESULTS.append(
            {"probe": "line+circle Y distance", "ok": True, "result": result["data"]}
        )
    except Exception as exc:  # noqa: BLE001
        RESULTS.append(
            {
                "probe": "line+circle Y distance",
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    # which InsertSurfaceFinishSymbol3 string parameter displays the roughness
    extension = drawings._extension(doc)
    variants = [
        ("mach_allowance", ("1.6", "", "", "", "", "", "")),
        ("other_vals", ("", "1.6", "", "", "", "", "")),
        ("max_roughness", ("", "", "", "", "1.6", "", "")),
        ("min_roughness", ("", "", "", "", "", "1.6", "")),
    ]
    variant_results = []
    for order, (label, params) in enumerate(variants):
        x_mm = 60.0 + order * 30.0
        raw = extension.InsertSurfaceFinishSymbol3(
            0, 0, x_mm / 1000.0, 0.240, 0.0, 0, 0, *params
        )
        if raw is None:
            variant_results.append({"label": label, "created": False})
            continue
        symbol = binding.wrap(raw, "ISFSymbol")
        try:
            count = int(binding.value(symbol.GetTextCount()))
        except Exception:
            count = -1
        variant_results.append(
            {
                "label": label,
                "created": True,
                "text_count": count,
                "texts": [
                    str(symbol.GetText(i) or "") for i in range(7)
                ],
            }
        )
    RESULTS.append({"probe": "surface_finish_params", "ok": True, "result": variant_results})

    exported = export.export_document(str(OUTPUT))
    print(json.dumps({"export": exported, "probes": RESULTS}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
