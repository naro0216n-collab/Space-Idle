from __future__ import annotations

from .application_catalog_support import site_requirements_definition
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
                    vehicle_id=str(vehicle.id),
                    vehicle_definition_id=str(vehicle.definition_id),
                    display_name=vehicle_def.display_name,
                    location_id=None if vehicle.location_id is None else str(vehicle.location_id),
                    status=vehicle.status.value,
                    blockers=option_blockers,
                    can_assign=service.can_assign_vehicle(definition.id, vehicle.id, day=sim.day),
                ))
            rows.append(ScientificExplorationRow(
                id=str(definition.id),
                display_name=definition.display_name,
                status=status,
                paused=paused,
                origin_id=str(definition.origin_id),
                destination_id=str(definition.destination_id),
                operations=tuple(
                    (operation.operation_type, operation.delta_v_km_s)
                    for operation in definition.operations
                ),
                mission_duration_days=definition.mission_duration_days,
                origin_requirements=site_requirements_definition(definition.origin_requirements),
                destination_requirements=site_requirements_definition(definition.destination_requirements),
                duration_days=definition.duration_days,
                progress_days=progress_days,
                research_points_total=definition.research_points_total,
                research_points_per_day=definition.points_per_day,
                research_points_awarded=awarded,
                consumable_resources=tuple(
                    (str(resource_id), amount)
                    for resource_id, amount in definition.consumable_resources
                ),
                assigned_vehicle_id=assigned_vehicle_id,
                blockers=blockers,
                can_start=service.can_start(definition.id),
                can_pause=service.can_pause(definition.id),
                can_resume=service.can_resume(definition.id),
                can_unassign=service.can_unassign_vehicle(definition.id),
                vehicle_options=tuple(vehicle_options),
            ))
        return ScientificExplorationsView(tuple(rows))
