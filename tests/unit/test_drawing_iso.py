from solidworks_mcp.domain import drawing_iso


def manifest(**overrides):
    result = {
        "document": {"type": "drawing"},
        "sheet": {
            "paper_size": "A3",
            "format": "Sheet Format1",
            "template_code": 8,
            "scale": [1.0, 1.0],
            "first_angle": True,
            "size_mm": [420.0, 297.0],
            "title_block": {
                "verified": True,
                "matched_properties": {
                    "Title": True,
                    "DrawingNumber": True,
                    "Revision": True,
                },
            },
        },
        "units": {"metric": True, "length_unit": 0},
        "views": [
            {
                "name": "Front",
                "type": "standard",
                "orientation": "front",
                "position_mm": [120.0, 160.0],
                "outline_mm": {"min": [80.0, 130.0], "max": [160.0, 180.0]},
            },
            {
                "name": "Top",
                "type": "standard",
                "orientation": "top",
                "position_mm": [120.0, 90.0],
                "outline_mm": {"min": [80.0, 70.0], "max": [160.0, 110.0]},
            },
            {
                "name": "Right",
                "type": "standard",
                "orientation": "right",
                "position_mm": [50.0, 160.0],
                "outline_mm": {"min": [20.0, 130.0], "max": [70.0, 180.0]},
            },
        ],
        "annotations": {
            "views": [
                {
                    "name": "Front",
                    "annotations": [
                        {
                            "type": "dimension",
                            "visible": True,
                            "text": "100",
                        }
                    ],
                }
            ]
        },
        "properties": {
            "Title": "ISO TEST PART",
            "DrawingNumber": "DRW-001",
            "Revision": "A",
        },
        "rebuild": {"ok": True, "whats_wrong": {"count": 0}},
    }
    result.update(overrides)
    return result


def test_valid_iso_manifest_passes_release_checks():
    result = drawing_iso.validate_iso_manifest(manifest(), minimum_model_views=2)

    assert result["valid"] is True
    assert all(result["checks"].values())
    assert result["annotation_counts"] == {"dimension": 1}


def test_validator_reports_missing_release_content():
    result = drawing_iso.validate_iso_manifest(
        manifest(
            properties={"Title": "ISO TEST PART"},
            annotations={"views": []},
            views=manifest()["views"][:2],
        ),
        minimum_model_views=3,
    )

    codes = {issue["code"] for issue in result["errors"]}
    assert result["valid"] is False
    assert {"too_few_model_views", "missing_dimensions", "missing_properties"} <= codes


def test_validator_rejects_overlapping_views_and_out_of_bounds_views():
    result = drawing_iso.validate_iso_manifest(
        manifest(
            views=[
                {
                    "name": "Front",
                    "type": "standard",
                    "outline_mm": {"min": [5.0, 5.0], "max": [120.0, 120.0]},
                },
                {
                    "name": "Right",
                    "type": "standard",
                    "outline_mm": {"min": [100.0, 100.0], "max": [430.0, 200.0]},
                },
            ]
        ),
        require_dimensions=False,
    )

    codes = {issue["code"] for issue in result["errors"]}
    assert "view_overlap" in codes
    assert "view_outside_usable_sheet" in codes


def test_preflight_can_skip_release_only_requirements():
    result = drawing_iso.validate_iso_manifest(
        manifest(properties={}, annotations={"views": []}),
        required_properties=[],
        require_dimensions=False,
        allow_view_overlap=True,
    )

    assert result["valid"] is True
    assert result["checks"]["required_properties"] is True
    assert result["checks"]["dimensions"] is True


def test_validator_rejects_missing_sheet_size_instead_of_skipping_bounds_check():
    result = drawing_iso.validate_iso_manifest(
        manifest(sheet={"paper_size": "A3", "format": "Sheet Format1"}),
        required_properties=[],
        require_dimensions=False,
    )

    assert result["valid"] is False
    assert "invalid_sheet_size" in {issue["code"] for issue in result["errors"]}


def test_validator_rejects_non_metric_units_and_non_iso_frame():
    result = drawing_iso.validate_iso_manifest(
        manifest(
            units={"metric": False, "length_unit": 3},
            sheet={
                "paper_size": "A3",
                "format": "custom.slddrt",
                "template_code": 12,
                "scale": [1.0, 1.0],
                "first_angle": True,
                "size_mm": [420.0, 297.0],
                "title_block": {"verified": True},
            },
        ),
        minimum_model_views=3,
    )

    codes = {issue["code"] for issue in result["errors"]}
    assert {"non_metric_units", "non_iso_sheet_frame"} <= codes


def test_title_block_display_can_be_explicitly_optional():
    result = drawing_iso.validate_iso_manifest(
        manifest(sheet={"paper_size": "A3", "format": "Sheet Format1", "template_code": 8,
                        "scale": [1.0, 1.0], "first_angle": True,
                        "size_mm": [420.0, 297.0]}),
        minimum_model_views=3,
        require_title_block_display=False,
    )

    assert result["valid"] is True
    assert result["checks"]["title_block_display"] is True
