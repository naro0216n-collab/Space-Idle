from __future__ import annotations

from .application_views import LogisticsLaneRow, LogisticsLanesView, ResourceDemandRow


class LogisticsLaneProjectorMixin:
    def _demand_rows(
        self, demands=None, snapshot=None, execution_allocation=None, resolutions=None
    ) -> tuple[ResourceDemandRow, ...]:
        sim = self._simulation
        if resolutions is None:
            decision = sim.tick_decision_projection()
            resolutions = decision.plan.demand_resolutions
            if demands is None:
                demands = decision.plan.external_demands
        resolutions = tuple(resolutions)
        external_demands = tuple(
            demand for resolution in resolutions
            if (demand := resolution.external_demand()) is not None
        ) if demands is None else tuple(demands)
        lane_snapshot = (
            sim.logistics.lane_snapshot(
                external_demands,
                sim.day,
                execution_allocation=execution_allocation,
            )
            if snapshot is None else snapshot
        )
        pipeline = dict(lane_snapshot.demand_pipeline_t)

        # Runway is an observable site-level stock horizon, not a protected
        # allocation. Durable reservations/commitments belong to their owners
        # and are therefore excluded from stock available to recurring demands.
        recurring_rate_by_key: dict[tuple[object, object], float] = {}
        for resolution in resolutions:
            demand = resolution.demand
            rate = demand.recurring_rate_t_per_day
            if rate is None:
                continue
            key = (demand.destination_id, demand.resource_id)
            recurring_rate_by_key[key] = recurring_rate_by_key.get(key, 0.0) + rate
        runway_by_key: dict[tuple[object, object], float] = {}
        for key, rate in recurring_rate_by_key.items():
            available = sim.inventory.available(key[0], key[1])
            runway_by_key[key] = available / rate if rate > 1e-12 else 0.0

        rows: list[ResourceDemandRow] = []
        for resolution in resolutions:
            demand = resolution.demand
            procurement_pipeline_t = sim.logistics.procurement_pipeline_t(
                demand.id, delivery_node_id=demand.destination_id
            )
            pipeline_t = pipeline.get(demand.id, 0.0) + procurement_pipeline_t
            remaining_t = max(0.0, resolution.external_required_t - pipeline_t)
            options = sim.logistics.demand_supply_options(
                demand,
                sim.day,
                execution_allocation=execution_allocation,
            )
            rate = demand.recurring_rate_t_per_day
            runway = None if rate is None else runway_by_key.get(
                (demand.destination_id, demand.resource_id), 0.0
            )
            procurement_arrivals = [
                row.ready_day
                for row in sim.logistics.procurement_delivery_snapshots()
                if row.demand_id == demand.id
                and row.delivery_node_id == demand.destination_id
            ]
            arrival_days = [
                value
                for value in (
                    options.earliest_confirmed_arrival_day,
                    min(procurement_arrivals) if procurement_arrivals else None,
                )
                if value is not None
            ]
            earliest_arrival_day = min(arrival_days) if arrival_days else None
            gap = None
            if runway is not None and earliest_arrival_day is not None:
                gap = max(
                    0.0,
                    float(earliest_arrival_day - sim.day) - runway,
                )

            if resolution.external_required_t <= 1e-9:
                supply_state = "local_covered"
            elif gap is not None and gap > 1e-9:
                supply_state = "coverage_gap"
            elif remaining_t <= 1e-9:
                supply_state = "pipeline_covered"
            elif not options.eligible_lane_ids:
                supply_state = "no_lane"
            elif not options.operational_lane_ids:
                supply_state = "lane_blocked"
            elif not options.stocked_source_ids:
                supply_state = "source_shortage"
            elif runway is not None and runway <= 1.0 + 1e-9:
                supply_state = "low_runway"
            else:
                supply_state = "uncovered"

            blockers = list(options.blockers)
            if resolution.external_required_t > 1e-9 and not options.eligible_lane_ids:
                blockers.append("no_configured_lane")
            if resolution.external_required_t > 1e-9 and options.eligible_lane_ids and not options.operational_lane_ids:
                blockers.append("no_operational_lane")
            if resolution.external_required_t > 1e-9 and options.operational_lane_ids and not options.stocked_source_ids:
                blockers.append("source_inventory_shortage")

            rows.append(ResourceDemandRow(
                str(demand.id),
                demand.owner_kind,
                str(demand.owner_id),
                None if demand.source_id is None else str(demand.source_id),
                str(demand.destination_id),
                str(demand.resource_id),
                demand.amount_t,
                resolution.local_supply_t,
                resolution.external_required_t,
                pipeline_t,
                remaining_t,
                demand.priority,
                rate,
                runway,
                earliest_arrival_day,
                gap,
                len(options.eligible_lane_ids),
                len(options.operational_lane_ids),
                len(options.stocked_source_ids),
                supply_state,
                tuple(dict.fromkeys(blockers)),
            ))
        return tuple(rows)

    def _lane_rows(
        self, demands=None, snapshot=None, decision=None
    ) -> tuple[LogisticsLaneRow, ...]:
        sim = self._simulation
        decision = sim.tick_decision_projection() if decision is None else decision
        demand_rows = (
            decision.plan.external_demands if demands is None else tuple(demands)
        )
        lane_snapshot = (
            sim.logistics.lane_snapshot(
                demand_rows,
                sim.day,
                execution_allocation=decision.allocations.transport,
            )
            if snapshot is None else snapshot
        )
        metrics = {row.lane_id: row for row in lane_snapshot.lanes}
        funds = decision.allocations.funds
        funds_blockers: dict[str, list[str]] = {}
        factor_codes = {
            "spending_cap": "external_spending_cap",
            "period_budget": "external_period_budget",
            "funds": "external_funds",
            "minimum_reserve": "external_minimum_reserve",
        }
        for row in funds.rows:
            if row.owner_kind != "lane" or row.unmet_musd <= 1e-9:
                continue
            bucket = funds_blockers.setdefault(str(row.owner_id), [])
            for factor in row.limiting_factors:
                bucket.append(factor_codes.get(factor, f"external_spending:{factor}"))
        return tuple(
            LogisticsLaneRow(
                str(lane.id),
                str(lane.source_id),
                str(lane.destination_id),
                lane.requested_capacity_t_per_day,
                metrics[lane.id].effective_capacity_t_per_day,
                metrics[lane.id].used_t,
                metrics[lane.id].queued_t,
                lane.priority,
                None if lane.path is None else tuple(str(route_id) for route_id in lane.path),
                lane.path_policy.value,
                lane.paused,
                tuple(dict.fromkeys(metrics[lane.id].blockers + tuple(funds_blockers.get(str(lane.id), ())))),
            )
            for lane in sim.logistics.lane_definitions()
        )

    def _logistics_lanes_view(self) -> LogisticsLanesView:
        sim = self._simulation
        decision = sim.tick_decision_projection()
        demands = decision.plan.external_demands
        snapshot = sim.logistics.lane_snapshot(
            demands,
            sim.day,
            execution_allocation=decision.allocations.transport,
        )
        return LogisticsLanesView(
            self._lane_rows(demands, snapshot, decision),
            self._demand_rows(
                demands,
                snapshot,
                decision.allocations.transport,
                decision.plan.demand_resolutions,
            ),
        )
