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
    blockers: tuple[tuple[str, str], ...]
    can_plan: bool
    procurement_policy_options: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceCellFoundationOption:
    staging_node_id: str
    deployment_recipe_id: str
    recipe_display_name: str
    vehicle_definition_id: str
    vehicle_display_name: str
    preparation_work: float
    transit_days: int
    payload_t: float
    payload_t_per_unit: float
    required_units: int
    resources: tuple[tuple[str, float], ...]
    blockers: tuple[tuple[str, str], ...]
    can_plan: bool
    active_project_id: str | None = None


@dataclass(frozen=True)
class SurfaceCellDevelopmentOption:
    location_id: str
    blockers: tuple[tuple[str, str], ...]
    can_plan: bool
    projected_surface_infrastructure_demand: float | None = None
    projected_surface_infrastructure_fulfillment: float | None = None
    limiting_factors: tuple[str, ...] = ()
    construction_required: float | None = None
    resources: tuple[tuple[str, float], ...] = ()
    active_project_id: str | None = None
    procurement_policy_options: tuple[str, ...] = ()


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
