from __future__ import annotations
from dataclasses import dataclass
from ..priority import (
    ActivityPriority, DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PROVISIONING_PRIORITY, ProvisioningPriority,
)


@dataclass(frozen=True)
class ProduceVehicle:
    vehicle_definition_id: str
    operational_node_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY


@dataclass(frozen=True)
class PauseVehicleProduction:
    production_id: str


@dataclass(frozen=True)
class ResumeVehicleProduction:
    production_id: str


@dataclass(frozen=True)
class SetVehicleProductionSettings:
    production_id: str
    priority: ActivityPriority | None = None


@dataclass(frozen=True)
class CreateTransportAllocation:
    vehicle_definition_id: str
    anchor_node_id: str
    destination_id: str
    target_forward_t_per_day: float
    target_reverse_t_per_day: float
    provisioning_priority: ProvisioningPriority = DEFAULT_PROVISIONING_PRIORITY
    movement_hard_constraint: tuple[str, ...] | None = None
    paused: bool = False


@dataclass(frozen=True)
class UpdateTransportAllocation:
    allocation_id: str
    target_forward_t_per_day: float | None = None
    target_reverse_t_per_day: float | None = None
    provisioning_priority: ProvisioningPriority | None = None


@dataclass(frozen=True)
class SetTransportMovementConstraint:
    allocation_id: str
    movement_plan_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClearTransportMovementConstraint:
    allocation_id: str


@dataclass(frozen=True)
class PauseTransportAllocation:
    allocation_id: str


@dataclass(frozen=True)
class ResumeTransportAllocation:
    allocation_id: str


@dataclass(frozen=True)
class DeleteTransportAllocation:
    allocation_id: str


@dataclass(frozen=True)
class RetireFleet:
    vehicle_definition_id: str
    units: int
    operational_node_id: str
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY


@dataclass(frozen=True)
class CancelFleetRetirement:
    retirement_id: str


@dataclass(frozen=True)
class SetFleetRetirementPriority:
    retirement_id: str
    priority: ActivityPriority


@dataclass(frozen=True)
class RelocateFleet:
    vehicle_definition_id: str
    units: int
    source_id: str
    destination_id: str
    movement_hard_constraint: tuple[str, ...] | None = None
