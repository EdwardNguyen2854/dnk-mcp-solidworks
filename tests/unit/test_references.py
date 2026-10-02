"""Unit tests for entity-reference tokens and fingerprint matching.

Pure logic only; COM-backed behavior is covered by
``scripts/acceptance_selection.py`` on a live session.
"""
from __future__ import annotations

import base64
import json

import pytest

from solidworks_mcp.domain import references
from solidworks_mcp.errors import InvalidParameterError


def make_token(**overrides) -> str:
    payload = {
        "v": 1,
        "doc": {"title": "Part1.SLDPRT", "path": "", "type": "part"},
        "kind": "face",
        "persist": base64.b64encode(b"persist-bytes").decode("ascii"),
        "fp": {"surface": "plane", "area_mm2": 100.0, "normal": [0.0, 0.0, 1.0]},
    }
    payload.update(overrides)
    return references._encode(payload)


def test_token_round_trip() -> None:
    token = make_token()
    payload = references.decode_reference(token)
    assert payload["v"] == 1
    assert payload["kind"] == "face"
    assert payload["fp"]["area_mm2"] == 100.0


def test_token_rejects_garbage_and_unknown_versions() -> None:
    for bad in ("", "not-base64!", "e30"):  # e30 is `{}` with no version
        with pytest.raises(InvalidParameterError):
            references.decode_reference(bad)
    with pytest.raises(InvalidParameterError):
        references.decode_reference(make_token(v=99))
    with pytest.raises(InvalidParameterError):
        references.decode_reference(make_token(kind="wormhole"))
    assert len(make_token()) <= references.MAX_TOKEN_CHARS


def test_face_fingerprint_matching() -> None:
    fp = {
        "surface": "plane",
        "area_mm2": 6000.0,
        "normal": [0.0, 0.0, 1.0],
        "box_mm": {"min": [-50.0, -30.0, 25.0], "max": [50.0, 30.0, 25.0]},
    }
    same = dict(fp)
    assert references._face_matches(same, fp)
    assert not references._face_matches({**same, "surface": "cylinder"}, fp)
    assert not references._face_matches({**same, "area_mm2": 6000.5}, fp)
    assert not references._face_matches({**same, "normal": [0.0, 1.0, 0.0]}, fp)
    shifted = {**same, "box_mm": {"min": [-50.0, -30.0, 25.2], "max": [50.0, 30.0, 25.0]}}
    assert not references._face_matches(shifted, fp)


def test_edge_fingerprint_matching() -> None:
    fp = {
        "curve": "line",
        "length_mm": 25.0,
        "start_mm": [-50.0, -30.0, 25.0],
        "end_mm": [-50.0, -30.0, 0.0],
    }
    same = dict(fp)
    assert references._edge_matches(same, fp)
    assert not references._edge_matches({**same, "curve": "circle"}, fp)
    assert not references._edge_matches({**same, "length_mm": 25.5}, fp)
    moved = {**same, "start_mm": [-49.5, -30.0, 25.0]}
    assert not references._edge_matches(moved, fp)


def test_vertex_fingerprint_matching() -> None:
    fp = {"point_mm": [1.0, 2.0, 3.0]}
    assert references._vertex_matches({"point_mm": [1.0, 2.0, 3.0]}, fp)
    assert not references._vertex_matches({"point_mm": [1.0, 2.0, 3.2]}, fp)
    assert references._vertex_matches({}, {}) is True


def test_labels_and_measurements() -> None:
    assert references._label("face", {"surface": "plane", "area_mm2": 6000.0}) == "plane face, 6000 mm2"
    assert references._label("edge", {"curve": "line", "length_mm": 25.0}) == "line edge, 25 mm"
    assert references._label("vertex", {"point_mm": [0.0, 0.0, 25.0]}) == "Vertex at (0, 0, 25) mm"
    assert references._label("plane", {}, 4) == "Selected plane"
    assert references._measurements("face", {"area_mm2": 6000.0}) == [
        {"name": "area", "value": 6000.0, "unit": "mm2"}
    ]
    assert references._measurements("edge", {"length_mm": 25.0}) == [
        {"name": "length", "value": 25.0, "unit": "mm"}
    ]
    assert references._measurements("vertex", {}) == []


def test_document_scope_mismatch_is_explicit() -> None:
    payload = references.decode_reference(make_token())
    # A fake document object is enough for the pure comparison helper.
    class FakeDoc:
        pass

    original_doc_info = references.session.doc_info
    try:
        references.session.doc_info = lambda _doc: {
            "title": "Other.SLDPRT",
            "path": "",
            "type": "part",
        }
        from solidworks_mcp.errors import ReferenceDocumentMismatchError

        with pytest.raises(ReferenceDocumentMismatchError):
            references._check_scope(FakeDoc(), payload)
    finally:
        references.session.doc_info = original_doc_info


def test_encoded_token_is_json_base64() -> None:
    token = make_token()
    decoded = json.loads(base64.urlsafe_b64decode(token))
    assert decoded["v"] == 1
