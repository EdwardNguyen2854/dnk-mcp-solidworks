#!/usr/bin/env python
"""Live acceptance for the drawing edit actuators.

Covers the Tier-1 gaps from the Cline review:

- ``drawing_delete_view``
- ``drawing_move_annotation`` / ``drawing_delete_annotation`` /
  ``drawing_set_annotation_text``
- ``drawing_add_dimension`` on picked view edges

Hand calculations: the plate has two Ø10 holes with centres 60 mm apart, so
the centre-distance dimension must read 60.00 and the diameter 10.00; the
dimension/note positions are checked against the requested sheet millimetres.

Needs a running SOLIDWORKS session. The script creates and closes its own
part and drawing (discards, never saves over the user's work).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "acceptance_drawing_edit"
PART = OUTPUT / "plate.sldprt"
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

    async def data(self, tool: str, **arguments) -> dict:
        envelope = await self.call(tool, **arguments)
        return envelope.get("data", {}) if envelope.get("ok") else {}


def close_enough(first, second, tolerance: float = 1e-3) -> bool:
    try:
        return abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


async def close_active(client: Client, path: Path) -> None:
    active = await client.data("get_active_document_info")
    document = active.get("document", active)
    current = str(document.get("path") or "")
    if current and current.lower() == str(path).lower():
        await client.call("close_document", save=False)


async def find_annotation(client: Client, text: str):
    listed = await client.data("list_drawing_annotations")
    for view in listed.get("views", []):
        for annotation in view.get("annotations", []):
            candidate = annotation.get("resolved_text") or annotation.get("text")
            if candidate == text:
                return view["name"], annotation
    return None, None


async def test_drawing_edit(client: Client) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    # --- scratch part: 120 x 80 x 20 plate, two Ø10 holes 60 mm apart ----
    await client.call("new_document", kind="part")
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0.0, y1_mm=0.0, x2_mm=120.0, y2_mm=80.0
    )
    await client.call(
        "sketch_circle", center_x_mm=30.0, center_y_mm=40.0, radius_mm=5.0
    )
    await client.call(
        "sketch_circle", center_x_mm=90.0, center_y_mm=40.0, radius_mm=5.0
    )
    await client.call("exit_sketch")
    extruded = await client.call("boss_extrude", depth_mm=20.0, name="Body")
    check("part extrudes", extruded["ok"])
    mass = await client.data("get_mass_properties")
    expected_volume = 120 * 80 * 20 - 2 * 3.141592653589793 * 5**2 * 20
    check(
        "plate volume matches 120x80x20 minus two holes",
        close_enough(mass.get("volume_mm3"), expected_volume, 1.0),
        f"measured={mass.get('volume_mm3')} expected={expected_volume:.1f}",
    )
    saved = await client.call("save_document", path=str(PART))
    check("part saves", saved["ok"])

    # --- drawing and picked-geometry dimensions ---------------------------
    created = await client.call(
        "new_drawing",
        model=str(PART),
        paper_size="A3",
        scale=1.0,
        first_angle=True,
    )
    check("drawing creates", created["ok"])
    views = await client.data("drawing_insert_standard_views")
    check("standard views insert", bool(views.get("views")))

    listed_views = await client.data("list_drawing_views")
    front = next(
        (
            view
            for view in listed_views.get("views", [])
            if view.get("orientation") == "front"
        ),
        None,
    )
    check("front view found", front is not None)
    if front is None:
        return

    edges_data = await client.data("list_drawing_view_edges", view=front["name"])
    view_edges = next(
        (
            item.get("edges", [])
            for item in edges_data.get("views", [])
            if item.get("name") == front["name"]
        ),
        [],
    )
    circles = [
        (index, edge)
        for index, edge in enumerate(view_edges)
        if edge.get("kind") == "circle"
    ]
    check("two circle edges visible", len(circles) == 2, f"got {len(circles)}")
    if len(circles) != 2:
        return

    def circle_near(x_mm: float):
        for index, edge in circles:
            centre = edge.get("center_mm") or [None, None]
            if centre[0] is not None and close_enough(centre[0], x_mm, 0.5):
                return index
        return None

    left = circle_near(30.0)
    right = circle_near(90.0)
    check("hole edges addressable by centre", left is not None and right is not None)

    distance = await client.call(
        "drawing_add_dimension",
        view=front["name"],
        edge_indices=[left, right],
        placement_mm=[60.0, 12.0],
    )
    distance_data = distance.get("data", {})
    check(
        "two-hole dimension reads 60.00",
        close_enough(distance_data.get("value"), 60.0),
        json.dumps(distance_data),
    )

    diameter = await client.call(
        "drawing_add_dimension",
        view=front["name"],
        edge_indices=[left],
        placement_mm=[15.0, 80.0],
    )
    diameter_data = diameter.get("data", {})
    check(
        "single-hole dimension reads 10.00",
        close_enough(diameter_data.get("value"), 10.0),
        json.dumps(diameter_data),
    )

    # --- dimension text override (prefix), move ---------------------------
    diameter_index = diameter_data.get("index")
    prefixed = await client.call(
        "drawing_set_annotation_text",
        view=front["name"],
        index=diameter_index,
        prefix="2x ",
    )
    check(
        "dimension prefix set",
        prefixed.get("ok") and prefixed.get("data", {}).get("prefix") == "2x ",
        json.dumps(prefixed.get("data", {})),
    )
    re_listed = await client.data("list_drawing_annotations", view=front["name"])
    prefixed_reading = [
        annotation.get("reading")
        for view_item in re_listed.get("views", [])
        for annotation in view_item.get("annotations", [])
        if annotation.get("type") == "dimension"
        and close_enough(annotation.get("value"), 10.0)
    ]
    check(
        "prefix reads back into the annotation listing",
        any(text and text.startswith("2x") for text in prefixed_reading),
        json.dumps(prefixed_reading),
    )

    moved = await client.call(
        "drawing_move_annotation",
        view=front["name"],
        index=diameter_index,
        x_mm=140.0,
        y_mm=25.0,
    )
    moved_to = moved.get("data", {}).get("position_mm") or [None, None]
    check(
        "dimension moves to the requested position",
        close_enough(moved_to[0], 140.0, 0.1) and close_enough(moved_to[1], 25.0, 0.1),
        json.dumps(moved_to),
    )

    # --- note lifecycle ---------------------------------------------------
    await client.call("drawing_add_note", text="EDIT ME", x_mm=180.0, y_mm=230.0)
    note_view, note = await find_annotation(client, "EDIT ME")
    check("note appears in the annotation listing", note is not None and note_view is not None)
    if note is not None:
        note_index = note.get("index")
        edited = await client.call(
            "drawing_set_annotation_text",
            view=note_view,
            index=note_index,
            text="EDITED",
            height_mm=4.0,
        )
        check(
            "note text edited",
            edited.get("ok") and edited.get("data", {}).get("text") == "EDITED",
            json.dumps(edited.get("data", {})),
        )
        note_moved = await client.call(
            "drawing_move_annotation",
            view=note_view,
            index=note_index,
            x_mm=200.0,
            y_mm=210.0,
        )
        check("note moved", note_moved["ok"])
        deleted_note = await client.call(
            "drawing_delete_annotation", view=note_view, index=note_index
        )
        check("note deleted", deleted_note["ok"], json.dumps(deleted_note.get("data", {})))
        _view, gone = await find_annotation(client, "EDITED")
        check("deleted note is gone from the listing", gone is None)

    # --- view deletion ----------------------------------------------------
    inserted = await client.data(
        "drawing_insert_view", view="isometric", x_mm=330.0, y_mm=230.0
    )
    extra_name = inserted.get("name")
    check("extra isometric view inserted", bool(extra_name), str(extra_name))
    if extra_name:
        removed = await client.call("drawing_delete_view", view=extra_name)
        names = await client.data("list_drawing_views")
        remaining = {view["name"] for view in names.get("views", [])}
        check(
            "view deleted",
            removed.get("ok") and extra_name not in remaining,
            json.dumps(removed.get("data", {})),
        )

    sheet_protected = await client.call("drawing_delete_view", view="Sheet1")
    check("sheet view is protected", not sheet_protected["ok"])

    bad_index = await client.call(
        "drawing_add_dimension",
        view=front["name"],
        edge_indices=[999],
        placement_mm=[10.0, 10.0],
    )
    check("out-of-range edge index is refused", not bad_index["ok"])

    # --- PDF export and structural verification ---------------------------
    pdf = OUTPUT / "plate.pdf"
    exported = await client.call("export_document", path=str(pdf))
    check("drawing exports to PDF", exported["ok"], json.dumps(exported.get("data", {}))[:120])
    verified = await client.call("verify_export", path=str(pdf))
    pdf_details = verified.get("data", {}).get("details", {})
    check(
        "PDF verifies as one consistent page",
        verified["ok"]
        and pdf_details.get("page_count") == 1
        and pdf_details.get("page_count_consistent") is True,
        json.dumps(pdf_details),
    )

    await client.call("close_document", save=False)
    await close_active(client, PART)


async def test_checkpoint_transactions(client: Client) -> None:
    """Regression: unsaved checkpoint path and typed rollback reopen."""
    await client.call("new_document", kind="part")
    checkpoint = await client.call("create_checkpoint", label="drawing-edit")
    checkpoint_data = checkpoint.get("data", {})
    check(
        "unsaved document checkpoints as save-a-copy",
        checkpoint["ok"] and checkpoint_data.get("mode") == "save-a-copy",
        json.dumps(checkpoint_data),
    )
    path = checkpoint_data.get("checkpoint")

    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0.0, y1_mm=0.0, x2_mm=20.0, y2_mm=20.0
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=5.0, name="Body")
    before = await client.data("list_features")
    names = [feature.get("name") for feature in before.get("features", [])]
    check("scratch document has the extrusion before rollback", "Body" in names, str(names))

    if path:
        rolled = await client.call("rollback_to_checkpoint", checkpoint=path)
        opened = rolled.get("data", {}).get("opened_document", {})
        check(
            "rollback reopens the checkpoint copy",
            rolled["ok"]
            and str(opened.get("path", "")).lower() == str(path).lower(),
            json.dumps(rolled.get("data", {})),
        )
        after = await client.data("list_features")
        names = [feature.get("name") for feature in after.get("features", [])]
        check("rollback restored the empty document", "Body" not in names, str(names))
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
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            client = Client(session)
            await test_drawing_edit(client)
            await test_checkpoint_transactions(client)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
