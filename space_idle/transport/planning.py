from __future__ import annotations

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import OperationAssetDisposition, PathPolicy, VehicleStatus, RouteDef, ExternalTransportServiceDef, TransportMode

import heapq


class TransportPlanningMixin:
        def _service_for_mode(self, mode_id: str) -> ExternalTransportServiceDef | None:
            return self.external_services.get(DefinitionId(mode_id))

        def _transport_modes(self, route_id: RouteId, day: int = 0) -> tuple[TransportMode, ...]:
            if not self.route_available(route_id, day):
                return ()
            route = self.routes[route_id]
            modes: list[TransportMode] = []
            for definition_id, vehicle in sorted(self.vehicle_defs.items(), key=lambda row: str(row[0])):
                ids = self.available_vehicle_ids(route_id, definition_id, day)
                if not ids:
                    continue
                modes.append(
                    TransportMode(
                        str(definition_id), definition_id, vehicle.max_cargo_for_route(route) * len(ids),
                        vehicle.operating_cost_musd_per_cargo_t, ids,
                    )
                )
            for service in sorted(self.external_services.values(), key=lambda row: str(row.id)):
                if service.capacity_t_per_day <= 1e-12 or self.service_route_failures(route_id, service.id, day):
                    continue
                modes.append(TransportMode(str(service.id), None, service.capacity_t_per_day, service.cost_musd_per_t))
            return tuple(modes)

        def _mode_is_defined_for_route(self, route_id: RouteId, mode_id: str, day: int = 0) -> bool:
            service = self._service_for_mode(mode_id)
            if service is not None:
                return service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day)
            definition_id = DefinitionId(mode_id)
            return definition_id in self.vehicle_defs and not self.vehicle_route_physical_failures(route_id, definition_id, day)

        def _selected_modes(self, route_id: RouteId, day: int, mode_id: str | None) -> tuple[TransportMode, ...]:
            modes = self._transport_modes(route_id, day)
            if mode_id is None:
                return tuple(sorted(
                    modes,
                    key=lambda mode: (
                        self.route_mode_transit_days(route_id, mode.mode_id, day),
                        mode.cost_musd_per_t,
                        mode.mode_id,
                    ),
                ))
            return tuple(mode for mode in modes if mode.mode_id == mode_id)

        def route_mode_ids(self, route_id: RouteId, day: int = 0) -> tuple[str, ...]:
            # Return defined candidates even when currently blocked so UI can explain why.
            result = [str(service.id) for service in sorted(self.external_services.values(), key=lambda row: str(row.id))]
            result.extend(str(definition_id) for definition_id in sorted(self.vehicle_defs, key=str))
            return tuple(result)

        def route_mode_transit_days(self, route_id: RouteId, mode_id: str, day: int = 0) -> int:
            route = self.routes[route_id]
            service = self._service_for_mode(mode_id)
            if service is not None:
                return max(1, round(route.transit_days * service.transit_time_multiplier))
            vehicle = self.vehicle_defs[DefinitionId(mode_id)]
            return max(1, round(route.transit_days * vehicle.transit_time_multiplier))

        def route_dispatch_capacity_t(self, route_id: RouteId, day: int = 0, mode_id: str | None = None) -> float:
            return sum(mode.dispatch_capacity_t for mode in self._selected_modes(route_id, day, mode_id))

        def route_operational_failures(
            self, route_id: RouteId, day: int = 0, mode_id: str | None = None
        ) -> tuple[str, ...]:
            failures = list(self.route_failures(route_id, day))
            if failures:
                return tuple(failures)
            if mode_id is not None:
                service = self._service_for_mode(mode_id)
                if service is not None:
                    compatibility = self.service_route_failures(route_id, service.id, day)
                    if service.capacity_t_per_day <= 1e-12 or compatibility:
                        return tuple(f"transport_mode:{mode_id}:{reason}" for reason in compatibility) or (f"transport_mode:{mode_id}:unsupported",)
                    if self.account.funds_musd <= 1e-12 and service.cost_musd_per_t > 0:
                        return ("funds",)
                    return ()
                definition_id = DefinitionId(mode_id)
                if definition_id not in self.vehicle_defs:
                    return (f"transport_mode:{mode_id}:unsupported",)
                compatibility = self.vehicle_route_failures(route_id, definition_id, day)
                if compatibility:
                    return tuple(f"transport_mode:{mode_id}:{reason}" for reason in compatibility)
                ids = self.available_vehicle_ids(route_id, definition_id, day)
                if not ids:
                    return (f"vehicle_location_or_state:{mode_id}",)
                vehicle = self.vehicle_defs[definition_id]
                if vehicle.operating_cost_musd_per_mission > self.account.funds_musd + 1e-12:
                    return ("funds",)
                if vehicle.propellant_resource_id is not None and vehicle.propellant_t_per_total_t_per_km_s > 0:
                    minimum = vehicle.propellant_t(self.routes[route_id], 0.0)
                    if all(self.vehicles[vid].propellant_t + 1e-12 < minimum for vid in ids):
                        origin_id = self.routes[route_id].origin_id
                        if not self._has_available_capability(origin_id, "vehicle_refueling", day):
                            return ("vehicle_refueling_infrastructure",)
                        origin_stock = self.inventory.available(origin_id, vehicle.propellant_resource_id)
                        if all(self.vehicles[vid].propellant_t + origin_stock + 1e-12 < minimum for vid in ids):
                            return (f"propellant:{vehicle.propellant_resource_id}",)
                return ()
            modes = self._transport_modes(route_id, day)
            if not modes:
                # Distinguish a physically impossible route from one awaiting a vehicle.
                compatible_defs = [
                    definition_id for definition_id in self.vehicle_defs
                    if not self.vehicle_route_failures(route_id, definition_id, day)
                ]
                if compatible_defs:
                    return ("vehicle_location_or_state",)
                return ("transport_capacity",)
            mode_failures: list[str] = []
            for mode in modes:
                failures_for_mode = self.route_operational_failures(route_id, day, mode.mode_id)
                if not failures_for_mode:
                    return ()
                mode_failures.extend(failures_for_mode)
            return tuple(dict.fromkeys(mode_failures))

        def route_usable(self, route_id: RouteId, day: int = 0) -> bool:
            return not self.route_operational_failures(route_id, day)

        def _route_has_physical_mode(self, route_id: RouteId, day: int = 0) -> bool:
            """Whether content defines any physically compatible mode for an explicit plan."""
            if self.route_failures(route_id, day):
                return False
            if any(
                service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day)
                for service in self.external_services.values()
            ):
                return True
            return any(not self.vehicle_route_physical_failures(route_id, definition_id, day) for definition_id in self.vehicle_defs)

        def _route_has_plannable_mode(self, route_id: RouteId, day: int = 0) -> bool:
            """Automatic planning only uses capacity that actually exists now.

            Explicit player plans may intentionally wait for future equipment, but an
            automatic path must not strand cargo based only on a compatible vehicle
            definition that has no owned instance or external service.
            """
            if self.route_failures(route_id, day):
                return False
            if any(
                service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day)
                for service in self.external_services.values()
            ):
                return True
            return any(self.available_vehicle_ids(route_id, definition_id, day) for definition_id in self.vehicle_defs)

        def route_effective_transit_days(self, route_id: RouteId, day: int = 0) -> int:
            durations: list[int] = []
            for service in self.external_services.values():
                if service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day):
                    durations.append(self.route_mode_transit_days(route_id, str(service.id), day))
            for definition_id in self.vehicle_defs:
                if self.available_vehicle_ids(route_id, definition_id, day):
                    durations.append(self.route_mode_transit_days(route_id, str(definition_id), day))
            if not durations:
                raise ValueError("route has no currently available transport mode")
            return min(durations)

        def route_estimated_cost_musd_per_t(self, route_id: RouteId, day: int = 0) -> float:
            route = self.routes[route_id]
            costs: list[float] = []
            for service in self.external_services.values():
                if service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day):
                    costs.append(service.cost_musd_per_t)
            for definition_id, vehicle in self.vehicle_defs.items():
                if not self.available_vehicle_ids(route_id, definition_id, day):
                    continue
                capacity = max(vehicle.max_cargo_for_route(route), 1e-9)
                costs.append(vehicle.operating_cost_musd_per_cargo_t + vehicle.operating_cost_musd_per_mission / capacity)
            if not costs:
                raise ValueError("route has no currently available transport mode")
            return min(costs)

        def route_estimated_propellant_t_per_cargo_t(self, route_id: RouteId, day: int = 0) -> float:
            route = self.routes[route_id]
            values: list[float] = []
            for service in self.external_services.values():
                if service.capacity_t_per_day > 1e-12 and not self.service_route_failures(route_id, service.id, day):
                    # Externally purchased propellant is outside owned-resource accounting.
                    values.append(0.0)
            for definition_id, vehicle in self.vehicle_defs.items():
                if not self.available_vehicle_ids(route_id, definition_id, day):
                    continue
                cargo = max(vehicle.max_cargo_for_route(route), 1e-9)
                values.append(vehicle.propellant_t(route, cargo) / cargo)
            if not values:
                raise ValueError("route has no currently available transport mode")
            return min(values)

        def _mode_cost_musd_per_t(self, route_id: RouteId, mode_id: str) -> float:
            service = self._service_for_mode(mode_id)
            if service is not None:
                return service.cost_musd_per_t
            vehicle = self.vehicle_defs[DefinitionId(mode_id)]
            route = self.routes[route_id]
            capacity = max(vehicle.max_cargo_for_route(route), 1e-9)
            return vehicle.operating_cost_musd_per_cargo_t + vehicle.operating_cost_musd_per_mission / capacity

        def _mode_propellant_t_per_cargo_t(self, route_id: RouteId, mode_id: str) -> float:
            service = self._service_for_mode(mode_id)
            if service is not None:
                # Purchased transport does not consume player-owned propellant.
                return 0.0
            vehicle = self.vehicle_defs[DefinitionId(mode_id)]
            route = self.routes[route_id]
            cargo = max(vehicle.max_cargo_for_route(route), 1e-9)
            return vehicle.propellant_t(route, cargo) / cargo

        def _mode_policy_score(self, route_id: RouteId, mode_id: str, day: int, policy: PathPolicy) -> float:
            if policy is PathPolicy.FASTEST:
                return float(self.route_mode_transit_days(route_id, mode_id, day))
            if policy is PathPolicy.LOWEST_COST:
                return self._mode_cost_musd_per_t(route_id, mode_id)
            return self._mode_propellant_t_per_cargo_t(route_id, mode_id)

        def _best_mode_for_route(self, route_id: RouteId, day: int, policy: PathPolicy) -> str | None:
            modes = self._transport_modes(route_id, day)
            if not modes:
                return None
            candidates = [mode.mode_id for mode in modes]
            return min(candidates, key=lambda mode_id: (self._mode_policy_score(route_id, mode_id, day, policy), mode_id))

        def _continuous_vehicle_plan(
            self, path: tuple[RouteId, ...], day: int, policy: PathPolicy
        ) -> dict[RouteId, str] | None:
            """Choose one owned carrier definition that can keep cargo onboard."""
            if not path:
                return {}
            origin = self.routes[path[0]].origin_id
            candidates: list[DefinitionId] = []
            for state in sorted(self.vehicles.values(), key=lambda row: str(row.id)):
                definition = self.vehicle_defs[state.definition_id]
                if (
                    state.location_id != origin
                    or state.status != VehicleStatus.AVAILABLE
                    or state.available_day > day
                    or any(
                        definition.route_asset_disposition(self.routes[route_id])
                        is not OperationAssetDisposition.DESTINATION
                        for route_id in path
                    )
                ):
                    continue
                if all(
                    not self.route_failures(route_id, day)
                    and not self.vehicle_route_failures(route_id, definition.id, day)
                    for route_id in path
                ):
                    candidates.append(definition.id)
            if not candidates:
                return None
            chosen = min(
                candidates,
                key=lambda definition_id: (
                    sum(self._mode_policy_score(route_id, str(definition_id), day, policy) for route_id in path),
                    str(definition_id),
                ),
            )
            return {route_id: str(chosen) for route_id in path}

        def _staged_vehicle_plan(
            self, path: tuple[RouteId, ...], day: int, policy: PathPolicy
        ) -> dict[RouteId, str] | None:
            """Plan a recoverable first-stage carrier with an onboard onward vehicle.

            The onward vehicle is integrated at the original departure node and is
            carried through the first leg. Handoff therefore needs no waypoint cargo
            terminal; it is a vehicle separation inside one TransportMission.
            """
            if len(path) < 2:
                return None
            origin = self.routes[path[0]].origin_id
            first_route = self.routes[path[0]]
            first_candidates: list[DefinitionId] = []
            onward_candidates: list[DefinitionId] = []
            for state in sorted(self.vehicles.values(), key=lambda row: str(row.id)):
                definition = self.vehicle_defs[state.definition_id]
                if state.location_id != origin or state.status != VehicleStatus.AVAILABLE or state.available_day > day:
                    continue
                if (
                    definition.route_asset_disposition(first_route) is OperationAssetDisposition.ORIGIN
                    and not self.vehicle_route_failures(first_route.id, definition.id, day)
                ):
                    first_candidates.append(definition.id)
                if (
                    all(
                        definition.route_asset_disposition(self.routes[route_id])
                        is OperationAssetDisposition.DESTINATION
                        and not self.vehicle_route_failures(route_id, definition.id, day)
                        for route_id in path[1:]
                    )
                ):
                    onward_candidates.append(definition.id)
            combinations: list[tuple[float, str, str, DefinitionId, DefinitionId]] = []
            for first_id in first_candidates:
                first = self.vehicle_defs[first_id]
                for onward_id in onward_candidates:
                    onward = self.vehicle_defs[onward_id]
                    # Leave at least some payload margin beyond the carried vehicle itself.
                    carried_vehicle_mass = onward.dry_mass_t
                    if carried_vehicle_mass + 1e-9 >= first.max_cargo_for_route(first_route):
                        continue
                    score = self._mode_policy_score(path[0], str(first_id), day, policy)
                    score += sum(self._mode_policy_score(route_id, str(onward_id), day, policy) for route_id in path[1:])
                    combinations.append((score, str(first_id), str(onward_id), first_id, onward_id))
            if not combinations:
                return None
            _, _, _, first_id, onward_id = min(combinations)
            return {path[0]: str(first_id), **{route_id: str(onward_id) for route_id in path[1:]}}

        def _automatic_mode_plan(
            self, path: tuple[RouteId, ...], day: int, policy: PathPolicy = PathPolicy.FASTEST
        ) -> dict[RouteId, str] | None:
            """Build an executable mode plan for an automatically selected path.

            Transfer nodes require actual cargo-transfer service. If any interchange
            lacks it, a single persistent owned carrier must cover the whole path.
            Otherwise each leg is assigned the best currently existing mode under
            the requested policy. The selected plan is stored on the cargo order, so
            it will not silently switch policies later.
            """
            if not path:
                return {}
            # Candidate routes only need a physically defined mode here. Actual
            # executable capacity is evaluated for the whole mission plan below,
            # so an onward spacecraft carried from the original departure node can
            # satisfy a later leg without being pre-positioned at that waypoint.
            if any(not self._route_has_physical_mode(route_id, day) for route_id in path):
                return None
            missing_transfer = any(
                not self._has_available_capability(self.routes[path[index]].destination_id, "cargo_transfer", day)
                for index in range(len(path) - 1)
            )
            if missing_transfer:
                continuous = self._continuous_vehicle_plan(path, day, policy)
                if continuous is not None:
                    return continuous
                return self._staged_vehicle_plan(path, day, policy)
            selected: dict[RouteId, str] = {}
            for route_id in path:
                mode_id = self._best_mode_for_route(route_id, day, policy)
                if mode_id is None:
                    return None
                selected[route_id] = mode_id
            return selected

        def _candidate_paths(
            self, source: SpatialNodeId, destination: SpatialNodeId, day: int
        ) -> tuple[tuple[RouteId, ...], ...]:
            graph: dict[SpatialNodeId, list[RouteDef]] = {}
            for route in sorted(self.routes.values(), key=lambda row: str(row.id)):
                if self._route_has_physical_mode(route.id, day):
                    graph.setdefault(route.origin_id, []).append(route)
            results: list[tuple[RouteId, ...]] = []
            max_depth = max(1, len(self.facilities.environment.graph.nodes))

            def visit(node: SpatialNodeId, visited: frozenset[SpatialNodeId], path: tuple[RouteId, ...]) -> None:
                if len(path) > max_depth:
                    return
                if node == destination:
                    results.append(path)
                    return
                for route in graph.get(node, []):
                    if route.destination_id in visited:
                        continue
                    visit(route.destination_id, visited | {route.destination_id}, path + (route.id,))

            visit(source, frozenset({source}), ())
            return tuple(results)

        def _path_score(self, path: tuple[RouteId, ...], day: int, policy: PathPolicy) -> float:
            plan = self._automatic_mode_plan(path, day, policy)
            if plan is None:
                return float("inf")
            return sum(self._mode_policy_score(route_id, plan[route_id], day, policy) for route_id in path)

        def find_path(
            self, source: SpatialNodeId, destination: SpatialNodeId, day: int = 0,
            policy: PathPolicy = PathPolicy.FASTEST,
        ) -> tuple[RouteId, ...]:
            candidates = [
                path for path in self._candidate_paths(source, destination, day)
                if self._automatic_mode_plan(path, day, policy) is not None
            ]
            if not candidates:
                raise ValueError(f"no route path {source} -> {destination}")
            return min(candidates, key=lambda path: (self._path_score(path, day, policy), tuple(map(str, path))))

        def find_fastest_path(self, source: SpatialNodeId, destination: SpatialNodeId, day: int = 0) -> tuple[RouteId, ...]:
            return self.find_path(source, destination, day, PathPolicy.FASTEST)

        def validate_path_structure(self, source: SpatialNodeId, destination: SpatialNodeId, path: tuple[RouteId, ...]) -> None:
            current = source
            for route_id in path:
                route = self.routes[route_id]
                if route.origin_id != current:
                    raise ValueError("cargo path is not contiguous")
                current = route.destination_id
            if current != destination:
                raise ValueError("cargo path does not reach destination")

        def validate_mode_selection(
            self, path: tuple[RouteId, ...], mode_by_route: dict[RouteId, str], *, day: int = 0
        ) -> None:
            extra = set(mode_by_route) - set(path)
            if extra:
                raise ValueError(f"transport mode specified for route outside path: {sorted(map(str, extra))}")
            for route_id, mode_id in mode_by_route.items():
                if not self._mode_is_defined_for_route(route_id, mode_id, day):
                    raise ValueError(f"unsupported transport mode for route: {route_id}/{mode_id}")

        def validate_path(
            self, source: SpatialNodeId, destination: SpatialNodeId, path: tuple[RouteId, ...], day: int = 0,
            mode_by_route: dict[RouteId, str] | None = None,
        ) -> None:
            self.validate_path_structure(source, destination, path)
            selected_modes = {} if mode_by_route is None else mode_by_route
            self.validate_mode_selection(path, selected_modes, day=day)
            for route_id in path:
                if not self._route_has_physical_mode(route_id, day):
                    raise ValueError("cargo path contains route with no compatible transport mode")
