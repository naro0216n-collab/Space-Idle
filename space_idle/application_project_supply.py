from __future__ import annotations

from .application_views import SupplyPolicyRow, SupplyRequirementRow, TargetStockRow


class SupplyPlanningProjectorMixin:
    def _requirement_rows(
        self, *, execution_allocation=None, resolutions=None
    ) -> tuple[SupplyRequirementRow, ...]:
        sim = self._simulation
        if resolutions is None:
            decision = sim.tick_decision_projection()
            resolutions = decision.plan.requirement_resolutions
            if execution_allocation is None:
                execution_allocation = decision.allocations.transport
        resolutions = tuple(resolutions)

        recurring_rate_by_key: dict[tuple[object, object], float] = {}
        for resolution in resolutions:
            requirement = resolution.requirement
            if requirement.recurring_rate_t_per_day is None:
                continue
            key = (requirement.destination_id, requirement.resource_id)
            recurring_rate_by_key[key] = (
                recurring_rate_by_key.get(key, 0.0) + requirement.recurring_rate_t_per_day
            )
        runway_by_key = {
            key: sim.inventory.available(key[0], key[1]) / rate
            for key, rate in recurring_rate_by_key.items()
            if rate > 1e-12
        }

        rows: list[SupplyRequirementRow] = []
        for resolution in resolutions:
            requirement = resolution.requirement
            cargo_pipeline = sim.logistics.cargo_flow_pipeline_t(requirement.id)
            procurement_pipeline = sim.logistics.external_supply_pipeline_t(
                requirement.id, supply_node_id=requirement.destination_id
            )
            pipeline_t = cargo_pipeline + procurement_pipeline
            remaining_t = max(0.0, resolution.external_required_t - pipeline_t)
            options = sim.logistics.supply_planning_options(
                requirement,
                sim.day,
                execution_allocation=execution_allocation,
            )
            rate = requirement.recurring_rate_t_per_day
            runway = None if rate is None else runway_by_key.get(
                (requirement.destination_id, requirement.resource_id), 0.0
            )
            external_supply_days = [
                row.available_day
                for row in sim.logistics.external_supply_snapshots()
                if row.requirement_id == requirement.id
                and row.supply_node_id == requirement.destination_id
            ]
            arrivals = [
                value
                for value in (
                    options.earliest_confirmed_arrival_day,
                    min(external_supply_days) if external_supply_days else None,
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
                    id=str(requirement.id),
                    owner_kind=requirement.owner_kind,
                    owner_id=str(requirement.owner_id),
                    source_id=None if requirement.source_id is None else str(requirement.source_id),
                    destination_id=str(requirement.destination_id),
                    resource_id=str(requirement.resource_id),
                    requested_t=requirement.amount_t,
                    local_supply_t=resolution.local_supply_t,
                    external_required_t=resolution.external_required_t,
                    pipeline_t=pipeline_t,
                    remaining_t=remaining_t,
                    priority=requirement.priority,
                    forecast_requirement_day=requirement.forecast_requirement_day,
                    recurring_rate_t_per_day=rate,
                    local_runway_days=runway,
                    earliest_confirmed_arrival_day=earliest,
                    projected_gap_days=gap,
                    candidate_source_count=len(options.candidate_source_ids),
                    operational_source_count=len(options.operational_source_ids),
                    stocked_source_count=len(options.stocked_source_ids),
                    supply_state=supply_state,
                    blockers=tuple(dict.fromkeys(blockers)),
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
