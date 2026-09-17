from __future__ import annotations

from ..facilities import CapabilitySupply, ServiceCapacitySupply
from ..service_capacity import ServiceCapacityScope
from ..projects import BuildResourceRequirement, ConstructionRecipe
from ..shared import DefinitionId
from ..site import (
    CapabilityRequirement, CapabilityRequirementState, FacetValueRange, SiteRequirements,
    SpatialClassification, SpatialClassificationRequirement,
)
from ..spatial import AtmosphereField, ThermalField
from .base_ids import STRUCTURAL_COMPONENTS, MACHINERY, PRECISION_ELECTRONICS, BULK_STRUCTURE, FABRICATED_STRUCTURE, BASIC_MACHINE_PARTS

SURFACE_CLASSIFICATION = (
    SpatialClassificationRequirement(
        SpatialClassification.SURFACE, "spatial:surface", "地表地点が必要"
    ),
)
ORBIT_CLASSIFICATION = (
    SpatialClassificationRequirement(
        SpatialClassification.ORBITAL, "spatial:orbit", "軌道地点が必要"
    ),
)
VACUUM_ENV = (
    FacetValueRange(
        AtmosphereField, "pressure_pa", "environment:low_pressure", "低圧環境が必要", maximum=1000.0
    ),
)
COLD_VOLATILE_ENV = VACUUM_ENV + (
    FacetValueRange(
        ThermalField, "nominal_temperature_k", "environment:cold", "低温環境が必要", maximum=180.0
    ),
)
SURFACE_SITE = SiteRequirements(spatial_classification_requirements=SURFACE_CLASSIFICATION)
ORBIT_SITE = SiteRequirements(spatial_classification_requirements=ORBIT_CLASSIFICATION)
ATMOSPHERIC_SURFACE_SITE = SiteRequirements(
    environment=(
        FacetValueRange(
            AtmosphereField,
            "pressure_pa",
            "environment:atmospheric_surface",
            "十分な大気圧を持つ地表が必要",
            minimum=50000.0,
        ),
    ),
    spatial_classification_requirements=SURFACE_CLASSIFICATION,
)
VACUUM_SURFACE_SITE = SiteRequirements(
    environment=VACUUM_ENV,
    spatial_classification_requirements=SURFACE_CLASSIFICATION,
)
COLD_VOLATILE_SURFACE_SITE = SiteRequirements(
    environment=COLD_VOLATILE_ENV,
    spatial_classification_requirements=SURFACE_CLASSIFICATION,
)


def with_capabilities(site: SiteRequirements, *capability_ids: str) -> SiteRequirements:
    return SiteRequirements(
        environment=site.environment,
        capability_requirements=site.capability_requirements + _available_requirements(*capability_ids),
        spatial_classification_requirements=site.spatial_classification_requirements,
    )



def _capabilities(*ids: str) -> tuple[CapabilitySupply, ...]:
    return tuple(CapabilitySupply(capability_id) for capability_id in ids)


def _services(**rates: float) -> tuple[ServiceCapacitySupply, ...]:
    return tuple(
        ServiceCapacitySupply(service_type, rate)
        for service_type, rate in sorted(rates.items())
    )


def _organization_services(**rates: float) -> tuple[ServiceCapacitySupply, ...]:
    return tuple(
        ServiceCapacitySupply(service_type, rate, ServiceCapacityScope.ORGANIZATION)
        for service_type, rate in sorted(rates.items())
    )


def _infrastructure_requirements(*ids: str) -> tuple[CapabilityRequirement, ...]:
    return tuple(CapabilityRequirement(capability_id, CapabilityRequirementState.INSTALLED) for capability_id in ids)


def _available_requirements(*ids: str) -> tuple[CapabilityRequirement, ...]:
    return tuple(CapabilityRequirement(capability_id, CapabilityRequirementState.ACTIVE) for capability_id in ids)


def _structure_resource(amount: float) -> BuildResourceRequirement:
    return BuildResourceRequirement(STRUCTURAL_COMPONENTS, amount)


def _machinery_resource(amount: float) -> BuildResourceRequirement:
    return BuildResourceRequirement(MACHINERY, amount)


def _electronics_resource(amount: float) -> BuildResourceRequirement:
    return BuildResourceRequirement(PRECISION_ELECTRONICS, amount)


def _surface_recipe(
    facility_id: DefinitionId,
    structure_t: float,
    machinery_t: float,
    electronics_t: float,
    work: float,
    *,
    technologies: frozenset[DefinitionId] = frozenset(),
    capabilities: frozenset[str] = frozenset(),
    self_deploying: bool = False,
) -> ConstructionRecipe:
    site = SiteRequirements(capability_requirements=_infrastructure_requirements(*sorted(capabilities)))
    resources = tuple(
        requirement
        for requirement in (
            _structure_resource(structure_t) if structure_t > 0 else None,
            _machinery_resource(machinery_t) if machinery_t > 0 else None,
            _electronics_resource(electronics_t) if electronics_t > 0 else None,
        )
        if requirement is not None
    )
    return ConstructionRecipe(
        facility_id,
        resources,
        work,
        site,
        technologies,
        self_deploying,
    )
