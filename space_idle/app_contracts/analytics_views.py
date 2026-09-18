from __future__ import annotations

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
    limiting_factors: tuple[str, ...]


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
    limiting_factors: tuple[str, ...]


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
    critical_dependency_resource_ids: tuple[str, ...] = ()
