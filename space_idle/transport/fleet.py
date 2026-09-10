from __future__ import annotations

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import VehicleDisposition, VehicleStatus, RouteDef, VehicleDef, VehicleState, TransportMissionState


class FleetManagementMixin:
        def add_vehicle(self, definition_id: DefinitionId, location_id: SpatialNodeId) -> EntityId:
            if definition_id not in self.vehicle_defs:
                raise KeyError(definition_id)
            if location_id not in self.facilities.environment.graph.nodes:
                raise KeyError(location_id)
            self._vehicle_counter += 1
            vehicle_id = EntityId(f"vehicle.{self._vehicle_counter}")
            self.vehicles[vehicle_id] = VehicleState(vehicle_id, definition_id, location_id)
            return vehicle_id

        def add_vehicles(self, definition_id: DefinitionId, count: int, location_id: SpatialNodeId) -> tuple[EntityId, ...]:
            if count < 0:
                raise ValueError("vehicle count must be non-negative")
            return tuple(self.add_vehicle(definition_id, location_id) for _ in range(count))

        def refuel_vehicle(self, vehicle_id: EntityId, amount_t: float | None = None, day: int = 0) -> float:
            """Load propellant from the current node into a stationary vehicle tank."""
            self._refresh_vehicle_states(day)
            state = self.vehicles[vehicle_id]
            definition = self.vehicle_defs[state.definition_id]
            if state.location_id is None or state.status != VehicleStatus.AVAILABLE or state.available_day > day:
                raise ValueError("vehicle is not stationary and available")
            if definition.propellant_resource_id is None or definition.propellant_capacity_t <= 1e-12:
                raise ValueError("vehicle has no refuellable propellant tank")
            if not self._has_available_capability(state.location_id, "vehicle_refueling", day):
                raise ValueError("vehicle refueling infrastructure is unavailable")
            free_capacity = max(0.0, definition.propellant_capacity_t - state.propellant_t)
            available_stock = self.inventory.available(state.location_id, definition.propellant_resource_id)
            requested = min(free_capacity, available_stock) if amount_t is None else amount_t
            if requested < -1e-12:
                raise ValueError("refuel amount must be non-negative")
            load = min(free_capacity, max(0.0, requested))
            if load <= 1e-12:
                return 0.0
            if not self.inventory.take_unreserved(state.location_id, definition.propellant_resource_id, load):
                raise ValueError("insufficient propellant inventory at vehicle location")
            state.propellant_t += load
            return load

        def _refresh_vehicle_states(self, day: int) -> None:
            for state in self.vehicles.values():
                definition = self.vehicle_defs[state.definition_id]
                if state.status == VehicleStatus.TRANSIT_RETURN and state.location_id is not None and state.available_day <= day:
                    self._start_turnaround(state, definition, state.location_id, day)
                if state.status == VehicleStatus.MAINTENANCE_WAIT and state.location_id is not None:
                    self._start_turnaround(state, definition, state.location_id, day)
                if state.status == VehicleStatus.TURNAROUND and state.available_day <= day:
                    state.status = VehicleStatus.AVAILABLE

        def vehicle_blockers(self, vehicle_id: EntityId, day: int = 0) -> tuple[str, ...]:
            self._refresh_vehicle_states(day)
            state = self.vehicles[vehicle_id]
            definition = self.vehicle_defs[state.definition_id]
            if state.status == VehicleStatus.AVAILABLE:
                return ()
            if state.status == VehicleStatus.MAINTENANCE_WAIT and state.location_id is not None:
                blockers: list[str] = []
                required = definition.turnaround_capability_id
                if required is not None and not self._has_available_capability(state.location_id, required, day):
                    blockers.append(f"maintenance_capability:{required}")
                if self.account.funds_musd + 1e-12 < definition.turnaround_cost_musd:
                    blockers.append("maintenance_funds")
                for resource_id, amount_t in definition.turnaround_resources:
                    if self.inventory.available(state.location_id, resource_id) + 1e-12 < amount_t:
                        blockers.append(f"maintenance_resource:{resource_id}")
                return tuple(blockers) or (VehicleStatus.MAINTENANCE_WAIT,)
            if state.status == VehicleStatus.TURNAROUND:
                return (f"turnaround_until:{state.available_day}",)
            if state.status == VehicleStatus.UNLOADING:
                return ("destination_unloading",)
            if state.status in {VehicleStatus.TRANSIT, VehicleStatus.TRANSIT_RETURN}:
                return (state.status,)
            if state.status == VehicleStatus.WAYPOINT_WAIT:
                return (VehicleStatus.WAYPOINT_WAIT,)
            return (state.status,)

        def available_vehicle_ids(
            self, route_id: RouteId, vehicle_definition_id: DefinitionId, day: int = 0
        ) -> tuple[EntityId, ...]:
            self._refresh_vehicle_states(day)
            route = self.routes[route_id]
            if self.vehicle_route_failures(route_id, vehicle_definition_id, day):
                return ()
            return tuple(
                state.id
                for state in sorted(self.vehicles.values(), key=lambda row: str(row.id))
                if state.definition_id == vehicle_definition_id
                and state.location_id == route.origin_id
                and state.status == VehicleStatus.AVAILABLE
                and state.available_day <= day
            )

        def vehicle_counts(self, definition_id: DefinitionId) -> tuple[int, int]:
            states = [row for row in self.vehicles.values() if row.definition_id == definition_id]
            available = sum(1 for row in states if row.status == VehicleStatus.AVAILABLE)
            return len(states), available

        def exclusive_assignment_failures(
            self,
            vehicle_id: EntityId,
            required_location_id: SpatialNodeId,
            day: int = 0,
        ) -> tuple[str, ...]:
            """Return blockers for handing a vehicle to another Domain exclusively."""
            self._refresh_vehicle_states(day)
            if vehicle_id not in self.vehicles:
                return ("unknown_vehicle",)
            state = self.vehicles[vehicle_id]
            failures: list[str] = []
            if state.status is not VehicleStatus.AVAILABLE:
                failures.append(f"vehicle_status:{state.status.value}")
            if state.available_day > day:
                failures.append(f"vehicle_available_day:{state.available_day}")
            if state.location_id != required_location_id:
                failures.append(f"vehicle_location:{state.location_id}/{required_location_id}")
            if state.assignment_id is not None:
                failures.append(f"vehicle_assignment:{state.assignment_id}")
            return tuple(failures)

        def assign_vehicle_exclusively(
            self,
            vehicle_id: EntityId,
            assignment_id: EntityId,
            assignment_kind: str,
            required_location_id: SpatialNodeId,
            day: int = 0,
        ) -> None:
            """Transfer a vehicle to one external activity without knowing that activity's Domain."""
            if not assignment_kind:
                raise ValueError("vehicle assignment kind must be non-empty")
            failures = self.exclusive_assignment_failures(
                vehicle_id, required_location_id, day
            )
            if failures:
                raise ValueError("vehicle is unavailable for assignment: " + "; ".join(failures))
            state = self.vehicles[vehicle_id]
            state.status = VehicleStatus.ASSIGNED
            state.assignment_id = assignment_id
            state.assignment_kind = assignment_kind

        def move_assigned_vehicle(
            self,
            vehicle_id: EntityId,
            assignment_id: EntityId,
            destination_id: SpatialNodeId,
        ) -> None:
            """Record an assigned activity taking a vehicle away from its current node."""
            state = self.vehicles[vehicle_id]
            if state.assignment_id != assignment_id:
                raise ValueError("vehicle assignment owner mismatch")
            if state.status is not VehicleStatus.ASSIGNED:
                raise ValueError("vehicle is not in an assigned activity state")
            if destination_id not in self.facilities.environment.graph.nodes:
                raise KeyError(destination_id)
            state.location_id = None
            state.transit_destination_id = destination_id

        def release_vehicle_assignment(
            self,
            vehicle_id: EntityId,
            assignment_id: EntityId,
            final_location_id: SpatialNodeId,
            *,
            available_day: int | None = None,
        ) -> None:
            """Return an exclusively assigned vehicle to normal Fleet availability."""
            state = self.vehicles[vehicle_id]
            if state.assignment_id != assignment_id:
                raise ValueError("vehicle assignment owner mismatch")
            if final_location_id not in self.facilities.environment.graph.nodes:
                raise KeyError(final_location_id)
            state.location_id = final_location_id
            state.transit_destination_id = None
            state.assignment_id = None
            state.assignment_kind = None
            state.status = VehicleStatus.AVAILABLE
            if available_day is not None:
                state.available_day = available_day

        def _turnaround_requirements_available(
            self, definition: VehicleDef, location_id: SpatialNodeId, day: int
        ) -> bool:
            required = definition.turnaround_capability_id
            if required is not None and not self._has_available_capability(location_id, required, day):
                return False
            if self.account.funds_musd + 1e-12 < definition.turnaround_cost_musd:
                return False
            return all(
                self.inventory.available(location_id, resource_id) + 1e-12 >= amount_t
                for resource_id, amount_t in definition.turnaround_resources
            )

        def _consume_turnaround_requirements(
            self, definition: VehicleDef, location_id: SpatialNodeId, day: int
        ) -> bool:
            if not self._turnaround_requirements_available(definition, location_id, day):
                return False
            if not self.account.spend(definition.turnaround_cost_musd):
                return False
            consumed: list[tuple[DefinitionId, float]] = []
            for resource_id, amount_t in definition.turnaround_resources:
                if amount_t <= 1e-12:
                    continue
                if not self.inventory.take_unreserved(location_id, resource_id, amount_t):
                    for restore_id, restore_amount in consumed:
                        self.inventory.add(location_id, restore_id, restore_amount)
                    self.account.earn(definition.turnaround_cost_musd)
                    return False
                consumed.append((resource_id, amount_t))
            return True

        def _start_turnaround(self, state: VehicleState, definition: VehicleDef, location_id: SpatialNodeId, day: int) -> None:
            state.location_id = location_id
            state.transit_destination_id = None
            if not self._consume_turnaround_requirements(definition, location_id, day):
                state.status = VehicleStatus.MAINTENANCE_WAIT
                state.available_day = day
                return
            if definition.turnaround_days <= 1e-12:
                state.status = VehicleStatus.AVAILABLE
                state.available_day = day
                return
            state.status = VehicleStatus.TURNAROUND
            state.available_day = day + max(1, round(definition.turnaround_days))

        def _finish_mission_vehicle(self, mission: TransportMissionState, route: RouteDef, day: int, blocked: bool = False) -> None:
            if mission.vehicle_id is None:
                return
            state = self.vehicles[mission.vehicle_id]
            definition = self.vehicle_defs[state.definition_id]
            if mission.vehicle_disposition is VehicleDisposition.RETURN_TO_ORIGIN:
                # A returned carrier is released from the cargo mission once. Cargo
                # may remain arrival-waiting for storage without resetting vehicle
                # maintenance every simulation day.
                if state.status in {VehicleStatus.TURNAROUND, VehicleStatus.MAINTENANCE_WAIT, VehicleStatus.AVAILABLE}:
                    return
                location_id = route.origin_id
                self._start_turnaround(state, definition, location_id, day)
                return
            state.location_id = route.destination_id
            state.transit_destination_id = None
            if blocked:
                if state.status != VehicleStatus.UNLOADING:
                    state.status = VehicleStatus.UNLOADING
                    state.available_day = day
            else:
                self._start_turnaround(state, definition, route.destination_id, day)
