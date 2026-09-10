from __future__ import annotations

from dataclasses import dataclass

from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import PathPolicy, VehicleDisposition, VehicleStatus


_EPS = 1e-9


@dataclass(frozen=True)
class TransportPlanCapacity:
    """Current physical throughput available to a resolved transport plan.

    ``capacity_t`` is the end-to-end bottleneck across transfer-separated path
    segments. ``dispatch_chunks_t`` describes source-departure chunks that are
    individually executable with the currently available vehicles/services.
    Lane automation uses both: aggregate throughput cannot exceed ``capacity_t``
    and no generated CargoOrder is larger than a source transport unit can
    actually dispatch.
    """

    capacity_t: float
    dispatch_chunks_t: tuple[float, ...]
    blockers: tuple[str, ...] = ()


@dataclass
class _CapacityBudget:
    funds_musd: float
    propellant_stock: dict[tuple[SpatialNodeId, DefinitionId], float]

    def copy(self) -> "_CapacityBudget":
        return _CapacityBudget(self.funds_musd, dict(self.propellant_stock))


class TransportCapacityMixin:
    """Pure current-state capacity projection shared by lanes and transport UI.

    This layer does not create orders or move vehicles. It composes route/mode
    compatibility with the same authoritative per-leg resource evaluator used by
    mission execution, so displayed capacity cannot acquire a second fuel/cost
    model of its own.
    """

    def _capacity_budget(
        self,
        route_ids: tuple[RouteId, ...],
        vehicle_definition_ids: tuple[DefinitionId, ...],
    ) -> _CapacityBudget:
        stock: dict[tuple[SpatialNodeId, DefinitionId], float] = {}
        for definition_id in vehicle_definition_ids:
            definition = self.vehicle_defs[definition_id]
            resource_id = definition.propellant_resource_id
            if resource_id is None:
                continue
            for route_id in route_ids:
                origin_id = self.routes[route_id].origin_id
                key = (origin_id, resource_id)
                if key not in stock:
                    stock[key] = self.inventory.available(origin_id, resource_id)
        return _CapacityBudget(self.account.funds_musd, stock)

    def _vehicle_path_simulation(
        self,
        vehicle_id: EntityId,
        route_ids: tuple[RouteId, ...],
        cargo_t: float,
        day: int,
        budget: _CapacityBudget,
        *,
        first_payload_overhead_t: float = 0.0,
        require_available_at_start: bool = True,
    ) -> _CapacityBudget | None:
        if cargo_t < -_EPS or not route_ids:
            return None
        state = self.vehicles[vehicle_id]
        definition = self.vehicle_defs[state.definition_id]
        first_route = self.routes[route_ids[0]]
        if require_available_at_start and (
            state.location_id != first_route.origin_id
            or state.status != VehicleStatus.AVAILABLE
            or state.available_day > day
        ):
            return None
        if len(route_ids) > 1 and definition.default_disposition is not VehicleDisposition.DESTINATION:
            return None

        remaining = budget.copy()
        fuel_t = state.propellant_t
        for index, route_id in enumerate(route_ids):
            route = self.routes[route_id]
            if self.route_failures(route_id, day) or self.vehicle_route_failures(
                route_id, definition.id, day
            ):
                return None
            payload_t = cargo_t + (first_payload_overhead_t if index == 0 else 0.0)
            if payload_t > definition.max_cargo_for_route(route) + _EPS:
                return None

            resource_id = definition.propellant_resource_id
            key = None if resource_id is None else (route.origin_id, resource_id)
            available_stock = 0.0 if key is None else remaining.propellant_stock.get(
                key, self.inventory.available(route.origin_id, resource_id)
            )
            plan = self._vehicle_leg_resource_plan(
                state,
                definition,
                route,
                payload_t,
                day,
                starting_propellant_t=fuel_t,
                funds_musd=remaining.funds_musd,
                propellant_stock_t=available_stock,
                vehicle_at_origin=True,
            )
            if not plan.feasible:
                return None
            remaining.funds_musd = max(0.0, remaining.funds_musd - plan.mission_cost_musd)
            if key is not None and plan.refuel_t > _EPS:
                remaining.propellant_stock[key] = max(0.0, available_stock - plan.refuel_t)
            fuel_t = plan.ending_propellant_t
        return remaining

    def _vehicle_path_capacity_with_budget(
        self,
        vehicle_id: EntityId,
        route_ids: tuple[RouteId, ...],
        day: int,
        budget: _CapacityBudget,
        *,
        first_payload_overhead_t: float = 0.0,
        require_available_at_start: bool = True,
    ) -> tuple[float, _CapacityBudget]:
        if not route_ids:
            return 0.0, budget
        definition = self.vehicle_defs[self.vehicles[vehicle_id].definition_id]
        upper = min(
            max(
                0.0,
                definition.max_cargo_for_route(self.routes[route_id])
                - (first_payload_overhead_t if index == 0 else 0.0),
            )
            for index, route_id in enumerate(route_ids)
        )
        if upper <= _EPS:
            return 0.0, budget
        zero = self._vehicle_path_simulation(
            vehicle_id,
            route_ids,
            0.0,
            day,
            budget,
            first_payload_overhead_t=first_payload_overhead_t,
            require_available_at_start=require_available_at_start,
        )
        if zero is None:
            return 0.0, budget

        low = 0.0
        high = upper
        best_budget = zero
        for _ in range(36):
            mid = (low + high) / 2.0
            simulated = self._vehicle_path_simulation(
                vehicle_id,
                route_ids,
                mid,
                day,
                budget,
                first_payload_overhead_t=first_payload_overhead_t,
                require_available_at_start=require_available_at_start,
            )
            if simulated is None:
                high = mid
            else:
                low = mid
                best_budget = simulated
        return (0.0, budget) if low <= _EPS else (low, best_budget)

    def _owned_continuous_segment_capacity(
        self,
        route_ids: tuple[RouteId, ...],
        definition_id: DefinitionId,
        day: int,
    ) -> tuple[float, tuple[float, ...]]:
        if not route_ids:
            return 0.0, ()
        first_route = route_ids[0]
        vehicle_ids = self.available_vehicle_ids(first_route, definition_id, day)
        if not vehicle_ids:
            return 0.0, ()
        budget = self._capacity_budget(route_ids, (definition_id,))
        chunks: list[float] = []
        for vehicle_id in vehicle_ids:
            cargo_t, remaining = self._vehicle_path_capacity_with_budget(
                vehicle_id, route_ids, day, budget
            )
            if cargo_t <= _EPS:
                continue
            chunks.append(cargo_t)
            budget = remaining
        return sum(chunks), tuple(chunks)

    def _staged_segment_capacity(
        self,
        route_ids: tuple[RouteId, ...],
        carrier_definition_id: DefinitionId,
        onward_definition_id: DefinitionId,
        day: int,
    ) -> tuple[float, tuple[float, ...]]:
        if len(route_ids) < 2:
            return 0.0, ()
        first_route = route_ids[0]
        source_id = self.routes[first_route].origin_id
        carrier_ids = self.available_vehicle_ids(first_route, carrier_definition_id, day)
        onward_ids = tuple(
            state.id
            for state in sorted(self.vehicles.values(), key=lambda row: str(row.id))
            if state.definition_id == onward_definition_id
            and state.location_id == source_id
            and state.status == VehicleStatus.AVAILABLE
            and state.available_day <= day
        )
        if not carrier_ids or not onward_ids:
            return 0.0, ()
        carrier = self.vehicle_defs[carrier_definition_id]
        onward = self.vehicle_defs[onward_definition_id]
        if (
            carrier.default_disposition is not VehicleDisposition.RETURN_TO_ORIGIN
            or onward.default_disposition is not VehicleDisposition.DESTINATION
        ):
            return 0.0, ()

        budget = self._capacity_budget(
            route_ids, (carrier_definition_id, onward_definition_id)
        )
        unused_onward = set(onward_ids)
        chunks: list[float] = []
        for carrier_id in carrier_ids:
            best: tuple[float, EntityId, _CapacityBudget] | None = None
            for onward_id in sorted(unused_onward, key=str):
                onward_state = self.vehicles[onward_id]
                overhead_t = onward.dry_mass_t + onward_state.propellant_t
                upper = min(
                    max(0.0, carrier.max_cargo_for_route(self.routes[first_route]) - overhead_t),
                    *(onward.max_cargo_for_route(self.routes[route_id]) for route_id in route_ids[1:]),
                )
                if upper <= _EPS:
                    continue
                low = 0.0
                high = upper
                best_budget = budget
                for _ in range(36):
                    mid = (low + high) / 2.0
                    after_carrier = self._vehicle_path_simulation(
                        carrier_id,
                        (first_route,),
                        mid,
                        day,
                        budget,
                        first_payload_overhead_t=overhead_t,
                    )
                    if after_carrier is None:
                        high = mid
                        continue
                    after_onward = self._vehicle_path_simulation(
                        onward_id,
                        route_ids[1:],
                        mid,
                        day,
                        after_carrier,
                        require_available_at_start=False,
                    )
                    if after_onward is None:
                        high = mid
                    else:
                        low = mid
                        best_budget = after_onward
                if low > _EPS and (best is None or low > best[0] + _EPS):
                    best = (low, onward_id, best_budget)
            if best is None:
                continue
            chunks.append(best[0])
            unused_onward.remove(best[1])
            budget = best[2]
        return sum(chunks), tuple(chunks)

    def _external_segment_capacity(
        self, route_id: RouteId, service_id: DefinitionId, day: int
    ) -> tuple[float, tuple[float, ...]]:
        if self.route_failures(route_id, day) or self.service_route_failures(
            route_id, service_id, day
        ):
            return 0.0, ()
        service = self.external_services[service_id]
        capacity = self._external_service_remaining_capacity(service_id, day)
        if service.cost_musd_per_t > _EPS:
            capacity = min(capacity, self.account.funds_musd / service.cost_musd_per_t)
        return (capacity, (capacity,)) if capacity > _EPS else (0.0, ())

    def _path_segments(
        self, path: tuple[RouteId, ...], day: int
    ) -> tuple[tuple[RouteId, ...], ...]:
        if not path:
            return ()
        segments: list[tuple[RouteId, ...]] = []
        start = 0
        for index in range(len(path) - 1):
            transfer_node = self.routes[path[index]].destination_id
            if self._has_available_capability(transfer_node, "cargo_transfer", day):
                segments.append(path[start : index + 1])
                start = index + 1
        segments.append(path[start:])
        return tuple(segments)

    def _segment_capacity(
        self,
        route_ids: tuple[RouteId, ...],
        mode_by_route: dict[RouteId, str],
        day: int,
    ) -> tuple[float, tuple[float, ...], tuple[str, ...]]:
        first = route_ids[0]
        modes = tuple(mode_by_route[route_id] for route_id in route_ids)
        first_mode = modes[0]
        service = self._service_for_mode(first_mode)
        if service is not None:
            if len(route_ids) != 1:
                return 0.0, (), (f"route:{first}:cargo_transfer_required",)
            capacity, chunks = self._external_segment_capacity(first, service.id, day)
        else:
            first_definition_id = DefinitionId(first_mode)
            if first_definition_id not in self.vehicle_defs:
                return 0.0, (), (f"route:{first}:transport_mode:{first_mode}:unsupported",)
            if all(mode == first_mode for mode in modes):
                capacity, chunks = self._owned_continuous_segment_capacity(
                    route_ids, first_definition_id, day
                )
            elif (
                len(route_ids) >= 2
                and all(mode == modes[1] for mode in modes[1:])
                and self._service_for_mode(modes[1]) is None
            ):
                onward_definition_id = DefinitionId(modes[1])
                if onward_definition_id not in self.vehicle_defs:
                    return 0.0, (), (f"route:{first}:transport_mode:{modes[1]}:unsupported",)
                capacity, chunks = self._staged_segment_capacity(
                    route_ids, first_definition_id, onward_definition_id, day
                )
            else:
                return 0.0, (), (f"route:{first}:transport_continuity",)

        if capacity > _EPS:
            return capacity, chunks, ()
        operational = self.route_operational_failures(first, day, first_mode)
        if operational:
            return 0.0, (), tuple(f"route:{first}:{reason}" for reason in operational)
        return 0.0, (), (f"route:{first}:transport_capacity",)

    def _staged_full_path_capacity(
        self,
        path: tuple[RouteId, ...],
        mode_by_route: dict[RouteId, str],
        day: int,
    ) -> tuple[float, tuple[float, ...]]:
        """Project carrier/onboard-handoff capacity even at transfer-capable waypoints.

        Mission execution may keep cargo onboard by carrying the onward vehicle
        through the first leg and separating it at the waypoint. The presence of
        cargo-transfer infrastructure does not make that physical option disappear.
        Capacity/query projection therefore has to recognize the same state
        transition instead of requiring the onward vehicle to be pre-positioned at
        the intermediate node.
        """
        if len(path) < 2:
            return 0.0, ()
        modes = tuple(mode_by_route[route_id] for route_id in path)
        first_mode = modes[0]
        onward_mode = modes[1]
        if self._service_for_mode(first_mode) is not None or self._service_for_mode(onward_mode) is not None:
            return 0.0, ()
        if any(mode != onward_mode for mode in modes[1:]):
            return 0.0, ()
        carrier_definition_id = DefinitionId(first_mode)
        onward_definition_id = DefinitionId(onward_mode)
        if carrier_definition_id not in self.vehicle_defs or onward_definition_id not in self.vehicle_defs:
            return 0.0, ()
        return self._staged_segment_capacity(
            path, carrier_definition_id, onward_definition_id, day
        )

    def transport_plan_capacity(
        self,
        path: tuple[RouteId, ...],
        mode_by_route: dict[RouteId, str],
        day: int = 0,
    ) -> TransportPlanCapacity:
        if not path:
            return TransportPlanCapacity(0.0, (), ("route_unavailable",))
        missing_modes = [route_id for route_id in path if route_id not in mode_by_route]
        if missing_modes:
            return TransportPlanCapacity(
                0.0,
                (),
                tuple(f"route:{route_id}:transport_mode_unresolved" for route_id in missing_modes),
            )

        # Execution can use a recoverable first-stage carrier with an onboard
        # onward vehicle even when the waypoint also has cargo-transfer service.
        # Treat this as an alternative realization of the same explicit mode plan.
        staged_capacity, staged_chunks = self._staged_full_path_capacity(
            path, mode_by_route, day
        )

        capacities: list[float] = []
        blockers: list[str] = []
        source_chunks: tuple[float, ...] = ()
        for index, segment in enumerate(self._path_segments(path, day)):
            capacity, chunks, segment_blockers = self._segment_capacity(
                segment, mode_by_route, day
            )
            capacities.append(capacity)
            blockers.extend(segment_blockers)
            if index == 0:
                source_chunks = chunks

        transfer_capacity = min(capacities) if capacities and not blockers else 0.0
        # Both realizations use the same configured path/modes. Use the stronger
        # currently executable projection, but never add them together because
        # they can share the same first-stage carrier and resource budget.
        if staged_capacity > transfer_capacity + _EPS:
            return TransportPlanCapacity(staged_capacity, staged_chunks)
        if transfer_capacity > _EPS:
            return TransportPlanCapacity(transfer_capacity, source_chunks)
        if staged_capacity > _EPS:
            return TransportPlanCapacity(staged_capacity, staged_chunks)
        if blockers:
            return TransportPlanCapacity(0.0, (), tuple(dict.fromkeys(blockers)))
        return TransportPlanCapacity(0.0, (), ("transport_capacity",))

    def resolved_transport_modes(
        self,
        path: tuple[RouteId, ...],
        selected_modes: dict[RouteId, str],
        day: int,
        policy: PathPolicy,
    ) -> dict[RouteId, str]:
        """Resolve a complete mode map for a lane without hiding partial config."""
        resolved = dict(selected_modes)
        if not resolved:
            automatic = self._automatic_mode_plan(path, day, policy)
            if automatic is None:
                raise ValueError("transport plan has no executable mode assignment")
            return automatic
        for route_id in path:
            if route_id in resolved:
                continue
            mode_id = self._best_mode_for_route(route_id, day, policy)
            if mode_id is None:
                raise ValueError(f"route has no executable transport mode: {route_id}")
            resolved[route_id] = mode_id
        self.validate_mode_selection(path, resolved, day=day)
        return resolved
