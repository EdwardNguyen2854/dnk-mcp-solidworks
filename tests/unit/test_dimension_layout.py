from solidworks_mcp.domain import drawings


def dim(x_mm: float, y_mm: float, axis: str = "horizontal") -> dict:
    return {"position": (x_mm / 1000.0, y_mm / 1000.0), "axis": axis}


def test_below_rows_enforce_spacing_and_keep_original_order():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, -5), dim(50, -6), dim(50, -7)],
        spacing_m=0.009,
        margin_m=0.008,
    )
    assert [round(item["position"][1] * 1000, 3) for item in plan] == [-8.0, -17.0, -26.0]
    assert [item["row"] for item in plan] == [0, 1, 2]
    assert all(abs(item["position"][0] - 0.050) < 1e-9 for item in plan)


def test_vertical_rows_keep_their_y_and_stagger_left():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(-4, 30, "vertical"), dim(-6, 20, "vertical")],
        spacing_m=0.009,
        margin_m=0.008,
    )
    assert [round(item["position"][0] * 1000, 3) for item in plan] == [-8.0, -17.0]
    assert [round(item["position"][1] * 1000, 3) for item in plan] == [30.0, 20.0]
    assert all(item["side"] == "left" for item in plan)


def test_dimensions_keep_the_side_they_were_on():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, 70), dim(50, -5)],
        spacing_m=0.009,
        margin_m=0.008,
    )
    sides = {item["side"] for item in plan}
    assert sides == {"above", "below"}
    above = next(item for item in plan if item["side"] == "above")
    below = next(item for item in plan if item["side"] == "below")
    assert round(above["position"][1] * 1000, 3) == 68.0
    assert round(below["position"][1] * 1000, 3) == -8.0


def test_dimensions_inside_the_view_are_pushed_to_the_nearer_side():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, 10), dim(50, 50)],
        spacing_m=0.009,
        margin_m=0.008,
    )
    assert plan[0]["side"] == "below"
    assert round(plan[0]["position"][1] * 1000, 3) == -8.0
    assert plan[1]["side"] == "above"
    assert round(plan[1]["position"][1] * 1000, 3) == 68.0


def test_plan_entries_stay_in_input_order():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, -5), dim(-4, 30, "vertical"), dim(50, -9), dim(104, 30, "vertical")],
        spacing_m=0.009,
        margin_m=0.008,
    )
    assert [item["index"] for item in plan] == [0, 1, 2, 3]


def test_group_flips_to_the_opposite_side_when_blocked():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, -5), dim(50, -6), dim(50, -7)],
        spacing_m=0.009,
        margin_m=0.008,
        limits_m={"below": 0.020, "above": 0.100, "left": 0.050, "right": 0.050},
        min_spacing_m=0.0065,
    )
    assert all(item["side"] == "above" for item in plan)
    assert all(item["original_side"] == "below" for item in plan)
    assert [round(item["position"][1] * 1000, 3) for item in plan] == [68.0, 77.0, 86.0]
    assert all(item["spacing_m"] == 0.009 for item in plan)


def test_group_compresses_when_neither_side_has_room():
    outline = [0.0, 0.0, 0.100, 0.060]
    plan = drawings.plan_dimension_arrangement(
        outline,
        [dim(50, -5), dim(50, -6), dim(50, -7)],
        spacing_m=0.009,
        margin_m=0.008,
        limits_m={"below": 0.020, "above": 0.020, "left": 0.050, "right": 0.050},
        min_spacing_m=0.0065,
    )
    assert all(item["side"] == "below" for item in plan)
    assert [round(item["position"][1] * 1000, 3) for item in plan] == [-8.0, -14.5, -21.0]
    assert all(abs(item["spacing_m"] - 0.0065) < 1e-9 for item in plan)
