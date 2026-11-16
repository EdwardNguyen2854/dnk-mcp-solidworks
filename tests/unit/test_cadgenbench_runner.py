import json

import pytest

from scripts.cadgenbench_runner import load_cases


def test_load_cases_accepts_prepared_tool_calls(tmp_path):
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [{"id": "sample-001", "calls": [
        {"tool": "boss_extrude", "args": {"depth_mm": 10}},
    ]}]}), encoding="utf-8")

    assert load_cases(manifest)[0]["id"] == "sample-001"


@pytest.mark.parametrize("case_id", ["../escape", "", "two/levels"])
def test_load_cases_rejects_unsafe_case_ids(tmp_path, case_id):
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [{"id": case_id, "calls": []}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid or duplicate"):
        load_cases(manifest)


def test_load_cases_rejects_runner_controlled_tools(tmp_path):
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [{"id": "sample-001", "calls": [
        {"tool": "export_document", "args": {"path": "elsewhere.step"}},
    ]}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="managed by the runner"):
        load_cases(manifest)
