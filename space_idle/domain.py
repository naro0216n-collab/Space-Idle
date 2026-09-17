from __future__ import annotations

from dataclasses import dataclass
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
    optional: bool = False


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


def validate_extension_registry(extensions: tuple[DomainExtension, ...]) -> None:
    """Validate generic extension identity constraints without knowing any content/domain set."""
    names = [extension.name for extension in extensions]
    if len(names) != len(set(names)):
        raise ValueError("duplicate domain extension name")
    codec_keys = [extension.state_codec.key for extension in extensions if extension.state_codec is not None]
    if len(codec_keys) != len(set(codec_keys)):
        raise ValueError("duplicate domain state codec key")
