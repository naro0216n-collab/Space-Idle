from __future__ import annotations

from dataclasses import dataclass

from .location_views import EnvironmentFacetRow


@dataclass(frozen=True)
class SurfaceResourceKnowledgeRow:
    resource_id: str
    resource_name: str
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None




@dataclass(frozen=True)
class SurfaceFacilityPlacementOption:
    facility_definition_id: str
    display_name: str
    location_id: str
    construction_required: float
    self_deploying: bool
    resources: tuple[tuple[str, float], ...]
    missing_technologies: tuple[str, ...]
    site_blockers: tuple[tuple[str, str], ...]
    sourcing_policy_options: tuple[str, ...] = ()
    import_source_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceCellFoundationOption:
    provider_location_id: str
    construction_required: float
    resources: tuple[tuple[str, float], ...]
    missing_technologies: tuple[str, ...]
    blockers: tuple[tuple[str, str], ...]
    active_project_id: str | None = None
    sourcing_policy_options: tuple[str, ...] = ()
    import_source_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceCellDevelopmentOption:
    location_id: str
    blockers: tuple[tuple[str, str], ...]
    projected_surface_infrastructure_demand: float | None = None
    projected_surface_infrastructure_fulfillment: float | None = None
    limiting_factors: tuple[str, ...] = ()
    construction_required: float | None = None
    resources: tuple[tuple[str, float], ...] = ()
    missing_technologies: tuple[str, ...] = ()
    active_project_id: str | None = None
    sourcing_policy_options: tuple[str, ...] = ()
    import_source_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceCellRow:
    id: str
    body_id: str
    area_km2: float
    latitude_deg: float
    longitude_deg: float
    neighbor_ids: tuple[str, ...]
    terrain: tuple[tuple[str, float], ...]
    environment: tuple[EnvironmentFacetRow, ...]
    resources: tuple[SurfaceResourceKnowledgeRow, ...]
    developed: bool
    location_id: str | None
    is_location_core: bool
    foundation_blockers: tuple[tuple[str, str], ...]
    development_options: tuple[SurfaceCellDevelopmentOption, ...]
    facility_placement_options: tuple[SurfaceFacilityPlacementOption, ...] = ()
    foundation_options: tuple[SurfaceCellFoundationOption, ...] = ()
    display_name: str = ""


@dataclass(frozen=True)
class SurfaceLocationTerritoryRow:
    id: str
    display_name: str
    body_id: str
    core_cell_id: str
    developed_cell_ids: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceMapView:
    body_id: str
    display_name: str
    cells: tuple[SurfaceCellRow, ...]
    locations: tuple[SurfaceLocationTerritoryRow, ...]
