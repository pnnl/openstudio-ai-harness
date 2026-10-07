"""Validate skill-bound schemas using their bounded JSON Schema vocabulary."""

from __future__ import annotations

import math


def finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate(
    value, schema: dict, root: dict | None = None, path: str = "$"
) -> list[str]:
    root = root or schema
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate(value, target, root, path)
    errors = []
    if "oneOf" in schema:
        matches = sum(
            not validate(value, option, root, path) for option in schema["oneOf"]
        )
        if matches != 1:
            errors.append(f"{path}: must match exactly one allowed form")
    kinds = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "number": finite_number(value),
    }
    if "type" in schema and not kinds[schema["type"]]:
        return [f"{path}: expected {schema['type']}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']}")
    if (
        isinstance(value, str)
        and "minLength" in schema
        and len(value.strip()) < schema["minLength"]
    ):
        errors.append(f"{path}: must be nonempty")
    if type(value) in (int, float):
        for key, bad in (
            ("minimum", lambda x: value < x),
            ("maximum", lambda x: value > x),
            ("exclusiveMinimum", lambda x: value <= x),
        ):
            if key in schema and bad(schema[key]):
                errors.append(f"{path}: violates {key} {schema[key]}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(
                f"{path}.{key}: unknown field"
                for key in sorted(value.keys() - props.keys())
            )
        errors.extend(
            f"{path}.{key}: required"
            for key in schema.get("required", [])
            if key not in value
        )
        for key in sorted(value.keys() & props.keys()):
            errors.extend(validate(value[key], props[key], root, f"{path}.{key}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: requires at least {schema['minItems']} items")
        if schema.get("uniqueItems") and any(
            item in value[:i] for i, item in enumerate(value)
        ):
            errors.append(f"{path}: duplicate items")
        for i, item in enumerate(value):
            if "items" in schema:
                errors.extend(validate(item, schema["items"], root, f"{path}[{i}]"))
    return errors


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON value: {value}")


def finite_float(value):
    import math

    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Nonfinite JSON number")
    return parsed


def read_json(path):
    import json

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
        parse_float=finite_float,
    )
