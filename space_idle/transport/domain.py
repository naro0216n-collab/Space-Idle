from __future__ import annotations

from typing import Any

from ..domain import DomainExtension, StateCodec
from ..validation_support import ValidationContext, require as _require, validate_site_requirements as _validate_site_requirements
from ..shared import CargoOrderId, DefinitionId, EntityId, RouteId, SpatialNodeId
from .models import (
    CargoOrder,
    MissionStatus,
    PathPolicy,
    RecurringCargoRule,
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
        "rule_counter": lg._rule_counter,
        "vehicle_counter": lg._vehicle_counter,
        "mission_counter": lg._mission_counter,
        "vehicles": [
            {
                "id": str(s.id), "definition_id": str(s.definition_id),
                "location_id": None if s.location_id is None else str(s.location_id),
                "status": s.status.value, "available_day": s.available_day,
                "transit_destination_id": None if s.transit_destination_id is None else str(s.transit_destination_id),
                "propellant_t": s.propellant_t,
            }
            for s in sorted(lg.vehicles.values(), key=lambda r: str(r.id))
        ],
        "vehicle_transit": [
            {"vehicle_id": str(r.vehicle_id), "route_id": str(r.route_id), "arrival_day": r.arrival_day, "used_for_mission": r.used_for_mission}
            for r in sorted(lg.vehicle_transit, key=lambda r: (r.arrival_day, str(r.vehicle_id)))
        ],
        "recurring_rules": [
            {
                "id": str(r.id), "source_id": str(r.source_id), "destination_id": str(r.destination_id),
                "resource_id": str(r.resource_id), "target_stock_t": r.target_stock_t, "batch_t": r.batch_t,
                "priority": r.priority, "path": None if r.path is None else [str(x) for x in r.path],
                "mode_by_route": {str(route_id): mode_id for route_id, mode_id in sorted(r.mode_by_route.items(), key=lambda row: str(row[0]))},
                "path_policy": r.path_policy.value, "paused": r.paused,
            }
            for r in sorted(lg.recurring_rules.values(), key=lambda row: str(row.id))
        ],
        "orders": [
            {
                "id": str(o.id), "source_id": str(o.source_id), "destination_id": str(o.destination_id),
                "resource_id": str(o.resource_id), "amount_t": o.amount_t, "priority": o.priority,
                "owner_kind": o.owner_kind, "owner_id": str(o.owner_id), "path": [str(x) for x in o.path],
                "mode_by_route": {str(route_id): mode_id for route_id, mode_id in sorted(o.mode_by_route.items(), key=lambda row: str(row[0]))},
                "path_policy": o.path_policy.value, "delivered_t": o.delivered_t,
            }
            for o in sorted(lg.orders.values(), key=lambda row: str(row.id))
        ],
        "waiting": [
            {"order_id": str(oid), "leg_index": leg, "amount_t": amount}
            for (oid, leg), amount in sorted(lg.waiting.items(), key=lambda x: (str(x[0][0]), x[0][1]))
        ],
        "missions": [
            {
                "id": str(m.id), "order_id": str(m.order_id), "leg_index": m.leg_index,
                "amount_t": m.amount_t, "mode_id": m.mode_id,
                "departure_day": m.departure_day, "arrival_day": m.arrival_day,
                "vehicle_id": None if m.vehicle_id is None else str(m.vehicle_id),
                "vehicle_disposition": m.vehicle_disposition.value, "status": m.status.value,
                "onboard": m.onboard,
                "handoff_vehicle_id": None if m.handoff_vehicle_id is None else str(m.handoff_vehicle_id),
            }
            for m in sorted(lg.missions.values(), key=lambda row: str(row.id))
        ],
    }


def restore_logistics(sim: Any, data: dict[str, Any]) -> None:
    lg = sim.logistics
    lg._counter = int(data["counter"])
    lg._rule_counter = int(data.get("rule_counter", 0))
    lg._vehicle_counter = int(data.get("vehicle_counter", 0))
    lg._mission_counter = int(data.get("mission_counter", 0))
    lg.recurring_rules = {
        EntityId(r["id"]): RecurringCargoRule(
            EntityId(r["id"]), SpatialNodeId(r["source_id"]), SpatialNodeId(r["destination_id"]),
            DefinitionId(r["resource_id"]), float(r["target_stock_t"]), float(r["batch_t"]), int(r["priority"]),
            None if r["path"] is None else tuple(RouteId(x) for x in r["path"]),
            {RouteId(k): v for k, v in r.get("mode_by_route", {}).items()},
            PathPolicy(r.get("path_policy", "fastest")), bool(r["paused"]),
        )
        for r in data.get("recurring_rules", [])
    }
    lg.vehicles = {
        EntityId(r["id"]): VehicleState(
            EntityId(r["id"]), DefinitionId(r["definition_id"]),
            None if r["location_id"] is None else SpatialNodeId(r["location_id"]),
            VehicleStatus(r["status"]), int(r["available_day"]),
            None if r.get("transit_destination_id") is None else SpatialNodeId(r["transit_destination_id"]),
            float(r.get("propellant_t", 0.0)),
        )
        for r in data.get("vehicles", [])
    }
    lg.vehicle_transit = [
        VehicleTransit(EntityId(r["vehicle_id"]), RouteId(r["route_id"]), int(r["arrival_day"]), bool(r.get("used_for_mission", True)))
        for r in data.get("vehicle_transit", [])
    ]
    lg.orders = {}
    for r in data["orders"]:
        oid = CargoOrderId(r["id"])
        lg.orders[oid] = CargoOrder(
            oid, SpatialNodeId(r["source_id"]), SpatialNodeId(r["destination_id"]), DefinitionId(r["resource_id"]),
            float(r["amount_t"]), int(r["priority"]), r["owner_kind"], EntityId(r["owner_id"]),
            tuple(RouteId(x) for x in r["path"]), {RouteId(k): v for k, v in r.get("mode_by_route", {}).items()},
            PathPolicy(r.get("path_policy", "fastest")), float(r["delivered_t"]),
        )
    lg.waiting = {
        (CargoOrderId(r["order_id"]), int(r["leg_index"])): float(r["amount_t"])
        for r in data["waiting"]
    }
    lg.missions = {
        EntityId(r["id"]): TransportMissionState(
            EntityId(r["id"]), CargoOrderId(r["order_id"]), int(r["leg_index"]), float(r["amount_t"]),
            str(r["mode_id"]), int(r["departure_day"]), int(r["arrival_day"]),
            None if r.get("vehicle_id") is None else EntityId(r["vehicle_id"]),
            VehicleDisposition(r.get("vehicle_disposition", "destination")),
            MissionStatus(r.get("status", "in_transit")), bool(r.get("onboard", True)),
            None if r.get("handoff_vehicle_id") is None else EntityId(r["handoff_vehicle_id"]),
        )
        for r in data.get("missions", [])
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
        _require(sim.logistics.operation_registry.supports(capability.operation_type),
                 f"unregistered transport operation capability: {label}/{capability.operation_type}")
        for field_name, value in vars(capability).items():
            if field_name == "operation_type":
                continue
            if isinstance(value, (int, float)):
                _require(value >= 0, f"negative transport capability {capability.operation_type}.{field_name}: {label}")
    for req in profile.operation_support_requirements:
        _require(req.capability_id, f"empty transport operation support capability: {label}")
        _require(req.capability_id in known_capabilities,
                 f"transport operation support references unknown capability: {label}/{req.capability_id}")
        _require(req.operation_type in operation_types,
                 f"transport operation support has no matching vehicle capability: {label}/{req.operation_type}")


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
            _require(sim.logistics.operation_registry.supports(operation.operation_type),
                     f"route references unregistered transport operation: {route_id}/{operation.operation_type}")
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
        _require(all(amount >= 0 for _resource_id, amount in vehicle.maintenance.resources), f"negative vehicle turnaround resource: {vehicle_id}")
        _require(vehicle.production.days >= 0, f"negative vehicle production time: {vehicle_id}")
        _require(vehicle.production.cost_musd >= 0, f"negative vehicle production cost: {vehicle_id}")
        _require(all(amount >= 0 for _resource_id, amount in vehicle.production.resources), f"negative vehicle production resource: {vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_mission >= 0, f"negative vehicle mission cost: {vehicle_id}")
        _require(vehicle.economics.operating_cost_musd_per_cargo_t >= 0, f"negative vehicle cargo cost: {vehicle_id}")
        if vehicle.maintenance.capability_id is not None:
            _require(vehicle.maintenance.capability_id in known_capabilities,
                     f"vehicle turnaround references unknown capability: {vehicle_id}/{vehicle.maintenance.capability_id}")
        if vehicle.production.capability_id is not None:
            _require(vehicle.production.capability_id in known_capabilities,
                     f"vehicle production references unknown capability: {vehicle_id}/{vehicle.production.capability_id}")
    for route_id in sim.logistics.routes:
        external_service_exists = any(
            service.capacity_t_per_day > 1e-12 and not sim.logistics.service_route_failures(route_id, service.id, 0)
            for service in sim.logistics.external_services.values()
        )
        compatible_vehicle_exists = any(
            not sim.logistics.vehicle_route_physical_failures(route_id, vehicle_id, 0)
            for vehicle_id in sim.logistics.vehicle_defs
        )
        _require(external_service_exists or compatible_vehicle_exists,
                 f"route has no physically compatible transport mode: {route_id}")


def validate_runtime(sim: Any) -> None:
    for vehicle_id, state in sim.logistics.vehicles.items():
        _require(vehicle_id == state.id, f"vehicle state key mismatch: {vehicle_id}")
        _require(state.definition_id in sim.logistics.vehicle_defs, f"vehicle references unknown definition: {vehicle_id}")
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
        definition = sim.logistics.vehicle_defs[state.definition_id]
        _require(state.propellant_t >= -1e-9, f"negative onboard propellant: {vehicle_id}")
        _require(state.propellant_t <= definition.performance.propellant_capacity_t + 1e-9,
                 f"onboard propellant exceeds tank capacity: {vehicle_id}")
    for movement in sim.logistics.vehicle_transit:
        _require(movement.vehicle_id in sim.logistics.vehicles, f"vehicle transit references unknown vehicle: {movement.vehicle_id}")
        _require(movement.route_id in sim.logistics.routes, f"vehicle transit references unknown route: {movement.route_id}")
    for rule_id, rule in sim.logistics.recurring_rules.items():
        _require(rule_id == rule.id, f"logistics rule key mismatch: {rule_id}")
        _require(rule.source_id in sim.graph.nodes and rule.destination_id in sim.graph.nodes, f"logistics rule references unknown location: {rule_id}")
        _require(rule.source_id != rule.destination_id, f"logistics rule has identical endpoints: {rule_id}")
        _require(rule.target_stock_t >= 0 and rule.batch_t > 0, f"invalid logistics rule quantities: {rule_id}")
        if rule.path is not None:
            sim.logistics.validate_path_structure(rule.source_id, rule.destination_id, rule.path)
            sim.logistics.validate_mode_selection(rule.path, rule.mode_by_route)
        else:
            _require(not rule.mode_by_route, f"dynamic-path logistics rule retains explicit route modes: {rule_id}")
    for (order_id, leg_index), amount in sim.logistics.waiting.items():
        _require(order_id in sim.logistics.orders, f"waiting cargo references unknown order: {order_id}")
        order = sim.logistics.orders[order_id]
        _require(0 <= leg_index < len(order.path), f"waiting cargo has invalid leg: {order_id}/{leg_index}")
        _require(amount >= -1e-9, f"negative waiting cargo: {order_id}/{leg_index}")
    for mission_id, mission in sim.logistics.missions.items():
        _require(mission_id == mission.id, f"transport mission key mismatch: {mission_id}")
        _require(isinstance(mission.status, MissionStatus), f"invalid transport mission status: {mission_id}/{mission.status}")
        _require(mission.order_id in sim.logistics.orders, f"transport mission references unknown order: {mission.order_id}")
        order = sim.logistics.orders[mission.order_id]
        _require(0 <= mission.leg_index < len(order.path), f"transport mission has invalid leg: {mission.order_id}/{mission.leg_index}")
        _require(mission.amount_t > 0, f"non-positive transport mission: {mission.order_id}")
        _require(DefinitionId(mission.mode_id) in sim.logistics.vehicle_defs or sim.logistics._service_for_mode(mission.mode_id) is not None,
                 f"transport mission has invalid transport mode: {mission.order_id}/{mission.mode_id}")
        if mission.vehicle_id is not None:
            _require(mission.vehicle_id in sim.logistics.vehicles, f"transport mission references unknown vehicle: {mission.order_id}/{mission.vehicle_id}")
        if mission.handoff_vehicle_id is not None:
            _require(mission.handoff_vehicle_id in sim.logistics.vehicles,
                     f"transport mission references unknown handoff vehicle: {mission.order_id}/{mission.handoff_vehicle_id}")
            _require(mission.handoff_vehicle_id != mission.vehicle_id,
                     f"transport mission handoff vehicle equals carrier: {mission.order_id}/{mission.handoff_vehicle_id}")
            handoff_state = sim.logistics.vehicles[mission.handoff_vehicle_id]
            _require(handoff_state.status is VehicleStatus.TRANSIT,
                     f"handoff vehicle is not in transit with mission: {mission.order_id}/{mission.handoff_vehicle_id}")
            _require(handoff_state.location_id is None,
                     f"handoff vehicle retains a location while carried: {mission.order_id}/{mission.handoff_vehicle_id}")
    expected_external_occupancy: dict[tuple[EntityId, object, object], float] = {}
    for (order_id, leg_index), amount in sim.logistics.waiting.items():
        order = sim.logistics.orders[order_id]
        route = sim.logistics.routes[order.path[leg_index]]
        owner = sim.logistics._waiting_owner(order_id, leg_index)
        key = (owner, route.origin_id, order.resource_id)
        expected_external_occupancy[key] = expected_external_occupancy.get(key, 0.0) + amount
    actual_external_occupancy = {key: amount for key, amount in sim.inventory.external_occupancy.items() if amount > 1e-12}
    _require(set(actual_external_occupancy) == set(expected_external_occupancy),
             "logistics staging storage occupancy keys do not match waiting cargo")
    for key, expected in expected_external_occupancy.items():
        _require(abs(actual_external_occupancy.get(key, 0.0) - expected) <= 1e-7,
                 f"logistics staging storage occupancy mismatch: {key}")
    for order_id, order in sim.logistics.orders.items():
        _require(order_id == order.id, f"cargo order key mismatch: {order_id}")
        _require(order.source_id in sim.graph.nodes and order.destination_id in sim.graph.nodes, f"cargo order references unknown location: {order_id}")
        _require(order.source_id != order.destination_id, f"cargo order has identical endpoints: {order_id}")
        _require(order.amount_t > 0, f"non-positive cargo order: {order_id}")
        _require(-1e-9 <= order.delivered_t <= order.amount_t + 1e-8, f"invalid delivered cargo: {order_id}")
        sim.logistics.validate_path_structure(order.source_id, order.destination_id, order.path)
        sim.logistics.validate_mode_selection(order.path, order.mode_by_route)
        waiting = sum(amount for (oid, _leg), amount in sim.logistics.waiting.items() if oid == order_id)
        transit = sum(batch.amount_t for batch in sim.logistics.in_transit if batch.order_id == order_id)
        _require(waiting >= -1e-9 and transit >= -1e-9, f"negative cargo bucket: {order_id}")
        _require(abs(order.delivered_t + waiting + transit - order.amount_t) <= 1e-7,
                 f"cargo mass accounting mismatch: {order_id}")


STATE_CODEC = StateCodec("logistics", capture_logistics, restore_logistics)
DOMAIN_EXTENSION = DomainExtension("transport", state_codec=STATE_CODEC, configuration_validator=validate_configuration, runtime_validator=validate_runtime, referenced_resources=referenced_resources)
