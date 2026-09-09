from __future__ import annotations

from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import VehicleDisposition, VehicleStatus, MissionStatus, RouteDef, VehicleDef, VehicleState, TransportMissionState, CargoOrder, VehicleTransit


class TransportExecutionMixin:
        @property
        def in_transit(self) -> tuple[TransportMissionState, ...]:
            """Compatibility/query view over active transport missions."""
            return tuple(self.missions.values())

        def _new_mission(
            self, order_id: CargoOrderId, leg_index: int, amount_t: float, mode_id: str,
            day: int, arrival_day: int, vehicle_id: EntityId | None = None,
            disposition: VehicleDisposition = VehicleDisposition.DESTINATION,
            handoff_vehicle_id: EntityId | None = None,
        ) -> TransportMissionState:
            self._mission_counter += 1
            mission_id = EntityId(f"transport_mission.{self._mission_counter}")
            mission = TransportMissionState(
                mission_id, order_id, leg_index, amount_t, mode_id, day, arrival_day,
                vehicle_id, disposition, MissionStatus.IN_TRANSIT, True, handoff_vehicle_id,
            )
            self.missions[mission_id] = mission
            return mission

        def _external_service_remaining_capacity(self, service_id: DefinitionId, day: int) -> float:
            service = self.external_services[service_id]
            used = sum(
                mission.amount_t
                for mission in self.missions.values()
                if mission.mode_id == str(service_id)
                and mission.departure_day == day
                and mission.status == MissionStatus.IN_TRANSIT
            )
            return max(0.0, service.capacity_t_per_day - used)

        def _arrival_waiting(self, route_id: RouteId, mode_id: str, day: int) -> float:
            return sum(
                mission.amount_t
                for mission in self.missions.values()
                if mission.arrival_day <= day
                and mission.mode_id == mode_id
                and mission.status in {MissionStatus.ARRIVAL_WAITING, MissionStatus.WAYPOINT_WAIT}
                and mission.leg_index < len(self.orders[mission.order_id].path)
                and self.orders[mission.order_id].path[mission.leg_index] == route_id
            )

        def order_blockers(self, order_id: CargoOrderId, day: int = 0) -> tuple[str, ...]:
            if self.order_complete(order_id):
                return ()
            order = self.orders[order_id]
            blockers: list[str] = []
            for mission in self.missions.values():
                if mission.order_id != order_id or mission.arrival_day > day:
                    continue
                route_id = order.path[mission.leg_index]
                next_leg = mission.leg_index + 1
                if mission.status == MissionStatus.WAYPOINT_WAIT:
                    blockers.append(f"route:{route_id}:onboard_waypoint_wait")
                elif next_leg >= len(order.path):
                    blockers.append(f"route:{route_id}:destination_storage")
                else:
                    transfer_node = self.routes[route_id].destination_id
                    if not self._has_available_capability(transfer_node, "cargo_transfer", day):
                        blockers.append(f"route:{route_id}:cargo_transfer_infrastructure")
                    else:
                        blockers.append(f"route:{route_id}:transfer_storage")
            for (waiting_order_id, leg_index), mass in self.waiting.items():
                if waiting_order_id != order_id or mass <= 1e-12 or leg_index >= len(order.path):
                    continue
                route_id = order.path[leg_index]
                blockers.extend(
                    f"route:{route_id}:{reason}"
                    for reason in self.route_operational_failures(route_id, day, order.mode_by_route.get(route_id))
                )
            return tuple(dict.fromkeys(blockers))

        def _can_continue_same_vehicle(
            self, mission: TransportMissionState, order: CargoOrder, next_leg: int, day: int
        ) -> bool:
            if mission.vehicle_id is None or mission.vehicle_disposition is not VehicleDisposition.DESTINATION:
                return False
            state = self.vehicles[mission.vehicle_id]
            definition = self.vehicle_defs[state.definition_id]
            next_route_id = order.path[next_leg]
            next_route = self.routes[next_route_id]
            selected_mode = order.mode_by_route.get(next_route_id)
            if selected_mode is not None and selected_mode != str(definition.id):
                return False
            if self.route_failures(next_route_id, day) or self.vehicle_route_failures(next_route_id, definition.id, day):
                return False
            if mission.amount_t > definition.max_cargo_for_route(next_route) + 1e-9:
                return False
            return True

        def _continue_mission_same_vehicle(
            self, mission: TransportMissionState, order: CargoOrder, next_leg: int, day: int
        ) -> bool:
            if not self._can_continue_same_vehicle(mission, order, next_leg, day):
                return False
            state = self.vehicles[mission.vehicle_id]  # type: ignore[index]
            definition = self.vehicle_defs[state.definition_id]
            next_route = self.routes[order.path[next_leg]]
            # Vehicle has arrived at this waypoint and may consume onboard fuel or
            # refuel through actual infrastructure without unloading its cargo.
            state.location_id = next_route.origin_id
            state.status = VehicleStatus.WAYPOINT_WAIT
            state.transit_destination_id = None
            if not self._pay_vehicle_mission(state, definition, next_route, mission.amount_t, day):
                mission.status = MissionStatus.WAYPOINT_WAIT
                mission.arrival_day = day
                return False
            transit_days = max(1, round(next_route.transit_days * definition.transit_time_multiplier))
            state.location_id = None
            state.status = VehicleStatus.TRANSIT
            state.transit_destination_id = next_route.destination_id
            mission.leg_index = next_leg
            mission.mode_id = str(definition.id)
            mission.departure_day = day
            mission.arrival_day = day + transit_days
            mission.status = MissionStatus.IN_TRANSIT
            mission.vehicle_disposition = definition.default_disposition
            return True

        def _attempt_mission_arrival(self, mission: TransportMissionState, through_day: int) -> bool:
            """Process one mission. Return True when mission remains active."""
            if mission.status == MissionStatus.IN_TRANSIT and mission.arrival_day > through_day:
                return True
            order = self.orders[mission.order_id]
            route = self.routes[order.path[mission.leg_index]]

            # A carrier that accompanies the payload is physically present at the
            # waypoint before unloading/continuation. A returning carrier is not.
            if mission.vehicle_id is not None and mission.vehicle_disposition is VehicleDisposition.DESTINATION:
                state = self.vehicles[mission.vehicle_id]
                state.location_id = route.destination_id
                state.transit_destination_id = None
                state.status = VehicleStatus.WAYPOINT_WAIT
                state.available_day = through_day

            next_leg = mission.leg_index + 1
            if next_leg < len(order.path):
                if mission.handoff_vehicle_id is not None:
                    handoff_state = self.vehicles[mission.handoff_vehicle_id]
                    handoff_definition = self.vehicle_defs[handoff_state.definition_id]
                    selected_mode = order.mode_by_route.get(order.path[next_leg])
                    if selected_mode == str(handoff_definition.id):
                        # Release the first-stage carrier and continue the same cargo
                        # mission with the vehicle that was integrated as payload.
                        self._finish_mission_vehicle(mission, route, through_day, False)
                        handoff_state.location_id = route.destination_id
                        handoff_state.status = VehicleStatus.WAYPOINT_WAIT
                        handoff_state.transit_destination_id = None
                        handoff_state.available_day = through_day
                        mission.vehicle_id = handoff_state.id
                        mission.handoff_vehicle_id = None
                        mission.vehicle_disposition = handoff_definition.default_disposition
                        if self._continue_mission_same_vehicle(mission, order, next_leg, through_day):
                            return True
                        mission.status = MissionStatus.WAYPOINT_WAIT
                        return True
                if self._can_continue_same_vehicle(mission, order, next_leg, through_day):
                    if self._continue_mission_same_vehicle(mission, order, next_leg, through_day):
                        return True
                    # Same vehicle is the intended continuous carrier, so wait
                    # onboard for fuel/funds rather than silently forcing transfer.
                    return True

                transfer_node = route.destination_id
                if not self._has_available_capability(transfer_node, "cargo_transfer", through_day):
                    mission.status = MissionStatus.ARRIVAL_WAITING
                    self._finish_mission_vehicle(mission, route, through_day, True)
                    return True
                # Cargo transfer is not the same as storage. If the next carrier or
                # service can accept the payload now, hand it over directly and keep
                # the same TransportMission alive without touching node inventory.
                if self._try_direct_transfer_to_next_mode(mission, order, next_leg, through_day):
                    return True
                waiting_owner = self._waiting_owner(order.id, next_leg)
                accepted = self.inventory.occupy_storage(waiting_owner, transfer_node, order.resource_id, mission.amount_t)
                if accepted > 1e-12:
                    key = (order.id, next_leg)
                    self.waiting[key] = self.waiting.get(key, 0.0) + accepted
                remainder = mission.amount_t - accepted
                if remainder > 1e-9:
                    mission.amount_t = remainder
                    mission.status = MissionStatus.ARRIVAL_WAITING
                    self._finish_mission_vehicle(mission, route, through_day, True)
                    return True
                self._finish_mission_vehicle(mission, route, through_day, False)
                return False

            accepted = self.inventory.add_up_to(order.destination_id, order.resource_id, mission.amount_t)
            order.delivered_t += accepted
            remainder = mission.amount_t - accepted
            if remainder > 1e-9:
                mission.amount_t = remainder
                mission.status = MissionStatus.ARRIVAL_WAITING
                self._finish_mission_vehicle(mission, route, through_day, True)
                return True
            self._finish_mission_vehicle(mission, route, through_day, False)
            return False

        def _arrive(self, through_day: int) -> None:
            for mission_id, mission in sorted(
                list(self.missions.items()),
                key=lambda row: (row[1].arrival_day, -self.orders[row[1].order_id].priority, str(row[0])),
            ):
                if not self._attempt_mission_arrival(mission, through_day):
                    self.missions.pop(mission_id, None)

            remaining_vehicle_transit: list[VehicleTransit] = []
            for movement in sorted(self.vehicle_transit, key=lambda row: (row.arrival_day, str(row.vehicle_id))):
                if movement.arrival_day > through_day:
                    remaining_vehicle_transit.append(movement)
                    continue
                state = self.vehicles[movement.vehicle_id]
                definition = self.vehicle_defs[state.definition_id]
                route = self.routes[movement.route_id]
                state.location_id = route.destination_id
                state.transit_destination_id = None
                if movement.used_for_mission:
                    self._start_turnaround(state, definition, route.destination_id, through_day)
                else:
                    state.status = VehicleStatus.AVAILABLE
                    state.available_day = through_day
            self.vehicle_transit = remaining_vehicle_transit

        def _handoff_vehicle_for_leg(
            self, order: CargoOrder, leg_index: int, carrier_state: VehicleState, cargo_t: float, day: int
        ) -> VehicleState | None:
            next_leg = leg_index + 1
            if next_leg >= len(order.path):
                return None
            carrier = self.vehicle_defs[carrier_state.definition_id]
            if carrier.default_disposition is not VehicleDisposition.RETURN_TO_ORIGIN:
                return None
            next_route_id = order.path[next_leg]
            mode_id = order.mode_by_route.get(next_route_id)
            if mode_id is None or self._service_for_mode(mode_id) is not None:
                return None
            definition_id = DefinitionId(mode_id)
            if definition_id not in self.vehicle_defs:
                return None
            onward = self.vehicle_defs[definition_id]
            if onward.default_disposition is not VehicleDisposition.DESTINATION:
                return None
            if self.vehicle_route_failures(next_route_id, definition_id, day):
                return None
            if cargo_t > onward.max_cargo_for_route(self.routes[next_route_id]) + 1e-9:
                return None
            for state in sorted(self.vehicles.values(), key=lambda row: str(row.id)):
                if state.id == carrier_state.id or state.definition_id != definition_id:
                    continue
                if (
                    state.location_id == self.routes[order.path[leg_index]].origin_id
                    and state.status == VehicleStatus.AVAILABLE
                    and state.available_day <= day
                ):
                    total_payload = cargo_t + onward.dry_mass_t + state.propellant_t
                    if total_payload <= carrier.max_cargo_for_route(self.routes[order.path[leg_index]]) + 1e-9:
                        return state
            return None

        def _prepare_owned_vehicle_departure(
            self, state: VehicleState, route: RouteDef, day: int, order: CargoOrder, leg_index: int, cargo_t: float
        ) -> tuple[VehicleDisposition, VehicleState | None, int] | None:
            definition = self.vehicle_defs[state.definition_id]
            handoff_state = self._handoff_vehicle_for_leg(order, leg_index, state, cargo_t, day)
            next_leg = leg_index + 1
            if next_leg < len(order.path):
                next_mode = order.mode_by_route.get(order.path[next_leg])
                same_carrier_selected = next_mode in {None, str(definition.id)}
                transfer_node = route.destination_id
                if (
                    not same_carrier_selected
                    and handoff_state is None
                    and not self._has_available_capability(transfer_node, "cargo_transfer", day)
                ):
                    return None
            payload_mass = cargo_t
            if handoff_state is not None:
                handoff_definition = self.vehicle_defs[handoff_state.definition_id]
                payload_mass += handoff_definition.dry_mass_t + handoff_state.propellant_t
            if payload_mass > definition.max_cargo_for_route(route) + 1e-9:
                return None
            if not self._pay_vehicle_mission(state, definition, route, payload_mass, day):
                return None
            transit_days = max(1, round(route.transit_days * definition.transit_time_multiplier))
            disposition = definition.default_disposition
            if disposition is VehicleDisposition.DESTINATION:
                state.location_id = None
                state.status = VehicleStatus.TRANSIT
                state.transit_destination_id = route.destination_id
            else:
                state.status = VehicleStatus.TRANSIT_RETURN
                state.available_day = day + transit_days
                state.transit_destination_id = None
            if handoff_state is not None:
                handoff_state.location_id = None
                handoff_state.status = VehicleStatus.TRANSIT
                handoff_state.transit_destination_id = route.destination_id
            return disposition, handoff_state, transit_days

        def _dispatch_owned_vehicle(
            self, state: VehicleState, route: RouteDef, day: int, order_id: CargoOrderId, leg_index: int, cargo_t: float
        ) -> bool:
            order = self.orders[order_id]
            prepared = self._prepare_owned_vehicle_departure(state, route, day, order, leg_index, cargo_t)
            if prepared is None:
                return False
            disposition, handoff_state, transit_days = prepared
            self._new_mission(
                order_id, leg_index, cargo_t, str(self.vehicle_defs[state.definition_id].id), day, day + transit_days,
                state.id, disposition, None if handoff_state is None else handoff_state.id,
            )
            return True

        def _try_direct_transfer_to_next_mode(
            self, mission: TransportMissionState, order: CargoOrder, next_leg: int, day: int
        ) -> bool:
            next_route_id = order.path[next_leg]
            next_route = self.routes[next_route_id]
            mode_id = order.mode_by_route.get(next_route_id)
            if mode_id is None:
                mode_id = self._best_mode_for_route(next_route_id, day, order.path_policy)
            if mode_id is None or self.route_operational_failures(next_route_id, day, mode_id):
                return False

            service = self._service_for_mode(mode_id)
            if service is not None:
                if self._external_service_remaining_capacity(service.id, day) + 1e-12 < mission.amount_t:
                    return False
                cost = mission.amount_t * service.cost_musd_per_t
                if not self.account.spend(cost):
                    return False
                old_route = self.routes[order.path[mission.leg_index]]
                self._finish_mission_vehicle(mission, old_route, day, False)
                transit_days = self.route_mode_transit_days(next_route_id, mode_id, day)
                mission.leg_index = next_leg
                mission.mode_id = mode_id
                mission.departure_day = day
                mission.arrival_day = day + transit_days
                mission.vehicle_id = None
                mission.handoff_vehicle_id = None
                mission.vehicle_disposition = VehicleDisposition.DESTINATION
                mission.status = MissionStatus.IN_TRANSIT
                mission.onboard = True
                return True

            definition_id = DefinitionId(mode_id)
            for vehicle_id in self.available_vehicle_ids(next_route_id, definition_id, day):
                state = self.vehicles[vehicle_id]
                prepared = self._prepare_owned_vehicle_departure(
                    state, next_route, day, order, next_leg, mission.amount_t
                )
                if prepared is None:
                    continue
                disposition, handoff_state, transit_days = prepared
                old_route = self.routes[order.path[mission.leg_index]]
                self._finish_mission_vehicle(mission, old_route, day, False)
                mission.leg_index = next_leg
                mission.mode_id = mode_id
                mission.departure_day = day
                mission.arrival_day = day + transit_days
                mission.vehicle_id = state.id
                mission.handoff_vehicle_id = None if handoff_state is None else handoff_state.id
                mission.vehicle_disposition = disposition
                mission.status = MissionStatus.IN_TRANSIT
                mission.onboard = True
                return True
            return False

        def dispatch_vehicle(
            self,
            vehicle_id: EntityId,
            route_id: RouteId,
            day: int = 0,
            carrier_vehicle_id: EntityId | None = None,
        ) -> None:
            """Move a vehicle under its own power or as another vehicle's payload.

            Carrier outcome is controlled by physical mission disposition rather
            than by LaunchVehicle/Spacecraft class identity.
            """
            self._refresh_vehicle_states(day)
            state = self.vehicles[vehicle_id]
            definition = self.vehicle_defs[state.definition_id]
            route = self.routes[route_id]
            if carrier_vehicle_id is not None:
                if carrier_vehicle_id == vehicle_id:
                    raise ValueError("vehicle cannot carry itself")
                carrier_state = self.vehicles[carrier_vehicle_id]
                carrier = self.vehicle_defs[carrier_state.definition_id]
                if state.location_id != route.origin_id or state.status != VehicleStatus.AVAILABLE or state.available_day > day:
                    raise ValueError("payload vehicle is not available at route origin")
                if carrier_state.location_id != route.origin_id or carrier_state.status != VehicleStatus.AVAILABLE or carrier_state.available_day > day:
                    raise ValueError("carrier vehicle is not available at route origin")
                failures = self.route_failures(route_id, day) + self.vehicle_route_failures(route_id, carrier_state.definition_id, day)
                if failures:
                    raise ValueError("carrier does not satisfy route requirements: " + ",".join(failures))
                transport_mass_t = definition.dry_mass_t + state.propellant_t
                if transport_mass_t > carrier.max_cargo_for_route(route) + 1e-9:
                    raise ValueError("payload vehicle exceeds carrier capacity for route")
                if not self._pay_vehicle_mission(carrier_state, carrier, route, transport_mass_t, day):
                    raise ValueError("insufficient funds, propellant, or refueling infrastructure for carrier movement")
                transit_days = max(1, round(route.transit_days * carrier.transit_time_multiplier))
                if carrier.default_disposition is VehicleDisposition.DESTINATION:
                    carrier_state.location_id = None
                    carrier_state.status = VehicleStatus.TRANSIT
                    carrier_state.transit_destination_id = route.destination_id
                    self.vehicle_transit.append(VehicleTransit(carrier_vehicle_id, route_id, day + transit_days, True))
                else:
                    carrier_state.status = VehicleStatus.TRANSIT_RETURN
                    carrier_state.available_day = day + transit_days
                    carrier_state.transit_destination_id = None
                state.location_id = None
                state.status = VehicleStatus.TRANSIT
                state.transit_destination_id = route.destination_id
                self.vehicle_transit.append(VehicleTransit(vehicle_id, route_id, day + transit_days, False))
                return
            if definition.default_disposition is not VehicleDisposition.DESTINATION:
                raise ValueError("vehicle mission profile returns to origin; use it as a carrier rather than repositioning it")
            if state.location_id != route.origin_id or state.status != VehicleStatus.AVAILABLE or state.available_day > day:
                raise ValueError("vehicle is not available at route origin")
            failures = self.route_failures(route_id, day) + self.vehicle_route_failures(route_id, state.definition_id, day)
            if failures:
                raise ValueError("vehicle does not satisfy route requirements: " + ",".join(failures))
            if not self._pay_vehicle_mission(state, definition, route, 0.0, day):
                raise ValueError("insufficient funds, propellant, or refueling infrastructure for vehicle movement")
            state.location_id = None
            state.status = VehicleStatus.TRANSIT
            state.transit_destination_id = route.destination_id
            transit_days = max(1, round(route.transit_days * definition.transit_time_multiplier))
            self.vehicle_transit.append(VehicleTransit(vehicle_id, route_id, day + transit_days))

        def _move_waiting_by_priority(self, day: int) -> None:
            self._refresh_vehicle_states(day)
            external_capacity: dict[str, float] = {
                str(service.id): service.capacity_t_per_day
                for service in self.external_services.values()
                if service.capacity_t_per_day > 1e-12
            }

            candidates = [
                (-self.orders[order_id].priority, str(order_id), order_id, leg_index)
                for (order_id, leg_index), mass in self.waiting.items()
                if mass > 1e-12 and leg_index < len(self.orders[order_id].path)
            ]
            used_vehicle_ids: set[EntityId] = set()
            for _neg_priority, _stable_id, order_id, leg_index in sorted(candidates):
                key_waiting = (order_id, leg_index)
                mass = self.waiting.get(key_waiting, 0.0)
                if mass <= 1e-12:
                    continue
                order = self.orders[order_id]
                route_id = order.path[leg_index]
                route = self.routes[route_id]
                selected_mode_id = order.mode_by_route.get(route_id)
                for mode in self._selected_modes(route_id, day, selected_mode_id):
                    if mass <= 1e-12:
                        break
                    if mode.vehicle_definition_id is None:
                        capacity = external_capacity.get(mode.mode_id, 0.0)
                        if capacity <= 1e-12:
                            continue
                        affordable = self.account.funds_musd / mode.cost_musd_per_t if mode.cost_musd_per_t > 0 else mass
                        moved = min(capacity, mass, affordable)
                        if moved <= 1e-12 or self._arrival_waiting(route_id, mode.mode_id, day) > 1e-12:
                            continue
                        cost = moved * mode.cost_musd_per_t
                        if not self.account.spend(cost):
                            continue
                        owner = self._waiting_owner(order_id, leg_index)
                        self.inventory.release_storage_occupancy(owner, route.origin_id, order.resource_id, moved)
                        mass -= moved
                        self.waiting[key_waiting] = mass
                        external_capacity[mode.mode_id] = capacity - moved
                        transit_days = self.route_mode_transit_days(route_id, mode.mode_id, day)
                        self._new_mission(order_id, leg_index, moved, mode.mode_id, day, day + transit_days)
                        continue

                    definition = self.vehicle_defs[mode.vehicle_definition_id]
                    for vehicle_id in mode.available_vehicle_ids:
                        if mass <= 1e-12:
                            break
                        if vehicle_id in used_vehicle_ids:
                            continue
                        state = self.vehicles[vehicle_id]
                        moved = min(definition.max_cargo_for_route(route), mass)
                        if moved <= 1e-12:
                            continue
                        if not self._dispatch_owned_vehicle(state, route, day, order_id, leg_index, moved):
                            continue
                        owner = self._waiting_owner(order_id, leg_index)
                        self.inventory.release_storage_occupancy(owner, route.origin_id, order.resource_id, moved)
                        mass -= moved
                        self.waiting[key_waiting] = mass
                        used_vehicle_ids.add(vehicle_id)

        def advance_day(self, day: int) -> None:
            self._move_waiting_by_priority(day)
            self._arrive(day + 1)
            self.waiting = {key: value for key, value in self.waiting.items() if value > 1e-9}
            self._advance_vehicle_production(day)
            self._refresh_vehicle_states(day + 1)
