from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PauseFacility: facility_id: str
@dataclass(frozen=True)
class ResumeFacility: facility_id: str
@dataclass(frozen=True)
class SetFacilityProcess:
    facility_id: str; process_id: str
@dataclass(frozen=True)
class SetPowerPriority:
    facility_id: str; priority: int | None
@dataclass(frozen=True)
class SetMaintenancePriority:
    facility_id: str; priority: int
@dataclass(frozen=True)
class AdvanceTime: days: int
