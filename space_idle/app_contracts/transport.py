from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from ..priority import (
    ActivityPriority, DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PROVISIONING_PRIORITY, ProvisioningPriority,
)

PathPolicyLiteral = Literal["fastest", "lowest_cost", "lowest_propellant"]
TransportControlModeLiteral = Literal["units", "capacity"]


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
    provisioning_priority: ProvisioningPriority = DEFAULT_PROVISIONING_PRIORITY
    control_mode: TransportControlModeLiteral = "units"
    target_units: int | None = None
    target_forward_t_per_day: float | None = None
    target_reverse_t_per_day: float | None = None
    path: tuple[str, ...] | None = None
    path_policy: PathPolicyLiteral = "fastest"
    paused: bool = False


@dataclass(frozen=True)
class UpdateTransportAllocation:
    allocation_id: str
    provisioning_priority: ProvisioningPriority | None = None
    target_units: int | None = None
    target_forward_t_per_day: float | None = None
    target_reverse_t_per_day: float | None = None
    path_policy: PathPolicyLiteral | None = None


@dataclass(frozen=True)
class ChangeTransportAllocationMode:
    allocation_id: str
    control_mode: TransportControlModeLiteral


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
class RelocateFleet:
    vehicle_definition_id: str
    units: int
    source_id: str
    destination_id: str
    path: tuple[str, ...] | None = None
    path_policy: PathPolicyLiteral = "fastest"
