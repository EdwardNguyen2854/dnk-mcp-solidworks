"""Extended-tier tools: topology, finishing features, checkpoints."""
from __future__ import annotations

from .. import registry
from ..com.worker import run
from ..domain import (
    artifacts,
    assemblies,
    documents,
    drawing_audit,
    drawing_iso,
    drawings,
    features,
    inspect,
    sketch,
)
from ..errors import ok
from ..registry import array, boolean, integer, number, obj, string
from ..tx import checkpoint
from .core import envelope

MATE_TYPES = ["coincident", "concentric", "perpendicular", "parallel",
              "tangent", "distance", "angle"]
DIRECTIONS = ["+x", "-x", "+y", "-y", "+z", "-z"]


@registry.tool(
    "list_faces",
    "List planar/curved faces of every body with indices for selection. "
    "Filters narrow the listing but the returned indices are still the global "
    "ones shell, draft and measure accept.",
    obj(
        {
            "body_type": string(
                "body filter", enum=["all", "solid", "sheet", "wire"], default="all"
            ),
            "surface_type": string(
                "only faces of this surface type",
                enum=["plane", "cylinder", "cone", "sphere", "torus", "other"],
                default=None,
            ),
            "min_area_mm2": number(
                "only faces at least this large (mm^2)", minimum=0, default=None
            ),
            "normal": string(
                "only faces whose normal points this way",
                enum=["+x", "-x", "+y", "-y", "+z", "-z"],
                default=None,
            ),
        }
    ),
    tier="extended",
    tags=("inspect",),
)
def list_faces(args: dict) -> dict:
    def job() -> dict:
        faces = inspect.list_faces(
            body_type=args.get("body_type", "all"),
            surface_type=args.get("surface_type"),
            min_area_mm2=args.get("min_area_mm2"),
            normal=args.get("normal"),
        )
        return {"faces": faces, "count": len(faces)}

    return ok(run(job))


@registry.tool(
    "list_edges",
    "List edges of every body with indices for selection (fillet, chamfer). "
    "Filters narrow the listing but the returned indices are still the global "
    "ones fillet, chamfer and measure accept.",
    obj(
        {
            "body_type": string(
                "body filter", enum=["all", "solid", "sheet", "wire"], default="all"
            ),
            "curve_type": string(
                "only edges of this curve type",
                enum=sorted(inspect.CURVE_TYPES),
                default=None,
            ),
            "min_length_mm": number(
                "only edges at least this long (mm)", minimum=0, default=None
            ),
        }
    ),
    tier="extended",
    tags=("inspect",),
)
def list_edges(args: dict) -> dict:
    def job() -> dict:
        edges = inspect.list_edges(
            body_type=args.get("body_type", "all"),
            curve_type=args.get("curve_type"),
            min_length_mm=args.get("min_length_mm"),
        )
        return {"edges": edges, "count": len(edges)}

    return ok(run(job))


@registry.tool(
    "list_bodies",
    "List solid bodies with box, face count and edge count.",
    obj({}),
    tier="extended",
    tags=("inspect",),
)
def list_bodies(args: dict) -> dict:
    def job() -> dict:
        bodies = inspect.list_bodies()
        return {"bodies": bodies, "count": len(bodies)}

    return ok(run(job))


@registry.tool(
    "combine_bodies",
    "Combine one tool body into a main body. Indices come from the current "
    "list_bodies result; supported operations are add, subtract and common.",
    obj(
        {
            "operation": string(
                "combine operation", enum=["add", "subtract", "common"]
            ),
            "main_body_index": integer(
                "main body index from list_bodies", minimum=0
            ),
            "tool_body_index": integer(
                "single tool body index from list_bodies", minimum=0
            ),
        },
        required=("operation", "main_body_index", "tool_body_index"),
    ),
    tier="extended",
    tags=("features", "bodies"),
)
def combine_bodies(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.combine_bodies(
            args["operation"], args["main_body_index"], args["tool_body_index"]
        )

    return envelope(run(job))


@registry.tool(
    "fillet",
    "Round the selected edges (kind=constant, indices from list_edges) or "
    "blend between two faces (kind=face, two face_indices that meet at the "
    "edge).",
    obj(
        {
            "radius_mm": number("fillet radius (mm)", exclusiveMinimum=0),
            "kind": string(
                "fillet kind",
                enum=["constant", "face"],
                default="constant",
            ),
            "edge_indices": array(
                "edge indices from list_edges (kind=constant)",
                {"type": "integer"},
                default=None,
            ),
            "face_indices": array(
                "exactly two face indices from list_faces (kind=face)",
                {"type": "integer"},
                default=None,
            ),
            "propagate": boolean(
                "extend the fillet along tangent edges", default=True
            ),
            "name": string("feature name override", default=None),
        },
        required=("radius_mm",),
    ),
    tier="extended",
    tags=("features",),
)
def fillet(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.fillet(
            args["radius_mm"],
            args.get("edge_indices"),
            args.get("propagate", True),
            args.get("name"),
            args.get("kind", "constant"),
            args.get("face_indices"),
        )

    return envelope(run(job))


@registry.tool(
    "chamfer",
    "Chamfer the selected edges. kind=equal is a 45-degree equal-distance "
    "chamfer; kind=angle_distance uses distance_mm along the face and "
    "angle_deg from it; kind=distance_distance uses distance_mm and "
    "second_distance_mm. Indices come from list_edges.",
    obj(
        {
            "distance_mm": number("chamfer distance (mm)", exclusiveMinimum=0),
            "edge_indices": array(
                "edge indices from list_edges", {"type": "integer"}
            ),
            "kind": string(
                "chamfer kind",
                enum=["equal", "angle_distance", "distance_distance"],
                default="equal",
            ),
            "angle_deg": number("chamfer angle (degrees)", default=45),
            "second_distance_mm": number(
                "second distance (mm) for kind=distance_distance", default=None
            ),
            "name": string("feature name override", default=None),
        },
        required=("distance_mm", "edge_indices"),
    ),
    tier="extended",
    tags=("features",),
)
def chamfer(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.chamfer(
            args["distance_mm"],
            args["edge_indices"],
            args.get("angle_deg", 45),
            args.get("name"),
            args.get("kind", "equal"),
            args.get("second_distance_mm"),
        )

    return envelope(run(job))


@registry.tool(
    "shell",
    "Hollow the part to a wall thickness, opening the selected faces (or none "
    "for a closed shell).",
    obj(
        {
            "thickness_mm": number("wall thickness (mm)", exclusiveMinimum=0),
            "face_indices": array(
                "faces to remove (from list_faces); omit for closed shell",
                {"type": "integer"},
                default=None,
            ),
            "outward": boolean("thicken outward", default=False),
            "name": string("feature name override", default=None),
        },
        required=("thickness_mm",),
    ),
    tier="extended",
    tags=("features",),
)
def shell(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.shell(
            args["thickness_mm"],
            args.get("face_indices"),
            args.get("outward", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "linear_pattern",
    "Repeat features along one or two directions. Seed features come from "
    "list_features; each direction is a straight edge index from list_edges or "
    "a plane name.",
    obj(
        {
            "feature_names": array(
                "features to repeat (from list_features)", {"type": "string"}
            ),
            "spacing_mm": number("spacing along direction 1 (mm)", exclusiveMinimum=0),
            "direction_edge": integer(
                "straight edge index for direction 1 (from list_edges)", default=None
            ),
            "direction_plane": string(
                "plane name for direction 1 (front/top/right or exact)", default=None
            ),
            "count": integer(
                "instances in direction 1, including the seed", minimum=2, default=2
            ),
            "reverse": boolean("flip direction 1", default=False),
            "direction2_edge": integer(
                "straight edge index for direction 2", default=None
            ),
            "direction2_plane": string("plane name for direction 2", default=None),
            "spacing2_mm": number("spacing along direction 2 (mm)", default=0),
            "count2": integer("instances in direction 2", minimum=1, default=1),
            "reverse2": boolean("flip direction 2", default=False),
            "geometry_pattern": boolean(
                "pattern the geometry instead of the feature", default=False
            ),
            "name": string("feature name override", default=None),
        },
        required=("feature_names", "spacing_mm"),
    ),
    tier="extended",
    tags=("features",),
)
def linear_pattern(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.linear_pattern(
            args["feature_names"],
            args["spacing_mm"],
            args.get("direction_edge"),
            args.get("direction_plane"),
            args.get("count", 2),
            args.get("reverse", False),
            args.get("direction2_edge"),
            args.get("direction2_plane"),
            args.get("spacing2_mm", 0),
            args.get("count2", 1),
            args.get("reverse2", False),
            args.get("geometry_pattern", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "circular_pattern",
    "Repeat features around an axis. The axis is a straight edge index from "
    "list_edges or a cylindrical face index from list_faces.",
    obj(
        {
            "feature_names": array(
                "features to repeat (from list_features)", {"type": "string"}
            ),
            "count": integer(
                "total instances, including the seed", minimum=2, default=4
            ),
            "angle_deg": number(
                "total spread when equal_spacing (degrees)", default=360
            ),
            "axis_edge": integer("straight edge index used as the axis", default=None),
            "axis_face": integer(
                "cylindrical face index used as the axis", default=None
            ),
            "equal_spacing": boolean(
                "space instances evenly over angle_deg", default=True
            ),
            "reverse": boolean("flip the direction", default=False),
            "geometry_pattern": boolean(
                "pattern the geometry instead of the feature", default=False
            ),
            "name": string("feature name override", default=None),
        },
        required=("feature_names",),
    ),
    tier="extended",
    tags=("features",),
)
def circular_pattern(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.circular_pattern(
            args["feature_names"],
            args.get("count", 4),
            args.get("angle_deg", 360),
            args.get("axis_edge"),
            args.get("axis_face"),
            args.get("equal_spacing", True),
            args.get("reverse", False),
            args.get("geometry_pattern", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "mirror_feature",
    "Mirror features about a plane or a planar face. Seed features come from "
    "list_features.",
    obj(
        {
            "feature_names": array(
                "features to mirror (from list_features)", {"type": "string"}
            ),
            "plane": string(
                "mirror plane: front/top/right or exact name", default=None
            ),
            "face_index": integer(
                "planar face index from list_faces used as the mirror plane",
                default=None,
            ),
            "mirror_body": boolean("mirror the whole body", default=False),
            "geometry_pattern": boolean("mirror geometry, not the feature", default=False),
            "merge": boolean("merge mirrored bodies", default=True),
            "name": string("feature name override", default=None),
        },
        required=("feature_names",),
    ),
    tier="extended",
    tags=("features",),
)
def mirror_feature(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.mirror_feature(
            args["feature_names"],
            args.get("plane"),
            args.get("face_index"),
            args.get("mirror_body", False),
            args.get("geometry_pattern", False),
            args.get("merge", True),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "set_material",
    "Assign a material so mass and density are meaningful.",
    obj(
        {
            "name": string("material name, e.g. '6061 Alloy'"),
            "database": string("material database", default="SOLIDWORKS Materials"),
        },
        required=("name",),
    ),
    tier="extended",
    tags=("features",),
)
def set_material(args: dict) -> dict:
    return envelope(
        run(
            lambda: features.set_material(
                args["name"], args.get("database", "SOLIDWORKS Materials")
            )
        )
    )


@registry.tool(
    "set_appearance",
    "Colour the model, or specific faces when face_indices are given. Red, "
    "green and blue are 0-255; the applied colour is read back.",
    obj(
        {
            "red": integer("red 0-255", minimum=0, maximum=255),
            "green": integer("green 0-255", minimum=0, maximum=255),
            "blue": integer("blue 0-255", minimum=0, maximum=255),
            "face_indices": array(
                "faces to colour, from list_faces; the whole model if omitted",
                {"type": "integer"},
                default=None,
            ),
        },
        required=("red", "green", "blue"),
    ),
    tier="extended",
    tags=("documents",),
)
def set_appearance(args: dict) -> dict:
    result = run(
        lambda: documents.set_appearance(
            args["red"],
            args["green"],
            args["blue"],
            args.get("face_indices"),
        )
    )
    return envelope(result)


@registry.tool(
    "rename_feature",
    "Rename a feature in the tree.",
    obj(
        {
            "current_name": string("existing feature name"),
            "new_name": string("new name"),
        },
        required=("current_name", "new_name"),
    ),
    tier="extended",
    tags=("features",),
)
def rename_feature(args: dict) -> dict:
    return ok(
        run(
            lambda: features.rename_feature(args["current_name"], args["new_name"])
        )
    )


@registry.tool(
    "delete_feature",
    "Delete a feature (and optionally its children).",
    obj(
        {
            "name": string("feature to delete"),
            "absorb_children": boolean(
                "absorb dependent child features", default=False
            ),
        },
        required=("name",),
    ),
    tier="extended",
    tags=("features",),
)
def delete_feature(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.delete_feature(
            args["name"], args.get("absorb_children", False)
        )

    return ok(run(job))


@registry.tool(
    "sketch_offset",
    "Offset selected sketch entities, optionally in both directions.",
    obj(
        {
            "offset_mm": number("offset distance (mm)", exclusiveMinimum=0),
            "both_directions": boolean("offset both ways", default=False),
            "chain": boolean("offset the whole chain", default=True),
            "make_construction": boolean(
                "create as construction geometry", default=False
            ),
        },
        required=("offset_mm",),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_offset(args: dict) -> dict:
    return ok(
        run(
            lambda: sketch.offset(
                args["offset_mm"],
                args.get("both_directions", False),
                args.get("chain", True),
                args.get("make_construction", False),
            )
        )
    )


@registry.tool(
    "sketch_convert_entities",
    "Project the selected model edges into the active sketch.",
    obj({}),
    tier="extended",
    tags=("sketch",),
)
def sketch_convert_entities(args: dict) -> dict:
    return ok(run(sketch.convert_entities))


@registry.tool(
    "sketch_spline",
    "Draw a smooth spline through points in the active sketch.",
    obj(
        {
            "points_mm": array(
                "list of [x_mm, y_mm] points", {"type": "array"}
            )
        },
        required=("points_mm",),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_spline(args: dict) -> dict:
    return ok(run(lambda: sketch.spline(args["points_mm"])))


@registry.tool(
    "create_checkpoint",
    "Snapshot the active document into the checkpoint folder (file copy; "
    "save-a-copy for unsaved documents).",
    obj({"label": string("optional label", default=None)}),
    tier="extended",
    tags=("transactions",),
)
def create_checkpoint(args: dict) -> dict:
    return ok(run(lambda: checkpoint.create_checkpoint(args.get("label"))))


@registry.tool(
    "list_checkpoints",
    "List checkpoints, newest first.",
    obj({}),
    tier="extended",
    tags=("transactions",),
)
def list_checkpoints(args: dict) -> dict:
    return ok({"checkpoints": checkpoint.list_checkpoints()})


@registry.tool(
    "rollback_to_checkpoint",
    "Close the active document without saving and open a checkpoint copy. "
    "The copy becomes the active document.",
    obj(
        {
            "checkpoint": string(
                "checkpoint path or file name; newest if omitted", default=None
            )
        }
    ),
    tier="extended",
    tags=("transactions",),
)
def rollback_to_checkpoint(args: dict) -> dict:
    return ok(
        run(lambda: checkpoint.rollback(args.get("checkpoint")))
    )


@registry.tool(
    "insert_component",
    "Insert a part or assembly into the active assembly. The first component "
    "is usually fixed; later ones should be movable so mates can solve.",
    obj(
        {
            "path": string("path to the .sldprt/.sldasm file"),
            "x_mm": number("placement x (mm)", default=0),
            "y_mm": number("placement y (mm)", default=0),
            "z_mm": number("placement z (mm)", default=0),
            "fixed": boolean("fix the component in place", default=False),
        },
        required=("path",),
    ),
    tier="extended",
    tags=("assemblies",),
)
def insert_component(args: dict) -> dict:
    return ok(
        run(
            lambda: assemblies.insert_component(
                args["path"],
                args.get("x_mm", 0),
                args.get("y_mm", 0),
                args.get("z_mm", 0),
                args.get("fixed", False),
            )
        )
    )


@registry.tool(
    "list_components",
    "Names, paths, fixed state, positions and boxes of assembly components.",
    obj({}),
    tier="extended",
    tags=("assemblies",),
)
def list_components(args: dict) -> dict:
    def job() -> dict:
        components = assemblies.list_components()
        return {"components": components, "count": len(components)}

    return ok(run(job))


@registry.tool(
    "set_component_transform",
    "Move and rotate a component; the resulting placement is read back.",
    obj(
        {
            "name": string("component name from list_components"),
            "x_mm": number("x (mm)", default=0),
            "y_mm": number("y (mm)", default=0),
            "z_mm": number("z (mm)", default=0),
            "rx_deg": number("rotation about x (deg)", default=0),
            "ry_deg": number("rotation about y (deg)", default=0),
            "rz_deg": number("rotation about z (deg)", default=0),
        },
        required=("name",),
    ),
    tier="extended",
    tags=("assemblies",),
)
def set_component_transform(args: dict) -> dict:
    return ok(
        run(
            lambda: assemblies.set_component_transform(
                args["name"],
                args.get("x_mm", 0),
                args.get("y_mm", 0),
                args.get("z_mm", 0),
                args.get("rx_deg", 0),
                args.get("ry_deg", 0),
                args.get("rz_deg", 0),
            )
        )
    )


@registry.tool(
    "add_mate",
    "Mate two planar faces, named by component and outward direction in the "
    "component's own frame (e.g. '+x', '-z'). Distance is required for the "
    "distance mate type.",
    obj(
        {
            "mate_type": string("mate type", enum=MATE_TYPES),
            "component_a": string("first component name"),
            "direction_a": string("first face direction", enum=DIRECTIONS),
            "component_b": string("second component name"),
            "direction_b": string("second face direction", enum=DIRECTIONS),
            "distance_mm": number("distance for distance mates (mm)", default=None),
            "align": string(
                "alignment", enum=["aligned", "anti_aligned", "closest"],
                default="closest",
            ),
            "flip": boolean("flip the mate alignment", default=False),
        },
        required=(
            "mate_type", "component_a", "direction_a", "component_b", "direction_b",
        ),
    ),
    tier="extended",
    tags=("assemblies",),
)
def add_mate(args: dict) -> dict:
    return ok(
        run(
            lambda: assemblies.add_mate(
                args["mate_type"],
                args["component_a"],
                args["direction_a"],
                args["component_b"],
                args["direction_b"],
                args.get("distance_mm"),
                args.get("align", "closest"),
                args.get("flip", False),
            )
        )
    )


@registry.tool(
    "check_interference",
    "Report component pairs whose solids overlap.",
    obj({}),
    tier="extended",
    tags=("assemblies",),
)
def check_interference(args: dict) -> dict:
    return ok(run(assemblies.check_interference))


@registry.tool(
    "get_assembly_bounding_box",
    "Bounding box of the whole assembly in millimetres.",
    obj({}),
    tier="extended",
    tags=("assemblies",),
)
def get_assembly_bounding_box(args: dict) -> dict:
    return ok(run(assemblies.assembly_bounding_box))


@registry.tool(
    "new_drawing",
    "Create a drawing from the active part/assembly (or an explicit model "
    "path) and frame it with the standard sheet format (border and title "
    "block: ISO for A4-A0, ANSI for A-E).",
    obj(
        {
            "model": string(
                "model path or title; defaults to the active document", default=None
            ),
            "template": string("drawing template path", default=None),
            "paper_size": string(
                "paper size for the framed sheet",
                enum=sorted(drawings.PAPER_SIZE_MM),
                default=drawings.DEFAULT_PAPER_SIZE,
            ),
            "scale": number(
                "sheet scale as model:paper decimal (0.5 is 1:2)", default=1.0
            ),
            "first_angle": boolean("first-angle projection", default=True),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def new_drawing(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.create_drawing(
                args.get("model"),
                args.get("template"),
                args.get("paper_size", drawings.DEFAULT_PAPER_SIZE),
                args.get("scale", 1.0),
                args.get("first_angle", True),
            )
        )
    )


@registry.tool(
    "drawing_set_iso_units",
    "Set the active drawing document's length units to millimetres and verify "
    "the measured unit read-back.",
    obj({}),
    tier="extended",
    tags=("drawings", "documents"),
)
def drawing_set_iso_units(args: dict) -> dict:
    return envelope(run(drawings.set_iso_units))


@registry.tool(
    "drawing_insert_view",
    "Insert a model view of an explicitly referenced open model and named "
    "configuration. For a projection-based orthographic set, use this for the "
    "single master view, then create every companion with "
    "drawing_insert_projected_view from this view.",
    obj(
        {
            "view": string(
                "standard view",
                enum=["front", "back", "left", "right", "top", "bottom",
                      "isometric", "trimetric", "dimetric"],
            ),
            "x_mm": number("sheet x position (mm)", default=100),
            "y_mm": number("sheet y position (mm)", default=150),
            "model_reference": string("exact open model path or unique document title"),
            "configuration": string("configuration to reference in the drawing view"),
        },
        required=("view", "model_reference", "configuration"),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_view(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_model_view(
                args["view"],
                args["model_reference"],
                args["configuration"],
                args.get("x_mm", 100),
                args.get("y_mm", 150),
            )
        )
    )


@registry.tool(
    "drawing_insert_standard_views",
    "Convenience batch: insert front, top and right views directly from the "
    "referenced model using the requested first- or third-angle layout. This "
    "does not create the latter views as projections. For the normal "
    "projection-based workflow, insert one master with drawing_insert_view "
    "and create companions from it with drawing_insert_projected_view. Use "
    "this batch only when direct standard-view insertion is requested. Views "
    "share the sheet scale and are laid out with a clear gap.",
    obj(
        {
            "model_reference": string("exact open model path or unique document title"),
            "configuration": string("configuration to reference in each drawing view"),
            "front_mm": array(
                "front view [x, y] on the sheet", {"type": "number"}, default=None
            ),
            "gap_mm": number(
                "clear gap between the laid-out view outlines (mm)",
                minimum=1,
                default=20,
            ),
            "scale": number(
                "drawing scale for every view and the sheet (0.5 is 1:2); "
                "default: the sheet scale measured before insertion",
                exclusiveMinimum=0,
                default=None,
            ),
            "projection": string(
                "orthographic projection layout",
                enum=["first_angle", "third_angle"],
                default="first_angle",
            ),
        },
        required=("model_reference", "configuration"),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_standard_views(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_standard_views(
                args["model_reference"],
                args["configuration"],
                args.get("front_mm"),
                args.get("gap_mm", 20),
                args.get("projection", "first_angle"),
                args.get("scale"),
            )
        )
    )


@registry.tool(
    "list_drawing_views",
    "List views on the active drawing with names, outlines and dimension counts.",
    obj(
        {
            "sheet": string(
                "only list views on this sheet; default is every sheet", default=None
            )
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def list_drawing_views(args: dict) -> dict:
    return ok(run(lambda: drawings.list_drawing_views(args.get("sheet"))))


@registry.tool(
    "drawing_insert_model_dimensions",
    "Import the model's own dimensions and annotations into the drawing "
    "(Insert > Model Items). The model must carry driving dimensions. The "
    "tool inventories annotations before and after the API call and reports "
    "the measured additions for this specific drawing.",
    obj(
        {
            "view": string(
                "target view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "types": array(
                "annotation kinds to import",
                {
                    "type": "string",
                    "enum": sorted(drawings.ANNOTATION_TYPES),
                },
                default=["dimensions"],
            ),
            "all_views": boolean("import into every view", default=True),
            "duplicate_dimensions": boolean(
                "allow the same dimension in more than one view", default=False
            ),
            "hidden_feature_dimensions": boolean(
                "include dimensions of hidden features", default=False
            ),
            "source": string(
                "which model items to import",
                enum=sorted(drawings.ANNOTATION_SOURCES),
                default="entire_model",
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_model_dimensions(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_model_annotations(
            args.get("view"),
            args.get("types"),
            args.get("all_views", True),
            args.get("duplicate_dimensions", False),
            args.get("hidden_feature_dimensions", False),
            args.get("source", "entire_model"),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_auto_dimension",
    "Generate dimensions on a drawing view from its geometry with DimXpert "
    "(re-spaced into non-overlapping rows by default). Use this when the "
    "model has no dimensions marked for drawing, or when "
    "drawing_insert_model_dimensions imports nothing.",
    obj(
        {
            "view": string(
                "target view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "horizontal_scheme": string(
                "horizontal dimension style",
                enum=sorted(drawings.AUTODIM_SCHEMES),
                default="baseline",
            ),
            "vertical_scheme": string(
                "vertical dimension style",
                enum=sorted(drawings.AUTODIM_SCHEMES),
                default="baseline",
            ),
            "horizontal_placement": string(
                "horizontal dimension placement",
                enum=sorted(drawings.AUTODIM_HORIZONTAL),
                default="below",
            ),
            "vertical_placement": string(
                "vertical dimension placement",
                enum=sorted(drawings.AUTODIM_VERTICAL),
                default="left",
            ),
            "arrange": boolean(
                "re-space the new dimensions into non-overlapping rows",
                default=True,
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_auto_dimension(args: dict) -> dict:
    result = run(
        lambda: drawings.auto_dimension(
            args.get("view"),
            args.get("horizontal_scheme", "baseline"),
            args.get("vertical_scheme", "baseline"),
            args.get("horizontal_placement", "below"),
            args.get("vertical_placement", "left"),
            args.get("arrange", True),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_arrange_dimensions",
    "Re-space the linear dimensions of a drawing view into non-overlapping "
    "rows (dimensions keep their side of the view and their original stacking "
    "order). Use after auto or imported dimensions land on top of each other.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "spacing_mm": number(
                "row spacing for the dimension lines (mm)",
                minimum=1,
                default=drawings.DIMENSION_SPACING_MM,
            ),
            "margin_mm": number(
                "gap between the view outline and the first row (mm)",
                minimum=0,
                default=drawings.DIMENSION_MARGIN_MM,
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_arrange_dimensions(args: dict) -> dict:
    result = run(
        lambda: drawings.arrange_dimensions(
            args.get("view"),
            args.get("spacing_mm", drawings.DIMENSION_SPACING_MM),
            args.get("margin_mm", drawings.DIMENSION_MARGIN_MM),
        )
    )
    return envelope(result)


@registry.tool(
    "list_drawing_view_edges",
    "List a drawing view's visible edges with index, kind (line/circle), "
    "endpoints or centre and length in millimetres. These indices attach "
    "datum, GD&T and surface-finish annotations.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            )
        }
    ),
    tier="extended",
    tags=("drawings", "inspect"),
)
def list_drawing_view_edges(args: dict) -> dict:
    return ok(run(lambda: drawings.list_view_edges(args.get("view"))))


@registry.tool(
    "list_drawing_dimensions",
    "List the active drawing's dimensions per view with index, kind, value, "
    "position, tolerance and hole-callout state. Indexes address "
    "drawing_set_dimension_tolerance; re-list after geometry changes.",
    obj(
        {
            "view": string(
                "only list dimensions of this view; default: every view on "
                "the active sheet",
                default=None,
            )
        }
    ),
    tier="extended",
    tags=("drawings", "inspect"),
)
def list_drawing_dimensions(args: dict) -> dict:
    return ok(run(lambda: drawings.list_dimensions(args.get("view"))))


@registry.tool(
    "drawing_audit_feature_coverage",
    "Audit an explicit feature-to-dimension coverage map. Feature refs come "
    "from list_features and dimension IDs from list_drawing_dimensions. The "
    "tool finds missing coverage, stale IDs, and duplicate assignments; it "
    "does not infer functional intent from edge counts.",
    obj(
        {
            "coverage": array(
                "design-critical model features and the drawing dimension IDs "
                "assigned to each feature",
                {
                    "type": "object",
                    "properties": {
                        "feature_ref": {"type": "string"},
                        "dimension_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "required": {"type": "boolean", "default": True},
                    },
                    "required": ["feature_ref", "dimension_ids"],
                },
            )
        },
        required=("coverage",),
    ),
    tier="extended",
    tags=("drawings", "dimensions", "inspect"),
)
def drawing_audit_feature_coverage(args: dict) -> dict:
    return ok(run(lambda: drawings.audit_feature_dimension_coverage(args["coverage"])))


@registry.tool(
    "drawing_set_dimension_tolerance",
    "Set one drawing dimension's tolerance (symmetric, bilateral, limits, "
    "min/max or an ISO fit) and verify the measured read-back. Dimension "
    "indexes come from list_drawing_dimensions.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "index": integer("dimension index from list_drawing_dimensions"),
            "tolerance": string(
                "tolerance type",
                enum=sorted(drawings.TOLERANCE_TYPES),
                default="symmetric",
            ),
            "value_mm": number(
                "symmetric magnitude or the single min/max bound (mm)",
                default=None,
            ),
            "minus_mm": number(
                "bilateral lower deviation magnitude (mm)", default=None
            ),
            "plus_mm": number(
                "bilateral upper deviation magnitude (mm)", default=None
            ),
            "lower_mm": number("limits lower bound (mm)", default=None),
            "upper_mm": number("limits upper bound (mm)", default=None),
            "hole_fit": string('ISO hole fit, for example "H7"', default=None),
            "shaft_fit": string('ISO shaft fit, for example "g6"', default=None),
        },
        required=("index",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_set_dimension_tolerance(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.set_dimension_tolerance(
                args.get("view"),
                args["index"],
                args.get("tolerance", "symmetric"),
                args.get("value_mm"),
                args.get("minus_mm"),
                args.get("plus_mm"),
                args.get("lower_mm"),
                args.get("upper_mm"),
                args.get("hole_fit"),
                args.get("shaft_fit"),
            )
        )
    )


@registry.tool(
    "drawing_insert_general_tolerance_table",
    "Insert the installed general tolerance table into the "
    "active document. Measured on SW2026 SP0.0: the annotation is available "
    "for parts/assemblies through the API. On a drawing, use a note only "
    "when the design authority supplies the applicable standard and class.",
    obj(
        {
            "x": integer("table x position in API units", default=None),
            "y": integer("table y position in API units", default=None),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_general_tolerance_table(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_general_tolerance_table(
                args.get("x"), args.get("y")
            )
        )
    )


@registry.tool(
    "drawing_insert_datum",
    "Attach a datum tag (for example A) to a view edge selected by index "
    "from list_drawing_view_edges, and verify the label read-back. The result "
    "reports the measured tag position and warns when another datum tag's "
    "letter box is within 10 mm (tags snap along the edge on this build).",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "edge_index": integer("edge index from list_drawing_view_edges"),
            "label": string("datum label, for example A", default="A"),
            "x_mm": number("optional tag position on the sheet (mm)", default=None),
            "y_mm": number("optional tag position on the sheet (mm)", default=None),
        },
        required=("edge_index",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_datum(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_datum(
                args.get("view"),
                args["edge_index"],
                args.get("label", "A"),
                args.get("x_mm"),
                args.get("y_mm"),
            )
        )
    )


@registry.tool(
    "drawing_insert_gtol",
    "Insert a single-frame geometric tolerance (characteristic symbol, "
    "tolerance text and up to three datum references) on the view edge "
    "selected by index, and verify the frame read-back.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "edge_index": integer("edge index from list_drawing_view_edges"),
            "symbol": string(
                "geometric characteristic",
                enum=sorted(drawings.GTOL_SYMBOLS),
                default="position",
            ),
            "tolerance": string(
                "primary tolerance text, for example 0.2", default="0.2"
            ),
            "tolerance2": string(
                "optional secondary tolerance text", default=None
            ),
            "datums": array(
                "datum references in frame order (up to three)",
                {"type": "string"},
                default=None,
            ),
            "diameter": boolean(
                "prefix the primary tolerance with the diameter symbol",
                default=False,
            ),
            "material_condition": string(
                "material condition for the primary tolerance",
                enum=sorted(drawings.MATERIAL_CONDITIONS),
                default="none",
            ),
            "datum_material_conditions": array(
                "material conditions for the datum references",
                {"type": "string"},
                default=None,
            ),
            "x_mm": number("optional frame position on the sheet (mm)", default=None),
            "y_mm": number("optional frame position on the sheet (mm)", default=None),
        },
        required=("edge_index",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_gtol(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_gtol(
                args.get("view"),
                args["edge_index"],
                args.get("symbol", "position"),
                args.get("tolerance", "0.2"),
                args.get("tolerance2"),
                args.get("datums"),
                args.get("diameter", False),
                args.get("material_condition", "none"),
                args.get("datum_material_conditions"),
                args.get("x_mm"),
                args.get("y_mm"),
            )
        )
    )


@registry.tool(
    "drawing_insert_surface_finish",
    "Insert a surface finish symbol with a roughness value (for example 1.6) "
    "onto a view edge or the sheet, and verify the text read-back.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "edge_index": integer(
                "edge index from list_drawing_view_edges", default=None
            ),
            "roughness": string(
                "roughness value, for example 1.6 or Ra 1.6", default="1.6"
            ),
            "symbol": string(
                "surface finish symbol type",
                enum=sorted(drawings.SURFACE_FINISH_SYMBOLS),
                default="basic",
            ),
            "x_mm": number("sheet x position (mm)", default=None),
            "y_mm": number("sheet y position (mm)", default=None),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_surface_finish(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_surface_finish(
                args.get("view"),
                args.get("edge_index"),
                args.get("roughness", "1.6"),
                args.get("symbol", "basic"),
                args.get("x_mm"),
                args.get("y_mm"),
            )
        )
    )


@registry.tool(
    "drawing_insert_revision_table",
    "Insert the sheet revision table (stock frame anchor type 1) and read its "
    "columns back.",
    obj(
        {
            "anchor_type": integer(
                "anchor type; the stock ISO/ANSI frames use 1",
                default=1,
            ),
            "template": string(
                "revision table template path; default template when empty",
                default="",
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_revision_table(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_revision_table(
                args.get("anchor_type", drawings.REVISION_TABLE_ANCHOR),
                args.get("template", ""),
            )
        )
    )


@registry.tool(
    "drawing_add_revision",
    "Add a revision row (for example A) to the sheet revision table and "
    "verify the current revision. Optional cells are matched by column title "
    "(ZONE, REV., DESCRIPTION, DATE, APPROVED).",
    obj(
        {
            "revision": string("revision label, for example A"),
            "description": string("DESCRIPTION cell text", default=None),
            "date": string("DATE cell text", default=None),
            "zone": string("ZONE cell text", default=None),
            "approved": string("APPROVED cell text", default=None),
        },
        required=("revision",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_add_revision(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.add_revision(
                args["revision"],
                args.get("description"),
                args.get("date"),
                args.get("zone"),
                args.get("approved"),
            )
        )
    )


@registry.tool(
    "drawing_insert_bom_table",
    "Insert a BOM table for an assembly drawing view and read its rows back. "
    "The view's referenced configuration is resolved automatically (an empty "
    "configuration produces a header-only table on this build).",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "bom_type": string(
                "BOM type",
                enum=sorted(drawings.BOM_TYPES),
                default="top_level_only",
            ),
            "configuration": string(
                "assembly configuration to list; default: the view's "
                "referenced configuration",
                default=None,
            ),
        }
    ),
    tier="extended",
    tags=("drawings", "assemblies"),
)
def drawing_insert_bom_table(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_bom_table(
                args.get("view"),
                args.get("bom_type", "top_level_only"),
                args.get("configuration"),
            )
        )
    )


@registry.tool(
    "drawing_insert_balloons",
    "Auto-balloon the components of an assembly drawing view and read the "
    "balloon texts back. Add the BOM table first so item numbers exist.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "style": string(
                "balloon shape",
                enum=sorted(drawings.BALLOON_STYLES),
                default="circular",
            ),
            "fit": string(
                "balloon text fit",
                enum=sorted(drawings.BALLOON_FITS),
                default="3_chars",
            ),
            "layout": string(
                "balloon layout around the view",
                enum=sorted(drawings.BALLOON_LAYOUTS),
                default="circle",
            ),
            "item_number_start": integer(
                "first balloon item number", minimum=1, default=1
            ),
        }
    ),
    tier="extended",
    tags=("drawings", "assemblies"),
)
def drawing_insert_balloons(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_balloons(
                args.get("view"),
                args.get("style", "circular"),
                args.get("fit", "3_chars"),
                args.get("layout", "circle"),
                args.get("item_number_start", 1),
            )
        )
    )


@registry.tool(
    "drawing_insert_hole_callout",
    "Add a hole callout for a circular edge from list_drawing_view_edges. "
    "Measured on this build: callouts are only produced for holes that carry "
    "callout data (Hole Wizard); other holes refuse with an actionable hint.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "edge_index": integer(
                "circular edge index from list_drawing_view_edges", default=None
            ),
            "x_mm": number(
                "sheet x of the hole, used when the no-select callout fails",
                default=None,
            ),
            "y_mm": number(
                "sheet y of the hole, used when the no-select callout fails",
                default=None,
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_hole_callout(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.insert_hole_callout(
                args.get("view"),
                args.get("edge_index"),
                args.get("x_mm"),
                args.get("y_mm"),
            )
        )
    )


@registry.tool(
    "drawing_add_note",
    "Place a text note on the active drawing sheet. Position is millimetres "
    "from the sheet's lower-left corner; use \\n for line breaks.",
    obj(
        {
            "text": string("note text"),
            "x_mm": number("x position on the sheet (mm)"),
            "y_mm": number("y position on the sheet (mm)"),
            "height_mm": number("text height (mm)", default=None),
        },
        required=("text", "x_mm", "y_mm"),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_add_note(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.add_note(
                args["text"],
                args["x_mm"],
                args["y_mm"],
                args.get("height_mm"),
            )
        )
    )


@registry.tool(
    "list_drawing_annotations",
    "Read back the annotations on the active drawing, including note text, so "
    "insertions can be verified.",
    obj(
        {
            "view": string(
                "only list annotations of this view", default=None
            ),
            "sheet": string(
                "only list annotations on this sheet", default=None
            ),
        }
    ),
    tier="extended",
    tags=("drawings", "inspect"),
)
def list_drawing_annotations(args: dict) -> dict:
    return ok(
        run(
            lambda: drawings.list_annotations(
                args.get("view"), args.get("sheet")
            )
        )
    )


@registry.tool(
    "drawing_move_annotation",
    "Move one annotation (note or dimension) to a sheet position in mm. "
    "Indexes come from list_drawing_annotations; re-list after any edit.",
    obj(
        {
            "view": string(
                "view name from list_drawing_annotations (Sheet1 holds sheet notes)"
            ),
            "index": integer("annotation index from list_drawing_annotations"),
            "x_mm": number("x position on the sheet (mm)"),
            "y_mm": number("y position on the sheet (mm)"),
        },
        required=("view", "index", "x_mm", "y_mm"),
    ),
    tier="extended",
    tags=("drawings", "annotations"),
)
def drawing_move_annotation(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.move_annotation(
                args["view"], args["index"], args["x_mm"], args["y_mm"]
            )
        )
    )


@registry.tool(
    "drawing_delete_annotation",
    "Delete one annotation by view and index from list_drawing_annotations. "
    "Measured on this build: Select(True) + DeleteSelection2 removes notes "
    "and dimensions; Select3(True, None) is a no-op.",
    obj(
        {
            "view": string("view name from list_drawing_annotations"),
            "index": integer("annotation index from list_drawing_annotations"),
        },
        required=("view", "index"),
    ),
    tier="extended",
    tags=("drawings", "annotations"),
)
def drawing_delete_annotation(args: dict) -> dict:
    return envelope(
        run(lambda: drawings.delete_annotation(args["view"], args["index"]))
    )


@registry.tool(
    "drawing_set_annotation_text",
    "Edit annotation text: notes take text (full replacement), dimensions "
    "take prefix and/or suffix. Measured on SW2026 SP0.0: SetText(0) is a "
    "no-op; prefix (1) and suffix (2) write and read back.",
    obj(
        {
            "view": string("view name from list_drawing_annotations"),
            "index": integer("annotation index from list_drawing_annotations"),
            "text": string("full note text (notes only)", default=None),
            "prefix": string("dimension prefix override", default=None),
            "suffix": string("dimension suffix override", default=None),
            "height_mm": number("new note text height (notes only)", default=None),
        },
        required=("view", "index"),
    ),
    tier="extended",
    tags=("drawings", "annotations"),
)
def drawing_set_annotation_text(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.set_annotation_text(
                args["view"],
                args["index"],
                args.get("text"),
                args.get("prefix"),
                args.get("suffix"),
                args.get("height_mm"),
            )
        )
    )


@registry.tool(
    "drawing_update_annotations",
    "Apply note or dimension text/position edits by IDs from "
    "list_drawing_annotations. Resolves the whole batch before mutation, "
    "rebuilds once, and restores saved values if any read-back or rebuild "
    "fails.",
    obj(
        {
            "updates": array(
                "annotation changes; each id must come from the current "
                "list_drawing_annotations result",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                        "prefix": {"type": "string"},
                        "suffix": {"type": "string"},
                        "height_mm": {"type": "number", "exclusiveMinimum": 0},
                        "position_mm": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    },
                    "required": ["id"],
                },
            )
        },
        required=("updates",),
    ),
    tier="extended",
    tags=("drawings", "annotations"),
)
def drawing_update_annotations(args: dict) -> dict:
    return envelope(run(lambda: drawings.update_annotations(args["updates"])))


@registry.tool(
    "drawing_add_dimension",
    "Dimension picked view edges: one circular edge gives its diameter, two "
    "edges the distance between them. Edge indexes come from "
    "list_drawing_view_edges; placement_mm is the text position on the sheet. "
    "The dimension measures the geometry and does not drive it.",
    obj(
        {
            "view": string(
                "view name from list_drawing_views; default: first model view",
                default=None,
            ),
            "edge_indices": array(
                "one or two edge indexes from list_drawing_view_edges",
                integer("edge index"),
            ),
            "placement_mm": array(
                "sheet position for the dimension text [x_mm, y_mm]",
                number("millimetres"),
            ),
        },
        required=("edge_indices", "placement_mm"),
    ),
    tier="extended",
    tags=("drawings", "dimensions"),
)
def drawing_add_dimension(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.add_dimension(
                args.get("view"),
                args["edge_indices"],
                args["placement_mm"],
            )
        )
    )


@registry.tool(
    "drawing_delete_view",
    "Delete a model view by exact name from list_drawing_views. The sheet "
    "view cannot be deleted. Dependent views SOLIDWORKS removes with it are "
    "reported in removed_views.",
    obj(
        {"view": string("exact view name from list_drawing_views")},
        required=("view",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_delete_view(args: dict) -> dict:
    return envelope(run(lambda: drawings.delete_view(args["view"])))


@registry.tool(
    "list_drawing_properties",
    "Read the active drawing's custom properties. Use these names for title-"
    "block fields linked to document properties.",
    obj({}),
    tier="extended",
    tags=("drawings", "inspect"),
)
def list_drawing_properties(args: dict) -> dict:
    return ok(run(drawings.list_properties))


@registry.tool(
    "drawing_set_property",
    "Add or update one text custom property on the active drawing and verify "
    "the value by reading it back. Use ISO title-block property names such as "
    "Title, DrawingNumber and Revision.",
    obj(
        {
            "name": string("custom property name"),
            "value": string("custom property text value"),
        },
        required=("name", "value"),
    ),
    tier="extended",
    tags=("drawings", "documents"),
)
def drawing_set_property(args: dict) -> dict:
    return envelope(run(lambda: drawings.set_property(args["name"], args["value"])))


@registry.tool(
    "set_file_property",
    "Set one text custom property on the active part/assembly/drawing and "
    "verify the read-back. This fills title-block links that resolve against "
    "the model: part Description (TITLE cell), Material, Finish; drawing "
    "DrawnBy, CheckedBy, DrawnDate, CheckedDate, Revision.",
    obj(
        {
            "name": string("custom property name"),
            "value": string("custom property text value"),
        },
        required=("name", "value"),
    ),
    tier="extended",
    tags=("documents", "drawings"),
)
def set_file_property(args: dict) -> dict:
    return envelope(
        run(lambda: documents.set_file_property(args["name"], args["value"]))
    )


@registry.tool(
    "drawing_manifest",
    "Collect the active drawing's sheets, views, annotations, custom "
    "properties and rebuild state for planning or release review.",
    obj({}),
    tier="extended",
    tags=("drawings", "inspect"),
)
def drawing_manifest(args: dict) -> dict:
    return ok(run(drawings.drawing_manifest))


@registry.tool(
    "drawing_layout_audit",
    "Screen the active drawing's annotation layout: estimated text boxes, "
    "collisions (overlaps and near-misses) and off-frame items. Boxes are "
    "estimated from the measured annotation position and character count. "
    "The default audits all returned text, including sheet-format and title-"
    "block notes; raster review is still required.",
    obj(
        {
            "sheet": string("only audit this sheet", default=None),
            "min_gap_mm": number(
                "flag annotations whose boxes are closer than this (mm)",
                default=2.0,
            ),
            "text_height_mm": number(
                "assumed text height for the estimate (mm)", default=3.5
            ),
            "inset_mm": number(
                "override the default measured ISO filing/frame inset (mm)",
                default=None,
            ),
            "edge_band_mm": number(
                "explicitly skip text annotations within this distance of the "
                "sheet edges; 0 audits the full sheet (mm)",
                default=0.0,
            ),
        }
    ),
    tier="extended",
    tags=("drawings", "inspect"),
)
def drawing_layout_audit(args: dict) -> dict:
    return ok(
        run(
            lambda: drawing_audit.layout_audit(
                args.get("sheet"),
                args.get("min_gap_mm", 2.0),
                args.get("text_height_mm", 3.5),
                args.get("inset_mm"),
                args.get("edge_band_mm", 0.0),
            )
        )
    )


@registry.tool(
    "drawing_preflight",
    "Run a non-release ISO metric drawing preflight. It checks the document, "
    "stock ISO sheet frame, first-angle projection, at least one model view "
    "and a clean rebuild without requiring dimensions or title-block fields.",
    obj({}),
    tier="extended",
    tags=("drawings", "inspect"),
)
def drawing_preflight(args: dict) -> dict:
    return ok(run(drawings.iso_preflight))


@registry.tool(
    "validate_iso_drawing",
    "Validate the active drawing against the ISO metric release contract. "
    "The result contains valid, checks, errors and warnings; a failed "
    "validation is returned as data so the skill can correct the drawing. "
    "Title-block links are required by default; disable that check when a "
    "stock frame is being reviewed before a company title block is applied.",
    obj(
        {
            "minimum_model_views": integer(
                "minimum number of model views", minimum=1,
                default=drawing_iso.DEFAULT_MINIMUM_MODEL_VIEWS,
            ),
            "required_properties": array(
                "custom properties that must be non-empty",
                {"type": "string"},
                default=list(drawing_iso.DEFAULT_REQUIRED_PROPERTIES),
            ),
            "require_dimensions": boolean(
                "require at least one readable dimension", default=True
            ),
            "projection": string(
                "expected sheet projection",
                enum=["first_angle", "third_angle"],
                default="first_angle",
            ),
            "allow_view_overlap": boolean(
                "allow overlapping model-view outlines", default=False
            ),
            "limitations_acknowledged": boolean(
                "acknowledge that visual/company-standard review remains human",
                default=False,
            ),
            "require_title_block_display": boolean(
                "require linked title-block notes to be read back; enable "
                "for a company frame that links the custom properties",
                default=False,
            ),
        }
    ),
    tier="extended",
    tags=("drawings", "inspect"),
)
def validate_iso_drawing(args: dict) -> dict:
    return ok(
        run(
            lambda: drawings.validate_iso_drawing(
                args.get(
                    "minimum_model_views", drawing_iso.DEFAULT_MINIMUM_MODEL_VIEWS
                ),
                args.get("required_properties"),
                args.get("require_dimensions", True),
                args.get("projection", "first_angle"),
                args.get("allow_view_overlap", False),
                args.get("limitations_acknowledged", False),
                args.get("require_title_block_display", False),
            )
        )
    )


@registry.tool(
    "list_drawing_sheets",
    "List the sheets of the active drawing with the active one marked, plus "
    "the current sheet's paper size, scale and size in millimetres.",
    obj({}),
    tier="extended",
    tags=("drawings", "inspect"),
)
def list_drawing_sheets(args: dict) -> dict:
    return ok(run(drawings.list_sheets))


@registry.tool(
    "drawing_add_sheet",
    "Add a sheet to the active drawing and frame it with the standard sheet "
    "format (border and title block). Paper sizes follow swDwgPaperSizes_e "
    "(A-E, A4-A0, custom); the new sheet is verified by re-reading the sheet "
    "list.",
    obj(
        {
            "name": string(
                "sheet name; defaults to Sheet<N>", default=None
            ),
            "paper_size": string(
                "paper size",
                enum=sorted(drawings.PAPER_SIZES),
                default="A3",
            ),
            "scale_numerator": number("sheet scale numerator", default=1),
            "scale_denominator": number("sheet scale denominator", default=1),
            "first_angle": boolean("first-angle projection", default=True),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_add_sheet(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.add_sheet(
                args.get("name"),
                args.get("paper_size", "A3"),
                args.get("scale_numerator", 1),
                args.get("scale_denominator", 1),
                args.get("first_angle", True),
            )
        )
    )


@registry.tool(
    "drawing_set_sheet_format",
    "Apply a standard sheet frame (border and title block) to the active "
    "sheet and set its paper size, scale and projection angle. Stock frames "
    "on this build are ISO (A4-A0) and ANSI (A-E).",
    obj(
        {
            "paper_size": string(
                "paper size for the framed sheet",
                enum=sorted(drawings.PAPER_SIZE_MM),
                default=drawings.DEFAULT_PAPER_SIZE,
            ),
            "scale": number(
                "sheet scale as model:paper decimal (0.5 is 1:2)", default=1.0
            ),
            "first_angle": boolean("first-angle projection", default=True),
            "sheet": string(
                "sheet to frame; default: the active sheet", default=None
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_set_sheet_format(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.apply_sheet_format(
                args.get("paper_size", drawings.DEFAULT_PAPER_SIZE),
                args.get("scale", 1.0),
                args.get("first_angle", True),
                args.get("sheet"),
            )
        )
    )


@registry.tool(
    "drawing_activate_sheet",
    "Make a sheet the active one; the active sheet is read back.",
    obj({"name": string("sheet name from list_drawing_sheets")}, required=("name",)),
    tier="extended",
    tags=("drawings",),
)
def drawing_activate_sheet(args: dict) -> dict:
    return envelope(run(lambda: drawings.activate_sheet(args["name"])))


@registry.tool(
    "drawing_activate_view",
    "Make a drawing view the active one. Section, detail and projected views "
    "and sketching inside a view all operate on the active view.",
    obj(
        {
            "name": string(
                "view name from list_drawing_views; first model view if omitted",
                default=None,
            )
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_activate_view(args: dict) -> dict:
    return envelope(run(lambda: drawings.activate_view(args.get("name"))))


@registry.tool(
    "drawing_set_view",
    "Move, rescale or restyle an existing drawing view. Position is "
    "millimetres from the sheet's lower-left corner; scale is decimal (0.25 "
    "is 1:4). The resulting view state is read back.",
    obj(
        {
            "name": string("view name from list_drawing_views"),
            "x_mm": number("x position on the sheet (mm)", default=None),
            "y_mm": number("y position on the sheet (mm)", default=None),
            "scale": number(
                "decimal scale, e.g. 0.25 for 1:4", exclusiveMinimum=0, default=None
            ),
            "display_mode": string(
                "display style",
                enum=sorted(drawings.DISPLAY_MODES),
                default=None,
            ),
            "tangent_edges": string(
                "how tangent edges are drawn",
                enum=sorted(drawings.TANGENT_EDGES),
                default=None,
            ),
        },
        required=("name",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_set_view(args: dict) -> dict:
    return envelope(
        run(
            lambda: drawings.set_view(
                args["name"],
                args.get("x_mm"),
                args.get("y_mm"),
                args.get("scale"),
                args.get("display_mode"),
                args.get("tangent_edges"),
            )
        )
    )


@registry.tool(
    "drawing_insert_projected_view",
    "Project an orthographic companion from a named parent. Standard workflow: "
    "insert one master with drawing_insert_view, then call this once per "
    "companion, always passing that master's exact name as parent_view. "
    "Direction is sheet placement, not the view-orientation name; use measured "
    "sheet coordinates when needed and verify type, position and source. "
    "SW2026 SP0.0 may omit projected orientation read-back, so confirm the "
    "projection convention from the sheet setting, symbol and raster. Multiple "
    "projections from one master work, but add them before additional sheets.",
    obj(
        {
            "parent_view": string(
                "exact master view name to project from; pass explicitly", default=None
            ),
            "direction": string(
                "sheet placement direction relative to parent (not view orientation)",
                enum=["right", "left", "up", "down"],
                default="right",
            ),
            "offset_mm": number("distance from the parent (mm)", default=80),
            "x_mm": number("exact sheet x, overriding direction (mm)", default=None),
            "y_mm": number("exact sheet y, overriding direction (mm)", default=None),
            "not_aligned": boolean("break alignment with the parent", default=False),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_projected_view(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_projected_view(
            args.get("parent_view"),
            args.get("direction", "right"),
            args.get("offset_mm", 80),
            args.get("x_mm"),
            args.get("y_mm"),
            args.get("not_aligned", False),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_insert_section_view",
    "Create a section view: give the cutting line's two endpoints (sheet "
    "millimetres, converted into the parent view's sketch space for you) and "
    "where the section should sit; the line is drawn in the parent "
    "view for you. The cut is verified by read-back: a section that exposes no "
    "cut edges is reported as an error. Depth 0 cuts all the way.",
    obj(
        {
            "x1_mm": number("cutting line start x on the sheet (mm)"),
            "y1_mm": number("cutting line start y on the sheet (mm)"),
            "x2_mm": number("cutting line end x on the sheet (mm)"),
            "y2_mm": number("cutting line end y on the sheet (mm)"),
            "place_x_mm": number("section view x on the sheet (mm)", default=0),
            "place_y_mm": number("section view y on the sheet (mm)", default=0),
            "parent_view": string(
                "view to cut; first model view if omitted", default=None
            ),
            "label": string("section label", default="A"),
            "not_aligned": boolean("do not align with the parent", default=False),
            "exclude_fasteners": boolean("exclude fasteners from the cut", default=False),
            "depth_mm": number("partial-section depth; 0 cuts all the way", default=0),
        },
        required=("x1_mm", "y1_mm", "x2_mm", "y2_mm"),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_section_view(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_section_view(
            args.get("parent_view"),
            args["x1_mm"],
            args["y1_mm"],
            args["x2_mm"],
            args["y2_mm"],
            args.get("place_x_mm", 0),
            args.get("place_y_mm", 0),
            args.get("label", "A"),
            args.get("not_aligned", False),
            args.get("exclude_fasteners", False),
            args.get("depth_mm", 0),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_insert_detail_view",
    "Create a detail view: give the detail circle's centre and radius and "
    "where the enlarged view should sit (sheet millimetres); the circle is "
    "drawn in the parent view for you, converted into that view's sketch "
    "space. The scale is absolute (model to "
    "paper), NOT relative to the parent: pick a scale near the sheet scale.",
    obj(
        {
            "center_x_mm": number("detail circle centre x on the sheet (mm)"),
            "center_y_mm": number("detail circle centre y on the sheet (mm)"),
            "radius_mm": number("detail circle radius on the sheet (mm)", exclusiveMinimum=0),
            "place_x_mm": number("detail view x on the sheet (mm)", default=0),
            "place_y_mm": number("detail view y on the sheet (mm)", default=0),
            "parent_view": string(
                "view to detail; first model view if omitted", default=None
            ),
            "label": string("detail label", default="I"),
            "scale_numerator": number("absolute scale numerator", default=2),
            "scale_denominator": number("absolute scale denominator", default=1),
            "full_outline": boolean("draw the full outline", default=False),
            "jagged_outline": boolean("draw a jagged outline", default=False),
        },
        required=("center_x_mm", "center_y_mm", "radius_mm"),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_detail_view(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_detail_view(
            args.get("parent_view"),
            args["center_x_mm"],
            args["center_y_mm"],
            args["radius_mm"],
            args.get("place_x_mm", 0),
            args.get("place_y_mm", 0),
            args.get("label", "I"),
            args.get("scale_numerator", 2),
            args.get("scale_denominator", 1),
            args.get("full_outline", False),
            args.get("jagged_outline", False),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_create_sketch",
    "Open a sketch in a drawing view, which is where section and detail "
    "boundaries are drawn and where the normal sketch tools act. Geometry "
    "drawn here is in the view sketch's own space (the view's centre is the "
    "origin), not sheet millimetres; the section/detail tools convert sheet "
    "coordinates for you. Measured "
    "limitation: SW2026 SP0.0 cannot close a drawing view sketch through the "
    "API (exit_sketch reports view_sketch=true); geometry collects in the "
    "view's sketch until a section or detail command consumes it.",
    obj(
        {
            "view_name": string(
                "view to sketch in; first model view if omitted", default=None
            )
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_create_sketch(args: dict) -> dict:
    return envelope(run(lambda: drawings.create_sketch(args.get("view_name"))))


@registry.tool(
    "drawing_insert_center_marks",
    "Add center marks to the circular edges of a drawing view. By default "
    "every hole, fillet and slot in the view gets one; selected_only marks "
    "the circles this tool selects instead.",
    obj(
        {
            "view_name": string(
                "view to mark; first model view if omitted", default=None
            ),
            "style": string(
                "center mark style",
                enum=sorted(drawings.CENTER_MARK_STYLES),
                default="single",
            ),
            "propagate": boolean("propagate along the feature", default=True),
            "slots": boolean("include slot centres", default=False),
            "selected_only": boolean(
                "mark the view's circular edges one by one instead of using "
                "the automatic command",
                default=False,
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_center_marks(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_center_marks(
            args.get("view_name"),
            args.get("style", "single"),
            args.get("propagate", True),
            args.get("slots", False),
            args.get("selected_only", False),
        )
    )
    return envelope(result)


@registry.tool(
    "drawing_insert_centerlines",
    "Add centerline annotations to a drawing view. By default the axes of the "
    "view's circular holes are added as automatic center marks; selected_only "
    "uses InsertCenterLine2 on the circles this tool selects. The result "
    "distinguishes true centerlines from center marks.",
    obj(
        {
            "view_name": string(
                "view to mark; first model view if omitted", default=None
            ),
            "selected_only": boolean(
                "use InsertCenterLine2 on circular edges instead of the "
                "automatic hole-axis command",
                default=False,
            ),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_centerlines(args: dict) -> dict:
    result = run(
        lambda: drawings.insert_centerlines(
            args.get("view_name"),
            args.get("selected_only", False),
        )
    )
    return envelope(result)


@registry.tool(
    "verify_export",
    "Inspect an exported file and report structural facts: PDF pages, DXF "
    "entities and extents, STL triangles and bounding box, STEP/IGES sections. "
    "Read-only; paths are not sandboxed.",
    obj({"path": string("exported file to verify")}, required=("path",)),
    tier="extended",
    tags=("export", "inspect"),
)
def verify_export(args: dict) -> dict:
    return ok(artifacts.verify(args["path"]))


@registry.tool(
    "sketch_slot",
    "Draw a straight slot in the active sketch from two centre points and a "
    "width. length_type center_center measures between arc centres; "
    "full_length measures the overall length.",
    obj(
        {
            "x1_mm": number("first centre x (mm)"),
            "y1_mm": number("first centre y (mm)"),
            "x2_mm": number("second centre x (mm)"),
            "y2_mm": number("second centre y (mm)"),
            "width_mm": number("slot width (mm)", exclusiveMinimum=0),
            "length_type": string(
                "length interpretation",
                enum=sorted(sketch.SLOT_LENGTH_TYPES),
                default="center_center",
            ),
            "add_dimensions": boolean(
                "create the slot with its dimensions", default=False
            ),
        },
        required=("x1_mm", "y1_mm", "x2_mm", "y2_mm", "width_mm"),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_slot(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return sketch.slot(
            args["x1_mm"],
            args["y1_mm"],
            args["x2_mm"],
            args["y2_mm"],
            args["width_mm"],
            args.get("length_type", "center_center"),
            args.get("add_dimensions", False),
        )

    return ok(run(job))


@registry.tool(
    "sketch_trim",
    "Trim a sketch segment back to its nearest intersection. Put the segment "
    "to trim in segment_indices and give a point on the piece to remove.",
    obj(
        {
            "segment_indices": array(
                "the single segment to trim, from list_sketch_segments",
                {"type": "integer"},
            ),
            "x_mm": number("x of a point on the piece to remove (mm)"),
            "y_mm": number("y of a point on the piece to remove (mm)"),
            "mode": string(
                "trim mode", enum=sorted(sketch.TRIM_CHOICES), default="closest"
            ),
        },
        required=("segment_indices", "x_mm", "y_mm"),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_trim(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return sketch.trim(
            args["segment_indices"],
            args["x_mm"],
            args["y_mm"],
            args.get("mode", "closest"),
        )

    return ok(run(job))


@registry.tool(
    "sketch_mirror",
    "Mirror sketch entities about a construction centerline. Give the entities "
    "in segment_indices and the centerline in mirror_segment.",
    obj(
        {
            "segment_indices": array(
                "entities to mirror, from list_sketch_segments",
                {"type": "integer"},
            ),
            "mirror_segment": integer(
                "index of the construction centerline segment"
            ),
        },
        required=("segment_indices", "mirror_segment"),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_mirror(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return sketch.mirror(args["segment_indices"], args["mirror_segment"])

    return ok(run(job))


@registry.tool(
    "sketch_fillet",
    "Round the corner between two selected sketch segments.",
    obj(
        {
            "segment_indices": array(
                "the two segments sharing the corner", {"type": "integer"}
            ),
            "radius_mm": number("fillet radius (mm)", exclusiveMinimum=0),
            "keep_constraints": boolean("keep existing constraints", default=True),
        },
        required=("segment_indices", "radius_mm"),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_fillet(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return sketch.sketch_fillet(
            args["segment_indices"],
            args["radius_mm"],
            args.get("keep_constraints", True),
        )

    return ok(run(job))


@registry.tool(
    "sketch_chamfer",
    "Chamfer the corner between two selected sketch segments at an equal "
    "distance, or a distance and angle.",
    obj(
        {
            "segment_indices": array(
                "the two segments sharing the corner", {"type": "integer"}
            ),
            "distance_mm": number("chamfer distance (mm)", exclusiveMinimum=0),
            "angle_deg": number("angle for mode=distance_angle", default=45),
            "mode": string(
                "chamfer mode",
                enum=["equal_distance", "distance_angle"],
                default="equal_distance",
            ),
        },
        required=("segment_indices", "distance_mm"),
    ),
    tier="extended",
    tags=("sketch",),
)
def sketch_chamfer(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return sketch.sketch_chamfer(
            args["segment_indices"],
            args["distance_mm"],
            args.get("angle_deg", 45),
            args.get("mode", "equal_distance"),
        )

    return ok(run(job))


@registry.tool(
    "edit_sketch",
    "Reopen an existing sketch for editing by name from list_sketches. Close "
    "it again with exit_sketch.",
    obj({"name": string("sketch name from list_sketches")}, required=("name",)),
    tier="extended",
    tags=("sketch",),
)
def edit_sketch(args: dict) -> dict:
    return ok(run(lambda: sketch.edit_sketch(args["name"])))


@registry.tool(
    "simple_hole",
    "Drill a straight hole into a planar face. The hole centre is placed at "
    "(x_mm, y_mm) measured in millimetres from the face bounding-box minimum "
    "corner along ascending model X/Y, independent of the face normal. The "
    "point is checked against the trimmed face. This is geometry-only and "
    "does not create native Hole Wizard callout data.",
    obj(
        {
            "diameter_mm": number("hole diameter (mm)", exclusiveMinimum=0),
            "face_index": integer("planar face index from list_faces"),
            "x_mm": number("hole centre x on the face (mm)"),
            "y_mm": number("hole centre y on the face (mm)"),
            "depth_mm": number("blind hole depth (mm)", default=10),
            "end_condition": string(
                "end condition",
                enum=["blind", "through_all", "up_to_next"],
                default="blind",
            ),
            "reverse": boolean("drill the other way", default=False),
            "name": string("feature name override", default=None),
        },
        required=("diameter_mm", "face_index", "x_mm", "y_mm"),
    ),
    tier="extended",
    tags=("features",),
)
def simple_hole(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.simple_hole(
            args["diameter_mm"],
            args["face_index"],
            args["x_mm"],
            args["y_mm"],
            args.get("depth_mm", 10),
            args.get("end_condition", "blind"),
            args.get("reverse", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "thin_extrude",
    "Thin-wall extrude of the sketch shown on screen: the profile is swept "
    "as a wall of thickness_mm, on the outward, inward or mid side of it. "
    "cut=true makes it a thin cut.",
    obj(
        {
            "depth_mm": number("depth (mm); required for blind", default=None),
            "end_condition": string(
                "end condition", enum=["blind", "through_all"], default="blind"
            ),
            "thickness_mm": number("wall thickness (mm)", exclusiveMinimum=0, default=1),
            "side": string(
                "which side of the profile the wall sits on",
                enum=["outward", "inward", "mid"],
                default="mid",
            ),
            "cut": boolean("cut instead of boss", default=False),
            "reverse": boolean("flip the direction", default=False),
            "name": string("feature name override", default=None),
        },
        required=("thickness_mm",),
    ),
    tier="extended",
    tags=("features",),
)
def thin_extrude(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.thin_extrude(
            depth_mm=args.get("depth_mm"),
            end_condition=args.get("end_condition", "blind"),
            thickness_mm=args.get("thickness_mm", 1),
            side=args.get("side", "mid"),
            cut=args.get("cut", False),
            reverse=args.get("reverse", False),
            name=args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "counterbore_hole",
    "Drill a counterbore: the counterbore diameter to counterbore_depth_mm, "
    "the pilot diameter on to the full depth. The centre is placed at "
    "(x_mm, y_mm) on the planar face (measured from its minimum corner). "
    "The feature is two geometry-only cuts, not a native Hole Wizard feature; "
    "failure of the second cut rolls back the pilot and verifies the model fingerprint.",
    obj(
        {
            "diameter_mm": number("pilot diameter (mm)", exclusiveMinimum=0),
            "counterbore_diameter_mm": number(
                "counterbore diameter (mm)", exclusiveMinimum=0
            ),
            "counterbore_depth_mm": number(
                "counterbore depth (mm)", exclusiveMinimum=0
            ),
            "face_index": integer("planar face index from list_faces"),
            "x_mm": number("hole centre x on the face (mm)"),
            "y_mm": number("hole centre y on the face (mm)"),
            "depth_mm": number("pilot depth for blind holes (mm)", default=10),
            "end_condition": string(
                "end condition",
                enum=["blind", "through_all", "up_to_next"],
                default="blind",
            ),
            "name": string("feature name override", default=None),
        },
        required=(
            "diameter_mm",
            "counterbore_diameter_mm",
            "counterbore_depth_mm",
            "face_index",
            "x_mm",
            "y_mm",
        ),
    ),
    tier="extended",
    tags=("features",),
)
def counterbore_hole(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.counterbore_hole(
            args["diameter_mm"],
            args["counterbore_diameter_mm"],
            args["counterbore_depth_mm"],
            args["face_index"],
            args["x_mm"],
            args["y_mm"],
            args.get("depth_mm", 10),
            args.get("end_condition", "blind"),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "countersink_hole",
    "Drill a pilot hole and countersink its top edge at the given included "
    "angle (default 90 degrees). The centre is placed at (x_mm, y_mm) on the "
    "planar face (measured from its minimum corner). It is geometry-only and "
    "does not create native Hole Wizard callout data.",
    obj(
        {
            "diameter_mm": number("pilot diameter (mm)", exclusiveMinimum=0),
            "countersink_diameter_mm": number(
                "countersink diameter at the face (mm)", exclusiveMinimum=0
            ),
            "face_index": integer("planar face index from list_faces"),
            "x_mm": number("hole centre x on the face (mm)"),
            "y_mm": number("hole centre y on the face (mm)"),
            "angle_deg": number("countersink included angle (degrees)", default=90),
            "depth_mm": number("pilot depth for blind holes (mm)", default=10),
            "end_condition": string(
                "end condition",
                enum=["blind", "through_all", "up_to_next"],
                default="blind",
            ),
            "name": string("feature name override", default=None),
        },
        required=(
            "diameter_mm",
            "countersink_diameter_mm",
            "face_index",
            "x_mm",
            "y_mm",
        ),
    ),
    tier="extended",
    tags=("features",),
)
def countersink_hole(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.countersink_hole(
            args["diameter_mm"],
            args["countersink_diameter_mm"],
            args["face_index"],
            args["x_mm"],
            args["y_mm"],
            args.get("angle_deg", 90),
            args.get("depth_mm", 10),
            args.get("end_condition", "blind"),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "tapped_hole",
    "Drill a tap-drill hole and attach a cosmetic thread. The drill diameter "
    "defaults to diameter - pitch; the thread is cosmetic, so the geometry is "
    "the drilled hole. It does not create native Hole Wizard callout data.",
    obj(
        {
            "diameter_mm": number("nominal thread diameter (mm)", exclusiveMinimum=0),
            "pitch_mm": number("thread pitch (mm)", exclusiveMinimum=0),
            "face_index": integer("planar face index from list_faces"),
            "x_mm": number("hole centre x on the face (mm)"),
            "y_mm": number("hole centre y on the face (mm)"),
            "depth_mm": number("drill depth for blind holes (mm)", default=10),
            "end_condition": string(
                "end condition",
                enum=["blind", "through_all", "up_to_next"],
                default="blind",
            ),
            "drill_diameter_mm": number(
                "explicit tap-drill diameter (mm)", default=None
            ),
            "note": string("thread callout note (default M<diameter>x<pitch>)", default=None),
            "name": string("feature name override", default=None),
        },
        required=("diameter_mm", "pitch_mm", "face_index", "x_mm", "y_mm"),
    ),
    tier="extended",
    tags=("features",),
)
def tapped_hole(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.tapped_hole(
            args["diameter_mm"],
            args["pitch_mm"],
            args["face_index"],
            args["x_mm"],
            args["y_mm"],
            args.get("depth_mm", 10),
            args.get("end_condition", "blind"),
            args.get("drill_diameter_mm"),
            args.get("note"),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "cosmetic_thread",
    "Attach a cosmetic thread to one circular edge (a hole or a shaft). The "
    "diameter defaults to the edge's own diameter; pass it explicitly for a "
    "tapped hole's nominal size. The feature adds no geometry; the result "
    "carries the measured read-back.",
    obj(
        {
            "edge_index": integer("circular edge index from list_edges"),
            "depth_mm": number(
                "thread depth for a blind thread (mm)", default=None
            ),
            "diameter_mm": number(
                "thread diameter; default: from the edge", default=None
            ),
            "through": boolean("thread runs through the feature", default=False),
            "note": string("thread callout note, e.g. M6x1", default=""),
            "name": string("feature name override", default=None),
        },
        required=("edge_index",),
    ),
    tier="extended",
    tags=("features",),
)
def cosmetic_thread(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.cosmetic_thread(
            args["edge_index"],
            args.get("depth_mm"),
            args.get("diameter_mm"),
            args.get("through", False),
            args.get("note", ""),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "dome",
    "Dome a planar face by height_mm. On a circular face the added volume is "
    "a spherical cap; InsertDome returns nothing, so the result is judged by "
    "the feature tree and measured mass properties.",
    obj(
        {
            "height_mm": number("dome height (mm)", exclusiveMinimum=0),
            "face_index": integer("planar face index from list_faces"),
            "reverse": boolean("dome the other way", default=False),
            "elliptic": boolean("elliptical dome", default=False),
            "name": string("feature name override", default=None),
        },
        required=("height_mm", "face_index"),
    ),
    tier="extended",
    tags=("features",),
)
def dome(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.dome(
            args["height_mm"],
            args["face_index"],
            args.get("reverse", False),
            args.get("elliptic", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "draft",
    "Draft selected faces about a neutral plane or planar face. Angle is "
    "degrees; reverse=true removes material (the usual moulded-part choice).",
    obj(
        {
            "angle_deg": number("draft angle (degrees)", exclusiveMinimum=0),
            "face_indices": array(
                "faces to draft, from list_faces", {"type": "integer"}
            ),
            "neutral_face_index": integer(
                "planar face used as the neutral reference", default=None
            ),
            "neutral_plane": string(
                "plane name used as the neutral reference", default=None
            ),
            "reverse": boolean("draft inward instead of outward", default=False),
            "name": string("feature name override", default=None),
        },
        required=("angle_deg", "face_indices"),
    ),
    tier="extended",
    tags=("features",),
)
def draft(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.draft(
            args["angle_deg"],
            args["face_indices"],
            args.get("neutral_face_index"),
            args.get("neutral_plane"),
            args.get("reverse", False),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "sweep",
    "Sweep a closed profile sketch along a path sketch. Both sketches are "
    "named from list_sketches.",
    obj(
        {
            "profile_sketch": string("closed profile sketch name"),
            "path_sketch": string("path sketch name"),
            "cut": boolean("remove material instead of adding", default=False),
            "merge": boolean("merge with existing bodies", default=True),
            "keep_tangency": boolean("keep the path tangency", default=False),
            "twist_angle_deg": number("twist along the path (degrees)", default=0),
            "name": string("feature name override", default=None),
        },
        required=("profile_sketch", "path_sketch"),
    ),
    tier="extended",
    tags=("features",),
)
def sweep(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.sweep(
            args["profile_sketch"],
            args["path_sketch"],
            args.get("cut", False),
            args.get("merge", True),
            args.get("keep_tangency", False),
            args.get("twist_angle_deg", 0),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "loft",
    "Loft a solid through two or more profile sketches, in the order given.",
    obj(
        {
            "profile_sketches": array(
                "sketch names, ordered from one end of the loft to the other",
                {"type": "string"},
            ),
            "cut": boolean("remove material instead of adding", default=False),
            "closed": boolean("close the loft into a loop", default=False),
            "keep_tangency": boolean("keep tangency at the profiles", default=False),
            "merge": boolean("merge with existing bodies", default=True),
            "name": string("feature name override", default=None),
        },
        required=("profile_sketches",),
    ),
    tier="extended",
    tags=("features",),
)
def loft(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.loft(
            args["profile_sketches"],
            args.get("cut", False),
            args.get("closed", False),
            args.get("keep_tangency", False),
            args.get("merge", True),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "set_feature_suppression",
    "Suppress or unsuppress named features; the state is verified by "
    "read-back and measured mass properties.",
    obj(
        {
            "feature_names": array(
                "features to suppress or unsuppress", {"type": "string"}
            ),
            "suppressed": boolean("true suppresses, false unsuppresses", default=True),
        },
        required=("feature_names",),
    ),
    tier="extended",
    tags=("features",),
)
def set_feature_suppression(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.set_feature_suppression(
            args["feature_names"], args.get("suppressed", True)
        )

    return envelope(run(job))


@registry.tool(
    "create_axis",
    "Create a reference axis from a cylindrical face (face_index), a straight "
    "edge (edge_index), or two planes (planes). Use the returned axis name in "
    "circular_pattern or create_reference_plane.",
    obj(
        {
            "face_index": integer(
                "cylindrical or conical face index from list_faces", default=None
            ),
            "edge_index": integer(
                "straight edge index from list_edges", default=None
            ),
            "planes": array(
                "two plane names whose intersection is the axis",
                {"type": "string"},
                default=None,
            ),
            "name": string("axis name override", default=None),
        }
    ),
    tier="extended",
    tags=("reference",),
)
def create_axis(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.create_axis(
            args.get("face_index"),
            args.get("edge_index"),
            args.get("planes"),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "list_vertices",
    "List body vertices with positions and indices for measure.",
    obj(
        {
            "body_type": string(
                "body filter", enum=["all", "solid", "sheet", "wire"], default="all"
            )
        }
    ),
    tier="extended",
    tags=("inspect",),
)
def list_vertices(args: dict) -> dict:
    def job() -> dict:
        vertices = inspect.list_vertices(body_type=args.get("body_type", "all"))
        return {"vertices": vertices, "count": len(vertices)}

    return ok(run(job))


@registry.tool(
    "measure",
    "Measure selected topology: one face gives area and perimeter, one edge "
    "its length, two entities the distance and delta between them. Indices "
    "come from list_faces / list_edges / list_vertices.",
    obj(
        {
            "face_indices": array(
                "face indices to measure", {"type": "integer"}, default=None
            ),
            "edge_indices": array(
                "edge indices to measure", {"type": "integer"}, default=None
            ),
            "vertex_indices": array(
                "vertex indices to measure", {"type": "integer"}, default=None
            ),
        }
    ),
    tier="extended",
    tags=("inspect",),
)
def measure(args: dict) -> dict:
    return ok(
        run(
            lambda: inspect.measure(
                args.get("face_indices"),
                args.get("edge_indices"),
                args.get("vertex_indices"),
            )
        )
    )


@registry.tool(
    "list_mates",
    "Read back the assembly's mates with types, distances and mated "
    "component names.",
    obj({}),
    tier="extended",
    tags=("assemblies", "inspect"),
)
def list_mates(args: dict) -> dict:
    return ok(run(assemblies.list_mates))


@registry.tool(
    "set_component_fixed",
    "Fix or float named components; the resulting state is read back.",
    obj(
        {
            "component_names": array(
                "component names from list_components", {"type": "string"}
            ),
            "fixed": boolean("true fixes, false floats", default=True),
        },
        required=("component_names",),
    ),
    tier="extended",
    tags=("assemblies",),
)
def set_component_fixed(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return assemblies.set_component_fixed(
            args["component_names"], args.get("fixed", True)
        )

    return ok(run(job))
