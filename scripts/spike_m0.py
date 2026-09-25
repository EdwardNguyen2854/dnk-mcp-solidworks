#!/usr/bin/env python
"""M0 spike: attach to a running SOLIDWORKS, build a box, verify the volume.

This proves the load-bearing assumptions before any server code is written:
  1. early binding via makepy on the installed SW2026 typelib,
  2. attach to an already-running session (never launch),
  3. sketch -> extrude -> measured mass properties,
  4. measured volume matches a hand calculation.

Usage:
    python scripts/spike_m0.py [--keep]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding  # noqa: E402
from solidworks_mcp.com.connect import attach, revision  # noqa: E402

TEMPLATE_PART = Path(
    r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates\Part.PRTDOT"
)
PLANE_CANDIDATES = ("Front Plane", "前视基准面", "前视基準面")
EXPECTED_VOLUME_M3 = 0.05 * 0.03 * 0.02


def close_leftovers(app) -> None:
    for doc in app.GetDocuments() or []:
        doc = binding.wrap(doc, "IModelDoc2")
        try:
            doc.SetSaveFlag()
        except Exception:
            pass
        try:
            app.CloseDoc(binding.value(doc.GetTitle))
        except Exception:
            pass


def find_plane_name(doc) -> str:
    names = []
    feat = doc.FirstFeature()
    while feat:
        feat = binding.wrap(feat, "IFeature")
        try:
            if feat.GetTypeName2() == "RefPlane":
                names.append(str(binding.value(feat.Name)))
        except Exception:
            pass
        feat = feat.GetNextFeature()
    for candidate in PLANE_CANDIDATES:
        if candidate in names:
            return candidate
    if not names:
        raise SystemExit("no reference planes found")
    return names[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the document open")
    args = parser.parse_args()

    app = attach()
    print("attached:", revision(app), "| typelib:", binding.version())

    close_leftovers(app)
    raw_doc = app.NewDocument(str(TEMPLATE_PART), 0, 0, 0)
    if raw_doc is None:
        raw_doc = app.ActiveDoc
    if raw_doc is None:
        raise SystemExit("NewDocument failed: no active document")
    doc = binding.wrap(raw_doc, "IModelDoc2")

    plane = find_plane_name(doc)
    ext = doc.Extension
    if not ext.SelectByID2(plane, "PLANE", 0, 0, 0, False, 0, None, 0):
        raise SystemExit(f"could not select plane {plane!r}")

    sketch_mgr = doc.SketchManager
    sketch_mgr.InsertSketch(True)
    sketch_mgr.CreateCornerRectangle(0, 0, 0, 0.05, 0.03, 0)
    sketch_mgr.InsertSketch(True)

    feature = doc.FeatureManager.FeatureExtrusion3(
        True, False, False,       # Sd, Flip, Dir
        0, 0,                     # T1, T2 (blind)
        0.02, 0.02,               # D1, D2
        False, False,             # Dchk1, Dchk2
        False, False,             # Ddir1, Ddir2
        0.0, 0.0,                 # Dang1, Dang2
        False, False,             # OffsetReverse1, OffsetReverse2
        False, False,             # TranslateSurface1, TranslateSurface2
        True, True, True,         # Merge, UseFeatScope, UseAutoSelect
        0, 0.0, False,            # T0, StartOffset, FlipStartOffset
    )
    if feature is None:
        raise SystemExit("FeatureExtrusion3 returned None")
    feature = binding.wrap(feature, "IFeature")

    mass_prop = ext.CreateMassProperty()
    volume = float(binding.value(mass_prop.Volume))
    mass = float(binding.value(mass_prop.Mass))
    density = float(binding.value(mass_prop.Density))

    report = {
        "revision": revision(app),
        "typelib": binding.version(),
        "plane": plane,
        "feature_name": str(binding.value(feature.Name)),
        "volume_m3": volume,
        "expected_volume_m3": EXPECTED_VOLUME_M3,
        "volume_error_pct": abs(volume - EXPECTED_VOLUME_M3)
        / EXPECTED_VOLUME_M3
        * 100,
        "mass_kg": mass,
        "density_kg_m3": density,
        "app_class": type(app).__name__,
    }

    if not args.keep:
        doc.SetSaveFlag()
        app.CloseDoc(binding.value(doc.GetTitle))

    print(json.dumps(report, indent=2))
    ok = report["volume_error_pct"] < 0.5
    print("M0 VOLUME CHECK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
