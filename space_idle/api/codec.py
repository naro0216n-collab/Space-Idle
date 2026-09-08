from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
import types
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from ..application_commands import Command


class ApiPayloadError(ValueError):
    pass


def to_jsonable(value: Any) -> Any:
    """Convert application DTOs/results to a stable JSON-compatible shape."""
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _command_types() -> dict[str, type]:
    result: dict[str, type] = {}
    for command_type in get_args(Command):
        if isinstance(command_type, type) and is_dataclass(command_type):
            result[command_type.__name__] = command_type
    return result


COMMAND_TYPES = _command_types()


def command_schema() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for name, command_type in sorted(COMMAND_TYPES.items()):
        hints = get_type_hints(command_type)
        parameters = []
        for field in fields(command_type):
            parameters.append({
                "name": field.name,
                "type": _annotation_name(hints.get(field.name, field.type)),
                "required": field.default is MISSING and field.default_factory is MISSING,
                "default": None if field.default is MISSING else to_jsonable(field.default),
            })
        rows.append({"type": name, "parameters": parameters})
    return tuple(rows)


def _annotation_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Literal:
        return "literal[" + ",".join(repr(item) for item in get_args(annotation)) + "]"
    if origin in {tuple, list}:
        args = get_args(annotation)
        if args:
            return f"{origin.__name__}[{','.join(_annotation_name(arg) for arg in args if arg is not Ellipsis)}]"
        return origin.__name__
    if origin in {Union, types.UnionType}:
        return " | ".join(_annotation_name(arg) for arg in get_args(annotation))
    return getattr(annotation, "__name__", str(annotation))


def _coerce(value: Any, annotation: Any, path: str) -> Any:
    if annotation is Any:
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in {Union, types.UnionType}:
        if value is None and type(None) in args:
            return None
        last_error: ApiPayloadError | None = None
        for option in args:
            if option is type(None):
                continue
            try:
                return _coerce(value, option, path)
            except ApiPayloadError as exc:
                last_error = exc
        raise last_error or ApiPayloadError(f"{path}: invalid value")

    if origin is Literal:
        if value not in args:
            raise ApiPayloadError(f"{path}: expected one of {args!r}")
        return value

    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ApiPayloadError(f"{path}: expected array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce(item, args[0], f"{path}[]") for item in value)
        if args and len(value) != len(args):
            raise ApiPayloadError(f"{path}: expected {len(args)} items")
        return tuple(
            _coerce(item, args[index] if args else Any, f"{path}[{index}]")
            for index, item in enumerate(value)
        )

    if annotation is str:
        if not isinstance(value, str):
            raise ApiPayloadError(f"{path}: expected string")
        return value
    if annotation is bool:
        if not isinstance(value, bool):
            raise ApiPayloadError(f"{path}: expected boolean")
        return value
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiPayloadError(f"{path}: expected integer")
        return value
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiPayloadError(f"{path}: expected number")
        return float(value)
    return value


def decode_command(document: Any):
    if not isinstance(document, dict):
        raise ApiPayloadError("command document must be an object")
    command_name = document.get("type")
    payload = document.get("payload", {})
    if not isinstance(command_name, str) or command_name not in COMMAND_TYPES:
        raise ApiPayloadError(f"unknown command type: {command_name!r}")
    if not isinstance(payload, dict):
        raise ApiPayloadError("command payload must be an object")

    command_type = COMMAND_TYPES[command_name]
    field_map = {field.name: field for field in fields(command_type)}
    unknown = sorted(set(payload) - set(field_map))
    if unknown:
        raise ApiPayloadError(f"unknown command fields: {', '.join(unknown)}")

    hints = get_type_hints(command_type)
    values: dict[str, Any] = {}
    for name, field in field_map.items():
        if name not in payload:
            if field.default is MISSING and field.default_factory is MISSING:
                raise ApiPayloadError(f"missing command field: {name}")
            continue
        values[name] = _coerce(payload[name], hints.get(name, field.type), f"payload.{name}")
    try:
        return command_type(**values)
    except (TypeError, ValueError) as exc:
        raise ApiPayloadError(str(exc)) from exc
