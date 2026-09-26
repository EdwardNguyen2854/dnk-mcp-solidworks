"""Export documents and capture screenshots as MCP image content."""
from __future__ import annotations

import base64
import time
from pathlib import Path

from ..com import binding
from ..config import get_config
from ..errors import ComCallError, InvalidParameterError, PathNotFoundError
from . import artifacts, session

EXPORT_FORMATS = {
    "step": ".step",
    "stp": ".step",
    "iges": ".igs",
    "igs": ".igs",
    "stl": ".stl",
    "3mf": ".3mf",
    "parasolid": ".x_t",
    "x_t": ".x_t",
    "pdf": ".pdf",
    "dxf": ".dxf",
    "dwg": ".dwg",
    "png": ".png",
    "jpg": ".jpg",
    "bmp": ".bmp",
    "tif": ".tif",
}


def export_document(path: str, file_format: str | None = None) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    config = get_config()
    if file_format:
        suffix = EXPORT_FORMATS.get(file_format.lower())
        if suffix is None:
            raise InvalidParameterError(
                f"unknown format {file_format!r}",
                available=sorted(set(EXPORT_FORMATS)),
            )
        path = str(Path(path).with_suffix(suffix))
    target = config.resolve_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    result = doc.Extension.SaveAs3(str(target), 0, 1, None, None, 0, 0)
    ok, (errors, warnings) = session.com_result(result, 2)
    if not ok or not target.exists():
        raise ComCallError(
            f"export to {target} failed",
            error_code=int(errors or 0),
            warning_code=int(warnings or 0),
            hint="An empty part has nothing to export; build geometry first."
            if target.suffix.lower() not in (".pdf", ".png", ".jpg", ".bmp", ".tif")
            else None,
        )
    size = target.stat().st_size
    if size == 0:
        raise ComCallError(f"export produced an empty file: {target}")
    return {
        "path": str(target),
        "size_bytes": size,
        "format": target.suffix.lstrip("."),
        "artifact": artifacts.sniff(target),
    }


def capture_screenshot(
    path: str | None = None,
    view: str | None = "isometric",
    width: int = 1600,
    height: int = 900,
) -> dict:
    _, doc, _ = session.active_doc(("part", "assembly", "drawing"))
    config = get_config()
    if view:
        session.set_view(doc, view)
    if path:
        target = config.resolve_output_path(path)
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = config.output_root / "screenshots" / f"shot-{stamp}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    bmp_path = target.with_suffix(".bmp")
    if bmp_path.exists():
        bmp_path.unlink()
    ok = doc.SaveBMP(str(bmp_path), width, height)
    if not ok or not bmp_path.exists():
        raise ComCallError("SOLIDWORKS could not save the screen image")
    try:
        from PIL import Image

        with Image.open(bmp_path) as image:
            image.convert("RGB").save(target, format="PNG")
        bmp_path.unlink(missing_ok=True)
    except ImportError:
        target = bmp_path
    data = base64.b64encode(target.read_bytes()).decode("ascii")
    mime = "image/png" if target.suffix.lower() == ".png" else "image/bmp"
    return {
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "_images": [{"data": data, "mime": mime}],
    }
