"""Measured verification of exported artifacts.

Pure file analysis: no COM, no third-party parsers, no network. The point is
to replace "the export returned True" with structural facts about the file
that was actually written (page counts, entity counts, extents, triangle
counts), because SOLIDWORKS' export calls report success the same way they
report everything else.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from ..errors import PathNotFoundError

IMAGE_SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".bmp": b"BM",
    ".tif": b"II*\x00",
    ".tiff": b"II*\x00",
}

TEXT_SIGNATURES = {
    ".step": b"ISO-10303-21",
    ".stp": b"ISO-10303-21",
    ".x_t": b"**",
    ".x_b": b"**",
}


def sniff(path: str | Path) -> dict:
    """Cheap format/signature check used as export evidence."""
    target = Path(path)
    if not target.is_file():
        raise PathNotFoundError(f"file not found: {target}")
    head = target.read_bytes()[:16]
    return {
        "format": target.suffix.lower().lstrip("."),
        "size_bytes": target.stat().st_size,
        "signature_ok": _signature_ok(target.suffix.lower(), head),
    }


def _signature_ok(suffix: str, head: bytes) -> bool:
    if suffix in IMAGE_SIGNATURES:
        return head.startswith(IMAGE_SIGNATURES[suffix])
    if suffix in TEXT_SIGNATURES:
        return head.lstrip().startswith(TEXT_SIGNATURES[suffix])
    if suffix == ".pdf":
        return head.startswith(b"%PDF-")
    if suffix == ".3mf":
        return head.startswith(b"PK")
    if suffix == ".dxf":
        return b"SECTION" in head or head.startswith(b"AutoCAD")
    if suffix == ".stl":
        return bool(head.strip())
    return bool(head)


def verify(path: str | Path) -> dict:
    """Structural facts about an exported file, with pass/fail checks."""
    target = Path(path)
    if not target.is_file():
        raise PathNotFoundError(f"file not found: {target}")
    data = target.read_bytes()
    suffix = target.suffix.lower()
    details: dict = {}
    checks: dict[str, bool] = {"signature": _signature_ok(suffix, data[:16])}

    if suffix == ".pdf":
        details, extra = _verify_pdf(data)
        checks.update(extra)
    elif suffix == ".dxf":
        details, extra = _verify_dxf(data)
        checks.update(extra)
    elif suffix == ".stl":
        details, extra = _verify_stl(data)
        checks.update(extra)
    elif suffix in (".step", ".stp"):
        details, extra = _verify_step(data)
        checks.update(extra)
    elif suffix in (".igs", ".iges"):
        details, extra = _verify_iges(data)
        checks.update(extra)
    elif suffix == ".3mf":
        details = {"zip_container": data[:2] == b"PK"}
        checks["zip_container"] = details["zip_container"]
    elif suffix in IMAGE_SIGNATURES:
        details = {"image": True}
    elif suffix == ".dwg":
        details = {"dwg_signature": data[:6] == b"AC10"}
        checks["dwg_signature"] = details["dwg_signature"]

    return {
        "path": str(target),
        "format": suffix.lstrip("."),
        "size_bytes": len(data),
        "details": details,
        "checks": checks,
        "ok": all(checks.values()),
    }


def _verify_pdf(data: bytes) -> tuple[dict, dict]:
    # Page objects are authoritative. A bare /Count regex also catches
    # outline dictionaries (where /Count counts outline items, not pages),
    # which reported a genuine one-page PDF as five pages.
    pages = len(re.findall(rb"/Type\s*/Page\b", data))
    counts = [
        int(item)
        for item in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)
    ]
    declared = max(counts) if counts else 0
    page_count = pages if pages else declared
    details = {
        "page_count": page_count,
        "page_objects": pages,
        "declared_count": declared,
        "page_count_consistent": pages == 0 or declared == 0 or pages == declared,
    }
    checks = {
        "trailer": b"%%EOF" in data[-4096:],
        "pages": page_count >= 1,
    }
    return details, checks


def _dxf_pairs(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(lines) - 1, 2):
        pairs.append((lines[index].strip(), lines[index + 1].strip()))
    return pairs


def _verify_dxf(data: bytes) -> tuple[dict, dict]:
    try:
        text = data.decode("latin-1")
    except Exception:
        return {"binary": True}, {"decodable": False}
    pairs = _dxf_pairs(text)
    in_entities = False
    counts: dict[str, int] = {}
    xs: list[float] = []
    ys: list[float] = []
    for index, (code, value) in enumerate(pairs):
        if code == "0":
            if value == "SECTION":
                if index + 1 < len(pairs) and pairs[index + 1][0] == "2":
                    in_entities = pairs[index + 1][1] == "ENTITIES"
            elif value == "ENDSEC":
                in_entities = False
            elif in_entities and value:
                counts[value] = counts.get(value, 0) + 1
        elif in_entities and code in ("10", "11", "20", "21"):
            try:
                number = float(value)
            except ValueError:
                continue
            (xs if code in ("10", "11") else ys).append(number)
    total = sum(counts.values())
    details: dict = {"entities": total, "by_type": counts}
    checks = {"entities": total > 0}
    if xs and ys:
        details["extents_mm"] = {
            "min": [round(min(xs), 4), round(min(ys), 4)],
            "max": [round(max(xs), 4), round(max(ys), 4)],
            "size_mm": [
                round(max(xs) - min(xs), 4),
                round(max(ys) - min(ys), 4),
            ],
        }
        checks["extents"] = True
    return details, checks


def _stl_bbox(points: list[tuple[float, float, float]]) -> list[list[float]]:
    axes = list(zip(*points))
    return [
        [round(min(axis), 4) for axis in axes],
        [round(max(axis), 4) for axis in axes],
    ]


def _verify_stl(data: bytes) -> tuple[dict, dict]:
    stripped = data.lstrip()
    if stripped[:5].lower() == b"solid" and b"facet" in stripped[:4096].lower():
        vertices = re.findall(
            rb"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", data
        )
        triangles = len(re.findall(rb"facet\s+normal", data))
        details: dict = {
            "ascii": True,
            "triangle_count": triangles,
            "vertex_count": len(vertices),
        }
        if vertices:
            points = [
                (float(x), float(y), float(z)) for x, y, z in vertices
            ]
            details["bbox_mm"] = _stl_bbox(points)
        return details, {"triangles": triangles > 0}
    if len(data) < 84:
        return {"ascii": False}, {"triangles": False}
    declared = struct.unpack("<I", data[80:84])[0]
    expected = 84 + 50 * declared
    details = {
        "ascii": False,
        "triangle_count": declared,
        "size_matches": len(data) == expected,
    }
    if declared and declared < 2_000_000 and len(data) >= 134:
        points = []
        for index in range(min(declared, 2_000_000)):
            offset = 84 + 50 * index
            values = struct.unpack_from("<12f", data, offset)
            for vertex in range(3):
                base = 3 + vertex * 3
                points.append(
                    (values[base], values[base + 1], values[base + 2])
                )
        details["bbox_mm"] = _stl_bbox(points)
    checks = {"triangles": declared > 0, "size_matches": bool(details["size_matches"])}
    return details, checks


def _verify_step(data: bytes) -> tuple[dict, dict]:
    text = data.decode("latin-1", errors="replace")
    details = {
        "solids": text.count("MANIFOLD_SOLID_BREP"),
        "advanced_faces": text.count("ADVANCED_FACE"),
    }
    checks = {
        "terminator": "END-ISO-10303-21" in text[-8192:],
        "geometry": details["solids"] > 0 or details["advanced_faces"] > 0,
    }
    return details, checks


def _verify_iges(data: bytes) -> tuple[dict, dict]:
    text = data.decode("latin-1", errors="replace")
    # IGES is fixed-width: column 73 is the section letter.
    sections: dict[str, int] = {}
    for line in text.splitlines():
        if len(line) >= 80 and line[72:73] in "SGDPT":
            letter = line[72:73]
            sections[letter] = sections.get(letter, 0) + 1
    details = {"sections": sections}
    checks = {
        "terminator": sections.get("T", 0) >= 1,
        "geometry": sections.get("D", 0) > 0,
    }
    return details, checks
