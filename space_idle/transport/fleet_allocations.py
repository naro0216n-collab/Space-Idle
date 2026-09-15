from __future__ import annotations

from dataclasses import replace
import math

from ..priority import DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PROVISIONING_PRIORITY, ProvisioningPriority
from ..resource_claim import ResourceAllocationPlan, ResourceClaim
from ..supply import SupplyRequirement
from ..service_capacity import ServiceCapacityRequest
from ..shared import DefinitionId, EntityId, MovementPlanId, SpatialNodeId
from .models import (
    DirectionalCapacity,
    FleetPool,
    FleetPoolSnapshot,
    FleetRelocation,
    FleetRelocationPlan,
    FleetRelocationResourceNeed,
    FleetRelocationResourceRequirement,
    MovementExecutionKind,
    FleetRelease,
    FleetReservation,
    FleetReservationKind,
    FleetReservationSnapshot,
    OperationAssetDisposition,
    OperationSupportLocation,
    PathPolicy,
    TransportAllocation,
    TransportCapacitySnapshot,
    TransportControlMode,
    TransportServiceLeg,
    TransportServicePlan,
)


class FleetAllocationMixin:
    """Aggregate owned-vehicle state and allocation fulfillment.

    Fleet quantity is authoritative. ``free`` is always derived from total units
    minus exclusive commitments; no individual VehicleState participates in this
    accounting.
    """

    def _pool_key(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> tuple[DefinitionId, SpatialNodeId]:
        return vehicle_definition_id, location_id

    def validate_movement_path_structure(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        path: tuple[MovementPlanId, ...],
    ) -> None:
        if not path:
            raise ValueError("transport path must be non-empty")
        node = source_id
        for movement_plan_id in path:
            plan = self.require_movement_plan(movement_plan_id)
            if plan.origin_id != node:
                raise ValueError(
                    f"transport path is discontinuous at {movement_plan_id}: "
                    f"expected origin {node}, got {plan.origin_id}"
                )
            node = plan.destination_id
        if node != destination_id:
            raise ValueError(
                f"transport path ends at {node}, expected {destination_id}"
            )

    def fleet_pool(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> FleetPool:
        key = self._pool_key(vehicle_definition_id, location_id)
        pool = self.fleet_pools.get(key)
        if pool is None:
            pool = FleetPool(vehicle_definition_id, location_id, 0)
            self.fleet_pools[key] = pool
        return pool

    def add_fleet_units(
        self,
        vehicle_definition_id: DefinitionId,
        count: int,
        location_id: SpatialNodeId,
        *,
        day: int = 0,
    ) -> None:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if not self.facilities.environment.graph.has_operational_node(location_id):
            raise KeyError(location_id)
        if count < 0:
            raise ValueError("fleet unit count must be non-negative")
        if count == 0:
            return
        pool = self.fleet_pool(vehicle_definition_id, location_id)
        pool.total_units += count
        # Fleet owns fulfillment. Any transition that creates free units must
        # immediately offer them to existing Transport Allocation targets instead
        # of requiring the producing/owning Domain to know reconciliation rules.
        self.reconcile_fleet_allocations(day)

    @staticmethod
    def _transport_reservation_id(allocation_id: EntityId) -> EntityId:
        return EntityId(f"fleet.transport:{allocation_id}")

    def transport_active_units(self, allocation_id: EntityId) -> int:
        reservation = self.fleet_reservations.get(
            self._transport_reservation_id(allocation_id)
        )
        if reservation is None:
            return 0
        if (
            reservation.kind is not FleetReservationKind.TRANSPORT
            or reservation.owner_id != allocation_id
        ):
            raise RuntimeError(f"invalid transport fleet reservation: {allocation_id}")
        return reservation.units

    def _allocation_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            reservation.units
            for reservation in self.fleet_reservations.values()
            if reservation.kind is FleetReservationKind.TRANSPORT
            and reservation.vehicle_definition_id == vehicle_definition_id
            and reservation.operational_node_id == location_id
        )

    def _reserved_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            reservation.units
            for reservation in self.fleet_reservations.values()
            if reservation.vehicle_definition_id == vehicle_definition_id
            and reservation.operational_node_id == location_id
        )

    def _relocating_units_from(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            relocation.units
            for relocation in self.fleet_relocations.values()
            if relocation.vehicle_definition_id == vehicle_definition_id
            and relocation.source_id == location_id
            and not relocation.started
        )

    def _releasing_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            release.units
            for release in self.fleet_releases.values()
            if release.vehicle_definition_id == vehicle_definition_id
            and release.operational_node_id == location_id
        )

    def fleet_free_units(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        pool = self.fleet_pools.get(self._pool_key(vehicle_definition_id, location_id))
        total_units = 0 if pool is None else pool.total_units
        committed = (
            self._reserved_units_at(vehicle_definition_id, location_id)
            + self._relocating_units_from(vehicle_definition_id, location_id)
            + self._releasing_units_at(vehicle_definition_id, location_id)
        )
        free = total_units - committed
        if free < 0:
            raise RuntimeError(
                f"fleet over-committed: {vehicle_definition_id}/{location_id}: "
                f"total={total_units} committed={committed}"
            )
        return free

    def fleet_reservation_snapshot(
        self, reservation_id: EntityId
    ) -> FleetReservationSnapshot | None:
        reservation = self.fleet_reservations.get(reservation_id)
        if reservation is None:
            return None
        return FleetReservationSnapshot(
            reservation.id,
            reservation.owner_id,
            reservation.kind,
            reservation.vehicle_definition_id,
            reservation.operational_node_id,
            reservation.units,
        )

    def fleet_reservation_snapshots(self) -> tuple[FleetReservationSnapshot, ...]:
        return tuple(
            FleetReservationSnapshot(
                reservation.id,
                reservation.owner_id,
                reservation.kind,
                reservation.vehicle_definition_id,
                reservation.operational_node_id,
                reservation.units,
            )
            for reservation in sorted(
                self.fleet_reservations.values(), key=lambda row: str(row.id)
            )
        )

    def fleet_pool_snapshot(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> FleetPoolSnapshot:
        pool = self.fleet_pools.get(self._pool_key(vehicle_definition_id, location_id))
        total_units = 0 if pool is None else pool.total_units
        transport_units = self._allocation_units_at(vehicle_definition_id, location_id)
        exploration_units = sum(
            reservation.units
            for reservation in self.fleet_reservations.values()
            if reservation.vehicle_definition_id == vehicle_definition_id
            and reservation.operational_node_id == location_id
            and reservation.kind is FleetReservationKind.SCIENTIFIC_EXPLORATION
        )
        reserved_units = self._reserved_units_at(vehicle_definition_id, location_id)
        relocating_units = self._relocating_units_from(vehicle_definition_id, location_id)
        releasing_units = self._releasing_units_at(vehicle_definition_id, location_id)
        return FleetPoolSnapshot(
            vehicle_definition_id, location_id, total_units,
            self.fleet_free_units(vehicle_definition_id, location_id),
            transport_units, exploration_units, max(0, reserved_units - transport_units - exploration_units),
            relocating_units, releasing_units,
        )

    def fleet_campaign_failures(
        self,
        vehicle_definition_id: DefinitionId,
        movement_plan,
        *,
        activity_days: float = 0.0,
        return_to_origin: bool = False,
        minimum_payload_t: float = 0.0,
        required_vehicle_capabilities: tuple[str, ...] = (),
        day: int = 0,
    ) -> tuple[str, ...]:
        """Evaluate a finite Fleet use without exposing Fleet internals to its owner Domain."""
        definition = self.vehicle_defs[vehicle_definition_id]
        failures = list(
            self.performance_movement_failures(movement_plan, definition.performance, day)
        )
        usable_payload_t = definition.max_cargo_for_movement(movement_plan)
        if usable_payload_t + 1e-9 < minimum_payload_t:
            failures.append(f"payload_capacity:{usable_payload_t:g}/{minimum_payload_t:g}")
        vehicle_capabilities = set(definition.generic_capabilities)
        failures.extend(
            f"vehicle_capability:{capability}"
            for capability in sorted(set(required_vehicle_capabilities) - vehicle_capabilities)
        )
        travel_days = self.performance_movement_transit_days(movement_plan, definition.performance)
        if return_to_origin and definition.movement_asset_disposition(movement_plan) is OperationAssetDisposition.DESTINATION:
            try:
                reverse = self._movement_path_for_vehicle(
                    movement_plan.destination_id,
                    movement_plan.origin_id,
                    vehicle_definition_id,
                    day,
                    PathPolicy.FASTEST,
                )
                travel_days += sum(
                    self.performance_movement_transit_days(self.require_movement_plan(movement_plan_id), definition.performance)
                    for movement_plan_id in reverse
                )
            except ValueError as exc:
                failures.append(f"return_path:{exc}")
        failures.extend(definition.endurance_failures(float(travel_days) + max(0.0, activity_days)))
        return tuple(dict.fromkeys(failures))

    def reserve_fleet_units(
        self,
        reservation_id: EntityId,
        owner_id: EntityId,
        kind: FleetReservationKind,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        units: int,
    ) -> None:
        if reservation_id in self.fleet_reservations:
            raise ValueError(f"fleet reservation already exists: {reservation_id}")
        if units <= 0:
            raise ValueError("fleet reservation units must be positive")
        if self.fleet_free_units(vehicle_definition_id, location_id) < units:
            raise ValueError("insufficient free fleet units")
        self.fleet_reservations[reservation_id] = FleetReservation(
            reservation_id,
            owner_id,
            kind,
            vehicle_definition_id,
            location_id,
            units,
        )

    def resize_fleet_reservation(
        self, reservation_id: EntityId, units: int
    ) -> None:
        """Resize an existing exclusive Fleet commitment.

        This is a Fleet-domain state transition. Callers may request a new
        commitment size but never mutate Fleet reservation state directly.
        """
        reservation = self.fleet_reservations.get(reservation_id)
        if reservation is None:
            raise KeyError(reservation_id)
        if units < 0:
            raise ValueError("fleet reservation units must be non-negative")
        if units == reservation.units:
            return
        if units == 0:
            del self.fleet_reservations[reservation_id]
            return
        if units > reservation.units:
            additional = units - reservation.units
            if self.fleet_free_units(
                reservation.vehicle_definition_id, reservation.operational_node_id
            ) < additional:
                raise ValueError("insufficient free fleet units")
        reservation.units = units

    def release_fleet_reservation(
        self, reservation_id: EntityId, *, day: int = 0
    ) -> None:
        if reservation_id not in self.fleet_reservations:
            raise KeyError(reservation_id)
        del self.fleet_reservations[reservation_id]
        # Releasing an exclusive use creates free Fleet. Fulfillment is part of
        # this Fleet-domain state transition, not a responsibility of the caller.
        self.reconcile_fleet_allocations(day)

    def dispatch_fleet_reservation(
        self, reservation_id: EntityId, *, day: int = 0
    ) -> FleetReservationSnapshot:
        """Move an exclusive node reservation into in-transit ownership.

        The Fleet disappears from the source Operational Node at dispatch.  The
        owning MovementExecution then represents those units until a later Boundary
        settlement places them at an Operational Node again.
        """
        reservation = self.fleet_reservations.get(reservation_id)
        if reservation is None:
            raise KeyError(reservation_id)
        source = self.fleet_pool(
            reservation.vehicle_definition_id, reservation.operational_node_id
        )
        if source.total_units < reservation.units:
            raise RuntimeError("fleet reservation exceeds source pool")
        snapshot = FleetReservationSnapshot(
            reservation.id,
            reservation.owner_id,
            reservation.kind,
            reservation.vehicle_definition_id,
            reservation.operational_node_id,
            reservation.units,
        )
        source.total_units -= reservation.units
        del self.fleet_reservations[reservation_id]
        self.reconcile_fleet_allocations(day)
        return snapshot

    def receive_reserved_fleet_units(
        self,
        reservation_id: EntityId,
        owner_id: EntityId,
        kind: FleetReservationKind,
        vehicle_definition_id: DefinitionId,
        location_id: SpatialNodeId,
        units: int,
        *,
        day: int = 0,
    ) -> None:
        """Place arrived in-transit Fleet directly into an exclusive reservation.

        Pool quantity and the exclusive reservation are created atomically so the
        arriving units cannot transiently satisfy an unrelated Transport target.
        """
        if reservation_id in self.fleet_reservations:
            raise ValueError(f"fleet reservation already exists: {reservation_id}")
        if units <= 0:
            raise ValueError("fleet reservation units must be positive")
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if not self.facilities.environment.graph.has_operational_node(location_id):
            raise KeyError(location_id)
        pool = self.fleet_pool(vehicle_definition_id, location_id)
        pool.total_units += units
        self.fleet_reservations[reservation_id] = FleetReservation(
            reservation_id,
            owner_id,
            kind,
            vehicle_definition_id,
            location_id,
            units,
        )
        self.reconcile_fleet_allocations(day)

    def _movement_path_for_vehicle(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId,
        day: int,
        policy: PathPolicy,
        explicit_path: tuple[MovementPlanId, ...] | None = None,
        *,
        require_destination_disposition: bool = False,
    ) -> tuple[MovementPlanId, ...]:
        if explicit_path is not None:
            self.validate_movement_path_structure(source_id, destination_id, explicit_path)
            failures = [
                (movement_plan_id, self.vehicle_movement_physical_failures(movement_plan_id, vehicle_definition_id, day))
                for movement_plan_id in explicit_path
            ]
            bad = [(movement_plan_id, reasons) for movement_plan_id, reasons in failures if reasons]
            if bad:
                detail = "; ".join(
                    f"{movement_plan_id}:{','.join(reasons)}" for movement_plan_id, reasons in bad
                )
                raise ValueError(f"vehicle cannot operate explicit path: {detail}")
            if require_destination_disposition:
                bad_disposition = tuple(
                    movement_plan_id
                    for movement_plan_id in explicit_path
                    if self.vehicle_defs[vehicle_definition_id].movement_asset_disposition(
                        self.require_movement_plan(movement_plan_id)
                    )
                    is not OperationAssetDisposition.DESTINATION
                )
                if bad_disposition:
                    raise ValueError(
                        "fleet relocation path does not move the asset to destination: "
                        + ",".join(str(movement_plan_id) for movement_plan_id in bad_disposition)
                    )
            return explicit_path

        # Dijkstra over physical compatibility only. Current resource/support
        # availability belongs to Available Capacity, not Nominal planning.
        import heapq

        queue: list[tuple[float, tuple[str, ...], SpatialNodeId, tuple[MovementPlanId, ...]]] = [
            (0.0, (), source_id, ())
        ]
        best: dict[SpatialNodeId, tuple[float, tuple[str, ...]]] = {}
        while queue:
            score, key_path, node, path = heapq.heappop(queue)
            prior = best.get(node)
            if prior is not None and prior <= (score, key_path):
                continue
            best[node] = (score, key_path)
            if node == destination_id:
                return path
            for plan in self.outbound_movement_plans(node):
                if self.vehicle_movement_physical_failures(plan.id, vehicle_definition_id, day):
                    continue
                definition = self.vehicle_defs[vehicle_definition_id]
                if (
                    require_destination_disposition
                    and definition.movement_asset_disposition(plan)
                    is not OperationAssetDisposition.DESTINATION
                ):
                    continue
                if policy is PathPolicy.FASTEST:
                    edge = self.performance_movement_transit_days(plan, definition.performance)
                elif policy is PathPolicy.LOWEST_PROPELLANT:
                    edge = definition.propellant_t(plan, max(definition.max_cargo_for_movement(plan), 0.0))
                else:
                    payload = max(definition.max_cargo_for_movement(plan), 1e-9)
                    edge = definition.operating_cost_musd_per_cargo_t + definition.operating_cost_musd_per_cycle / payload
                new_path = path + (plan.id,)
                heapq.heappush(
                    queue,
                    (score + float(edge), tuple(str(r) for r in new_path), plan.destination_id, new_path),
                )
        raise ValueError(f"no physically compatible path {source_id} -> {destination_id}")

    def _vehicle_path_infrastructure_requirements(
        self,
        definition,
        movement_plans: tuple,
        *,
        resource_requirements: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = (),
        servicing_node_id: SpatialNodeId | None = None,
        servicing_rate: float = 0.0,
    ) -> tuple[tuple[SpatialNodeId, str, str], ...]:
        """Project categorical infrastructure requirements for decision surfaces."""
        infrastructure: set[tuple[SpatialNodeId, str, str]] = set()

        def _require(location_id: SpatialNodeId, capability_id: str, required_state: str) -> None:
            infrastructure.add((location_id, capability_id, required_state))

        for movement_plan in movement_plans:
            for location_id, site_requirements in (
                (movement_plan.origin_id, movement_plan.origin_requirements),
                (movement_plan.destination_id, movement_plan.destination_requirements),
            ):
                for requirement in site_requirements.capability_requirements:
                    _require(
                        location_id,
                        requirement.capability_id,
                        requirement.required_state.value,
                    )
            present_operations = {operation.operation_type for operation in movement_plan.operations}
            for support in definition.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    movement_plan.origin_id
                    if support.location is OperationSupportLocation.ORIGIN
                    else movement_plan.destination_id
                )
                _require(location_id, support.capability_id, "ACTIVE")

        for location_id, resource_id, amount in resource_requirements:
            if amount <= 1e-12:
                continue
            for support in definition.resource_support_requirements:
                if support.resource_id == resource_id:
                    _require(location_id, support.infrastructure_capability_id, "ACTIVE")

        return tuple(sorted(infrastructure, key=lambda row: (str(row[0]), row[1], row[2])))

    def derive_transport_service_plan(
        self, allocation_id: EntityId, day: int = 0
    ) -> TransportServicePlan:
        return self._derive_transport_service_plan(
            self.transport_allocations[allocation_id], day
        )

    def transport_service_plan_for(
        self,
        vehicle_definition_id: DefinitionId,
        anchor_node_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        day: int = 0,
        path: tuple[MovementPlanId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
    ) -> TransportServicePlan:
        """Derive a deterministic service plan without creating authoritative state."""
        preview = TransportAllocation(
            id=EntityId(
                f"transport.service.preview:{vehicle_definition_id}:{anchor_node_id}:{destination_id}:{path_policy.value}"
            ),
            vehicle_definition_id=vehicle_definition_id,
            anchor_node_id=anchor_node_id,
            destination_id=destination_id,
            provisioning_priority=DEFAULT_PROVISIONING_PRIORITY,
            control_mode=TransportControlMode.UNITS,
            target_units=0,
            path=path,
            path_policy=path_policy,
            paused=False,
        )
        return self._derive_transport_service_plan(preview, day)

    def _derive_transport_service_plan(
        self, allocation: TransportAllocation, day: int
    ) -> TransportServicePlan:
        definition = self.vehicle_defs[allocation.vehicle_definition_id]
        blockers: list[str] = []
        try:
            forward = self._movement_path_for_vehicle(
                allocation.anchor_node_id,
                allocation.destination_id,
                allocation.vehicle_definition_id,
                day,
                allocation.path_policy,
                allocation.path,
            )
        except ValueError as exc:
            return TransportServicePlan(
                allocation.id,
                allocation.vehicle_definition_id,
                allocation.anchor_node_id,
                allocation.destination_id,
                (), (), (), 0.0, definition.turnaround_days, 0.0, 0.0, 0, None,
                DirectionalCapacity(), blockers=(f"service_plan:{exc}",),
            )

        if not forward:
            raise ValueError("transport service path must be non-empty")

        forward_plans = tuple(self.require_movement_plan(movement_plan_id) for movement_plan_id in forward)
        for index, movement_plan in enumerate(forward_plans):
            blockers.extend(self.movement_plan_failures(movement_plan.id, day))
            blockers.extend(
                self.vehicle_movement_failures(
                    movement_plan.id, allocation.vehicle_definition_id, day
                )
            )
            if (
                index < len(forward_plans) - 1
                and definition.movement_asset_disposition(movement_plan)
                is not OperationAssetDisposition.DESTINATION
            ):
                blockers.append(
                    f"asset_position:{movement_plan.id}:cannot_continue_to_next_movement_plan"
                )
        forward_days = sum(
            self.performance_movement_transit_days(movement_plan, definition.performance)
            for movement_plan in forward_plans
        )
        forward_payload = min(definition.max_cargo_for_movement(movement_plan) for movement_plan in forward_plans)
        if forward_payload <= 1e-12:
            blockers.append("payload_capacity")

        # A movement_plan whose operation returns the asset to its origin already closes
        # the service cycle. Otherwise the same Fleet unit needs a physical
        # reverse path to become reusable at its anchor.
        final_disposition = definition.movement_asset_disposition(forward_plans[-1])
        reverse: tuple[MovementPlanId, ...] = ()
        reverse_plans: tuple = ()
        reverse_days = 0
        reverse_payload = 0.0
        if final_disposition is OperationAssetDisposition.DESTINATION:
            try:
                reverse = self._movement_path_for_vehicle(
                    allocation.destination_id,
                    allocation.anchor_node_id,
                    allocation.vehicle_definition_id,
                    day,
                    allocation.path_policy,
                )
                reverse_plans = tuple(self.require_movement_plan(movement_plan_id) for movement_plan_id in reverse)
                for index, movement_plan in enumerate(reverse_plans):
                    blockers.extend(self.movement_plan_failures(movement_plan.id, day))
                    blockers.extend(
                        self.vehicle_movement_failures(
                            movement_plan.id, allocation.vehicle_definition_id, day
                        )
                    )
                    if (
                        index < len(reverse_plans) - 1
                        and definition.movement_asset_disposition(movement_plan)
                        is not OperationAssetDisposition.DESTINATION
                    ):
                        blockers.append(
                            f"asset_position:{movement_plan.id}:cannot_continue_to_next_movement_plan"
                        )
                reverse_days = sum(
                    self.performance_movement_transit_days(movement_plan, definition.performance)
                    for movement_plan in reverse_plans
                )
                reverse_payload = min(
                    (definition.max_cargo_for_movement(movement_plan) for movement_plan in reverse_plans),
                    default=0.0,
                )
            except ValueError as exc:
                blockers.append(f"return_path:{exc}")

        operating_days = float(forward_days + reverse_days)
        blockers.extend(definition.endurance_failures(operating_days))
        cycle_days = operating_days + max(0.0, definition.turnaround_days)
        if cycle_days <= 1e-12:
            blockers.append("cycle_duration")

        legs: list[TransportServiceLeg] = []
        empty_resource_per_cycle: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        forward_increment_per_cycle: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        reverse_increment_per_cycle: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for direction, movement_plans, service_payload in (
            ("forward", forward_plans, forward_payload),
            ("reverse", reverse_plans, reverse_payload),
        ):
            for movement_plan in movement_plans:
                payload = max(0.0, service_payload)
                empty_propellant = definition.propellant_t(movement_plan, 0.0)
                loaded_propellant = definition.propellant_t(movement_plan, payload)
                legs.append(
                    TransportServiceLeg(
                        movement_plan.id,
                        direction,
                        True,
                        payload,
                        self.performance_movement_transit_days(movement_plan, definition.performance),
                        loaded_propellant,
                    )
                )
                if definition.propellant_resource_id is not None:
                    resource_key = (movement_plan.origin_id, definition.propellant_resource_id)
                    empty_resource_per_cycle[resource_key] = (
                        empty_resource_per_cycle.get(resource_key, 0.0) + empty_propellant
                    )
                    increment = max(0.0, loaded_propellant - empty_propellant)
                    target = forward_increment_per_cycle if direction == "forward" else reverse_increment_per_cycle
                    target[resource_key] = target.get(resource_key, 0.0) + increment

        # Turnaround/maintenance resources are cycle-rate costs independent of
        # which direction carries payload. They are therefore part of the empty
        # cycle baseline rather than either directional payload increment.
        for resource_id, amount in definition.turnaround_resources:
            key = (allocation.anchor_node_id, resource_id)
            empty_resource_per_cycle[key] = empty_resource_per_cycle.get(key, 0.0) + amount

        nominal = DirectionalCapacity(
            0.0 if cycle_days <= 1e-12 else forward_payload / cycle_days,
            0.0 if cycle_days <= 1e-12 else reverse_payload / cycle_days,
        )

        def _per_day(values: dict[tuple[SpatialNodeId, DefinitionId], float]):
            if cycle_days <= 1e-12:
                return ()
            return tuple(
                sorted(
                    ((location_id, resource_id, amount / cycle_days)
                     for (location_id, resource_id), amount in values.items() if amount > 1e-12),
                    key=lambda row: (str(row[0]), str(row[1])),
                )
            )

        empty_resources = _per_day(empty_resource_per_cycle)
        forward_increment_resources = _per_day(forward_increment_per_cycle)
        reverse_increment_resources = _per_day(reverse_increment_per_cycle)
        full_resource_per_cycle = dict(empty_resource_per_cycle)
        for values in (forward_increment_per_cycle, reverse_increment_per_cycle):
            for key, amount in values.items():
                full_resource_per_cycle[key] = full_resource_per_cycle.get(key, 0.0) + amount
        resources = _per_day(full_resource_per_cycle)
        servicing = 0.0 if cycle_days <= 1e-12 else 1.0 / cycle_days

        infrastructure_requirements = self._vehicle_path_infrastructure_requirements(
            definition,
            (*forward_plans, *reverse_plans),
            resource_requirements=resources,
            servicing_node_id=allocation.anchor_node_id,
            servicing_rate=servicing,
        )
        return TransportServicePlan(
            allocation.id,
            allocation.vehicle_definition_id,
            allocation.anchor_node_id,
            allocation.destination_id,
            forward,
            reverse,
            tuple(legs),
            cycle_days,
            max(0.0, definition.turnaround_days),
            max(0.0, forward_payload),
            max(0.0, reverse_payload),
            int(forward_days),
            None if not reverse else int(reverse_days),
            nominal,
            resources,
            servicing,
            infrastructure_requirements,
            tuple(dict.fromkeys(blockers)),
            empty_resources,
            forward_increment_resources,
            reverse_increment_resources,
        )

    @staticmethod
    def _units_for_capacity(
        target: DirectionalCapacity, nominal_per_unit: DirectionalCapacity
    ) -> int:
        ratios: list[float] = []
        if target.forward_t_per_day > 1e-12:
            if nominal_per_unit.forward_t_per_day <= 1e-12:
                raise ValueError("forward capacity target requires a cargo-capable forward service")
            ratios.append(target.forward_t_per_day / nominal_per_unit.forward_t_per_day)
        if target.reverse_t_per_day > 1e-12:
            if nominal_per_unit.reverse_t_per_day <= 1e-12:
                raise ValueError("reverse capacity target requires a cargo-capable reverse service")
            ratios.append(target.reverse_t_per_day / nominal_per_unit.reverse_t_per_day)
        return 0 if not ratios else int(math.ceil(max(ratios) - 1e-12))

    def allocation_required_units(self, allocation_id: EntityId, day: int = 0) -> int:
        allocation = self.transport_allocations[allocation_id]
        if allocation.control_mode is TransportControlMode.UNITS:
            return int(allocation.target_units or 0)
        plan = self.derive_transport_service_plan(allocation_id, day)
        assert allocation.target_capacity is not None
        return self._units_for_capacity(allocation.target_capacity, plan.nominal_per_unit)

    def create_transport_allocation(
        self,
        vehicle_definition_id: DefinitionId,
        anchor_node_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        provisioning_priority: ProvisioningPriority = DEFAULT_PROVISIONING_PRIORITY,
        control_mode: TransportControlMode = TransportControlMode.UNITS,
        target_units: int | None = 0,
        target_capacity: DirectionalCapacity | None = None,
        path: tuple[MovementPlanId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        paused: bool = False,
        day: int = 0,
    ) -> EntityId:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if not self.facilities.environment.graph.has_operational_node(anchor_node_id):
            raise KeyError(anchor_node_id)
        if not self.facilities.environment.graph.has_operational_node(destination_id):
            raise KeyError(destination_id)
        self._transport_allocation_counter += 1
        allocation_id = EntityId(f"transport.allocation.{self._transport_allocation_counter}")
        allocation = TransportAllocation(
            id=allocation_id,
            vehicle_definition_id=vehicle_definition_id,
            anchor_node_id=anchor_node_id,
            destination_id=destination_id,
            provisioning_priority=provisioning_priority,
            control_mode=control_mode,
            target_units=target_units,
            target_capacity=target_capacity,
            path=path,
            path_policy=path_policy,
            paused=paused,
        )
        self.transport_allocations[allocation_id] = allocation
        try:
            # Reject structurally invalid explicit paths immediately, while allowing
            # allocations whose capacity is temporarily unavailable. CAPACITY targets
            # must also refer only to directions this service can carry cargo.
            plan = self.derive_transport_service_plan(allocation_id, day)
            if control_mode is TransportControlMode.CAPACITY:
                assert target_capacity is not None
                self._units_for_capacity(target_capacity, plan.nominal_per_unit)
            self.reconcile_fleet_allocations(day)
        except Exception:
            self.transport_allocations.pop(allocation_id, None)
            self._transport_allocation_counter -= 1
            raise
        return allocation_id

    def update_transport_allocation(
        self,
        allocation_id: EntityId,
        *,
        provisioning_priority: ProvisioningPriority | None = None,
        target_units: int | None = None,
        target_capacity: DirectionalCapacity | None = None,
        path_policy: PathPolicy | None = None,
        paused: bool | None = None,
        day: int = 0,
    ) -> None:
        current = self.transport_allocations[allocation_id]
        if current.control_mode is TransportControlMode.UNITS:
            if target_capacity is not None:
                raise ValueError("UNITS allocation cannot accept capacity target")
            updated = replace(
                current,
                provisioning_priority=(
                    current.provisioning_priority
                    if provisioning_priority is None
                    else ProvisioningPriority(provisioning_priority)
                ),
                target_units=current.target_units if target_units is None else target_units,
                path_policy=current.path_policy if path_policy is None else path_policy,
                paused=current.paused if paused is None else paused,
            )
        else:
            if target_units is not None:
                raise ValueError("CAPACITY allocation cannot accept unit target")
            updated = replace(
                current,
                provisioning_priority=(
                    current.provisioning_priority
                    if provisioning_priority is None
                    else ProvisioningPriority(provisioning_priority)
                ),
                target_capacity=current.target_capacity if target_capacity is None else target_capacity,
                path_policy=current.path_policy if path_policy is None else path_policy,
                paused=current.paused if paused is None else paused,
            )
        self.transport_allocations[allocation_id] = updated
        try:
            plan = self.derive_transport_service_plan(allocation_id, day)
            if updated.control_mode is TransportControlMode.CAPACITY:
                assert updated.target_capacity is not None
                self._units_for_capacity(updated.target_capacity, plan.nominal_per_unit)
            self.reconcile_fleet_allocations(day)
        except Exception:
            self.transport_allocations[allocation_id] = current
            self.reconcile_fleet_allocations(day)
            raise

    def change_transport_allocation_mode(
        self,
        allocation_id: EntityId,
        mode: TransportControlMode,
        *,
        day: int = 0,
    ) -> None:
        current = self.transport_allocations[allocation_id]
        if current.control_mode is mode:
            return
        plan = self.derive_transport_service_plan(allocation_id, day)
        if mode is TransportControlMode.CAPACITY:
            # Mode conversion preserves the player's authoritative UNITS target,
            # not the currently fulfilled Fleet quantity. Temporary Fleet scarcity
            # must not silently rewrite intent during a control-mode change.
            units = int(current.target_units or 0)
            target = DirectionalCapacity(
                plan.nominal_per_unit.forward_t_per_day * units,
                plan.nominal_per_unit.reverse_t_per_day * units,
            )
            updated = replace(
                current,
                control_mode=mode,
                target_units=None,
                target_capacity=target,
            )
        else:
            assert current.target_capacity is not None
            units = self._units_for_capacity(current.target_capacity, plan.nominal_per_unit)
            updated = replace(
                current,
                control_mode=mode,
                target_units=units,
                target_capacity=None,
            )
        self.transport_allocations[allocation_id] = updated
        self.reconcile_fleet_allocations(day)

    def delete_transport_allocation(self, allocation_id: EntityId, *, day: int = 0) -> None:
        allocation = self.transport_allocations[allocation_id]
        active_units = self.transport_active_units(allocation_id)
        if active_units > 0 and allocation.last_operated_day is not None:
            self._new_release(allocation, active_units, day)
        reservation_id = self._transport_reservation_id(allocation_id)
        if reservation_id in self.fleet_reservations:
            self.resize_fleet_reservation(reservation_id, 0)
        del self.transport_allocations[allocation_id]
        self.reconcile_fleet_allocations(day)

    def _new_release(
        self, allocation: TransportAllocation, units: int, day: int
    ) -> None:
        if units <= 0:
            return
        plan = self.derive_transport_service_plan(allocation.id, day)
        self._fleet_release_counter += 1
        release_id = EntityId(f"fleet.release.{self._fleet_release_counter}")
        cycle_days = max(1, int(math.ceil(max(plan.cycle_days, 1.0))))
        last_operated_day = allocation.last_operated_day
        if last_operated_day is None:
            return
        recovery_day = last_operated_day + cycle_days
        if recovery_day <= day:
            return
        self.fleet_releases[release_id] = FleetRelease(
            release_id,
            allocation.id,
            allocation.vehicle_definition_id,
            allocation.anchor_node_id,
            units,
            recovery_day,
        )

    def advance_fleet_state(self, day: int) -> None:
        # Release recovery completes without changing pool totals.
        for release_id in sorted(
            [rid for rid, row in self.fleet_releases.items() if row.release_day <= day],
            key=str,
        ):
            del self.fleet_releases[release_id]

        # Started relocations are owned by MovementExecution while in transit.
        # Boundary completion places the units at the destination pool.
        for relocation_id in sorted(self.fleet_relocations, key=str):
            relocation = self.fleet_relocations[relocation_id]
            execution_id = relocation.movement_execution_id
            if execution_id is None:
                continue
            execution = self.movement_executions.get(execution_id)
            if execution is None:
                raise RuntimeError(f"fleet relocation missing movement execution: {relocation_id}")
            if execution.completion_day > day:
                continue
            self.finish_movement_execution(execution_id)
            relocation = self.fleet_relocations.pop(relocation_id)
            self.fleet_pool(
                relocation.vehicle_definition_id, relocation.destination_id
            ).total_units += relocation.units
        self.reconcile_fleet_allocations(day)

    def fleet_relocation_plan(
        self,
        vehicle_definition_id: DefinitionId,
        units: int,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        path: tuple[MovementPlanId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        day: int = 0,
    ) -> FleetRelocationPlan:
        """Derive the exact decision contract used to start a Fleet relocation."""
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if not self.facilities.environment.graph.has_operational_node(source_id):
            raise KeyError(source_id)
        if not self.facilities.environment.graph.has_operational_node(destination_id):
            raise KeyError(destination_id)

        blockers: list[str] = []
        if units <= 0:
            blockers.append("relocation_units:positive_required")
        if source_id == destination_id:
            blockers.append("relocation_endpoints:must_differ")

        free_units = self.fleet_free_units(vehicle_definition_id, source_id)
        if units > 0 and free_units < units:
            blockers.append(f"fleet_units:{free_units}/{units}")

        movement_plan_path: tuple[MovementPlanId, ...] = ()
        if source_id != destination_id:
            try:
                movement_plan_path = self._movement_path_for_vehicle(
                    source_id,
                    destination_id,
                    vehicle_definition_id,
                    day,
                    path_policy,
                    path,
                    require_destination_disposition=True,
                )
            except ValueError as exc:
                blockers.append(f"relocation_path:{exc}")
        if not movement_plan_path and source_id != destination_id and not any(
            row.startswith("relocation_path:") for row in blockers
        ):
            blockers.append("relocation_path:empty")

        definition = self.vehicle_defs[vehicle_definition_id]
        movement_plans = tuple(self.require_movement_plan(movement_plan_id) for movement_plan_id in movement_plan_path)
        propellant_requirements: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        if movement_plan_path:
            for movement_plan in movement_plans:
                blockers.extend(self.movement_plan_failures(movement_plan.id, day))
                blockers.extend(
                    self.vehicle_movement_failures(movement_plan.id, vehicle_definition_id, day)
                )
                if definition.propellant_resource_id is not None and units > 0:
                    amount = definition.propellant_t(movement_plan, 0.0) * units
                    if amount > 1e-12:
                        blockers.extend(
                            self.resource_support_failures(
                                definition.performance,
                                movement_plan.origin_id,
                                definition.propellant_resource_id,
                                day,
                            )
                        )
                        key = (movement_plan.origin_id, definition.propellant_resource_id)
                        propellant_requirements[key] = (
                            propellant_requirements.get(key, 0.0) + amount
                        )

        resource_requirements: list[FleetRelocationResourceRequirement] = []
        for (location_id, resource_id), amount in sorted(
            propellant_requirements.items(),
            key=lambda row: (str(row[0][0]), str(row[0][1])),
        ):
            available = self.inventory.available(location_id, resource_id)
            resource_requirements.append(
                FleetRelocationResourceRequirement(
                    location_id, resource_id, amount, available
                )
            )
            if available + 1e-9 < amount:
                blockers.append(
                    f"resource:{location_id}:{resource_id}:{available:g}/{amount:g}"
                )

        travel_days = sum(
            self.performance_movement_transit_days(movement_plan, definition.performance)
            for movement_plan in movement_plans
        )
        if movement_plan_path:
            blockers.extend(definition.endurance_failures(float(travel_days)))
        arrival_day = day + max(1, int(math.ceil(travel_days))) if movement_plan_path else None
        infrastructure_requirements = self._vehicle_path_infrastructure_requirements(
            definition,
            movement_plans,
            resource_requirements=tuple(
                (row.operational_node_id, row.resource_id, row.required_t)
                for row in resource_requirements
            ),
        )
        return FleetRelocationPlan(
            vehicle_definition_id=vehicle_definition_id,
            units=units,
            source_id=source_id,
            destination_id=destination_id,
            path=movement_plan_path,
            travel_days=int(travel_days),
            departure_day=day,
            arrival_day=arrival_day,
            resource_requirements=tuple(resource_requirements),
            infrastructure_requirements=infrastructure_requirements,
            blockers=tuple(dict.fromkeys(blockers)),
        )

    def relocate_fleet(
        self,
        vehicle_definition_id: DefinitionId,
        units: int,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        path: tuple[MovementPlanId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        day: int = 0,
    ) -> EntityId:
        plan = self.fleet_relocation_plan(
            vehicle_definition_id,
            units,
            source_id,
            destination_id,
            path=path,
            path_policy=path_policy,
            day=day,
        )
        # Inventory shortage is resolved by the shared Resource Claim allocator,
        # not by command ordering. Structural/operational blockers still reject
        # the relocation intent immediately.
        blockers = tuple(
            blocker for blocker in plan.blockers if not blocker.startswith("resource:")
        )
        if blockers:
            raise ValueError(
                "fleet relocation is not operationally feasible: "
                + "; ".join(blockers)
            )
        if not plan.path or plan.travel_days <= 0:
            raise ValueError("fleet relocation has no executable movement path")
        self._fleet_relocation_counter += 1
        relocation_id = EntityId(f"fleet.relocation.{self._fleet_relocation_counter}")
        needs = tuple(
            FleetRelocationResourceNeed(
                row.operational_node_id, row.resource_id, row.required_t
            )
            for row in plan.resource_requirements
            if row.required_t > 1e-12
        )
        self.fleet_relocations[relocation_id] = FleetRelocation(
            relocation_id,
            vehicle_definition_id,
            units,
            source_id,
            destination_id,
            day,
            plan.path,
            needs,
        )
        return relocation_id

    @staticmethod
    def _relocation_claim_id(
        relocation_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(
            f"claim.fleet_relocation:{relocation_id}:{operational_node_id}:{resource_id}"
        )

    @staticmethod
    def _relocation_requirement_id(
        relocation_id: EntityId, operational_node_id: SpatialNodeId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(
            f"requirement.fleet_relocation:{relocation_id}:{operational_node_id}:{resource_id}"
        )

    def fleet_relocation_resource_claims(self, day: int) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for relocation in sorted(self.fleet_relocations.values(), key=lambda row: str(row.id)):
            if relocation.started:
                continue
            for need in relocation.resource_needs:
                staged = self.inventory.staged_for(
                    relocation.id, need.operational_node_id, need.resource_id
                )
                missing = max(0.0, need.required_t - staged)
                if missing <= 1e-12:
                    continue
                claims.append(ResourceClaim(
                    self._relocation_claim_id(
                        relocation.id, need.operational_node_id, need.resource_id
                    ),
                    need.operational_node_id,
                    need.resource_id,
                    missing,
                    relocation.priority,
                    "fleet_relocation",
                    relocation.id,
                    "operation_resource",
                ))
        return tuple(claims)

    def fleet_relocation_supplys(self, day: int) -> tuple[SupplyRequirement, ...]:
        requirements: list[SupplyRequirement] = []
        for relocation in sorted(self.fleet_relocations.values(), key=lambda row: str(row.id)):
            if relocation.started:
                continue
            for need in relocation.resource_needs:
                staged = self.inventory.staged_for(
                    relocation.id, need.operational_node_id, need.resource_id
                )
                missing = max(0.0, need.required_t - staged)
                if missing <= 1e-12:
                    continue
                requirements.append(SupplyRequirement(
                    self._relocation_requirement_id(
                        relocation.id, need.operational_node_id, need.resource_id
                    ),
                    "fleet_relocation",
                    relocation.id,
                    need.operational_node_id,
                    need.resource_id,
                    missing,
                    relocation.priority,
                ))
        return tuple(requirements)

    def advance_fleet_relocations(
        self, allocations: ResourceAllocationPlan, day: int
    ) -> None:
        for relocation in sorted(self.fleet_relocations.values(), key=lambda row: str(row.id)):
            if relocation.started:
                continue
            for need in relocation.resource_needs:
                claim_id = self._relocation_claim_id(
                    relocation.id, need.operational_node_id, need.resource_id
                )
                try:
                    amount = allocations.allocated(claim_id)
                except KeyError:
                    amount = 0.0
                if amount > 1e-12:
                    self.inventory.stage_allocated(
                        relocation.id, need.operational_node_id, need.resource_id, amount
                    )
            ready = all(
                self.inventory.staged_for(
                    relocation.id, need.operational_node_id, need.resource_id
                ) + 1e-9 >= need.required_t
                for need in relocation.resource_needs
            )
            if not ready:
                continue
            for need in relocation.resource_needs:
                self.inventory.release_storage_occupancy(
                    relocation.id, need.operational_node_id, need.resource_id, need.required_t
                )
            execution_id = EntityId(f"movement.fleet_relocation:{relocation.id}")
            execution = self.start_movement_execution_for_path(
                execution_id,
                relocation.id,
                MovementExecutionKind.FLEET_RELOCATION,
                relocation.vehicle_definition_id,
                relocation.units,
                relocation.path,
                day=day,
            )
            if execution.destination.operational_node_id != relocation.destination_id:
                self.finish_movement_execution(execution_id)
                raise RuntimeError("fleet relocation MovementExecution destination mismatch")
            source = self.fleet_pool(
                relocation.vehicle_definition_id, relocation.source_id
            )
            if source.total_units < relocation.units:
                self.finish_movement_execution(execution_id)
                raise RuntimeError("fleet relocation exceeds source pool")
            source.total_units -= relocation.units
            relocation.movement_execution_id = execution_id


    @staticmethod
    def _allocation_order_key(allocation: TransportAllocation) -> tuple:
        """Stable same-priority ordering derived from authoritative allocation state."""
        if allocation.control_mode is TransportControlMode.UNITS:
            target_key = (int(allocation.target_units or 0), 0.0, 0.0)
        else:
            target = allocation.target_capacity or DirectionalCapacity()
            target_key = (0, target.forward_t_per_day, target.reverse_t_per_day)
        return (
            -allocation.provisioning_priority,
            str(allocation.vehicle_definition_id),
            str(allocation.anchor_node_id),
            str(allocation.destination_id),
            tuple(str(movement_plan_id) for movement_plan_id in (allocation.path or ())),
            allocation.path_policy.value,
            allocation.control_mode.value,
            target_key,
        )

    def reconcile_fleet_allocations(self, day: int = 0) -> None:
        """Fulfill Transport targets through Fleet-owned reservations.

        Transport owns target intent and priority. Fleet owns the exclusive unit
        commitment.  Reconciliation therefore computes desired commitments from
        Transport state, then changes only Fleet reservation/release state through
        Fleet-domain operations.
        """
        groups: dict[tuple[DefinitionId, SpatialNodeId], list[TransportAllocation]] = {}
        for allocation in self.transport_allocations.values():
            groups.setdefault(
                (allocation.vehicle_definition_id, allocation.anchor_node_id), []
            ).append(allocation)

        for (definition_id, location_id), rows in sorted(
            groups.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            pool = self.fleet_pool(definition_id, location_id)
            non_transport = (
                sum(
                    reservation.units
                    for reservation in self.fleet_reservations.values()
                    if reservation.kind is not FleetReservationKind.TRANSPORT
                    and reservation.vehicle_definition_id == definition_id
                    and reservation.operational_node_id == location_id
                )
                + self._relocating_units_from(definition_id, location_id)
                + self._releasing_units_at(definition_id, location_id)
            )
            allocatable = max(0, pool.total_units - non_transport)
            desired: dict[EntityId, int] = {}
            remaining = allocatable
            ordered = sorted(rows, key=self._allocation_order_key)
            for allocation in ordered:
                required = (
                    0
                    if allocation.paused
                    else self.allocation_required_units(allocation.id, day)
                )
                grant = min(required, remaining)
                desired[allocation.id] = grant
                remaining -= grant

            # First shrink displaced commitments. Recovery remains a Fleet
            # commitment when recently operated, so shrinking never teleports a
            # unit into the free pool.
            for allocation in ordered:
                current_units = self.transport_active_units(allocation.id)
                target_active = desired[allocation.id]
                if current_units <= target_active:
                    continue
                delta = current_units - target_active
                if allocation.last_operated_day is not None:
                    self._new_release(allocation, delta, day)
                reservation_id = self._transport_reservation_id(allocation.id)
                self.resize_fleet_reservation(reservation_id, target_active)

            # Newly created releases still consume Fleet ownership. Fill target
            # deficits only from the actual free pool.
            free = self.fleet_free_units(definition_id, location_id)
            for allocation in ordered:
                current_units = self.transport_active_units(allocation.id)
                target_active = desired[allocation.id]
                if current_units >= target_active or free <= 0:
                    continue
                delta = min(target_active - current_units, free)
                reservation_id = self._transport_reservation_id(allocation.id)
                if current_units == 0:
                    self.reserve_fleet_units(
                        reservation_id,
                        allocation.id,
                        FleetReservationKind.TRANSPORT,
                        definition_id,
                        location_id,
                        delta,
                    )
                else:
                    self.resize_fleet_reservation(
                        reservation_id, current_units + delta
                    )
                free -= delta

        # Remove stale Transport reservations whose Allocation no longer exists.
        for reservation_id, reservation in tuple(self.fleet_reservations.items()):
            if (
                reservation.kind is FleetReservationKind.TRANSPORT
                and reservation.owner_id not in self.transport_allocations
            ):
                raise RuntimeError(
                    f"orphan transport fleet reservation: {reservation.owner_id}"
                )

    def record_transport_operation(self, allocation_id: EntityId, day: int) -> None:
        """Record Transport activity through the Transport-owned state contract."""
        allocation = self.transport_allocations[allocation_id]
        if self.transport_active_units(allocation_id) <= 0:
            raise RuntimeError(
                f"cannot record operation for unfulfilled transport allocation: {allocation_id}"
            )
        allocation.last_operated_day = day

    @staticmethod
    def transport_service_request_id(allocation_id: EntityId) -> EntityId:
        return EntityId(f"service.transport_turnaround:{allocation_id}")

    def transport_service_capacity_requests(
        self,
        day: int,
        planned_usage: tuple[tuple[EntityId, DirectionalCapacity], ...],
    ) -> tuple[ServiceCapacityRequest, ...]:
        usage_by_allocation = dict(planned_usage)
        requests: list[ServiceCapacityRequest] = []
        for allocation in sorted(
            self.transport_allocations.values(), key=lambda row: str(row.id)
        ):
            if allocation.paused or self.transport_active_units(allocation.id) <= 0:
                continue
            definition = self.vehicle_defs[allocation.vehicle_definition_id]
            service_type = definition.turnaround_service_type
            if service_type is None:
                continue
            plan = self.derive_transport_service_plan(allocation.id, day)
            usage = usage_by_allocation.get(allocation.id, DirectionalCapacity())
            nominal_forward = (
                plan.nominal_per_unit.forward_t_per_day * self.transport_active_units(allocation.id)
            )
            nominal_reverse = (
                plan.nominal_per_unit.reverse_t_per_day * self.transport_active_units(allocation.id)
            )
            forward_util = (
                0.0
                if nominal_forward <= 1e-12
                else min(1.0, max(0.0, usage.forward_t_per_day / nominal_forward))
            )
            reverse_util = (
                0.0
                if nominal_reverse <= 1e-12
                else min(1.0, max(0.0, usage.reverse_t_per_day / nominal_reverse))
            )
            utilization = max(forward_util, reverse_util)
            requested = (
                plan.servicing_units_per_full_utilization_day
                * self.transport_active_units(allocation.id)
                * utilization
            )
            if requested <= 1e-12:
                continue
            requests.append(
                ServiceCapacityRequest(
                    self.transport_service_request_id(allocation.id),
                    allocation.anchor_node_id,
                    service_type,
                    requested,
                    DEFAULT_ACTIVITY_PRIORITY,
                    "transport",
                    allocation.id,
                    "turnaround_servicing",
                )
            )
        return tuple(requests)

    def transport_capacity_snapshot(
        self,
        allocation_id: EntityId,
        *,
        day: int = 0,
        used: DirectionalCapacity = DirectionalCapacity(),
    ) -> TransportCapacitySnapshot:
        allocation = self.transport_allocations[allocation_id]
        plan = self.derive_transport_service_plan(allocation_id, day)
        required = self.allocation_required_units(allocation_id, day)
        active = self.transport_active_units(allocation_id)
        nominal = DirectionalCapacity(
            plan.nominal_per_unit.forward_t_per_day * active,
            plan.nominal_per_unit.reverse_t_per_day * active,
        )
        limiting: list[str] = []
        blockers = list(plan.blockers)

        # Service-plan blockers are authoritative for whether a sustained
        # service can operate at all.  Nominal remains a design/cycle value,
        # while Available must drop to zero whenever execution would omit the
        # service edge for the same plan.
        forward_ratio = 0.0 if plan.blockers else 1.0
        reverse_ratio = 0.0 if plan.blockers else 1.0

        definition = self.vehicle_defs[allocation.vehicle_definition_id]
        # Operation support is attached to the actual leg endpoint where the
        # operation occurs.  Allocation endpoints are not sufficient for a
        # multi-leg service and would incorrectly skip intermediate support.
        for leg in plan.legs:
            movement_plan = self.require_movement_plan(leg.movement_plan_id)
            present_operations = {operation.operation_type for operation in movement_plan.operations}
            for support in definition.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    movement_plan.origin_id
                    if support.location.value == "origin"
                    else movement_plan.destination_id
                )
                if not self._has_active_capability(location_id, support.capability_id, day):
                    forward_ratio = 0.0
                    reverse_ratio = 0.0
                    limiting.append(f"infrastructure:{location_id}:{support.capability_id}")

        def _resource_map(rows):
            return {(location_id, resource_id): amount for location_id, resource_id, amount in rows}

        empty_resources = _resource_map(plan.resource_t_per_empty_cycle_day)
        forward_increments = _resource_map(plan.resource_t_per_forward_payload_increment_day)
        reverse_increments = _resource_map(plan.resource_t_per_reverse_payload_increment_day)

        # Resource stock is allocated later through shared Resource Claims.
        # Only non-scarcity support prerequisites belong in this physical snapshot.
        required_resource_keys = (
            set(empty_resources) | set(forward_increments) | set(reverse_increments)
        )
        for location_id, resource_id in sorted(
            required_resource_keys, key=lambda row: (str(row[0]), str(row[1]))
        ):
            support_failures = self.resource_support_failures(
                definition.performance, location_id, resource_id, day
            )
            if support_failures:
                forward_ratio = 0.0
                reverse_ratio = 0.0
                limiting.extend(support_failures)

        available = DirectionalCapacity(
            nominal.forward_t_per_day * forward_ratio,
            nominal.reverse_t_per_day * reverse_ratio,
        )
        used_forward = min(used.forward_t_per_day, available.forward_t_per_day)
        used_reverse = min(used.reverse_t_per_day, available.reverse_t_per_day)
        actual_used = DirectionalCapacity(used_forward, used_reverse)
        spare = DirectionalCapacity(
            max(0.0, available.forward_t_per_day - used_forward),
            max(0.0, available.reverse_t_per_day - used_reverse),
        )

        # Operational demand is derived from actual/planned service utilization
        # against Nominal Capacity. Scarce stock is not interpreted here.
        forward_util = 0.0 if nominal.forward_t_per_day <= 1e-12 else used_forward / nominal.forward_t_per_day
        reverse_util = 0.0 if nominal.reverse_t_per_day <= 1e-12 else used_reverse / nominal.reverse_t_per_day
        utilization = max(forward_util, reverse_util)
        operational_map: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for key in set(empty_resources) | set(forward_increments) | set(reverse_increments):
            amount = active * (
                empty_resources.get(key, 0.0) * utilization
                + forward_increments.get(key, 0.0) * forward_util
                + reverse_increments.get(key, 0.0) * reverse_util
            )
            if amount > 1e-12:
                operational_map[key] = amount
        operational = tuple(
            (location_id, resource_id, amount)
            for (location_id, resource_id), amount in sorted(
                operational_map.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
            )
        )
        if active < required:
            blockers.append(f"fleet_unfilled:{required - active}")
        return TransportCapacitySnapshot(
            allocation.id,
            allocation.target_capacity,
            required,
            active,
            max(0, required - active),
            nominal,
            available,
            actual_used,
            spare,
            utilization,
            operational,
            tuple(dict.fromkeys(blockers)),
            tuple(dict.fromkeys(limiting)),
        )
