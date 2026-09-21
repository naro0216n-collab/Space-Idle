from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

from .shared import DefinitionId

CaptureFn = Callable[[Any], Any]
RestoreFn = Callable[[Any, Any], None]
ConfigurationValidator = Callable[[Any, Any], None]
RuntimeValidator = Callable[[Any], None]
ResourceReferenceProvider = Callable[[Any], set[DefinitionId]]
ServiceCapacityProviderFactory = Callable[[Any], Any]
ServiceCapacityRequestProviderFactory = Callable[[Any], Any]
AllocationPoolProviderFactory = Callable[[Any], Any]


@dataclass(frozen=True)
class StateCodec:
    key: str
    capture: CaptureFn
    restore: RestoreFn


@dataclass(frozen=True)
class DomainExtension:
    """Cross-cutting hooks owned by one domain.

    Persistence, validation and resource-catalog references are declared beside
    the domain that owns the state instead of being accumulated in central
    switch files. The composition root decides which domains are present.
    """

    name: str
    state_codec: StateCodec | None = None
    configuration_validator: ConfigurationValidator | None = None
    runtime_validator: RuntimeValidator | None = None
    referenced_resources: ResourceReferenceProvider | None = None
    service_capacity_provider: ServiceCapacityProviderFactory | None = None
    service_capacity_request_provider: ServiceCapacityRequestProviderFactory | None = None
    allocation_pool_provider: AllocationPoolProviderFactory | None = None


def decode_bool(value: Any, field: str) -> bool:
    """Decode a persisted boolean without Python truthiness coercion."""
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def decode_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def decode_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    decoded = float(value)
    if not math.isfinite(decoded):
        raise ValueError(f"{field} must be finite")
    return decoded


def decode_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def decode_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def decode_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} keys must be strings")
    return value


def require_fields(value: Any, fields: set[str], field: str) -> dict[str, Any]:
    row = decode_dict(value, field)
    if set(row) != fields:
        missing = sorted(fields - set(row))
        unexpected = sorted(set(row) - fields)
        raise ValueError(
            f"{field} has invalid fields; missing={missing}; unexpected={unexpected}"
        )
    return row


def validate_extension_registry(extensions: tuple[DomainExtension, ...]) -> None:
    """Validate generic extension identity constraints without knowing any content/domain set."""
    names = [extension.name for extension in extensions]
    if len(names) != len(set(names)):
        raise ValueError("duplicate domain extension name")
    codec_keys = [extension.state_codec.key for extension in extensions if extension.state_codec is not None]
    if len(codec_keys) != len(set(codec_keys)):
        raise ValueError("duplicate domain state codec key")
