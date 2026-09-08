from __future__ import annotations

from dataclasses import dataclass

from .shared import DefinitionId, SpatialNodeId


@dataclass(frozen=True)
class VehicleCapability:
    id: DefinitionId
    max_payload_t: float
    max_transfer_energy: float
    max_mission_days: int


@dataclass(frozen=True)
class TransferOption:
    origin_id: SpatialNodeId
    destination_id: SpatialNodeId
    departure_day: int
    duration_days: int
    transfer_energy: float


@dataclass(frozen=True)
class MissionPlan:
    origin_id: SpatialNodeId
    destination_id: SpatialNodeId
    vehicle_id: DefinitionId
    payload_t: float
    departure_day: int
    arrival_day: int


class MissionPlanner:
    def plan(self, vehicle: VehicleCapability, option: TransferOption, payload_t: float) -> MissionPlan:
        if payload_t < -1e-9:
            raise ValueError("payload must be non-negative")
        if vehicle.max_payload_t < 0 or vehicle.max_transfer_energy < 0 or vehicle.max_mission_days < 0:
            raise ValueError("vehicle capabilities must be non-negative")
        if option.departure_day < 0 or option.duration_days < 0 or option.transfer_energy < 0:
            raise ValueError("departure day, transfer duration and energy must be non-negative")
        if payload_t > vehicle.max_payload_t + 1e-9:
            raise ValueError("payload exceeds vehicle capability")
        if option.transfer_energy > vehicle.max_transfer_energy + 1e-9:
            raise ValueError("transfer energy exceeds vehicle capability")
        if option.duration_days > vehicle.max_mission_days:
            raise ValueError("mission duration exceeds vehicle capability")
        return MissionPlan(
            option.origin_id,
            option.destination_id,
            vehicle.id,
            payload_t,
            option.departure_day,
            option.departure_day + option.duration_days,
        )
