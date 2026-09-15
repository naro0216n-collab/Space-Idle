from __future__ import annotations

from collections import defaultdict

from .application_views import (
    BottlenecksView, DependencyAnalyticsView, DependencyMetricRow,
    FlowReportView, IssueRow, ResourceFlowRow,
)
from .application_commands import GetDependencyAnalytics
from .shared import CelestialBodyId, SpatialNodeId


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
        sim = self._simulation
        nodes = self._dependency_scope_nodes(query)
        scope = set(nodes)
        decision = sim.tick_decision_projection()
        powers = decision.allocations.power_by_location
        resource_allocations = decision.allocations.resources
        service_allocations = decision.allocations.services
        execution_allocations = decision.allocations.execution
        logistics_execution = sim.logistics.capacity_logistics_execution_projection(
            decision.allocations.transport
        )

        production: dict[object, float] = defaultdict(float)
        consumption: dict[object, float] = defaultdict(float)
        recurring_demand: dict[object, float] = defaultdict(float)
        external_inflow: dict[object, float] = defaultdict(float)
        external_outflow: dict[object, float] = defaultdict(float)
        imports_pipeline: dict[object, float] = defaultdict(float)
        exports_pipeline: dict[object, float] = defaultdict(float)
        unmet: dict[object, float] = defaultdict(float)
        dependency_sources: dict[object, set[SpatialNodeId]] = defaultdict(set)

        # Production and actual recurring consumption are projected from the same
        # allocation result the next normal tick would execute. Same-tick output is
        # intentionally not fed back into that allocation.
        for node_id in nodes:
            power = powers[node_id]
            for snap in sim.industry.snapshots(
                node_id, sim.facilities, sim.inventory, sim.day,
                execution_allocations,
            ):
                for resource_id, amount in snap.output_rates_per_day.items():
                    production[resource_id] += amount
                for resource_id, amount in snap.input_rates_per_day.items():
                    consumption[resource_id] += amount
            if sim.extraction is not None:
                for snap in sim.extraction.snapshots(
                    node_id, sim.facilities, sim.inventory, power, sim.day,
                    execution_allocations,
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

        # Recurring ResourceDemand is the structural daily requirement before
        # current stock/pipeline masks a dependency. Transport operation demand is
        # created during Logistics planning, so its current-tick claims are the
        # authoritative recurring requirement for that service usage.
        for demand in decision.intents.resource_demands:
            if demand.destination_id not in scope or demand.recurring_rate_t_per_day is None:
                continue
            recurring_demand[demand.resource_id] += demand.recurring_rate_t_per_day
        for claim in decision.allocations.logistics.claims:
            if claim.owner_kind != "transport_operation" or claim.operational_node_id not in scope:
                continue
            recurring_demand[claim.resource_id] += claim.requested_amount

        # Current authorized dispatch is a one-day flow. Existing CargoFlow state is
        # a stock in the pipeline and therefore remains a separate quantity.
        projected_dispatch_by_demand: dict[object, float] = defaultdict(float)
        for dispatch in logistics_execution.dispatches:
            projected_dispatch_by_demand[dispatch.demand_id] += dispatch.amount_t
            source_inside = dispatch.source_id in scope
            destination_inside = dispatch.destination_id in scope
            if source_inside == destination_inside:
                continue
            if destination_inside:
                external_inflow[dispatch.resource_id] += dispatch.amount_t
                dependency_sources[dispatch.resource_id].add(dispatch.source_id)
            else:
                external_outflow[dispatch.resource_id] += dispatch.amount_t

        # External Procurement crosses the player-system boundary without a source
        # Operational Node. Authorized orders are this tick's external inflow;
        # persisted delivery batches are pipeline stock until Storage admission.
        projected_procurement_by_destination: dict[
            tuple[object, SpatialNodeId], float
        ] = defaultdict(float)
        for order in decision.allocations.procurement.orders:
            projected_procurement_by_destination[
                (order.demand.id, order.delivery_node_id)
            ] += order.amount_t
            if order.delivery_node_id in scope:
                external_inflow[order.demand.resource_id] += order.amount_t

        for delivery in sim.logistics.procurement_delivery_snapshots():
            if delivery.delivery_node_id in scope:
                imports_pipeline[delivery.resource_id] += delivery.amount_t

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

        # Unmet Demand is the residual off-site need after local stock, existing
        # pipeline, and the current tick's actually executable dispatch are credited.
        # Internal sourcing remains internal to the selected scope and is never
        # labeled as an external source.
        for demand in decision.plan.external_demands:
            if demand.destination_id not in scope:
                continue
            remaining = max(
                0.0,
                sim.logistics.demand_remaining_t(demand)
                - sim.logistics.procurement_pipeline_t(
                    demand.id, delivery_node_id=demand.destination_id
                )
                - projected_dispatch_by_demand[demand.id]
                - projected_procurement_by_destination[
                    (demand.id, demand.destination_id)
                ],
            )
            if remaining <= 1e-12:
                continue
            unmet[demand.resource_id] += remaining
            if demand.source_id is not None and demand.source_id not in scope:
                dependency_sources[demand.resource_id].add(demand.source_id)
            for lane in sim.logistics.lane_definitions():
                if (
                    lane.source_id not in scope
                    and sim.logistics.lane_accepts_demand(lane, demand)
                ):
                    dependency_sources[demand.resource_id].add(lane.source_id)

        resource_ids = (
            set(production) | set(consumption) | set(recurring_demand) |
            set(external_inflow) | set(external_outflow) |
            set(imports_pipeline) | set(exports_pipeline) | set(unmet)
        )
        rows: list[DependencyMetricRow] = []
        for resource_id in sorted(resource_ids, key=str):
            definition = self._catalog.resources.get(resource_id)
            produced = production[resource_id]
            consumed = consumption[resource_id]
            demand_rate = recurring_demand[resource_id]
            dependency_rate = max(0.0, demand_rate - produced)
            covered_rate = max(0.0, demand_rate - dependency_rate)
            coverage = (
                None if demand_rate <= 1e-12
                else min(1.0, covered_rate / demand_rate)
            )
            limiting: list[str] = []
            if unmet[resource_id] > 1e-9:
                limiting.append("unmet_demand")
            if dependency_rate > 1e-9:
                limiting.append("external_dependency")
            rows.append(DependencyMetricRow(
                str(resource_id),
                str(resource_id) if definition is None else definition.display_name,
                "t" if definition is None else definition.unit,
                (str(resource_id),),
                produced,
                consumed,
                demand_rate,
                dependency_rate,
                coverage,
                external_inflow[resource_id],
                external_outflow[resource_id],
                imports_pipeline[resource_id],
                exports_pipeline[resource_id],
                unmet[resource_id],
                tuple(str(value) for value in sorted(dependency_sources[resource_id], key=str)),
                tuple(limiting),
            ))

        by_id = {row.id: row for row in rows}
        group_rows: list[DependencyMetricRow] = []
        for group_id, group in sorted(
            self._catalog.resource_groups.items(), key=lambda item: str(item[0])
        ):
            members = tuple(
                by_id[str(resource_id)]
                for resource_id in group.resource_ids
                if str(resource_id) in by_id
            )
            if not members:
                continue
            units = {member.unit for member in members}
            if len(units) != 1:
                raise ValueError(f"resource group {group_id} mixes incompatible units")
            produced = sum(row.local_production_per_day for row in members)
            consumed = sum(row.local_consumption_per_day for row in members)
            demand_rate = sum(row.local_demand_per_day for row in members)
            dependency_rate = sum(row.external_dependency_per_day for row in members)
            covered_rate = max(0.0, demand_rate - dependency_rate)
            group_rows.append(DependencyMetricRow(
                str(group_id), group.display_name, next(iter(units)),
                tuple(row.id for row in members),
                produced, consumed, demand_rate, dependency_rate,
                None if demand_rate <= 1e-12 else min(1.0, covered_rate / demand_rate),
                sum(row.external_inflow_per_day for row in members),
                sum(row.external_outflow_per_day for row in members),
                sum(row.imports_pipeline for row in members),
                sum(row.exports_pipeline for row in members),
                sum(row.unmet_demand for row in members),
                tuple(sorted({
                    source
                    for row in members
                    for source in row.dependency_source_node_ids
                })),
                tuple(dict.fromkeys(
                    factor for row in members for factor in row.limiting_factors
                )),
            ))

        return DependencyAnalyticsView(
            query.scope_kind,
            query.scope_id,
            tuple(str(value) for value in nodes),
            sim.day,
            tuple(rows),
            tuple(group_rows),
            tuple(
                row.id for row in rows
                if row.external_dependency_per_day > 1e-9 or row.unmet_demand > 1e-9
            ),
        )

    @staticmethod
    def _issue(
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
    ) -> IssueRow:
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
        )

    def _operational_node_issues(self, location_id: SpatialNodeId) -> tuple[IssueRow, ...]:
        sim = self._simulation
        loc = str(location_id)
        issues: list[IssueRow] = []
        decision = sim.tick_decision_projection()
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

        resource_allocations = decision.allocations.resources
        service_allocations = decision.allocations.services
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
                    issues.append(self._issue(
                        factor, factor, category="industry", source="industry",
                        operational_node_id=loc, entity_id=str(facility.id),
                        definition_id=str(facility.definition_id), impact="limited",
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
                    f"{row.storage_class} のUsable Capacity超過占有 {row.unusable_occupied_t:g} t",
                    category="storage", source="storage", operational_node_id=loc, impact="limited",
                ))

        return tuple(issues)

    def _global_logistics_issues(self, location_filter: str | None) -> tuple[IssueRow, ...]:
        sim = self._simulation
        issues: list[IssueRow] = []
        decision = sim.tick_decision_projection()

        # Route issues are intrinsic endpoint/site constraints. Vehicle/Fleet
        # feasibility is projected through Transport Allocation rather than
        # individual Vehicle availability.
        for route in sim.transport.route_definitions():
            if location_filter is not None and location_filter not in {
                str(route.origin_id), str(route.destination_id)
            }:
                continue
            for blocker in sim.transport.route_failures(route.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="route",
                    operational_node_id=location_filter, entity_id=str(route.id),
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

        demands = decision.plan.external_demands
        lane_snapshot = sim.logistics.lane_snapshot(
            demands,
            sim.day,
            execution_allocation=decision.allocations.transport,
        )
        for lane in self._lane_rows(demands, lane_snapshot, decision):
            if location_filter is not None and location_filter not in {
                lane.source_id, lane.destination_id
            }:
                continue
            for blocker in lane.blockers:
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="logistics_lane",
                    operational_node_id=location_filter, entity_id=lane.id,
                ))

        for demand in self._demand_rows(
            demands, lane_snapshot, decision.allocations.transport
        ):
            if location_filter is not None and location_filter != demand.destination_id:
                continue
            if demand.owner_kind == "project" or demand.remaining_t <= 1e-9:
                continue
            if demand.eligible_lane_count > 0:
                continue
            issues.append(self._issue(
                "demand_unassigned",
                f"未割当需要 {demand.remaining_t:g} t",
                category="logistics", source="resource_demand",
                operational_node_id=demand.destination_id, entity_id=demand.id,
                resource_id=demand.resource_id, impact="limited",
            ))
        return tuple(issues)

    def _progression_issues(self, location_filter: str | None) -> tuple[IssueRow, ...]:
        issues: list[IssueRow] = []
        research = self._research_view()
        for row in research.items:
            groups: list[tuple[str, tuple[tuple[str, str], ...], str | None]] = []
            if row.status in {"available", "locked"}:
                groups.append(("research_start", row.start_blockers, None))
            elif row.status == "prototype":
                groups.append(("research_prototype", row.prototype_blockers, row.prototype_operational_node_id))
            elif row.status == "demonstration":
                groups.append(("research_demonstration", row.demonstration_blockers, row.demonstration_operational_node_id))

            for source, blockers, selected_location in groups:
                if location_filter is not None and selected_location != location_filter:
                    continue
                for code, detail in blockers:
                    issues.append(self._issue(
                        code, detail, category="research", source=source,
                        operational_node_id=selected_location, definition_id=row.id,
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
        for row in surveys.items:
            if location_filter is not None and row.location_id != location_filter:
                continue
            for blocker in row.blockers:
                issues.append(self._issue(
                    blocker, blocker, category="survey", source="survey",
                    operational_node_id=row.location_id, resource_id=row.resource_id,
                ))

        if location_filter is None:
            contracts = self._contracts_view()
            for row in contracts.items:
                for blocker in row.blockers:
                    code, _, detail = blocker.partition(":")
                    issues.append(self._issue(
                        code, detail or blocker, category="contract", source="contract",
                        entity_id=row.id, definition_id=row.template_id,
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

    def _flow_report_view(self, location_id: SpatialNodeId) -> FlowReportView:
        sim = self._simulation
        decision = sim.tick_decision_projection()
        power = decision.allocations.power_by_location[location_id]
        production: dict[object, float] = defaultdict(float)
        consumption: dict[object, float] = defaultdict(float)
        outbound_waiting: dict[object, float] = defaultdict(float)
        outbound_transit: dict[object, float] = defaultdict(float)
        inbound_transit: dict[object, float] = defaultdict(float)
        arrival_waiting: dict[object, float] = defaultdict(float)

        resource_allocations = decision.allocations.resources
        service_allocations = decision.allocations.services
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
            status = getattr(flow.status, "value", flow.status)
            if status == "in_transit":
                if flow.source_id == location_id:
                    outbound_transit[flow.resource_id] += flow.amount_t
                if flow.destination_id == location_id:
                    inbound_transit[flow.resource_id] += flow.amount_t
            elif status == "arrival_waiting" and flow.destination_id == location_id:
                arrival_waiting[flow.resource_id] += flow.amount_t

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
                sim.inventory.free_capacity(location_id, resource_id),
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
