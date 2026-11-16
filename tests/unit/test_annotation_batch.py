from types import SimpleNamespace

import pytest

from solidworks_mcp.domain import drawings
from solidworks_mcp.errors import VerificationError


class Note:
    def __init__(self, text):
        self.text = text
        self.format = SimpleNamespace(CharHeight=0.0035)

    def GetText(self):
        return self.text

    def SetText(self, value):
        if value != "refused":
            self.text = value

    def GetTextFormat(self):
        return self.format

    def SetTextFormat(self, index, value):
        self.format = value


class Annotation:
    def __init__(self, text):
        self.note = Note(text)
        self.position = [0.1, 0.2, 0]

    def GetSpecificAnnotation(self):
        return self.note

    def GetPosition(self):
        return self.position

    def SetPosition(self, x, y, z):
        self.position = [x, y, z]


def prepare(monkeypatch):
    annotations = [Annotation("first"), Annotation("second")]
    rebuilds = []
    monkeypatch.setattr(drawings.binding, "wrap", lambda obj, interface: obj)
    monkeypatch.setattr(drawings.session, "active_doc", lambda kinds: (None, object(), "drawing"))
    monkeypatch.setattr(drawings.session, "clear_selection", lambda doc: None)
    monkeypatch.setattr(drawings, "_current_sheet", lambda doc: object())
    monkeypatch.setattr(drawings, "_sheet_name", lambda sheet: "Sheet1")
    monkeypatch.setattr(drawings, "_named_view", lambda doc, name: object())
    monkeypatch.setattr(drawings, "_annotation_at", lambda view, index: annotations[index])

    def inventory(**kwargs):
        return {"views": [{"name": "Sheet1", "annotations": [
            {"id": f"{i}-{ann.note.text}", "index": i, "type": "note",
             "text": ann.note.text}
            for i, ann in enumerate(annotations)
        ]}]}

    def rebuild(doc):
        rebuilds.append(True)
        return {"ok": True, "whats_wrong": {"count": 0}}

    monkeypatch.setattr(drawings, "list_annotations", inventory)
    monkeypatch.setattr(drawings.inspect, "rebuild", rebuild)
    return annotations, rebuilds


def test_batch_restores_earlier_note_when_later_edit_is_refused(monkeypatch):
    annotations, rebuilds = prepare(monkeypatch)
    with pytest.raises(VerificationError) as failure:
        drawings.update_annotations([
            {"id": "0-first", "text": "changed", "position_mm": [210, 220]},
            {"id": "1-second", "text": "refused"},
        ])
    assert failure.value.details["rolled_back"] is True
    assert [ann.note.text for ann in annotations] == ["first", "second"]
    assert annotations[0].position == [0.1, 0.2, 0]
    assert len(rebuilds) == 1


def test_batch_returns_fresh_ids_and_only_changed_annotation_evidence(monkeypatch):
    annotations, rebuilds = prepare(monkeypatch)
    result = drawings.update_annotations([{"id": "0-first", "text": "changed"}])
    assert result["data"]["annotations"][0]["id"] == "0-changed"
    assert result["data"]["annotations"][0]["previous_id"] == "0-first"
    assert len(result["evidence"]["annotations"]) == 1
    assert annotations[1].note.text == "second"
    assert len(rebuilds) == 1
