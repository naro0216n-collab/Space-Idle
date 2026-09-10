from __future__ import annotations

from .application_views import (
    ScientificExplorationRow,
    ScientificExplorationVehicleOptionRow,
    ScientificExplorationsView,
)


class ScientificExplorationProgressionProjectorMixin:
    def _scientific_explorations_view(self) -> ScientificExplorationsView:
        sim = self._simulation
        service = sim.scientific_exploration
        if service is None:
            return ScientificExplorationsView(())
        rows: list[ScientificExplorationRow] = []
        for definition in sorted(service.definitions.values(), key=lambda row: str(row.id)):
            state = service.campaigns.get(definition.id)
            if state is None:
                status = "available"
                paused = False
                progress_days = 0.0
                awarded = 0.0
                assigned_vehicle_id = None
                blockers: tuple[str, ...] = ()
            else:
                status = state.phase.value
                paused = state.paused
                progress_days = state.progress_days
                awarded = state.research_points_awarded
                assigned_vehicle_id = None if state.vehicle_id is None else str(state.vehicle_id)
                blockers = service.blockers(definition.id, day=sim.day)

            vehicle_options: list[ScientificExplorationVehicleOptionRow] = []
            for vehicle in sorted(sim.logistics.vehicles.values(), key=lambda row: str(row.id)):
                vehicle_def = sim.logistics.vehicle_defs[vehicle.definition_id]
                option_blockers = service.vehicle_failures(definition.id, vehicle.id, day=sim.day)
                if state is not None and state.vehicle_id == vehicle.id:
                    option_blockers = ()
                vehicle_options.append(ScientificExplorationVehicleOptionRow(
                    str(vehicle.id),
                    str(vehicle.definition_id),
                    vehicle_def.display_name,
                    None if vehicle.location_id is None else str(vehicle.location_id),
                    vehicle.status.value,
                    option_blockers,
                ))
            rows.append(ScientificExplorationRow(
                str(definition.id),
                definition.display_name,
                status,
                paused,
                str(definition.origin_id),
                str(definition.destination_id),
                tuple((operation.operation_type, operation.delta_v_km_s) for operation in definition.operations),
                definition.mission_duration_days,
                definition.duration_days,
                progress_days,
                definition.research_points_total,
                awarded,
                tuple((str(resource_id), amount) for resource_id, amount in definition.consumable_resources),
                assigned_vehicle_id,
                blockers,
                tuple(vehicle_options),
            ))
        return ScientificExplorationsView(tuple(rows))
