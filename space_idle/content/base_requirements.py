from __future__ import annotations

from ..facilities import CapabilitySupply
from ..projects import BuildResourceRequirement, ConstructionRecipe
from ..shared import DefinitionId
from ..site import CapabilityRequirement, FacetValueRange, RequiresFacet, SiteRequirements
from ..spatial import AtmosphereField, OrbitalField, SurfaceField, ThermalField
from .base_ids import STRUCTURAL_COMPONENTS, MACHINERY, PRECISION_ELECTRONICS, BULK_STRUCTURE, FABRICATED_STRUCTURE, BASIC_MACHINE_PARTS

SURFACE_ENV = (
    RequiresFacet(SurfaceField, "environment:surface", "地表環境が必要"),
)
ORBIT_ENV = (
    RequiresFacet(OrbitalField, "environment:orbit", "軌道環境が必要"),
)
VACUUM_SURFACE_ENV = SURFACE_ENV + (
    FacetValueRange(AtmosphereField, "pressure_pa", "environment:low_pressure", "低圧環境が必要", maximum=1000.0),
)
COLD_VOLATILE_SURFACE_ENV = VACUUM_SURFACE_ENV + (
    FacetValueRange(ThermalField, "nominal_temperature_k", "environment:cold", "低温環境が必要", maximum=180.0),
)
SURFACE_SITE = SiteRequirements(SURFACE_ENV)
ORBIT_SITE = SiteRequirements(ORBIT_ENV)
ATMOSPHERIC_SURFACE_SITE = SiteRequirements(SURFACE_ENV + (
    FacetValueRange(AtmosphereField, "pressure_pa", "environment:atmospheric_surface", "十分な大気圧を持つ地表が必要", minimum=50000.0),
))
VACUUM_SURFACE_SITE = SiteRequirements(VACUUM_SURFACE_ENV)


def _capabilities(*ids: str) -> tuple[CapabilitySupply, ...]:
    return tuple(CapabilitySupply(capability_id) for capability_id in ids)


def _infrastructure_requirements(*ids: str) -> tuple[CapabilityRequirement, ...]:
    return tuple(CapabilityRequirement(capability_id, 1.0, "infrastructure") for capability_id in ids)


def _available_requirements(*ids: str) -> tuple[CapabilityRequirement, ...]:
    # Any non-trivial powered service is enough for qualitative demonstrations;
    # physical throughput remains governed by the owning domain service.
    return tuple(CapabilityRequirement(capability_id, 0.01, "available") for capability_id in ids)


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
