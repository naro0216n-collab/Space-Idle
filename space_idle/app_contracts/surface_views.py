from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceResourceKnowledgeRow:
    resource_id: str
    resource_name: str
    knowledge_level: int
    presence_probability: float | None
    visible_potential: float | None
    visible_potential_precision_fraction: float | None


@dataclass(frozen=True)
class SurfaceCellRow:
    id: str
    body_id: str
    area_km2: float
    latitude_deg: float
    longitude_deg: float
    neighbor_ids: tuple[str, ...]
    terrain: tuple[tuple[str, float], ...]
    resources: tuple[SurfaceResourceKnowledgeRow, ...]
    developed: bool
    location_id: str | None
    is_location_core: bool
    foundation_blockers: tuple[tuple[str, str], ...]
    development_options: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


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
