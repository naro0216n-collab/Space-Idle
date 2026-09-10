from __future__ import annotations

from collections import defaultdict

from .application_views import BottlenecksView, FlowReportView, IssueRow, ResourceFlowRow
from .shared import SpatialNodeId


class ApplicationReportProjectorMixin:
    @staticmethod
    def _issue(
        code: str,
        message: str | None,
        *,
        category: str,
        source: str,
        location_id: str | None = None,
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
            location_id=location_id,
            entity_id=entity_id,
            definition_id=definition_id,
            resource_id=resource_id,
            impact=impact,
        )

    def _location_operational_issues(self, location_id: SpatialNodeId) -> tuple[IssueRow, ...]:
        sim = self._simulation
        loc = str(location_id)
        issues: list[IssueRow] = []
        power = sim.power.snapshot(location_id, sim.facilities, sim.day)

        if power.demand_mw > power.allocated_mw + 1e-9:
            issues.append(self._issue(
                "power_shortage",
                f"需要 {power.demand_mw:g} MW に対して {power.allocated_mw:g} MW を配分",
                category="capacity", source="power", location_id=loc, impact="limited",
            ))

        for facility in sorted(sim.facilities.all_at(location_id), key=lambda row: str(row.id)):
            definition = sim.facilities.definitions[facility.definition_id]
            for code, detail in sim.facilities.activation_failures(facility, sim.day):
                issues.append(self._issue(
                    code, detail, category="facility", source="facility",
                    location_id=loc, entity_id=str(facility.id), definition_id=str(definition.id),
                ))

        snapshots = {
            snap.facility_id: snap
            for snap in sim.industry.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day)
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
                        category="industry", source="industry", location_id=loc,
                        entity_id=str(facility.id), definition_id=str(facility.definition_id),
                    ))
                continue
            if snap.scale < 1.0 - 1e-9:
                for factor in snap.limiting_factors:
                    issues.append(self._issue(
                        factor, factor, category="industry", source="industry",
                        location_id=loc, entity_id=str(facility.id),
                        definition_id=str(facility.definition_id), impact="limited",
                    ))

        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day):
                if snap.scale >= 1.0 - 1e-9:
                    continue
                for factor in snap.limiting_factors:
                    issues.append(self._issue(
                        factor, factor, category="extraction", source="extraction",
                        location_id=loc, entity_id=str(snap.facility_id),
                        definition_id=str(snap.facility_def_id),
                        resource_id=str(snap.output_resource_id), impact="limited",
                    ))

        for project in sorted(sim.projects.projects.values(), key=lambda row: str(row.id)):
            if project.location_id != location_id:
                continue
            definition_id = str(sim.projects.target_facility_definition_id(project))
            for blocker in sim.projects.blockers(project.id, sim.day, power):
                issues.append(self._issue(
                    blocker.code, blocker.detail, category="construction", source="project",
                    location_id=loc, entity_id=str(project.id), definition_id=definition_id,
                ))

        for row in self._storage_rows(location_id):
            if row.unserviced_occupied_t > 1e-9:
                issues.append(self._issue(
                    "storage_service_shortage",
                    f"{row.storage_class} の未サービス占有 {row.unserviced_occupied_t:g} t",
                    category="storage", source="storage", location_id=loc, impact="limited",
                ))

        return tuple(issues)

    def _global_logistics_issues(self, location_filter: str | None) -> tuple[IssueRow, ...]:
        sim = self._simulation
        issues: list[IssueRow] = []
        for route in sorted(sim.logistics.routes.values(), key=lambda row: str(row.id)):
            if location_filter is not None and location_filter not in {
                str(route.origin_id), str(route.destination_id)
            }:
                continue
            for blocker in sim.logistics.route_operational_failures(route.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="route",
                    location_id=location_filter, entity_id=str(route.id),
                ))
        for state in sorted(sim.logistics.vehicles.values(), key=lambda row: str(row.id)):
            state_location = None if state.location_id is None else str(state.location_id)
            if location_filter is not None and state_location != location_filter and (
                state.transit_destination_id is None
                or str(state.transit_destination_id) != location_filter
            ):
                continue
            for blocker in sim.logistics.vehicle_blockers(state.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="vehicle",
                    location_id=state_location, entity_id=str(state.id),
                    definition_id=str(state.definition_id),
                ))
        for order in sorted(sim.logistics.orders.values(), key=lambda row: str(row.id)):
            if location_filter is not None and location_filter not in {
                str(order.source_id), str(order.destination_id)
            }:
                continue
            for blocker in sim.logistics.order_blockers(order.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="cargo_order",
                    location_id=location_filter, entity_id=str(order.id),
                    resource_id=str(order.resource_id),
                ))
        for lane in sorted(sim.logistics.lanes.values(), key=lambda row: str(row.id)):
            if location_filter is not None and location_filter not in {
                str(lane.source_id), str(lane.destination_id)
            }:
                continue
            for blocker in sim.logistics.lane_blockers(lane.id, sim.day):
                issues.append(self._issue(
                    blocker, blocker, category="logistics", source="logistics_lane",
                    location_id=location_filter, entity_id=str(lane.id),
                ))

        demands = sim.resource_demands()
        for demand in demands:
            if location_filter is not None and location_filter != str(demand.destination_id):
                continue
            remaining = sim.logistics.demand_remaining_t(demand)
            if remaining <= 1e-9:
                continue
            matching = [
                lane for lane in sim.logistics.lanes.values()
                if sim.logistics.lane_accepts_demand(lane, demand)
            ]
            if matching:
                continue
            issues.append(self._issue(
                "demand_unassigned",
                f"未割当需要 {remaining:g} t",
                category="logistics", source="resource_demand",
                location_id=str(demand.destination_id), entity_id=str(demand.id),
                resource_id=str(demand.resource_id), impact="limited",
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
                groups.append(("research_prototype", row.prototype_blockers, row.prototype_location_id))
            elif row.status == "demonstration":
                groups.append(("research_demonstration", row.demonstration_blockers, row.demonstration_location_id))

            for source, blockers, selected_location in groups:
                if location_filter is not None and selected_location != location_filter:
                    continue
                for code, detail in blockers:
                    issues.append(self._issue(
                        code, detail, category="research", source=source,
                        location_id=selected_location, definition_id=row.id,
                    ))

        surveys = self._surveys_view(None)
        for row in surveys.items:
            if location_filter is not None and row.location_id != location_filter:
                continue
            for blocker in row.blockers:
                issues.append(self._issue(
                    blocker, blocker, category="survey", source="survey",
                    location_id=row.location_id, resource_id=row.resource_id,
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
            for node in sorted(sim.graph.nodes.values(), key=lambda row: str(row.id)):
                issues.extend(self._location_operational_issues(node.id))
        else:
            issues.extend(self._location_operational_issues(location_id))
        issues.extend(self._global_logistics_issues(location_filter))
        issues.extend(self._progression_issues(location_filter))

        unique: list[IssueRow] = []
        seen: set[tuple] = set()
        for issue in issues:
            key = (
                issue.code, issue.category, issue.source, issue.location_id,
                issue.entity_id, issue.definition_id, issue.resource_id,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return BottlenecksView(sim.day, location_filter, tuple(unique))

    def _flow_report_view(self, location_id: SpatialNodeId) -> FlowReportView:
        sim = self._simulation
        power = sim.power.snapshot(location_id, sim.facilities, sim.day)
        production: dict[object, float] = defaultdict(float)
        consumption: dict[object, float] = defaultdict(float)
        outbound_waiting: dict[object, float] = defaultdict(float)
        outbound_transit: dict[object, float] = defaultdict(float)
        inbound_transit: dict[object, float] = defaultdict(float)
        arrival_waiting: dict[object, float] = defaultdict(float)

        for snap in sim.industry.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day):
            for resource_id, amount in snap.output_rates_per_day.items():
                production[resource_id] += amount
            for resource_id, amount in snap.input_rates_per_day.items():
                consumption[resource_id] += amount
        if sim.extraction is not None:
            for snap in sim.extraction.snapshots(location_id, sim.facilities, sim.inventory, power, sim.day):
                production[snap.output_resource_id] += snap.output_t_per_day

        for (order_id, leg_index), amount in sim.logistics.waiting.items():
            order = sim.logistics.orders[order_id]
            route = sim.logistics.routes[order.path[leg_index]]
            if route.origin_id == location_id:
                outbound_waiting[order.resource_id] += amount
        for mission in sim.logistics.missions.values():
            order = sim.logistics.orders[mission.order_id]
            route_id = order.path[mission.leg_index]
            route = sim.logistics.routes[route_id]
            status = getattr(mission.status, "value", mission.status)
            if status == "in_transit":
                if route.origin_id == location_id:
                    outbound_transit[order.resource_id] += mission.amount_t
                if route.destination_id == location_id:
                    inbound_transit[order.resource_id] += mission.amount_t
            elif status in {"arrival_waiting", "waypoint_wait"} and route.destination_id == location_id:
                arrival_waiting[order.resource_id] += mission.amount_t

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
            tuple(rows), self._location_operational_issues(location_id),
        )
