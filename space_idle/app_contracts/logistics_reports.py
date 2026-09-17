from __future__ import annotations
from dataclasses import dataclass
from .logistics_views import (
    CargoFlowRow, FleetPoolRow, FleetCommitmentRow, FleetRelocationResourceRequirementRow,
    FleetRelocationRow, FleetReleaseRow, FleetRetirementRow, InfrastructureRequirementRow,
    SupplyRequirementRow, MovementPlanRow, TransportAllocationRow,
)


@dataclass(frozen=True)
class LogisticsSummaryView:
    movement_plan_count: int
    usable_movement_plan_count: int
    fleet_units: int
    free_fleet_units: int
    allocation_count: int
    unfilled_allocation_units: int
    cargo_flow_count: int
    supply_policy_count: int
    target_stock_count: int
    requirement_count: int
    queued_supply_t: float
    in_transit_t: float
    arrival_waiting_t: float


@dataclass(frozen=True)
class MovementPlansView:
    items: tuple[MovementPlanRow, ...]


@dataclass(frozen=True)
class FleetView:
    pools: tuple[FleetPoolRow, ...]
    commitments: tuple[FleetCommitmentRow, ...]
    relocations: tuple[FleetRelocationRow, ...]
    releases: tuple[FleetReleaseRow, ...]
    retirements: tuple[FleetRetirementRow, ...]


@dataclass(frozen=True)
class FleetRelocationPreviewView:
    vehicle_definition_id: str
    display_name: str
    units: int
    source_id: str
    destination_id: str
    path_policy: str
    path: tuple[str, ...]
    travel_days: int
    departure_day: int
    arrival_day: int | None
    resource_requirements: tuple[FleetRelocationResourceRequirementRow, ...]
    infrastructure_requirements: tuple[InfrastructureRequirementRow, ...]
    feasible: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class TransportAllocationsView:
    items: tuple[TransportAllocationRow, ...]


@dataclass(frozen=True)
class CargoFlowsView:
    items: tuple[CargoFlowRow, ...]
