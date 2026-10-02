"""Public reference APIs against a fake external COM boundary, not live CAD."""
from types import SimpleNamespace

import pytest

from solidworks_mcp.com import binding
from solidworks_mcp.domain import references, session
from solidworks_mcp.domain import features
from solidworks_mcp.errors import (
    ComCallError, ReferenceAmbiguousError, ReferenceNotFoundError, SelectionError,
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
