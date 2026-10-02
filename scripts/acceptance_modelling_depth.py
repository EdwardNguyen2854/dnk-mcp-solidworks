#!/usr/bin/env python
"""Live acceptance suite: Wave-1 3D feature depth.

Every check compares measured volume or geometry against a hand calculation.
Runs the MCP server over stdio against the open SOLIDWORKS session; creates
and closes its own documents (never saves over anything).

Usage:
    python scripts/acceptance_modelling_depth.py
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

    async def volume(self) -> float:
        result = await self.call("get_mass_properties")
        return float(result.get("data", {}).get("volume_mm3", -1))

    async def bbox(self) -> dict:
        result = await self.call("get_bounding_box")
        return result.get("data", {})

    async def new_part(self) -> None:
        await self.call("new_document", kind="part")

    async def close(self) -> None:
        await self.call("close_document", save=False)


def near(actual: float, expected: float, tolerance: float = 0.01) -> bool:
    return abs(actual - expected) <= max(abs(expected) * tolerance, 0.05)


def top_of(bbox: dict) -> float | None:
    maximum = bbox.get("max_mm")
    return maximum[2] if maximum else None


async def top_face(client: Client, z_min: float) -> int | None:
    faces = await client.call("list_faces")
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        box = face.get("box_mm", {})
        if (
            normal
            and abs(normal[2] - 1) < 1e-6
            and box.get("min", [0, 0, 0])[2] > z_min - 0.01
        ):
            return face["index"]
    return None


async def top_line_edge(client: Client, height_mm: float) -> int | None:
    edges = await client.call("list_edges")
    for edge in edges["data"]["edges"]:
        if edge.get("curve") != "line":
            continue
        start = edge.get("start_mm") or []
        end = edge.get("end_mm") or []
        if (
            len(start) >= 3
            and len(end) >= 3
            and abs(start[2] - height_mm) < 0.01
            and abs(end[2] - height_mm) < 0.01
        ):
            return edge["index"]
    return None


async def offset_plane(client: Client, distance_mm: float, name: str) -> str:
    result = await client.call(
        "create_reference_plane",
        kind="offset",
        plane="front",
        distance_mm=distance_mm,
        name=name,
    )
    return result.get("data", {}).get("feature", name)


# ---------------------------------------------------------------------------


async def test_up_to_surface(client: Client) -> None:
    await client.new_part()
    plane = await offset_plane(client, 30, "Top Ref")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "boss_extrude", end_condition="up_to_surface", plane=plane, name="ToSurface"
    )
    expected = math.pi * 25 * 30
    volume = await client.volume()
    bbox = await client.bbox()
    check(
        "up_to_surface volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    check(
        "up_to_surface stops at the reference",
        near(top_of(bbox) or 0, 30.0),
        f"top {top_of(bbox)}",
    )
    await client.close()


async def test_offset_from_surface(client: Client) -> None:
    await client.new_part()
    plane = await offset_plane(client, 30, "Top Ref")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "boss_extrude",
        end_condition="offset_from_surface",
        offset_mm=5,
        plane=plane,
        name="Beyond",
    )
    expected = math.pi * 25 * 35
    volume = await client.volume()
    check(
        "offset_from_surface +5 volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()

    await client.new_part()
    plane = await offset_plane(client, 30, "Top Ref")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "boss_extrude",
        end_condition="offset_from_surface",
        offset_mm=-5,
        plane=plane,
        name="Short",
    )
    expected = math.pi * 25 * 25
    volume = await client.volume()
    check(
        "offset_from_surface -5 pulls back",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_up_to_vertex(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=60, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=10, y1_mm=10, x2_mm=20, y2_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=40, name="Post")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=40, center_y_mm=20, radius_mm=3)
    await client.call("exit_sketch")
    vertices = await client.call("list_vertices")
    target = None
    for vertex in vertices["data"]["vertices"]:
        if abs(vertex.get("point_mm", [0, 0, 0])[2] - 40) < 0.01:
            target = vertex["index"]
            break
    check("up_to_vertex target vertex", target is not None, f"index {target}")
    if target is None:
        await client.close()
        return
    result = await client.call(
        "boss_extrude",
        end_condition="up_to_vertex",
        vertex_index=target,
        name="ToVertex",
    )
    expected = 24000 + 3000 + math.pi * 9 * 30
    volume = await client.volume()
    check(
        "up_to_vertex volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_up_to_body(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=60, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Plate")
    plane = await offset_plane(client, 30, "Block Base")
    await client.call("create_sketch", plane=plane)
    await client.call("sketch_rectangle", x1_mm=15, y1_mm=15, x2_mm=45, y2_mm=45)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=20, merge=False, name="Block")
    bodies = await client.call("list_bodies")
    block = None
    for body in bodies["data"]["bodies"]:
        box = body.get("box_mm", {}).get("min", [0, 0, 0])
        if abs(box[2] - 30) < 0.01:
            block = body["index"]
    check("up_to_body target body", block is not None, f"index {block}")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=30, center_y_mm=30, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "boss_extrude",
        end_condition="up_to_body",
        body_index=block,
        name="ToBody",
    )
    expected = 36000 + 18000 + math.pi * 25 * 20
    volume = await client.volume()
    check(
        "up_to_body volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_cut_up_to_surface(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=20, name="Box")
    plane = await offset_plane(client, 10, "Cut Ref")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=20, center_y_mm=20, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "cut_extrude",
        end_condition="up_to_surface",
        plane=plane,
        name="CutToSurface",
    )
    expected = 32000 - math.pi * 25 * 10
    volume = await client.volume()
    check(
        "cut up_to_surface volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_revolve_cut(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=-20, y1_mm=-20, x2_mm=20, y2_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=20, both_directions=True, name="Cube")
    await client.call("create_sketch", plane="top")
    await client.call("sketch_rectangle", x1_mm=5, y1_mm=-30, x2_mm=15, y2_mm=30)
    await client.call("sketch_line", x1_mm=0, y1_mm=-35, x2_mm=0, y2_mm=35, construction=True)
    await client.call("exit_sketch")
    result = await client.call("revolve_cut", angle_deg=360, name="RingCut")
    expected = 64000 - math.pi * (225 - 25) * 40
    volume = await client.volume()
    check(
        "revolve_cut removes the ring",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_thin_extrude(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=-50, y1_mm=-50, x2_mm=50, y2_mm=50)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Plate")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=20)
    await client.call("exit_sketch")
    result = await client.call(
        "thin_extrude",
        cut=True,
        end_condition="through_all",
        thickness_mm=2,
        side="mid",
        name="ThinCut",
    )
    expected = 100000 - 2 * math.pi * 20 * 2 * 10
    volume = await client.volume()
    check(
        "thin cut through-all mid",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=20)
    await client.call("exit_sketch")
    result = await client.call(
        "thin_extrude",
        depth_mm=10,
        thickness_mm=2,
        side="outward",
        name="ThinWall",
    )
    expected = math.pi * (22 * 22 - 20 * 20) * 10
    volume = await client.volume()
    check(
        "thin boss outward",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_fillet_face(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=40, name="Cube")
    faces = await client.call("list_faces")
    top = front = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal") or [0, 0, 0]
        if abs(normal[2] - 1) < 1e-6:
            top = face["index"]
        if abs(normal[1] - 1) < 1e-6 and abs(normal[2]) < 1e-6:
            front = face["index"]
    check("face fillet faces found", top is not None and front is not None, f"{top},{front}")
    result = await client.call(
        "fillet",
        radius_mm=6,
        kind="face",
        face_indices=[top, front],
        name="FaceBlend",
    )
    expected = 64000 - (1 - math.pi / 4) * 36 * 40
    volume = await client.volume()
    check(
        "face fillet volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_chamfer_kinds(client: Client) -> None:
    cases = [
        ("equal", {"distance_mm": 10}, 0.5 * 10 * 10 * 40),
        (
            "angle_distance",
            {"distance_mm": 10, "kind": "angle_distance", "angle_deg": 30},
            0.5 * 10 * (10 * math.tan(math.radians(30))) * 40,
        ),
        (
            "distance_distance",
            {"distance_mm": 10, "kind": "distance_distance", "second_distance_mm": 4},
            0.5 * 10 * 4 * 40,
        ),
    ]
    for label, arguments, removed in cases:
        await client.new_part()
        await client.call("create_sketch", plane="front")
        await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
        await client.call("exit_sketch")
        await client.call("boss_extrude", depth_mm=40, name="Cube")
        edge = await top_line_edge(client, 40)
        result = await client.call("chamfer", edge_indices=[edge], **arguments)
        volume = await client.volume()
        expected = 64000 - removed
        check(
            f"chamfer {label}",
            result["ok"] and near(volume, expected),
            f"{volume:.3f} vs {expected:.3f}",
        )
        await client.close()


async def test_hole_recipes(client: Client) -> None:
    # Counterbore: Ø6 through with a Ø10 x 5 counterbore.
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Plate")
    top = await top_face(client, 9.9)
    result = await client.call(
        "counterbore_hole",
        diameter_mm=6,
        counterbore_diameter_mm=10,
        counterbore_depth_mm=5,
        face_index=top,
        x_mm=20,
        y_mm=20,
        end_condition="through_all",
        name="Counterbore",
    )
    removed = math.pi * 9 * 10 + math.pi * (25 - 9) * 5
    expected = 16000 - removed
    volume = await client.volume()
    check(
        "counterbore_hole volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()

    # Countersink: Ø6 through with a 90-degree Ø10 countersink.
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=20, y2_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Plate")
    top = await top_face(client, 9.9)
    result = await client.call(
        "countersink_hole",
        diameter_mm=6,
        countersink_diameter_mm=10,
        face_index=top,
        x_mm=10,
        y_mm=10,
        angle_deg=90,
        end_condition="through_all",
        name="Countersink",
    )
    frustum = math.pi * 2 / 3 * (25 + 15 + 9)
    extra = frustum - math.pi * 9 * 2
    expected = 4000 - (math.pi * 9 * 10 + extra)
    volume = await client.volume()
    check(
        "countersink_hole volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    await client.close()


async def test_tapped_and_cosmetic_thread(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=20, y2_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=20, name="Block")
    top = await top_face(client, 19.9)
    result = await client.call(
        "tapped_hole",
        diameter_mm=8,
        pitch_mm=1.25,
        face_index=top,
        x_mm=10,
        y_mm=10,
        depth_mm=15,
        name="Tapped",
    )
    drill = 8 - 1.25
    expected = 8000 - math.pi * (drill / 2) ** 2 * 15
    volume = await client.volume()
    check(
        "tapped_hole volume (thread is cosmetic)",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    check(
        "tapped_hole callout",
        result.get("data", {}).get("callout") == "M8x1.25"
        and abs(result["data"].get("drill_diameter_mm", 0) - drill) < 1e-6,
        json.dumps(result.get("data")),
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=20, y2_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=20, name="Block")
    top = await top_face(client, 19.9)
    await client.call(
        "simple_hole", diameter_mm=6, face_index=top, x_mm=10, y_mm=10,
        end_condition="through_all",
    )
    edges = await client.call("list_edges")
    circle = None
    for edge in edges["data"]["edges"]:
        if edge.get("curve") == "circle" and abs(
            edge.get("length_mm", 0) - math.pi * 6
        ) < 0.05:
            circle = edge["index"]
            break
    result = await client.call(
        "cosmetic_thread", edge_index=circle, depth_mm=15, note="M6x1"
    )
    volume = await client.volume()
    expected = 8000 - math.pi * 9 * 20
    check(
        "cosmetic_thread adds no volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    check(
        "cosmetic_thread read-back",
        abs(result.get("data", {}).get("diameter_mm", 0) - 6) < 0.01
        and result.get("data", {}).get("callout") == "M6x1",
        json.dumps(result.get("data")),
    )
    await client.close()


async def test_dome(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=20)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=30, name="Cylinder")
    top = await top_face(client, 29.9)
    result = await client.call("dome", height_mm=10, face_index=top, name="Cap")
    cap = math.pi * 10 / 6 * (3 * 20 * 20 + 10 * 10)
    expected = math.pi * 400 * 30 + cap
    volume = await client.volume()
    bbox = await client.bbox()
    check(
        "dome spherical-cap volume",
        result["ok"] and near(volume, expected),
        f"{volume:.3f} vs {expected:.3f}",
    )
    check(
        "dome reaches its height",
        near(top_of(bbox) or 0, 40.0),
        f"top {top_of(bbox)}",
    )
    await client.close()


async def test_missing_reference_is_reported(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", end_condition="up_to_surface")
    error = result.get("error") or {}
    message = json.dumps(error)
    check(
        "up_to_surface without a reference fails loudly",
        not result.get("ok") and "reference" in message,
        message,
    )
    await client.close()


async def main() -> int:
    env = dict(os.environ)
    env.setdefault("SW_MCP_TOOL_TIER", "extended")
    env.setdefault("SW_MCP_OUTPUT_ROOT", str(ROOT / "artifacts" / "acceptance"))
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
            await test_up_to_surface(client)
            await test_offset_from_surface(client)
            await test_up_to_vertex(client)
            await test_up_to_body(client)
            await test_cut_up_to_surface(client)
            await test_revolve_cut(client)
            await test_thin_extrude(client)
            await test_fillet_face(client)
            await test_chamfer_kinds(client)
            await test_hole_recipes(client)
            await test_tapped_and_cosmetic_thread(client)
            await test_dome(client)
            await test_missing_reference_is_reported(client)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} modelling-depth checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
