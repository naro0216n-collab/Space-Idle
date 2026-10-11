from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetPopulationTarget:
    operational_node_id: str
    desired_count: int

    def __post_init__(self) -> None:
        if not self.operational_node_id or isinstance(self.desired_count, bool) or not isinstance(self.desired_count, int) or self.desired_count < 0:
            raise ValueError('population target requires an existing node and nonnegative integer')


@dataclass(frozen=True)
class ClearPopulationTarget:
    operational_node_id: str

    def __post_init__(self) -> None:
        if not self.operational_node_id:
            raise ValueError('population target node required')


@dataclass(frozen=True)
class PassengerCapacityChoice:
    transport_allocation_ids: tuple[str, ...] | None = None
    dedicated_vehicle_definition_id: str | None = None
    dedicated_units: int | None = None
    movement_hard_constraint: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        from ..population import PassengerCapacitySource
        from ..shared import DefinitionId, EntityId
        PassengerCapacitySource(
            None if self.transport_allocation_ids is None else tuple(EntityId(value) for value in self.transport_allocation_ids),
            None if self.dedicated_vehicle_definition_id is None else DefinitionId(self.dedicated_vehicle_definition_id),
            self.dedicated_units, self.movement_hard_constraint,
        )


@dataclass(frozen=True)
class RequestPassengerTransfer:
    origin_node_id: str
    destination_node_id: str
    requested_count: int
    source_external_provider_id: str | None = None
    activity_priority: int = 3
    capacity_source_constraint: PassengerCapacityChoice | None = None

    def __post_init__(self) -> None:
        from ..priority import ActivityPriority
        ActivityPriority(self.activity_priority)
        if not self.origin_node_id or not self.destination_node_id or self.origin_node_id == self.destination_node_id:
            raise ValueError('passenger transfer requires two distinct established nodes')
        if isinstance(self.requested_count, bool) or not isinstance(self.requested_count, int) or self.requested_count < 1:
            raise ValueError('passenger transfer count must be a positive integer')


@dataclass(frozen=True)
class CancelPassengerTransfer:
    order_id: str

    def __post_init__(self) -> None:
        if not self.order_id:
            raise ValueError('passenger transfer order ID required')


@dataclass(frozen=True)
class GetPassengerTransferPreview:
    origin_node_id: str
    destination_node_id: str
    requested_count: int
    source_external_provider_id: str | None = None

    def __post_init__(self) -> None:
        RequestPassengerTransfer(self.origin_node_id, self.destination_node_id, self.requested_count,
                                 source_external_provider_id=self.source_external_provider_id)


@dataclass(frozen=True)
class GetPassengerTransfers:
    operational_node_id: str | None = None
