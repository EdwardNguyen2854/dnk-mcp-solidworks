"""Core-tier tools: the everyday modelling loop."""
from __future__ import annotations

from typing import Any

from .. import capabilities as capabilities_module
from .. import registry
from ..com.worker import run
from ..domain import documents, export, features, inspect, session, sketch
from ..errors import ok
from ..registry import array, boolean, integer, number, obj, string

END_CONDITIONS = ["blind", "through_all", "through_all_both", "up_to_next", "mid_plane"]


def envelope(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and ("data" in result or "evidence" in result):
        images = result.pop("_images", None)
        return ok(
            result.get("data"),
            evidence=result.get("evidence"),
            images=images,
        )
    return ok(result)


@registry.tool(
    "get_status",
    "Confirm the SOLIDWORKS connection and report the active document.",
    obj({}),
    tags=("session",),
)
def get_status(args: dict) -> dict:
    return ok(run(documents.status))


@registry.tool(
    "get_capabilities",
    "Report server version, tool tier, binding, templates, paths and policy, "
    "plus the live SOLIDWORKS revision and active document.",
    obj({}),
    tags=("session",),
)
def get_capabilities(args: dict) -> dict:
    return ok(capabilities_module.collect())


@registry.tool(
    "search_tools",
    "Find tools by keyword across names, descriptions and tags.",
    obj({"query": string("space-separated search terms")}, required=("query",)),
    tags=("session",),
)
def search_tools(args: dict) -> dict:
    return ok({"results": registry.search(args["query"])})


@registry.tool(
    "new_document",
    "Create a new empty part, assembly or drawing from the default template.",
    obj(
        {
            "kind": string("document kind", enum=["part", "assembly", "drawing"]),
            "template": string("optional explicit template path", default=None),
        },
        required=("kind",),
    ),
    tags=("documents",),
)
def new_document(args: dict) -> dict:
    return ok(run(lambda: documents.new_document(args["kind"], args.get("template"))))


@registry.tool(
    "open_document",
    "Open a .sldprt/.sldasm/.slddrw file. Read paths are not sandboxed.",
    obj({"path": string("absolute path to the document")}, required=("path",)),
    tags=("documents",),
)
def open_document(args: dict) -> dict:
    return ok(run(lambda: documents.open_document(args["path"])))


@registry.tool(
    "save_document",
    "Save the active document. With a path it is save-as (sandboxed); without "
    "one the existing path is used.",
    obj(
        {
            "path": string("save-as target (optional)", default=None),
            "overwrite": boolean("allow replacing an existing file", default=True),
        }
    ),
    tags=("documents",),
)
def save_document(args: dict) -> dict:
    return ok(
        run(
            lambda: documents.save_document(
                args.get("path"), args.get("overwrite", True)
            )
        )
    )


@registry.tool(
    "close_document",
    "Close the active document. save=false discards unsaved changes.",
    obj({"save": boolean("save before closing", default=False)}),
    tags=("documents",),
)
def close_document(args: dict) -> dict:
    return ok(run(lambda: documents.close_document(args.get("save", False))))


@registry.tool(
    "list_documents",
    "List every document open in SOLIDWORKS.",
    obj({}),
    tags=("documents",),
)
def list_documents(args: dict) -> dict:
    return ok(run(documents.list_open_documents))


@registry.tool(
    "get_active_document_info",
    "Title, path, type and dirty state of the active document.",
    obj({}),
    tags=("documents",),
)
def get_active_document_info(args: dict) -> dict:
    def job() -> dict:
        _, doc, kind = session.active_doc()
        return {"document": session.doc_info(doc), "kind": kind}

    return ok(run(job))


@registry.tool(
    "rebuild_document",
    "Force a rebuild and report What's Wrong.",
    obj({"top_only": boolean("rebuild only top-level features", default=False)}),
    tags=("documents",),
)
def rebuild_document(args: dict) -> dict:
    return ok(run(lambda: documents.rebuild_document(args.get("top_only", False))))


@registry.tool(
    "set_view",
    "Set a standard view and zoom to fit.",
    obj(
        {
            "view": string(
                "standard view",
                enum=["front", "back", "left", "right", "top", "bottom",
                      "isometric", "trimetric", "dimetric"],
            )
        },
        required=("view",),
    ),
    tags=("view",),
)
def set_view(args: dict) -> dict:
    def job() -> dict:
        _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
        session.set_view(doc, args["view"])
        return {"view": args["view"]}

    return ok(run(job))


@registry.tool(
    "capture_screenshot",
    "Save a view as an image and return it as image content so the model can "
    "be looked at.",
    obj(
        {
            "path": string("optional output path (sandboxed)", default=None),
            "view": string(
                "standard view to apply first",
                enum=["front", "back", "left", "right", "top", "bottom",
                      "isometric", "trimetric", "dimetric"],
                default="isometric",
            ),
            "width": integer("image width in pixels", default=1600),
            "height": integer("image height in pixels", default=900),
        }
    ),
    tags=("view",),
)
def capture_screenshot(args: dict) -> dict:
    result = run(
        lambda: export.capture_screenshot(
            args.get("path"),
            args.get("view", "isometric"),
            args.get("width", 1600),
            args.get("height", 900),
        )
    )
    return envelope(result)


@registry.tool(
    "export_document",
    "Export the active document. Formats: step, iges, stl, 3mf, parasolid, "
    "pdf, dxf, dwg, png, jpg, bmp, tif.",
    obj(
        {
            "path": string("output path (sandboxed)"),
            "file_format": string(
                "explicit format; default is taken from the path extension",
                default=None,
            ),
        },
        required=("path",),
    ),
    tags=("export",),
)
def export_document(args: dict) -> dict:
    return ok(
        run(
            lambda: export.export_document(args["path"], args.get("file_format"))
        )
    )


@registry.tool(
    "list_features",
    "List the feature tree: name and type of every feature.",
    obj({}),
    tags=("inspect",),
)
def list_features(args: dict) -> dict:
    def job() -> dict:
        _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
        features_list = session.list_feature_infos(doc)
        return {"features": features_list, "count": len(features_list)}

    return ok(run(job))


@registry.tool(
    "get_mass_properties",
    "Measured volume, mass, density, surface area and centre of mass.",
    obj({}),
    tags=("inspect",),
)
def get_mass_properties(args: dict) -> dict:
    return ok(run(inspect.mass_properties))


@registry.tool(
    "get_bounding_box",
    "Tight bounding box of a part in model coordinates, in millimetres.",
    obj({}),
    tags=("inspect",),
)
def get_bounding_box(args: dict) -> dict:
    return ok(run(inspect.bounding_box))


@registry.tool(
    "check_errors",
    "What SOLIDWORKS thinks is wrong: failing features, error and warning "
    "codes.",
    obj({}),
    tags=("inspect",),
)
def check_errors(args: dict) -> dict:
    def job() -> dict:
        _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
        return inspect.whats_wrong(doc)

    return ok(run(job))


@registry.tool(
    "create_reference_plane",
    "Create a reference plane: offset from a plane or planar face, midplane "
    "between two references, or at an angle from a plane about a straight "
    "edge. Use the returned plane name in create_sketch or a pattern.",
    obj(
        {
            "kind": string(
                "construction", enum=["offset", "midplane", "angle"], default="offset"
            ),
            "plane": string(
                "base plane: front, top, right, or an exact plane name", default=None
            ),
            "face_index": integer(
                "planar face index from list_faces as the base reference", default=None
            ),
            "second_plane": string("second plane for midplane", default=None),
            "second_face_index": integer(
                "second planar face for midplane", default=None
            ),
            "distance_mm": number("offset distance (mm)", default=None),
            "angle_deg": number("angle for kind=angle (degrees)", default=None),
            "axis_edge": integer(
                "straight edge index from list_edges, for kind=angle", default=None
            ),
            "flip": boolean("flip the offset to the other side", default=False),
            "name": string("optional name for the new plane", default=None),
        }
    ),
    tags=("sketch", "reference"),
)
def create_reference_plane(args: dict) -> dict:
    result = run(
        lambda: features.create_reference_plane(
            args.get("kind", "offset"),
            args.get("plane"),
            args.get("face_index"),
            args.get("second_plane"),
            args.get("second_face_index"),
            args.get("distance_mm"),
            args.get("angle_deg"),
            args.get("axis_edge"),
            args.get("flip", False),
            args.get("name"),
        )
    )
    return envelope(result)


@registry.tool(
    "list_reference_planes",
    "List the reference planes and axes in the active part, so a sketch or "
    "pattern can target one by exact name.",
    obj({}),
    tags=("sketch", "reference", "inspect"),
)
def list_reference_planes(args: dict) -> dict:
    return ok(run(features.list_reference_planes))


@registry.tool(
    "create_sketch",
    "Start a sketch on a named plane (front/top/right or exact plane name) or "
    "on a planar face selected by face_index from list_faces.",
    obj(
        {
            "plane": string(
                "plane to sketch on: front, top, right, or an exact plane name "
                "returned by list_features",
                default=None,
            ),
            "face_index": integer(
                "index from list_faces to sketch on a planar face", default=None
            ),
        }
    ),
    tags=("sketch",),
)
def create_sketch(args: dict) -> dict:
    return ok(
        run(lambda: sketch.create_sketch(args.get("plane"), args.get("face_index")))
    )


@registry.tool(
    "exit_sketch",
    "Close the active sketch and rebuild. Drawing view sketches cannot be "
    "closed on SW2026 SP0.0; the result reports view_sketch=true and the "
    "sketch is consumed by the next section or detail command.",
    obj({}),
    tags=("sketch",),
)
def exit_sketch(args: dict) -> dict:
    return ok(run(sketch.exit_sketch))


@registry.tool(
    "sketch_rectangle",
    "Draw a rectangle in the active sketch. Without centered, (x1,y1) and "
    "(x2,y2) are opposite corners; with centered, (x1,y1) is the centre.",
    obj(
        {
            "x1_mm": number("first x (mm)"),
            "y1_mm": number("first y (mm)"),
            "x2_mm": number("second x (mm)"),
            "y2_mm": number("second y (mm)"),
            "centered": boolean("treat (x1,y1) as the centre", default=False),
        },
        required=("x1_mm", "y1_mm", "x2_mm", "y2_mm"),
    ),
    tags=("sketch",),
)
def sketch_rectangle(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.rectangle(
                args["x1_mm"],
                args["y1_mm"],
                args["x2_mm"],
                args["y2_mm"],
                args.get("centered", False),
            )
        )
    )


@registry.tool(
    "sketch_circle",
    "Draw a circle in the active sketch.",
    obj(
        {
            "center_x_mm": number("centre x (mm)"),
            "center_y_mm": number("centre y (mm)"),
            "radius_mm": number("radius (mm)", exclusiveMinimum=0),
        },
        required=("center_x_mm", "center_y_mm", "radius_mm"),
    ),
    tags=("sketch",),
)
def sketch_circle(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.circle(
                args["center_x_mm"], args["center_y_mm"], args["radius_mm"]
            )
        )
    )


@registry.tool(
    "sketch_line",
    "Draw a line (or centerline with construction=true) in the active sketch.",
    obj(
        {
            "x1_mm": number("start x (mm)"),
            "y1_mm": number("start y (mm)"),
            "x2_mm": number("end x (mm)"),
            "y2_mm": number("end y (mm)"),
            "construction": boolean("draw as construction/centerline", default=False),
        },
        required=("x1_mm", "y1_mm", "x2_mm", "y2_mm"),
    ),
    tags=("sketch",),
)
def sketch_line(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.line(
                args["x1_mm"],
                args["y1_mm"],
                args["x2_mm"],
                args["y2_mm"],
                args.get("construction", False),
            )
        )
    )


@registry.tool(
    "sketch_polygon",
    "Draw a regular polygon in the active sketch.",
    obj(
        {
            "center_x_mm": number("centre x (mm)"),
            "center_y_mm": number("centre y (mm)"),
            "radius_mm": number("circumscribed/inscribed radius (mm)"),
            "sides": integer("number of sides (>= 3)", minimum=3),
            "inscribed": boolean("inscribed in the radius", default=True),
        },
        required=("center_x_mm", "center_y_mm", "radius_mm", "sides"),
    ),
    tags=("sketch",),
)
def sketch_polygon(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.polygon(
                args["center_x_mm"],
                args["center_y_mm"],
                args["radius_mm"],
                args["sides"],
                args.get("inscribed", True),
            )
        )
    )


@registry.tool(
    "sketch_arc",
    "Draw an arc in the active sketch from its centre, start point and end "
    "point. direction 1 is counter-clockwise, -1 clockwise; the start point "
    "sets the radius.",
    obj(
        {
            "center_x_mm": number("centre x (mm)"),
            "center_y_mm": number("centre y (mm)"),
            "start_x_mm": number("start point x (mm)"),
            "start_y_mm": number("start point y (mm)"),
            "end_x_mm": number("end point x (mm)"),
            "end_y_mm": number("end point y (mm)"),
            "direction": integer(
                "sweep direction", enum=[1, -1], default=1
            ),
        },
        required=(
            "center_x_mm", "center_y_mm", "start_x_mm", "start_y_mm",
            "end_x_mm", "end_y_mm",
        ),
    ),
    tags=("sketch",),
)
def sketch_arc(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.arc(
                args["center_x_mm"],
                args["center_y_mm"],
                args["start_x_mm"],
                args["start_y_mm"],
                args["end_x_mm"],
                args["end_y_mm"],
                args.get("direction", 1),
            )
        )
    )


@registry.tool(
    "sketch_arc_3point",
    "Draw an arc through three points in the active sketch: start, end and a "
    "point on the arc.",
    obj(
        {
            "x1_mm": number("start x (mm)"),
            "y1_mm": number("start y (mm)"),
            "x2_mm": number("end x (mm)"),
            "y2_mm": number("end y (mm)"),
            "x3_mm": number("point on the arc x (mm)"),
            "y3_mm": number("point on the arc y (mm)"),
        },
        required=("x1_mm", "y1_mm", "x2_mm", "y2_mm", "x3_mm", "y3_mm"),
    ),
    tags=("sketch",),
)
def sketch_arc_3point(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.three_point_arc(
                args["x1_mm"],
                args["y1_mm"],
                args["x2_mm"],
                args["y2_mm"],
                args["x3_mm"],
                args["y3_mm"],
            )
        )
    )


@registry.tool(
    "sketch_ellipse",
    "Draw an ellipse in the active sketch from its centre, a major-axis point "
    "and a minor-axis point.",
    obj(
        {
            "center_x_mm": number("centre x (mm)"),
            "center_y_mm": number("centre y (mm)"),
            "major_x_mm": number("major-axis endpoint x (mm)"),
            "major_y_mm": number("major-axis endpoint y (mm)"),
            "minor_x_mm": number("minor-axis endpoint x (mm)"),
            "minor_y_mm": number("minor-axis endpoint y (mm)"),
        },
        required=(
            "center_x_mm", "center_y_mm", "major_x_mm", "major_y_mm",
            "minor_x_mm", "minor_y_mm",
        ),
    ),
    tags=("sketch",),
)
def sketch_ellipse(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.ellipse(
                args["center_x_mm"],
                args["center_y_mm"],
                args["major_x_mm"],
                args["major_y_mm"],
                args["minor_x_mm"],
                args["minor_y_mm"],
            )
        )
    )


@registry.tool(
    "sketch_point",
    "Draw a sketch point in the active sketch, for use as a pierce or hole "
    "position reference.",
    obj(
        {"x_mm": number("x (mm)"), "y_mm": number("y (mm)")},
        required=("x_mm", "y_mm"),
    ),
    tags=("sketch",),
)
def sketch_point(args: dict) -> dict:
    return ok(run(lambda: sketch.point(args["x_mm"], args["y_mm"])))


@registry.tool(
    "sketch_construction",
    "Toggle selected sketch segments between normal and construction geometry.",
    obj(
        {
            "segment_indices": array(
                "indices from list_sketch_segments", {"type": "integer"}
            ),
            "construction": boolean("true makes construction geometry", default=True),
        },
        required=("segment_indices",),
    ),
    tags=("sketch",),
)
def sketch_construction(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.set_construction(
                args["segment_indices"], args.get("construction", True)
            )
        )
    )


@registry.tool(
    "list_sketches",
    "List every sketch feature with segment count and constrained status; the "
    "feed for edit_sketch.",
    obj({}),
    tags=("sketch", "inspect"),
)
def list_sketches(args: dict) -> dict:
    return ok(run(sketch.list_sketches))


@registry.tool(
    "list_sketch_segments",
    "List segments in the active sketch with indices for selection and "
    "dimensioning.",
    obj({}),
    tags=("sketch",),
)
def list_sketch_segments(args: dict) -> dict:
    return ok(run(sketch.list_sketch_segments))


@registry.tool(
    "sketch_add_dimension",
    "Add a dimension to the selected sketch segments and optionally drive it "
    "to value_mm.",
    obj(
        {
            "segment_indices": array(
                "indices from list_sketch_segments", {"type": "integer"}
            ),
            "value_mm": number("driving value (mm); omit to keep it driven", default=None),
            "placement_mm": array(
                "dimension text placement [x, y] in mm",
                {"type": "number"},
                default=None,
            ),
        },
        required=("segment_indices",),
    ),
    tags=("sketch",),
)
def sketch_add_dimension(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.add_dimension(
                args["segment_indices"],
                args.get("value_mm"),
                args.get("placement_mm"),
            )
        )
    )


@registry.tool(
    "sketch_add_relation",
    "Add a relation to selected sketch segments. Common relations: "
    "sgHORIZONTAL, sgVERTICAL, sgCOINCIDENT, sgTANGENT, sgEQUAL, "
    "sgPARALLEL, sgPERPENDICULAR, sgCONCENTRIC, sgFIXED.",
    obj(
        {
            "relation": string("SOLIDWORKS relation token, e.g. sgHORIZONTAL"),
            "segment_indices": array(
                "indices from list_sketch_segments", {"type": "integer"}
            ),
        },
        required=("relation", "segment_indices"),
    ),
    tags=("sketch",),
)
def sketch_add_relation(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.add_relation(args["relation"], args["segment_indices"])
        )
    )


@registry.tool(
    "list_dimensions",
    "Read back the driving dimensions of the document, with the full_name "
    "values set_dimension accepts.",
    obj(
        {
            "feature_name": string(
                "only list dimensions of this feature or sketch", default=None
            )
        }
    ),
    tags=("sketch", "inspect"),
)
def list_dimensions(args: dict) -> dict:
    return ok(run(lambda: sketch.list_dimensions(args.get("feature_name"))))


@registry.tool(
    "set_dimension",
    "Drive an existing dimension by its full name from list_dimensions. Linear "
    "dimensions take value_mm, angular ones value_deg.",
    obj(
        {
            "full_name": string("dimension name, e.g. 'D1@Sketch1'"),
            "value_mm": number("new linear value (mm)", default=None),
            "value_deg": number("new angular value (degrees)", default=None),
        },
        required=("full_name",),
    ),
    tags=("sketch",),
)
def set_dimension(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.set_dimension(
                args["full_name"], args.get("value_mm"), args.get("value_deg")
            )
        )
    )


def _extrude_schema() -> dict[str, Any]:
    return {
        "depth_mm": number("depth (mm); required unless through_all_both", default=None),
        "end_condition": string(
            "end condition", enum=END_CONDITIONS, default="blind"
        ),
        "draft_deg": number("draft angle (degrees)", default=0),
        "reverse": boolean("flip the direction", default=False),
        "both_directions": boolean("symmetric in both directions", default=False),
        "name": string("feature name override", default=None),
    }


@registry.tool(
    "boss_extrude",
    "Extrude the sketch shown on screen as a boss. The last-created or "
    "just-closed sketch is used; exit_sketch first is recommended.",
    obj(_extrude_schema()),
    tags=("features",),
)
def boss_extrude(args: dict) -> dict:
    result = run(
        lambda: features.boss_extrude(
            args.get("depth_mm"),
            args.get("end_condition", "blind"),
            args.get("draft_deg", 0),
            args.get("reverse", False),
            args.get("both_directions", False),
            args.get("name"),
        )
    )
    return envelope(result)


@registry.tool(
    "cut_extrude",
    "Cut-extrude the sketch shown on screen. through_all_both is translated "
    "internally to a two-direction through-all cut. If the requested direction "
    "removes nothing, the other direction is tried automatically.",
    obj(
        {
            **_extrude_schema(),
            "normal_cut": boolean("use normal cut (sheet metal)", default=False),
            "flip_side": boolean(
                "remove everything outside the profile instead", default=False
            ),
        }
    ),
    tags=("features",),
)
def cut_extrude(args: dict) -> dict:
    result = run(
        lambda: features.cut_extrude(
            args.get("depth_mm"),
            args.get("end_condition", "blind"),
            args.get("draft_deg", 0),
            args.get("reverse", False),
            args.get("both_directions", False),
            args.get("normal_cut", False),
            args.get("flip_side", False),
            args.get("name"),
        )
    )
    return envelope(result)


@registry.tool(
    "revolve",
    "Revolve the sketch shown on screen around its centerline (or a selected "
    "axis). Use a construction line as the axis.",
    obj(
        {
            "angle_deg": number("revolution angle (degrees)", default=360),
            "reverse": boolean("flip the direction", default=False),
            "name": string("feature name override", default=None),
        }
    ),
    tags=("features",),
)
def revolve(args: dict) -> dict:
    result = run(
        lambda: features.revolve(
            args.get("angle_deg", 360),
            args.get("reverse", False),
            args.get("name"),
        )
    )
    return envelope(result)
