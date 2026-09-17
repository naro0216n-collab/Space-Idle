from __future__ import annotations

from .domain import validate_extension_registry
from .simulation import Simulation
from .service_capacity import service_capacity_dependency_order
from .validation_support import ConfigurationError, ValidationContext


def validate_simulation_configuration(sim: Simulation) -> None:
    """Validate the configured simulation through domain-owned validators."""
    validate_extension_registry(sim.domain_extensions)
    ctx = ValidationContext.from_simulation(sim)
    service_owners: dict[str, str] = {}
    for extension in sim.domain_extensions:
        factory = extension.service_capacity_provider
        if factory is None:
            continue
        provider = factory(sim)
        if provider is None:
            continue
        for service_type in provider.service_capacity_types():
            prior = service_owners.get(service_type)
            if prior is not None:
                raise ConfigurationError(
                    f"service capacity type has multiple providers: {service_type}: {prior}, {extension.name}"
                )
            service_owners[service_type] = extension.name
            try:
                provider.service_capacity_scope(service_type)
            except (KeyError, ValueError) as exc:
                raise ConfigurationError(
                    f"service capacity provider has invalid scope: {extension.name}/{service_type}"
                ) from exc
    for extension in sim.domain_extensions:
        validator = extension.configuration_validator
        if validator is not None:
            validator(sim, ctx)

    dependencies = sim.service_capacity_dependencies()
    for dependency in dependencies:
        if dependency.service_type not in ctx.known_service_types:
            raise ConfigurationError(
                "service capacity dependency references unknown service type: "
                + dependency.service_type
            )
        if dependency.upstream_service_type not in ctx.known_service_types:
            raise ConfigurationError(
                "service capacity dependency references unknown upstream service type: "
                + dependency.upstream_service_type
            )
    try:
        service_capacity_dependency_order(ctx.known_service_types, dependencies)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    try:
        sim.tick_allocation_order(ctx.known_service_types)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


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
    for group_id, group in catalog.resource_groups.items():
        if group_id != group.id:
            raise ConfigurationError(f"resource group catalog key mismatch: {group_id}")
        if not group.display_name or not group.resource_ids:
            raise ConfigurationError(f"resource group definition is incomplete: {group_id}")
        if len(set(group.resource_ids)) != len(group.resource_ids):
            raise ConfigurationError(f"resource group contains duplicate members: {group_id}")
        missing_members = set(group.resource_ids) - set(catalog.resources)
        if missing_members:
            raise ConfigurationError(
                f"resource group {group_id} references missing resources: "
                + ",".join(sorted(map(str, missing_members)))
            )
        units = {catalog.resources[resource_id].unit for resource_id in group.resource_ids}
        if len(units) != 1:
            raise ConfigurationError(f"resource group mixes incompatible units: {group_id}")
