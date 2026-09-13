from __future__ import annotations

from .domain import validate_extension_registry
from .simulation import Simulation
from .validation_support import ConfigurationError, ValidationContext


def validate_simulation_configuration(sim: Simulation) -> None:
    """Validate the configured simulation through domain-owned validators."""
    validate_extension_registry(sim.domain_extensions)
    ctx = ValidationContext.from_simulation(sim)
    for extension in sim.domain_extensions:
        validator = extension.configuration_validator
        if validator is not None:
            validator(sim, ctx)


def validate_runtime_state(sim: Simulation) -> None:
    """Validate configuration, then each domain's mutable-state invariants."""
    validate_simulation_configuration(sim)
    for extension in sim.domain_extensions:
        validator = extension.runtime_validator
        if validator is not None:
            validator(sim)


def validate_catalog_coverage(sim: Simulation, catalog) -> None:
    """Validate resource catalog coverage using domain-owned reference providers."""
    referenced = set()
    for extension in sim.domain_extensions:
        provider = extension.referenced_resources
        if provider is not None:
            referenced.update(provider(sim))

    missing = referenced - set(catalog.resources)
    if missing:
        raise ConfigurationError("catalog is missing resource definitions: " + ",".join(sorted(map(str, missing))))
    for resource_id, definition in catalog.resources.items():
        if resource_id != definition.id:
            raise ConfigurationError(f"resource catalog key mismatch: {resource_id}")
        if not definition.display_name or not definition.unit or not definition.category:
            raise ConfigurationError(f"resource catalog metadata is incomplete: {resource_id}")
