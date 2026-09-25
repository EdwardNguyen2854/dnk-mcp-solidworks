"""Extended-tier tools: topology, finishing features, checkpoints."""
from __future__ import annotations

from .. import registry
from ..com.worker import run
from ..domain import features, inspect, sketch
from ..errors import ok
from ..registry import array, boolean, integer, number, obj, string
from ..tx import checkpoint
from .core import envelope


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
