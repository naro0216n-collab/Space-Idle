from __future__ import annotations

from .application_transport_support import infrastructure_requirement_rows
from .application_views import (
    CargoFlowRow, CargoFlowsView, DirectionalCapacityRow, FleetPoolRow,
    ExternalSupplyRow,
    FleetRelocationPreviewView, FleetRelocationResourceRequirementRow,
    FleetRelocationRow, FleetReleaseRow, FleetView, TransportAllocationRow,
    TransportAllocationsView, VehicleProductionOptionRow, VehicleProductionRow,
)
from .transport.models import PathPolicy
from .shared import DefinitionId, SpatialNodeId


class LogisticsStateProjectorMixin:
    @staticmethod
    def _capacity_row(value) -> DirectionalCapacityRow:
        return DirectionalCapacityRow(
            value.forward_t_per_day, value.reverse_t_per_day
        )

    def _vehicle_definition(self, definition_id: DefinitionId):
        definition = self._simulation.transport.vehicle_definition(definition_id)
        if definition is None:
            raise RuntimeError(f"Transport projection references unknown Vehicle: {definition_id}")
        return definition

    def _fleet_pool_rows(
        self,
        *,
        location_id: str | None = None,
        vehicle_definition_id: str | None = None,
    ) -> tuple[FleetPoolRow, ...]:
        sim = self._simulation
        keys = set(sim.transport.fleet_pool_keys())
        # Allocations/reservations can make a zero-total pool decision-relevant.
        keys.update(
            (row.vehicle_definition_id, row.anchor_node_id)
            for row in sim.transport.transport_allocation_snapshots()
        )
        keys.update(
            (row.vehicle_definition_id, row.operational_node_id)
            for row in sim.transport.fleet_reservation_snapshots()
        )
        rows: list[FleetPoolRow] = []
        for definition_id, node_id in sorted(keys, key=lambda row: (str(row[0]), str(row[1]))):
            if location_id is not None and str(node_id) != location_id:
                continue
            if vehicle_definition_id is not None and str(definition_id) != vehicle_definition_id:
                continue
            snapshot = sim.transport.fleet_pool_snapshot(definition_id, node_id)
            rows.append(
                FleetPoolRow(
                    str(definition_id),
                    self._vehicle_definition(definition_id).display_name,
                    str(node_id),
                    snapshot.total_units,
                    snapshot.free_units,
                    snapshot.transport_units,
                    snapshot.exploration_units,
                    snapshot.other_reserved_units,
                    snapshot.relocating_units,
                    snapshot.releasing_units,
                )
            )
        return tuple(rows)

    def _fleet_relocation_rows(
        self,
        *,
        location_id: str | None = None,
        vehicle_definition_id: str | None = None,
    ) -> tuple[FleetRelocationRow, ...]:
        sim = self._simulation
        return tuple(
            FleetRelocationRow(
                str(row.id), str(row.vehicle_definition_id),
                self._vehicle_definition(row.vehicle_definition_id).display_name,
                row.units, str(row.source_id), str(row.destination_id),
                (
                    None
                    if row.movement_execution_id is None
                    else sim.transport.movement_executions[row.movement_execution_id].started_day
                ),
                (
                    None
                    if row.movement_execution_id is None
                    else sim.transport.movement_executions[row.movement_execution_id].completion_day
                ),
            )
            for row in sim.transport.fleet_relocation_snapshots()
            if (vehicle_definition_id is None or str(row.vehicle_definition_id) == vehicle_definition_id)
            and (
                location_id is None
                or str(row.source_id) == location_id
                or str(row.destination_id) == location_id
            )
        )

    def _fleet_release_rows(
        self,
        *,
        location_id: str | None = None,
        vehicle_definition_id: str | None = None,
    ) -> tuple[FleetReleaseRow, ...]:
        sim = self._simulation
        return tuple(
            FleetReleaseRow(
                str(row.id),
                str(row.allocation_id),
                str(row.vehicle_definition_id),
                self._vehicle_definition(row.vehicle_definition_id).display_name,
                str(row.operational_node_id),
                row.units,
                row.release_day,
                max(0, row.release_day - sim.day),
            )
            for row in sim.transport.fleet_release_snapshots()
            if (location_id is None or str(row.operational_node_id) == location_id)
            and (vehicle_definition_id is None or str(row.vehicle_definition_id) == vehicle_definition_id)
        )

    def _transport_allocation_rows(self) -> tuple[TransportAllocationRow, ...]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        rows: list[TransportAllocationRow] = []
        for allocation in sim.transport.transport_allocation_snapshots():
            plan = sim.transport.derive_transport_service_plan(allocation.id, sim.day)
            snapshot = sim.logistics.current_transport_capacity_snapshot(
                allocation.id,
                day=sim.day,
                execution_allocation=decision.allocations.transport,
            )
            rows.append(
                TransportAllocationRow(
                    id=str(allocation.id),
                    vehicle_definition_id=str(allocation.vehicle_definition_id),
                    display_name=self._vehicle_definition(allocation.vehicle_definition_id).display_name,
                    anchor_node_id=str(allocation.anchor_node_id),
                    destination_id=str(allocation.destination_id),
                    provisioning_priority=allocation.provisioning_priority,
                    control_mode=allocation.control_mode.value,
                    target_units=allocation.target_units,
                    target_capacity=None if allocation.target_capacity is None else self._capacity_row(allocation.target_capacity),
                    active_units=sim.transport.transport_active_units(allocation.id),
                    required_units=snapshot.required_units,
                    unfilled_units=snapshot.unfilled_units,
                    nominal=self._capacity_row(snapshot.nominal),
                    available=self._capacity_row(snapshot.available),
                    used=self._capacity_row(snapshot.used),
                    spare=self._capacity_row(snapshot.spare),
                    utilization=snapshot.utilization,
                    path=None if allocation.path is None else tuple(str(movement_plan_id) for movement_plan_id in allocation.path),
                    path_policy=allocation.path_policy.value,
                    paused=allocation.paused,
                    cycle_days=plan.cycle_days,
                    forward_latency_days=plan.forward_latency_days,
                    reverse_latency_days=plan.reverse_latency_days,
                    operational_supply=tuple(
                        (str(location), str(resource_id), amount)
                        for location, resource_id, amount in snapshot.operational_supply
                    ),
                    infrastructure_requirements=infrastructure_requirement_rows(plan),
                    blockers=snapshot.blockers,
                    limiting_factors=snapshot.limiting_factors,
                )
            )
        return tuple(rows)

    def _cargo_flow_rows(self) -> tuple[CargoFlowRow, ...]:
        sim = self._simulation
        rows: list[CargoFlowRow] = []
        for flow in sorted(sim.logistics.cargo_flow_snapshots(), key=lambda row: str(row.id)):
            legs = (flow.leg,) + flow.remaining_legs
            rows.append(CargoFlowRow(
                id=str(flow.id), resource_id=str(flow.resource_id), amount_t=flow.amount_t,
                source_id=str(flow.source_id), destination_id=str(flow.destination_id),
                requirement_id=None if flow.requirement_id is None else str(flow.requirement_id),
                owner_kind=flow.owner_kind, owner_id=str(flow.owner_id), priority=flow.priority,
                service_ids=tuple(leg.service_identity for leg in legs),
                service_destinations=tuple(str(leg.destination_id) for leg in legs),
                departure_day=flow.dispatch_start_day, ready_day=flow.first_arrival_day,
                status="in_transit",
                final_destination_id=str(flow.final_destination_id),
                dispatch_end_day=flow.dispatch_end_day,
                dispatch_rate_t_per_day=flow.dispatch_rate_t_per_day,
                latency_days=flow.latency_days,
            ))
        for waiting in sorted(
            sim.logistics.arrival_waiting_snapshots(), key=lambda row: str(row.id)
        ):
            legs = (waiting.arrival_leg,) + waiting.remaining_legs
            rows.append(CargoFlowRow(
                id=str(waiting.id), resource_id=str(waiting.resource_id), amount_t=waiting.amount_t,
                source_id=str(waiting.arrival_leg.source_id), destination_id=str(waiting.node_id),
                requirement_id=None if waiting.requirement_id is None else str(waiting.requirement_id),
                owner_kind=waiting.owner_kind, owner_id=str(waiting.owner_id), priority=waiting.priority,
                service_ids=tuple(leg.service_identity for leg in legs),
                service_destinations=tuple(str(leg.destination_id) for leg in legs),
                departure_day=waiting.arrived_day - waiting.arrival_leg.latency_days,
                ready_day=waiting.arrived_day, status="arrival_waiting",
                admission_blockers=sim.inventory.admission_state(
                    waiting.node_id, waiting.resource_id
                ).blockers,
                final_destination_id=str(waiting.final_destination_id),
                latency_days=waiting.arrival_leg.latency_days,
            ))
        for staging in sorted(
            sim.logistics.handoff_staging_snapshots(), key=lambda row: str(row.id)
        ):
            next_leg = staging.next_leg
            rows.append(CargoFlowRow(
                id=str(staging.id), resource_id=str(staging.resource_id), amount_t=staging.amount_t,
                source_id=str(staging.node_id), destination_id=str(next_leg.destination_id),
                requirement_id=None if staging.requirement_id is None else str(staging.requirement_id),
                owner_kind=staging.owner_kind, owner_id=str(staging.owner_id), priority=staging.priority,
                service_ids=tuple(leg.service_identity for leg in staging.remaining_legs),
                service_destinations=tuple(str(leg.destination_id) for leg in staging.remaining_legs),
                departure_day=staging.staged_day, ready_day=staging.staged_day + next_leg.latency_days,
                status="handoff_staged",
                final_destination_id=str(staging.final_destination_id),
                latency_days=next_leg.latency_days,
            ))
        return tuple(sorted(rows, key=lambda row: row.id))

    def _external_supply_rows(self) -> tuple[ExternalSupplyRow, ...]:
        sim = self._simulation
        return tuple(
            ExternalSupplyRow(
                id=str(row.id),
                service_id=str(row.service_id),
                requirement_id=str(row.requirement_id),
                owner_kind=row.owner_kind,
                owner_id=str(row.owner_id),
                supply_node_id=str(row.supply_node_id),
                resource_id=str(row.resource_id),
                amount_t=row.amount_t,
                order_day=row.order_day,
                available_day=row.available_day,
                status=row.status.value,
                admission_blockers=(
                    sim.inventory.admission_state(row.supply_node_id, row.resource_id).blockers
                    if row.status.value == "admission_waiting" else ()
                ),
            )
            for row in sorted(
                sim.logistics.external_supply_snapshots(), key=lambda row: str(row.id)
            )
        )

    def _vehicle_production_option_rows(self) -> tuple[VehicleProductionOptionRow, ...]:
        sim = self._simulation
        powers = self._tick_decision_projection().allocations.power_by_location
        rows: list[VehicleProductionOptionRow] = []
        for definition in sim.transport.vehicle_definitions():
            if definition.production.service_type is None or definition.production.days <= 1e-12:
                continue
            for node in sim.graph.operational_nodes():
                power = powers[node.id]
                blockers = tuple(
                    f"{failure.code}:{failure.detail}"
                    for failure in sim.transport.vehicle_production_site_failures(
                        definition.id, node.id, day=sim.day, power=power
                    )
                )
                plan_failures = sim.transport.vehicle_production_plan_failures(
                    definition.id, node.id, day=sim.day
                )
                rows.append(
                    VehicleProductionOptionRow(
                        vehicle_definition_id=str(definition.id),
                        display_name=definition.display_name,
                        operational_node_id=str(node.id),
                        production_service_type=definition.production.service_type,
                        production_days=definition.production.days,
                        resources=tuple(
                            (str(resource_id), amount)
                            for resource_id, amount in definition.production.resources
                        ),
                        blockers=blockers,
                        can_plan=not plan_failures,
                    )
                )
        return tuple(rows)

    def _vehicle_production_rows(self) -> tuple[VehicleProductionRow, ...]:
        sim = self._simulation
        powers = self._tick_decision_projection().allocations.power_by_location
        rows: list[VehicleProductionRow] = []
        for state in sim.transport.vehicle_production_snapshots():
            definition = self._vehicle_definition(state.vehicle_definition_id)
            power = powers[state.operational_node_id]
            blockers = sim.transport.vehicle_production_blockers(state.id, day=sim.day, power=power)
            remaining_days = max(0.0, definition.production.days - state.progress_days)
            estimated_completion_day = (
                float(sim.day) + remaining_days
                if not state.paused and not blockers and state.phase.value != "complete"
                else float(sim.day) if state.phase.value == "complete" else None
            )
            rows.append(
                VehicleProductionRow(
                    str(state.id), str(state.vehicle_definition_id), definition.display_name,
                    str(state.operational_node_id), state.phase.value, state.paused, state.progress_days,
                    definition.production.days, remaining_days, estimated_completion_day,
                    definition.production.service_type,
                    tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.production.resources),
                    state.priority,
                    sim.transport.vehicle_production_priority_editable(state.id),
                    blockers, state.completed_units,
                )
            )
        return tuple(rows)

    def _fleet_view(self, query) -> FleetView:
        return FleetView(
            self._fleet_pool_rows(
                location_id=query.operational_node_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
            self._fleet_relocation_rows(
                location_id=query.operational_node_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
            self._fleet_release_rows(
                location_id=query.operational_node_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
        )

    def _fleet_relocation_preview_view(self, query) -> FleetRelocationPreviewView:
        sim = self._simulation
        policy = PathPolicy(query.path_policy)
        plan = sim.transport.fleet_relocation_plan(
            DefinitionId(query.vehicle_definition_id),
            int(query.units),
            SpatialNodeId(query.source_id),
            SpatialNodeId(query.destination_id),
            path_policy=policy,
            day=sim.day,
        )
        definition = self._vehicle_definition(plan.vehicle_definition_id)
        return FleetRelocationPreviewView(
            vehicle_definition_id=str(plan.vehicle_definition_id),
            display_name=definition.display_name,
            units=plan.units,
            source_id=str(plan.source_id),
            destination_id=str(plan.destination_id),
            path_policy=policy.value,
            path=tuple(str(movement_plan_id) for movement_plan_id in plan.path),
            travel_days=plan.travel_days,
            departure_day=plan.departure_day,
            arrival_day=plan.arrival_day,
            resource_requirements=tuple(
                FleetRelocationResourceRequirementRow(
                    str(row.operational_node_id),
                    str(row.resource_id),
                    row.required_t,
                    row.available_t,
                )
                for row in plan.resource_requirements
            ),
            infrastructure_requirements=infrastructure_requirement_rows(plan),
            feasible=plan.feasible,
            blockers=plan.blockers,
        )

    def _transport_allocations_view(self) -> TransportAllocationsView:
        return TransportAllocationsView(self._transport_allocation_rows())

    def _cargo_flows_view(self) -> CargoFlowsView:
        return CargoFlowsView(self._cargo_flow_rows())
