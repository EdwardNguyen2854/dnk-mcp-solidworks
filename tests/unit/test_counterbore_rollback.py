import pytest

from solidworks_mcp.domain import features, inspect
from solidworks_mcp.errors import FeatureBuildError


class FakePart:
    def __init__(self):
        self.features = set()
        self.residual_volume_delta = 0.0


def install_counterbore_fakes(monkeypatch, *, leave_residual=False):
    doc = FakePart()
    face = object()
    rollback_calls = []
    cut_calls = 0

    monkeypatch.setattr(features.session, "active_doc", lambda _types: (None, doc, "part"))
    monkeypatch.setattr(features, "feature_names", lambda _doc: set(doc.features))
    monkeypatch.setattr(features, "_resolve_hole_face", lambda *_args: (face, [0.0, 0.0, 0.0]))
    monkeypatch.setattr(features, "_planar_face_signature", lambda _face: {"plane": 1})
    monkeypatch.setattr(features, "_refresh_hole_face", lambda *_args: face)
    monkeypatch.setattr(features, "_newest_feature_name", lambda _doc, _before: "PilotCut")
    monkeypatch.setattr(
        features.inspect,
        "rebuild",
        lambda _doc: {"ok": True, "whats_wrong": {"count": 0}},
    )

    def fingerprint(_doc):
        volume = 1000.0 - 10.0 * len(doc.features) - doc.residual_volume_delta
        return {
            "features": set(doc.features),
            "mass": {"volume_mm3": volume, "area_mm2": 500.0, "mass_g": volume},
            "bounds": {"min_mm": [0.0, 0.0, 0.0], "max_mm": [10.0, 10.0, 10.0]},
            "topology": [(6, 12)] if not doc.features else [(7, 14)],
        }

    def create_cut(_doc, _face, _point, _diameter, _code, _depth, _reverse=False):
        nonlocal cut_calls
        cut_calls += 1
        if cut_calls == 1:
            doc.features.add("PilotCut")
            if leave_residual:
                doc.residual_volume_delta = 0.25
            return object()
        raise FeatureBuildError("counterbore cut rejected")

    def rollback(_doc, original_names):
        rollback_calls.append(set(original_names))
        doc.features = set(original_names)

    monkeypatch.setattr(features, "_model_fingerprint", fingerprint)
    monkeypatch.setattr(features, "_simple_hole_feature", create_cut)
    monkeypatch.setattr(features, "_rollback_features", rollback)
    return doc, rollback_calls


def run_counterbore():
    return features.counterbore_hole(
        diameter_mm=5.0,
        counterbore_diameter_mm=8.0,
        counterbore_depth_mm=2.0,
        face_index=0,
        x_mm=5.0,
        y_mm=5.0,
        depth_mm=10.0,
        end_condition="blind",
    )


def test_counterbore_rolls_back_pilot_and_verifies_fingerprint(monkeypatch):
    doc, rollback_calls = install_counterbore_fakes(monkeypatch)

    with pytest.raises(FeatureBuildError, match="partial cuts were rolled back") as error:
        run_counterbore()

    assert doc.features == set()
    assert rollback_calls == [set()]
    assert error.value.details["rolled_back"] is True
    assert error.value.details["model_unchanged"] is True


def test_counterbore_rejects_rollback_with_residual_geometry_change(monkeypatch):
    doc, _rollback_calls = install_counterbore_fakes(monkeypatch, leave_residual=True)

    with pytest.raises(FeatureBuildError, match="model changed after rollback") as error:
        run_counterbore()

    assert doc.features == set()
    assert error.value.details["failure"] == "counterbore cut rejected"
