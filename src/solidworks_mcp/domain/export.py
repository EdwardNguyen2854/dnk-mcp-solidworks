"""Export documents and capture screenshots as MCP image content."""
from __future__ import annotations

import base64
import os
import time
from io import BytesIO
from pathlib import Path

from ..com import binding
from ..config import get_config
from ..errors import (
    ComCallError,
    InvalidParameterError,
    PathNotFoundError,
)
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

MAX_REFERENCE_IMAGE_BYTES = 16 * 1024 * 1024
MAX_REFERENCE_IMAGE_PIXELS = 24_000_000


def _is_network_path(path: str) -> bool:
    if path.startswith(("\\\\", "//")):
        return True
    candidate = Path(path)
    if os.name != "nt" or not candidate.is_absolute() or not candidate.drive:
        return False
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(
            f"{candidate.drive}\\"
        )
    except (AttributeError, OSError):
        return True
    return drive_type in {0, 1, 4}


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


def view_reference_image(path: str) -> dict:
    """Read a local PNG/JPEG and return it as MCP image content.

    Absolute paths follow the existing read policy for CAD documents; relative
    paths resolve under the configured output root. The image is decoded,
    orientation-corrected, and re-encoded to strip metadata before it is
    presented to the MCP client.
    """
    if _is_network_path(path):
        raise InvalidParameterError(
            "network image paths are not supported",
            hint="Use an image stored on a local drive.",
        )
    target = Path(path).expanduser()
    if target.is_absolute():
        target = target.resolve()
    else:
        target = get_config().resolve_output_path(path, must_exist=True)
    if _is_network_path(str(target)):
        raise InvalidParameterError(
            "network image paths are not supported",
            hint="Use an image stored on a local drive.",
        )
    try:
        if not target.is_file():
            raise PathNotFoundError(f"reference image does not exist: {target}")
        with target.open("rb") as stream:
            source_bytes = stream.read(MAX_REFERENCE_IMAGE_BYTES + 1)
    except OSError as exc:
        raise PathNotFoundError(
            f"could not read reference image: {target}",
            hint="Check that the path exists and is readable.",
        ) from exc

    if len(source_bytes) > MAX_REFERENCE_IMAGE_BYTES:
        raise InvalidParameterError(
            f"reference image exceeds the {MAX_REFERENCE_IMAGE_BYTES}-byte limit",
            hint="Use a smaller PNG/JPEG or reduce its resolution before retrying.",
            max_bytes=MAX_REFERENCE_IMAGE_BYTES,
        )

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(source_bytes)) as source:
            source_format = source.format
            if source_format not in {"PNG", "JPEG"}:
                raise InvalidParameterError(
                    f"unsupported reference image format: {source_format or 'unknown'}",
                    hint="Use a PNG or JPEG image.",
                    available=["PNG", "JPEG"],
                )
            if source.width * source.height > MAX_REFERENCE_IMAGE_PIXELS:
                raise InvalidParameterError(
                    "reference image exceeds the pixel limit",
                    hint="Reduce the image resolution before retrying.",
                    max_pixels=MAX_REFERENCE_IMAGE_PIXELS,
                    width_px=source.width,
                    height_px=source.height,
                )
            source.load()
            image = ImageOps.exif_transpose(source)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            output_format = "PNG" if source_format == "PNG" else "JPEG"
            output = BytesIO()
            save_options = (
                {"optimize": True}
                if output_format == "PNG"
                else {"quality": 95, "optimize": True}
            )
            image.save(output, format=output_format, **save_options)
    except InvalidParameterError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise InvalidParameterError(
            "could not decode the reference image",
            hint="Provide a valid PNG or JPEG image and retry.",
        ) from exc

    image_bytes = output.getvalue()
    if len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
        raise InvalidParameterError(
            "normalized reference image exceeds the MCP image-content size limit",
            hint="Reduce the image resolution before retrying.",
            max_bytes=MAX_REFERENCE_IMAGE_BYTES,
        )

    mime = "image/png" if output_format == "PNG" else "image/jpeg"
    return {
        "data": {
            "path": str(target.resolve()),
            "format": output_format.lower(),
            "width_px": image.width,
            "height_px": image.height,
            "source_size_bytes": len(source_bytes),
            "content_size_bytes": len(image_bytes),
        },
        "evidence": {
            "input_format": source_format.lower(),
            "orientation_corrected": True,
            "metadata_stripped": True,
            "ocr_performed": False,
            "geometry_extraction_performed": False,
        },
        "_images": [
            {"data": base64.b64encode(image_bytes).decode("ascii"), "mime": mime}
        ],
    }
