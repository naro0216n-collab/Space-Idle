from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyMetricRow:
    id: str
    display_name: str
    unit: str
    member_resource_ids: tuple[str, ...]
    local_production_per_day: float
    local_consumption_per_day: float
    external_dependency_per_day: float
    local_coverage_ratio: float | None
    imports_pipeline: float
    exports_pipeline: float
    unmet_demand: float
    dependency_source_node_ids: tuple[str, ...]
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class DependencyAnalyticsView:
    scope_kind: str
    scope_id: str | None
    node_ids: tuple[str, ...]
    day: int
    resources: tuple[DependencyMetricRow, ...]
    resource_groups: tuple[DependencyMetricRow, ...]
    critical_dependency_resource_ids: tuple[str, ...]