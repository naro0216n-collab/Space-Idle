from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

PathPolicyLiteral = Literal["fastest", "lowest_cost", "lowest_propellant"]


@dataclass(frozen=True)
class DispatchVehicle:
    vehicle_id: str
    route_id: str
    carrier_vehicle_id: str | None = None


@dataclass(frozen=True)
class RefuelVehicle:
    vehicle_id: str
    amount_t: float | None = None


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
class SubmitCargo:
    source_id: str
    destination_id: str
    resource_id: str
    amount_t: float
    priority: int = 50
    path: tuple[str, ...] | None = None
    route_modes: tuple[tuple[str, str], ...] = ()
    path_policy: PathPolicyLiteral = "fastest"


@dataclass(frozen=True)
class CreateLogisticsLane:
    source_id: str
    destination_id: str
    requested_capacity_t_per_day: float
    priority: int = 50
    path: tuple[str, ...] | None = None
    route_modes: tuple[tuple[str, str], ...] = ()
    path_policy: PathPolicyLiteral = "fastest"


@dataclass(frozen=True)
class UpdateLogisticsLane:
    lane_id: str
    requested_capacity_t_per_day: float
    priority: int


@dataclass(frozen=True)
class PauseLogisticsLane:
    lane_id: str


@dataclass(frozen=True)
class ResumeLogisticsLane:
    lane_id: str


@dataclass(frozen=True)
class DeleteLogisticsLane:
    lane_id: str
