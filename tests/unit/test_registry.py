import pytest

from solidworks_mcp import registry
from solidworks_mcp.errors import InvalidParameterError
from solidworks_mcp.registry import array, boolean, integer, number, obj, string


@pytest.fixture
def tool_name():
    name = "unit_test_tool"
    yield name
    registry.REGISTRY.pop(name, None)


def make(name, schema, tier="core", handler=None):
    @registry.tool(name, "unit test tool", schema, tier=tier)
    def _handler(args):
        return {"echo": args}

    return registry.REGISTRY[name]


def test_registration_and_invoke(tool_name):
    make(
        tool_name,
        obj({"depth_mm": number("depth")}, required=("depth_mm",)),
    )
    assert registry.invoke(tool_name, {"depth_mm": 5}) == {"echo": {"depth_mm": 5}}


def test_duplicate_registration_rejected():
    make("unit_dup_tool", obj({}))
    with pytest.raises(ValueError):
        make("unit_dup_tool", obj({}))
    registry.REGISTRY.pop("unit_dup_tool")


def test_tier_filtering():
    make("unit_core_tool", obj({}), tier="core")
    make("unit_debug_tool", obj({}), tier="debug")
    core_names = {spec.name for spec in registry.visible_tools("core")}
    all_names = {spec.name for spec in registry.visible_tools("all")}
    assert "unit_core_tool" in core_names
    assert "unit_debug_tool" not in core_names
    assert "unit_debug_tool" in all_names
    registry.REGISTRY.pop("unit_core_tool")
    registry.REGISTRY.pop("unit_debug_tool")


def test_unknown_parameter_rejected(tool_name):
    make(tool_name, obj({"depth_mm": number("depth")}))
    with pytest.raises(InvalidParameterError) as info:
        registry.invoke(tool_name, {"depth_mm": 1, "width": 2})
    assert "width" in str(info.value)


def test_missing_required_rejected(tool_name):
    make(tool_name, obj({"depth_mm": number("depth")}, required=("depth_mm",)))
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {})


def test_type_and_range_checks(tool_name):
    make(
        tool_name,
        obj(
            {
                "depth_mm": number("depth", minimum=0.1),
                "sides": integer("sides", minimum=3),
                "mode": string("mode", enum=["a", "b"]),
                "flag": boolean("flag", default=True),
            }
        ),
    )
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"depth_mm": "ten"})
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"depth_mm": True})
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"depth_mm": 0.05})
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"sides": 2})
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"mode": "c"})
    result = registry.invoke(tool_name, {"depth_mm": 1.0, "sides": 6, "mode": "a"})
    assert result["echo"]["flag"] is True


def test_array_items_checked(tool_name):
    make(
        tool_name,
        obj({"indices": array("edges", {"type": "integer"})}),
    )
    with pytest.raises(InvalidParameterError):
        registry.invoke(tool_name, {"indices": ["one"]})
    assert registry.invoke(tool_name, {"indices": [1, 2]})["echo"]


def test_search_matches_name_and_description(tool_name):
    make(tool_name, obj({}), tier="extended")
    results = registry.search("unit_test")
    assert any(item["name"] == tool_name for item in results)
    assert registry.search("no_such_term_xyz") == []


def test_every_registered_tool_schema_is_well_formed():
    from solidworks_mcp.server import _import_tools

    _import_tools()
    for spec in registry.REGISTRY.values():
        schema = spec.input_schema
        assert schema.get("type") == "object", spec.name
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            assert required in properties, f"{spec.name}: required {required}"
        for name, prop in properties.items():
            assert "description" in prop, f"{spec.name}.{name} has no description"
            assert "type" in prop, f"{spec.name}.{name} has no type"
