from __future__ import annotations

from .application_views import (
    SurfaceCellRow,
    SurfaceLocationTerritoryRow,
    SurfaceMapView,
    SurfaceResourceKnowledgeRow,
)
from .shared import CelestialBodyId


class SurfaceProjectorMixin:
    def _surface_map_view(self, body_id: CelestialBodyId) -> SurfaceMapView:
        sim = self._simulation
        body = sim.graph.bodies[body_id]
        locations = tuple(
            SurfaceLocationTerritoryRow(
                str(location.id),
                location.display_name,
                str(location.body_id),
                str(location.core_cell_id),
                tuple(sorted((str(cell_id) for cell_id in location.developed_cell_ids))),
            )
            for location in sorted(
                (row for row in sim.graph.locations.values() if row.body_id == body_id),
                key=lambda row: str(row.id),
            )
        )
        rows: list[SurfaceCellRow] = []
        for cell in sim.graph.cells_for_body(body_id):
            owner = sim.graph.owner_of_cell(cell.id)
            owner_state = None if owner is None else sim.graph.locations[owner]
            development_options = tuple(
                (
                    str(location.id),
                    sim.graph.surface_cell_development_failures(location.id, cell.id),
                )
                for location in sorted(
                    (row for row in sim.graph.locations.values() if row.body_id == body_id),
                    key=lambda row: str(row.id),
                )
            )
            resources = ()
            if sim.survey is not None:
                resources = tuple(
                    SurfaceResourceKnowledgeRow(
                        str(resource_id),
                        self._resource_name(resource_id),
                        sim.survey.knowledge_level(cell.id, resource_id),
                        sim.survey.visible_presence_probability(cell.id, resource_id),
                        sim.survey.visible_potential(cell.id, resource_id),
                        sim.survey.visible_potential_precision_fraction(cell.id, resource_id),
                    )
                    for (target_cell_id, resource_id) in sorted(
                        (
                            key
                            for key in sim.survey.targets
                            if key[0] == cell.id
                        ),
                        key=lambda key: str(key[1]),
                    )
                )
            rows.append(
                SurfaceCellRow(
                    str(cell.id),
                    str(cell.body_id),
                    cell.area_km2,
                    cell.centroid.latitude_deg,
                    cell.centroid.longitude_deg,
                    tuple(sorted(map(str, cell.neighbor_ids))),
                    (
                        ("terrain_factor", cell.terrain.terrain_factor),
                        ("bearing_capacity_factor", cell.terrain.bearing_capacity_factor),
                        ("dust_factor", cell.terrain.dust_factor),
                        ("slope_factor", cell.terrain.slope_factor),
                    ),
                    resources,
                    owner is not None,
                    None if owner is None else str(owner),
                    owner_state is not None and owner_state.core_cell_id == cell.id,
                    sim.graph.location_foundation_failures(body_id, cell.id),
                    development_options,
                )
            )
        return SurfaceMapView(str(body.id), body.display_name, tuple(rows), locations)
