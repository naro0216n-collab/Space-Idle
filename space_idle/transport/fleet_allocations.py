from __future__ import annotations

from dataclasses import replace
import math

from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import (
    DirectionalCapacity,
    FleetPool,
    FleetPoolSnapshot,
    FleetRelocation,
    FleetRelocationPlan,
    FleetRelocationResourceRequirement,
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

    def validate_path_structure(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        path: tuple[RouteId, ...],
    ) -> None:
        if not path:
            raise ValueError("transport path must be non-empty")
        node = source_id
        for route_id in path:
            route = self.routes[route_id]
            if route.origin_id != node:
                raise ValueError(
                    f"transport path is discontinuous at {route_id}: "
                    f"expected origin {node}, got {route.origin_id}"
                )
            node = route.destination_id
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
        if location_id not in self.facilities.environment.graph.nodes:
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

    def _allocation_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            allocation.active_units
            for allocation in self.transport_allocations.values()
            if allocation.vehicle_definition_id == vehicle_definition_id
            and allocation.anchor_location_id == location_id
        )

    def _reserved_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            reservation.units
            for reservation in self.fleet_reservations.values()
            if reservation.vehicle_definition_id == vehicle_definition_id
            and reservation.location_id == location_id
        )

    def _relocating_units_from(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            relocation.units
            for relocation in self.fleet_relocations.values()
            if relocation.vehicle_definition_id == vehicle_definition_id
            and relocation.source_id == location_id
        )

    def _releasing_units_at(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        return sum(
            release.units
            for release in self.fleet_releases.values()
            if release.vehicle_definition_id == vehicle_definition_id
            and release.location_id == location_id
        )

    def fleet_free_units(
        self, vehicle_definition_id: DefinitionId, location_id: SpatialNodeId
    ) -> int:
        pool = self.fleet_pools.get(self._pool_key(vehicle_definition_id, location_id))
        total_units = 0 if pool is None else pool.total_units
        committed = (
            self._allocation_units_at(vehicle_definition_id, location_id)
            + self._reserved_units_at(vehicle_definition_id, location_id)
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
            reservation.location_id,
            reservation.units,
        )

    def fleet_reservation_snapshots(self) -> tuple[FleetReservationSnapshot, ...]:
        return tuple(
            FleetReservationSnapshot(
                reservation.id,
                reservation.owner_id,
                reservation.kind,
                reservation.vehicle_definition_id,
                reservation.location_id,
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
            and reservation.location_id == location_id
            and reservation.kind is FleetReservationKind.SCIENTIFIC_EXPLORATION
        )
        reserved_units = self._reserved_units_at(vehicle_definition_id, location_id)
        relocating_units = self._relocating_units_from(vehicle_definition_id, location_id)
        releasing_units = self._releasing_units_at(vehicle_definition_id, location_id)
        return FleetPoolSnapshot(
            vehicle_definition_id, location_id, total_units,
            self.fleet_free_units(vehicle_definition_id, location_id),
            transport_units, exploration_units, max(0, reserved_units - exploration_units),
            relocating_units, releasing_units,
        )

    def fleet_campaign_failures(
        self,
        vehicle_definition_id: DefinitionId,
        route,
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
            self.performance_route_failures(route, definition.performance, day)
        )
        usable_payload_t = definition.max_cargo_for_route(route)
        if usable_payload_t + 1e-9 < minimum_payload_t:
            failures.append(f"payload_capacity:{usable_payload_t:g}/{minimum_payload_t:g}")
        vehicle_capabilities = set(definition.generic_capabilities)
        failures.extend(
            f"vehicle_capability:{capability}"
            for capability in sorted(set(required_vehicle_capabilities) - vehicle_capabilities)
        )
        travel_days = max(1, round(route.transit_days * definition.transit_time_multiplier))
        if return_to_origin and definition.route_asset_disposition(route) is OperationAssetDisposition.DESTINATION:
            try:
                reverse = self._route_path_for_vehicle(
                    route.destination_id,
                    route.origin_id,
                    vehicle_definition_id,
                    day,
                    PathPolicy.FASTEST,
                )
                travel_days += sum(
                    max(1, round(self.routes[route_id].transit_days * definition.transit_time_multiplier))
                    for route_id in reverse
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

    def release_fleet_reservation(
        self, reservation_id: EntityId, *, day: int = 0
    ) -> None:
        if reservation_id not in self.fleet_reservations:
            raise KeyError(reservation_id)
        del self.fleet_reservations[reservation_id]
        # Releasing an exclusive use creates free Fleet. Fulfillment is part of
        # this Fleet-domain state transition, not a responsibility of the caller.
        self.reconcile_fleet_allocations(day)

    def complete_fleet_reservation(
        self,
        reservation_id: EntityId,
        *,
        final_location_id: SpatialNodeId | None = None,
        day: int = 0,
    ) -> None:
        """Finish an exclusive Fleet use and atomically place its units.

        Owning domains choose the final location implied by their operation but do
        not mutate Fleet pools.  Releasing the reservation, moving aggregate Fleet
        quantity, and refilling allocation targets are one Fleet-domain transition.
        """
        reservation = self.fleet_reservations.get(reservation_id)
        if reservation is None:
            raise KeyError(reservation_id)
        destination_id = final_location_id or reservation.location_id
        if destination_id not in self.facilities.environment.graph.nodes:
            raise KeyError(destination_id)

        if destination_id != reservation.location_id:
            source = self.fleet_pool(
                reservation.vehicle_definition_id, reservation.location_id
            )
            if source.total_units < reservation.units:
                raise RuntimeError("fleet reservation exceeds source pool")
            source.total_units -= reservation.units
            self.fleet_pool(
                reservation.vehicle_definition_id, destination_id
            ).total_units += reservation.units

        del self.fleet_reservations[reservation_id]
        self.reconcile_fleet_allocations(day)

    def _route_path_for_vehicle(
        self,
        source_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId,
        day: int,
        policy: PathPolicy,
        explicit_path: tuple[RouteId, ...] | None = None,
        *,
        require_destination_disposition: bool = False,
    ) -> tuple[RouteId, ...]:
        if explicit_path is not None:
            self.validate_path_structure(source_id, destination_id, explicit_path)
            failures = [
                (route_id, self.vehicle_route_physical_failures(route_id, vehicle_definition_id, day))
                for route_id in explicit_path
            ]
            bad = [(route_id, reasons) for route_id, reasons in failures if reasons]
            if bad:
                detail = "; ".join(
                    f"{route_id}:{','.join(reasons)}" for route_id, reasons in bad
                )
                raise ValueError(f"vehicle cannot operate explicit path: {detail}")
            if require_destination_disposition:
                bad_disposition = tuple(
                    route_id
                    for route_id in explicit_path
                    if self.vehicle_defs[vehicle_definition_id].route_asset_disposition(
                        self.routes[route_id]
                    )
                    is not OperationAssetDisposition.DESTINATION
                )
                if bad_disposition:
                    raise ValueError(
                        "fleet relocation path does not move the asset to destination: "
                        + ",".join(str(route_id) for route_id in bad_disposition)
                    )
            return explicit_path

        # Dijkstra over physical compatibility only. Current resource/support
        # availability belongs to Available Capacity, not Nominal planning.
        import heapq

        queue: list[tuple[float, tuple[str, ...], SpatialNodeId, tuple[RouteId, ...]]] = [
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
            for route in sorted(self.routes.values(), key=lambda row: str(row.id)):
                if route.origin_id != node:
                    continue
                if self.vehicle_route_physical_failures(route.id, vehicle_definition_id, day):
                    continue
                definition = self.vehicle_defs[vehicle_definition_id]
                if (
                    require_destination_disposition
                    and definition.route_asset_disposition(route)
                    is not OperationAssetDisposition.DESTINATION
                ):
                    continue
                if policy is PathPolicy.FASTEST:
                    edge = max(1, round(route.transit_days * definition.transit_time_multiplier))
                elif policy is PathPolicy.LOWEST_PROPELLANT:
                    edge = definition.propellant_t(route, max(definition.max_cargo_for_route(route), 0.0))
                else:
                    payload = max(definition.max_cargo_for_route(route), 1e-9)
                    edge = definition.operating_cost_musd_per_cargo_t + definition.operating_cost_musd_per_cycle / payload
                new_path = path + (route.id,)
                heapq.heappush(
                    queue,
                    (score + float(edge), tuple(str(r) for r in new_path), route.destination_id, new_path),
                )
        raise ValueError(f"no physically compatible path {source_id} -> {destination_id}")

    def _vehicle_path_infrastructure_requirements(
        self,
        definition,
        routes: tuple,
        *,
        resource_requirements: tuple[tuple[SpatialNodeId, DefinitionId, float], ...] = (),
        servicing_location_id: SpatialNodeId | None = None,
        servicing_rate: float = 0.0,
    ) -> tuple[tuple[SpatialNodeId, str, float, str], ...]:
        """Project the infrastructure contract already used by route execution.

        This is derived state for decision surfaces.  Callers supply resource
        requirements in whatever rate/quantity applies to their operation; only
        the presence of a positive demand matters for support-interface needs.
        """
        infrastructure: dict[tuple[SpatialNodeId, str, str], float] = {}

        def _require(
            location_id: SpatialNodeId, capability_id: str, minimum: float, mode: str
        ) -> None:
            key = (location_id, capability_id, mode)
            infrastructure[key] = max(
                infrastructure.get(key, 0.0), max(0.0, minimum)
            )

        for route in routes:
            for location_id, site_requirements in (
                (route.origin_id, route.origin_requirements),
                (route.destination_id, route.destination_requirements),
            ):
                for requirement in site_requirements.capability_requirements:
                    _require(
                        location_id,
                        requirement.capability_id,
                        requirement.minimum_capacity,
                        requirement.mode,
                    )
            present_operations = {operation.operation_type for operation in route.operations}
            for support in definition.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    route.origin_id
                    if support.location is OperationSupportLocation.ORIGIN
                    else route.destination_id
                )
                _require(location_id, support.capability_id, 0.0, "available")

        for location_id, resource_id, amount in resource_requirements:
            if amount <= 1e-12:
                continue
            for support in definition.resource_support_requirements:
                if support.resource_id == resource_id:
                    _require(
                        location_id,
                        support.infrastructure_capability_id,
                        0.0,
                        "available",
                    )

        if (
            servicing_location_id is not None
            and definition.turnaround_capability_id is not None
            and servicing_rate > 1e-12
        ):
            _require(
                servicing_location_id,
                definition.turnaround_capability_id,
                servicing_rate,
                "available",
            )

        return tuple(
            (location_id, capability_id, minimum, mode)
            for (location_id, capability_id, mode), minimum in sorted(
                infrastructure.items(),
                key=lambda row: (str(row[0][0]), row[0][1], row[0][2]),
            )
        )

    def derive_transport_service_plan(
        self, allocation_id: EntityId, day: int = 0
    ) -> TransportServicePlan:
        return self._derive_transport_service_plan(
            self.transport_allocations[allocation_id], day
        )

    def transport_service_plan_for(
        self,
        vehicle_definition_id: DefinitionId,
        anchor_location_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        day: int = 0,
        path: tuple[RouteId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
    ) -> TransportServicePlan:
        """Derive a deterministic service plan without creating authoritative state."""
        preview = TransportAllocation(
            EntityId(
                f"transport.service.preview:{vehicle_definition_id}:{anchor_location_id}:{destination_id}:{path_policy.value}"
            ),
            vehicle_definition_id,
            anchor_location_id,
            destination_id,
            0,
            TransportControlMode.UNITS,
            0,
            None,
            path,
            path_policy,
            False,
            0,
        )
        return self._derive_transport_service_plan(preview, day)

    def _derive_transport_service_plan(
        self, allocation: TransportAllocation, day: int
    ) -> TransportServicePlan:
        definition = self.vehicle_defs[allocation.vehicle_definition_id]
        blockers: list[str] = []
        try:
            forward = self._route_path_for_vehicle(
                allocation.anchor_location_id,
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
                allocation.anchor_location_id,
                allocation.destination_id,
                (), (), (), 0.0, definition.turnaround_days, 0.0, 0.0, 0, None,
                DirectionalCapacity(), blockers=(f"service_plan:{exc}",),
            )

        if not forward:
            raise ValueError("transport service path must be non-empty")

        forward_routes = tuple(self.routes[route_id] for route_id in forward)
        for index, route in enumerate(forward_routes):
            blockers.extend(self.route_failures(route.id, day))
            blockers.extend(
                self.vehicle_route_failures(
                    route.id, allocation.vehicle_definition_id, day
                )
            )
            if (
                index < len(forward_routes) - 1
                and definition.route_asset_disposition(route)
                is not OperationAssetDisposition.DESTINATION
            ):
                blockers.append(
                    f"asset_position:{route.id}:cannot_continue_to_next_route"
                )
        forward_days = sum(
            max(1, round(route.transit_days * definition.transit_time_multiplier))
            for route in forward_routes
        )
        forward_payload = min(definition.max_cargo_for_route(route) for route in forward_routes)
        if forward_payload <= 1e-12:
            blockers.append("payload_capacity")

        # A route whose operation returns the asset to its origin already closes
        # the service cycle. Otherwise the same Fleet unit needs a physical
        # reverse path to become reusable at its anchor.
        final_disposition = definition.route_asset_disposition(forward_routes[-1])
        reverse: tuple[RouteId, ...] = ()
        reverse_routes: tuple = ()
        reverse_days = 0
        reverse_payload = 0.0
        if final_disposition is OperationAssetDisposition.DESTINATION:
            try:
                reverse = self._route_path_for_vehicle(
                    allocation.destination_id,
                    allocation.anchor_location_id,
                    allocation.vehicle_definition_id,
                    day,
                    allocation.path_policy,
                )
                reverse_routes = tuple(self.routes[route_id] for route_id in reverse)
                for index, route in enumerate(reverse_routes):
                    blockers.extend(self.route_failures(route.id, day))
                    blockers.extend(
                        self.vehicle_route_failures(
                            route.id, allocation.vehicle_definition_id, day
                        )
                    )
                    if (
                        index < len(reverse_routes) - 1
                        and definition.route_asset_disposition(route)
                        is not OperationAssetDisposition.DESTINATION
                    ):
                        blockers.append(
                            f"asset_position:{route.id}:cannot_continue_to_next_route"
                        )
                reverse_days = sum(
                    max(1, round(route.transit_days * definition.transit_time_multiplier))
                    for route in reverse_routes
                )
                reverse_payload = min(
                    (definition.max_cargo_for_route(route) for route in reverse_routes),
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
        for direction, routes, service_payload in (
            ("forward", forward_routes, forward_payload),
            ("reverse", reverse_routes, reverse_payload),
        ):
            for route in routes:
                payload = max(0.0, service_payload)
                empty_propellant = definition.propellant_t(route, 0.0)
                loaded_propellant = definition.propellant_t(route, payload)
                legs.append(
                    TransportServiceLeg(
                        route.id,
                        direction,
                        True,
                        payload,
                        max(1, round(route.transit_days * definition.transit_time_multiplier)),
                        loaded_propellant,
                    )
                )
                if definition.propellant_resource_id is not None:
                    resource_key = (route.origin_id, definition.propellant_resource_id)
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
            key = (allocation.anchor_location_id, resource_id)
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
            (*forward_routes, *reverse_routes),
            resource_requirements=resources,
            servicing_location_id=allocation.anchor_location_id,
            servicing_rate=servicing,
        )
        return TransportServicePlan(
            allocation.id,
            allocation.vehicle_definition_id,
            allocation.anchor_location_id,
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
        anchor_location_id: SpatialNodeId,
        destination_id: SpatialNodeId,
        *,
        priority: int = 50,
        control_mode: TransportControlMode = TransportControlMode.UNITS,
        target_units: int | None = 0,
        target_capacity: DirectionalCapacity | None = None,
        path: tuple[RouteId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        paused: bool = False,
        day: int = 0,
    ) -> EntityId:
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if anchor_location_id not in self.facilities.environment.graph.nodes:
            raise KeyError(anchor_location_id)
        if destination_id not in self.facilities.environment.graph.nodes:
            raise KeyError(destination_id)
        self._transport_allocation_counter += 1
        allocation_id = EntityId(f"transport.allocation.{self._transport_allocation_counter}")
        allocation = TransportAllocation(
            allocation_id,
            vehicle_definition_id,
            anchor_location_id,
            destination_id,
            priority,
            control_mode,
            target_units,
            target_capacity,
            path,
            path_policy,
            paused,
            0,
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
        priority: int | None = None,
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
                priority=current.priority if priority is None else priority,
                target_units=current.target_units if target_units is None else target_units,
                path_policy=current.path_policy if path_policy is None else path_policy,
                paused=current.paused if paused is None else paused,
            )
        else:
            if target_units is not None:
                raise ValueError("CAPACITY allocation cannot accept unit target")
            updated = replace(
                current,
                priority=current.priority if priority is None else priority,
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
        if allocation.active_units > 0 and allocation.last_operated_day is not None:
            self._new_release(allocation, allocation.active_units, day)
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
            allocation.anchor_location_id,
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

        # Relocations remain committed against the source pool until arrival,
        # then atomically move their quantity into the destination pool.
        for relocation_id in sorted(
            [rid for rid, row in self.fleet_relocations.items() if row.arrival_day <= day],
            key=str,
        ):
            relocation = self.fleet_relocations.pop(relocation_id)
            source = self.fleet_pool(relocation.vehicle_definition_id, relocation.source_id)
            if source.total_units < relocation.units:
                raise RuntimeError("fleet relocation exceeds source pool")
            source.total_units -= relocation.units
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
        path: tuple[RouteId, ...] | None = None,
        path_policy: PathPolicy = PathPolicy.FASTEST,
        day: int = 0,
    ) -> FleetRelocationPlan:
        """Derive the exact decision contract used to start a Fleet relocation."""
        if vehicle_definition_id not in self.vehicle_defs:
            raise KeyError(vehicle_definition_id)
        if source_id not in self.facilities.environment.graph.nodes:
            raise KeyError(source_id)
        if destination_id not in self.facilities.environment.graph.nodes:
            raise KeyError(destination_id)

        blockers: list[str] = []
        if units <= 0:
            blockers.append("relocation_units:positive_required")
        if source_id == destination_id:
            blockers.append("relocation_endpoints:must_differ")

        free_units = self.fleet_free_units(vehicle_definition_id, source_id)
        if units > 0 and free_units < units:
            blockers.append(f"fleet_units:{free_units}/{units}")

        route_path: tuple[RouteId, ...] = ()
        if source_id != destination_id:
            try:
                route_path = self._route_path_for_vehicle(
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
        if not route_path and source_id != destination_id and not any(
            row.startswith("relocation_path:") for row in blockers
        ):
            blockers.append("relocation_path:empty")

        definition = self.vehicle_defs[vehicle_definition_id]
        routes = tuple(self.routes[route_id] for route_id in route_path)
        propellant_requirements: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        if route_path:
            for route in routes:
                blockers.extend(self.route_failures(route.id, day))
                blockers.extend(
                    self.vehicle_route_failures(route.id, vehicle_definition_id, day)
                )
                if definition.propellant_resource_id is not None and units > 0:
                    amount = definition.propellant_t(route, 0.0) * units
                    if amount > 1e-12:
                        blockers.extend(
                            self.resource_support_failures(
                                definition.performance,
                                route.origin_id,
                                definition.propellant_resource_id,
                                day,
                            )
                        )
                        key = (route.origin_id, definition.propellant_resource_id)
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
            max(1, round(route.transit_days * definition.transit_time_multiplier))
            for route in routes
        )
        if route_path:
            blockers.extend(definition.endurance_failures(float(travel_days)))
        arrival_day = day + max(1, int(math.ceil(travel_days))) if route_path else None
        infrastructure_requirements = self._vehicle_path_infrastructure_requirements(
            definition,
            routes,
            resource_requirements=tuple(
                (row.location_id, row.resource_id, row.required_t)
                for row in resource_requirements
            ),
        )
        return FleetRelocationPlan(
            vehicle_definition_id=vehicle_definition_id,
            units=units,
            source_id=source_id,
            destination_id=destination_id,
            path=route_path,
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
        path: tuple[RouteId, ...] | None = None,
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
        if plan.blockers:
            raise ValueError(
                "fleet relocation is not operationally feasible: "
                + "; ".join(plan.blockers)
            )
        assert plan.arrival_day is not None
        for requirement in plan.resource_requirements:
            if requirement.required_t > 1e-12 and not self.inventory.take_unreserved(
                requirement.location_id, requirement.resource_id, requirement.required_t
            ):
                raise RuntimeError(
                    "fleet relocation resources changed after feasibility check"
                )
        self._fleet_relocation_counter += 1
        relocation_id = EntityId(f"fleet.relocation.{self._fleet_relocation_counter}")
        self.fleet_relocations[relocation_id] = FleetRelocation(
            relocation_id,
            vehicle_definition_id,
            units,
            source_id,
            destination_id,
            day,
            plan.arrival_day,
        )
        return relocation_id


    @staticmethod
    def _allocation_order_key(allocation: TransportAllocation) -> tuple:
        """Stable same-priority ordering derived from authoritative allocation state."""
        if allocation.control_mode is TransportControlMode.UNITS:
            target_key = (int(allocation.target_units or 0), 0.0, 0.0)
        else:
            target = allocation.target_capacity or DirectionalCapacity()
            target_key = (0, target.forward_t_per_day, target.reverse_t_per_day)
        return (
            -allocation.priority,
            str(allocation.vehicle_definition_id),
            str(allocation.anchor_location_id),
            str(allocation.destination_id),
            tuple(str(route_id) for route_id in (allocation.path or ())),
            allocation.path_policy.value,
            allocation.control_mode.value,
            target_key,
        )

    def reconcile_fleet_allocations(self, day: int = 0) -> None:
        # Determine desired transport ownership by pool and priority, independent
        # of insertion order. Existing non-transport commitments and releases are
        # removed from the allocatable quantity first.
        groups: dict[tuple[DefinitionId, SpatialNodeId], list[TransportAllocation]] = {}
        for allocation in self.transport_allocations.values():
            groups.setdefault(
                (allocation.vehicle_definition_id, allocation.anchor_location_id), []
            ).append(allocation)

        for (definition_id, location_id), rows in sorted(
            groups.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            pool = self.fleet_pool(definition_id, location_id)
            non_transport = (
                self._reserved_units_at(definition_id, location_id)
                + self._relocating_units_from(definition_id, location_id)
                + self._releasing_units_at(definition_id, location_id)
            )
            allocatable = max(0, pool.total_units - non_transport)
            desired: dict[EntityId, int] = {}
            remaining = allocatable
            ordered = sorted(rows, key=self._allocation_order_key)
            for allocation in ordered:
                required = 0 if allocation.paused else self.allocation_required_units(allocation.id, day)
                grant = min(required, remaining)
                desired[allocation.id] = grant
                remaining -= grant

            # Units displaced by priority/target changes must physically recover
            # before they become free again.
            for allocation in ordered:
                target_active = desired[allocation.id]
                if allocation.active_units > target_active:
                    delta = allocation.active_units - target_active
                    if allocation.last_operated_day is not None:
                        self._new_release(allocation, delta, day)
                    allocation.active_units = target_active

            # Newly created releases are still committed, so recompute actual
            # free quantity before filling target deficits.
            free = self.fleet_free_units(definition_id, location_id)
            for allocation in ordered:
                target_active = desired[allocation.id]
                if allocation.active_units >= target_active or free <= 0:
                    continue
                delta = min(target_active - allocation.active_units, free)
                allocation.active_units += delta
                free -= delta

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
        active = allocation.active_units
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
            route = self.routes[leg.route_id]
            present_operations = {operation.operation_type for operation in route.operations}
            for support in definition.operation_support_requirements:
                if support.operation_type not in present_operations:
                    continue
                location_id = (
                    route.origin_id
                    if support.location.value == "origin"
                    else route.destination_id
                )
                if not self._has_available_capability(location_id, support.capability_id, day):
                    forward_ratio = 0.0
                    reverse_ratio = 0.0
                    limiting.append(f"infrastructure:{location_id}:{support.capability_id}")

        # Turnaround servicing is a cycle-rate capacity, not merely a boolean
        # facility prerequisite. A partially provisioned service therefore
        # lowers Available Capacity without changing the Fleet target.
        if definition.turnaround_capability_id is not None:
            required_service = plan.servicing_units_per_full_utilization_day * active
            available_service = self._available_capability(
                allocation.anchor_location_id, definition.turnaround_capability_id, day
            )
            if required_service > 1e-12:
                service_ratio = min(1.0, max(0.0, available_service / required_service))
                forward_ratio = min(forward_ratio, service_ratio)
                reverse_ratio = min(reverse_ratio, service_ratio)
                if service_ratio < 1.0 - 1e-12:
                    limiting.append(
                        f"servicing:{allocation.anchor_location_id}:{definition.turnaround_capability_id}"
                    )

        def _resource_map(rows):
            return {(location_id, resource_id): amount for location_id, resource_id, amount in rows}

        empty_resources = _resource_map(plan.resource_t_per_empty_cycle_day)
        forward_increments = _resource_map(plan.resource_t_per_forward_payload_increment_day)
        reverse_increments = _resource_map(plan.resource_t_per_reverse_payload_increment_day)

        def _resource_ratio(increments, direction: str) -> float:
            ratio = 1.0
            keys = set(empty_resources) | set(increments)
            for location_id, resource_id in sorted(keys, key=lambda row: (str(row[0]), str(row[1]))):
                demand_per_day = empty_resources.get((location_id, resource_id), 0.0) + increments.get(
                    (location_id, resource_id), 0.0
                )
                full_demand = demand_per_day * active
                if full_demand <= 1e-12:
                    continue
                support_failures = self.resource_support_failures(
                    definition.performance, location_id, resource_id, day
                )
                if support_failures:
                    ratio = 0.0
                    limiting.extend(support_failures)
                    continue
                stock = self.inventory.available(location_id, resource_id)
                resource_ratio = min(1.0, max(0.0, stock / full_demand))
                ratio = min(ratio, resource_ratio)
                if resource_ratio < 1.0 - 1e-12:
                    limiting.append(f"resource:{direction}:{location_id}:{resource_id}")
            return ratio

        forward_ratio = min(forward_ratio, _resource_ratio(forward_increments, "forward"))
        reverse_ratio = min(reverse_ratio, _resource_ratio(reverse_increments, "reverse"))

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

        # Utilization is relative to Nominal Capacity. If current resources cap
        # Available at 50%, fully using that available half means a 50% cycle
        # rate, not 100% of the design cycle rate.
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
