import pytest

from solidworks_mcp.domain import drawings
from solidworks_mcp.errors import InvalidParameterError


def test_symmetric_plan_uses_one_magnitude():
    plan = drawings.plan_tolerance("symmetric", value_mm=0.1)

    assert plan["type_code"] == drawings.TOLERANCE_TYPES["symmetric"]
    assert plan["values"] == (0.1, 0.1)


def test_symmetric_plan_requires_a_positive_value():
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("symmetric")
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("symmetric", value_mm=0)


def test_bilateral_plan_signed_deviations():
    plan = drawings.plan_tolerance("bilateral", minus_mm=0.05, plus_mm=0.1)

    assert plan["values"] == (-0.05, 0.1)


def test_limits_plan_requires_ordered_bounds():
    plan = drawings.plan_tolerance("limits", lower_mm=99.9, upper_mm=100.2)

    assert plan["values"] == (99.9, 100.2)
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("limits", lower_mm=100.2, upper_mm=99.9)
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("limits", lower_mm=100.0)


def test_min_and_max_use_the_single_bound():
    plan = drawings.plan_tolerance("max", value_mm=100.1)

    assert plan["values"] == (100.1, 100.1)


def test_fit_family_needs_the_hole_fit_and_accepts_hole_only():
    plan = drawings.plan_tolerance("fit", hole_fit="H7")

    assert plan["fit"] == ("H7", "")
    plan = drawings.plan_tolerance("fit", hole_fit="H7", shaft_fit="g6")
    assert plan["fit"] == ("H7", "g6")
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("fit")


def test_fit_with_tolerance_combines_fit_and_deviations():
    plan = drawings.plan_tolerance(
        "fit_with_tolerance", hole_fit="H7", shaft_fit="g6", minus_mm=0.01, plus_mm=0.02
    )

    assert plan["fit"] == ("H7", "g6")
    assert plan["values"] == (-0.01, 0.02)


def test_none_and_basic_carry_no_values():
    assert "values" not in drawings.plan_tolerance("none")
    assert "values" not in drawings.plan_tolerance("basic")


def test_unknown_tolerance_is_rejected():
    with pytest.raises(InvalidParameterError):
        drawings.plan_tolerance("block")


def test_decimal_scale_reads_the_sheet_pair():
    assert drawings._decimal_scale([1.0, 2.0]) == 0.5
    assert drawings._decimal_scale([2.0, 1.0]) == 2.0
    assert drawings._decimal_scale(None) is None
    assert drawings._decimal_scale([0.0, 1.0]) is None
