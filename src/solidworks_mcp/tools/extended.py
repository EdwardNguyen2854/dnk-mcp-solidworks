"""Extended-tier tools: topology, finishing features, checkpoints."""
from __future__ import annotations

from .. import registry
from ..com.worker import run
from ..domain import assemblies, drawings, features, inspect, sketch
from ..errors import ok
from ..registry import array, boolean, integer, number, obj, string
from ..tx import checkpoint
from .core import envelope

MATE_TYPES = ["coincident", "concentric", "perpendicular", "parallel",
              "tangent", "distance", "angle"]
DIRECTIONS = ["+x", "-x", "+y", "-y", "+z", "-z"]


@registry.tool(
    "list_faces",
    "List planar/curved faces of every body with indices for selection.",
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
def list_faces(args: dict) -> dict:
    def job() -> dict:
        faces = inspect.list_faces(body_type=args.get("body_type", "all"))
        return {"faces": faces, "count": len(faces)}

    return ok(run(job))


@registry.tool(
    "list_edges",
    "List edges of every body with indices for selection (fillet, chamfer).",
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
def list_edges(args: dict) -> dict:
    def job() -> dict:
        edges = inspect.list_edges(body_type=args.get("body_type", "all"))
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
    "fillet",
    "Round the selected edges. Indices come from list_edges.",
    obj(
        {
            "radius_mm": number("fillet radius (mm)", exclusiveMinimum=0),
            "edge_indices": array(
                "edge indices from list_edges", {"type": "integer"}
            ),
            "propagate": boolean(
                "extend the fillet along tangent edges", default=True
            ),
            "name": string("feature name override", default=None),
        },
        required=("radius_mm", "edge_indices"),
    ),
    tier="extended",
    tags=("features",),
)
def fillet(args: dict) -> dict:
    def job() -> dict:
        checkpoint.maybe_auto_checkpoint()
        return features.fillet(
            args["radius_mm"],
            args["edge_indices"],
            args.get("propagate", True),
            args.get("name"),
        )

    return envelope(run(job))


@registry.tool(
    "chamfer",
    "Chamfer the selected edges at equal distance and angle. Indices come "
    "from list_edges.",
    obj(
        {
            "distance_mm": number("chamfer distance (mm)", exclusiveMinimum=0),
            "edge_indices": array(
                "edge indices from list_edges", {"type": "integer"}
            ),
            "angle_deg": number("chamfer angle (degrees)", default=45),
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
    "path).",
    obj(
        {
            "model": string(
                "model path or title; defaults to the active document", default=None
            ),
            "template": string("drawing template path", default=None),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def new_drawing(args: dict) -> dict:
    return ok(
        run(lambda: drawings.create_drawing(args.get("model"), args.get("template")))
    )


@registry.tool(
    "drawing_insert_view",
    "Insert a standard view of the model onto the active drawing sheet.",
    obj(
        {
            "view": string(
                "standard view",
                enum=["front", "back", "left", "right", "top", "bottom",
                      "isometric", "trimetric", "dimetric"],
            ),
            "x_mm": number("sheet x position (mm)", default=100),
            "y_mm": number("sheet y position (mm)", default=150),
            "model": string("model path or title", default=None),
        },
        required=("view",),
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_view(args: dict) -> dict:
    return ok(
        run(
            lambda: drawings.insert_model_view(
                args["view"],
                args.get("x_mm", 100),
                args.get("y_mm", 150),
                args.get("model"),
            )
        )
    )


@registry.tool(
    "drawing_insert_standard_views",
    "Insert front, top and right views onto the active drawing sheet.",
    obj(
        {
            "model": string("model path or title", default=None),
            "front_mm": array(
                "front view [x, y] on the sheet", {"type": "number"}, default=None
            ),
            "spacing_mm": number("view spacing (mm)", default=120),
        }
    ),
    tier="extended",
    tags=("drawings",),
)
def drawing_insert_standard_views(args: dict) -> dict:
    return ok(
        run(
            lambda: drawings.insert_standard_views(
                args.get("model"),
                args.get("front_mm"),
                args.get("spacing_mm", 120),
            )
        )
    )


@registry.tool(
    "list_drawing_views",
    "List views on the active drawing with names and outlines.",
    obj({}),
    tier="extended",
    tags=("drawings",),
)
def list_drawing_views(args: dict) -> dict:
    return ok(run(drawings.list_drawing_views))
