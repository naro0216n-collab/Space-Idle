from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class IssueRow:
    """Normalized UI-facing explanation of a blocked or constrained state."""

    code: str
    message: str
    category: str
    source: str
    location_id: str | None = None
    entity_id: str | None = None
    definition_id: str | None = None
    resource_id: str | None = None
    impact: str = "blocked"


@dataclass(frozen=True)
class ResourceFlowRow:
    resource_id: str
    display_name: str
    unit: str
    local_production_per_day: float
    local_consumption_per_day: float
    local_net_per_day: float
    stock: float
    reserved: float
    available: float
    free_capacity: float | None
    outbound_waiting_t: float
    outbound_in_transit_t: float
    inbound_in_transit_t: float
    arrival_waiting_t: float


@dataclass(frozen=True)
class FlowReportView:
    location_id: str
    day: int
    power_generation_mw: float
    power_demand_mw: float
    power_allocated_mw: float
    power_utilization: float
    construction_capacity_per_day: float
    resources: tuple[ResourceFlowRow, ...]
    issues: tuple[IssueRow, ...]


@dataclass(frozen=True)
class BottlenecksView:
    day: int
    location_id: str | None
    items: tuple[IssueRow, ...]
