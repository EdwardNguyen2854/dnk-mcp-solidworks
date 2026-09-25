"""Tool registry: typed schemas, tier gating, and argument validation.

Tool handlers are plain synchronous functions that receive a validated
argument dict and return the result envelope. COM access happens inside
handlers via :func:`solidworks_mcp.com.worker.run`, so handlers can be called
from any thread.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import InvalidParameterError

TIER_ORDER = {"core": 0, "extended": 1, "advanced": 2, "debug": 3}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    tier: str = "core"
    tags: tuple[str, ...] = field(default_factory=tuple)


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    *,
    tier: str = "core",
    tags: tuple[str, ...] = (),
):
    def decorator(handler: Callable[[dict[str, Any]], dict[str, Any]]):
        if name in REGISTRY:
            raise ValueError(f"duplicate tool name: {name}")
        if tier not in TIER_ORDER:
            raise ValueError(f"invalid tier {tier!r} for tool {name}")
        REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema or obj({}),
            handler=handler,
            tier=tier,
            tags=tuple(tags),
        )
        return handler

    return decorator


def visible_tools(tier: str) -> list[ToolSpec]:
    if tier == "all":
        return sorted(REGISTRY.values(), key=lambda spec: spec.name)
    limit = TIER_ORDER.get(tier)
    if limit is None:
        raise InvalidParameterError(f"unknown tool tier: {tier}")
    return sorted(
        (spec for spec in REGISTRY.values() if TIER_ORDER[spec.tier] <= limit),
        key=lambda spec: spec.name,
    )


def invoke(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    spec = REGISTRY.get(name)
    if spec is None:
        raise InvalidParameterError(
            f"unknown tool: {name}",
            hint="Call tools/list for the tool names enabled at this tier.",
        )
    validated = validate(spec, args)
    return spec.handler(validated)


def search(query: str) -> list[dict[str, str]]:
    terms = [term for term in query.lower().split() if term]
    results = []
    for spec in sorted(REGISTRY.values(), key=lambda item: item.name):
        haystack = " ".join(
            (spec.name, spec.description, " ".join(spec.tags))
        ).lower()
        if all(term in haystack for term in terms):
            results.append(
                {"name": spec.name, "tier": spec.tier, "description": spec.description}
            )
    return results


_SCALAR_TYPES: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "string": (str,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def _check_value(name: str, schema: dict[str, Any], value: Any) -> None:
    expected = schema.get("type")
    if expected == "number" and isinstance(value, bool):
        raise InvalidParameterError(f"parameter {name!r} must be a number")
    if expected in _SCALAR_TYPES and not isinstance(value, _SCALAR_TYPES[expected]):
        raise InvalidParameterError(
            f"parameter {name!r} must be a {expected}, got {type(value).__name__}"
        )
    if "enum" in schema and value not in schema["enum"]:
        raise InvalidParameterError(
            f"parameter {name!r} must be one of {schema['enum']}"
        )
    if expected in ("number", "integer"):
        if "minimum" in schema and value < schema["minimum"]:
            raise InvalidParameterError(
                f"parameter {name!r} must be >= {schema['minimum']}"
            )
        if "maximum" in schema and value > schema["maximum"]:
            raise InvalidParameterError(
                f"parameter {name!r} must be <= {schema['maximum']}"
            )
    if expected == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            item_type = items.get("type")
            if item_type in _SCALAR_TYPES:
                for index, item in enumerate(value):
                    if item_type == "number" and isinstance(item, bool):
                        raise InvalidParameterError(
                            f"parameter {name!r}[{index}] must be a number"
                        )
                    if not isinstance(item, _SCALAR_TYPES[item_type]):
                        raise InvalidParameterError(
                            f"parameter {name!r}[{index}] must be a {item_type}"
                        )


def validate(spec: ToolSpec, args: dict[str, Any] | None) -> dict[str, Any]:
    schema = spec.input_schema
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise InvalidParameterError("tool arguments must be a JSON object")
    unknown = sorted(set(args) - set(properties))
    if unknown:
        raise InvalidParameterError(
            f"unknown parameter(s) {unknown} for {spec.name}",
            known=sorted(properties),
        )
    validated: dict[str, Any] = {}
    for name, prop in properties.items():
        if name in args:
            _check_value(name, prop, args[name])
            validated[name] = args[name]
        elif "default" in prop:
            validated[name] = prop["default"]
    missing = sorted(required - set(validated))
    if missing:
        raise InvalidParameterError(f"missing required parameter(s): {missing}")
    return validated


def obj(
    properties: dict[str, Any],
    required: tuple[str, ...] | list[str] = (),
    **extra: Any,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(required),
    }
    schema.update(extra)
    return schema


def prop(description: str, **schema: Any) -> dict[str, Any]:
    return {"description": description, **schema}


def number(description: str, **schema: Any) -> dict[str, Any]:
    return prop(description, type="number", **schema)


def integer(description: str, **schema: Any) -> dict[str, Any]:
    return prop(description, type="integer", **schema)


def string(description: str, **schema: Any) -> dict[str, Any]:
    return prop(description, type="string", **schema)


def boolean(description: str, **schema: Any) -> dict[str, Any]:
    return prop(description, type="boolean", **schema)


def array(description: str, items: dict[str, Any], **schema: Any) -> dict[str, Any]:
    return prop(description, type="array", items=items, **schema)
