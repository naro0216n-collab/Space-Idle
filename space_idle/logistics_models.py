from __future__ import annotations

from dataclasses import dataclass
from .priority import ActivityPriority
from .shared import DefinitionId, EntityId, SpatialNodeId

_EPS = 1e-9


@dataclass(frozen=True)
class CargoServiceLeg:
    """Dispatch-time transport-service conditions for one logistics leg.

    These values are authoritative for Cargo that has already been dispatched.
    Later Fleet, Infrastructure, Technology, or Definition changes only affect
    new dispatches.
    """

    service_identity: str
    source_id: SpatialNodeId
    destination_id: SpatialNodeId
    latency_days: int
    cycle_days: float
    allocation_id: EntityId | None = None
    direction: str | None = None
    external_service_id: DefinitionId | None = None

    def __post_init__(self) -> None:
        if not self.service_identity:
            raise ValueError("cargo service identity must not be empty")
        if self.source_id == self.destination_id:
            raise ValueError("cargo service leg endpoints must differ")
        if self.latency_days <= 0:
            raise ValueError("cargo service leg latency must be positive")
        if self.cycle_days <= 0:
            raise ValueError("cargo service leg cycle must be positive")
        if (self.allocation_id is None) != (self.direction is None):
            raise ValueError("cargo service leg allocation and direction must be paired")
        if self.direction not in (None, "forward", "reverse"):
            raise ValueError("cargo service leg direction must be forward or reverse")
        if self.allocation_id is not None and self.external_service_id is not None:
            raise ValueError("cargo service leg cannot be both owned and external")


@dataclass
class CargoFlowSegment:
    """Logistics-owned in-transit flow under one unchanged service condition.

    ``dispatch_end_day`` is exclusive. A one-day dispatch on day D therefore
    occupies [D, D + 1). Adjacent same-rate dispatches with identical semantics
    are extended into one Segment rather than creating one persistent entity per
    tick. As dispatch slices arrive, ``dispatch_start_day`` advances and
    ``amount_t`` shrinks; completed history is not retained as authoritative
    simulation state.
    """

    id: EntityId
    resource_id: DefinitionId
    amount_t: float
    source_id: SpatialNodeId
    final_destination_id: SpatialNodeId
    requirement_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: ActivityPriority
    leg: CargoServiceLeg
    remaining_legs: tuple[CargoServiceLeg, ...]
    dispatch_start_day: int
    dispatch_end_day: int
    dispatch_rate_t_per_day: float

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.amount_t <= 0:
            raise ValueError("cargo flow segment amount must be positive")
        if self.dispatch_end_day <= self.dispatch_start_day:
            raise ValueError("cargo flow segment dispatch interval must be positive")
        if self.dispatch_rate_t_per_day <= 0:
            raise ValueError("cargo flow segment dispatch rate must be positive")
        if self.leg.source_id != self.source_id:
            raise ValueError("cargo flow segment source must match current service leg")
        expected = self.dispatch_rate_t_per_day * self.dispatch_days
        if abs(self.amount_t - expected) > max(_EPS, expected * 1e-8):
            raise ValueError("cargo flow segment amount must match dispatch interval and rate")
        chain = (self.leg,) + self.remaining_legs
        for current, following in zip(chain, chain[1:]):
            if current.destination_id != following.source_id:
                raise ValueError("cargo service path is not contiguous")
        if chain[-1].destination_id != self.final_destination_id:
            raise ValueError("cargo service path must end at final destination")

    @property
    def destination_id(self) -> SpatialNodeId:
        return self.leg.destination_id

    @property
    def transport_service_identity(self) -> str:
        return self.leg.service_identity

    @property
    def latency_days(self) -> int:
        return self.leg.latency_days

    @property
    def dispatch_days(self) -> int:
        return self.dispatch_end_day - self.dispatch_start_day

    @property
    def first_arrival_day(self) -> int:
        return self.dispatch_start_day + self.latency_days

    @property
    def last_arrival_day(self) -> int:
        return self.dispatch_end_day - 1 + self.latency_days


@dataclass
class CargoArrivalWaiting:
    """Logistics-owned Cargo that reached a handoff/final Operational Node.

    Arrival waiting has left the in-transit Segment but has not yet transferred
    ownership to Inventory or the next transport leg. The arrival service
    remains occupied in aggregate and therefore contributes backpressure until
    the waiting quantity is cleared.
    """

    id: EntityId
    resource_id: DefinitionId
    amount_t: float
    node_id: SpatialNodeId
    final_destination_id: SpatialNodeId
    requirement_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: ActivityPriority
    arrival_leg: CargoServiceLeg
    remaining_legs: tuple[CargoServiceLeg, ...]
    arrived_day: int

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.amount_t <= 0:
            raise ValueError("arrival waiting amount must be positive")
        if self.arrival_leg.destination_id != self.node_id:
            raise ValueError("arrival waiting node must match arrival service destination")
        if self.remaining_legs and self.remaining_legs[0].source_id != self.node_id:
            raise ValueError("arrival waiting next leg must start at waiting node")
        if self.remaining_legs:
            if self.remaining_legs[-1].destination_id != self.final_destination_id:
                raise ValueError("arrival waiting path must end at final destination")
        elif self.node_id != self.final_destination_id:
            raise ValueError("arrival waiting without next leg must be at final destination")

    @property
    def next_leg(self) -> CargoServiceLeg | None:
        return None if not self.remaining_legs else self.remaining_legs[0]


@dataclass
class CargoHandoffStaging:
    """Inventory-owned, reserved Cargo waiting to load onto the next leg.

    The physical Resource is held by Inventory under ``reservation_owner_id``;
    this state only owns the continuation commitment and frozen downstream
    service conditions. It must never be counted as Logistics-owned cargo mass.
    """

    id: EntityId
    resource_id: DefinitionId
    amount_t: float
    node_id: SpatialNodeId
    final_destination_id: SpatialNodeId
    requirement_id: EntityId | None
    owner_kind: str
    owner_id: EntityId
    priority: ActivityPriority
    reservation_owner_id: EntityId
    remaining_legs: tuple[CargoServiceLeg, ...]
    staged_day: int

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)
        if self.amount_t <= 0:
            raise ValueError("handoff staging amount must be positive")
        if not self.remaining_legs:
            raise ValueError("handoff staging requires a next transport leg")
        if self.remaining_legs[0].source_id != self.node_id:
            raise ValueError("handoff staging next leg must start at staging node")
        if self.remaining_legs[-1].destination_id != self.final_destination_id:
            raise ValueError("handoff staging path must end at final destination")

    @property
    def next_leg(self) -> CargoServiceLeg:
        return self.remaining_legs[0]
