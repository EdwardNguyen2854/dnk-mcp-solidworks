import struct

import pytest

from solidworks_mcp.domain import artifacts
from solidworks_mcp.errors import PathNotFoundError


def write(tmp_path, name, data):
    target = tmp_path / name
    target.write_bytes(data)
    return target


def test_pdf_verification(tmp_path):
    data = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type /Pages /Count 1 /Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type /Page /Parent 2 0 R>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    result = artifacts.verify(write(tmp_path, "drawing.pdf", data))
    assert result["ok"]
    assert result["details"]["page_count"] == 1
    assert result["checks"]["trailer"] is True


def test_pdf_without_trailer_fails(tmp_path):
    result = artifacts.verify(write(tmp_path, "broken.pdf", b"%PDF-1.4\n"))
    assert not result["ok"]
    assert result["checks"]["pages"] is False


def test_pdf_outline_count_does_not_inflate_pages(tmp_path):
    # A PDF outline's /Count counts outline items, not pages. The old
    # "max over every /Count" logic reported this one-page file as 5 pages.
    data = (
        b"%PDF-1.5\n"
        b"1 0 obj<</Type /Catalog /Pages 2 0 R /Outlines 5 0 R>>endobj\n"
        b"2 0 obj<</Type /Pages /Count 1 /Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type /Page /Parent 2 0 R>>endobj\n"
        b"5 0 obj<</Type /Outlines /Count 5 /First 6 0 R /Last 9 0 R>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    result = artifacts.verify(write(tmp_path, "outline.pdf", data))
    assert result["ok"]
    assert result["details"]["page_count"] == 1
    assert result["details"]["declared_count"] == 1
    assert result["details"]["page_count_consistent"] is True


def test_dxf_entities_and_extents(tmp_path):
    data = (
        "0\nSECTION\n2\nENTITIES\n"
        "0\nLINE\n8\n0\n10\n0.0\n20\n0.0\n11\n100.0\n21\n0.0\n"
        "0\nLINE\n8\n0\n10\n100.0\n20\n0.0\n11\n100.0\n21\n60.0\n"
        "0\nCIRCLE\n8\n0\n10\n20.0\n20\n30.0\n40\n5.0\n"
        "0\nENDSEC\n0\nEOF\n"
    ).encode("ascii")
    result = artifacts.verify(write(tmp_path, "view.dxf", data))
    assert result["ok"]
    assert result["details"]["entities"] == 3
    assert result["details"]["by_type"]["LINE"] == 2
    assert result["details"]["by_type"]["CIRCLE"] == 1
    extents = result["details"]["extents_mm"]
    assert extents["min"] == [0.0, 0.0]
    assert extents["max"] == [100.0, 60.0]


def test_binary_stl_triangles_and_bbox(tmp_path):
    header = b"binary stl test".ljust(80, b"\0")
    body = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 0, 5, 0, 0)
    data = header + struct.pack("<I", 1) + body
    result = artifacts.verify(write(tmp_path, "part.stl", data))
    assert result["ok"]
    assert result["details"]["triangle_count"] == 1
    assert result["details"]["size_matches"] is True
    assert result["details"]["bbox_mm"] == [[0.0, 0.0, 0.0], [10.0, 5.0, 0.0]]


def test_ascii_stl(tmp_path):
    data = (
        b"solid test\n"
        b"facet normal 0 0 1\n outer loop\n"
        b"  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n"
        b" endloop\nendfacet\nendsolid test\n"
    )
    result = artifacts.verify(write(tmp_path, "part.stl", data))
    assert result["ok"]
    assert result["details"]["ascii"] is True
    assert result["details"]["triangle_count"] == 1


def test_step_geometry_check(tmp_path):
    data = (
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
        b"#1=MANIFOLD_SOLID_BREP('',#2);\n"
        b"ENDSEC;\nEND-ISO-10303-21;\n"
    )
    result = artifacts.verify(write(tmp_path, "part.step", data))
    assert result["ok"]
    assert result["details"]["solids"] == 1


def test_sniff_reports_signature(tmp_path):
    target = write(tmp_path, "shot.png", b"\x89PNG\r\n\x1a\nrest")
    result = artifacts.sniff(target)
    assert result["format"] == "png"
    assert result["signature_ok"] is True
    assert result["size_bytes"] == 12


def test_missing_file_raises(tmp_path):
    with pytest.raises(PathNotFoundError):
        artifacts.verify(tmp_path / "nope.pdf")
