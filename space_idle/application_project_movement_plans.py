from __future__ import annotations

from .application_transport_support import infrastructure_requirement_rows, vehicle_concept
from .application_constraints import constraints_from_codes
from .application_views import (
    DirectionalCapacityRow,
    MovementEndpointRow,
    MovementServiceModeRow,
    MovementPlanRow,
    MovementPlansView,
    TransportAllocationOptionRow,
    TransportAllocationOptionsView,
    TransportAllocationPreviewView,
    TransportCapacityPresetRow,
)
from .shared import DefinitionId, EntityId, MovementPlanId
from .transport.models import DirectionalCapacity


class LogisticsMovementPlanProjectorMixin:
    @staticmethod
    def _directional_capacity_row(value) -> DirectionalCapacityRow:
        return DirectionalCapacityRow(
            value.forward_t_per_day, value.reverse_t_per_day
        )

    def _transport_capacity_assistance(
        self, vehicle_definition_id, source_id, plan
    ):
        sim = self._simulation
        fleet = sim.transport.fleet_pool_snapshot(vehicle_definition_id, source_id)
        preset_units = tuple(dict.fromkeys((1, fleet.free_units, fleet.total_units)))
        presets = tuple(
            TransportCapacityPresetRow(
                key=(
                    "one_unit" if units == 1
                    else "free_fleet" if units == fleet.free_units
                    else "total_fleet"
                ),
                display_name=(
                    "1 unit分" if units == 1
                    else "空きFleet分" if units == fleet.free_units
                    else "全Fleet分"
                ),
                capacity=self._directional_capacity_row(
                    sim.transport.capacity_for_service_units(plan.nominal_per_unit, units)
                ),
                units=units,
            )
            for units in preset_units
            if units > 0
        )
        suggested_units = max(1, fleet.total_units)
        suggested_max = sim.transport.capacity_for_service_units(
            plan.nominal_per_unit, suggested_units
        )
        return fleet, presets, suggested_max

    def _movement_service_mode_rows(self, movement_plan) -> tuple[MovementServiceModeRow, ...]:
        sim = self._simulation
        rows: list[MovementServiceModeRow] = []

        for definition in sim.transport.vehicle_definitions():
            plan = sim.transport.transport_service_plan_for(
                definition.id,
                movement_plan.origin_id,
                movement_plan.destination_id,
                day=sim.day,
                movement_hard_constraint=(movement_plan.id,),
            )
            fleet = sim.transport.fleet_pool_snapshot(
                definition.id, movement_plan.origin_id
            )
            full_load_propellant = None
            if definition.propellant_resource_id is not None:
                full_load_propellant = definition.propellant_t(
                    movement_plan, max(0.0, plan.forward_payload_t)
                )
            rows.append(
                MovementServiceModeRow(
                    id=str(definition.id),
                    display_name=definition.display_name,
                    kind=vehicle_concept(definition),
                    vehicle_definition_id=str(definition.id),
                    fleet_total_units=fleet.total_units,
                    fleet_free_units=fleet.free_units,
                    nominal_capacity=self._directional_capacity_row(
                        plan.nominal_per_unit
                    ),
                    cycle_days=plan.cycle_days,
                    forward_latency_days=plan.forward_latency_days,
                    reverse_latency_days=plan.reverse_latency_days,
                    propellant_resource_id=(
                        None
                        if definition.propellant_resource_id is None
                        else str(definition.propellant_resource_id)
                    ),
                    full_load_propellant_t=full_load_propellant,
                    service_feasible=plan.feasible,
                    infrastructure_requirements=infrastructure_requirement_rows(plan),
                    blockers=constraints_from_codes(
                        plan.blockers,
                        affected_action="use_movement_service",
                        related_entity_kind="movement_plan",
                        related_entity_id=str(movement_plan.id),
                    ),
                )
            )

        return tuple(rows)

    def _movement_plan_rows(
        self,
        *,
        origin_id: str | None = None,
        destination_id: str | None = None,
        movement_plan_id: str | None = None,
        include_modes: bool = True,
    ) -> tuple[MovementPlanRow, ...]:
        sim = self._simulation
        if movement_plan_id is not None:
            movement_plan = sim.transport.movement_plan(movement_plan_id)
            candidates = () if movement_plan is None else (movement_plan,)
        elif origin_id is not None and destination_id is not None:
            candidates = sim.transport.movement_plan_candidates(origin_id, destination_id)
        elif origin_id is not None:
            candidates = sim.transport.outbound_movement_plans(origin_id)
        elif destination_id is not None:
            candidates = sim.transport.inbound_movement_plans(destination_id)
        else:
            candidates = sim.transport.movement_plan_options()

        rows: list[MovementPlanRow] = []
        for movement_plan in candidates:
            movement_plan_blockers = sim.transport.movement_plan_failures(movement_plan.id, sim.day)
            mode_rows = self._movement_service_mode_rows(movement_plan)
            try:
                geometry = sim.transport.movement_geometry(movement_plan.id)
                origin_endpoint = MovementEndpointRow(
                    str(geometry.origin.node_id), geometry.origin.locator_kind,
                    geometry.origin.locator_id,
                    None if geometry.origin.surface_cell_id is None else str(geometry.origin.surface_cell_id),
                )
                destination_endpoint = MovementEndpointRow(
                    str(geometry.destination.node_id), geometry.destination.locator_kind,
                    geometry.destination.locator_id,
                    None if geometry.destination.surface_cell_id is None else str(geometry.destination.surface_cell_id),
                )
                same_body_surface = geometry.same_body_surface
                distance_km = geometry.distance_km
            except ValueError:
                origin_endpoint = MovementEndpointRow(
                    str(movement_plan.origin_id), movement_plan.origin.locator_kind, movement_plan.origin.locator_id, None
                )
                destination_endpoint = MovementEndpointRow(
                    str(movement_plan.destination_id), movement_plan.destination.locator_kind, movement_plan.destination.locator_id, None
                )
                same_body_surface = False
                distance_km = None
            rows.append(
                MovementPlanRow(
                    id=str(movement_plan.id),
                    display_name=movement_plan.display_name or str(movement_plan.id),
                    origin_id=str(movement_plan.origin_id),
                    destination_id=str(movement_plan.destination_id),
                    origin_endpoint=origin_endpoint,
                    destination_endpoint=destination_endpoint,
                    same_body_surface=same_body_surface,
                    distance_km=distance_km,
                    available=not movement_plan_blockers,
                    service_feasible_now=any(
                        row.service_feasible for row in mode_rows
                    ),
                    transit_days=movement_plan.transit_days,
                    delta_v_km_s=movement_plan.delta_v_km_s,
                    operations=tuple(
                        (operation.operation_type, operation.delta_v_km_s)
                        for operation in movement_plan.operations
                    ),
                    blockers=constraints_from_codes(
                        movement_plan_blockers,
                        affected_action="use_movement_plan",
                        related_entity_kind="movement_plan",
                        related_entity_id=str(movement_plan.id),
                    ),
                    modes=mode_rows if include_modes else (),
                )
            )
        return tuple(rows)

    def _movement_plans_view(self, query) -> MovementPlansView:
        rows = self._movement_plan_rows(
            origin_id=query.origin_id,
            destination_id=query.destination_id,
            movement_plan_id=query.movement_plan_id,
            include_modes=query.include_modes,
        )
        if query.movement_plan_id is not None and not rows:
            raise KeyError(query.movement_plan_id)
        return MovementPlansView(rows)

    def _transport_allocation_options_view(
        self, source_id, destination_id
    ) -> TransportAllocationOptionsView:
        sim = self._simulation
        options: list[TransportAllocationOptionRow] = []
        for definition in sim.transport.vehicle_definitions():
            plan = sim.transport.transport_service_plan_for(
                definition.id,
                source_id,
                destination_id,
                day=sim.day,
            )
            fleet, preset_rows, suggested_capacity_max = self._transport_capacity_assistance(
                definition.id, source_id, plan
            )
            options.append(
                TransportAllocationOptionRow(
                    vehicle_definition_id=str(definition.id),
                    display_name=definition.display_name,
                    source_id=str(source_id),
                    destination_id=str(destination_id),
                    forward_path=tuple(str(value) for value in plan.forward_path),
                    reverse_path=tuple(str(value) for value in plan.reverse_path),
                    cycle_days=plan.cycle_days,
                    forward_latency_days=plan.forward_latency_days,
                    reverse_latency_days=plan.reverse_latency_days,
                    nominal_capacity=self._directional_capacity_row(
                        plan.nominal_per_unit
                    ),
                    suggested_capacity_max=self._directional_capacity_row(
                        suggested_capacity_max
                    ),
                    capacity_presets=preset_rows,
                    fleet_total_units=fleet.total_units,
                    fleet_free_units=fleet.free_units,
                    operational_supply_at_full_unit=tuple(
                        (str(location_id), str(resource_id), amount)
                        for location_id, resource_id, amount
                        in plan.resource_t_per_full_utilization_day
                    ),
                    infrastructure_requirements=infrastructure_requirement_rows(plan),
                    blockers=constraints_from_codes(
                        plan.blockers,
                        affected_action="plan_transport_allocation",
                        related_entity_kind="vehicle_definition",
                        related_entity_id=str(definition.id),
                    ),
                )
            )
        return TransportAllocationOptionsView(
            str(source_id), str(destination_id), tuple(options)
        )

    def _transport_allocation_preview_view(
        self, query, source_id, destination_id
    ) -> TransportAllocationPreviewView:
        sim = self._simulation
        vehicle_definition_id = DefinitionId(query.vehicle_definition_id)
        constraint = (
            None
            if not query.movement_hard_constraint
            else tuple(MovementPlanId(value) for value in query.movement_hard_constraint)
        )
        target = DirectionalCapacity(
            float(query.target_forward_t_per_day),
            float(query.target_reverse_t_per_day),
        )
        plan = sim.transport.transport_service_plan_for(
            vehicle_definition_id,
            source_id,
            destination_id,
            day=sim.day,
            movement_hard_constraint=constraint,
        )
        fleet, capacity_presets, suggested_capacity_max = self._transport_capacity_assistance(
            vehicle_definition_id, source_id, plan
        )
        current_units = 0
        if query.allocation_id is not None:
            allocation_id = EntityId(query.allocation_id)
            allocation = sim.transport.transport_allocation_snapshot(allocation_id)
            if allocation is None:
                raise KeyError(query.allocation_id)
            if (
                allocation.vehicle_definition_id != vehicle_definition_id
                or allocation.anchor_node_id != source_id
                or allocation.destination_id != destination_id
            ):
                raise ValueError("allocation preview context does not match allocation")
            current_units = sim.transport.transport_active_units(allocation_id)

        blockers = list(plan.blockers)
        try:
            required_units = sim.transport.required_units_for_capacity(
                target, plan.nominal_per_unit
            )
        except ValueError as exc:
            required_units = None
            blockers.append(str(exc))

        available_units = fleet.free_units + current_units
        if required_units is None:
            unfilled_units = None
            achievable = DirectionalCapacity()
        else:
            unfilled_units = max(0, required_units - available_units)
            achievable_units = min(required_units, available_units)
            achievable = sim.transport.capacity_for_service_units(
                plan.nominal_per_unit, achievable_units
            )
            if unfilled_units > 0:
                blockers.append(f"fleet_units:{available_units}/{required_units}")

        return TransportAllocationPreviewView(
            vehicle_definition_id=str(vehicle_definition_id),
            source_id=str(source_id),
            destination_id=str(destination_id),
            target_capacity=self._directional_capacity_row(target),
            nominal_capacity_per_unit=self._directional_capacity_row(plan.nominal_per_unit),
            suggested_capacity_max=self._directional_capacity_row(suggested_capacity_max),
            capacity_presets=capacity_presets,
            achievable_capacity=self._directional_capacity_row(achievable),
            required_units=required_units,
            available_units=available_units,
            unfilled_units=unfilled_units,
            selected_forward_path=tuple(str(value) for value in plan.forward_path),
            selected_reverse_path=tuple(str(value) for value in plan.reverse_path),
            cycle_days=plan.cycle_days,
            forward_latency_days=plan.forward_latency_days,
            reverse_latency_days=plan.reverse_latency_days,
            blockers=constraints_from_codes(
                tuple(dict.fromkeys(blockers)),
                affected_action="preview_transport_allocation",
                related_entity_kind="vehicle_definition",
                related_entity_id=str(vehicle_definition_id),
            ),
        )
