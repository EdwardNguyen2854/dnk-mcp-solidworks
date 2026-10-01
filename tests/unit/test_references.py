"""Public reference APIs against a fake external COM boundary, not live CAD."""
from types import SimpleNamespace

import pytest

from solidworks_mcp.com import binding
from solidworks_mcp.domain import references, session
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


class Document:
    def __init__(self):
        self.faces = [Face(b"original")]
        self.selection = [self.faces[0]]
        self.selection_type = 2
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
        references.highlight_entities([reference])
    assert doc.selection == baseline
    assert doc.clear_calls == 0
