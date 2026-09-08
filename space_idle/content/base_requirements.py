from __future__ import annotations

from ..facilities import CapabilitySupply
from ..projects import BuildComponentRequirement, ConstructionRecipe, LocalSubstitutionTier
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


def _structure_component(amount: float) -> BuildComponentRequirement:
    return BuildComponentRequirement(
        "structure",
        amount,
        STRUCTURAL_COMPONENTS,
        (
            LocalSubstitutionTier(BULK_STRUCTURE, 0.25),
            LocalSubstitutionTier(FABRICATED_STRUCTURE, 0.80),
        ),
    )


def _machinery_component(amount: float) -> BuildComponentRequirement:
    return BuildComponentRequirement(
        "machinery",
        amount,
        MACHINERY,
        (LocalSubstitutionTier(BASIC_MACHINE_PARTS, 0.35),),
    )


def _electronics_component(amount: float) -> BuildComponentRequirement:
    return BuildComponentRequirement("electronics", amount, PRECISION_ELECTRONICS)


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
    return ConstructionRecipe(
        facility_id,
        (_structure_component(structure_t), _machinery_component(machinery_t), _electronics_component(electronics_t)),
        work,
        site,
        technologies,
        self_deploying,
    )
