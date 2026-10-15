"""Fixed-installation cargo movement without fictitious Fleet units.

Logistics sees the same immutable TransportServiceSupply/Execution Bundle contract
as mobile Fleet. The transport operator owns player targets; Facility and Power
own physical finite source/receiver capacity and material maintenance.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ..shared import DefinitionId, EntityId
from ..facilities import FacilityBook, FacilityLifecycle
from .models import TransportServiceSupply, TransportOperationUsageRequirements


@dataclass(frozen=True)
class InfrastructureTransportMethod:
    id: DefinitionId
    launch_service: str
    capture_service: str
    launch_service_per_t: float
    capture_service_per_t: float
    max_distance_km: float
    transit_speed_km_per_day: float
    payload_support_resource_id: DefinitionId | None = None
    payload_support_resource_per_t: float = 0.0
    same_body: bool = False

    def __post_init__(self) -> None:
        if not self.launch_service or not self.capture_service:
            raise ValueError("physical fixed-transport endpoints need finite service")
        for value in (self.launch_service_per_t, self.capture_service_per_t,
                      self.max_distance_km, self.transit_speed_km_per_day):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("infrastructure movement parameters must be finite and positive")
        if not math.isfinite(self.payload_support_resource_per_t) or self.payload_support_resource_per_t < 0:
            raise ValueError("invalid payload support amount")
        if (self.payload_support_resource_id is None) != (self.payload_support_resource_per_t <= 0):
            raise ValueError("positive payload support needs Resource definition")


@dataclass(frozen=True)
class InfrastructureFreightLink:
    id: EntityId
    method_id: DefinitionId
    origin_facility_id: EntityId
    destination_facility_id: EntityId
    target_t_per_day: float
    paused: bool = False

    def __post_init__(self) -> None:
        if self.origin_facility_id == self.destination_facility_id:
            raise ValueError("infrastructure transport endpoints must differ")
        if not math.isfinite(self.target_t_per_day) or self.target_t_per_day <= 0:
            raise ValueError("fixed infrastructure transport target must be positive")


def infrastructure_link_eligibility(
    link: InfrastructureFreightLink, method: InfrastructureTransportMethod,
    facilities: FacilityBook, day: int,
) -> tuple[bool, float]:
    source = facilities.facilities.get(link.origin_facility_id)
    destination = facilities.facilities.get(link.destination_facility_id)
    if source is None or destination is None:
        return False, 0.0
    if source.operational_node_id == destination.operational_node_id:
        return False, 0.0
    graph = facilities.environment.graph
    if method.same_body:
        source_node = graph.operational_node(source.operational_node_id)
        destination_node = graph.operational_node(destination.operational_node_id)
        if (source_node.body_id is None or
            source_node.body_id != destination_node.body_id or
            source.operational_node_id in graph.locations or
            destination.operational_node_id in graph.locations):
            return False, 0.0
    separation = graph.characteristic_transport_separation(
        facilities.facility_environment_context(source),
        facilities.facility_environment_context(destination),
    )
    distance = separation.distance_km
    if distance is None or distance > method.max_distance_km:
        return False, 0.0
    if (link.paused or source.paused or destination.paused or
        source.lifecycle is not FacilityLifecycle.NORMAL or
        destination.lifecycle is not FacilityLifecycle.NORMAL or
        not facilities.is_environmentally_compatible(source, day) or
        not facilities.is_environmentally_compatible(destination, day)):
        return False, distance
    origin_supplies = facilities.definitions[source.definition_id].service_capacity_supplies
    destination_supplies = facilities.definitions[destination.definition_id].service_capacity_supplies
    if (not any(row.service_type == method.launch_service for row in origin_supplies) or
        not any(row.service_type == method.capture_service for row in destination_supplies)):
        return False, distance
    return True, distance


def infrastructure_transport_supply(
    link: InfrastructureFreightLink, method: InfrastructureTransportMethod,
    facilities: FacilityBook, day: int,
) -> TransportServiceSupply | None:
    usable, distance = infrastructure_link_eligibility(link, method, facilities, day)
    if not usable:
        return None
    source = facilities.facilities[link.origin_facility_id]
    destination = facilities.facilities[link.destination_facility_id]
    return TransportServiceSupply(
        key=f"infrastructure:{link.id}:forward",
        source_id=source.operational_node_id,
        destination_id=destination.operational_node_id,
        capacity_t_per_day=link.target_t_per_day,
        latency_days=max(1, math.ceil(distance / method.transit_speed_km_per_day)),
        cycle_days=1.0,
        movement_plan_path=(),
        allocation_id=link.id,
        direction="forward",
    )


def infrastructure_operation_requirements(
    link: InfrastructureFreightLink, method: InfrastructureTransportMethod,
    facilities: FacilityBook,
) -> TransportOperationUsageRequirements:
    source = facilities.facilities[link.origin_facility_id]
    destination = facilities.facilities[link.destination_facility_id]
    return TransportOperationUsageRequirements(
        link.id,
        (((source.operational_node_id, method.payload_support_resource_id,
            method.payload_support_resource_per_t),)
         if method.payload_support_resource_id is not None else ()),
        (),
        None,
        source.operational_node_id,
        forward_service_per_t=(
            (source.operational_node_id, method.launch_service, method.launch_service_per_t),
            (destination.operational_node_id, method.capture_service, method.capture_service_per_t),
        ),
    )
