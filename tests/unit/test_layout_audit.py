from solidworks_mcp.domain import drawing_audit as audit


def annotation(kind, position, **extra):
    base = {"type": kind, "index": 0, "position_mm": position}
    base.update(extra)
    return base


def test_datum_tag_size_is_a_small_box():
    width, height = audit.estimate_size_mm(
        annotation("datum_tag", [100, 100], label="A"), 3.5
    )

    assert width == height == 5.5


def test_note_size_uses_lines_and_longest_line():
    note = annotation("note", [50, 50], text="LINE ONE\nLONGER LINE TWO")

    width, height = audit.estimate_size_mm(note, 3.5)

    assert height == 2 * 3.5 * 1.5
    assert round(width, 6) == round(15 * 3.5 * 0.62, 6)


def test_dimension_size_uses_the_reading():
    dimension = annotation("dimension", [50, 50], reading="2X 10.00 THRU")

    width, height = audit.estimate_size_mm(dimension, 3.5)

    assert round(width, 6) == round(13 * 3.5 * 0.62, 6)
    assert round(height, 6) == round(3.5 * 1.6, 6)


def test_geometric_tolerance_size_uses_the_frame_values():
    frame = annotation(
        "geometric_tolerance",
        [50, 50],
        frame_values=["0.2", "", "A", "B", "C"],
    )

    width, height = audit.estimate_size_mm(frame, 3.5)

    assert width > 12.0
    assert height == 7.0


def test_rect_overlap_and_gap():
    first = (0.0, 0.0, 10.0, 10.0)
    second = (5.0, 5.0, 15.0, 15.0)
    third = (13.0, 0.0, 20.0, 10.0)

    assert audit.rect_overlap_area(first, second) == 25.0
    assert audit.rect_gap(first, second) == 0.0
    assert audit.rect_overlap_area(first, third) == 0.0
    assert audit.rect_gap(first, third) == 3.0


def test_audit_flags_the_overlapping_datum_tags():
    views = [
        {
            "name": "Drawing View1",
            "annotations": [
                annotation("datum_tag", [155.95, 117.22], label="A"),
                annotation("datum_tag", [151.66, 117.22], label="C"),
            ],
        }
    ]

    result = audit.audit_annotations(views, [420.0, 297.0])

    assert result["counts"]["collisions"] == 1
    assert result["collisions"][0]["kind"] == "overlap"


def test_audit_flags_near_misses_within_the_gap():
    views = [
        {
            "name": "Drawing View1",
            "annotations": [
                annotation("datum_tag", [100.0, 100.0], label="A"),
                annotation("datum_tag", [107.0, 100.0], label="B"),
            ],
        }
    ]

    result = audit.audit_annotations(views, [420.0, 297.0], min_gap_mm=2.0)

    assert result["counts"]["collisions"] == 1
    assert result["collisions"][0]["kind"] == "near"
    assert result["collisions"][0]["gap_mm"] == 1.5


def test_audit_flags_off_frame_items():
    views = [
        {
            "name": "Sheet1",
            "annotations": [annotation("note", [5.0, 150.0], text="HI")],
        }
    ]

    result = audit.audit_annotations(views, [420.0, 297.0], edge_band_mm=0.0)

    assert result["counts"]["off_frame"] == 1
    assert result["off_frame"][0]["sides"] == ["left"]


def test_audit_skips_margin_decoration_by_default():
    views = [
        {"name": "Sheet1", "annotations": [annotation("note", [30.0, 8.0], text="8")]},
    ]

    result = audit.audit_annotations(views, [420.0, 297.0])

    assert result["counts"]["items"] == 0
    assert result["counts"]["skipped"]["frame_decoration"] == 1


def test_audit_skips_the_title_block_region():
    views = [
        {
            "name": "Sheet1",
            "annotations": [annotation("note", [300.0, 40.0], text="MATERIAL:")],
        }
    ]

    result = audit.audit_annotations(
        views, [420.0, 297.0], title_block_region_mm=[240.0, 5.0, 410.0, 70.0]
    )

    assert result["counts"]["items"] == 0
    assert result["counts"]["skipped"]["title_block"] == 1


def test_title_block_region_wraps_linked_notes():
    listed = {
        "views": [
            {
                "name": "Sheet1",
                "annotations": [
                    {
                        "type": "note",
                        "position_mm": [300.0, 20.0],
                        "property_linked_text": '$PRP:"DrawnBy"',
                    },
                    {
                        "type": "note",
                        "position_mm": [400.0, 60.0],
                        "property_linked_text": '$PRP:"Revision"',
                    },
                    {"type": "note", "position_mm": [30.0, 255.0], "text": "NOTE"},
                ],
            }
        ]
    }

    region = audit.title_block_region(listed)

    margin = audit.TITLE_BLOCK_MARGIN_MM
    assert region == [
        300.0 - margin,
        20.0 - margin,
        400.0 + margin,
        60.0 + margin,
    ]


def test_audit_ignores_non_text_annotations():
    views = [
        {
            "name": "Drawing View1",
            "annotations": [
                annotation("center_mark", [100.0, 100.0]),
                annotation("table", [100.0, 100.0]),
            ],
        }
    ]

    result = audit.audit_annotations(views, [420.0, 297.0])

    assert result["counts"]["items"] == 0
    assert result["counts"]["collisions"] == 0
