from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ..facilities import FacilityBook
from ..shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from ..site import SiteRequirements
from ..spatial import SpatialGraph
from .models import RouteDef, RouteEndpoint, TransportOperationRequirement

DERIVED_SURFACE_ACCESS_ROUTE_PREFIX = "derived.surface_access."
DERIVED_SURFACE_ORBIT_ROUTE_PREFIX = "derived.surface_orbit."


@dataclass(frozen=True)
class SurfaceTransportRouteRule:
    id: DefinitionId
    display_name: str
    operation: TransportOperationRequirement
    gateway_capability_id: str = "surface_distribution"
    transit_days: int = 1


@dataclass(frozen=True)
class SurfaceOrbitRouteRule:
    id: DefinitionId
    display_name: str
    orbit_node_id: SpatialNodeId
    descent_operations: tuple[TransportOperationRequirement, ...]
    ascent_operations: tuple[TransportOperationRequirement, ...]
    transit_days: int
    gateway_capability_id: str = "surface_distribution"
    orbit_requirements: SiteRequirements = SiteRequirements()
    surface_requirements: SiteRequirements = SiteRequirements()


def _stable_route_id(prefix: str, *parts: object) -> RouteId:
    payload = "\0".join(str(part) for part in parts).encode("utf-8")
    return RouteId(prefix + sha256(payload).hexdigest()[:24])


def derived_surface_access_route_id(
    origin_id: SpatialNodeId,
    destination_id: SpatialNodeId,
    rule_id: DefinitionId | str = "surface_transport",
    origin_gateway_id: EntityId | str = "gateway",
    destination_gateway_id: EntityId | str = "gateway",
) -> RouteId:
    return _stable_route_id(
        DERIVED_SURFACE_ACCESS_ROUTE_PREFIX,
        rule_id,
        origin_id,
        destination_id,
        origin_gateway_id,
        destination_gateway_id,
    )


def derived_surface_orbit_route_id(
    rule_id: DefinitionId,
    surface_location_id: SpatialNodeId,
    gateway_id: EntityId,
    direction: str,
) -> RouteId:
    return _stable_route_id(
        DERIVED_SURFACE_ORBIT_ROUTE_PREFIX,
        rule_id,
        surface_location_id,
        gateway_id,
        direction,
    )


def _gateways(
    facilities: FacilityBook,
    location_id: SpatialNodeId,
    capability_id: str,
) -> tuple[EntityId, ...]:
    rows: list[EntityId] = []
    for facility in facilities.all_at(location_id):
        if facility.site_cell_id is None:
            continue
        definition = facilities.definitions[facility.definition_id]
        if any(supply.id == capability_id for supply in definition.capability_supplies):
            rows.append(facility.id)
    return tuple(sorted(rows, key=str))


def build_derived_surface_access_routes(
    graph: SpatialGraph,
    facilities: FacilityBook,
    surface_rules: tuple[SurfaceTransportRouteRule, ...] = (),
    orbit_rules: tuple[SurfaceOrbitRouteRule, ...] = (),
) -> dict[RouteId, RouteDef]:
    """Derive normal Routes only from established Locations and real gateways."""
    routes: dict[RouteId, RouteDef] = {}
    locations = tuple(sorted(graph.locations.values(), key=lambda row: str(row.id)))

    for rule in sorted(surface_rules, key=lambda row: str(row.id)):
        for origin in locations:
            origin_gateways = _gateways(facilities, origin.id, rule.gateway_capability_id)
            if not origin_gateways:
                continue
            for destination in locations:
                if origin.id == destination.id or origin.body_id != destination.body_id:
                    continue
                destination_gateways = _gateways(facilities, destination.id, rule.gateway_capability_id)
                for origin_gateway in origin_gateways:
                    for destination_gateway in destination_gateways:
                        route_id = derived_surface_access_route_id(
                            origin.id,
                            destination.id,
                            rule.id,
                            origin_gateway,
                            destination_gateway,
                        )
                        routes[route_id] = RouteDef(
                            id=route_id,
                            origin=RouteEndpoint(origin.id, surface_interface_id=origin_gateway),
                            destination=RouteEndpoint(destination.id, surface_interface_id=destination_gateway),
                            transit_days=max(1, rule.transit_days),
                            operations=(rule.operation,),
                            display_name=f"{origin.display_name} → {destination.display_name} {rule.display_name}",
                        )

    for rule in sorted(orbit_rules, key=lambda row: str(row.id)):
        if not graph.has_operational_node(rule.orbit_node_id):
            continue
        orbit = graph.operational_node(rule.orbit_node_id)
        for location in locations:
            if orbit.body_id != location.body_id:
                continue
            for gateway_id in _gateways(facilities, location.id, rule.gateway_capability_id):
                down_id = derived_surface_orbit_route_id(rule.id, location.id, gateway_id, "down")
                routes[down_id] = RouteDef(
                    id=down_id,
                    origin=RouteEndpoint(rule.orbit_node_id, non_surface_interface="operational_node"),
                    destination=RouteEndpoint(location.id, surface_interface_id=gateway_id),
                    transit_days=rule.transit_days,
                    operations=rule.descent_operations,
                    display_name=f"{rule.display_name} → {location.display_name}",
                    origin_requirements=rule.orbit_requirements,
                    destination_requirements=rule.surface_requirements,
                )
                up_id = derived_surface_orbit_route_id(rule.id, location.id, gateway_id, "up")
                routes[up_id] = RouteDef(
                    id=up_id,
                    origin=RouteEndpoint(location.id, surface_interface_id=gateway_id),
                    destination=RouteEndpoint(rule.orbit_node_id, non_surface_interface="operational_node"),
                    transit_days=rule.transit_days,
                    operations=rule.ascent_operations,
                    display_name=f"{location.display_name} → {rule.display_name}",
                    origin_requirements=rule.surface_requirements,
                    destination_requirements=rule.orbit_requirements,
                )
    return routes
