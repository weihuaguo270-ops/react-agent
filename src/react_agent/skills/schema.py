"""Small dependency-free JSON Schema subset used at the Skill boundary."""
from __future__ import annotations

import math
from typing import Any


class SkillSchemaError(ValueError):
    """Raised when Skill input or output violates its declared schema."""


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    """Validate the practical schema subset needed by business Skills."""
    if not isinstance(schema, dict):
        raise SkillSchemaError(f"{path}: schema must be an object")
    expected = schema.get("type")
    if expected:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, item) for item in expected_types):
            raise SkillSchemaError(
                f"{path}: expected type {expected_types}, got {type(value).__name__}"
            )

    if "enum" in schema and value not in schema["enum"]:
        raise SkillSchemaError(f"{path}: value is not in enum")
    if "const" in schema and value != schema["const"]:
        raise SkillSchemaError(f"{path}: value does not match const")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise SkillSchemaError(f"{path}: string is shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise SkillSchemaError(f"{path}: string exceeds maxLength")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise SkillSchemaError(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise SkillSchemaError(f"{path}: number is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SkillSchemaError(f"{path}: number exceeds maximum")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise SkillSchemaError(f"{path}: array has too few items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SkillSchemaError(f"{path}: array has too many items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema(item, item_schema, path=f"{path}[{index}]")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise SkillSchemaError(f"{path}: missing required property {key!r}")
        properties = schema.get("properties") or {}
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], path=f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise SkillSchemaError(f"{path}: unexpected property {key!r}")


def schema_descriptor(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a defensive copy suitable for discovery responses."""
    return dict(schema or {})
