#!/usr/bin/env python
"""Live acceptance suite: drive the MCP server over stdio and verify measured
geometry against hand calculations.

Usage:
    python scripts/acceptance.py [--keep]
"""
from __future__ import annotations

import argparse
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

    async def new_part(self) -> None:
        await self.call("new_document", kind="part")

    async def close(self) -> None:
        await self.call("close_document", save=False)


async def test_box(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=25, name="Base")
    volume = await client.volume()
    check("box extrude volume", abs(volume - 150000) < 1, f"{volume:.2f} mm3")
    check("box extrude evidence", "evidence" in result, "evidence present")

    edges = await client.call("list_edges")
    verticals = [
        edge["index"]
        for edge in edges["data"]["edges"]
        if abs(edge.get("length_mm", 0) - 25) < 0.01
    ]
    check("list_edges finds verticals", len(verticals) == 4, str(verticals))

    result = await client.call("fillet", radius_mm=5, edge_indices=verticals)
    expected = 150000 - 4 * (25 - math.pi * 25 / 4) * 25
    volume = await client.volume()
    check(
        "fillet 4 verticals",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )

    result = await client.call("set_material", name="6061 Alloy")
    density = result.get("data", {}).get("density_kg_m3", 0)
    check("set_material 6061", abs(density - 2700) < 50, f"{density} kg/m3")
    await client.close()


async def test_shell(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Box")

    faces = await client.call("list_faces")
    top = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        box = face.get("box_mm", {})
        if normal and abs(normal[2] - 1) < 1e-6 and box.get("max", [0, 0, 0])[2] > 24.9:
            top = face["index"]
            break
    check("find top face", top is not None, f"index {top}")

    result = await client.call("shell", thickness_mm=2, face_indices=[top])
    expected = 100 * 60 * 25 - (100 - 4) * (60 - 4) * (25 - 2)
    volume = await client.volume()
    check(
        "shell top face",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_through_cut(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Box")

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=50, center_y_mm=30, radius_mm=10)
    await client.call("exit_sketch")
    result = await client.call(
        "cut_extrude", end_condition="through_all_both", name="ThroughHole"
    )
    expected = 150000 - math.pi * 100 * 25
    volume = await client.volume()
    check(
        "through_all_both cut",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_reference_plane_and_pattern(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=-50, y1_mm=-30, x2_mm=50, y2_mm=30
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")

    result = await client.call(
        "create_reference_plane",
        kind="offset",
        plane="front",
        distance_mm=20,
        name="Offset20",
    )
    check(
        "offset reference plane",
        result["ok"] and result["data"]["feature"] == "Offset20",
        json.dumps(result.get("data")),
    )
    result = await client.call(
        "create_reference_plane",
        kind="midplane",
        plane="front",
        second_plane="Offset20",
        name="Mid10",
    )
    check(
        "midplane reference plane",
        result["ok"] and result["data"]["feature"] == "Mid10",
        json.dumps(result.get("data")),
    )

    await client.call("create_sketch", plane="Offset20")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=20, radius_mm=10)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Pad")

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    result = await client.call(
        "cut_extrude", depth_mm=10, end_condition="through_all", name="Hole1"
    )
    check("single-ended through cut", result["ok"], json.dumps(result.get("data")))

    edges = await client.call("list_edges")
    direction = None
    for edge in edges["data"]["edges"]:
        if (
            abs(edge.get("length_mm", 0) - 100) < 0.01
            and edge["end_mm"][0] - edge["start_mm"][0] > 99
        ):
            direction = edge["index"]
            break
    check("direction edge found", direction is not None, f"index {direction}")
    result = await client.call(
        "linear_pattern",
        feature_names=["Hole1"],
        spacing_mm=20,
        direction_edge=direction,
        count=3,
        name="HolePattern",
    )
    expected = 60000 + math.pi * 100 * 10 - 3 * math.pi * 25 * 10
    volume = await client.volume()
    check(
        "linear pattern volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    errors = await client.call("check_errors")
    check(
        "no errors after linear pattern",
        errors["data"]["count"] == 0,
        json.dumps(errors.get("data")),
    )
    await client.close()


async def test_mirror(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=-50, y1_mm=-30, x2_mm=50, y2_mm=30
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=20, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    await client.call(
        "cut_extrude", depth_mm=10, end_condition="through_all", name="Hole"
    )
    result = await client.call(
        "mirror_feature", feature_names=["Hole"], plane="right", name="HoleMirror"
    )
    expected = 60000 - 2 * math.pi * 25 * 10
    volume = await client.volume()
    check(
        "mirror feature volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_circular_pattern(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_rectangle", x1_mm=-50, y1_mm=-30, x2_mm=50, y2_mm=30
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=3)
    await client.call("exit_sketch")
    await client.call(
        "boss_extrude", depth_mm=5, both_directions=True, name="Hub"
    )

    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=20, center_y_mm=0, radius_mm=5)
    await client.call("exit_sketch")
    await client.call(
        "cut_extrude", depth_mm=10, end_condition="through_all", name="BoltHole"
    )

    faces = await client.call("list_faces")
    axis = None
    for face in faces["data"]["faces"]:
        if face.get("surface") != "cylinder":
            continue
        box = face.get("box_mm", {})
        cx = (box["min"][0] + box["max"][0]) / 2
        cy = (box["min"][1] + box["max"][1]) / 2
        if abs(cx) < 0.5 and abs(cy) < 0.5:
            axis = face["index"]
            break
    check("circular axis face found", axis is not None, f"index {axis}")
    result = await client.call(
        "circular_pattern",
        feature_names=["BoltHole"],
        count=6,
        angle_deg=360,
        axis_face=axis,
        name="BoltCircle",
    )
    expected = 60000 + math.pi * 3**2 * 5 - 6 * math.pi * 25 * 10
    volume = await client.volume()
    check(
        "circular pattern volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_revolve(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_line", x1_mm=0, y1_mm=0, x2_mm=0, y2_mm=10, construction=True
    )
    await client.call("sketch_rectangle", x1_mm=20, y1_mm=0, x2_mm=30, y2_mm=10)
    await client.call("exit_sketch")
    result = await client.call("revolve", angle_deg=360, name="Ring")
    expected = math.pi * (30**2 - 20**2) * 10
    volume = await client.volume()
    check(
        "revolve ring volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_dimension(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=50, y2_mm=30)
    listing = await client.call("list_sketch_segments")
    target = None
    for segment in listing["data"]["segments"]:
        if segment.get("type") == "line" and abs(segment.get("length_mm", 0) - 50) < 0.01:
            target = segment["index"]
            break
    check("sketch segment listing", target is not None, f"segment {target}")
    result = await client.call(
        "sketch_add_dimension",
        segment_indices=[target],
        value_mm=80,
        placement_mm=[25, -10],
    )
    listing = await client.call("list_sketch_segments")
    lengths = [
        segment.get("length_mm", 0)
        for segment in listing["data"]["segments"]
        if segment.get("type") == "line"
    ]
    check(
        "driving dimension applied",
        result.get("data", {}).get("value_applied") and max(lengths) > 79,
        f"lengths={lengths}",
    )
    await client.close()


async def test_sketch_geometry(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_arc",
        center_x_mm=0, center_y_mm=0,
        start_x_mm=20, start_y_mm=0,
        end_x_mm=-20, end_y_mm=0,
    )
    await client.call("sketch_line", x1_mm=-20, y1_mm=0, x2_mm=20, y2_mm=0)
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=10, name="ArcDisc")
    expected = math.pi * 20**2 / 2 * 10
    volume = await client.volume()
    check(
        "arc half-disc volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_slot", x1_mm=0, y1_mm=0, x2_mm=60, y2_mm=0, width_mm=10
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=5, name="Slot")
    expected = (60 * 10 + math.pi * 5**2) * 5
    volume = await client.volume()
    check(
        "slot volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call(
        "sketch_ellipse",
        center_x_mm=0, center_y_mm=0,
        major_x_mm=30, major_y_mm=0,
        minor_x_mm=0, minor_y_mm=20,
    )
    await client.call("exit_sketch")
    result = await client.call("boss_extrude", depth_mm=10, name="Ellipse")
    expected = math.pi * 30 * 20 * 10
    volume = await client.volume()
    check(
        "ellipse volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_sketch_modify(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    result = await client.call(
        "sketch_fillet", segment_indices=[0, 1], radius_mm=5
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Filleted")
    expected = (1600 - (25 - math.pi * 25 / 4)) * 10
    volume = await client.volume()
    check(
        "sketch fillet profile volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    result = await client.call(
        "sketch_chamfer", segment_indices=[0, 1], distance_mm=5
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Chamfered")
    expected = (1600 - 12.5) * 10
    volume = await client.volume()
    check(
        "sketch chamfer profile volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call(
        "sketch_line", x1_mm=50, y1_mm=-20, x2_mm=50, y2_mm=60, construction=True
    )
    listing = await client.call("list_sketch_segments")
    segments = listing["data"]["segments"]
    centerline = next(
        (s["index"] for s in segments if s.get("construction")), None
    )
    entities = [s["index"] for s in segments if not s.get("construction")]
    result = await client.call(
        "sketch_mirror", segment_indices=entities, mirror_segment=centerline
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Mirrored")
    expected = 2 * 1600 * 10
    volume = await client.volume()
    check(
        "sketch mirror volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("sketch_line", x1_mm=20, y1_mm=20, x2_mm=60, y2_mm=20)
    listing = await client.call("list_sketch_segments")
    crossing = next(
        (
            s["index"]
            for s in listing["data"]["segments"]
            if abs(s.get("length_mm", 0) - 40) < 0.01
            and "point_mm" in s
            and abs(s["point_mm"][0] - 20) < 5
        ),
        listing["data"]["segments"][-1]["index"],
    )
    result = await client.call(
        "sketch_trim", segment_indices=[crossing], x_mm=50, y_mm=20
    )
    check(
        "sketch trim",
        result["ok"] and result["data"]["segments_after"] < result["data"]["segments_before"],
        json.dumps(result.get("data")),
    )
    await client.call("exit_sketch")
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    result = await client.call(
        "sketch_construction", segment_indices=[0], construction=True
    )
    listing = await client.call("list_sketch_segments")
    check(
        "sketch construction toggle",
        result["ok"] and listing["data"]["segments"][0].get("construction") is True,
        json.dumps(result.get("data")),
    )
    await client.call("exit_sketch")
    await client.close()


async def test_sketch_edit_and_dimensions(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")
    listing = await client.call("list_sketches")
    check(
        "list_sketches",
        listing["ok"] and listing["data"]["count"] == 1,
        json.dumps(listing.get("data")),
    )
    sketch_name = listing["data"]["sketches"][0]["name"]
    result = await client.call("edit_sketch", name=sketch_name)
    check(
        "edit_sketch reopens the sketch",
        result["ok"] and result["data"]["active"],
        json.dumps(result.get("data")),
    )
    await client.call("exit_sketch")
    await client.close()

    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=50, y2_mm=40)
    await client.call(
        "sketch_add_dimension", segment_indices=[0], value_mm=80, placement_mm=[25, -10]
    )
    dimensions = await client.call("list_dimensions")
    entry = dimensions["data"]["dimensions"][0] if dimensions["data"]["dimensions"] else {}
    check(
        "list_dimensions reads the driving dimension",
        entry.get("kind") == "linear" and abs(entry.get("value_mm", 0) - 80) < 0.01,
        json.dumps(entry),
    )
    result = await client.call(
        "set_dimension", full_name=entry.get("full_name", ""), value_mm=100
    )
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Driven")
    expected = 100 * 40 * 10
    volume = await client.volume()
    check(
        "set_dimension drives geometry",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_simple_hole(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Plate")
    faces = await client.call("list_faces")
    top = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        box = face.get("box_mm", {})
        if (
            normal
            and abs(normal[2] - 1) < 1e-6
            and box.get("max", [0, 0, 0])[2] > 24.9
        ):
            top = face["index"]
            break
    result = await client.call(
        "simple_hole",
        diameter_mm=20,
        face_index=top,
        x_mm=50,
        y_mm=30,
        end_condition="through_all",
        name="ThroughHole",
    )
    expected = 150000 - math.pi * 100 * 25
    volume = await client.volume()
    check(
        "simple hole through volume",
        result["ok"] and abs(volume - expected) / expected < 0.001,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_draft(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Block")
    faces = await client.call("list_faces")
    side = bottom = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        if not normal:
            continue
        if all(abs(a - b) < 1e-6 for a, b in zip(normal, [1, 0, 0])):
            side = face["index"]
        if all(abs(a - b) < 1e-6 for a, b in zip(normal, [0, 0, -1])):
            bottom = face["index"]
    result = await client.call(
        "draft",
        angle_deg=5,
        face_indices=[side],
        neutral_face_index=bottom,
        reverse=True,
        name="Draft",
    )
    removed = 0.5 * (25 * math.tan(math.radians(5))) * 25 * 60
    expected = 150000 - removed
    volume = await client.volume()
    check(
        "draft wedge volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_sweep_and_loft(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_line", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=0)
    await client.call("exit_sketch")
    await client.call("create_sketch", plane="right")
    await client.call("sketch_circle", center_x_mm=0, center_y_mm=0, radius_mm=10)
    await client.call("exit_sketch")
    listing = await client.call("list_sketches")
    names = [item["name"] for item in listing["data"]["sketches"]]
    result = await client.call(
        "sweep", profile_sketch=names[1], path_sketch=names[0], name="Rod"
    )
    expected = math.pi * 100 * 100
    volume = await client.volume()
    check(
        "swept rod volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()

    await client.new_part()
    plane = await client.call(
        "create_reference_plane", kind="offset", plane="front", distance_mm=50
    )
    plane_name = plane["data"]["feature"]
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=10, y1_mm=10, x2_mm=50, y2_mm=50)
    await client.call("exit_sketch")
    await client.call("create_sketch", plane=plane_name)
    await client.call("sketch_rectangle", x1_mm=20, y1_mm=20, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    listing = await client.call("list_sketches")
    names = [item["name"] for item in listing["data"]["sketches"]]
    result = await client.call("loft", profile_sketches=names[:2], name="Frustum")
    expected = 50 / 3 * (1600 + 400 + math.sqrt(1600 * 400))
    volume = await client.volume()
    check(
        "lofted frustum volume",
        result["ok"] and abs(volume - expected) / expected < 0.01,
        f"{volume:.2f} vs {expected:.2f}",
    )
    await client.close()


async def test_suppression(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=40, y2_mm=40)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=10, name="Base")
    await client.call("create_sketch", plane="front")
    await client.call("sketch_circle", center_x_mm=20, center_y_mm=20, radius_mm=5)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=30, name="Post")
    full = await client.volume()
    result = await client.call(
        "set_feature_suppression", feature_names=["Post"], suppressed=True
    )
    suppressed = await client.volume()
    check(
        "suppress feature volume",
        result["ok"] and abs(suppressed - 16000) < 1,
        f"{suppressed:.2f} vs 16000.00",
    )
    await client.call(
        "set_feature_suppression", feature_names=["Post"], suppressed=False
    )
    restored = await client.volume()
    check(
        "unsuppress feature volume",
        abs(restored - full) < 1,
        f"{restored:.2f} vs {full:.2f}",
    )
    await client.close()


async def test_axis_vertices_measure(client: Client) -> None:
    await client.new_part()
    await client.call("create_sketch", plane="front")
    await client.call("sketch_rectangle", x1_mm=0, y1_mm=0, x2_mm=100, y2_mm=60)
    await client.call("exit_sketch")
    await client.call("boss_extrude", depth_mm=25, name="Plate")

    result = await client.call(
        "create_axis", planes=["Front Plane", "Right Plane"], name="YAxis"
    )
    planes = await client.call("list_reference_planes")
    check(
        "create reference axis",
        result["ok"] and "YAxis" in planes["data"]["axes"],
        json.dumps(planes.get("data")),
    )

    vertices = await client.call("list_vertices")
    check(
        "list_vertices finds a box",
        vertices["ok"] and vertices["data"]["count"] == 8,
        f"{vertices['data'].get('count')} vertices",
    )
    corners = vertices["data"]["vertices"]
    pair = None
    for first in corners:
        for second in corners:
            if first["index"] >= second["index"]:
                continue
            if (
                abs(first["point_mm"][1] - second["point_mm"][1]) < 1e-6
                and abs(first["point_mm"][2] - second["point_mm"][2]) < 1e-6
                and abs(abs(first["point_mm"][0] - second["point_mm"][0]) - 100) < 0.01
            ):
                pair = (first["index"], second["index"])
    check("100 mm vertex pair found", pair is not None, str(pair))
    if pair:
        result = await client.call("measure", vertex_indices=list(pair))
        check(
            "measure vertex distance",
            result["ok"] and abs(result["data"].get("distance_mm", 0) - 100) < 0.01,
            json.dumps(result.get("data")),
        )

    faces = await client.call("list_faces")
    top = None
    for face in faces["data"]["faces"]:
        normal = face.get("normal")
        box = face.get("box_mm", {})
        if (
            normal
            and abs(normal[2] - 1) < 1e-6
            and box.get("max", [0, 0, 0])[2] > 24.9
        ):
            top = face["index"]
    result = await client.call("measure", face_indices=[top])
    check(
        "measure face area",
        result["ok"] and abs(result["data"].get("area_mm2", 0) - 6000) < 1,
        json.dumps(result.get("data")),
    )
    await client.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
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
            await test_box(client)
            await test_shell(client)
            await test_through_cut(client)
            await test_reference_plane_and_pattern(client)
            await test_mirror(client)
            await test_circular_pattern(client)
            await test_revolve(client)
            await test_dimension(client)
            await test_sketch_geometry(client)
            await test_sketch_modify(client)
            await test_sketch_edit_and_dimensions(client)
            await test_simple_hole(client)
            await test_draft(client)
            await test_sweep_and_loft(client)
            await test_suppression(client)
            await test_axis_vertices_measure(client)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
