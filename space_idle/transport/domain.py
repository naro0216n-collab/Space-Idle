from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import (
    ValidationContext,
    require as _require,
    validate_site_requirements as _validate_site_requirements,
)
from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import (
    CargoOrder,
    LogisticsLane,
    MissionStatus,
    PathPolicy,
    TransportMissionState,
    VehicleDisposition,
    VehicleState,
    VehicleStatus,
    VehicleTransit,
)


def capture_logistics(sim: Any) -> dict[str, Any]:
    lg = sim.logistics
    return {
        "counter": lg._counter,
        "lane_counter": lg._lane_counter,
        "vehicle_counter": lg._vehicle_counter,
        "mission_counter": lg._mission_counter,
        "vehicles": [
            {
                "id": str(s.id),
                "definition_id": str(s.definition_id),
                "location_id": None if s.location_id is None else str(s.location_id),
                "status": s.status.value,
                "available_day": s.available_day,
                "transit_destination_id": None if s.transit_destination_id is None else str(s.transit_destination_id),
                "propellant_t": s.propellant_t,
            }
            for s in sorted(lg.vehicles.values(), key=lambda row: str(row.id))
        ],
        "vehicle_transit": [
            {
                "vehicle_id": str(r.vehicle_id),
                "route_id": str(r.route_id),
                "arrival_day": r.arrival_day,
                "used_for_mission": r.used_for_mission,
            }
            for r in sorted(lg.vehicle_transit, key=lambda row: (row.arrival_day, str(row.vehicle_id)))
        ],
        "lanes": [
            {
                "id": str(lane.id),
                "source_id": str(lane.source_id),
                "destination_id": str(lane.destination_id),
                "requested_capacity_t_per_day": lane.requested_capacity_t_per_day,
                "priority": lane.priority,
                "path": None if lane.path is None else [str(route_id) for route_id in lane.path],
                "mode_by_route": {
                    str(route_id): mode_id
                    for route_id, mode_id in sorted(lane.mode_by_route.items(), key=lambda row: str(row[0]))
                },
                "path_policy": lane.path_policy.value,
                "paused": lane.paused,
            }
            for lane in sorted(lg.lanes.values(), key=lambda row: str(row.id))
        ],
        "orders": [
            {
                "id": str(order.id),
                "source_id": str(order.source_id),
                "destination_id": str(order.destination_id),
                "resource_id": str(order.resource_id),
                "amount_t": order.amount_t,
                "priority": order.priority,
                "owner_kind": order.owner_kind,
                "owner_id": str(order.owner_id),
                "path": [str(route_id) for route_id in order.path],
                "mode_by_route": {
                    str(route_id): mode_id
                    for route_id, mode_id in sorted(order.mode_by_route.items(), key=lambda row: str(row[0]))
                },
                "path_policy": order.path_policy.value,
                "delivered_t": order.delivered_t,
                "created_day": order.created_day,
                "lane_id": None if order.lane_id is None else str(order.lane_id),
                "demand_id": None if order.demand_id is None else str(order.demand_id),
            }
            for order in sorted(lg.orders.values(), key=lambda row: str(row.id))
        ],
        "waiting": [
            {"order_id": str(order_id), "leg_index": leg, "amount_t": amount}
            for (order_id, leg), amount in sorted(lg.waiting.items(), key=lambda row: (str(row[0][0]), row[0][1]))
        ],
        "missions": [
            {
                "id": str(mission.id),
                "order_id": str(mission.order_id),
                "leg_index": mission.leg_index,
                "amount_t": mission.amount_t,
                "mode_id": mission.mode_id,
                "departure_day": mission.departure_day,
                "arrival_day": mission.arrival_day,
                "vehicle_id": None if mission.vehicle_id is None else str(mission.vehicle_id),
                "vehicle_disposition": mission.vehicle_disposition.value,
                "status": mission.status.value,
                "onboard": mission.onboard,
                "handoff_vehicle_id": None if mission.handoff_vehicle_id is None else str(mission.handoff_vehicle_id),
            }
            for mission in sorted(lg.missions.values(), key=lambda row: str(row.id))
        ],
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._counter = int(data["counter"])
    lg._lane_counter = int(data.get("lane_counter", 0))
    lg._vehicle_counter = int(data.get("vehicle_counter", 0))
    lg._mission_counter = int(data.get("mission_counter", 0))
    lg.lanes = {
        EntityId(row["id"]): LogisticsLane(
            EntityId(row["id"]),
            SpatialNodeId(row["source_id"]),
            SpatialNodeId(row["destination_id"]),
            float(row["requested_capacity_t_per_day"]),
            int(row["priority"]),
            None if row["path"] is None else tuple(RouteId(value) for value in row["path"]),
            {RouteId(key): value for key, value in row.get("mode_by_route", {}).items()},
            PathPolicy(row.get("path_policy", "fastest")),
            bool(row["paused"]),
        )
        for row in data.get("lanes", [])
    }
    lg.vehicles = {
        EntityId(row["id"]): VehicleState(
            EntityId(row["id"]),
            DefinitionId(row["definition_id"]),
            None if row["location_id"] is None else SpatialNodeId(row["location_id"]),
            VehicleStatus(row["status"]),
            int(row["available_day"]),
            None if row.get("transit_destination_id") is None else SpatialNodeId(row["transit_destination_id"]),
            float(row.get("propellant_t", 0.0)),
        )
        for row in data.get("vehicles", [])
    }
    lg.vehicle_transit = [
        VehicleTransit(
            EntityId(row["vehicle_id"]),
            RouteId(row["route_id"]),
            int(row["arrival_day"]),
            bool(row.get("used_for_mission", True)),
        )
        for row in data.get("vehicle_transit", [])
    ]
    lg.orders = {}
    for row in data.get("orders", []):
        order_id = CargoOrderId(row["id"])
        lg.orders[order_id] = CargoOrder(
            order_id,
            SpatialNodeId(row["source_id"]),
            SpatialNodeId(row["destination_id"]),
            DefinitionId(row["resource_id"]),
            float(row["amount_t"]),
            int(row["priority"]),
            row["owner_kind"],
            EntityId(row["owner_id"]),
            tuple(RouteId(value) for value in row["path"]),
            {RouteId(key): value for key, value in row.get("mode_by_route", {}).items()},
            PathPolicy(row.get("path_policy", "fastest")),
            float(row["delivered_t"]),
            int(row.get("created_day", 0)),
            None if row.get("lane_id") is None else EntityId(row["lane_id"]),
            None if row.get("demand_id") is None else EntityId(row["demand_id"]),
        )
    lg.waiting = {
        (CargoOrderId(row["order_id"]), int(row["leg_index"])): float(row["amount_t"])
        for row in data.get("waiting", [])
    }
    lg.missions = {
        EntityId(row["id"]): TransportMissionState(
            EntityId(row["id"]),
            CargoOrderId(row["order_id"]),
            int(row["leg_index"]),
            float(row["amount_t"]),
            str(row["mode_id"]),
            int(row["departure_day"]),
            int(row["arrival_day"]),
            None if row.get("vehicle_id") is None else EntityId(row["vehicle_id"]),
            VehicleDisposition(row.get("vehicle_disposition", "destination")),
            MissionStatus(row.get("status", "in_transit")),
            bool(row.get("onboard", True)),
            None if row.get("handoff_vehicle_id") is None else EntityId(row["handoff_vehicle_id"]),
        )
        for row in data.get("missions", [])
    }


def referenced_resources(sim: Any) -> set[DefinitionId]:
    result: set[DefinitionId] = set()
    for vehicle in sim.logistics.vehicle_defs.values():
        profile = vehicle.performance
        if profile.propellant_resource_id is not None:
            result.add(profile.propellant_resource_id)
        result.update(resource_id for resource_id, _amount in vehicle.maintenance.resources)
        result.update(resource_id for resource_id, _amount in vehicle.production.resources)
    return result


def _validate_transport_profile(sim: Any, profile, known_capabilities: set[str], label: str) -> None:
    _require(profile.dry_mass_t >= 0, f"negative transport dry mass: {label}")
    _require(profile.payload_t > 0, f"non-positive transport payload: {label}")
    _require(profile.transit_time_multiplier > 0, f"non-positive transport time multiplier: {label}")
    _require(profile.propellant_capacity_t >= 0, f"negative propellant capacity: {label}")
    _require(profile.propellant_t_per_total_t_per_km_s >= 0, f"negative propellant use: {label}")
    if profile.propellant_t_per_total_t_per_km_s > 0:
        _require(profile.propellant_resource_id is not None, f"propellant rate without resource: {label}")
        _require(profile.propellant_capacity_t > 0, f"propellant rate without tank capacity: {label}")
    operation_types = [capability.operation_type for capability in profile.operation_capabilities]
    _require(len(operation_types) == len(set(operation_types)), f"duplicate transport operation capability: {label}")
    for capability in profile.operation_capabilities:
        _require(
            sim.logistics.operation_registry.supports(capability.operation_type),
            f"unregistered transport operation capability: {label}/{capability.operation_type}",
        )
        for field_name, value in vars(capability).items():
            if field_name == "operation_type":
                continue
            if isinstance(value, (int, float)):
                _require(value >= 0, f"negative transport capability {capability.operation_type}.{field_name}: {label}")
    for requirement in profile.operation_support_requirements:
        _require(requirement.capability_id, f"empty transport operation support capability: {label}")
        _require(
            requirement.capability_id in known_capabilities,
            f"transport operation support references unknown capability: {label}/{requirement.capability_id}",
        )
        _require(
            requirement.operation_type in operation_types,
            f"transport operation support has no matching vehicle capability: {label}/{requirement.operation_type}",
        )


def validate_configuration(sim: Any, ctx: ValidationContext) -> None:
    nodes = ctx.nodes
    known_capabilities = ctx.known_capabilities
    for route_id, route in sim.logistics.routes.items():
        _require(route_id == route.id, f"route definition key mismatch: {route_id}")
        _require(route.origin_id in nodes and route.destination_id in nodes, f"route references unknown location: {route_id}")
        _require(route.origin_id != route.destination_id, f"route loops to same location: {route_id}")
        _require(route.transit_days >= 0, f"negative route transit time: {route_id}")
        _require(route.delta_v_km_s >= 0, f"negative route delta-v: {route_id}")
        for operation in route.operations:
            _require(
                sim.logistics.operation_registry.supports(operation.operation_type),
                f"route references unregistered transport operation: {route_id}/{operation.operation_type}",
            )
        _validate_site_requirements(route.origin_requirements, known_capabilities, f"route:{route_id}:origin")
        _validate_site_requirements(route.destination_requirements, known_capabilities, f"route:{route_id}:destination")
    for service_id, service in sim.logistics.external_services.items():
        _require(service_id == service.id, f"transport service key mismatch: {service_id}")
        _require(service.capacity_t_per_day >= 0, f"negative transport service capacity: {service_id}")
        _require(service.cost_musd_per_t >= 0, f"negative transport service cost: {service_id}")
        _require(service.transit_time_multiplier > 0, f"non-positive transport service time multiplier: {service_id}")
        _validate_transport_profile(sim, service.performance, known_capabilities, f"transport_service:{service_id}")
        _validate_site_requirements(service.origin_requirements, known_capabilities, f"transport_service:{service_id}:origin")
        _validate_site_requirements(service.destination_requirements, known_capabilities, f"transport_service:{service_id}:destination")
    for vehicle_id, vehicle in sim.logistics.vehicle_defs.items():
        _require(vehicle_id == vehicle.id, f"vehicle definition key mismatch: {vehicle_id}")
        _validate_transport_profile(sim, vehicle.performance, known_capabilities, f"vehicle:{vehicle_id}")
        _require(vehicle.maintenance.turnaround_days >= 0, f"negative vehicle turnaround: {vehicle_id}")
        _require(vehicle.maintenance.cost_musd >= 0, f"negative vehicle turnaround cost: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.maintenance.resources), f"negative vehicle turnaround resource: {vehicle_id}")
        _require(vehicle.production.days >= 0, f"negative vehicle production time: {vehicle_id}")
        _require(vehicle.production.cost_musd >= 0, f"negative vehicle production cost: {vehicle_id}")
        _require(all(amount >= 0 for _resource, amount in vehicle.production.resources), f"negative vehicle production resource: {vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_mission >= 0, f"negative vehicle mission cost: {vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_cargo_t >= 0, f"negative vehicle cargo cost: {vehicle_id}")
        if vehicle.maintenance.capability_id is not None:
            _require(vehicle.maintenance.capability_id in known_capabilities, f"vehicle turnaround references unknown capability: {vehicle_id}/{vehicle.maintenance.capability_id}")
        if vehicle.production.capability_id is not None:
            _require(vehicle.production.capability_id in known_capabilities, f"vehicle production references unknown capability: {vehicle_id}/{vehicle.production.capability_id}")
    for route_id in sim.logistics.routes:
        external_service_exists = any(
            service.capacity_t_per_day > 1e-12 and not sim.logistics.service_route_failures(route_id, service.id, 0)
            for service in sim.logistics.external_services.values()
        )
        compatible_vehicle_exists = any(
            not sim.logistics.vehicle_route_physical_failures(route_id, vehicle_id, 0)
            for vehicle_id in sim.logistics.vehicle_defs
        )
        _require(external_service_exists or compatible_vehicle_exists, f"route has no physically compatible transport mode: {route_id}")


def validate_runtime(sim: Any) -> None:
    lg = sim.logistics
    for vehicle_id, state in lg.vehicles.items():
        _require(vehicle_id == state.id, f"vehicle state key mismatch: {vehicle_id}")
        _require(state.definition_id in lg.vehicle_defs, f"vehicle references unknown definition: {vehicle_id}")
        _require(isinstance(state.status, VehicleStatus), f"invalid vehicle status: {vehicle_id}/{state.status}")
        if state.status is VehicleStatus.TRANSIT:
            _require(state.location_id is None, f"transit vehicle still has a location: {vehicle_id}")
            _require(state.transit_destination_id in sim.graph.nodes, f"transit vehicle lacks valid destination: {vehicle_id}")
        elif state.status is VehicleStatus.TRANSIT_RETURN:
            _require(state.location_id in sim.graph.nodes, f"returning vehicle lacks recovery location: {vehicle_id}")
            _require(state.transit_destination_id is None, f"returning vehicle retains transit destination: {vehicle_id}")
        else:
            _require(state.location_id in sim.graph.nodes, f"vehicle references unknown location: {vehicle_id}")
            _require(state.transit_destination_id is None, f"stationary vehicle retains transit destination: {vehicle_id}")
        definition = lg.vehicle_defs[state.definition_id]
        _require(state.propellant_t >= -1e-9, f"negative onboard propellant: {vehicle_id}")
        _require(state.propellant_t <= definition.performance.propellant_capacity_t + 1e-9, f"onboard propellant exceeds tank capacity: {vehicle_id}")
    for movement in lg.vehicle_transit:
        _require(movement.vehicle_id in lg.vehicles, f"vehicle transit references unknown vehicle: {movement.vehicle_id}")
        _require(movement.route_id in lg.routes, f"vehicle transit references unknown route: {movement.route_id}")
    for lane_id, lane in lg.lanes.items():
        _require(lane_id == lane.id, f"lane key mismatch: {lane_id}")
        _require(lane.source_id in sim.graph.nodes and lane.destination_id in sim.graph.nodes, f"lane references unknown endpoint: {lane_id}")
        _require(lane.source_id != lane.destination_id, f"lane loops to same location: {lane_id}")
        _require(lane.requested_capacity_t_per_day > 0, f"lane has non-positive requested capacity: {lane_id}")
        if lane.path is None:
            _require(not lane.mode_by_route, f"automatic lane retains explicit modes: {lane_id}")
        else:
            lg.validate_path_structure(lane.source_id, lane.destination_id, lane.path)
            lg.validate_mode_selection(lane.path, lane.mode_by_route)
    for order_id, order in lg.orders.items():
        _require(order_id == order.id, f"cargo order key mismatch: {order_id}")
        _require(order.source_id in sim.graph.nodes and order.destination_id in sim.graph.nodes, f"cargo order references unknown endpoint: {order_id}")
        _require(order.amount_t > 0, f"cargo order has non-positive amount: {order_id}")
        _require(-1e-9 <= order.delivered_t <= order.amount_t + 1e-9, f"invalid cargo delivery progress: {order_id}")
        _require(order.created_day >= 0, f"cargo order has negative creation day: {order_id}")
        if order.lane_id is not None:
            _require(order.lane_id in lg.lanes, f"cargo order references unknown lane: {order_id}/{order.lane_id}")
            _require(order.demand_id is not None, f"lane cargo order lacks demand id: {order_id}")
        lg.validate_path_structure(order.source_id, order.destination_id, order.path)
        lg.validate_mode_selection(order.path, order.mode_by_route)
    for (order_id, leg_index), amount in lg.waiting.items():
        _require(order_id in lg.orders, f"waiting cargo references unknown order: {order_id}")
        _require(0 <= leg_index < len(lg.orders[order_id].path), f"waiting cargo has invalid leg: {order_id}/{leg_index}")
        _require(amount >= -1e-9, f"negative waiting cargo: {order_id}/{leg_index}")
    for mission_id, mission in lg.missions.items():
        _require(mission_id == mission.id, f"mission key mismatch: {mission_id}")
        _require(mission.order_id in lg.orders, f"mission references unknown order: {mission_id}")
        order = lg.orders[mission.order_id]
        _require(0 <= mission.leg_index < len(order.path), f"mission has invalid leg index: {mission_id}")
        _require(mission.amount_t > 0, f"mission has non-positive mass: {mission_id}")
        _require(mission.arrival_day >= mission.departure_day, f"mission arrives before departure: {mission_id}")
        if mission.vehicle_id is not None:
            _require(mission.vehicle_id in lg.vehicles, f"mission references unknown vehicle: {mission_id}")
        if mission.handoff_vehicle_id is not None:
            _require(mission.handoff_vehicle_id in lg.vehicles, f"mission references unknown handoff vehicle: {mission_id}")


STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension(
    "logistics",
    state_codec=STATE_CODEC,
    configuration_validator=validate_configuration,
    runtime_validator=validate_runtime,
    referenced_resources=referenced_resources,
)
