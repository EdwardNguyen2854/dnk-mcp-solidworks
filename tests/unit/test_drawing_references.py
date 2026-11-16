from types import SimpleNamespace

import pytest

from solidworks_mcp.domain import drawings
from solidworks_mcp.errors import InvalidParameterError, SelectionError


class Model:
    def __init__(self, path, title, configurations, model_type=1):
        self.GetPathName = path
        self.GetTitle = title
        self._configurations = {
            name: SimpleNamespace(Name=name) for name in configurations
        }
        self._model_type = model_type

    def GetType(self):
        return self._model_type

    def GetConfigurationByName(self, name):
        return self._configurations.get(name)


class Application:
    def __init__(self, documents):
        self._documents = documents

    def GetDocuments(self):
        return self._documents


def test_drawing_view_reference_resolves_exact_model_among_open_documents(monkeypatch):
    first = Model(r"C:\parts\fixture_a.sldprt", "fixture_a", ["Default"])
    second = Model(r"C:\parts\fixture_b.sldprt", "fixture_b", ["Default", "Machined"])
    monkeypatch.setattr(drawings.session, "wrap_doc", lambda value: value)
    monkeypatch.setattr(drawings.binding, "wrap", lambda value, _interface: value)

    result = drawings._model_reference_record(
        Application([first, second]), r"c:/parts/fixture_b.sldprt", "Machined"
    )

    assert result["document"] is second
    assert result["reference"] == second.GetPathName
    assert result["configuration"] == "Machined"
    assert first is not result["document"]


def test_drawing_view_reference_rejects_duplicate_open_titles(monkeypatch):
    documents = [
        Model(r"C:\a\duplicate.sldprt", "duplicate", ["Default"]),
        Model(r"C:\b\duplicate.sldprt", "duplicate", ["Default"]),
    ]
    monkeypatch.setattr(drawings.session, "wrap_doc", lambda value: value)

    with pytest.raises(SelectionError, match="exactly one"):
        drawings._model_reference_record(Application(documents), "duplicate", "Default")


def test_drawing_view_reference_requires_existing_configuration(monkeypatch):
    model = Model(r"C:\parts\fixture.sldprt", "fixture", ["Default"])
    monkeypatch.setattr(drawings.session, "wrap_doc", lambda value: value)
    monkeypatch.setattr(drawings.binding, "wrap", lambda value, _interface: value)

    with pytest.raises(SelectionError, match="does not exist"):
        drawings._model_reference_record(
            Application([model]), model.GetPathName, "Missing"
        )


def test_drawing_view_reference_inputs_are_required():
    with pytest.raises(InvalidParameterError, match="model_reference is required"):
        drawings._model_reference_record(Application([]), " ", "Default")
    with pytest.raises(InvalidParameterError, match="configuration is required"):
        drawings._model_reference_record(Application([]), "part.sldprt", " ")


def test_display_mode_values_use_sw_display_mode_enum():
    assert drawings.DISPLAY_MODES == {
        "wireframe": 0,
        "hidden_lines_grayed": 1,
        "hidden_lines_removed": 2,
        "shaded": 3,
        "faceted_wireframe": 4,
        "faceted_hidden_lines_grayed": 5,
        "faceted_hidden_lines_removed": 6,
        "shaded_with_edges": 7,
        "default": 8,
    }
    assert drawings.DISPLAY_MODE_NAMES[1] == "hidden_lines_grayed"
