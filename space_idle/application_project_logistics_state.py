from __future__ import annotations

from .application_views import (
    CargoFlowRow, CargoFlowsView, DirectionalCapacityRow, FleetPoolRow,
    FleetRelocationRow, FleetReleaseRow, FleetView, TransportAllocationRow,
    TransportAllocationsView, VehicleProductionOptionRow, VehicleProductionRow,
)


class LogisticsStateProjectorMixin:
    @staticmethod
    def _capacity_row(value) -> DirectionalCapacityRow:
        return DirectionalCapacityRow(
            value.forward_t_per_day, value.reverse_t_per_day
        )

    def _fleet_pool_rows(
        self,
        *,
        location_id: str | None = None,
        vehicle_definition_id: str | None = None,
    ) -> tuple[FleetPoolRow, ...]:
        sim = self._simulation
        keys = set(sim.logistics.fleet_pools)
        # Allocations/reservations can make a zero-total pool decision-relevant.
        keys.update(
            (row.vehicle_definition_id, row.anchor_location_id)
            for row in sim.logistics.transport_allocations.values()
        )
        keys.update(
            (row.vehicle_definition_id, row.location_id)
            for row in sim.logistics.fleet_reservations.values()
        )
        rows: list[FleetPoolRow] = []
        for definition_id, node_id in sorted(keys, key=lambda row: (str(row[0]), str(row[1]))):
            if location_id is not None and str(node_id) != location_id:
                continue
            if vehicle_definition_id is not None and str(definition_id) != vehicle_definition_id:
                continue
            snapshot = sim.logistics.fleet_pool_snapshot(definition_id, node_id)
            rows.append(
                FleetPoolRow(
                    str(definition_id),
                    sim.logistics.vehicle_defs[definition_id].display_name,
                    str(node_id),
                    snapshot.total_units,
                    snapshot.free_units,
                    snapshot.transport_units,
                    snapshot.exploration_units,
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
                sim.logistics.vehicle_defs[row.vehicle_definition_id].display_name,
                row.units, str(row.source_id), str(row.destination_id),
                row.departure_day, row.arrival_day,
            )
            for row in sorted(sim.logistics.fleet_relocations.values(), key=lambda row: str(row.id))
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
                sim.logistics.vehicle_defs[row.vehicle_definition_id].display_name,
                str(row.location_id),
                row.units,
                row.release_day,
                max(0, row.release_day - sim.day),
            )
            for row in sorted(sim.logistics.fleet_releases.values(), key=lambda row: str(row.id))
            if (location_id is None or str(row.location_id) == location_id)
            and (vehicle_definition_id is None or str(row.vehicle_definition_id) == vehicle_definition_id)
        )

    def _transport_allocation_rows(self) -> tuple[TransportAllocationRow, ...]:
        sim = self._simulation
        rows: list[TransportAllocationRow] = []
        for allocation in sorted(sim.logistics.transport_allocations.values(), key=lambda row: str(row.id)):
            plan = sim.logistics.derive_transport_service_plan(allocation.id, sim.day)
            snapshot = sim.logistics.current_transport_capacity_snapshot(allocation.id, day=sim.day)
            rows.append(
                TransportAllocationRow(
                    id=str(allocation.id),
                    vehicle_definition_id=str(allocation.vehicle_definition_id),
                    display_name=sim.logistics.vehicle_defs[allocation.vehicle_definition_id].display_name,
                    anchor_location_id=str(allocation.anchor_location_id),
                    destination_id=str(allocation.destination_id),
                    priority=allocation.priority,
                    control_mode=allocation.control_mode.value,
                    target_units=allocation.target_units,
                    target_capacity=None if allocation.target_capacity is None else self._capacity_row(allocation.target_capacity),
                    active_units=allocation.active_units,
                    required_units=snapshot.required_units,
                    unfilled_units=snapshot.unfilled_units,
                    nominal=self._capacity_row(snapshot.nominal),
                    available=self._capacity_row(snapshot.available),
                    used=self._capacity_row(snapshot.used),
                    spare=self._capacity_row(snapshot.spare),
                    utilization=snapshot.utilization,
                    path=None if allocation.path is None else tuple(str(route_id) for route_id in allocation.path),
                    path_policy=allocation.path_policy.value,
                    paused=allocation.paused,
                    cycle_days=plan.cycle_days,
                    forward_latency_days=plan.forward_latency_days,
                    reverse_latency_days=plan.reverse_latency_days,
                    operational_resource_demand=tuple(
                        (str(location), str(resource_id), amount)
                        for location, resource_id, amount in snapshot.operational_resource_demand
                    ),
                    blockers=snapshot.blockers,
                    limiting_factors=snapshot.limiting_factors,
                )
            )
        return tuple(rows)

    def _cargo_flow_rows(self) -> tuple[CargoFlowRow, ...]:
        sim = self._simulation
        return tuple(
            CargoFlowRow(
                id=str(flow.id), resource_id=str(flow.resource_id), amount_t=flow.amount_t,
                source_id=str(flow.source_id), destination_id=str(flow.destination_id),
                lane_id=None if flow.lane_id is None else str(flow.lane_id),
                demand_id=None if flow.demand_id is None else str(flow.demand_id),
                owner_kind=flow.owner_kind, owner_id=str(flow.owner_id), priority=flow.priority,
                service_ids=flow.service_ids,
                service_destinations=tuple(str(value) for value in flow.service_destinations),
                departure_day=flow.departure_day, ready_day=flow.ready_day, status=flow.status.value,
            )
            for flow in sorted(sim.logistics.cargo_flows.values(), key=lambda row: str(row.id))
        )

    def _vehicle_production_option_rows(self) -> tuple[VehicleProductionOptionRow, ...]:
        sim = self._simulation
        rows: list[VehicleProductionOptionRow] = []
        for definition in sorted(sim.logistics.vehicle_defs.values(), key=lambda row: str(row.id)):
            if definition.production.capability_id is None or definition.production.days <= 1e-12:
                continue
            for node in sorted(sim.graph.nodes.values(), key=lambda row: str(row.id)):
                power = sim.power.snapshot(node.id, sim.facilities, sim.day)
                blockers = tuple(
                    f"{failure.code}:{failure.detail}"
                    for failure in sim.logistics.vehicle_production_site_failures(
                        definition.id, node.id, day=sim.day, power=power
                    )
                )
                rows.append(
                    VehicleProductionOptionRow(
                        str(definition.id), definition.display_name, str(node.id),
                        definition.production.capability_id, definition.production.days,
                        tuple((str(resource_id), amount) for resource_id, amount in definition.production.resources),
                        blockers,
                    )
                )
        return tuple(rows)

    def _vehicle_production_rows(self) -> tuple[VehicleProductionRow, ...]:
        sim = self._simulation
        rows: list[VehicleProductionRow] = []
        for state in sorted(sim.logistics.vehicle_production_projects.values(), key=lambda row: str(row.id)):
            definition = sim.logistics.vehicle_defs[state.vehicle_definition_id]
            power = sim.power.snapshot(state.location_id, sim.facilities, sim.day)
            blockers = sim.logistics.vehicle_production_blockers(state.id, day=sim.day, power=power)
            remaining_days = max(0.0, definition.production.days - state.progress_days)
            estimated_completion_day = (
                float(sim.day) + remaining_days
                if not state.paused and not blockers and state.phase.value != "complete"
                else float(sim.day) if state.phase.value == "complete" else None
            )
            rows.append(
                VehicleProductionRow(
                    str(state.id), str(state.vehicle_definition_id), definition.display_name,
                    str(state.location_id), state.phase.value, state.paused, state.progress_days,
                    definition.production.days, remaining_days, estimated_completion_day,
                    definition.production.capability_id,
                    tuple((str(resource_id), amount_t) for resource_id, amount_t in definition.production.resources),
                    state.priority, state.allocation_weight,
                    sim.logistics.vehicle_production_priority_editable(state.id),
                    sim.logistics.vehicle_production_allocation_editable(state.id),
                    blockers, state.completed_units,
                )
            )
        return tuple(rows)

    def _fleet_view(self, query) -> FleetView:
        return FleetView(
            self._fleet_pool_rows(
                location_id=query.location_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
            self._fleet_relocation_rows(
                location_id=query.location_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
            self._fleet_release_rows(
                location_id=query.location_id,
                vehicle_definition_id=query.vehicle_definition_id,
            ),
        )

    def _transport_allocations_view(self) -> TransportAllocationsView:
        return TransportAllocationsView(self._transport_allocation_rows())

    def _cargo_flows_view(self) -> CargoFlowsView:
        return CargoFlowsView(self._cargo_flow_rows())
