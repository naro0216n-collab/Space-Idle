from __future__ import annotations

from .application_catalog_support import site_requirements_definition
from .application_views import (
    ScientificExplorationFleetOptionRow,
    ScientificExplorationRow,
    ScientificExplorationsView,
)


class ScientificExplorationProjectorMixin:
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
                assigned_vehicle_definition_id = None
                reserved_units = 0
                blockers: tuple[str, ...] = ()
            else:
                status = state.phase.value
                paused = state.paused
                progress_days = state.progress_days
                awarded = state.research_points_awarded
                assigned_vehicle_definition_id = (
                    None if state.vehicle_definition_id is None else str(state.vehicle_definition_id)
                )
                reserved_units = state.reserved_units
                blockers = service.blockers(definition.id, day=sim.day)

            fleet_options: list[ScientificExplorationFleetOptionRow] = []
            for vehicle_definition in sorted(
                sim.logistics.vehicle_defs.values(), key=lambda row: str(row.id)
            ):
                pool = sim.logistics.fleet_pool(vehicle_definition.id, definition.origin_id)
                free_units = sim.logistics.fleet_free_units(
                    vehicle_definition.id, definition.origin_id
                )
                option_blockers = service.fleet_failures(
                    definition.id, vehicle_definition.id, day=sim.day
                )
                if state is not None and state.vehicle_definition_id == vehicle_definition.id:
                    option_blockers = ()
                fleet_options.append(
                    ScientificExplorationFleetOptionRow(
                        vehicle_definition_id=str(vehicle_definition.id),
                        display_name=vehicle_definition.display_name,
                        location_id=str(definition.origin_id),
                        total_units=pool.total_units,
                        free_units=free_units,
                        required_units=definition.required_units,
                        blockers=option_blockers,
                        can_assign=service.can_assign_fleet(
                            definition.id, vehicle_definition.id, day=sim.day
                        ),
                    )
                )
            rows.append(
                ScientificExplorationRow(
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
                    required_units=definition.required_units,
                    minimum_payload_t=definition.minimum_payload_t,
                    required_vehicle_capabilities=definition.required_vehicle_capabilities,
                    assigned_vehicle_definition_id=assigned_vehicle_definition_id,
                    reserved_units=reserved_units,
                    blockers=blockers,
                    can_start=service.can_start(definition.id),
                    can_pause=service.can_pause(definition.id),
                    can_resume=service.can_resume(definition.id),
                    can_unassign=service.can_unassign_fleet(definition.id),
                    fleet_options=tuple(fleet_options),
                )
            )
        return ScientificExplorationsView(tuple(rows))
