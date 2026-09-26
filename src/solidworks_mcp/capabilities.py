"""Capability discovery: what this server can do right now, on this machine."""
from __future__ import annotations

from . import __version__
from .com import binding
from .com.connect import revision
from .com.worker import run
from .config import TEMPLATE_FILES, get_config
from .domain import session
from .errors import SwMcpError

DOMAINS = {
    "documents": "create/open/save/close/list; part, assembly and drawing",
    "sketching": "planes and planar faces; lines, circles, arcs, ellipses, "
    "rectangles, polygons, splines, slots, points; relations, dimensions with "
    "read-back and re-drive, offset, convert, trim, fillet, chamfer, mirror, "
    "construction toggle, sketch re-editing",
    "features": "boss/cut extrude, revolve, fillet, chamfer, shell, simple "
    "holes, draft, sweep, loft, feature suppression, reference planes and "
    "axes, linear/circular patterns, mirror",
    "inspection": "mass properties, bounding box, feature/face/edge/body/"
    "vertex listings, point and face measurement, What's Wrong",
    "export": "STEP, IGES, STL, 3MF, Parasolid, PDF, DXF, DWG; screenshots; "
    "structural export verification",
    "transactions": "file checkpoints and rollback",
    "assemblies": "components, origin placement, planar-face mates with "
    "read-back, fix/float, interference detection, bounding box",
    "drawings": "ISO metric drawing profile, framed sheets, standard views, "
    "millimetre unit verification, model dimensions, auto-dimension, notes, "
    "custom properties, manifests, release validation, PDF/DXF export",
}


def collect() -> dict:
    config = get_config()

    def probe_solidworks() -> dict:
        info: dict = {}
        try:
            application = session.app()
            info["connected"] = True
            info["revision"] = revision(application)
            raw = application.ActiveDoc
            if raw is not None:
                info["active_document"] = session.doc_info(session.wrap_doc(raw))
        except SwMcpError as error:
            info["connected"] = False
            info["error"] = error.to_dict()
        return info

    try:
        binding_info = {
            "libid": binding.SLDWORKS_LIBID,
            "typelib_version": list(binding.version()),
        }
    except SwMcpError as error:
        binding_info = {"error": error.to_dict()}

    templates: dict[str, str | None] = {}
    for kind in TEMPLATE_FILES:
        try:
            templates[kind] = str(config.find_template(kind))
        except SwMcpError:
            templates[kind] = None

    return {
        "server": {"name": "solidworks-mcp-core", "version": __version__},
        "tool_tier": config.tool_tier,
        "binding": binding_info,
        "solidworks": run(probe_solidworks),
        "templates": templates,
        "paths": {
            "output_root": str(config.output_root),
            "allowed_roots": [str(root) for root in config.effective_roots()],
            "checkpoint_root": str(config.checkpoint_root),
        },
        "policy": {
            "auto_checkpoint": config.auto_checkpoint,
            "checkpoint_debounce_sec": config.checkpoint_debounce_sec,
            "operation_timeout_sec": config.operation_timeout_sec,
        },
        "domains": DOMAINS,
    }
