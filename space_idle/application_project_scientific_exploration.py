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
        power_by_location = self._tick_decision_projection().allocations.power_by_location
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
                priority = 3
                can_set_priority = False
            else:
                status = state.phase.value
                paused = state.paused
                progress_days = state.progress_days
                awarded = state.research_points_awarded
                assigned_vehicle_definition_id = (
                    None if state.vehicle_definition_id is None else str(state.vehicle_definition_id)
                )
                reserved_units = state.reserved_units
                priority = state.priority
                can_set_priority = state.phase.value != "complete"
                blockers = service.blockers(
                    definition.id,
                    day=sim.day,
                    power_by_location=power_by_location,
                )

            movement_operations: tuple[tuple[str, float], ...] = ()
            outbound_latency_days: int | None = None
            return_latency_days: int | None = None
            movement_execution = (
                None
                if state is None or state.movement_execution_id is None
                else sim.transport.movement_execution_snapshot(state.movement_execution_id)
            )
            if movement_execution is not None:
                # A started one-shot Movement is authoritative.  Query output must
                # not drift when current Vehicle/Infrastructure definitions change.
                movement_operations = tuple(
                    (operation.operation_type, operation.delta_v_km_s)
                    for leg in movement_execution.legs
                    for operation in leg.operations
                )
                if state.phase.value == "outbound":
                    outbound_latency_days = movement_execution.latency_days
                elif state.phase.value == "returning":
                    return_latency_days = movement_execution.latency_days

            if assigned_vehicle_definition_id is not None:
                vehicle_id = state.vehicle_definition_id
                assert vehicle_id is not None
                try:
                    vehicle = sim.transport.vehicle_definition(vehicle_id)
                    assert vehicle is not None
                    if outbound_latency_days is None:
                        outbound_plans = service.movement_path(
                            definition, vehicle_id, sim.day
                        )
                        outbound_latency_days = sum(
                            sim.transport.performance_movement_transit_days(
                                plan, vehicle.performance
                            )
                            for plan in outbound_plans
                        )
                        if movement_execution is None:
                            movement_operations = tuple(
                                (operation.operation_type, operation.delta_v_km_s)
                                for plan in outbound_plans
                                for operation in plan.operations
                            )
                    if definition.return_to_origin and return_latency_days is None:
                        return_plans = service.movement_path(
                            definition, vehicle_id, sim.day, reverse=True
                        )
                        return_latency_days = sum(
                            sim.transport.performance_movement_transit_days(
                                plan, vehicle.performance
                            )
                            for plan in return_plans
                        )
                except ValueError:
                    # A future/unstarted leg may cease to be feasible.  The active
                    # MovementExecution, when present, remains visible above.
                    pass

            fleet_options: list[ScientificExplorationFleetOptionRow] = []
            for vehicle_definition in sim.transport.vehicle_definitions():
                fleet = sim.transport.fleet_pool_snapshot(
                    vehicle_definition.id, definition.origin_id
                )
                option_blockers = service.fleet_failures(
                    definition.id,
                    vehicle_definition.id,
                    day=sim.day,
                    power_by_location=power_by_location,
                )
                if state is not None and state.vehicle_definition_id == vehicle_definition.id:
                    option_blockers = ()
                option_outbound_latency: int | None = None
                option_return_latency: int | None = None
                try:
                    option_outbound = service.movement_path(
                        definition, vehicle_definition.id, sim.day
                    )
                    option_outbound_latency = sum(
                        sim.transport.performance_movement_transit_days(
                            plan, vehicle_definition.performance
                        )
                        for plan in option_outbound
                    )
                    if definition.return_to_origin:
                        option_return = service.movement_path(
                            definition, vehicle_definition.id, sim.day, reverse=True
                        )
                        option_return_latency = sum(
                            sim.transport.performance_movement_transit_days(
                                plan, vehicle_definition.performance
                            )
                            for plan in option_return
                        )
                except ValueError:
                    pass
                fleet_options.append(
                    ScientificExplorationFleetOptionRow(
                        vehicle_definition_id=str(vehicle_definition.id),
                        display_name=vehicle_definition.display_name,
                        operational_node_id=str(definition.origin_id),
                        total_units=fleet.total_units,
                        free_units=fleet.free_units,
                        required_units=definition.required_units,
                        blockers=option_blockers,
                        outbound_latency_days=option_outbound_latency,
                        return_latency_days=option_return_latency,
                        can_assign=service.can_assign_fleet(
                            definition.id,
                            vehicle_definition.id,
                            day=sim.day,
                            power_by_location=power_by_location,
                        ),
                    )
                )
            rows.append(
                ScientificExplorationRow(
                    id=str(definition.id),
                    display_name=definition.display_name,
                    status=status,
                    paused=paused,
                    priority=priority,
                    can_set_priority=can_set_priority,
                    origin_id=str(definition.origin_id),
                    destination_id=str(definition.destination_id),
                    movement_operations=movement_operations,
                    outbound_latency_days=outbound_latency_days,
                    return_latency_days=return_latency_days,
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
