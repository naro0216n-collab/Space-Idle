from __future__ import annotations

from .application_views import LogisticsLaneRow, LogisticsLanesView, ResourceDemandRow


class LogisticsLaneProjectorMixin:
    def _demand_rows(self, demands=None, snapshot=None) -> tuple[ResourceDemandRow, ...]:
        sim = self._simulation
        resolutions = sim.resource_demand_resolutions()
        external_demands = tuple(
            demand for resolution in resolutions
            if (demand := resolution.external_demand()) is not None
        ) if demands is None else tuple(demands)
        lane_snapshot = (
            sim.logistics.lane_snapshot(external_demands, sim.day)
            if snapshot is None else snapshot
        )
        pipeline = dict(lane_snapshot.demand_pipeline_t)

        # Runway is an observable site-level stock horizon, not a promise that
        # the Core will protect a demand. It uses physical unreserved stock plus
        # reservations already owned by recurring demands at the same site and
        # divides that pool by the combined recurring consumption rate.
        recurring_rate_by_key: dict[tuple[object, object], float] = {}
        recurring_owned_reservation_by_key: dict[tuple[object, object], float] = {}
        for resolution in resolutions:
            demand = resolution.demand
            rate = demand.recurring_rate_t_per_day
            if rate is None:
                continue
            key = (demand.destination_id, demand.resource_id)
            recurring_rate_by_key[key] = recurring_rate_by_key.get(key, 0.0) + rate
            recurring_owned_reservation_by_key[key] = (
                recurring_owned_reservation_by_key.get(key, 0.0)
                + sim.inventory.reserved_for(
                    demand.id, demand.destination_id, demand.resource_id
                )
            )
        runway_by_key: dict[tuple[object, object], float] = {}
        for key, rate in recurring_rate_by_key.items():
            available = sim.inventory.available(key[0], key[1])
            owned = recurring_owned_reservation_by_key.get(key, 0.0)
            runway_by_key[key] = (available + owned) / rate if rate > 1e-12 else 0.0

        rows: list[ResourceDemandRow] = []
        for resolution in resolutions:
            demand = resolution.demand
            pipeline_t = pipeline.get(demand.id, 0.0)
            remaining_t = max(0.0, resolution.external_required_t - pipeline_t)
            options = sim.logistics.demand_supply_options(demand, sim.day)
            rate = demand.recurring_rate_t_per_day
            runway = None if rate is None else runway_by_key.get(
                (demand.destination_id, demand.resource_id), 0.0
            )
            gap = None
            if runway is not None and options.earliest_confirmed_arrival_day is not None:
                gap = max(
                    0.0,
                    float(options.earliest_confirmed_arrival_day - sim.day) - runway,
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
                options.earliest_confirmed_arrival_day,
                gap,
                len(options.eligible_lane_ids),
                len(options.operational_lane_ids),
                len(options.stocked_source_ids),
                supply_state,
                tuple(dict.fromkeys(blockers)),
            ))
        return tuple(rows)

    def _lane_rows(self, demands=None, snapshot=None) -> tuple[LogisticsLaneRow, ...]:
        sim = self._simulation
        demand_rows = sim.resource_demands() if demands is None else tuple(demands)
        lane_snapshot = sim.logistics.lane_snapshot(demand_rows, sim.day) if snapshot is None else snapshot
        metrics = {row.lane_id: row for row in lane_snapshot.lanes}
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
                metrics[lane.id].blockers,
            )
            for lane in sorted(sim.logistics.lanes.values(), key=lambda row: str(row.id))
        )

    def _logistics_lanes_view(self) -> LogisticsLanesView:
        sim = self._simulation
        demands = sim.resource_demands()
        snapshot = sim.logistics.lane_snapshot(demands, sim.day)
        return LogisticsLanesView(
            self._lane_rows(demands, snapshot),
            self._demand_rows(demands, snapshot),
        )
