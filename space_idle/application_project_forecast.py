from __future__ import annotations

from copy import copy, deepcopy

from .application_commands import GetDependencyAnalytics, GetDetailedForecast
from .application_views import (
    DetailedForecastImpactRow,
    DetailedForecastInventoryRow,
    DetailedForecastLogisticsRow,
    DetailedForecastView,
)

class DetailedForecastProjectorMixin:
    _FORECAST_DEFAULT_DAYS = {
        "SHORT_TERM": 30,
        "MEDIUM_TERM": 120,
        "STEADY_STATE": 365,
    }

    def _detailed_forecast_view(self, query: GetDetailedForecast) -> DetailedForecastView:
        horizon = query.horizon.upper()
        if horizon not in self._FORECAST_DEFAULT_DAYS:
            raise ValueError(f"unsupported detailed forecast horizon: {query.horizon}")
        days = self._FORECAST_DEFAULT_DAYS[horizon] if query.period_days is None else int(query.period_days)
        if days <= 0 or days > 3650:
            raise ValueError("detailed forecast period_days must be within 1..3650")

        scope_query = GetDependencyAnalytics(query.scope_kind, query.scope_id, query.node_ids, "CURRENT")
        nodes = self._dependency_scope_nodes(scope_query)
        selected = set(nodes)
        base = self._simulation
        current_dependency = self._dependency_analytics_view(scope_query)

        forecast_sim = deepcopy(base)
        forecast_sim.advance_days(days)
        projected = copy(self)
        projected._simulation = forecast_sim
        projected._query_projection_cache = None
        projected_dependency = projected._dependency_analytics_view(scope_query)

        current_metrics = {row.id: row for row in current_dependency.current_resources}
        projected_metrics = {row.id: row for row in projected_dependency.current_resources}
        resource_ids = sorted(
            set(current_metrics) | set(projected_metrics) |
            {str(resource_id) for node_id, resource_id in base.inventory.stock if node_id in selected} |
            {str(resource_id) for node_id, resource_id in forecast_sim.inventory.stock if node_id in selected}
        )
        inventory_rows: list[DetailedForecastInventoryRow] = []
        for resource_id in resource_ids:
            from .shared import DefinitionId
            definition_id = DefinitionId(resource_id)
            definition = self._catalog.resources.get(definition_id)
            current_amount = sum(base.inventory.amount(node_id, definition_id) for node_id in nodes)
            projected_amount = sum(forecast_sim.inventory.amount(node_id, definition_id) for node_id in nodes)
            metric = projected_metrics.get(resource_id)
            production = 0.0 if metric is None else metric.production_per_day
            consumption = 0.0 if metric is None else metric.consumption_per_day
            external = 0.0 if metric is None else metric.external_dependency_per_day
            net = production + (0.0 if metric is None else metric.imports_per_day) - consumption - (0.0 if metric is None else metric.exports_per_day)
            if abs(net) <= 1e-9:
                steady_state = "stable"
            elif net > 0:
                steady_state = "accumulating"
            else:
                steady_state = "depleting"
            if abs(projected_amount - current_amount) <= 1e-9 and metric is None:
                continue
            inventory_rows.append(DetailedForecastInventoryRow(
                resource_id=resource_id,
                display_name=resource_id if definition is None else definition.display_name,
                unit="t" if definition is None else definition.unit,
                current_amount=current_amount,
                projected_amount=projected_amount,
                delta_amount=projected_amount - current_amount,
                projected_production_per_day=production,
                projected_consumption_per_day=consumption,
                projected_external_dependency_per_day=external,
                steady_state=steady_state,
            ))

        impacts: list[DetailedForecastImpactRow] = []
        current_projects = {row.id: row for row in self._project_rows(None)}
        projected_projects = {row.id: row for row in projected._project_rows(None)}
        for project_id in sorted(set(current_projects) | set(projected_projects)):
            current = current_projects.get(project_id)
            future = projected_projects.get(project_id)
            reference = future or current
            if reference is None or reference.operational_node_id not in {str(node_id) for node_id in selected}:
                continue
            current_state = "not_started" if current is None else current.status
            future_state = "absent" if future is None else future.status
            if current_state == future_state:
                continue
            impacts.append(DetailedForecastImpactRow(
                "project", project_id, reference.display_name, current_state, future_state
            ))

        if base.research is not None and forecast_sim.research is not None:
            research_ids = sorted(set(base.research.active) | set(base.research.completed) | set(forecast_sim.research.active) | set(forecast_sim.research.completed), key=str)
            for research_id in research_ids:
                definition = base.research.definitions.get(research_id) or forecast_sim.research.definitions.get(research_id)
                if definition is None:
                    continue
                def state_name(service):
                    if research_id in service.completed:
                        return "complete"
                    state = service.active.get(research_id)
                    if state is None:
                        return "not_started"
                    return service.current_stage_spec(research_id).stage_type.value
                if query.scope_kind != "player":
                    context = None
                    active_state = base.research.active.get(research_id) or forecast_sim.research.active.get(research_id)
                    if active_state is not None:
                        context = active_state.execution_context
                    if context is None or context.operational_node_id not in selected:
                        continue
                current_state = state_name(base.research)
                future_state = state_name(forecast_sim.research)
                if current_state != future_state:
                    impacts.append(DetailedForecastImpactRow(
                        "research", str(research_id), definition.display_name, current_state, future_state
                    ))

        requirement_rows = projected._requirement_rows()
        logistics_rows = tuple(
            DetailedForecastLogisticsRow(
                requirement_id=row.id,
                resource_id=row.resource_id,
                destination_id=row.destination_id,
                source_id=row.selected_source_id,
                handoff_count=int(row.selected_handoff_count or 0),
                service_ids=tuple(row.selected_service_ids),
                projected_arrival_day=row.projected_arrival_day,
                projected_latency_days=row.selected_latency_days,
                pipeline_t=row.pipeline_t,
                remaining_t=row.remaining_t,
                supply_state=row.supply_state,
            )
            for row in requirement_rows
            if row.destination_id in {str(node_id) for node_id in selected}
            and ((row.selected_handoff_count or 0) > 0 or len(row.selected_service_ids) > 1 or row.remaining_t > 1e-9)
        )

        return DetailedForecastView(
            scope_kind=query.scope_kind,
            scope_id=query.scope_id,
            node_ids=tuple(str(node_id) for node_id in nodes),
            base_day=base.day,
            projected_day=forecast_sim.day,
            horizon=horizon,
            period_days=days,
            inventory=tuple(inventory_rows),
            downstream_impacts=tuple(impacts),
            logistics_impacts=logistics_rows,
        )
