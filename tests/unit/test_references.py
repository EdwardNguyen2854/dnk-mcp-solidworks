"""Entity-reference behavior: pure token logic plus a fake COM boundary.

Pure logic is tested directly; COM-backed identity and highlight behavior run
against a fake external boundary here and against a live session in
``scripts/acceptance_selection.py``.
"""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from solidworks_mcp.com import binding
from solidworks_mcp.domain import features, references, session
from solidworks_mcp.errors import (
    ComCallError,
    InvalidParameterError,
    ReferenceAmbiguousError,
    ReferenceDocumentMismatchError,
    ReferenceNotFoundError,
    SelectionError,
)


class Face:
    def __init__(self, persist, area=100.0):
        self.persist = persist
        self.area = area
        self.Normal = [0.0, 0.0, 1.0]
        self.unreadable = False

    def GetSurface(self):
        return SimpleNamespace(IsPlane=True)

    def GetArea(self):
        if self.unreadable:
            raise RuntimeError("COM area read failed")
        return self.area / 1_000_000

    def GetBox(self):
        return [0.0, 0.0, 0.01, 0.01, 0.01, 0.01]

    def Select4(self, append, data):
        if not append:
            self.doc.ClearSelection2(True)
        self.doc.selection.append(self)
        self.doc.marks.append(data.Mark)
        return True


class Document:
    def __init__(self):
        self.faces = [Face(b"original")]
        self.selection = [self.faces[0]]
        self.selection_type = 2
        self.marks = [0]
        self.faces[0].doc = self
        self.clear_calls = 0
        self.Extension = SimpleNamespace(
            GetPersistReference3=lambda entity: entity.persist,
            IsSamePersistentID=lambda first, second: first == second,
            GetObjectByPersistReference3=lambda persist, error: (self.faces[0], 0),
        )
        self.SelectionManager = SimpleNamespace(
            GetSelectedObjectCount2=lambda mark: len(self.selection),
            GetSelectedObject6=lambda position, mark: self.selection[position - 1],
            GetSelectedObjectType3=lambda position, mark: self.selection_type,
            GetSelectedObjectMark=lambda position: self.marks[position - 1],
            CreateSelectData=lambda: SimpleNamespace(Mark=0),
            DeSelect2=self.deselect,
        )

    def GetBodies2(self, kind, visible):
        return [SimpleNamespace(GetFaces=lambda: self.faces)]

    def GetTitle(self):
        return "Part1.SLDPRT"

    def GetPathName(self):
        return "C:\\Part1.SLDPRT"

    def GetType(self):
        return 1

    def GetSaveFlag(self):
        return False

    def ClearSelection2(self, all_marks):
        self.clear_calls += 1
        self.selection.clear()
        self.marks.clear()

    def deselect(self, position, mark):
        self.selection.pop(position - 1)
        self.marks.pop(position - 1)
        return 1


@pytest.fixture
def doc(monkeypatch):
    document = Document()
    # Only replace the external COM attach/dispatch boundary.
    monkeypatch.setattr(session, "attach", lambda: SimpleNamespace(ActiveDoc=document))
    monkeypatch.setattr(binding, "wrap", lambda value, interface: value)
    return document


def test_persist_identity_wins_over_another_faces_unique_fingerprint(doc):
    captured = references.capture_selection()
    reference = captured["entities"][0]["ref"]
    doc.faces[0].area = 400.0
    doc.faces.append(Face(b"impostor", area=100.0))
    resolved = references.resolve_entity_reference(reference)
    assert resolved["index"] == 0
    assert resolved["measurements"] == [{"name": "area", "value": 400.0, "unit": "mm2"}]


def test_multiple_persistent_identity_matches_fail_closed(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces.append(Face(b"original"))
    with pytest.raises(ReferenceAmbiguousError):
        references.resolve_entity_reference(reference)


def test_unique_fingerprint_fallback_when_persistent_identity_is_lost(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces[0].persist = b"replacement"
    assert references.resolve_entity_reference(reference)["index"] == 0


def test_ambiguous_fingerprint_fallback_fails_closed(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces[:] = [Face(b"replacement-a"), Face(b"replacement-b")]
    with pytest.raises(ReferenceAmbiguousError):
        references.resolve_entity_reference(reference)


def test_missing_reference_fails_closed(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces.clear()
    with pytest.raises(ReferenceNotFoundError):
        references.resolve_entity_reference(reference)


def test_unverifiable_persistent_identity_does_not_select_an_impostor(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces[0].area = 400.0
    doc.faces.append(Face(b"impostor", area=100.0))

    def compare(first, second):
        if second == b"original":
            raise RuntimeError("COM comparison failed")
        return first == second

    doc.Extension.IsSamePersistentID = compare
    with pytest.raises(ComCallError):
        references.resolve_entity_reference(reference)


def test_unreadable_candidate_does_not_make_fallback_appear_unique(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces[0].persist = b"changed"
    doc.faces[0].unreadable = True
    doc.faces.append(Face(b"impostor", area=100.0))
    with pytest.raises(ComCallError):
        references.resolve_entity_reference(reference)


def test_unsupported_highlight_keeps_engineer_selection(doc):
    doc.selection_type = 4
    reference = references.capture_selection()["entities"][0]["ref"]
    baseline = list(doc.selection)
    with pytest.raises(SelectionError):
        references.highlight_entities([reference], owner="unsupported")
    assert doc.selection == baseline
    assert doc.clear_calls == 0


def test_owned_highlight_appends_and_clear_preserves_engineer_selection(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    engineer_face = Face(b"engineer", area=200.0)
    engineer_face.doc = doc
    doc.faces.append(engineer_face)
    doc.selection = [engineer_face]
    doc.marks = [7]
    result = references.highlight_entities([reference], owner="append-clear")
    assert result["status"] == "applied"
    assert doc.selection == [engineer_face, doc.faces[0]]
    assert doc.marks[0] == 7
    result = references.highlight_entities([], clear=True, owner="append-clear")
    assert result["status"] == "cleared"
    assert doc.selection == [engineer_face]
    assert doc.marks == [7]
    assert doc.clear_calls == 0


def test_unmarked_cad_side_effect_is_not_reported_as_cleaned_up(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.selection = []
    doc.marks = []

    def select_without_mark(append, data):
        doc.selection.append(doc.faces[0])
        doc.marks.append(0)
        return True

    doc.faces[0].Select4 = select_without_mark
    result = references.highlight_entities([reference], owner="lost-mark")
    assert result["status"] == "cleanup_unknown"
    assert doc.selection == [doc.faces[0]]
    doc.selection.clear()
    doc.marks.clear()
    assert references.highlight_entities([], clear=True, owner="lost-mark")["status"] == "cleared"


def test_already_selected_entity_keeps_its_engineer_mark_after_clear(doc):
    doc.marks = [12]
    reference = references.capture_selection()["entities"][0]["ref"]
    result = references.highlight_entities([reference], owner="already-selected")
    assert result["owned"] == 0
    references.highlight_entities([], clear=True, owner="already-selected")
    assert doc.selection == [doc.faces[0]]
    assert doc.marks == [12]


def test_clear_before_apply_fences_a_delayed_highlight(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    baseline = list(doc.selection)
    references.highlight_entities([], clear=True, owner="clear-before-apply")
    result = references.highlight_entities([reference], owner="clear-before-apply")
    assert result["status"] == "cleared"
    assert doc.selection == baseline


def test_clear_does_not_remove_an_entity_reselected_by_the_engineer(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.selection = []
    doc.marks = []
    references.highlight_entities([reference], owner="engineer-takeover")
    doc.marks = [0]
    references.highlight_entities([], clear=True, owner="engineer-takeover")
    assert doc.selection == [doc.faces[0]]
    assert doc.marks == [0]


def test_partial_highlight_failure_removes_only_the_successfully_added_entries(doc):
    doc.faces.append(Face(b"second", area=200.0))
    doc.faces[1].doc = doc
    doc.selection = list(doc.faces)
    doc.marks = [0, 0]
    refs = [item["ref"] for item in references.capture_selection()["entities"]]
    doc.selection = []
    doc.marks = []
    doc.faces[1].Select4 = lambda append, data: False
    with pytest.raises(SelectionError):
        references.highlight_entities(refs, owner="partial-failure")
    assert doc.selection == []
    assert doc.clear_calls == 0


def test_changed_face_cannot_commit_under_its_captured_reference(doc):
    reference = references.capture_selection()["entities"][0]["ref"]
    doc.faces[0].area = 400.0
    with pytest.raises(ReferenceNotFoundError, match="geometry changed"):
        features.create_reference_plane(entity_ref=reference, distance_mm=5, name="Selected face plane")
    assert doc.clear_calls == 0


# --- Pure token and fingerprint logic (no COM boundary) ---------------------

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

    class FakeDoc:
        pass

    original_doc_info = references.session.doc_info
    try:
        references.session.doc_info = lambda _doc: {
            "title": "Other.SLDPRT",
            "path": "",
            "type": "part",
        }
        with pytest.raises(ReferenceDocumentMismatchError):
            references._check_scope(FakeDoc(), payload)
    finally:
        references.session.doc_info = original_doc_info


def test_encoded_token_is_json_base64() -> None:
    token = make_token()
    decoded = json.loads(base64.urlsafe_b64decode(token))
    assert decoded["v"] == 1
