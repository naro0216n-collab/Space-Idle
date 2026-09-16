from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from typing import Iterable

from ..facilities import FacilityBook
from ..shared import CelestialBodyId, DefinitionId, EntityId, MovementPlanId, SpatialNodeId, SurfaceCellId
from ..site import SiteRequirements
from ..spatial import SpatialGraph
from ..spatial import great_circle_distance_km
from .endpoints import resolve_movement_endpoint
from .models import (
    MovementEndpoint,
    MovementPlan,
    SpatialRelation,
    TransportOperationRequirement,
)

MOVEMENT_PLAN_ID_PREFIX = "movement.plan."


@dataclass(frozen=True)
class SurfaceTransportMovementRule:
    """Movement profile for travel between established surface Locations."""

    id: DefinitionId
    display_name: str
    operation: TransportOperationRequirement
    gateway_capability_id: str = "surface_distribution"
    transit_days: int = 1


@dataclass(frozen=True)
class SurfaceAccessMovementRule:
    """Body-local surface/space access profile.

    A body may define one or more access profiles, but the profile is not bound
    to one orbit or one OD pair.  Any established non-surface endpoint in the
    same body context, and any end-to-end movement that enters/leaves the body,
    can reuse it.
    """

    id: DefinitionId
    display_name: str
    body_id: CelestialBodyId
    descent_operations: tuple[TransportOperationRequirement, ...]
    ascent_operations: tuple[TransportOperationRequirement, ...]
    transit_days: int
    gateway_capability_id: str = "surface_distribution"
    space_requirements: SiteRequirements = SiteRequirements()
    surface_requirements: SiteRequirements = SiteRequirements()


@dataclass(frozen=True)
class SpaceflightMovementRule:
    """Reusable spaceflight profile applied to characteristic Spatial separation."""

    id: DefinitionId
    display_name: str
    operation_type: str
    characteristic_speed_km_per_day: float
    minimum_transit_days: int = 1
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()

    def __post_init__(self) -> None:
        if not self.operation_type:
            raise ValueError("spaceflight movement operation type must not be empty")
        if self.characteristic_speed_km_per_day <= 0:
            raise ValueError("spaceflight characteristic speed must be positive")
        if self.minimum_transit_days <= 0:
            raise ValueError("spaceflight minimum transit days must be positive")


def _stable_plan_id(
    rule_ids: tuple[DefinitionId, ...], origin: MovementEndpoint, destination: MovementEndpoint
) -> MovementPlanId:
    payload = "\0".join(
        (
            *(str(rule_id) for rule_id in rule_ids),
            str(origin.operational_node_id),
            origin.locator_kind,
            origin.locator_id,
            str(destination.operational_node_id),
            destination.locator_kind,
            destination.locator_id,
        )
    ).encode("utf-8")
    return MovementPlanId(MOVEMENT_PLAN_ID_PREFIX + sha256(payload).hexdigest()[:24])


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


class MovementResolver:
    """Derive Movement Plan candidates from Spatial state and reusable profiles.

    Spatial geometry owns the stable relation between contexts. Movement rules
    describe reusable operation families. Neither layer materializes an OD
    Route table, so adding a new body/node does not require pairwise definitions.
    """

    def __init__(
        self,
        graph: SpatialGraph,
        facilities: FacilityBook,
        *,
        surface_rules: tuple[SurfaceTransportMovementRule, ...] = (),
        surface_access_rules: tuple[SurfaceAccessMovementRule, ...] = (),
        spaceflight_rules: tuple[SpaceflightMovementRule, ...] = (),
    ) -> None:
        self.graph = graph
        self.facilities = facilities
        self.surface_rules = surface_rules
        self.surface_access_rules = surface_access_rules
        self.spaceflight_rules = spaceflight_rules

    def direct_plans(
        self, origin_id: SpatialNodeId, destination_id: SpatialNodeId
    ) -> tuple[MovementPlan, ...]:
        if origin_id == destination_id:
            return ()
        if not self.graph.has_operational_node(origin_id) or not self.graph.has_operational_node(destination_id):
            return ()

        origin_location = self.graph.locations.get(origin_id)
        destination_location = self.graph.locations.get(destination_id)
        if (
            origin_location is not None
            and destination_location is not None
            and origin_location.body_id == destination_location.body_id
        ):
            return tuple(sorted(self._surface_plans(origin_id, destination_id), key=lambda row: str(row.id)))

        rows = self._space_connected_plans(origin_id, destination_id)
        return tuple(sorted(rows, key=lambda row: str(row.id)))

    def plans_to_physical_target(
        self, origin_id: SpatialNodeId, target_cell_id: SurfaceCellId
    ) -> tuple[MovementPlan, ...]:
        """Derive one-shot Movement to a surface target without creating a Node."""
        if not self.graph.has_operational_node(origin_id):
            return ()
        target_cell = self.graph.surface_cells.get(target_cell_id)
        if target_cell is None:
            return ()

        origin_location = self.graph.locations.get(origin_id)
        if origin_location is not None and origin_location.body_id == target_cell.body_id:
            return tuple(sorted(
                self._surface_target_plans(origin_id, target_cell_id), key=lambda row: str(row.id)
            ))

        destination = MovementEndpoint(physical_target_cell_id=target_cell_id)
        rows: list[MovementPlan] = []
        for origin_endpoint, origin_rule in self._space_origin_endpoints(origin_id):
            for destination_rule in self._access_rules_for_body(target_cell.body_id):
                for space_rule in self._spaceflight_rules_for(
                    origin_endpoint, destination, require_spaceflight=self._different_body(origin_endpoint, destination)
                ):
                    rows.append(self._build_space_connected_plan(
                        origin_endpoint,
                        destination,
                        origin_rule=origin_rule,
                        destination_rule=destination_rule,
                        space_rule=space_rule,
                    ))
        return tuple(sorted(rows, key=lambda row: str(row.id)))

    def outbound_plans(self, origin_id: SpatialNodeId) -> tuple[MovementPlan, ...]:
        if not self.graph.has_operational_node(origin_id):
            return ()
        plans: list[MovementPlan] = []
        for destination in self.graph.operational_nodes():
            if destination.id == origin_id:
                continue
            plans.extend(self.direct_plans(origin_id, destination.id))
        return tuple(sorted(plans, key=lambda row: (str(row.destination_id), str(row.id))))

    def inbound_plans(self, destination_id: SpatialNodeId) -> tuple[MovementPlan, ...]:
        if not self.graph.has_operational_node(destination_id):
            return ()
        plans: list[MovementPlan] = []
        for origin in self.graph.operational_nodes():
            if origin.id == destination_id:
                continue
            plans.extend(self.direct_plans(origin.id, destination_id))
        return tuple(sorted(plans, key=lambda row: (str(row.origin_id), str(row.id))))

    def all_direct_plans(self) -> tuple[MovementPlan, ...]:
        plans: list[MovementPlan] = []
        nodes = tuple(node.id for node in self.graph.operational_nodes())
        for origin_id in nodes:
            for destination_id in nodes:
                if origin_id != destination_id:
                    plans.extend(self.direct_plans(origin_id, destination_id))
        return tuple(sorted(plans, key=lambda row: str(row.id)))

    def _access_rules_for_body(self, body_id: CelestialBodyId) -> tuple[SurfaceAccessMovementRule, ...]:
        return tuple(
            sorted(
                (rule for rule in self.surface_access_rules if rule.body_id == body_id),
                key=lambda row: str(row.id),
            )
        )

    def _surface_plans(self, origin_id: SpatialNodeId, destination_id: SpatialNodeId) -> Iterable[MovementPlan]:
        origin = self.graph.locations.get(origin_id)
        destination = self.graph.locations.get(destination_id)
        if origin is None or destination is None or origin.body_id != destination.body_id:
            return ()
        rows: list[MovementPlan] = []
        body = self.graph.bodies[origin.body_id]
        for rule in sorted(self.surface_rules, key=lambda row: str(row.id)):
            for origin_gateway_id in _gateways(self.facilities, origin_id, rule.gateway_capability_id):
                for destination_gateway_id in _gateways(self.facilities, destination_id, rule.gateway_capability_id):
                    origin_endpoint = MovementEndpoint(origin_id, surface_interface_id=origin_gateway_id)
                    destination_endpoint = MovementEndpoint(destination_id, surface_interface_id=destination_gateway_id)
                    origin_resolved = resolve_movement_endpoint(origin_endpoint, self.facilities)
                    destination_resolved = resolve_movement_endpoint(destination_endpoint, self.facilities)
                    assert origin_resolved.surface_cell_id is not None
                    assert destination_resolved.surface_cell_id is not None
                    origin_cell = self.graph.surface_cells[origin_resolved.surface_cell_id]
                    destination_cell = self.graph.surface_cells[destination_resolved.surface_cell_id]
                    distance = great_circle_distance_km(
                        origin_cell.centroid, destination_cell.centroid, body.mean_radius_km
                    )
                    relation = SpatialRelation(
                        origin_resolved.environment_context_id,
                        destination_resolved.environment_context_id,
                        "surface",
                        characteristic_distance_km=distance,
                    )
                    rows.append(MovementPlan(
                        _stable_plan_id((rule.id,), origin_endpoint, destination_endpoint),
                        origin_endpoint,
                        destination_endpoint,
                        relation,
                        max(1, rule.transit_days),
                        (rule.operation,),
                        display_name=f"{origin.display_name} → {destination.display_name} {rule.display_name}",
                    ))
        return rows

    def _surface_target_plans(
        self, origin_id: SpatialNodeId, target_cell_id: SurfaceCellId
    ) -> Iterable[MovementPlan]:
        origin = self.graph.locations[origin_id]
        target = self.graph.surface_cells[target_cell_id]
        body = self.graph.bodies[origin.body_id]
        rows: list[MovementPlan] = []
        for rule in sorted(self.surface_rules, key=lambda row: str(row.id)):
            for origin_gateway_id in _gateways(self.facilities, origin_id, rule.gateway_capability_id):
                a = MovementEndpoint(origin_id, surface_interface_id=origin_gateway_id)
                b = MovementEndpoint(physical_target_cell_id=target_cell_id)
                origin_resolved = resolve_movement_endpoint(a, self.facilities)
                assert origin_resolved.surface_cell_id is not None
                origin_cell = self.graph.surface_cells[origin_resolved.surface_cell_id]
                distance = great_circle_distance_km(origin_cell.centroid, target.centroid, body.mean_radius_km)
                relation = SpatialRelation(
                    origin_resolved.environment_context_id,
                    target_cell_id,
                    "surface",
                    characteristic_distance_km=distance,
                )
                rows.append(MovementPlan(
                    _stable_plan_id((rule.id,), a, b),
                    a,
                    b,
                    relation,
                    max(1, rule.transit_days),
                    (rule.operation,),
                    display_name=f"{origin.display_name} → {target.display_name} {rule.display_name}",
                ))
        return rows

    def _space_connected_plans(
        self, origin_id: SpatialNodeId, destination_id: SpatialNodeId
    ) -> list[MovementPlan]:
        rows: list[MovementPlan] = []
        for origin_endpoint, origin_rule in self._space_origin_endpoints(origin_id):
            for destination_endpoint, destination_rule in self._space_destination_endpoints(destination_id):
                require_spaceflight = self._requires_spaceflight(origin_endpoint, destination_endpoint)
                for space_rule in self._spaceflight_rules_for(
                    origin_endpoint, destination_endpoint, require_spaceflight=require_spaceflight
                ):
                    rows.append(self._build_space_connected_plan(
                        origin_endpoint,
                        destination_endpoint,
                        origin_rule=origin_rule,
                        destination_rule=destination_rule,
                        space_rule=space_rule,
                    ))
        return rows

    def _space_origin_endpoints(
        self, node_id: SpatialNodeId
    ) -> tuple[tuple[MovementEndpoint, SurfaceAccessMovementRule | None], ...]:
        location = self.graph.locations.get(node_id)
        if location is None:
            return ((MovementEndpoint(node_id, non_surface_interface="operational_node"), None),)
        rows: list[tuple[MovementEndpoint, SurfaceAccessMovementRule | None]] = []
        for rule in self._access_rules_for_body(location.body_id):
            for gateway_id in _gateways(self.facilities, node_id, rule.gateway_capability_id):
                rows.append((MovementEndpoint(node_id, surface_interface_id=gateway_id), rule))
        return tuple(rows)

    def _space_destination_endpoints(
        self, node_id: SpatialNodeId
    ) -> tuple[tuple[MovementEndpoint, SurfaceAccessMovementRule | None], ...]:
        location = self.graph.locations.get(node_id)
        if location is None:
            return ((MovementEndpoint(node_id, non_surface_interface="operational_node"), None),)
        rows: list[tuple[MovementEndpoint, SurfaceAccessMovementRule | None]] = []
        for rule in self._access_rules_for_body(location.body_id):
            for gateway_id in _gateways(self.facilities, node_id, rule.gateway_capability_id):
                rows.append((MovementEndpoint(node_id, surface_interface_id=gateway_id), rule))
        return tuple(rows)

    def _different_body(self, origin: MovementEndpoint, destination: MovementEndpoint) -> bool:
        origin_resolved = resolve_movement_endpoint(origin, self.facilities)
        destination_resolved = resolve_movement_endpoint(destination, self.facilities)
        origin_body = self.graph.context_body_id(origin_resolved.environment_context_id)
        destination_body = self.graph.context_body_id(destination_resolved.environment_context_id)
        return origin_body != destination_body

    def _requires_spaceflight(self, origin: MovementEndpoint, destination: MovementEndpoint) -> bool:
        origin_resolved = resolve_movement_endpoint(origin, self.facilities)
        destination_resolved = resolve_movement_endpoint(destination, self.facilities)
        if origin_resolved.surface_cell_id is not None and destination_resolved.surface_cell_id is not None:
            return self.graph.context_body_id(origin_resolved.surface_cell_id) != self.graph.context_body_id(
                destination_resolved.surface_cell_id
            )
        if origin_resolved.surface_cell_id is None and destination_resolved.surface_cell_id is None:
            # Distinct non-surface contexts still require a Movement operation even
            # when their characteristic anchors coincide (for example local
            # maneuver / docking between co-located orbital facilities).
            return True
        origin_body = self.graph.context_body_id(origin_resolved.environment_context_id)
        destination_body = self.graph.context_body_id(destination_resolved.environment_context_id)
        if origin_body != destination_body:
            return True
        # Two distinct non-surface endpoints in the same body/system still need
        # a movement operation if their characteristic anchors differ.
        separation = self.graph.characteristic_transport_separation(
            origin_resolved.environment_context_id, destination_resolved.environment_context_id
        )
        return separation.distance_km > 1e-9 or separation.delta_v_km_s > 1e-9

    def _spaceflight_rules_for(
        self,
        origin: MovementEndpoint,
        destination: MovementEndpoint,
        *,
        require_spaceflight: bool,
    ) -> tuple[SpaceflightMovementRule | None, ...]:
        if not require_spaceflight:
            return (None,)
        return tuple(sorted(self.spaceflight_rules, key=lambda row: str(row.id)))

    def _build_space_connected_plan(
        self,
        origin: MovementEndpoint,
        destination: MovementEndpoint,
        *,
        origin_rule: SurfaceAccessMovementRule | None,
        destination_rule: SurfaceAccessMovementRule | None,
        space_rule: SpaceflightMovementRule | None,
    ) -> MovementPlan:
        origin_resolved = resolve_movement_endpoint(origin, self.facilities)
        destination_resolved = resolve_movement_endpoint(destination, self.facilities)
        separation = self.graph.characteristic_transport_separation(
            origin_resolved.environment_context_id,
            destination_resolved.environment_context_id,
        )

        operations: list[TransportOperationRequirement] = []
        rule_ids: list[DefinitionId] = []
        transit_days = 0
        origin_requirements = SiteRequirements()
        destination_requirements = SiteRequirements()

        if origin_rule is not None:
            operations.extend(origin_rule.ascent_operations)
            rule_ids.append(origin_rule.id)
            transit_days += origin_rule.transit_days
            origin_requirements = origin_rule.surface_requirements
            if space_rule is None and destination_rule is None:
                destination_requirements = origin_rule.space_requirements
        elif space_rule is not None:
            origin_requirements = space_rule.origin_requirements

        if space_rule is not None:
            operations.append(TransportOperationRequirement(
                space_rule.operation_type,
                separation.delta_v_km_s,
            ))
            rule_ids.append(space_rule.id)
            transit_days += max(
                space_rule.minimum_transit_days,
                ceil(separation.distance_km / space_rule.characteristic_speed_km_per_day - 1e-12),
            )

        if destination_rule is not None:
            operations.extend(destination_rule.descent_operations)
            rule_ids.append(destination_rule.id)
            transit_days += destination_rule.transit_days
            destination_requirements = destination_rule.surface_requirements
            if space_rule is None and origin_rule is None:
                origin_requirements = destination_rule.space_requirements
        elif space_rule is not None:
            destination_requirements = space_rule.destination_requirements

        if not operations:
            raise ValueError("movement relation produced no operations")

        relation_context = separation.scope
        if origin_resolved.surface_cell_id is not None or destination_resolved.surface_cell_id is not None:
            relation_context = f"{relation_context}_surface_access"
        origin_name = self._endpoint_display_name(origin)
        destination_name = self._endpoint_display_name(destination)
        return MovementPlan(
            _stable_plan_id(tuple(rule_ids), origin, destination),
            origin,
            destination,
            SpatialRelation(
                origin_resolved.environment_context_id,
                destination_resolved.environment_context_id,
                relation_context,
                characteristic_distance_km=separation.distance_km,
                characteristic_delta_v_km_s=separation.delta_v_km_s,
            ),
            max(1, transit_days),
            tuple(operations),
            display_name=f"{origin_name} → {destination_name}",
            origin_requirements=origin_requirements,
            destination_requirements=destination_requirements,
        )

    def _endpoint_display_name(self, endpoint: MovementEndpoint) -> str:
        if endpoint.operational_node_id is not None:
            return self.graph.operational_node(endpoint.operational_node_id).display_name
        assert endpoint.physical_target_cell_id is not None
        return self.graph.surface_cells[endpoint.physical_target_cell_id].display_name
