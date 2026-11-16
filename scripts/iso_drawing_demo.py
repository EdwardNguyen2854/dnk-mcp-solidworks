#!/usr/bin/env python
"""End-to-end ISO drawing demo following skills/dnk-solidworks-iso-engineering-drawing.

Builds a mounting bracket (140 x 80 x 12, 2 x Ø10 holes 90 mm apart, a 50 x 12
slot), then produces an A3 first-angle drawing with the standard workflow:

  capabilities -> part intake -> framed A3 sheet -> first-angle view set ->
  title-block properties -> datum scheme A|B|C -> basic (boxed) locating
  dimensions -> position GD&T -> hole fit -> surface finish -> general
  tolerance note -> revision table -> isometric view -> manifest/preflight/
  validation -> PDF + PNG export and verification -> save, close, reopen,
  re-validate.

Datum scheme (as a machinist reads it):

  A = large 140 x 80 mating face (side view's z = 0 outline)
  B = long side surface           (bottom edge, front view)
  C = perpendicular end surface   (right edge, front view)

Hole and slot locations are basic dimensions referenced to B/C: hole X = 25
and 90 (chain), hole Y = 40, slot centre Y = 40, slot X = 20 from the left
hole and 50 between arc centres, slot width 12. The 2X hole pattern gets one
POSITION ⌀0.2 A|B|C frame (callout `2X Ø10 H7 THRU`); the slot contour gets a
PROFILE 0.4 A|B|C frame. Title-block cells are filled through their real
property links (part Description/Material/Finish via $PRPSHEET, drawing
DrawnBy/CheckedBy/Dates/Revision via $PRP, and the revision-free file name
`BRK-1001` for DWG NO.).

Hand calculations: hole centre distance 90.00, hole Ø10.00, slot width 12.00,
slot arc spacing 50.00, plate 140 x 80 x 12, volume
140*80*12 - 2*pi*5^2*12 - (50*12 + pi*6^2)*12 mm^3.

Needs a running SOLIDWORKS session; creates/saves its own documents under
artifacts/iso-drawing-demo, then closes its part and drawing before exiting
so the session is left clean (outputs: BRK-1001.SLDDRW, BRK-1001-RevA.pdf,
BRK-1001-RevA.png). Any of the user's own open documents are left untouched.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "iso-drawing-demo"
PART = OUTPUT / "Bracket-1001.sldprt"
DRAWING = OUTPUT / "BRK-1001.SLDDRW"
PDF = OUTPUT / "BRK-1001-RevA.pdf"
PNG = OUTPUT / "BRK-1001-RevA.png"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                return {"ok": False, "error": {"message": item.text[:500]}}
    return {}


class Client:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool: str, **arguments) -> dict:
        envelope = parse(await self.session.call_tool(tool, arguments))
        if not envelope.get("ok"):
            print(f"      {tool}: {json.dumps(envelope.get('error'))}")
        return envelope

    async def data(self, tool: str, **arguments) -> dict:
        envelope = await self.call(tool, **arguments)
        return envelope.get("data", {}) if envelope.get("ok") else {}


def near(first, second, tolerance=0.05) -> bool:
    try:
        return abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


async def document_titles(client: Client) -> set[str]:
    data = await client.data("list_documents")
    documents = data if isinstance(data, list) else data.get("documents", [])
    return {str(item.get("title") or "") for item in documents}


async def close_workspace(client: Client, keep: set[str] | None = None) -> None:
    """Close this demo's documents, freeing the SOLIDWORKS session.

    ``keep`` is the set of titles that were open before the run (the user's
    documents). With ``keep`` set, only documents the run created are closed;
    without it, leftovers under the demo output folder are closed. Only the
    active document can be closed through the tool surface, so documents are
    closed one activation at a time and the loop stops if a foreign document
    becomes active.
    """
    for _ in range(10):
        data = await client.data("list_documents")
        documents = data if isinstance(data, list) else data.get("documents", [])
        if keep is not None:
            candidates = [
                item for item in documents if str(item.get("title") or "") not in keep
            ]
        else:
            candidates = [
                item
                for item in documents
                if str(OUTPUT).lower() in str(item.get("path") or "").lower()
            ]
        if not candidates:
            break
        titles = {str(item.get("title") or "") for item in candidates}
        active = await client.data("get_active_document_info")
        active_document = active.get("document", active) if isinstance(active, dict) else {}
        if str(active_document.get("title") or "") not in titles:
            break
        await client.call("close_document", save=False)


def edge_lookup(edges: list[dict]) -> dict:
    """Index the front view's edges by model geometry."""
    found: dict = {}
    for edge in edges:
        kind = edge.get("kind")
        if kind == "circle":
            centre = edge.get("center_mm") or [None, None]
            radius = edge.get("radius_mm")
            if near(centre[0], 25.0, 0.5) and near(centre[1], 40.0, 0.5):
                found["hole_left"] = edge["index"]
            elif near(centre[0], 115.0, 0.5) and near(centre[1], 40.0, 0.5):
                found["hole_right"] = edge["index"]
            elif near(centre[0], 45.0, 0.5) and near(centre[1], 40.0, 0.5):
                found["slot_arc_left"] = edge["index"]
            elif near(centre[0], 95.0, 0.5) and near(centre[1], 40.0, 0.5):
                found["slot_arc_right"] = edge["index"]
        elif kind == "line":
            start = edge.get("start_mm") or [None, None]
            end = edge.get("end_mm") or [None, None]
            length = edge.get("length_mm")
            ys = sorted([start[1], end[1]])
            xs = sorted([start[0], end[0]])
            if near(length, 140.0, 0.5) and near(ys[0], 0.0, 0.5):
                found["bottom"] = edge["index"]
            elif near(length, 140.0, 0.5) and near(ys[1], 80.0, 0.5):
                found["top"] = edge["index"]
            elif near(length, 80.0, 0.5) and near(xs[0], 0.0, 0.5):
                found["left"] = edge["index"]
            elif near(length, 80.0, 0.5) and near(xs[1], 140.0, 0.5):
                found["right"] = edge["index"]
            elif near(length, 50.0, 0.5) and near(ys[0], 34.0, 0.5):
                found["slot_lower"] = edge["index"]
            elif near(length, 50.0, 0.5) and near(ys[1], 46.0, 0.5):
                found["slot_upper"] = edge["index"]
    return found


async def build_part(client: Client) -> bool:
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0.0, y1_mm=0.0, x2_mm=140.0, y2_mm=80.0
    )
    await client.call(
        "sketch_circle", center_x_mm=25.0, center_y_mm=40.0, radius_mm=5.0
    )
    await client.call(
        "sketch_circle", center_x_mm=115.0, center_y_mm=40.0, radius_mm=5.0
    )
    await client.call(
        "sketch_slot", x1_mm=45.0, y1_mm=40.0, x2_mm=95.0, y2_mm=40.0, width_mm=12.0
    )
    await client.call("exit_sketch")
    extruded = await client.call("boss_extrude", depth_mm=12.0, name="Body")
    check("bracket extrudes", extruded["ok"])

    material = await client.call("set_material", name="6061 Alloy")
    mass = await client.data("get_mass_properties")
    expected = (
        140 * 80 * 12
        - 2 * math.pi * 5**2 * 12
        - (50 * 12 + math.pi * 6**2) * 12
    )
    check(
        "material is 6061 Aluminium",
        material["ok"] and near(mass.get("density_kg_m3"), 2700, 60),
        f"density={mass.get('density_kg_m3')}",
    )
    check(
        "volume matches the hand calculation",
        near(mass.get("volume_mm3"), expected, 1.0),
        f"measured={mass.get('volume_mm3')} expected={expected:.1f}",
    )
    # Title-block cells resolve against the part model: TITLE ← Description,
    # MATERIAL ← Material, FINISH ← Finish.
    part_fields = (
        ("Description", "Mounting Bracket"),
        ("Material", "AL 6061-T6"),
        ("Finish", "Ra 3.2 ON DATUM A FACE"),
    )
    written = 0
    for name, value in part_fields:
        result = await client.call("set_file_property", name=name, value=value)
        written += 1 if result.get("ok") else 0
    check("part model properties set for the title block", written == len(part_fields), f"{written}/{len(part_fields)}")
    saved = await client.call("save_document", path=str(PART))
    return bool(saved["ok"])


async def build_drawing(client: Client) -> dict:
    created = await client.call(
        "new_drawing",
        model=str(PART),
        paper_size="A3",
        scale=1.0,
        first_angle=True,
    )
    check("A3 drawing created", created["ok"])
    sheets = await client.data("list_drawing_sheets")
    check(
        "sheet is A3 landscape at 1:1 in millimetres",
        near(sheets.get("size_mm", [0, 0])[0], 420.0, 0.5)
        and near(sheets.get("size_mm", [0, 0])[1], 297.0, 0.5),
        json.dumps({"paper": sheets.get("paper_size"), "size": sheets.get("size_mm")}),
    )

    inserted = await client.call(
        "drawing_insert_standard_views",
        model_reference=str(PART),
        configuration="Default",
    )
    layout = inserted.get("data", {}).get("layout", {})
    front_box = layout.get("front", {}).get("outline_mm", {})
    top_box = layout.get("top", {}).get("outline_mm", {})
    right_box = layout.get("right", {}).get("outline_mm", {})
    check(
        "first-angle layout: top below front, right left of front",
        top_box.get("max", [0, 0])[1] < front_box.get("min", [0, 0])[1]
        and right_box.get("max", [0, 0])[0] < front_box.get("min", [0, 0])[0],
        json.dumps({"front": front_box, "top": top_box, "right": right_box}),
    )
    return {"layout": layout}


async def apply_properties(client: Client) -> None:
    fields = (
        ("Title", "Mounting Bracket"),
        ("DrawingNumber", "BRK-1001"),
        ("Revision", "A"),
        ("DrawnBy", "MCP DEMO"),
        ("CheckedBy", "REVIEW"),
        ("DrawnDate", "2026-09-27"),
        ("CheckedDate", "2026-09-27"),
        ("COMPANYNAME", "MCP DEMO"),
    )
    written = 0
    for name, value in fields:
        result = await client.call("drawing_set_property", name=name, value=value)
        written += 1 if result.get("ok") else 0
    check("title-block properties written", written == len(fields), f"{written}/{len(fields)}")


async def place_dimensions(client: Client) -> dict:
    listed = await client.data("list_drawing_views")
    front = next(
        (view for view in listed.get("views", []) if view.get("orientation") == "front"),
        None,
    )
    right = next(
        (view for view in listed.get("views", []) if view.get("orientation") == "right"),
        None,
    )
    top = next(
        (view for view in listed.get("views", []) if view.get("orientation") == "top"),
        None,
    )
    check(
        "front, right and top views found",
        front is not None and right is not None and top is not None,
    )
    if front is None or right is None or top is None:
        return {}
    view_name = front["name"]

    box = front.get("outline_mm", {})
    fmin_x, fmin_y = box.get("min", [164.0, 114.0])
    fmax_x, fmax_y = box.get("max", [316.0, 206.0])
    centre_x = (fmin_x + fmax_x) / 2.0
    centre_y = (fmin_y + fmax_y) / 2.0
    right_box = right.get("outline_mm", {})
    rmin_x = right_box.get("min", [120.0, 114.0])[0]
    rcentre_y = (right_box.get("min", [0.0, 0.0])[1] + right_box.get("max", [0.0, 0.0])[1]) / 2.0

    edges_data = await client.data("list_drawing_view_edges", view=view_name)
    edges = [
        edge
        for view in edges_data.get("views", [])
        for edge in view.get("edges", [])
    ]
    lookup = edge_lookup(edges)
    print(f"      edge lookup: {json.dumps(lookup)}")
    check(
        "all target edges identified",
        {
            "bottom",
            "left",
            "right",
            "top",
            "hole_left",
            "hole_right",
            "slot_lower",
            "slot_upper",
            "slot_arc_left",
            "slot_arc_right",
        }
        <= set(lookup),
    )

    async def add(label, edge_indices, placement, expected):
        result = await client.call(
            "drawing_add_dimension",
            view=view_name,
            edge_indices=edge_indices,
            placement_mm=placement,
        )
        value = result.get("data", {}).get("value")
        check(
            f"{label} reads {expected:.2f}",
            result["ok"] and near(value, expected),
            json.dumps(result.get("data", {})),
        )
        return result.get("data", {})

    dims: dict = {"view": view_name}

    # Sizes: 140 carries an individual tolerance, 80 is left to ISO 2768.
    dims["overall"] = await add("overall length", [lookup["top"]], [centre_x, fmax_y + 22.0], 140.0)
    dims["height"] = await add("overall height", [lookup["right"]], [fmax_x + 22.0, centre_y], 80.0)

    # Basic locating chain in X (datum C is the left edge).
    dims["hole_x"] = await add(
        "hole X from datum C", [lookup["left"], lookup["hole_left"]], [fmin_x + 14.0, fmax_y + 10.0], 25.0
    )
    dims["hole_span"] = await add(
        "hole span", [lookup["hole_left"], lookup["hole_right"]], [centre_x, fmax_y + 10.0], 90.0
    )
    dims["slot_offset"] = await add(
        "slot offset from the left hole",
        [lookup["hole_left"], lookup["slot_arc_left"]],
        [205.0, centre_y + 24.0],
        20.0,
    )
    dims["slot_span"] = await add(
        "slot arc spacing",
        [lookup["slot_arc_left"], lookup["slot_arc_right"]],
        [centre_x, centre_y + 24.0],
        50.0,
    )

    # Basic locating dimension in Y (datum B is the bottom edge), applied
    # explicitly to both the holes and the slot centreline.
    dims["hole_y"] = await add(
        "hole Y from datum B", [lookup["bottom"], lookup["hole_left"]], [fmin_x + 16.0, fmin_y + 26.0], 40.0
    )
    dims["slot_y"] = await add(
        "slot centre Y from datum B",
        [lookup["bottom"], lookup["slot_arc_left"]],
        [205.0, fmin_y + 30.0],
        40.0,
    )
    dims["slot_width"] = await add(
        "slot width", [lookup["slot_lower"], lookup["slot_upper"]], [centre_x, fmin_y + 28.0], 12.0
    )
    dims["diameter"] = await add("hole diameter", [lookup["hole_right"]], [300.0, fmin_y + 18.0], 10.0)

    right_edges = await client.data("list_drawing_view_edges", view=right["name"])
    thickness_edge = None
    for view in right_edges.get("views", []):
        if view.get("name") != right["name"]:
            continue
        thickness_edge = next(
            (
                edge["index"]
                for edge in view.get("edges", [])
                if edge.get("kind") == "line" and near(edge.get("depth_mm"), 12.0, 0.5)
            ),
            None,
        )
    thickness = await client.call(
        "drawing_add_dimension",
        view=right["name"],
        edge_indices=[thickness_edge],
        placement_mm=[rmin_x - 18.0, rcentre_y],
    )
    check(
        "plate thickness reads 12.00 on the side view",
        thickness["ok"] and near(thickness.get("data", {}).get("value"), 12.0),
        json.dumps(thickness.get("data", {})),
    )

    dims.update(
        {
            "right_view": right["name"],
            "top_view": top["name"],
            "fmin_x": fmin_x,
            "fmin_y": fmin_y,
            "fmax_x": fmax_x,
            "fmax_y": fmax_y,
            "centre_x": centre_x,
            "centre_y": centre_y,
            "rmin_x": rmin_x,
            "rcentre_y": rcentre_y,
            "lookup": lookup,
        }
    )
    return dims


async def apply_tolerances(client: Client, dims: dict) -> None:
    view_name = dims.get("view")

    overall = await client.call(
        "drawing_set_dimension_tolerance",
        view=view_name,
        index=dims["overall"].get("index"),
        tolerance="symmetric",
        value_mm=0.2,
    )
    tolerance = overall.get("data", {}).get("tolerance", {})
    check(
        "overall 140 carries symmetric ±0.2 (millimetres, not metres)",
        overall["ok"]
        and tolerance.get("type") == "symmetric"
        and near(tolerance.get("min"), 0.2, 1e-4)
        and near(tolerance.get("max"), 0.2, 1e-4),
        json.dumps(tolerance),
    )

    for key, label in (
        ("hole_x", "hole X (25) from C"),
        ("hole_span", "hole span (90)"),
        ("hole_y", "hole Y (40) from B"),
        ("slot_offset", "slot offset (20)"),
        ("slot_span", "slot arc spacing (50)"),
        ("slot_y", "slot centre Y (40) from B"),
        ("slot_width", "slot width (12)"),
    ):
        basic = await client.call(
            "drawing_set_dimension_tolerance",
            view=view_name,
            index=dims[key].get("index"),
            tolerance="basic",
        )
        applied = basic.get("data", {}).get("tolerance", {})
        check(
            f"{label} is a boxed basic dimension",
            basic["ok"] and applied.get("type") == "basic",
            json.dumps(applied),
        )

    fit = await client.call(
        "drawing_set_dimension_tolerance",
        view=view_name,
        index=dims["diameter"].get("index"),
        tolerance="fit",
        hole_fit="H7",
    )
    fit_data = fit.get("data", {}).get("tolerance", {})
    check(
        "hole callout is 2X dia 10 H7 (hole only, no shaft)",
        fit["ok"] and fit_data.get("hole_fit") == "H7" and not fit_data.get("shaft_fit"),
        json.dumps(fit_data),
    )

    prefix = await client.call(
        "drawing_set_annotation_text",
        view=view_name,
        index=dims["diameter"].get("index"),
        prefix="2X ",
    )
    check(
        "hole dimension reads 2X dia 10",
        prefix["ok"] and prefix.get("data", {}).get("prefix") == "2X ",
        json.dumps(prefix.get("data", {})),
    )
    suffix = await client.call(
        "drawing_set_annotation_text",
        view=view_name,
        index=dims["diameter"].get("index"),
        suffix=" THRU",
    )
    check(
        "hole callout ends with THRU",
        suffix["ok"] and suffix.get("data", {}).get("suffix") == " THRU",
        json.dumps(suffix.get("data", {})),
    )


async def apply_annotations(client: Client, dims: dict) -> None:
    view_name = dims.get("view")
    lookup = dims.get("lookup", {})

    marks = await client.call("drawing_insert_center_marks", view_name=view_name)
    check(
        "centre marks on the holes and slot",
        marks["ok"] and marks.get("data", {}).get("marks_added", 0) >= 2,
        json.dumps(marks.get("data", {})),
    )

    # Datum scheme (reviewer-agreed):
    #   A = large 140 x 80 mating face  -> side view z = 0 outline
    #   B = long side surface           -> front view bottom edge (140 long)
    #   C = perpendicular end surface   -> front view right edge (80 long)
    # Measured on SW2026 SP0.0: a datum tag snaps its along-edge coordinate to
    # the edge's start vertex, so the free coordinate is what separates the
    # symbols on the sheet.
    datum_b = await client.call(
        "drawing_insert_datum",
        view=view_name,
        edge_index=lookup.get("bottom"),
        label="B",
        x_mm=240.0,
        y_mm=dims["fmin_y"] - 14.0,
    )
    datum_c = await client.call(
        "drawing_insert_datum",
        view=view_name,
        edge_index=lookup.get("right"),
        label="C",
        x_mm=dims["fmax_x"] + 10.0,
        y_mm=dims["rcentre_y"],
    )
    check(
        "datum B (long surface) and C (end surface) attached",
        datum_b["ok"] and datum_c["ok"],
        json.dumps([datum_b.get("data"), datum_c.get("data")]),
    )

    # Datum A = mounting face: the side view's z = 0 outline.
    right_edges = await client.data("list_drawing_view_edges", view=dims["right_view"])
    datum_a_edge = None
    for view in right_edges.get("views", []):
        if view.get("name") != dims["right_view"]:
            continue
        datum_a_edge = next(
            (
                edge["index"]
                for edge in view.get("edges", [])
                if edge.get("kind") == "line"
                and edge.get("start3_mm")
                and near(edge["start3_mm"][2], 0.0, 1e-6)
                and near(edge.get("length_mm"), 80.0, 0.5)
            ),
            None,
        )
    datum_a = await client.call(
        "drawing_insert_datum",
        view=dims["right_view"],
        edge_index=datum_a_edge,
        label="A",
        x_mm=100.0,
        y_mm=dims["rcentre_y"],
    )
    check(
        "datum A attached to the mounting face",
        datum_a["ok"],
        json.dumps(datum_a.get("data", {})),
    )
    check(
        "datum tags are spaced apart",
        not any(
            result.get("data", {}).get("nearby_datum_tags")
            for result in (datum_b, datum_c, datum_a)
        ),
        json.dumps(
            [
                result.get("data", {}).get("text_position_mm")
                for result in (datum_b, datum_c, datum_a)
            ]
        ),
    )

    # One position FCF for the 2X hole pattern, one profile FCF for the slot.
    hole_fcf = await client.call(
        "drawing_insert_gtol",
        view=view_name,
        edge_index=lookup.get("hole_right"),
        symbol="position",
        tolerance="0.2",
        diameter=True,
        datums=["A", "B", "C"],
        x_mm=300.0,
        y_mm=dims["fmin_y"] - 10.0,
    )
    check(
        "one position FCF 0.2 A|B|C for the 2X hole pattern",
        hole_fcf["ok"]
        and hole_fcf.get("data", {}).get("frame_values", [])[:5]
        == ["0.2", "", "A", "B", "C"],
        json.dumps(hole_fcf.get("data", {})),
    )
    slot_fcf = await client.call(
        "drawing_insert_gtol",
        view=view_name,
        edge_index=lookup.get("slot_lower"),
        symbol="surface_profile",
        tolerance="0.4",
        datums=["A", "B", "C"],
        x_mm=dims["centre_x"],
        y_mm=dims["centre_y"] + 13.0,
    )
    check(
        "slot contour carries a profile FCF 0.4 A|B|C",
        slot_fcf["ok"]
        and slot_fcf.get("data", {}).get("frame_values", [])[:5]
        == ["0.4", "", "A", "B", "C"],
        json.dumps(slot_fcf.get("data", {})),
    )

    # Surface finish on datum A, shown on the top view's z = 0 outline.
    # Measured on SW2026 SP0.0: the value stores in MaxRoughness/GetText(5)
    # but its text items render at zero height, so a companion note spells
    # the value and its scope out.
    top_edges = await client.data("list_drawing_view_edges", view=dims["top_view"])
    sf_edge = None
    for view in top_edges.get("views", []):
        if view.get("name") != dims["top_view"]:
            continue
        sf_edge = next(
            (
                edge["index"]
                for edge in view.get("edges", [])
                if edge.get("kind") == "line"
                and edge.get("start3_mm")
                and near(edge["start3_mm"][2], 0.0, 1e-6)
                and near(edge.get("length_mm"), 140.0, 0.5)
            ),
            None,
        )
    finish = await client.call(
        "drawing_insert_surface_finish",
        view=dims["top_view"],
        edge_index=sf_edge,
        roughness="3.2",
        x_mm=170.0,
        y_mm=60.0,
    )
    check(
        "surface finish symbol with stored Ra 3.2",
        finish["ok"] and "3.2" in str(finish.get("data", {}).get("roughness", "")),
        json.dumps(finish.get("data", {})),
    )
    finish_note = await client.call(
        "drawing_add_note",
        text="Ra 3.2 ON DATUM A FACE",
        x_mm=150.0,
        y_mm=50.0,
        height_mm=3.5,
    )
    check("Ra value and scope spelled out beside the symbol", finish_note["ok"])

    note = await client.call(
        "drawing_add_note",
        text=(
            "UNLESS OTHERWISE SPECIFIED:\n"
            "REVIEW: GENERAL TOLERANCES UNCONFIRMED\n"
            "DEBURR AND BREAK SHARP EDGES"
        ),
        x_mm=30.0,
        y_mm=255.0,
        height_mm=3.5,
    )
    check(
        "general-tolerance and deburr note added",
        note["ok"] and "DEBURR" in str(note.get("data", {}).get("text")),
        json.dumps(note.get("data", {})),
    )

    table = await client.call("drawing_insert_revision_table")
    table_data = table.get("data", {})
    position = table_data.get("position_mm") or [0.0, 0.0]
    size = table_data.get("size_mm") or {}
    top_edge = position[1] + float(size.get("height", 0.0))
    right_edge = position[0] + float(size.get("width", 0.0))
    check(
        "revision table sits inside the frame",
        table["ok"]
        and table_data.get("inside_frame") is True
        and top_edge <= 287.5
        and right_edge <= 410.5,
        json.dumps(table_data),
    )
    revision = await client.call(
        "drawing_add_revision",
        revision="A",
        description="Initial release",
        date="2026-09-27",
    )
    check(
        "revision table current revision is A",
        table["ok"] and revision["ok"] and revision.get("data", {}).get("revision") == "A",
        json.dumps(revision.get("data", {})),
    )
    placement = revision.get("data", {}).get("placement") or {}
    check(
        "revision table stays inside the frame after the row is added",
        placement.get("inside_frame") is True,
        json.dumps(placement),
    )

    iso = await client.data(
        "drawing_insert_view", view="isometric", x_mm=95.0, y_mm=62.0,
        model_reference=str(PART), configuration="Default"
    )
    iso_name = iso.get("name")
    check("isometric view inserted", bool(iso_name), str(iso_name))
    if iso_name:
        placed = await client.call(
            "drawing_set_view", name=iso_name, x_mm=95.0, y_mm=62.0, scale=0.5
        )
        check("isometric view placed at 1:2", placed["ok"], json.dumps(placed.get("data", {})))


async def release_check(client: Client) -> bool:
    preflight = await client.call("drawing_preflight")
    check("preflight passes", preflight["ok"], json.dumps(preflight.get("data", {}).get("checks")))

    manifest = await client.call("drawing_manifest")
    check("manifest collected", manifest["ok"], json.dumps(manifest.get("data", {}).get("scope")))

    validated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    validation = validated.get("data", {}).get("validation", validated.get("data", {}))
    check(
        "ISO validation passes",
        validated["ok"] and validation.get("valid") is True,
        json.dumps(validation.get("errors") or validation.get("checks")),
    )
    check(
        "validation sees readable dimensions",
        validation.get("readable_dimensions", 0) >= 8,
        f"readable={validation.get('readable_dimensions')}",
    )

    # Save first: the DWG NO. cell links to $PRP:"SW-File Name", so the
    # revision-free file name must be set before the exports are made.
    saved = await client.call("save_document", path=str(DRAWING))
    check("drawing saved as the revision-free number BRK-1001", saved["ok"])

    annotations = await client.data("list_drawing_annotations")
    flat = [
        annotation
        for view in annotations.get("views", [])
        for annotation in view.get("annotations", [])
    ]

    def linked(code: str, name: str):
        return next(
            (
                annotation
                for annotation in flat
                if annotation.get("property_linked_text")
                == f'${code}:"{name}"'
            ),
            None,
        )

    for code, name, expected in (
        ("PRPSHEET", "Description", "Mounting Bracket"),
        ("PRPSHEET", "Material", "AL 6061-T6"),
        ("PRPSHEET", "Finish", "Ra 3.2 ON DATUM A FACE"),
        ("PRP", "SW-File Name", "BRK-1001"),
        ("PRP", "DrawnBy", "MCP DEMO"),
        ("PRP", "CheckedBy", "REVIEW"),
        ("PRP", "Revision", "A"),
    ):
        entry = linked(code, name) or {}
        resolved = entry.get("resolved_text") or ""
        check(
            f"title block {name} resolves to {expected!r}",
            resolved == expected,
            f"resolved={resolved!r}",
        )

    callouts = [
        annotation
        for annotation in flat
        if annotation.get("type") == "dimension"
        and annotation.get("value") == 10.0
        and annotation.get("prefix") == "2X "
    ]
    check(
        "hole callout reads 2X ... THRU",
        len(callouts) == 1 and callouts[0].get("suffix") == " THRU",
        json.dumps(callouts),
    )

    frames = [
        annotation for annotation in flat if annotation.get("type") == "geometric_tolerance"
    ]
    hole_frames = [
        frame for frame in frames if frame.get("frame_values", [])[:5] == ["0.2", "", "A", "B", "C"]
    ]
    slot_frames = [
        frame for frame in frames if frame.get("frame_values", [])[:5] == ["0.4", "", "A", "B", "C"]
    ]
    check("exactly one position FCF for the 2X hole pattern", len(hole_frames) == 1, json.dumps(hole_frames))
    check("exactly one profile FCF for the slot", len(slot_frames) == 1, json.dumps(slot_frames))

    note_texts = [
        annotation.get("resolved_text") or annotation.get("text") or ""
        for annotation in flat
        if annotation.get("type") == "note"
    ]
    check("deburr note present", any("DEBURR" in text for text in note_texts))
    check(
        "Ra 3.2 scope note present",
        any("Ra 3.2 ON DATUM A FACE" in text for text in note_texts),
    )
    check(
        "surface finish symbol stores Ra 3.2",
        any(
            annotation.get("type") == "surface_finish"
            and "3.2" in str(annotation.get("text", ""))
            for annotation in flat
        ),
    )

    audit_result = await client.call("drawing_layout_audit")
    audit_data = audit_result.get("data", {})
    counts = audit_data.get("counts", {})
    check(
        "annotation layout audit is clean",
        audit_result["ok"]
        and counts.get("collisions") == 0
        and counts.get("off_frame") == 0,
        json.dumps(
            {
                "counts": counts,
                "collisions": audit_data.get("collisions", [])[:3],
                "off_frame": audit_data.get("off_frame", [])[:3],
            }
        ),
    )

    exported = await client.call("export_document", path=str(PDF))
    check("PDF exported", exported["ok"])
    verified = await client.call("verify_export", path=str(PDF))
    details = verified.get("data", {}).get("details", {})
    check(
        "PDF verifies as one consistent page",
        verified["ok"] and details.get("page_count") == 1 and details.get("page_count_consistent") is True,
        json.dumps(details),
    )

    image = await client.call("export_document", path=str(PNG))
    check("PNG sheet image exported", image["ok"])

    await client.call("close_document", save=False)
    reopened = await client.call("open_document", path=str(DRAWING))
    check("drawing reopens from disk", reopened["ok"])
    revalidated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    revalidation = revalidated.get("data", {}).get("validation", revalidated.get("data", {}))
    check(
        "ISO validation survives save and reopen",
        revalidated["ok"] and revalidation.get("valid") is True,
        json.dumps(revalidation.get("errors") or revalidation.get("checks")),
    )
    return bool(validated["ok"])


async def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(OUTPUT))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "solidworks_mcp"],
        env=env,
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = Client(session)
            # Clear leftovers from earlier runs, remember what was open before
            # this run, and always close this run's documents on the way out.
            await close_workspace(client)
            baseline = await document_titles(client)
            try:
                capabilities = await client.data("get_capabilities")
                check(
                    "SOLIDWORKS reachable",
                    bool(capabilities),
                    json.dumps(capabilities.get("solidworks", capabilities))[:150],
                )
                built = await build_part(client)
                if not built:
                    print("part build failed; stopping")
                else:
                    await build_drawing(client)
                    await apply_properties(client)
                    dims = await place_dimensions(client)
                    if dims:
                        await apply_tolerances(client, dims)
                        await apply_annotations(client, dims)
                        await release_check(client)
            finally:
                await close_workspace(client, keep=baseline)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    summary = {
        "checks": [{"name": name, "passed": ok, "detail": detail} for name, ok, detail in CHECKS],
        "passed": passed,
        "total": len(CHECKS),
        "paths": {"part": str(PART), "drawing": str(DRAWING), "pdf": str(PDF), "png": str(PNG)},
    }
    (OUTPUT / "demo-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    print(f"drawing: {DRAWING}")
    print(f"pdf:     {PDF}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
