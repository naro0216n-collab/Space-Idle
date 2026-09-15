from __future__ import annotations

from .application_views import SupplyPolicyRow, SupplyRequirementRow, TargetStockRow


class SupplyPlanningProjectorMixin:
    def _requirement_rows(
        self, *, execution_allocation=None, resolutions=None
    ) -> tuple[SupplyRequirementRow, ...]:
        sim = self._simulation
        if resolutions is None:
            decision = sim.tick_decision_projection()
            resolutions = decision.plan.demand_resolutions
            if execution_allocation is None:
                execution_allocation = decision.allocations.transport
        resolutions = tuple(resolutions)

        recurring_rate_by_key: dict[tuple[object, object], float] = {}
        for resolution in resolutions:
            demand = resolution.demand
            if demand.recurring_rate_t_per_day is None:
                continue
            key = (demand.destination_id, demand.resource_id)
            recurring_rate_by_key[key] = (
                recurring_rate_by_key.get(key, 0.0) + demand.recurring_rate_t_per_day
            )
        runway_by_key = {
            key: sim.inventory.available(key[0], key[1]) / rate
            for key, rate in recurring_rate_by_key.items()
            if rate > 1e-12
        }

        rows: list[SupplyRequirementRow] = []
        for resolution in resolutions:
            demand = resolution.demand
            cargo_pipeline = sim.logistics.cargo_flow_pipeline_t(demand.id)
            procurement_pipeline = sim.logistics.procurement_pipeline_t(
                demand.id, delivery_node_id=demand.destination_id
            )
            pipeline_t = cargo_pipeline + procurement_pipeline
            remaining_t = max(0.0, resolution.external_required_t - pipeline_t)
            options = sim.logistics.supply_planning_options(
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
            arrivals = [
                value
                for value in (
                    options.earliest_confirmed_arrival_day,
                    min(procurement_arrivals) if procurement_arrivals else None,
                )
                if value is not None
            ]
            earliest = min(arrivals) if arrivals else None
            gap = None
            if runway is not None and earliest is not None:
                gap = max(0.0, float(earliest - sim.day) - runway)

            if resolution.external_required_t <= 1e-9:
                supply_state = "local_covered"
            elif gap is not None and gap > 1e-9:
                supply_state = "coverage_gap"
            elif remaining_t <= 1e-9:
                supply_state = "pipeline_covered"
            elif not options.candidate_source_ids:
                supply_state = "no_source"
            elif not options.operational_source_ids:
                supply_state = "transport_blocked"
            elif not options.stocked_source_ids:
                supply_state = "source_shortage"
            elif runway is not None and runway <= 1.0 + 1e-9:
                supply_state = "low_runway"
            else:
                supply_state = "uncovered"

            blockers = list(options.blockers) if remaining_t > 1e-9 else []
            if remaining_t > 1e-9 and not options.candidate_source_ids:
                blockers.append("no_supply_source")
            if (
                remaining_t > 1e-9
                and options.candidate_source_ids
                and not options.operational_source_ids
            ):
                blockers.append("no_transport_capacity")
            if (
                remaining_t > 1e-9
                and options.operational_source_ids
                and not options.stocked_source_ids
            ):
                blockers.append("source_inventory_shortage")

            rows.append(
                SupplyRequirementRow(
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
                    earliest,
                    gap,
                    len(options.candidate_source_ids),
                    len(options.operational_source_ids),
                    len(options.stocked_source_ids),
                    supply_state,
                    tuple(dict.fromkeys(blockers)),
                )
            )
        return tuple(rows)

    def _supply_policy_rows(self) -> tuple[SupplyPolicyRow, ...]:
        return tuple(
            SupplyPolicyRow(
                str(row.id),
                str(row.destination_id),
                str(row.resource_id),
                None if row.preferred_source_id is None else str(row.preferred_source_id),
                row.path_policy.value,
                None if row.explicit_path is None else tuple(str(value) for value in row.explicit_path),
            )
            for row in self._simulation.logistics.supply_policy_rows()
        )

    def _target_stock_rows(self) -> tuple[TargetStockRow, ...]:
        return tuple(
            TargetStockRow(
                str(row.id),
                str(row.destination_id),
                str(row.resource_id),
                row.target_quantity_t,
                row.priority,
            )
            for row in self._simulation.logistics.target_stock_policies()
        )
