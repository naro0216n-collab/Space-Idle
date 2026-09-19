from __future__ import annotations

from collections import defaultdict

from .application_views import (
    BottlenecksView, CurrentDependencyMetricRow, CurrentServiceDependencyMetricRow, DependencyAnalyticsView,
    DecisionContextTarget, ForecastDependencyMetricRow, ForecastServiceDependencyMetricRow, FlowReportView, IssueRow, ResourceFlowRow,
)
from .application_commands import GetDependencyAnalytics
from .shared import CelestialBodyId, SpatialNodeId
from .execution_requirements import ServiceCapacityRequirement
from .service_capacity import ServiceCapacityScope
from .construction.models import ProjectStatus
from .supply import SupplyRequirement, resolve_local_supply


class ApplicationReportProjectorMixin:
    def _dependency_scope_nodes(
        self, query: GetDependencyAnalytics
    ) -> tuple[SpatialNodeId, ...]:
        graph = self._simulation.graph
        kind = query.scope_kind
        if kind == "player":
            if query.scope_id is not None or query.node_ids:
                raise ValueError("player analytics scope takes no scope id or node ids")
            return tuple(sorted(graph.operational_node_ids(), key=str))
        if kind == "body":
            if query.scope_id is None or query.node_ids:
                raise ValueError("body analytics scope requires exactly one scope id")
            return graph.nodes_for_body(CelestialBodyId(query.scope_id))
        if kind == "operational_nodes":
            if query.scope_id is not None or not query.node_ids:
                raise ValueError("operational_nodes analytics scope requires node ids")
            nodes = tuple(SpatialNodeId(value) for value in query.node_ids)
            if len(set(nodes)) != len(nodes):
                raise ValueError("analytics scope contains duplicate operational nodes")
            for node_id in nodes:
                if not graph.has_operational_node(node_id):
                    raise KeyError(node_id)
            return tuple(sorted(nodes, key=str))
        raise ValueError(f"unsupported analytics scope kind: {kind}")

    def _dependency_analytics_view(
        self, query: GetDependencyAnalytics
    ) -> DependencyAnalyticsView:
        basis = query.time_basis.upper()
        if basis not in {"CURRENT", "FORECAST"}:
            raise ValueError(f"unsupported dependency analytics time basis: {query.time_basis}")
        nodes = self._dependency_scope_nodes(query)
        if basis == "CURRENT":
            rows, group_rows, critical = self._current_dependency_rows(nodes)
            service_rows, critical_services = self._current_service_dependency_rows(nodes)
            return DependencyAnalyticsView(
                scope_kind=query.scope_kind,
                scope_id=query.scope_id,
                node_ids=tuple(str(value) for value in nodes),
                day=self._simulation.day,
                time_basis="CURRENT",
                current_resources=tuple(rows),
                current_resource_groups=tuple(group_rows),
                current_services=tuple(service_rows),
                critical_dependency_resource_ids=tuple(critical),
                critical_dependency_service_types=tuple(critical_services),
            )
        rows, group_rows, critical = self._forecast_dependency_rows(nodes)
        service_rows, critical_services = self._forecast_service_dependency_rows(nodes)
        return DependencyAnalyticsView(
            scope_kind=query.scope_kind,
            scope_id=query.scope_id,
            node_ids=tuple(str(value) for value in nodes),
            day=self._simulation.day,
            time_basis="FORECAST",
            forecast_resources=tuple(rows),
            forecast_resource_groups=tuple(group_rows),
            forecast_services=tuple(service_rows),
            critical_dependency_resource_ids=tuple(critical),
            critical_dependency_service_types=tuple(critical_services),
        )

    def _current_service_dependency_rows(
        self, nodes: tuple[SpatialNodeId, ...]
    ) -> tuple[list[CurrentServiceDependencyMetricRow], list[str]]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        plan = decision.allocations.services
        execution = decision.allocations.execution
        selected = set(nodes)
        all_nodes = set(sim.graph.operational_node_ids())
        provider_scopes = sim.service_capacity_scopes()

        requested_by_node: dict[tuple[str, SpatialNodeId], float] = defaultdict(float)
        allocated_by_service: dict[str, float] = defaultdict(float)
        requested_by_service: dict[str, float] = defaultdict(float)
        pure_organization_requested: dict[str, float] = defaultdict(float)
        pure_organization_allocated: dict[str, float] = defaultdict(float)

        for request in plan.requests:
            if request.operational_node_id not in selected:
                continue
            requested_by_node[(request.service_type, request.operational_node_id)] += request.requested_rate
            requested_by_service[request.service_type] += request.requested_rate
            allocated_by_service[request.service_type] += plan.allocated(request.id)

        # Organization-only requirements have no node-scoped projection request.
        # Attribute them only when their bundle has an explicit selected node, or
        # when the query covers the whole organization. Conservation duplicates
        # added beside a node-scoped requirement are deliberately ignored here.
        for bundle in execution.bundles:
            requirements = tuple(
                requirement for requirement in bundle.requirements
                if isinstance(requirement, ServiceCapacityRequirement)
            )
            local_types = {
                requirement.service_type for requirement in requirements
                if requirement.scope is ServiceCapacityScope.OPERATIONAL_NODE
            }
            allocation = execution.allocation(bundle.id)
            for requirement in requirements:
                if (
                    requirement.scope is not ServiceCapacityScope.ORGANIZATION
                    or requirement.service_type in local_types
                ):
                    continue
                attributable = (
                    bundle.operational_node_id in selected
                    if bundle.operational_node_id is not None
                    else selected == all_nodes
                )
                if not attributable:
                    continue
                requested = bundle.requested_execution * requirement.amount_per_execution
                allocated = allocation.allocated_execution * requirement.amount_per_execution
                pure_organization_requested[requirement.service_type] += requested
                pure_organization_allocated[requirement.service_type] += allocated
                requested_by_service[requirement.service_type] += requested
                allocated_by_service[requirement.service_type] += allocated

        service_types = set(requested_by_service)
        service_types.update(
            service_type
            for node_id, service_type in plan.supply_nominal
            if node_id in selected
        )
        rows: list[CurrentServiceDependencyMetricRow] = []
        critical: list[str] = []
        for service_type in sorted(service_types):
            scope = provider_scopes.get(service_type, ServiceCapacityScope.OPERATIONAL_NODE)
            local_nominal = sum(
                max(0.0, plan.supply_nominal.get((node_id, service_type), 0.0))
                for node_id in selected
            )
            local_enabled = sum(
                max(0.0, plan.supply_enabled.get((node_id, service_type), 0.0))
                for node_id in selected
            )
            outside_enabled = sum(
                max(0.0, enabled)
                for (node_id, row_type), enabled in plan.supply_enabled.items()
                if row_type == service_type and node_id not in selected
            )

            node_shortfall = 0.0
            locally_covered = 0.0
            for node_id in selected:
                demand = requested_by_node[(service_type, node_id)]
                enabled = max(0.0, plan.supply_enabled.get((node_id, service_type), 0.0))
                node_shortfall += max(0.0, demand - enabled)
                locally_covered += min(demand, enabled)

            organization_demand = pure_organization_requested[service_type]
            organization_total_enabled = local_enabled + outside_enabled
            organization_shortfall = max(0.0, organization_demand - organization_total_enabled)
            external_dependency = min(
                outside_enabled, max(0.0, organization_demand - local_enabled)
            )
            locally_covered += min(organization_demand, local_enabled)
            requested = requested_by_service[service_type]
            coverage = None if requested <= 1e-12 else min(1.0, locally_covered / requested)
            unmet = node_shortfall + organization_shortfall

            limiting: list[str] = []
            for node_id in selected:
                limiting.extend(plan.supply_limiting_factors.get((node_id, service_type), ()))
            if unmet > 1e-9:
                limiting.append("service_capacity_shortfall")
            if external_dependency > 1e-9:
                limiting.append("outside_scope_service_dependency")
            limiting = list(dict.fromkeys(limiting))
            if unmet > 1e-9 or external_dependency > 1e-9:
                critical.append(service_type)
            if requested <= 1e-12 and unmet <= 1e-12 and external_dependency <= 1e-12:
                continue
            rows.append(CurrentServiceDependencyMetricRow(
                service_type=service_type,
                scope=scope.value,
                local_nominal_rate=local_nominal,
                local_enabled_rate=local_enabled,
                outside_scope_enabled_rate=outside_enabled,
                requested_rate=requested,
                allocated_rate=allocated_by_service[service_type],
                unmet_rate=unmet,
                external_dependency_rate=external_dependency,
                local_coverage_ratio=coverage,
                limiting_factors=tuple(limiting),
            ))
        return rows, critical

    def _forecast_service_dependency_rows(
        self, nodes: tuple[SpatialNodeId, ...]
    ) -> tuple[list[ForecastServiceDependencyMetricRow], list[str]]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        plan = decision.allocations.services
        selected = set(nodes)
        provider_scopes = sim.service_capacity_scopes()
        planned: dict[str, float] = defaultdict(float)
        earliest: dict[str, int | None] = {}
        paused: set[str] = set()

        for project in sim.projects.projects.values():
            if project.operational_node_id not in selected:
                continue
            if project.status in {ProjectStatus.COMPLETE, ProjectStatus.CANCELLED}:
                continue
            for service_type, amount in sim.projects.project_service_requirement_forecast(project):
                if amount <= 1e-12:
                    continue
                planned[service_type] += amount
                day = sim.day if project.status in {ProjectStatus.READY, ProjectStatus.BUILDING} else None
                prior = earliest.get(service_type)
                if day is not None and (prior is None or day < prior):
                    earliest[service_type] = day
                elif service_type not in earliest:
                    earliest[service_type] = None
                if project.paused:
                    paused.add(service_type)

        rows: list[ForecastServiceDependencyMetricRow] = []
        critical: list[str] = []
        for service_type in sorted(planned):
            scope = provider_scopes.get(service_type, ServiceCapacityScope.OPERATIONAL_NODE)
            local_enabled = sum(
                max(0.0, plan.supply_enabled.get((node_id, service_type), 0.0))
                for node_id in selected
            )
            outside_enabled = sum(
                max(0.0, enabled)
                for (node_id, row_type), enabled in plan.supply_enabled.items()
                if row_type == service_type and node_id not in selected
            )
            limiting: list[str] = []
            if scope is ServiceCapacityScope.OPERATIONAL_NODE and local_enabled <= 1e-12:
                limiting.append("no_local_service_capacity")
            elif (
                scope is ServiceCapacityScope.ORGANIZATION
                and local_enabled + outside_enabled <= 1e-12
            ):
                limiting.append("no_organization_service_capacity")
            if service_type in paused:
                limiting.append("paused_plan")
            if any(value.startswith("no_") for value in limiting):
                critical.append(service_type)
            rows.append(ForecastServiceDependencyMetricRow(
                service_type=service_type,
                scope=scope.value,
                planned_requirement=planned[service_type],
                local_enabled_rate=local_enabled,
                outside_scope_enabled_rate=outside_enabled,
                earliest_requirement_day=earliest.get(service_type),
                limiting_factors=tuple(limiting),
            ))
        return rows, critical

    def _current_dependency_rows(
        self, nodes: tuple[SpatialNodeId, ...]
    ) -> tuple[list[CurrentDependencyMetricRow], list[CurrentDependencyMetricRow], list[str]]:
        sim = self._simulation
        scope = set(nodes)
        decision = self._tick_decision_projection()
        powers = decision.allocations.power_by_location
        execution_allocations = decision.allocations.execution
        logistics_execution = sim.logistics.capacity_logistics_execution_projection(
            decision.allocations.transport
        )

        production: dict[object, float] = defaultdict(float)
        consumption: dict[object, float] = defaultdict(float)
        current_demand: dict[object, float] = defaultdict(float)
        external_inflow: dict[object, float] = defaultdict(float)
        external_outflow: dict[object, float] = defaultdict(float)
        imports_pipeline: dict[object, float] = defaultdict(float)
        exports_pipeline: dict[object, float] = defaultdict(float)
        unmet: dict[object, float] = defaultdict(float)
        dependency_sources: dict[object, set[SpatialNodeId]] = defaultdict(set)

        for node_id in nodes:
            power = powers[node_id]
            for snap in sim.industry.snapshots(
                node_id, sim.facilities, sim.inventory, sim.day, execution_allocations,
            ):
                for resource_id, amount in snap.output_rates_per_day.items():
                    production[resource_id] += amount
                for resource_id, amount in snap.input_rates_per_day.items():
                    consumption[resource_id] += amount
            if sim.extraction is not None:
                for snap in sim.extraction.snapshots(
                    node_id, sim.facilities, sim.inventory, power, sim.day, execution_allocations,
                ):
                    production[snap.output_resource_id] += snap.output_t_per_day

        if sim.maintenance is not None:
            for node_id, resource_id, amount in sim.maintenance.resource_consumption_projection(
                execution_allocations
            ):
                if node_id in scope:
                    consumption[resource_id] += amount
        for node_id, resource_id, amount in logistics_execution.operational_resource_use:
            if node_id in scope:
                consumption[resource_id] += amount

        # CURRENT demand is limited to requirements that are due in the snapshot.
        # Target Stock is a future planning intent and therefore belongs to FORECAST.
        current_requirement_ids: set[object] = set()
        for requirement in decision.intents.supplys:
            if requirement.destination_id not in scope or requirement.owner_kind == "target_stock":
                continue
            if (
                requirement.forecast_requirement_day is not None
                and requirement.forecast_requirement_day > sim.day
            ):
                continue
            current_requirement_ids.add(requirement.id)
            current_demand[requirement.resource_id] += (
                requirement.recurring_rate_t_per_day
                if requirement.recurring_rate_t_per_day is not None
                else requirement.amount_t
            )
        for allocation in decision.allocations.resources.rows:
            if (
                allocation.owner_kind == "transport_operation"
                and allocation.operational_node_id in scope
            ):
                current_demand[allocation.resource_id] += allocation.requested_amount

        projected_dispatch_by_requirement: dict[object, float] = defaultdict(float)
        for dispatch in logistics_execution.dispatches:
            projected_dispatch_by_requirement[dispatch.requirement_id] += dispatch.amount_t
            source_inside = dispatch.source_id in scope
            destination_inside = dispatch.destination_id in scope
            if source_inside == destination_inside:
                continue
            if destination_inside:
                external_inflow[dispatch.resource_id] += dispatch.amount_t
                dependency_sources[dispatch.resource_id].add(dispatch.source_id)
            else:
                external_outflow[dispatch.resource_id] += dispatch.amount_t

        for commitment in sim.market.buy_commitments.values():
            order = sim.market.orders.get(commitment.order_id)
            interface = None if order is None else sim.market.interfaces.get(order.market_interface_id)
            if interface is not None and interface.operational_node_id in scope:
                imports_pipeline[commitment.resource_id] += commitment.remaining_quantity_t

        for order in sim.market.orders.values():
            if order.direction.value != "sell":
                continue
            interface = sim.market.interfaces.get(order.market_interface_id)
            if interface is None or interface.operational_node_id not in scope:
                continue
            try:
                amount = decision.allocations.execution.allocated(sim.market.sell_execution_id(order.id))
            except KeyError:
                amount = 0.0
            if amount > 1e-12:
                external_outflow[order.resource_id] += amount

        for flow in sim.logistics.cargo_flow_snapshots():
            source_inside = flow.source_id in scope
            destination_inside = flow.destination_id in scope
            if source_inside == destination_inside:
                continue
            if destination_inside:
                imports_pipeline[flow.resource_id] += flow.amount_t
                dependency_sources[flow.resource_id].add(flow.source_id)
            else:
                exports_pipeline[flow.resource_id] += flow.amount_t
        for waiting in sim.logistics.arrival_waiting_snapshots():
            source_inside = waiting.arrival_leg.source_id in scope
            destination_inside = waiting.node_id in scope
            if source_inside == destination_inside:
                continue
            if destination_inside:
                imports_pipeline[waiting.resource_id] += waiting.amount_t
                dependency_sources[waiting.resource_id].add(waiting.arrival_leg.source_id)
            else:
                exports_pipeline[waiting.resource_id] += waiting.amount_t

        for requirement in decision.plan.external_requirements:
            if requirement.id not in current_requirement_ids or requirement.destination_id not in scope:
                continue
            remaining = max(
                0.0,
                sim.logistics.requirement_remaining_t(requirement)
                - projected_dispatch_by_requirement[requirement.id],
            )
            if remaining <= 1e-12:
                continue
            unmet[requirement.resource_id] += remaining
            constraint = sim.logistics.routing_constraint_for(requirement)
            constrained_source = None if constraint is None else constraint.source_node_id
            if constrained_source is not None and constrained_source not in scope:
                dependency_sources[requirement.resource_id].add(constrained_source)

        resource_ids = (
            set(production) | set(consumption) | set(current_demand) |
            set(external_inflow) | set(external_outflow) |
            set(imports_pipeline) | set(exports_pipeline) | set(unmet)
        )
        rows: list[CurrentDependencyMetricRow] = []
        for resource_id in sorted(resource_ids, key=str):
            definition = self._catalog.resources.get(resource_id)
            produced = production[resource_id]
            demand_rate = current_demand[resource_id]
            dependency_rate = max(0.0, demand_rate - produced)
            coverage = None if demand_rate <= 1e-12 else min(1.0, produced / demand_rate)
            limiting: list[str] = []
            if unmet[resource_id] > 1e-9:
                limiting.append("unmet_demand")
            if dependency_rate > 1e-9:
                limiting.append("external_dependency")
            rows.append(CurrentDependencyMetricRow(
                str(resource_id), str(resource_id) if definition is None else definition.display_name,
                "t" if definition is None else definition.unit, (str(resource_id),),
                produced, consumption[resource_id], demand_rate, dependency_rate, coverage,
                external_inflow[resource_id], external_outflow[resource_id],
                imports_pipeline[resource_id], exports_pipeline[resource_id], unmet[resource_id],
                tuple(str(value) for value in sorted(dependency_sources[resource_id], key=str)),
                tuple(limiting),
            ))

        by_id = {row.id: row for row in rows}
        group_rows: list[CurrentDependencyMetricRow] = []
        for group_id, group in sorted(self._catalog.resource_groups.items(), key=lambda item: str(item[0])):
            members = tuple(by_id[str(resource_id)] for resource_id in group.resource_ids if str(resource_id) in by_id)
            if not members:
                continue
            units = {member.unit for member in members}
            if len(units) != 1:
                raise ValueError(f"resource group {group_id} mixes incompatible units")
            demand = sum(row.demand_per_day for row in members)
            dependency = sum(row.external_dependency_per_day for row in members)
            produced = sum(row.production_per_day for row in members)
            group_rows.append(CurrentDependencyMetricRow(
                str(group_id), group.display_name, next(iter(units)), tuple(row.id for row in members),
                produced, sum(row.consumption_per_day for row in members), demand, dependency,
                None if demand <= 1e-12 else min(1.0, sum(max(0.0, row.demand_per_day - row.external_dependency_per_day) for row in members) / demand),
                sum(row.imports_per_day for row in members), sum(row.exports_per_day for row in members),
                sum(row.imports_pipeline_t for row in members), sum(row.exports_pipeline_t for row in members),
                sum(row.unmet_demand_t for row in members),
                tuple(sorted({source for row in members for source in row.dependency_source_node_ids})),
                tuple(dict.fromkeys(factor for row in members for factor in row.limiting_factors)),
            ))
        critical = [row.id for row in rows if row.external_dependency_per_day > 1e-9 or row.unmet_demand_t > 1e-9]
        return rows, group_rows, critical

    def _forecast_dependency_rows(
        self, nodes: tuple[SpatialNodeId, ...]
    ) -> tuple[list[ForecastDependencyMetricRow], list[ForecastDependencyMetricRow], list[str]]:
        sim = self._simulation
        scope = set(nodes)
        decision = self._tick_decision_projection()

        requirements: dict[object, SupplyRequirement] = {
            row.id: row for row in decision.intents.supplys if row.destination_id in scope
        }

        # Construction exposes planned requirements through its public forecast
        # contract, including requirements not yet due for current procurement.
        for requirement in sim.projects.forecast_supplys():
            if requirement.destination_id in scope:
                requirements[requirement.id] = requirement

        ordered = tuple(sorted(requirements.values(), key=lambda row: (-row.priority, str(row.id))))
        resolutions = resolve_local_supply(ordered, sim.inventory)
        external_by_id = {row.requirement.id: row.external_required_t for row in resolutions}

        planned: dict[object, float] = defaultdict(float)
        recurring: dict[object, float] = defaultdict(float)
        external: dict[object, float] = defaultdict(float)
        target_stock: dict[object, float] = defaultdict(float)
        earliest_day: dict[object, int | None] = {}
        dependency_sources: dict[object, set[SpatialNodeId]] = defaultdict(set)

        for requirement in ordered:
            resource_id = requirement.resource_id
            planned[resource_id] += requirement.amount_t
            external[resource_id] += external_by_id.get(requirement.id, requirement.amount_t)
            if requirement.recurring_rate_t_per_day is not None:
                recurring[resource_id] += requirement.recurring_rate_t_per_day
            if requirement.owner_kind == "target_stock":
                target_stock[resource_id] += requirement.amount_t
            if requirement.forecast_requirement_day is not None:
                previous = earliest_day.get(resource_id)
                earliest_day[resource_id] = requirement.forecast_requirement_day if previous is None else min(previous, requirement.forecast_requirement_day)
            constraint = sim.logistics.routing_constraint_for(requirement)
            constrained_source = None if constraint is None else constraint.source_node_id
            if constrained_source is not None and constrained_source not in scope:
                dependency_sources[resource_id].add(constrained_source)

        # Use snapshot production only to identify recurring future dependence;
        # unbuilt future facilities are never predicted.
        production: dict[object, float] = defaultdict(float)
        execution_allocations = decision.allocations.execution
        for node_id in nodes:
            power = decision.allocations.power_by_location[node_id]
            for snap in sim.industry.snapshots(node_id, sim.facilities, sim.inventory, sim.day, execution_allocations):
                for resource_id, amount in snap.output_rates_per_day.items():
                    production[resource_id] += amount
            if sim.extraction is not None:
                for snap in sim.extraction.snapshots(node_id, sim.facilities, sim.inventory, power, sim.day, execution_allocations):
                    production[snap.output_resource_id] += snap.output_t_per_day

        resource_ids = set(planned) | set(recurring) | set(external) | set(target_stock)
        rows: list[ForecastDependencyMetricRow] = []
        for resource_id in sorted(resource_ids, key=str):
            definition = self._catalog.resources.get(resource_id)
            recurring_dependency = max(0.0, recurring[resource_id] - production[resource_id])
            limiting: list[str] = []
            if external[resource_id] > 1e-9:
                limiting.append("external_requirement")
            if recurring_dependency > 1e-9:
                limiting.append("external_recurring_dependency")
            rows.append(ForecastDependencyMetricRow(
                str(resource_id), str(resource_id) if definition is None else definition.display_name,
                "t" if definition is None else definition.unit, (str(resource_id),),
                planned[resource_id], recurring[resource_id], external[resource_id], recurring_dependency,
                target_stock[resource_id], earliest_day.get(resource_id),
                tuple(str(value) for value in sorted(dependency_sources[resource_id], key=str)), tuple(limiting),
            ))

        by_id = {row.id: row for row in rows}
        group_rows: list[ForecastDependencyMetricRow] = []
        for group_id, group in sorted(self._catalog.resource_groups.items(), key=lambda item: str(item[0])):
            members = tuple(by_id[str(resource_id)] for resource_id in group.resource_ids if str(resource_id) in by_id)
            if not members:
                continue
            units = {member.unit for member in members}
            if len(units) != 1:
                raise ValueError(f"resource group {group_id} mixes incompatible units")
            days = [row.earliest_requirement_day for row in members if row.earliest_requirement_day is not None]
            group_rows.append(ForecastDependencyMetricRow(
                str(group_id), group.display_name, next(iter(units)), tuple(row.id for row in members),
                sum(row.planned_requirement_t for row in members),
                sum(row.recurring_consumption_per_day for row in members),
                sum(row.external_requirement_t for row in members),
                sum(row.external_recurring_dependency_per_day for row in members),
                sum(row.target_stock_t for row in members), min(days) if days else None,
                tuple(sorted({source for row in members for source in row.dependency_source_node_ids})),
                tuple(dict.fromkeys(factor for row in members for factor in row.limiting_factors)),
            ))
        critical = [row.id for row in rows if row.external_requirement_t > 1e-9 or row.external_recurring_dependency_per_day > 1e-9]
        return rows, group_rows, critical

    @staticmethod
    def _issue_navigation(
        *,
        category: str,
        source: str,
        operational_node_id: str | None,
        entity_id: str | None,
        definition_id: str | None,
        resource_id: str | None,
    ) -> DecisionContextTarget | None:
        if source in {"facility", "industry", "extraction"}:
            return DecisionContextTarget(
                "location", operational_node_id, "facility", entity_id, resource_id
            )
        if source == "project":
            return DecisionContextTarget(
                "location", operational_node_id, "project", entity_id, resource_id
            )
        if source == "storage":
            return DecisionContextTarget(
                "location", operational_node_id, "inventory", None, resource_id
            )
        if source == "power" or category == "capacity":
            return DecisionContextTarget(
                "location", operational_node_id, "location", operational_node_id, resource_id
            )
        if source == "movement_plan":
            return DecisionContextTarget(
                "logistics", operational_node_id, "movement_plan", entity_id, resource_id
            )
        if source in {"transport_allocation", "transport_capacity"}:
            return DecisionContextTarget(
                "logistics", operational_node_id, "transport_allocation", entity_id, resource_id
            )
        if source == "vehicle_production":
            return DecisionContextTarget(
                "logistics", operational_node_id, "vehicle_production", entity_id, resource_id
            )
        if source == "supply":
            return DecisionContextTarget(
                "logistics", operational_node_id, "supply_requirement", entity_id, resource_id
            )
        if category == "research":
            return DecisionContextTarget(
                "research", operational_node_id, "research", definition_id, resource_id
            )
        if source == "scientific_exploration":
            return DecisionContextTarget(
                "exploration", operational_node_id, "scientific_exploration", definition_id, resource_id
            )
        if source == "survey":
            return DecisionContextTarget(
                "exploration", operational_node_id, "survey_campaign", entity_id, resource_id
            )
        return None

    @classmethod
    def _issue(
        cls,
        code: str,
        message: str | None,
        *,
        category: str,
        source: str,
        operational_node_id: str | None = None,
        entity_id: str | None = None,
        definition_id: str | None = None,
        resource_id: str | None = None,
        impact: str = "blocked",
        attention_required: bool = True,
    ) -> IssueRow:
        navigation = cls._issue_navigation(
            category=category,
            source=source,
            operational_node_id=operational_node_id,
            entity_id=entity_id,
            definition_id=definition_id,
            resource_id=resource_id,
        )
        return IssueRow(
            code=str(code),
            message=str(message if message else code),
            category=category,
            source=source,
            operational_node_id=operational_node_id,
            entity_id=entity_id,
            definition_id=definition_id,
            resource_id=resource_id,
            impact=impact,
            attention_required=attention_required,
            navigation=navigation,
        )

    def _operational_node_issues(self, location_id: SpatialNodeId) -> tuple[IssueRow, ...]:
        sim = self._simulation
        loc = str(location_id)
        issues: list[IssueRow] = []
        decision = self._tick_decision_projection()
        power = decision.allocations.power_by_location[location_id]

        if power.demand_mw > power.allocated_mw + 1e-9:
            issues.append(self._issue(
                "power_shortage",
                f"需要 {power.demand_mw:g} MW に対して {power.allocated_mw:g} MW を配分",
                category="capacity", source="power", operational_node_id=loc, impact="limited",
            ))

        for facility in sorted(sim.facilities.all_at(location_id), key=lambda row: str(row.id)):
            definition = sim.facilities.definitions[facility.definition_id]
            for code, detail in sim.facilities.activation_failures(facility, sim.day):
                issues.append(self._issue(
                    code, detail, category="facility", source="facility",
                    operational_node_id=loc, entity_id=str(facility.id), definition_id=str(definition.id),
                ))

        execution_allocations = decision.allocations.execution
        snapshots = {
            snap.facility_id: snap
            for snap in sim.industry.snapshots(
                location_id, sim.facilities, sim.inventory, sim.day,
                execution_allocations,
            )
        }
        for facility in sorted(sim.facilities.all_at(location_id), key=lambda row: str(row.id)):
            compatible = sim.industry.compatible_processes(facility.definition_id)
            if not compatible:
                continue
            snap = snapshots.get(facility.id)
            if snap is None:
                if not sim.facilities.activation_failures(facility, sim.day):
                    issues.append(self._issue(
                        "process:unselected", "生産工程が未選択",
                        category="industry", source="industry", operational_node_id=loc,
                        entity_id=str(facility.id), definition_id=str(facility.definition_id),
                    ))
                continue
            if snap.scale < 1.0 - 1e-9:
                for factor in snap.limiting_factors:
                    resource_id = factor.removeprefix("input:") if factor.startswith("input:") else None
                    issues.append(self._issue(
                        factor, factor, category="industry", source="industry",
                        operational_node_id=loc, entity_id=str(facility.id),
                        definition_id=str(facility.definition_id), resource_id=resource_id,
                        impact="limited",
                    ))

        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(
                location_id, sim.facilities, sim.inventory, power, sim.day,
                execution_allocations,
            ):
                if snap.scale >= 1.0 - 1e-9:
                    continue
                for factor in snap.limiting_factors:
                    issues.append(self._issue(
                        factor, factor, category="extraction", source="extraction",
                        operational_node_id=loc, entity_id=str(snap.facility_id),
                        definition_id=str(snap.facility_def_id),
                        resource_id=str(snap.output_resource_id), impact="limited",
                    ))

        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if project.operational_node_id != location_id:
                continue
            definition_id = str(sim.projects.target_facility_definition_id(project))
            for code, detail in self._project_blockers(project, power):
                issues.append(self._issue(
                    code, detail, category="construction", source="project",
                    operational_node_id=loc, entity_id=str(project.id), definition_id=definition_id,
                ))

        for row in self._storage_rows(location_id):
            if row.unusable_occupied_t > 1e-9:
                issues.append(self._issue(
                    "storage_usable_capacity_shortage",
                    f"{row.storage_pool_key} のUsable Capacity超過占有 {row.unusable_occupied_t:g} t",
                    category="storage", source="storage", operational_node_id=loc, impact="limited",
                ))

        return tuple(issues)

    def _global_logistics_issues(self, location_filter: str | None) -> tuple[IssueRow, ...]:
        sim = self._simulation
        issues: list[IssueRow] = []
        decision = self._tick_decision_projection()

        # Route issues are intrinsic endpoint/site constraints. Vehicle/Fleet
        # feasibility is projected through Transport Allocation rather than
        # individual Vehicle availability.
        for movement_plan in sim.transport.movement_plan_options():
            if location_filter is not None and location_filter not in {
                str(movement_plan.origin_id), str(movement_plan.destination_id)
            }:
                continue
            for blocker in sim.transport.movement_plan_failures(movement_plan.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="movement_plan",
                    operational_node_id=location_filter, entity_id=str(movement_plan.id),
                    attention_required=False,
                ))

        for allocation in self._transport_allocation_rows():
            if location_filter is not None and location_filter not in {
                allocation.anchor_node_id, allocation.destination_id
            }:
                continue
            for blocker in allocation.blockers:
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="transport_allocation",
                    operational_node_id=allocation.anchor_node_id, entity_id=allocation.id,
                    definition_id=allocation.vehicle_definition_id,
                ))
            for limiting in allocation.limiting_factors:
                issues.append(self._issue(
                    limiting, limiting, category="logistics", source="transport_capacity",
                    operational_node_id=allocation.anchor_node_id, entity_id=allocation.id,
                    definition_id=allocation.vehicle_definition_id, impact="limited",
                ))

        for state in sim.transport.vehicle_production_snapshots():
            state_location = str(state.operational_node_id)
            if location_filter is not None and state_location != location_filter:
                continue
            for blocker in sim.transport.vehicle_production_blockers(
                state.id,
                day=sim.day,
                power=decision.allocations.power_by_location[state.operational_node_id],
            ):
                code, _, detail = blocker.partition(":")
                resource_id = None
                if code == "resource" and detail:
                    resource_id = detail.partition(":")[0]
                issues.append(self._issue(
                    code, detail or blocker,
                    category="vehicle_production", source="vehicle_production",
                    operational_node_id=state_location, entity_id=str(state.id),
                    definition_id=str(state.vehicle_definition_id), resource_id=resource_id,
                ))

        for requirement in self._requirement_rows(
            execution_allocation=decision.allocations.transport,
            resolutions=decision.plan.requirement_resolutions,
        ):
            if location_filter is not None and location_filter != requirement.destination_id:
                continue
            if requirement.owner_kind == "project" or requirement.remaining_t <= 1e-9:
                continue
            if requirement.candidate_source_count > 0:
                continue
            issues.append(self._issue(
                "supply_source_unavailable",
                f"供給元未確定 {requirement.remaining_t:g} t",
                category="logistics", source="supply",
                operational_node_id=requirement.destination_id, entity_id=requirement.id,
                resource_id=requirement.resource_id, impact="limited",
            ))
        return tuple(issues)

    def _progression_issues(self, location_filter: str | None) -> tuple[IssueRow, ...]:
        issues: list[IssueRow] = []
        research = self._research_view()
        for row in research.items:
            groups: list[tuple[str, tuple[tuple[str, str], ...], str | None]] = []
            if row.status in {"available", "locked"}:
                groups.append(("research_start", row.start_blockers, None))
            elif row.status in {"prototype", "demonstration"}:
                groups.append((
                    f"research_{row.status}",
                    row.current_blockers,
                    None if row.execution_context is None else row.execution_context.operational_node_id,
                ))

            for source, blockers, selected_location in groups:
                if location_filter is not None and selected_location != location_filter:
                    continue
                for code, detail in blockers:
                    issues.append(self._issue(
                        code, detail, category="research", source=source,
                        operational_node_id=selected_location, definition_id=row.id,
                        attention_required=source != "research_start",
                    ))

        explorations = self._scientific_explorations_view()
        for row in explorations.items:
            if location_filter is not None and location_filter not in {
                row.origin_id, row.destination_id
            }:
                continue
            for blocker in row.blockers:
                code, _, detail = blocker.partition(":")
                resource_id = None
                if code == "resource" and detail:
                    resource_id = detail.partition(":")[0]
                issue_location = row.origin_id
                if code == "destination":
                    issue_location = row.destination_id
                elif location_filter is not None:
                    issue_location = location_filter
                issues.append(self._issue(
                    code, detail or blocker,
                    category="exploration", source="scientific_exploration",
                    operational_node_id=issue_location, definition_id=row.id,
                    resource_id=resource_id,
                ))

        surveys = self._surveys_view(None)
        for row in surveys.campaigns:
            issue_location = row.projected_provider_operational_node_id or row.provider_constraint_operational_node_id
            if location_filter is not None and issue_location != location_filter:
                continue
            for blocker in row.blockers:
                issues.append(self._issue(
                    blocker, blocker, category="survey", source="survey",
                    operational_node_id=issue_location, entity_id=row.id,
                ))

        if location_filter is None:
            contracts = self._contracts_view()
            for row in contracts.items:
                for blocker in row.blockers:
                    code, _, detail = blocker.partition(":")
                    issues.append(self._issue(
                        code, detail or blocker, category="contract", source="contract",
                        entity_id=row.id, definition_id=row.template_id, attention_required=False,
                    ))
        return tuple(issues)

    def _bottlenecks_view(self, location_id: SpatialNodeId | None) -> BottlenecksView:
        sim = self._simulation
        location_filter = None if location_id is None else str(location_id)
        issues: list[IssueRow] = []
        if location_id is None:
            for node in sim.graph.operational_nodes():
                issues.extend(self._operational_node_issues(node.id))
        else:
            issues.extend(self._operational_node_issues(location_id))
        issues.extend(self._global_logistics_issues(location_filter))
        issues.extend(self._progression_issues(location_filter))

        unique: list[IssueRow] = []
        seen: set[tuple] = set()
        for issue in issues:
            key = (
                issue.code, issue.category, issue.source, issue.operational_node_id,
                issue.entity_id, issue.definition_id, issue.resource_id,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return BottlenecksView(sim.day, location_filter, tuple(unique))

    def _attention_view(self) -> BottlenecksView:
        bottlenecks = self._bottlenecks_view(None)
        return BottlenecksView(
            bottlenecks.day,
            None,
            tuple(issue for issue in bottlenecks.items if issue.attention_required),
        )

    def _flow_report_view(self, location_id: SpatialNodeId) -> FlowReportView:
        sim = self._simulation
        decision = self._tick_decision_projection()
        power = decision.allocations.power_by_location[location_id]
        production: dict[object, float] = defaultdict(float)
        consumption: dict[object, float] = defaultdict(float)
        outbound_waiting: dict[object, float] = defaultdict(float)
        outbound_transit: dict[object, float] = defaultdict(float)
        inbound_transit: dict[object, float] = defaultdict(float)
        arrival_waiting: dict[object, float] = defaultdict(float)

        execution_allocations = decision.allocations.execution
        for snap in sim.industry.snapshots(
            location_id, sim.facilities, sim.inventory, sim.day,
            execution_allocations,
        ):
            for resource_id, amount in snap.output_rates_per_day.items():
                production[resource_id] += amount
            for resource_id, amount in snap.input_rates_per_day.items():
                consumption[resource_id] += amount

        # Facility maintenance is an ordinary recurring physical resource flow.
        # Report the currently fulfilled consumption rate, while the full
        # requirement remains visible through Facility maintenance demand/query.
        if sim.maintenance is not None:
            for node_id, resource_id, amount in sim.maintenance.resource_consumption_projection(
                execution_allocations
            ):
                if node_id == location_id:
                    consumption[resource_id] += amount

        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(
                location_id, sim.facilities, sim.inventory, power, sim.day,
                execution_allocations,
            ):
                production[snap.output_resource_id] += snap.output_t_per_day

        for flow in sim.logistics.cargo_flow_snapshots():
            if flow.source_id == location_id:
                outbound_transit[flow.resource_id] += flow.amount_t
            if flow.destination_id == location_id:
                inbound_transit[flow.resource_id] += flow.amount_t
        for waiting in sim.logistics.arrival_waiting_snapshots():
            if waiting.node_id == location_id:
                arrival_waiting[waiting.resource_id] += waiting.amount_t

        resource_ids = (
            set(production) | set(consumption) | set(outbound_waiting) |
            set(outbound_transit) | set(inbound_transit) | set(arrival_waiting)
        )
        resource_ids.update(
            resource_id for (loc, resource_id) in sim.inventory.stock if loc == location_id
        )
        rows: list[ResourceFlowRow] = []
        for resource_id in sorted(resource_ids, key=str):
            definition = self._catalog.resources.get(resource_id)
            produced = production[resource_id]
            consumed = consumption[resource_id]
            rows.append(ResourceFlowRow(
                str(resource_id), self._resource_name(resource_id),
                "t" if definition is None else definition.unit,
                produced, consumed, produced - consumed,
                sim.inventory.amount(location_id, resource_id),
                sim.inventory.reserved_total(location_id, resource_id),
                sim.inventory.available(location_id, resource_id),
                sim.inventory.admission_state(location_id, resource_id).admission_capacity_t,
                outbound_waiting[resource_id], outbound_transit[resource_id],
                inbound_transit[resource_id], arrival_waiting[resource_id],
            ))

        utilization = (
            1.0 if power.demand_mw <= 1e-12
            else min(1.0, power.allocated_mw / power.demand_mw)
        )
        return FlowReportView(
            str(location_id), sim.day, power.generation_mw, power.demand_mw,
            power.allocated_mw, utilization,
            sim.projects.construction_capacity_at(location_id, power, sim.day),
            tuple(rows), self._operational_node_issues(location_id),
        )
