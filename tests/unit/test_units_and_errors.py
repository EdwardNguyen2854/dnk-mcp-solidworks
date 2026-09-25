import math

import pytest

from solidworks_mcp.com import units
from solidworks_mcp.errors import (
    ComCallError,
    InvalidParameterError,
    PathNotAllowedError,
    SwMcpError,
    fail,
    ok,
    translate_com_error,
)


def test_mm_m_roundtrip():
    assert units.mm_to_m(1000.0) == 1.0
    assert units.m_to_mm(0.025) == 25.0
    assert units.m3_to_mm3(3e-5) == pytest.approx(30000.0)
    assert units.m2_to_mm2(0.01) == pytest.approx(10000.0)


def test_degrees_radians_roundtrip():
    assert units.deg_to_rad(180.0) == pytest.approx(math.pi)
    assert units.rad_to_deg(math.pi / 2) == pytest.approx(90.0)


def test_point_to_mm():
    assert units.point_to_mm((0.001, 0.002, 0.003)) == [1.0, 2.0, 3.0]


def test_error_to_dict():
    error = InvalidParameterError("bad input", hint="try again", available=[1, 2])
    payload = error.to_dict()
    assert payload["code"] == "INVALID_PARAMETER"
    assert payload["recoverable"] is False
    assert payload["hint"] == "try again"
    assert payload["details"] == {"available": [1, 2]}


def test_envelope_helpers():
    assert ok() == {"ok": True}
    assert ok({"a": 1}, evidence={"v": 2})["evidence"] == {"v": 2}
    envelope = fail(SwMcpError("boom"))
    assert envelope["ok"] is False
    assert envelope["error"]["message"] == "boom"


def test_translate_com_error():
    exc = Exception("rpc failure")
    exc.args = (-2147023170, "The remote procedure call failed.", None, None)
    translated = translate_com_error(exc, "tool x")
    assert isinstance(translated, ComCallError)
    assert translated.details["hresult"] == -2147023170


def test_path_error_is_typed():
    assert issubclass(PathNotAllowedError, SwMcpError)
