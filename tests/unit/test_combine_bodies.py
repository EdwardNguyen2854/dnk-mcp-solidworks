from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from solidworks_mcp.domain import features
from solidworks_mcp.errors import FeatureBuildError, InvalidParameterError, SelectionError


class Body:
    def __init__(self, body_type=0):
        self.GetType = Mock(return_value=body_type)
        self.Select2 = Mock(return_value=True)


class Feature:
    def __init__(self, modify=True):
        self.Name = "Combine1"
        self.GetTypeName2 = Mock(return_value="CombineBodies")
        self.GetDefinition = Mock(return_value=SimpleNamespace(OperationType=1))
        self.ModifyDefinition = Mock(return_value=modify)


def setup_combine(monkeypatch, *, count=1, modify=True):
    doc = object()
    bodies = [Body(), Body()]
    tree = {"Base", "Boss-Extrude1"}
    feature = Feature(modify=modify)
    original_fp = {
        "features": sorted(tree),
        "mass": {"volume_mm3": 2200, "area_mm2": 1, "mass_g": 1},
        "bounds": {"min_mm": [0, 0, 0], "max_mm": [1, 1, 1]},
        "topology": [(6, 12), (6, 12)],
    }
    part = SimpleNamespace(InsertCombineFeature=Mock(return_value=False))

    monkeypatch.setattr(features.session, "active_doc", lambda kinds: (None, doc, None))
    monkeypatch.setattr(features.inspect, "_bodies", lambda d, body_type="all": bodies if body_type == "all" else [Body()] * count)
    monkeypatch.setattr(features, "feature_names", lambda d: set(tree))
    monkeypatch.setattr(features, "_model_fingerprint", lambda d: original_fp)
    monkeypatch.setattr(features, "_same_fingerprint", lambda before, after: True)
    monkeypatch.setattr(features.session, "clear_selection", Mock())
    monkeypatch.setattr(features.inspect, "create_select_data", Mock(return_value=object()))
    monkeypatch.setattr(features.binding, "wrap", lambda obj, interface: part if interface == "IPartDoc" else obj)
    monkeypatch.setattr(features, "_combine_dispatch_array", lambda body: [body])
    monkeypatch.setattr(features.session, "iter_features", lambda d: iter([feature]))
    monkeypatch.setattr(features.inspect, "rebuild", lambda d: {"ok": True, "whats_wrong": {"count": 0}})
    monkeypatch.setattr(features.inspect, "mass_properties", lambda d: {"volume_mm3": 800, "mass_g": 1})
    monkeypatch.setattr(features, "_rollback_features", Mock())

    def insert(*args):
        tree.add("Combine1")
        return False

    part.InsertCombineFeature.side_effect = insert
    return doc, bodies, feature, part, tree


@pytest.mark.parametrize(("operation", "expected"), [("subtract", None), ("add", 0), ("common", 2)])
def test_combine_operations_use_subtract_seed_and_feature_data_enum(monkeypatch, operation, expected):
    doc, bodies, feature, part, tree = setup_combine(monkeypatch)
    result = features.combine_bodies(operation, 0, 1)
    part.InsertCombineFeature.assert_called_once_with(15902, bodies[0], [bodies[1]])
    if expected is None:
        assert not getattr(feature, "ModifyDefinition", Mock()).called
    else:
        assert feature.ModifyDefinition.call_count == 1
        definition = feature.ModifyDefinition.call_args.args[0]
        assert definition.OperationType == expected
    assert result["evidence"]["body_count"] == 1
    assert result["evidence"]["mass_properties"]["volume_mm3"] == 800
    assert result["evidence"]["whats_wrong"]["count"] == 0
    assert result["evidence"]["insert_result"] is False


@pytest.mark.parametrize("operation,main,tool", [("wat", 0, 1), ("add", -1, 1), ("add", 0, 0), ("add", True, 1)])
def test_invalid_operation_and_indices_fail_before_com(monkeypatch, operation, main, tool):
    monkeypatch.setattr(features.session, "active_doc", Mock(side_effect=AssertionError("COM touched")))
    with pytest.raises(InvalidParameterError):
        features.combine_bodies(operation, main, tool)


def test_out_of_range_and_non_solid_indices_rejected(monkeypatch):
    doc = object()
    monkeypatch.setattr(features.session, "active_doc", lambda kinds: (None, doc, None))
    monkeypatch.setattr(features.inspect, "_bodies", lambda d: [Body()])
    with pytest.raises(SelectionError):
        features.combine_bodies("subtract", 0, 1)
    monkeypatch.setattr(features.inspect, "_bodies", lambda d: [Body(), Body(body_type=1)])
    with pytest.raises(InvalidParameterError):
        features.combine_bodies("subtract", 0, 1)


def test_postcondition_failure_rolls_back_when_two_bodies_remain(monkeypatch):
    doc, bodies, feature, part, tree = setup_combine(monkeypatch, count=2)
    monkeypatch.setattr(features.inspect, "_bodies", lambda d, body_type="all": bodies)

    def rollback(d, original):
        tree.discard("Combine1")

    rollback_mock = Mock(side_effect=rollback)
    monkeypatch.setattr(features, "_rollback_features", rollback_mock)
    with pytest.raises(FeatureBuildError, match="model was restored"):
        features.combine_bodies("subtract", 0, 1)
    rollback_mock.assert_called_once_with(doc, {"Base", "Boss-Extrude1"})


def test_modify_failure_rolls_back_partial_feature(monkeypatch):
    doc, bodies, feature, part, tree = setup_combine(monkeypatch, modify=False)
    rollback = Mock(side_effect=lambda d, original: tree.discard("Combine1"))
    monkeypatch.setattr(features, "_rollback_features", rollback)
    with pytest.raises(FeatureBuildError, match="model was restored"):
        features.combine_bodies("add", 0, 1)
    rollback.assert_called_once_with(doc, {"Base", "Boss-Extrude1"})


def test_failed_rollback_reports_residual_model(monkeypatch):
    doc, bodies, feature, part, tree = setup_combine(monkeypatch, modify=False)
    monkeypatch.setattr(features, "_rollback_features", Mock(side_effect=RuntimeError("delete refused")))
    monkeypatch.setattr(features, "_same_fingerprint", lambda before, after: False)
    with pytest.raises(FeatureBuildError, match="rollback could not be verified") as error:
        features.combine_bodies("add", 0, 1)
    assert error.value.details["rolled_back"] is False
    assert error.value.details["rollback_error"]
