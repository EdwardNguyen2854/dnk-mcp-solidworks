from solidworks_mcp.domain.drawings import audit_feature_coverage


def test_feature_coverage_reports_missing_stale_and_duplicate_dimensions():
    dimensions = [
        {"name": "Front", "dimensions": [{"id": "dim-a"}, {"id": "dim-b"}]}
    ]
    result = audit_feature_coverage(
        {"HolePattern", "MountingSlot"},
        dimensions,
        [
            {"feature_ref": "HolePattern", "dimension_ids": ["dim-a"]},
            {"feature_ref": "MountingSlot", "dimension_ids": ["dim-a", "stale"]},
        ],
    )

    assert result["passed"] is False
    assert result["missing_required_features"] == []
    assert result["duplicate_dimension_assignments"] == [
        {"dimension_id": "dim-a", "feature_refs": ["HolePattern", "MountingSlot"]}
    ]
    assert result["unknown_dimension_ids"] == [
        {"feature_ref": "MountingSlot", "dimension_id": "stale"}
    ]
    assert result["unassigned_dimension_ids"] == ["dim-b"]


def test_required_feature_without_a_dimension_is_missing_regardless_of_geometry_counts():
    result = audit_feature_coverage(
        {"CriticalFeature"},
        [{"name": "Front", "dimensions": [{"id": "unrelated-dimension"}]}],
        [{"feature_ref": "CriticalFeature", "dimension_ids": []}],
    )

    assert result["passed"] is False
    assert result["edge_count_used_as_feature_quantity"] is False
    assert result["missing_required_features"] == ["CriticalFeature"]


def test_duplicate_feature_refs_and_unknown_feature_names_are_reported():
    result = audit_feature_coverage(
        {"KnownFeature"},
        [{"name": "Front", "dimensions": [{"id": "dim-a"}]}],
        [
            {"feature_ref": "KnownFeature", "dimension_ids": ["dim-a"]},
            {"feature_ref": "KnownFeature", "dimension_ids": ["dim-a"]},
            {"feature_ref": "Typo", "dimension_ids": []},
        ],
    )

    assert result["duplicate_feature_refs"] == ["KnownFeature"]
    assert result["unknown_feature_refs"] == ["Typo"]


def test_optional_feature_may_be_uncovered():
    result = audit_feature_coverage(
        {"ReferenceFeature"},
        [],
        [{"feature_ref": "ReferenceFeature", "dimension_ids": [], "required": False}],
    )

    assert result["passed"] is True
    assert result["missing_required_features"] == []
