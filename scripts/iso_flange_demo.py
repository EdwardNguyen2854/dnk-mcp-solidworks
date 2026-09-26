#!/usr/bin/env python
"""Bearing flange housing: a revolved part and its ISO A3 drawing, end to end.

Builds a hand-calculable rotational part, then produces the 2D drawing:

  revolve flange ring (x 0..14, r 14..50) -> revolve hub ring (x 14..40,
  r 14..30) -> 6X dia 9 bolt holes on a 78 B.C. (one cut + circular pattern) ->
  R3 root fillet -> 1.5x45 bore chamfer at the mating face -> 1x45 rim chamfers
  on the flange OD -> material.

  Then: framed A3 sheet -> first-angle front/top/right -> full section A-A
  through the axis (real cut geometry, verified by read-back) -> isometric at
  1:2 -> title-block properties -> datum A (mating face) and datum B (dia 100
  OD) -> dimensions with a H7 bore fit -> position FCF 0.5 A|B on the bolt
  circle -> surface finish on the bore -> general-tolerance note -> revision
  table -> manifest/preflight/audit/ISO validation -> PDF + DXF + PNG export
  and verification -> save, close, reopen, re-validate.

Section views need the cutting line in the parent view sketch's local space,
not sheet millimetres; `drawing_insert_section_view` does that conversion and
refuses a view that exposes no cut edges. Before that fix a section view was
created silently uncut (`docs/COM-QUIRKS.md`).

Design intent (ISO metric, mm):

  flange dia 100 x 14 thick; hub dia 60, overall length 40; bore dia 28 H7;
  6X dia 9 clearance holes equally spaced on a dia 78 bolt circle; R3 fillet at
  the hub root; 1.5x45 bore chamfer at the mating face; 1x45 flange rim
  chamfers. The hub tip face is left sharp so its bore (dia 28) and hub (dia 60)
  edges stay visible in the circular view - that is where the tool surface can
  dimension them (a section view exposes no cut-contour edges on this build).

Datums:

  A = flange back face (the mating face, shown edge-on in the front view)
  B = flange OD dia 100 (the circular view), the practical turning datum;
      a reviewer may prefer the bore axis as B - the tool surface attaches
      datum symbols to view edges, so the bore axis is not directly available.

Hand calculations (verified against measured B-rep mass properties at every
feature, not just at the end):

  flange ring  pi (50^2 - 14^2) x 14
  hub ring     pi (30^2 - 14^2) x 26
  bolt holes   6 x pi x 4.5^2 x 14
  root fillet  Pappus ring: 2 pi (30 + c) A, A = R^2 - pi R^2/4, c = centroid
  chamfers     Pappus ring per corner: 2 pi (r +/- d/3) (d^2/2), the sign
               depending on whether the removed triangle sits outside (bore)
               or inside (OD) the corner

Needs a running SOLIDWORKS session; creates its own documents under
artifacts/flange-drawing-demo and closes them before exiting. Outputs:
Flange-2001.sldprt, FLG-2001.SLDDRW, FLG-2001-RevA.pdf/.png/.dxf.
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
OUTPUT = ROOT / "artifacts" / "flange-drawing-demo"
PART = OUTPUT / "Flange-2001.sldprt"
DRAWING = OUTPUT / "FLG-2001.SLDDRW"
PDF = OUTPUT / "FLG-2001-RevA.pdf"
PNG = OUTPUT / "FLG-2001-RevA.png"
DXF = OUTPUT / "FLG-2001-RevA.dxf"
PART_PNG = OUTPUT / "Flange-2001-iso.png"

# ---------------------------------------------------------------- design (mm)
FLANGE_OD = 100.0
FLANGE_T = 14.0
HUB_OD = 60.0
TOTAL_L = 40.0
BORE_D = 28.0
HOLE_D = 9.0
HOLE_COUNT = 6
BCD = 78.0
ROOT_FILLET = 3.0
CH_BORE = 1.5
CH_RIM = 1.0

R_FLANGE = FLANGE_OD / 2.0
R_HUB = HUB_OD / 2.0
R_BORE = BORE_D / 2.0
R_HOLE = HOLE_D / 2.0
R_BCD = BCD / 2.0

# Sheet layout (mm from the sheet's lower-left corner, A3 landscape). The top
# view hangs directly below the front view in first angle, leaving a dimension
# row under the front outline.
FRONT_POS = (200.0, 195.0)
ISO_POS = (80.0, 60.0)
ISO_SCALE = 0.5
VIEW_GAP = 20.0
FRAME = (10.0, 10.0, 410.0, 287.0)  # audit frame box for the stock ISO A3 sheet

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

    async def volume(self) -> float:
        mass = await self.data("get_mass_properties")
        return float(mass.get("volume_mm3") or 0.0)


def near(first, second, tolerance=0.05) -> bool:
    try:
        return abs(float(first) - float(second)) <= tolerance
    except (TypeError, ValueError):
        return False


def box_centre(box: dict) -> tuple[float, float]:
    return (
        (float(box["min"][0]) + float(box["max"][0])) / 2.0,
        (float(box["min"][1]) + float(box["max"][1])) / 2.0,
    )


def inside_frame(box: dict) -> bool:
    return (
        float(box["min"][0]) >= FRAME[0] - 0.5
        and float(box["min"][1]) >= FRAME[1] - 0.5
        and float(box["max"][0]) <= FRAME[2] + 0.5
        and float(box["max"][1]) <= FRAME[3] + 0.5
    )


# ------------------------------------------------------------ hand arithmetic
def chamfer_ring(radius_mm: float, leg_mm: float, inward: bool = False) -> float:
    """Volume removed by a 45-degree chamfer: the corner triangle revolved.

    ``inward`` marks a corner whose removed triangle lies inside the radius
    (an OD rim); the centroid then sits at r - d/3 instead of r + d/3.
    """
    area = 0.5 * leg_mm**2
    centroid = radius_mm - leg_mm / 3.0 if inward else radius_mm + leg_mm / 3.0
    return 2 * math.pi * centroid * area


def expected_volumes() -> dict:
    flange = math.pi * (R_FLANGE**2 - R_BORE**2) * FLANGE_T
    body = flange + math.pi * (R_HUB**2 - R_BORE**2) * (TOTAL_L - FLANGE_T)
    hole = math.pi * R_HOLE**2 * FLANGE_T
    # Root fillet adds a ring: cross-section is "square minus quarter disc";
    # its centroid offset feeds Pappus.
    a_square = ROOT_FILLET**2
    a_quarter = math.pi * ROOT_FILLET**2 / 4.0
    c_quarter = ROOT_FILLET - 4.0 * ROOT_FILLET / (3.0 * math.pi)
    offset = (a_square * (ROOT_FILLET / 2.0) - a_quarter * c_quarter) / (
        a_square - a_quarter
    )
    fillet = 2 * math.pi * (R_HUB + offset) * (a_square - a_quarter)
    chamfers = chamfer_ring(R_BORE, CH_BORE) + 2 * chamfer_ring(
        R_FLANGE, CH_RIM, inward=True
    )
    return {
        "flange": flange,
        "body": body,
        "hole": hole,
        "fillet": fillet,
        "chamfers": chamfers,
        "final": body - HOLE_COUNT * hole + fillet - chamfers,
    }


# ---------------------------------------------------- part geometry helpers
def circle_edges(edges: list[dict]) -> list[dict]:
    """Circle edges resolved to (index, plane x, radius from the part axis).

    ``list_edges`` reports each edge's Evaluate(0) point in model millimetres;
    a full circle's point sits at (x, y, z), so the distance from the X axis is
    sqrt(y^2 + z^2).
    """
    found = []
    for edge in edges:
        if edge.get("curve") != "circle":
            continue
        point = edge.get("start_mm") or []
        if len(point) < 3:
            continue
        found.append(
            {
                "index": edge["index"],
                "x_mm": round(float(point[0]), 4),
                "radius_mm": round(math.hypot(float(point[1]), float(point[2])), 4),
                "length_mm": edge.get("length_mm"),
            }
        )
    return found


def pick_circles(
    edges: list[dict], x_mm: float | None = None, radius_mm: float | None = None
) -> list[int]:
    tolerance = 0.05
    return [
        edge["index"]
        for edge in circle_edges(edges)
        if (x_mm is None or abs(edge["x_mm"] - x_mm) <= tolerance)
        and (radius_mm is None or abs(edge["radius_mm"] - radius_mm) <= tolerance)
    ]


async def document_titles(client: Client) -> set[str]:
    data = await client.data("list_documents")
    documents = data if isinstance(data, list) else data.get("documents", [])
    return {str(item.get("title") or "") for item in documents}


async def close_workspace(client: Client, keep: set[str] | None = None) -> None:
    """Close this demo's documents, leaving the user's own documents alone.

    With ``keep`` (the titles open before the run) only documents this run
    created are closed. Without it, the startup sweep closes leftovers under
    the demo output folder, and - because an unsaved document has no path to
    match on - a drawing that is currently active and references the demo
    part. A killed run otherwise leaves that drawing positioned to steal the
    active document mid-build. Only the active document can be closed through
    the tool surface, so the loop stops when a foreign document becomes active.
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
                active = await client.data("get_active_document_info")
                active_document = active.get("document", active) if isinstance(active, dict) else {}
                if str(active_document.get("type") or "") == "drawing":
                    views = (await client.data("list_drawing_views")).get("views", [])
                    referenced = [
                        str(view.get("model") or "").lower() for view in views
                    ]
                    if any(path.startswith(str(OUTPUT).lower()) for path in referenced):
                        candidates = [active_document]
        if not candidates:
            break
        titles = {str(item.get("title") or "") for item in candidates}
        active = await client.data("get_active_document_info")
        active_document = active.get("document", active) if isinstance(active, dict) else {}
        if str(active_document.get("title") or "") not in titles:
            break
        await client.call("close_document", save=False)


# --------------------------------------------------------------------- part
async def build_part(client: Client) -> bool:
    expected = expected_volumes()
    print(
        "      hand calc: flange={flange:.3f} body={body:.3f} hole={hole:.3f} "
        "fillet={fillet:.3f} chamfers={chamfers:.3f} final={final:.3f}".format(**expected)
    )
    await client.call("new_document", kind="part")

    # Revolving a rectangle is the geometry-safe way to build an annulus: the
    # sketch stays a proven closed contour with the axis as a construction line.
    await client.call("create_sketch", plane="front")
    await client.call("sketch_line", x1_mm=0.0, y1_mm=0.0, x2_mm=60.0, y2_mm=0.0, construction=True)
    await client.call("sketch_rectangle", x1_mm=0.0, y1_mm=R_BORE, x2_mm=FLANGE_T, y2_mm=R_FLANGE)
    await client.call("exit_sketch")
    result = await client.call("revolve", angle_deg=360, name="Flange")
    volume = await client.volume()
    check(
        "flange ring volume matches pi (50^2 - 14^2) x 14",
        result["ok"] and near(volume, expected["flange"], 1.0),
        f"measured={volume:.3f} expected={expected['flange']:.3f}",
    )

    await client.call("create_sketch", plane="front")
    await client.call("sketch_line", x1_mm=0.0, y1_mm=0.0, x2_mm=60.0, y2_mm=0.0, construction=True)
    await client.call("sketch_rectangle", x1_mm=FLANGE_T, y1_mm=R_BORE, x2_mm=TOTAL_L, y2_mm=R_HUB)
    await client.call("exit_sketch")
    result = await client.call("revolve", angle_deg=360, name="Hub")
    volume = await client.volume()
    check(
        "hub ring merges into one solid at the body volume",
        result["ok"] and near(volume, expected["body"], 1.0),
        f"measured={volume:.3f} expected={expected['body']:.3f}",
    )

    # One bolt hole, sketched on the plane normal to the part axis, then a
    # circular pattern about a cylindrical face of that axis.
    await client.call("create_sketch", plane="right")
    await client.call("sketch_circle", center_x_mm=R_BCD, center_y_mm=0.0, radius_mm=R_HOLE)
    await client.call("exit_sketch")
    result = await client.call(
        "cut_extrude", end_condition="through_all_both", name="BoltHole"
    )
    volume = await client.volume()
    check(
        "one dia 9 hole cuts through the flange",
        result["ok"] and near(volume, expected["body"] - expected["hole"], 1.0),
        f"measured={volume:.3f} expected={expected['body'] - expected['hole']:.3f}",
    )

    faces = (await client.data("list_faces", surface_type="cylinder")).get("faces", [])
    axis_face = None
    for face in faces:
        box = face.get("box_mm") or {}
        if not box:
            continue
        cx = (float(box["min"][0]) + float(box["max"][0])) / 2.0
        cy = (float(box["min"][1]) + float(box["max"][1])) / 2.0
        cz = (float(box["min"][2]) + float(box["max"][2])) / 2.0
        if abs(cy) < 0.5 and abs(cz) < 0.5:
            axis_face = face["index"]
            break
    result = await client.call(
        "circular_pattern",
        feature_names=["BoltHole"],
        count=HOLE_COUNT,
        angle_deg=360,
        axis_face=axis_face,
        name="BoltCircle",
    )
    volume = await client.volume()
    check(
        f"{HOLE_COUNT}X bolt pattern on the axis",
        result["ok"] and near(volume, expected["body"] - HOLE_COUNT * expected["hole"], 1.0),
        f"axis face={axis_face} measured={volume:.3f} "
        f"expected={expected['body'] - HOLE_COUNT * expected['hole']:.3f}",
    )

    edges = (await client.data("list_edges")).get("edges", [])
    junction = pick_circles(edges, x_mm=FLANGE_T, radius_mm=R_HUB)
    result = await client.call("fillet", radius_mm=ROOT_FILLET, edge_indices=junction, name="RootFillet")
    volume = await client.volume()
    body_after_holes = expected["body"] - HOLE_COUNT * expected["hole"]
    check(
        "R3 root fillet adds the Pappus ring volume",
        result["ok"] and len(junction) == 1 and near(volume, body_after_holes + expected["fillet"], 1.0),
        f"junction edges={junction} measured={volume:.3f} "
        f"expected={body_after_holes + expected['fillet']:.3f}",
    )

    edges = (await client.data("list_edges")).get("edges", [])
    bore = pick_circles(edges, x_mm=0.0, radius_mm=R_BORE)
    result = await client.call("chamfer", distance_mm=CH_BORE, edge_indices=bore, name="BoreChamfer")
    body_after_fillet = body_after_holes + expected["fillet"]
    volume = await client.volume()
    check(
        "1.5x45 bore chamfer at the mating face",
        result["ok"] and near(volume, body_after_fillet - chamfer_ring(R_BORE, CH_BORE), 1.0),
        f"edges={bore} measured={volume:.3f} "
        f"expected={body_after_fillet - chamfer_ring(R_BORE, CH_BORE):.3f}",
    )

    edges = (await client.data("list_edges")).get("edges", [])
    rims = pick_circles(edges, x_mm=0.0, radius_mm=R_FLANGE) + pick_circles(
        edges, x_mm=FLANGE_T, radius_mm=R_FLANGE
    )
    result = await client.call("chamfer", distance_mm=CH_RIM, edge_indices=rims, name="RimChamfer")
    volume = await client.volume()
    check(
        "1x45 flange rim chamfers at both faces",
        result["ok"] and len(rims) == 2 and near(volume, expected["final"], 1.0),
        f"edges={rims} measured={volume:.3f} expected={expected['final']:.3f}",
    )

    material = await client.call("set_material", name="6061 Alloy")
    mass = await client.data("get_mass_properties")
    check(
        "material 6061 Aluminium with a consistent mass",
        material["ok"] and near(mass.get("density_kg_m3"), 2700, 60)
        and near(mass.get("mass_g"), expected["final"] * 2700e-9 * 1000.0, 0.5),
        f"density={mass.get('density_kg_m3')} mass={mass.get('mass_g')} g",
    )

    box = await client.data("get_bounding_box")
    size = box.get("size_mm") or []
    check(
        "bounding box is 40 x 100 x 100",
        len(size) >= 3 and near(size[0], TOTAL_L, 0.2) and near(size[1], FLANGE_OD, 0.05) and near(size[2], FLANGE_OD, 0.05),
        f"size={size}",
    )
    bodies = await client.data("list_bodies")
    listed = bodies if isinstance(bodies, list) else bodies.get("bodies", [])
    check("exactly one solid body", len(listed) == 1, f"bodies={len(listed)}")

    errors = await client.data("check_errors")
    whats_wrong = errors.get("whats_wrong")
    check(
        "no What's Wrong entries",
        (isinstance(whats_wrong, dict) and not whats_wrong.get("count")) or not errors.get("errors"),
        json.dumps(errors)[:200],
    )

    # Title-block cells resolve against the model: TITLE <- Description,
    # MATERIAL <- Material, FINISH <- Finish.
    part_fields = (
        ("Description", "Bearing Flange Housing"),
        ("Material", "AL 6061-T6"),
        ("Finish", "Ra 1.6 BORE / Ra 3.2 FACES"),
    )
    written = 0
    for name, value in part_fields:
        result = await client.call("set_file_property", name=name, value=value)
        written += 1 if result.get("ok") else 0
    check("part model properties set for the title block", written == len(part_fields), f"{written}/{len(part_fields)}")

    shot = await client.call("capture_screenshot", path=str(PART_PNG), view="isometric")
    check("part screenshot captured", shot["ok"], str(PART_PNG))

    saved = await client.call("save_document", path=str(PART))
    check("part saved", saved["ok"], str(PART))
    return bool(saved["ok"])


# ------------------------------------------------------------------ drawing
async def standard_views(client: Client) -> dict:
    created = await client.call(
        "new_drawing", model=str(PART), paper_size="A3", scale=1.0, first_angle=True
    )
    check("A3 drawing created from the part", created["ok"])
    sheets = await client.data("list_drawing_sheets")
    check(
        "sheet is A3 landscape at 1:1 in millimetres",
        near((sheets.get("size_mm") or [0, 0])[0], 420.0, 0.5)
        and near((sheets.get("size_mm") or [0, 0])[1], 297.0, 0.5),
        json.dumps({"paper": sheets.get("paper_size"), "size": sheets.get("size_mm")}),
    )

    inserted = await client.call(
        "drawing_insert_standard_views",
        model=str(PART),
        front_mm=list(FRONT_POS),
        scale=1.0,
        projection="first_angle",
        gap_mm=VIEW_GAP,
    )
    check("first-angle front/top/right views inserted", inserted["ok"])

    views = (await client.data("list_drawing_views")).get("views", [])
    by_role = {
        view.get("orientation"): view
        for view in views
        if view.get("orientation") in {"front", "top", "right"}
    }
    check(
        "front, top and right roles identified",
        {"front", "top", "right"} <= set(by_role),
        json.dumps(sorted(by_role)),
    )
    if "front" not in by_role:
        return {}
    # Keep the first-angle arrangement (top below, right to the left) but set a
    # deliberate spacing so the sheet reads cleanly and nothing hits the frame.
    targets = {
        "front": FRONT_POS,
        "right": (FRONT_POS[0] - 98.6, FRONT_POS[1]),
        "top": (FRONT_POS[0], FRONT_POS[1] - 128.6),
    }
    for role, (x_mm, y_mm) in targets.items():
        view = by_role.get(role)
        if view is not None:
            await client.call("drawing_set_view", name=view["name"], x_mm=x_mm, y_mm=y_mm)

    views = (await client.data("list_drawing_views")).get("views", [])
    by_role = {
        view.get("orientation"): view
        for view in views
        if view.get("orientation") in {"front", "top", "right"}
    }
    front, top, right = by_role.get("front"), by_role.get("top"), by_role.get("right")
    f_box = (front or {}).get("outline_mm", {})
    t_box = (top or {}).get("outline_mm", {})
    r_box = (right or {}).get("outline_mm", {})
    check(
        "first-angle layout kept: top below front, right left of front",
        bool(f_box and t_box and r_box)
        and t_box["max"][1] < f_box["min"][1]
        and r_box["max"][0] < f_box["min"][0],
        json.dumps({"front": f_box, "top": t_box, "right": r_box}),
    )
    check(
        "front, top and right outlines sit inside the frame",
        all(inside_frame(box) for box in (f_box, t_box, r_box) if box),
        f"frame={FRAME}",
    )

    # Full section along the part axis: a horizontal cutting line through the
    # front view's vertical centre is the plane containing the axis, and the
    # 6X pattern always has a hole pair in that plane. Coordinates are sheet
    # millimetres; the tool converts them into the view's sketch space and
    # fails if the created view exposes no cut edges.
    fx, fy = front["position_mm"][:2]
    result = await client.call(
        "drawing_insert_section_view",
        parent_view=front["name"],
        x1_mm=f_box["min"][0] + 4.0,
        y1_mm=fy,
        x2_mm=f_box["max"][0] - 4.0,
        y2_mm=fy,
        place_x_mm=f_box["max"][0] + VIEW_GAP + 26.6,
        place_y_mm=fy,
        label="A",
        not_aligned=True,
    )
    section_view = (result.get("data", {}) or {}).get("view", {}) or {}
    check(
        "section A-A cuts the axis with verified cut edges",
        result["ok"]
        and section_view.get("type") == "section"
        and result.get("data", {}).get("cut_edges", 0) >= 1,
        json.dumps(
            {
                "view": section_view.get("name"),
                "cut_edges": result.get("data", {}).get("cut_edges"),
            }
        ),
    )
    if section_view.get("name"):
        await client.call(
            "drawing_set_view",
            name=section_view["name"],
            x_mm=f_box["max"][0] + VIEW_GAP + 26.6,
            y_mm=fy,
        )

    iso = await client.data("drawing_insert_view", view="isometric", x_mm=ISO_POS[0], y_mm=ISO_POS[1], model=str(PART))
    iso_name = iso.get("name")
    if iso_name:
        placed = await client.call("drawing_set_view", name=iso_name, x_mm=ISO_POS[0], y_mm=ISO_POS[1], scale=ISO_SCALE)
        check("isometric view inserted at 1:2", placed["ok"], str(iso_name))
    else:
        check("isometric view inserted at 1:2", False, "no view name")

    views = (await client.data("list_drawing_views")).get("views", [])
    model_views = [view for view in views if view.get("type") != "sheet"]
    boxes = [(view.get("name"), view.get("outline_mm") or {}) for view in model_views]
    check(
        "every model view outline is inside the frame",
        all(inside_frame(box) for _, box in boxes if box),
        json.dumps({name: box for name, box in boxes})[:300],
    )
    overlaps = []
    for index, (first_name, first_box) in enumerate(boxes):
        for second_name, second_box in boxes[index + 1 :]:
            if not first_box or not second_box:
                continue
            if (
                first_box["min"][0] < second_box["max"][0]
                and second_box["min"][0] < first_box["max"][0]
                and first_box["min"][1] < second_box["max"][1]
                and second_box["min"][1] < first_box["max"][1]
            ):
                overlaps.append((first_name, second_name))
    check("no model views overlap", not overlaps, json.dumps(overlaps))

    return {
        "front": front,
        "top": top,
        "right": right,
        "section": next(
            (view for view in views if view.get("name") == section_view.get("name")), {}
        ),
        "section_name": section_view.get("name"),
        "iso_name": iso_name,
    }


async def apply_properties(client: Client) -> None:
    fields = (
        ("Title", "Bearing Flange Housing"),
        ("DrawingNumber", "FLG-2001"),
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


def view_circles(edges: list[dict]) -> list[dict]:
    return [
        {"index": edge["index"], "radius_mm": edge.get("radius_mm"), "center_mm": edge.get("center_mm") or []}
        for edge in edges
        if edge.get("kind") == "circle"
    ]


async def edges_of(client: Client, name: str) -> list[dict]:
    data = await client.data("list_drawing_view_edges", view=name)
    return [
        edge
        for view in data.get("views", [])
        for edge in view.get("edges", [])
    ]


async def place_dimensions(client: Client, views: dict) -> dict:
    front = views["front"]
    right = views["right"]
    view_name = front["name"]
    right_name = right["name"]
    f_box = front["outline_mm"]
    r_box = right["outline_mm"]
    fcx, _ = box_centre(f_box)
    rcx, _ = box_centre(r_box)

    dims: dict = {"view": view_name}

    async def add(label, view, edge_indices, placement, expected):
        result = await client.call(
            "drawing_add_dimension", view=view, edge_indices=edge_indices, placement_mm=placement
        )
        value = result.get("data", {}).get("value")
        check(
            f"{label} reads {expected:.2f}",
            result["ok"] and near(value, expected),
            json.dumps(result.get("data", {}))[:200],
        )
        return result.get("data", {})

    # Front view: the axial lengths. Circles about the axis project to the
    # vertical lines that carry these dimensions.
    front_circles = view_circles(await edges_of(client, view_name))
    print(f"      front circles: {json.dumps(front_circles)}")
    face_edge = next((c for c in front_circles if near(c["center_mm"][0], 0.0, 0.5) and near(c["radius_mm"], R_FLANGE - CH_RIM, 0.5)), None)
    step_edge = next((c for c in front_circles if near(c["center_mm"][0], FLANGE_T, 0.5) and near(c["radius_mm"], R_FLANGE - CH_RIM, 0.5)), None)
    tip_edge = next((c for c in front_circles if near(c["center_mm"][0], TOTAL_L, 0.5) and near(c["radius_mm"], R_HUB, 0.5)), None)
    check(
        "front view axial edges identified (face, step, hub tip)",
        all(entry is not None for entry in (face_edge, step_edge, tip_edge)),
    )
    if all(entry is not None for entry in (face_edge, step_edge, tip_edge)):
        dims["length"] = await add("overall length", view_name, [face_edge["index"], tip_edge["index"]], [fcx, f_box["max"][1] + 12.0], TOTAL_L)
        dims["thickness"] = await add("flange thickness", view_name, [face_edge["index"], step_edge["index"]], [fcx, f_box["min"][1] - 13.0], FLANGE_T)
        dims["datum_a_edge"] = face_edge["index"]

    # Circular view: flange OD, hub tip face (dia 60 and the bore dia 28 on the
    # sharp tip edges), one bolt hole and the bolt circle.
    right_circles = view_circles(await edges_of(client, right_name))
    print(f"      right circles: {json.dumps(right_circles)}")
    od_circle = max(right_circles, key=lambda c: c["radius_mm"] or 0.0, default=None)
    tip_face = [c for c in right_circles if near(c["center_mm"][0], TOTAL_L, 0.5)]
    hub_circle = next((c for c in tip_face if near(c["radius_mm"], R_HUB, 0.01)), None)
    bore_circle = next((c for c in tip_face if near(c["radius_mm"], R_BORE, 0.01)), None)
    holes = [c for c in right_circles if near(c["radius_mm"], R_HOLE, 0.01)]
    check(
        "circular view shows the OD, hub tip, bore and six bolt holes",
        od_circle is not None
        and near(od_circle["radius_mm"], R_FLANGE, 0.01)
        and hub_circle is not None
        and bore_circle is not None
        and len(holes) == HOLE_COUNT,
        json.dumps({"od": od_circle, "hub": hub_circle, "bore": bore_circle, "holes": len(holes)})[:250],
    )
    if od_circle is not None:
        dims["od"] = await add("flange OD", right_name, [od_circle["index"]], [rcx + 45.0, r_box["max"][1] + 12.0], FLANGE_OD)
        dims["datum_b_edge"] = od_circle["index"]
    if hub_circle is not None:
        dims["hub_od"] = await add("hub OD", right_name, [hub_circle["index"]], [rcx + 10.0, r_box["max"][1] + 12.0], HUB_OD)
    if bore_circle is not None:
        dims["bore"] = await add("bore dia H7", right_name, [bore_circle["index"]], [rcx - 60.0, r_box["min"][1] - 13.0], BORE_D)
        dims["finish_edge"] = bore_circle["index"]
    if len(holes) == HOLE_COUNT:
        # The opposite hole pair is the one an axial pattern must dimension.
        # Seeded on the view's horizontal axis the pair projects 78 apart; on
        # the depth axis both holes project onto the same point, so the pair
        # with coincident projections and the smallest offset is the axial one.
        pair = None
        for index, first in enumerate(holes):
            for second in holes[index + 1 :]:
                distance = math.dist(first["center_mm"][:2], second["center_mm"][:2])
                if abs(distance - BCD) <= 0.5:
                    pair = (first, second)
        if pair is None:
            coincident = [
                (abs(holes[i]["center_mm"][1]), holes[i], holes[j])
                for i in range(len(holes))
                for j in range(i + 1, len(holes))
                if math.dist(holes[i]["center_mm"][:2], holes[j]["center_mm"][:2]) <= 0.5
            ]
            if coincident:
                pair = min(coincident, key=lambda entry: entry[0])[1:]
        check("opposite bolt holes identified for the B.C. dimension", pair is not None)
        if pair is not None:
            dims["bcd"] = await add("bolt circle", right_name, [pair[0]["index"], pair[1]["index"]], [rcx, r_box["min"][1] - 13.0], BCD)
            dims["hole"] = await add("bolt hole dia", right_name, [holes[0]["index"]], [r_box["max"][0] + 8.0, r_box["max"][1] - 26.0], HOLE_D)
            dims["fcf_edge"] = holes[0]["index"]
    return dims


async def apply_tolerances(client: Client, views: dict, dims: dict) -> None:
    right_name = views["right"]["name"]
    if dims.get("bore"):
        fit = await client.call(
            "drawing_set_dimension_tolerance",
            view=right_name,
            index=dims["bore"].get("index"),
            tolerance="fit",
            hole_fit="H7",
        )
        applied = fit.get("data", {}).get("tolerance", {})
        check(
            "bore dimension carries the ISO H7 hole fit",
            fit["ok"] and applied.get("hole_fit") == "H7" and not applied.get("shaft_fit"),
            json.dumps(applied),
        )
    if dims.get("hub_od"):
        prefix = await client.call(
            "drawing_set_annotation_text",
            view=right_name,
            index=dims["hub_od"].get("index"),
            prefix="\u00d8",
        )
        check(
            "hub OD linear dimension reads as a diameter",
            prefix["ok"] and prefix.get("data", {}).get("prefix") == "\u00d8",
            json.dumps(prefix.get("data", {}))[:160],
        )
    if dims.get("hole"):
        prefix = await client.call("drawing_set_annotation_text", view=right_name, index=dims["hole"].get("index"), prefix="6X ")
        suffix = await client.call("drawing_set_annotation_text", view=right_name, index=dims["hole"].get("index"), suffix=" EQ SP")
        check(
            "bolt hole callout reads 6X dia 9 EQ SP",
            prefix["ok"] and suffix["ok"] and prefix.get("data", {}).get("prefix") == "6X ",
            json.dumps(prefix.get("data", {}))[:160],
        )
    if dims.get("bcd"):
        suffix = await client.call("drawing_set_annotation_text", view=right_name, index=dims["bcd"].get("index"), suffix=" B.C.")
        check(
            "bolt circle dimension reads 78 B.C.",
            suffix["ok"] and suffix.get("data", {}).get("suffix") == " B.C.",
            json.dumps(suffix.get("data", {}))[:160],
        )


async def apply_annotations(client: Client, views: dict, dims: dict) -> None:
    front = views["front"]
    right = views["right"]
    f_box = front["outline_mm"]
    r_box = right["outline_mm"]
    rcx, rcy = box_centre(r_box)

    # One centre mark is the measured maximum on this build: AutoInsertCenterMarks2
    # marks a single circular edge of the circular view, and the selected-circle
    # path refuses bolt holes whose axis is normal to the sheet.
    marks = await client.call("drawing_insert_center_marks", view_name=right["name"])
    check(
        "centre mark on the circular view",
        marks["ok"] and marks.get("data", {}).get("marks_added", 0) >= 1,
        json.dumps(marks.get("data", {}))[:200],
    )

    # Datums: A = mating face (front view, edge-on), B = flange OD (circular
    # view). Datum tags snap along the edge, so the free coordinate separates
    # them from the geometry.
    datum_a = await client.call(
        "drawing_insert_datum",
        view=front["name"],
        edge_index=dims.get("datum_a_edge"),
        label="A",
        x_mm=f_box["min"][0] - 16.0,
        y_mm=box_centre(f_box)[1],
    )
    datum_b = await client.call(
        "drawing_insert_datum",
        view=right["name"],
        edge_index=dims.get("datum_b_edge"),
        label="B",
        x_mm=rcx - 30.0,
        y_mm=r_box["max"][1] + 8.0,
    )
    check(
        "datum A (mating face) and datum B (flange OD) attached",
        datum_a["ok"] and datum_b["ok"],
        json.dumps([datum_a.get("data"), datum_b.get("data")])[:300],
    )
    check(
        "datum tags are spaced apart",
        not any(
            result.get("data", {}).get("nearby_datum_tags")
            for result in (datum_a, datum_b)
        ),
        json.dumps([result.get("data", {}).get("text_position_mm") for result in (datum_a, datum_b)]),
    )

    fcf = await client.call(
        "drawing_insert_gtol",
        view=right["name"],
        edge_index=dims.get("fcf_edge"),
        symbol="position",
        tolerance="0.5",
        diameter=True,
        datums=["A", "B"],
        x_mm=rcx,
        y_mm=r_box["min"][1] - 31.0,
    )
    check(
        "position FCF 0.5 A|B on the bolt circle",
        fcf["ok"] and fcf.get("data", {}).get("frame_values", [])[:4] == ["0.5", "", "A", "B"],
        json.dumps(fcf.get("data", {}))[:200],
    )

    # Surface finish on the bore, with the scope spelled out (on this build the
    # symbol stores its value but renders it at zero height).
    if dims.get("finish_edge") is not None:
        finish = await client.call(
            "drawing_insert_surface_finish",
            view=right["name"],
            edge_index=dims.get("finish_edge"),
            roughness="1.6",
            x_mm=rcx - 26.0,
            y_mm=rcy + 26.0,
        )
        check(
            "surface finish symbol with stored Ra 1.6 on the bore",
            finish["ok"] and "1.6" in str(finish.get("data", {}).get("roughness", "")),
            json.dumps(finish.get("data", {}))[:200],
        )
        s_box = (views.get("section") or {}).get("outline_mm", {})
        finish_note = await client.call(
            "drawing_add_note",
            text="Ra 1.6 BORE \u00d828\nRa 3.2 ON OTHER MACHINED FACES",
            x_mm=s_box.get("min", [230.0, 100.0])[0] - 8.0,
            y_mm=s_box.get("min", [230.0, 100.0])[1] - 22.0,
            height_mm=3.5,
        )
        check("Ra value and scope spelled out beside the symbol", finish_note["ok"])
    else:
        check("surface finish symbol with stored Ra 1.6 on the bore", False, "no bore edge")

    note = await client.call(
        "drawing_add_note",
        text=(
            "UNLESS OTHERWISE SPECIFIED:\n"
            "GENERAL TOLERANCES ISO 2768-mK\n"
            "DEBURR AND BREAK SHARP EDGES"
        ),
        x_mm=12.0,
        y_mm=262.0,
        height_mm=3.5,
    )
    check(
        "general-tolerance and deburr note added",
        note["ok"] and "DEBURR" in str(note.get("data", {}).get("text")),
        json.dumps(note.get("data", {}))[:200],
    )

    table = await client.call("drawing_insert_revision_table")
    table_data = table.get("data", {})
    position = table_data.get("position_mm") or [0.0, 0.0]
    size = table_data.get("size_mm") or {}
    check(
        "revision table sits inside the frame",
        table["ok"]
        and table_data.get("inside_frame") is True
        and position[1] + float(size.get("height", 0.0)) <= 288.0
        and position[0] + float(size.get("width", 0.0)) <= 410.5,
        json.dumps(table_data)[:300],
    )
    revision = await client.call(
        "drawing_add_revision", revision="A", description="Initial release", date="2026-09-27"
    )
    check(
        "revision table current revision is A",
        table["ok"] and revision["ok"] and revision.get("data", {}).get("revision") == "A",
        json.dumps(revision.get("data", {}))[:200],
    )
    placement = revision.get("data", {}).get("placement") or {}
    check(
        "revision table stays inside the frame after the row is added",
        placement.get("inside_frame") is True,
        json.dumps(placement)[:200],
    )


async def release_check(client: Client, views: dict) -> None:
    audit_result = await client.call("drawing_layout_audit")
    audit = audit_result.get("data", {})
    counts = audit.get("counts", {})
    check(
        "annotation layout audit is clean",
        audit_result["ok"] and counts.get("collisions") == 0 and counts.get("off_frame") == 0,
        json.dumps(
            {
                "counts": counts,
                "collisions": audit.get("collisions", [])[:3],
                "off_frame": audit.get("off_frame", [])[:3],
            }
        )[:400],
    )

    preflight = await client.call("drawing_preflight")
    check("preflight passes", preflight["ok"], json.dumps(preflight.get("data", {}).get("checks"))[:200])

    manifest = await client.call("drawing_manifest")
    check("manifest collected", manifest["ok"])

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
        json.dumps(validation.get("errors") or validation.get("checks"))[:300],
    )
    check(
        "validation sees readable dimensions",
        validation.get("readable_dimensions", 0) >= 7,
        f"readable={validation.get('readable_dimensions')}",
    )
    check(
        "validation sees five model views",
        validation.get("model_view_count", 0) >= 5,
        f"model_views={validation.get('model_view_count')}",
    )

    # Save first: the DWG NO. cell links to $PRP:"SW-File Name", so the
    # revision-free file name must be set before the exports are made.
    saved = await client.call("save_document", path=str(DRAWING))
    check("drawing saved as the revision-free number FLG-2001", saved["ok"])

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
                if annotation.get("property_linked_text") == f'${code}:"{name}"'
            ),
            None,
        )

    for code, name, expected in (
        ("PRPSHEET", "Description", "Bearing Flange Housing"),
        ("PRPSHEET", "Material", "AL 6061-T6"),
        ("PRPSHEET", "Finish", "Ra 1.6 BORE / Ra 3.2 FACES"),
        ("PRP", "SW-File Name", "FLG-2001"),
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

    frames = [
        annotation for annotation in flat if annotation.get("type") == "geometric_tolerance"
    ]
    hole_frames = [
        frame for frame in frames if frame.get("frame_values", [])[:4] == ["0.5", "", "A", "B"]
    ]
    check("exactly one position FCF for the bolt circle", len(hole_frames) == 1, json.dumps(hole_frames)[:200])

    note_texts = [
        annotation.get("resolved_text") or annotation.get("text") or ""
        for annotation in flat
        if annotation.get("type") == "note"
    ]
    check("deburr note present", any("DEBURR" in text for text in note_texts))
    check("Ra 1.6 bore scope note present", any("Ra 1.6 BORE" in text for text in note_texts))
    check(
        "surface finish symbol stores Ra 1.6",
        any(
            annotation.get("type") == "surface_finish" and "1.6" in str(annotation.get("text", ""))
            for annotation in flat
        ),
    )
    hole_callout = [
        annotation
        for annotation in flat
        if annotation.get("type") == "dimension"
        and annotation.get("value") == HOLE_D
        and str(annotation.get("prefix", "")).startswith("6X")
    ]
    check(
        "hole callout reads 6X ... EQ SP",
        len(hole_callout) == 1 and hole_callout[0].get("suffix") == " EQ SP",
        json.dumps(hole_callout)[:200],
    )
    fit_callout = [
        annotation
        for annotation in flat
        if annotation.get("type") == "dimension" and annotation.get("value") == BORE_D
    ]
    check(
        "bore dimension carries H7 on the sheet",
        len(fit_callout) == 1
        and (fit_callout[0].get("tolerance") or {}).get("hole_fit") == "H7",
        json.dumps(fit_callout)[:200],
    )

    exported = await client.call("export_document", path=str(PDF))
    check("PDF exported", exported["ok"])
    verified = await client.call("verify_export", path=str(PDF))
    details = verified.get("data", {}).get("details", {})
    check(
        "PDF verifies as one consistent page",
        verified["ok"] and details.get("page_count") == 1 and details.get("page_count_consistent") is True,
        json.dumps(details)[:200],
    )
    image = await client.call("export_document", path=str(PNG))
    check("PNG sheet image exported", image["ok"])
    dxf = await client.call("export_document", path=str(DXF))
    dxf_verified = await client.call("verify_export", path=str(DXF))
    dxf_details = dxf_verified.get("data", {}).get("details", {})
    check(
        "DXF exported with entities and extents",
        dxf["ok"]
        and dxf_verified["ok"]
        and (dxf_details.get("entities") or 0) > 0
        and bool(dxf_details.get("extents_mm")),
        json.dumps(dxf_details)[:200],
    )

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
        json.dumps(revalidation.get("errors") or revalidation.get("checks"))[:300],
    )


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
                    views = await standard_views(client)
                    if views:
                        await apply_properties(client)
                        dims = await place_dimensions(client, views)
                        await apply_tolerances(client, views, dims)
                        await apply_annotations(client, views, dims)
                        await release_check(client, views)
                    else:
                        print("view set incomplete; stopping")
            finally:
                await close_workspace(client, keep=baseline)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    summary = {
        "checks": [{"name": name, "passed": ok, "detail": detail} for name, ok, detail in CHECKS],
        "passed": passed,
        "total": len(CHECKS),
        "paths": {
            "part": str(PART),
            "drawing": str(DRAWING),
            "pdf": str(PDF),
            "png": str(PNG),
            "dxf": str(DXF),
            "part_png": str(PART_PNG),
        },
    }
    (OUTPUT / "demo-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    print(f"drawing: {DRAWING}")
    print(f"pdf:     {PDF}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
