#!/usr/bin/env python
"""Live acceptance for the ISO annotation suite: tolerances, datums, GD&T,
surface finish, hole callouts and release tables."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "acceptance_iso"
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
    """Close the document at ``path`` only when it is the active one."""
    active = await client.call("get_active_document_info")
    document = active.get("data", {}).get("document", {}) or active.get("data", {})
    current = str((document or {}).get("path") or "")
    if current and current.lower() == path.lower():
        await client.call("close_document", save=False)


async def build_block(
    client: Client, path: str, width: float, height: float, depth: float
) -> None:
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


async def build_plate_with_hole(client: Client, path: str) -> None:
    await build_block(client, path, 80, 40, 10)
    await client.call("open_document", path=path)
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


async def test_tolerances(client: Client) -> None:
    block = str(OUTPUT / "iso_block.sldprt")
    await build_block(client, block, 100, 60, 10)
    await client.call("open_document", path=block)

    result = await client.call("new_drawing", model=block)
    check("new drawing for tolerance tooling", result["ok"], "")
    views = await client.call(
        "drawing_insert_standard_views", model_reference=block, configuration="Default"
    )
    check("standard view set inserted", views["ok"], "")
    data = views.get("data", {})
    layout = data.get("layout", {})
    gaps = layout.get("gaps_mm", {})
    check(
        "views share the sheet scale",
        data.get("scale") == 1.0,
        json.dumps({"scale": data.get("scale")}),
    )
    check(
        "standard views are laid out with the requested gap",
        abs(gaps.get("top_below_front", 0) - 20) <= 0.5
        and abs(gaps.get("right_left_of_front", 0) - 20) <= 0.5,
        json.dumps(gaps),
    )
    front = layout.get("front", {}).get("outline_mm", {})
    top = layout.get("top", {}).get("outline_mm", {})
    right = layout.get("right", {}).get("outline_mm", {})
    check(
        "first-angle layout keeps top below and right to the left",
        top.get("max", [0, 0])[1] < front.get("min", [0, 0])[1]
        and right.get("max", [0, 0])[0] < front.get("min", [0, 0])[0],
        json.dumps({"front": front, "top": top, "right": right}),
    )

    result = await client.call("drawing_auto_dimension")
    check(
        "auto dimension for tolerance editing",
        result["ok"] and result["data"]["dimensions_added"] > 0,
        json.dumps(result.get("data")),
    )

    listing = await client.call("list_drawing_dimensions")
    views_data = listing.get("data", {}).get("views", [])
    dimensions = [d for view in views_data for d in view.get("dimensions", [])]
    check(
        "dimension listing carries values and indices",
        listing["ok"]
        and any(d.get("value") in (100.0, 60.0) for d in dimensions),
        json.dumps(dimensions),
    )
    tolerance_dim = next(
        (d for d in dimensions if d.get("value") in (100.0, 60.0)), None
    )
    if tolerance_dim is None:
        check("linear dimension found for tolerance", False, "none")
        await client.call("close_document", save=False)
        return

    result = await client.call(
        "drawing_set_dimension_tolerance",
        index=tolerance_dim["index"],
        tolerance="symmetric",
        value_mm=0.1,
    )
    applied = result.get("data", {}).get("tolerance", {})
    check(
        "symmetric tolerance applied and read back",
        result["ok"]
        and applied.get("type") == "symmetric"
        and abs(applied.get("min", 0) - 0.1) < 1e-6
        and abs(applied.get("max", 0) - 0.1) < 1e-6,
        json.dumps(result.get("data")),
    )

    result = await client.call(
        "drawing_set_dimension_tolerance",
        index=tolerance_dim["index"],
        tolerance="bilateral",
        minus_mm=0.05,
        plus_mm=0.1,
    )
    applied = result.get("data", {}).get("tolerance", {})
    check(
        "bilateral tolerance applied and read back",
        result["ok"]
        and applied.get("type") == "bilateral"
        and abs(applied.get("min", 0) + 0.05) < 1e-6
        and abs(applied.get("max", 0) - 0.1) < 1e-6,
        json.dumps(result.get("data")),
    )

    result = await client.call(
        "drawing_set_dimension_tolerance",
        index=tolerance_dim["index"],
        tolerance="basic",
    )
    applied = result.get("data", {}).get("tolerance", {})
    check(
        "basic (boxed) tolerance applied",
        result["ok"] and applied.get("type") == "basic",
        json.dumps(result.get("data")),
    )

    result = await client.call(
        "drawing_set_dimension_tolerance",
        index=tolerance_dim["index"],
        tolerance="none",
    )
    applied = result.get("data", {}).get("tolerance", {})
    check(
        "tolerance cleared",
        result["ok"] and applied.get("type") == "none",
        json.dumps(result.get("data")),
    )

    # Fit tolerances need a diameter dimension; build a plate with a hole and
    # let DimXpert dimension it. Close the first drawing/part first so the
    # reused names and document states stay unambiguous.
    await client.call("close_document", save=False)
    await close_if_active(client, block)
    plate = str(OUTPUT / "iso_plate.sldprt")
    await build_plate_with_hole(client, plate)
    await client.call("open_document", path=plate)
    result = await client.call("new_drawing", model=plate)
    check("new drawing for fit tolerance", result["ok"], "")
    await client.call(
        "drawing_insert_standard_views", model_reference=plate, configuration="Default"
    )
    result = await client.call("drawing_auto_dimension")
    check("auto dimension on holed plate", result["ok"], json.dumps(result.get("data")))
    listing = await client.call("list_drawing_dimensions")
    dimensions = [
        d
        for view in listing.get("data", {}).get("views", [])
        for d in view.get("dimensions", [])
    ]
    diameter = next((d for d in dimensions if d.get("kind") == "diameter"), None)
    if diameter is None:
        check(
            "diameter dimension available for fit",
            False,
            json.dumps([d.get("kind") for d in dimensions]),
        )
    else:
        result = await client.call(
            "drawing_set_dimension_tolerance",
            index=diameter["index"],
            tolerance="fit",
            hole_fit="H7",
            shaft_fit="g6",
        )
        applied = result.get("data", {}).get("tolerance", {})
        check(
            "ISO fit applied and read back",
            result["ok"]
            and applied.get("type") == "fit"
            and applied.get("hole_fit") == "H7"
            and applied.get("shaft_fit") == "g6",
            json.dumps(result.get("data")),
        )

    # General tolerance table: available for parts/assemblies on this build.
    # Either outcome is valid; a drawing falls back to the standard note.
    result = await client.call("drawing_insert_general_tolerance_table")
    if result["ok"]:
        check(
            "general tolerance table inserted on the drawing",
            True,
            json.dumps(result.get("data")),
        )
    else:
        code = result.get("error", {}).get("code")
        check(
            "general tolerance table refuses drawings with a clear message",
            code == "COM_ERROR"
            and "2768" in result.get("error", {}).get("hint", ""),
            json.dumps(result.get("error")),
        )
        note = await client.call(
            "drawing_add_note",
            text="REVIEW ONLY: GENERAL TOLERANCES UNCONFIRMED",
            x_mm=20,
            y_mm=15,
        )
        check("general tolerance note added", note["ok"], json.dumps(note.get("data")))

    # Property values for the release gate.
    for name, value in (
        ("Title", "ISO TOLERANCE PART"),
        ("DrawingNumber", "ISO-ANN-001"),
        ("Revision", "A"),
    ):
        await client.call("drawing_set_property", name=name, value=value)

    validated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    validation = validated.get("data", {}).get("validation", {})
    check(
        "ISO validation passes after the phase 1 fixes",
        validated["ok"] and validation.get("valid") is True,
        json.dumps(validation.get("errors")),
    )
    check(
        "validation counts the value-carrying dimensions",
        validation.get("readable_dimensions", 0) >= 1,
        json.dumps({"readable": validation.get("readable_dimensions")}),
    )

    exported = await client.call(
        "export_document", path=str(OUTPUT / "iso_tolerances.pdf")
    )
    check("export tolerance drawing pdf", exported["ok"], "")
    verified = await client.call(
        "verify_export", path=str(OUTPUT / "iso_tolerances.pdf")
    )
    check(
        "tolerance pdf verified",
        verified["ok"] and verified["data"]["details"]["page_count"] >= 1,
        json.dumps(verified.get("data", {}).get("details")),
    )

    source = str(OUTPUT / "iso_tolerances.slddrw")
    saved = await client.call("save_document", path=source)
    check("save tolerance drawing", saved["ok"], "")
    await client.call("close_document", save=False)
    reopened = await client.call("open_document", path=source)
    check("reopen tolerance drawing", reopened["ok"], "")
    revalidated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=["Title", "DrawingNumber", "Revision"],
        limitations_acknowledged=True,
    )
    validation = revalidated.get("data", {}).get("validation", {})
    check(
        "tolerance drawing validates after save and reopen",
        revalidated["ok"] and validation.get("valid") is True,
        json.dumps(validation.get("errors")),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, plate)


async def test_datums_gdt(client: Client) -> None:
    part = str(OUTPUT / "iso_gdt.sldprt")
    await build_block(client, part, 100, 60, 10)
    await client.call("open_document", path=part)
    result = await client.call("new_drawing", model=part)
    check("new drawing for datums and GD&T", result["ok"], "")
    views = await client.call(
        "drawing_insert_standard_views", model_reference=part, configuration="Default"
    )
    check("standard views for datums and GD&T", views["ok"], "")
    view_name = (views.get("data", {}).get("views") or {}).get("front")

    edges = await client.call("list_drawing_view_edges", view=view_name)
    edge_list = [
        edge
        for view in edges.get("data", {}).get("views", [])
        for edge in view.get("edges", [])
    ]
    line = next(
        (
            edge
            for edge in edge_list
            if edge.get("kind") == "line" and edge.get("length_mm", 0) > 50
        ),
        None,
    )
    check(
        "view edge listing finds a long line edge",
        edges["ok"] and line is not None,
        json.dumps(edge_list[:3]),
    )
    if line is None:
        await client.call("close_document", save=False)
        await close_if_active(client, part)
        return

    datum = await client.call(
        "drawing_insert_datum", view=view_name, edge_index=line["index"], label="A"
    )
    check(
        "datum A attached and read back",
        datum["ok"] and datum.get("data", {}).get("label") == "A",
        json.dumps(datum.get("data")),
    )
    gtol = await client.call(
        "drawing_insert_gtol",
        view=view_name,
        edge_index=line["index"],
        symbol="perpendicularity",
        tolerance="0.2",
        diameter=True,
        datums=["A"],
    )
    frame = gtol.get("data", {})
    check(
        "GD&T frame inserted and read back",
        gtol["ok"]
        and frame.get("frame_values", [])[:3] == ["0.2", "", "A"]
        and frame.get("frame_symbols", [None])[0] == 21,
        json.dumps(frame),
    )

    annotations = await client.call("list_drawing_annotations", view=view_name)
    entries = [
        item
        for view in annotations.get("data", {}).get("views", [])
        for item in view.get("annotations", [])
    ]
    datum_entry = next(
        (item for item in entries if item.get("type") == "datum_tag"), None
    )
    gtol_entry = next(
        (item for item in entries if item.get("type") == "geometric_tolerance"),
        None,
    )
    check(
        "annotation inventory reports the datum label",
        datum_entry is not None and datum_entry.get("label") == "A",
        json.dumps(datum_entry),
    )
    check(
        "annotation inventory reports the GD&T frame",
        gtol_entry is not None
        and gtol_entry.get("frame_values", [])[:3] == ["0.2", "", "A"],
        json.dumps(gtol_entry),
    )

    validated = await client.call(
        "validate_iso_drawing",
        minimum_model_views=3,
        required_properties=[],
        require_dimensions=False,
        limitations_acknowledged=True,
    )
    validation = validated.get("data", {}).get("validation", {})
    check(
        "validation tolerates semantic annotations",
        validated["ok"] and validation.get("valid") is True,
        json.dumps(validation.get("errors")),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, part)


async def test_surface_finish(client: Client) -> None:
    part = str(OUTPUT / "iso_sf.sldprt")
    await build_block(client, part, 100, 60, 10)
    await client.call("open_document", path=part)
    result = await client.call("new_drawing", model=part)
    check("new drawing for surface finish", result["ok"], "")
    views = await client.call(
        "drawing_insert_standard_views", model_reference=part, configuration="Default"
    )
    view_name = (views.get("data", {}).get("views") or {}).get("front")
    edges = await client.call("list_drawing_view_edges", view=view_name)
    edge_list = [
        edge
        for view in edges.get("data", {}).get("views", [])
        for edge in view.get("edges", [])
    ]
    line = next(
        (
            edge
            for edge in edge_list
            if edge.get("kind") == "line" and edge.get("length_mm", 0) > 50
        ),
        None,
    )
    if line is None:
        check("surface finish edge found", False, json.dumps(edge_list[:3]))
        await client.call("close_document", save=False)
        await close_if_active(client, part)
        return

    symbol = await client.call(
        "drawing_insert_surface_finish",
        view=view_name,
        edge_index=line["index"],
        roughness="1.6",
    )
    check(
        "surface finish inserted with roughness read-back",
        symbol["ok"] and "1.6" in str(symbol.get("data", {}).get("roughness", "")),
        json.dumps(symbol.get("data")),
    )
    annotations = await client.call("list_drawing_annotations", view=view_name)
    finishes = [
        item
        for view in annotations.get("data", {}).get("views", [])
        for item in view.get("annotations", [])
        if item.get("type") == "surface_finish"
    ]
    check(
        "annotation inventory reports the surface roughness",
        any("1.6" in str(item.get("text", "")) for item in finishes),
        json.dumps(finishes),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, part)


async def test_revision_table(client: Client) -> None:
    part = str(OUTPUT / "iso_revision.sldprt")
    await build_block(client, part, 100, 60, 10)
    await client.call("open_document", path=part)
    result = await client.call("new_drawing", model=part)
    check("new drawing for the revision table", result["ok"], "")
    await client.call(
        "drawing_insert_standard_views", model_reference=part, configuration="Default"
    )

    table = await client.call("drawing_insert_revision_table")
    titles = table.get("data", {}).get("column_titles", [])
    check(
        "revision table inserted with the stock columns",
        table["ok"] and "REV." in titles and "DESCRIPTION" in titles,
        json.dumps(table.get("data")),
    )
    added = await client.call(
        "drawing_add_revision",
        revision="A",
        description="Initial release",
        date="2026-09-26",
    )
    check(
        "revision A added and read back",
        added["ok"] and added.get("data", {}).get("revision") == "A",
        json.dumps(added.get("data")),
    )
    cells = added.get("data", {}).get("cells", {})
    check(
        "revision description cell written",
        cells.get("DESCRIPTION") == "Initial release",
        json.dumps(cells),
    )

    source = str(OUTPUT / "iso_revision.slddrw")
    saved = await client.call("save_document", path=source)
    check("save revision drawing", saved["ok"], "")
    await client.call("close_document", save=False)
    reopened = await client.call("open_document", path=source)
    check("reopen revision drawing", reopened["ok"], "")
    added_b = await client.call("drawing_add_revision", revision="B")
    check(
        "revision table survives save and reopen",
        added_b["ok"] and added_b.get("data", {}).get("revision") == "B",
        json.dumps(added_b.get("data")),
    )
    await client.call("close_document", save=False)
    await close_if_active(client, part)


async def build_assembly(
    client: Client, part_a: str, part_b: str, path: str
) -> None:
    await client.call("new_document", kind="assembly")
    first = await client.call("insert_component", path=part_a, fixed=True)
    assert first["ok"], first
    second = await client.call("insert_component", path=part_b, x_mm=120)
    assert second["ok"], second
    saved = await client.call("save_document", path=path)
    assert saved["ok"], saved
    await client.call("close_document", save=False)


async def test_bom_balloons(client: Client) -> None:
    part_a = str(OUTPUT / "iso_bom_a.sldprt")
    part_b = str(OUTPUT / "iso_bom_b.sldprt")
    assembly = str(OUTPUT / "iso_bom.sldasm")
    await build_block(client, part_a, 50, 30, 10)
    await build_block(client, part_b, 40, 20, 10)
    await build_assembly(client, part_a, part_b, assembly)
    await client.call("open_document", path=assembly)

    result = await client.call("new_drawing", model=assembly)
    check("new assembly drawing", result["ok"], "")
    view = await client.call(
        "drawing_insert_view", view="front", x_mm=200, y_mm=160,
        model_reference=assembly, configuration="Default"
    )
    check("assembly drawing view inserted", view["ok"], json.dumps(view.get("data")))
    view_name = view.get("data", {}).get("name")

    bom = await client.call(
        "drawing_insert_bom_table", view=view_name, bom_type="top_level_only"
    )
    data = bom.get("data", {})
    check(
        "BOM table lists both components",
        bom["ok"] and data.get("rows", 0) >= 3 and len(data.get("items", [])) >= 2,
        json.dumps({"rows": data.get("rows"), "items": data.get("items")}),
    )
    check(
        "BOM resolves the referenced configuration",
        data.get("configuration") == "Default",
        json.dumps({"configuration": data.get("configuration")}),
    )

    balloons = await client.call("drawing_insert_balloons", view=view_name)
    balloon_data = balloons.get("data", {})
    check(
        "auto-balloons inserted and read back",
        balloons["ok"] and balloon_data.get("count", 0) >= 2,
        json.dumps(balloon_data),
    )
    check(
        "balloon texts carry item numbers",
        any(
            str(text).strip().isdigit()
            for text in balloon_data.get("balloons", [])
        ),
        json.dumps(balloon_data.get("balloons")),
    )

    await client.call("close_document", save=False)
    await close_if_active(client, assembly)


async def test_hole_callout(client: Client) -> None:
    part = str(OUTPUT / "iso_callout.sldprt")
    await build_block(client, part, 80, 40, 10)
    await client.call("open_document", path=part)
    faces = await client.call("list_faces", surface_type="plane", normal="+z")
    face_index = faces["data"]["faces"][0]["index"]
    await client.call(
        "simple_hole",
        diameter_mm=10,
        face_index=face_index,
        x_mm=40,
        y_mm=20,
        end_condition="through_all",
        name="Hole",
    )
    result = await client.call("new_drawing", model=part)
    check("new drawing for the hole callout", result["ok"], "")
    views = await client.call(
        "drawing_insert_standard_views", model_reference=part, configuration="Default"
    )
    view_name = (views.get("data", {}).get("views") or {}).get("front")
    edges = await client.call("list_drawing_view_edges", view=view_name)
    edge_list = [
        edge
        for view in edges.get("data", {}).get("views", [])
        for edge in view.get("edges", [])
    ]
    circle = next(
        (edge for edge in edge_list if edge.get("kind") == "circle"), None
    )
    check(
        "circular hole edge found for the callout",
        circle is not None,
        json.dumps(edge_list),
    )
    if circle is None:
        await client.call("close_document", save=False)
        await close_if_active(client, part)
        return
    callout = await client.call(
        "drawing_insert_hole_callout", view=view_name, edge_index=circle["index"]
    )
    if callout["ok"]:
        check(
            "hole callout inserted on a callout-capable hole",
            bool(callout.get("data", {}).get("is_hole_callout")),
            json.dumps(callout.get("data")),
        )
    else:
        error = callout.get("error", {})
        check(
            "hole callout refuses non-wizard holes with a clear hint",
            error.get("code") == "COM_ERROR" and "Hole Wizard" in error.get("hint", ""),
            json.dumps(error),
        )
    await client.call("close_document", save=False)
    await close_if_active(client, part)


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
        "tolerances": test_tolerances,
        "datums_gdt": test_datums_gdt,
        "surface_finish": test_surface_finish,
        "revision_table": test_revision_table,
        "bom_balloons": test_bom_balloons,
        "hole_callout": test_hole_callout,
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
