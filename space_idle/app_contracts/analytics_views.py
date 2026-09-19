from __future__ import annotations

from .ui_reports import DecisionConstraintRow
from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentDependencyMetricRow:
    id: str
    display_name: str
    unit: str
    member_resource_ids: tuple[str, ...]
    production_per_day: float
    consumption_per_day: float
    demand_per_day: float
    external_dependency_per_day: float
    local_coverage_ratio: float | None
    imports_per_day: float
    exports_per_day: float
    imports_pipeline_t: float
    exports_pipeline_t: float
    unmet_demand_t: float
    dependency_source_node_ids: tuple[str, ...]
    limiting_factors: tuple[DecisionConstraintRow, ...]


@dataclass(frozen=True)
class ForecastDependencyMetricRow:
    id: str
    display_name: str
    unit: str
    member_resource_ids: tuple[str, ...]
    planned_requirement_t: float
    recurring_consumption_per_day: float
    external_requirement_t: float
    external_recurring_dependency_per_day: float
    target_stock_t: float
    earliest_requirement_day: int | None
    dependency_source_node_ids: tuple[str, ...]
    limiting_factors: tuple[DecisionConstraintRow, ...]


@dataclass(frozen=True)
class CurrentServiceDependencyMetricRow:
    service_type: str
    scope: str
    local_nominal_rate: float
    local_enabled_rate: float
    outside_scope_enabled_rate: float
    requested_rate: float
    allocated_rate: float
    unmet_rate: float
    external_dependency_rate: float
    local_coverage_ratio: float | None
    limiting_factors: tuple[DecisionConstraintRow, ...]


@dataclass(frozen=True)
class ForecastServiceDependencyMetricRow:
    service_type: str
    scope: str
    planned_requirement: float
    local_enabled_rate: float
    outside_scope_enabled_rate: float
    earliest_requirement_day: int | None
    limiting_factors: tuple[DecisionConstraintRow, ...]


@dataclass(frozen=True)
class DetailedForecastInventoryRow:
    resource_id: str
    display_name: str
    unit: str
    current_amount: float
    projected_amount: float
    delta_amount: float
    projected_production_per_day: float
    projected_consumption_per_day: float
    projected_external_dependency_per_day: float
    steady_state: str


@dataclass(frozen=True)
class DetailedForecastImpactRow:
    kind: str
    subject_id: str
    display_name: str
    current_state: str
    projected_state: str


@dataclass(frozen=True)
class DetailedForecastLogisticsRow:
    requirement_id: str
    resource_id: str
    destination_id: str
    source_id: str | None
    handoff_count: int
    service_ids: tuple[str, ...]
    projected_arrival_day: int | None
    projected_latency_days: float | None
    pipeline_t: float
    remaining_t: float
    supply_state: str


@dataclass(frozen=True)
class DetailedForecastView:
    scope_kind: str
    scope_id: str | None
    node_ids: tuple[str, ...]
    base_day: int
    projected_day: int
    horizon: str
    period_days: int
    inventory: tuple[DetailedForecastInventoryRow, ...]
    downstream_impacts: tuple[DetailedForecastImpactRow, ...]
    logistics_impacts: tuple[DetailedForecastLogisticsRow, ...]


@dataclass(frozen=True)
class DependencyAnalyticsView:
    scope_kind: str
    scope_id: str | None
    node_ids: tuple[str, ...]
    day: int
    time_basis: str
    current_resources: tuple[CurrentDependencyMetricRow, ...] = ()
    current_resource_groups: tuple[CurrentDependencyMetricRow, ...] = ()
    forecast_resources: tuple[ForecastDependencyMetricRow, ...] = ()
    forecast_resource_groups: tuple[ForecastDependencyMetricRow, ...] = ()
    current_services: tuple[CurrentServiceDependencyMetricRow, ...] = ()
    forecast_services: tuple[ForecastServiceDependencyMetricRow, ...] = ()
    critical_dependency_resource_ids: tuple[str, ...] = ()
    critical_dependency_service_types: tuple[str, ...] = ()
