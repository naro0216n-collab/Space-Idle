from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

PathPolicyLiteral = Literal["fastest", "lowest_cost", "lowest_propellant"]
TransportControlModeLiteral = Literal["units", "capacity"]


@dataclass(frozen=True)
class ProduceVehicle:
    vehicle_definition_id: str
    location_id: str
    priority: int = 50
    allocation_weight: float = 1.0


@dataclass(frozen=True)
class PauseVehicleProduction:
    production_id: str


@dataclass(frozen=True)
class ResumeVehicleProduction:
    production_id: str


@dataclass(frozen=True)
class SetVehicleProductionSettings:
    production_id: str
    priority: int | None = None
    allocation_weight: float | None = None


@dataclass(frozen=True)
class CreateTransportAllocation:
    vehicle_definition_id: str
    anchor_location_id: str
    destination_id: str
    priority: int = 50
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
    priority: int | None = None
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


@dataclass(frozen=True)
class CreateLogisticsLane:
    source_id: str
    destination_id: str
    requested_capacity_t_per_day: float
    priority: int = 50
    path: tuple[str, ...] | None = None
    path_policy: PathPolicyLiteral = "fastest"


@dataclass(frozen=True)
class UpdateLogisticsLane:
    lane_id: str
    requested_capacity_t_per_day: float
    priority: int
    path_policy: PathPolicyLiteral | None = None


@dataclass(frozen=True)
class PauseLogisticsLane:
    lane_id: str


@dataclass(frozen=True)
class ResumeLogisticsLane:
    lane_id: str


@dataclass(frozen=True)
class DeleteLogisticsLane:
    lane_id: str
