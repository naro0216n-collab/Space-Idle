from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

PathPolicyLiteral = Literal["fastest", "lowest_cost", "lowest_propellant"]
@dataclass(frozen=True)
class DispatchVehicle:
    vehicle_id: str; route_id: str; carrier_vehicle_id: str | None = None
@dataclass(frozen=True)
class RefuelVehicle:
    vehicle_id: str; amount_t: float | None = None
@dataclass(frozen=True)
class ProduceVehicle:
    vehicle_definition_id: str; location_id: str
@dataclass(frozen=True)
class SubmitCargo:
    source_id: str; destination_id: str; resource_id: str; amount_t: float
    priority: int = 50
    path: tuple[str, ...] | None = None
    route_modes: tuple[tuple[str, str], ...] = ()
    path_policy: PathPolicyLiteral = "fastest"
@dataclass(frozen=True)
class CreateLogisticsRule:
    source_id: str; destination_id: str; resource_id: str; target_stock_t: float; batch_t: float
    priority: int = 50
    path: tuple[str, ...] | None = None
    route_modes: tuple[tuple[str, str], ...] = ()
    path_policy: PathPolicyLiteral = "fastest"
@dataclass(frozen=True)
class PauseLogisticsRule: rule_id: str
@dataclass(frozen=True)
class ResumeLogisticsRule: rule_id: str
@dataclass(frozen=True)
class DeleteLogisticsRule: rule_id: str
