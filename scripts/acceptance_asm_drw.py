#!/usr/bin/env python
"""Live acceptance for assemblies and drawings."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "acceptance_asm"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def parse(result) -> dict:
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    return {}


class Client:
    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool: str, **arguments) -> dict:
        envelope = parse(await self.session.call_tool(tool, arguments))
        if not envelope.get("ok"):
            print(f"      {tool}: {json.dumps(envelope.get('error'))}")
        return envelope


async def close_if_active(client: Client, path: str) -> None:
    """Close the document at ``path`` only when it is the active one.

    Leaves the user's own documents untouched; keeps reruns from colliding
    with parts and drawings the previous run left open.
    """
    active = await client.call("get_active_document_info")
    document = active.get("data", {}).get("document", {}) or active.get("data", {})
    current = str((document or {}).get("path") or "")
    if current and current.lower() == path.lower():
        await client.call("close_document", save=False)


async def build_part(client: Client, path: str, width: float, height: float,
                     depth: float) -> None:
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=width, y2_mm=height
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=depth, name="Body")
    assert result["ok"], result
    saved = await client.call("save_document", path=path)
    assert saved["ok"], saved
    await client.call("close_document", save=False)


async def test_assembly(client: Client) -> None:
    part_a = str(OUTPUT / "block_a.sldprt")
    part_b = str(OUTPUT / "block_b.sldprt")
    await build_part(client, part_a, 50, 30, 10)
    await build_part(client, part_b, 40, 20, 10)

    result = await client.call("new_document", kind="assembly")
    check("new assembly", result["ok"], "")

    result = await client.call("insert_component", path=part_a, fixed=True)
    check("insert fixed component", result["ok"], json.dumps(result.get("data", {}).get("component", {}).get("name")))
    result = await client.call(
        "insert_component", path=part_b, x_mm=100, y_mm=0, z_mm=0
    )
    check("insert movable component", result["ok"], "")

    listing = await client.call("list_components")
    components = listing.get("data", {}).get("components", [])
    check("two components", len(components) == 2, f"{len(components)}")
    if len(components) == 2:
        movable = [c for c in components if not c["fixed"]]
        check(
            "component placed at x=100",
            movable and abs(movable[0]["position_mm"][0] - 100) < 0.01,
            str(movable[0].get("position_mm") if movable else None),
        )

    components = listing["data"]["components"]
    fixed_component = next(c["name"] for c in components if c["fixed"])
    movable_component = next(c["name"] for c in components if not c["fixed"])

    await client.call(
        "set_component_transform", name=movable_component, x_mm=25, y_mm=0, z_mm=0
    )
    interference = await client.call("check_interference")
    check(
        "interference detected when overlapping",
        interference["ok"] and interference["data"]["count"] >= 1,
        json.dumps(interference.get("data")),
    )

    await client.call(
        "set_component_transform", name=movable_component, x_mm=100, y_mm=0, z_mm=0
    )
    interference = await client.call("check_interference")
    check(
        "no interference when separated",
        interference["ok"] and interference["data"]["count"] == 0,
        json.dumps(interference.get("data")),
    )

    result = await client.call(
        "add_mate",
        mate_type="coincident",
        component_a=fixed_component,
        direction_a="+x",
        component_b=movable_component,
        direction_b="-x",
        align="closest",
    )
    check("coincident mate", result["ok"], "")

    listing = await client.call("list_components")
    moved = next(
        (c for c in listing["data"]["components"] if c["name"] == movable_component),
        None,
    )
    check(
        "mate solved to x=50",
        moved is not None and abs(moved["position_mm"][0] - 50) < 0.01,
        str(moved.get("position_mm") if moved else None),
    )

    interference = await client.call("check_interference")
    check(
        "no interference when touching",
        interference["ok"] and interference["data"]["count"] == 0,
        json.dumps(interference.get("data")),
    )

    mates = await client.call("list_mates")
    entries = mates.get("data", {}).get("mates", [])
    check(
        "list_mates reads the coincident mate",
        mates["ok"] and any(m.get("mate_type") == "coincident" for m in entries),
        json.dumps(entries),
    )
    mated_components = {
        entity.get("component")
        for entry in entries
        for entity in entry.get("entities", [])
    }
    check(
        "mate entities name both components",
        fixed_component in mated_components and movable_component in mated_components,
        str(sorted(mated_components)),
    )

    result = await client.call(
        "set_component_fixed", component_names=[movable_component], fixed=True
    )
    listing = await client.call("list_components")
    state = next(
        c["fixed"]
        for c in listing["data"]["components"]
        if c["name"] == movable_component
    )
    check("set_component_fixed fixes", result["ok"] and state is True, str(state))
    result = await client.call(
        "set_component_fixed", component_names=[movable_component], fixed=False
    )
    listing = await client.call("list_components")
    state = next(
        c["fixed"]
        for c in listing["data"]["components"]
        if c["name"] == movable_component
    )
    check("set_component_fixed floats", result["ok"] and state is False, str(state))

    bbox = await client.call("get_assembly_bounding_box")
    size_x = bbox.get("data", {}).get("size_mm", [0])[0]
    check("assembly bounding box", bbox["ok"] and abs(size_x - 90) < 0.5,
          f"size_x={size_x}")

    saved = await client.call(
        "save_document", path=str(OUTPUT / "asm1.sldasm")
    )
    check("save assembly", saved["ok"], "")
    await client.call("close_document", save=False)


async def test_drawing(client: Client) -> None:
    part_a = str(OUTPUT / "block_a.sldprt")
    opened = await client.call("open_document", path=part_a)
    check("open part for drawing", opened["ok"], "")
    result = await client.call("new_drawing", model=part_a)
    check("new drawing", result["ok"], "")
    sheet = result.get("data", {}).get("sheet", {})
    check(
        "new drawing carries an A3 standard frame",
        sheet.get("paper_size") == "A3"
        and bool(sheet.get("format"))
        and sheet.get("template_code") == 8
        and sheet.get("size_mm") == [420.0, 297.0],
        json.dumps(sheet),
    )
    check(
        "new drawing uses millimetre units",
        result.get("data", {}).get("units", {}).get("metric") is True,
        json.dumps(result.get("data", {}).get("units")),
    )
    result = await client.call(
        "drawing_insert_standard_views", model_reference=part_a, configuration="Default"
    )
    check("insert standard views", result["ok"], json.dumps(result.get("data")))
    views = await client.call("list_drawing_views")
    count = views.get("data", {}).get("count", 0)
    check("drawing has views", views["ok"] and count >= 3, f"{count} views")
    standard = {
        item.get("orientation"): item
        for item in views.get("data", {}).get("views", [])
        if item.get("orientation") in {"front", "top", "right"}
    }
    check(
        "first-angle standard views are placed on the correct sides",
        {"front", "top", "right"} <= set(standard)
        and standard["top"]["position_mm"][1] < standard["front"]["position_mm"][1]
        and standard["right"]["position_mm"][0]
        < standard["front"]["position_mm"][0],
        json.dumps(standard),
    )
    exported = await client.call(
        "export_document", path=str(OUTPUT / "drawing.pdf")
    )
    check("export drawing pdf", exported["ok"], "")
    await client.call("close_document", save=False)
    await close_if_active(client, part_a)


async def test_drawing_annotations(client: Client) -> None:
    part = str(OUTPUT / "dim_block.sldprt")
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    listing = await client.call("list_sketch_segments")
    segments = listing["data"]["segments"]
    horizontal = next(
        s["index"] for s in segments
        if s.get("type") == "line" and abs(s.get("length_mm", 0) - 100) < 0.01
    )
    vertical = next(
        s["index"] for s in segments
        if s.get("type") == "line" and abs(s.get("length_mm", 0) - 60) < 0.01
    )
    await client.call(
        "sketch_add_dimension",
        segment_indices=[horizontal], value_mm=100, placement_mm=[50, -10],
    )
    await client.call(
        "sketch_add_dimension",
        segment_indices=[vertical], value_mm=60, placement_mm=[-10, 30],
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Body")
    await client.call("save_document", path=part)
    await client.call("close_document", save=False)

    opened = await client.call("open_document", path=part)
    check("open dimensioned part", opened["ok"], "")
    result = await client.call("new_drawing", model=part)
    check("new dimensioned drawing", result["ok"], "")
    result = await client.call(
        "drawing_insert_standard_views", model_reference=part, configuration="Default"
    )
    check("views for annotation", result["ok"], json.dumps(result.get("data")))

    result = await client.call("drawing_auto_dimension")
    check(
        "auto dimension added",
        result["ok"] and result["data"]["dimensions_added"] > 0,
        json.dumps(result.get("data")),
    )
    arranged = result.get("data", {}).get("arranged", {})
    check(
        "auto dimensions re-spaced into rows",
        arranged.get("linear_dimensions", 0) > 0 and arranged.get("moved", 0) > 0,
        json.dumps(arranged),
    )
    annotations = await client.call("list_drawing_annotations")
    dimensions = sum(
        1
        for view in annotations["data"]["views"]
        for item in view["annotations"]
        if item["type"] == "dimension"
    )
    check("dimension read-back", dimensions > 0, f"{dimensions} dimensions")

    result = await client.call(
        "drawing_add_note",
        text="MCP ACCEPTANCE NOTE",
        x_mm=230,
        y_mm=40,
        height_mm=5,
    )
    check("note added", result["ok"], json.dumps(result.get("data")))
    annotations = await client.call("list_drawing_annotations")
    notes = [
        item.get("text")
        for view in annotations["data"]["views"]
        for item in view["annotations"]
        if item["type"] == "note"
    ]
    check("note text read-back", "MCP ACCEPTANCE NOTE" in notes, json.dumps(notes))

    for name, value in (
        ("Title", "ISO ACCEPTANCE PART"),
        ("DrawingNumber", "ISO-ACCEPT-001"),
        ("Revision", "A"),
    ):
        result = await client.call("drawing_set_property", name=name, value=value)
        check(
            f"ISO property {name} read-back",
            result["ok"] and result.get("data", {}).get("value") == value,
            json.dumps(result.get("data")),
        )

    manifest = await client.call("drawing_manifest")
    check(
        "ISO drawing manifest collected",
        manifest["ok"]
        and manifest.get("data", {}).get("profile") == "iso_metric"
        and len(manifest.get("data", {}).get("views", [])) >= 3
        and manifest.get("data", {}).get("scope", {}).get("sheet") == "Sheet1",
        json.dumps(
            {
                "views": len(manifest.get("data", {}).get("views", [])),
                "scope": manifest.get("data", {}).get("scope"),
            }
        ),
    )
    validated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    validation = validated.get("data", {}).get("validation", {})
    check(
        "ISO drawing validation passes",
        validated["ok"] and validation.get("valid") is True,
        json.dumps(validation),
    )

    exported = await client.call(
        "export_document", path=str(OUTPUT / "annotated.pdf")
    )
    check("export annotated pdf", exported["ok"], "")
    verified = await client.call(
        "verify_export", path=str(OUTPUT / "annotated.pdf")
    )
    check(
        "pdf verified",
        verified["ok"] and verified["data"]["details"]["page_count"] >= 1,
        json.dumps(verified.get("data", {}).get("details")),
    )

    exported = await client.call(
        "export_document", path=str(OUTPUT / "annotated.dxf")
    )
    check("export annotated dxf", exported["ok"], "")
    verified = await client.call(
        "verify_export", path=str(OUTPUT / "annotated.dxf")
    )
    details = verified.get("data", {}).get("details", {})
    check(
        "dxf verified",
        verified["ok"] and details.get("entities", 0) > 0,
        json.dumps(details),
    )

    # A framed drawing exports the whole sheet, so the DXF extents track the
    # frame rather than the bare view outlines.
    sheets = await client.call("list_drawing_sheets")
    sheet_size = sheets.get("data", {}).get("size_mm", [0, 0])
    extents = details.get("extents_mm")
    if extents and sheet_size:
        within = (
            extents["min"][0] >= -0.01
            and extents["min"][1] >= -0.01
            and extents["max"][0] <= sheet_size[0] + 0.5
            and extents["max"][1] <= sheet_size[1] + 0.5
            and extents["size_mm"][0] >= 0.9 * sheet_size[0]
            and extents["size_mm"][1] >= 0.9 * sheet_size[1]
        )
        check(
            "dxf extents cover the framed sheet",
            within,
            f"dxf={extents} sheet={sheet_size}",
        )
    else:
        check("dxf extents cover the framed sheet", False, "missing extents/sheet")

    source = str(OUTPUT / "annotated.slddrw")
    saved = await client.call("save_document", path=source)
    check("save validated ISO drawing", saved["ok"], json.dumps(saved.get("data")))
    await client.call("close_document", save=False)
    reopened = await client.call("open_document", path=source)
    check("reopen validated ISO drawing", reopened["ok"], "")
    revalidated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    check(
        "ISO validation survives save and reopen",
        revalidated.get("ok")
        and revalidated.get("data", {}).get("validation", {}).get("valid") is True,
        json.dumps(revalidated.get("data", {}).get("validation")),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, part)


async def build_plate_with_hole(client: Client, path: str) -> dict:
    """80 x 40 x 10 plate with a 10 mm through hole; returns the hole face."""
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=80, y2_mm=40)
    await client.call("exit_sketch")
    extruded = await client.call("boss_extrude", depth_mm=10, name="Plate")
    assert extruded["ok"], extruded
    faces = await client.call("list_faces", surface_type="plane", normal="+z")
    assert faces["ok"] and faces["data"]["count"] == 1, faces
    face_index = faces["data"]["faces"][0]["index"]
    hole = await client.call(
        "simple_hole",
        diameter_mm=10,
        face_index=face_index,
        x_mm=40,
        y_mm=20,
        end_condition="through_all",
        name="Hole",
    )
    assert hole["ok"], hole
    saved = await client.call("save_document", path=path)
    assert saved["ok"], saved
    await client.call("close_document", save=False)
    return hole


async def test_drawing_tools(client: Client) -> None:
    plate = str(OUTPUT / "plate_hole.sldprt")
    await build_plate_with_hole(client, plate)
    opened = await client.call("open_document", path=plate)
    check("open holed plate", opened["ok"], "")

    result = await client.call("new_drawing", model=plate)
    check("new drawing for view tools", result["ok"], "")
    # Insert one master; projected companions must be created before a second
    # sheet is added and must name this same master explicitly.
    result = await client.call(
        "drawing_insert_view", view="front", x_mm=120, y_mm=160,
        model_reference=plate, configuration="Default"
    )
    check("single front view", result["ok"], json.dumps(result.get("data")))

    sheets = await client.call("list_drawing_sheets")
    data = sheets.get("data", {})
    size = data.get("size_mm", [0, 0])
    # new_drawing defaults to a framed A3 sheet (ISO).
    check(
        "sheet size matches the framed A3 default (420 x 297)",
        sheets["ok"]
        and abs(size[0] - 420.0) < 0.1
        and abs(size[1] - 297.0) < 0.1,
        json.dumps({"size_mm": size, "paper": data.get("paper_size"), "scale": data.get("scale")}),
    )

    views = await client.call("list_drawing_views")
    model_views = [v for v in views["data"]["views"] if v.get("type") != "sheet"]
    front = model_views[0]
    front_name = front["name"]
    # SOLIDWORKS may auto-scale a new view to suit the sheet, so read the
    # created scale back instead of assuming 1:1.
    base_scale = front["scale"]
    width_at_base = front["outline_mm"]["max"][0] - front["outline_mm"]["min"][0]
    check(
        "view listing carries type/position/scale",
        front.get("type") not in (None, "sheet", "unknown")
        and abs(front["position_mm"][0] - 120) < 0.01
        and base_scale > 0,
        json.dumps({k: front.get(k) for k in ("type", "position_mm", "scale")}),
    )
    check(
        "view keeps the explicitly requested model reference",
        str(front.get("model_reference", "")).casefold() == plate.casefold(),
        json.dumps({"requested": plate, "view": front.get("model_reference")}),
    )

    mode = await client.call(
        "drawing_set_view", name=front_name, display_mode="hidden_lines_grayed"
    )
    check(
        "display mode uses the measured swDisplayMode_e read-back",
        mode.get("ok")
        and mode.get("data", {}).get("view", {}).get("display_mode")
        == "hidden_lines_grayed",
        json.dumps(mode.get("data", {}).get("view", {})),
    )

    result = await client.call("drawing_activate_view", name=front_name)
    check(
        "activate view round-trips",
        result["ok"] and result["data"]["active_view"] == front_name,
        json.dumps(result.get("data")),
    )

    result = await client.call("drawing_set_view", name=front_name, scale=0.5)
    width_at_half = (
        result["data"]["view"]["outline_mm"]["max"][0]
        - result["data"]["view"]["outline_mm"]["min"][0]
    )
    # The outline is the 80 mm of geometry at the view scale plus a fixed
    # ~8.64 mm margin that does not scale.
    padding = width_at_base - 80.0 * base_scale
    check(
        "half scale halves the geometry in the outline",
        result["ok"] and abs(width_at_half - (80 * 0.5 + padding)) < 0.5,
        f"base {base_scale:g}:1 width {width_at_base:.2f}, "
        f"1:2 width {width_at_half:.2f}, padding {padding:.2f}",
    )

    # First-angle places the right-side view to the left of the front master.
    projection = await client.call(
        "drawing_insert_projected_view",
        parent_view=front_name,
        direction="left",
        offset_mm=80,
    )
    projection_data = projection.get("data", {})
    projected_view = projection_data.get("view", {})
    check(
        "first-angle right-side projection is placed left of master",
        projection["ok"]
        and projection_data.get("parent") == front_name
        and projected_view.get("type") == "projected"
        and projected_view.get("orientation") in (None, "right")
        and str(projected_view.get("model_reference", "")).casefold()
        == plate.casefold()
        and str(projected_view.get("configuration", "")).casefold()
        == "default"
        and abs(projected_view.get("position_mm", [0, 0])[0] - 40) < 0.01
        and abs(projected_view.get("position_mm", [0, 0])[1] - 160) < 0.01,
        json.dumps(projection_data),
    )

    # The top view is a second projection from the same master, below it in
    # first-angle projection. This also guards multiple projections per sheet.
    top_projection = await client.call(
        "drawing_insert_projected_view",
        parent_view=front_name,
        direction="down",
        offset_mm=80,
    )
    top_projection_data = top_projection.get("data", {})
    top_view = top_projection_data.get("view", {})
    check(
        "top projection is below and derived from the same master",
        top_projection["ok"]
        and top_projection_data.get("parent") == front_name
        and top_view.get("type") == "projected"
        and top_view.get("orientation") in (None, "top")
        and str(top_view.get("model_reference", "")).casefold() == plate.casefold()
        and str(top_view.get("configuration", "")).casefold() == "default"
        and abs(top_view.get("position_mm", [0, 0])[0] - 120) < 0.01
        and abs(top_view.get("position_mm", [0, 0])[1] - 80) < 0.01,
        json.dumps(top_projection_data),
    )

    projected_views = await client.call("list_drawing_views")
    projected_model_views = [
        view
        for view in projected_views.get("data", {}).get("views", [])
        if view.get("type") == "projected"
    ]
    check(
        "one master now has two projected companions",
        projected_views.get("ok") and len(projected_model_views) == 2,
        json.dumps(projected_model_views),
    )

    front_x, front_y = front["position_mm"]
    result = await client.call(
        "drawing_insert_section_view",
        parent_view=front_name,
        x1_mm=front_x - 30,
        y1_mm=front_y,
        x2_mm=front_x + 30,
        y2_mm=front_y,
        place_x_mm=front_x,
        place_y_mm=front_y + 80,
        label="B",
    )
    check(
        "section view created from a cutting line and cut (verified edges)",
        result["ok"]
        and result["data"]["view"]["type"] == "section"
        and "B" in result["data"]["view"]["name"]
        and result["data"].get("cut_edges", 0) >= 1,
        json.dumps(result.get("data")),
    )

    result = await client.call(
        "drawing_insert_detail_view",
        parent_view=front_name,
        center_x_mm=front_x,
        center_y_mm=front_y,
        radius_mm=10,
        place_x_mm=front_x + 130,
        place_y_mm=front_y,
        label="J",
        scale_numerator=1,
        scale_denominator=1,
    )
    check(
        "detail view created at 1:1",
        result["ok"]
        and result["data"]["view"]["type"] == "detail"
        and abs(result["data"]["view"]["scale"] - 1.0) < 1e-6,
        json.dumps(result.get("data")),
    )

    marks = await client.call("drawing_insert_center_marks", view_name=front_name)
    check(
        "center marks added (one hole -> one mark)",
        marks["ok"] and marks["data"]["marks_added"] >= 1,
        json.dumps(marks.get("data")),
    )
    lines = await client.call("drawing_insert_centerlines", view_name=front_name)
    check(
        "center annotation added for the hole axis",
        lines["ok"] and lines["data"]["center_annotations_added"] >= 1,
        json.dumps(lines.get("data")),
    )

    result = await client.call(
        "drawing_add_sheet", name="Details", paper_size="A4", first_angle=True
    )
    check("add A4 sheet", result["ok"], json.dumps(result.get("data")))
    sheets = await client.call("list_drawing_sheets")
    data = sheets.get("data", {})
    size = data.get("size_mm", [0, 0])
    check(
        "A4 sheet is 297 x 210 and active",
        sheets["ok"]
        and data.get("count") == 2
        and abs(size[0] - 297.0) < 0.1
        and abs(size[1] - 210.0) < 0.1
        and data.get("active_sheet") == "Details",
        json.dumps({"active": data.get("active_sheet"), "size_mm": size}),
    )
    result = await client.call("drawing_activate_sheet", name="Sheet1")
    check(
        "activate sheet round-trips",
        result["ok"] and result["data"]["active_sheet"] == "Sheet1",
        json.dumps(result.get("data")),
    )

    sketch_result = await client.call("drawing_create_sketch", view_name=front_name)
    check(
        "drawing sketch opens",
        sketch_result["ok"] and sketch_result["data"]["active_sketch"] is True,
        json.dumps(sketch_result.get("data")),
    )
    # Drawing view sketch coordinates are sheet millimetres; draw at the
    # view's own centre so the geometry is inside the view.
    await client.call(
        "sketch_line", x1_mm=front_x, y1_mm=front_y, x2_mm=front_x + 5, y2_mm=front_y + 5
    )
    segments = await client.call("list_sketch_segments")
    check(
        "sketch tools draw inside the view",
        segments["ok"] and segments["data"]["segment_count"] == 1,
        json.dumps(segments.get("data")),
    )
    closed = await client.call("exit_sketch")
    check(
        "exit_sketch reports the measured drawing limitation",
        closed["ok"] and closed["data"].get("view_sketch") is True,
        json.dumps(closed.get("data")),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, plate)


async def test_appearance_and_filters(client: Client) -> None:
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=10, y2_mm=20)
    await client.call("exit_sketch")
    extruded = await client.call("boss_extrude", depth_mm=30, name="Block")
    check("appearance block built", extruded["ok"], json.dumps(extruded.get("data")))

    edges = await client.call(
        "list_edges", curve_type="line", min_length_mm=20
    )
    lengths = [item.get("length_mm", 0) for item in edges.get("data", {}).get("edges", [])]
    # 4 x 30 mm verticals + 4 x 20 mm horizontals; the 4 x 10 mm edges drop out.
    check(
        "line/length filter keeps the global indices",
        edges["ok"]
        and edges["data"]["count"] == 8
        and min(lengths, default=0) >= 20
        and max(item["index"] for item in edges["data"]["edges"]) >= 4,
        json.dumps({"count": edges["data"].get("count"), "lengths": lengths}),
    )

    faces = await client.call("list_faces", surface_type="plane", normal="+z")
    details = faces.get("data", {}).get("faces", [])
    check(
        "plane/normal filter finds the 200 mm^2 top face",
        faces["ok"]
        and faces["data"]["count"] == 1
        and abs(details[0]["area_mm2"] - 200.0) < 0.01,
        json.dumps(details),
    )

    result = await client.call("set_appearance", red=10, green=200, blue=30)
    applied = result.get("data", {}).get("applied_rgb", [0, 0, 0])
    check(
        "model appearance read-back matches within 1/255",
        result["ok"]
        and abs(applied[0] - 10 / 255) <= 1 / 255 + 1e-6
        and abs(applied[1] - 200 / 255) <= 1 / 255 + 1e-6
        and abs(applied[2] - 30 / 255) <= 1 / 255 + 1e-6,
        json.dumps(result.get("data")),
    )

    face_index = details[0]["index"]
    result = await client.call(
        "set_appearance", red=255, green=0, blue=0, face_indices=[face_index]
    )
    face_rgb = result.get("data", {}).get("faces", [{}])[0].get("rgb", [0, 0, 0])
    check(
        "face appearance read-back is red",
        result["ok"]
        and result["data"].get("scope") == "faces"
        and abs(face_rgb[0] - 1.0) < 1e-6
        and face_rgb[1] < 1e-6,
        json.dumps(result.get("data")),
    )
    await client.call("close_document", save=False)


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
    tests = {
        "assembly": test_assembly,
        "drawing": test_drawing,
        "annotations": test_drawing_annotations,
        "drawing_tools": test_drawing_tools,
        "appearance": test_appearance_and_filters,
    }
    wanted = [name for name in sys.argv[1:] if not name.startswith("-")]
    unknown = [name for name in wanted if name not in tests]
    if unknown:
        print(f"unknown test(s): {unknown}; choose from {sorted(tests)}")
        return 2
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = Client(session)
            for name, test in tests.items():
                if wanted and name not in wanted:
                    continue
                await test(client)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
