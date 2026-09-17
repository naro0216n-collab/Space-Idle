from __future__ import annotations

from .application_views import LogisticsPolicyRow, SupplyRequirementRow, TargetStockRow


class SupplyPlanningProjectorMixin:
    def _requirement_rows(
        self, *, execution_allocation=None, resolutions=None
    ) -> tuple[SupplyRequirementRow, ...]:
        sim = self._simulation
        decision = self._tick_decision_projection()
        if resolutions is None:
            resolutions = decision.plan.requirement_resolutions
            if execution_allocation is None:
                execution_allocation = decision.allocations.transport
        resolutions = tuple(resolutions)
        shipping_by_id = {
            requirement.id: requirement
            for requirement in decision.plan.external_requirements
        }
        cache = getattr(self, "_query_projection_cache", None)
        cached = None if cache is None else cache.get("requirement_rows")
        if (
            cached is not None
            and cached[0] is execution_allocation
            and cached[1] is resolutions
        ):
            return cached[2]

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
            pipeline_t = sim.logistics.cargo_flow_pipeline_t(requirement.id)
            shipping = shipping_by_id.get(requirement.id)
            remaining_t = max(
                0.0,
                (0.0 if shipping is None else shipping.amount_t) - pipeline_t,
            )
            options = sim.logistics.supply_planning_options(
                requirement,
                sim.day,
                execution_allocation=execution_allocation,
            )
            rate = requirement.recurring_rate_t_per_day
            runway = None if rate is None else runway_by_key.get(
                (requirement.destination_id, requirement.resource_id), 0.0
            )
            earliest = options.earliest_confirmed_arrival_day
            gap = None
            if runway is not None and earliest is not None:
                gap = max(0.0, float(earliest - sim.day) - runway)

            if gap is not None and gap > 1e-9:
                supply_state = "coverage_gap"
            elif remaining_t > 1e-9 and not options.candidate_source_ids:
                supply_state = "no_source"
            elif remaining_t > 1e-9 and not options.operational_source_ids:
                supply_state = "transport_blocked"
            elif remaining_t > 1e-9 and not options.stocked_source_ids:
                supply_state = "source_shortage"
            elif remaining_t > 1e-9 and runway is not None and runway <= 1.0 + 1e-9:
                supply_state = "low_runway"
            elif remaining_t > 1e-9:
                supply_state = "uncovered"
            elif pipeline_t > 1e-9:
                supply_state = "pipeline_covered"
            else:
                supply_state = "local_covered"

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

            assigned_policy_id = sim.logistics.assigned_policy_id_for(
                requirement.owner_kind, requirement.owner_id
            )
            policy = sim.logistics.logistics_policy_for(requirement)
            rows.append(
                SupplyRequirementRow(
                    id=str(requirement.id),
                    owner_kind=requirement.owner_kind,
                    owner_id=str(requirement.owner_id),
                    destination_id=str(requirement.destination_id),
                    resource_id=str(requirement.resource_id),
                    requested_t=requirement.amount_t,
                    local_supply_t=resolution.local_supply_t,
                    external_required_t=resolution.external_required_t,
                    pipeline_t=pipeline_t,
                    remaining_t=remaining_t,
                    priority=requirement.priority,
                    assigned_policy_id=None if assigned_policy_id is None else str(assigned_policy_id),
                    resolved_policy_id=None if policy is None else str(policy.id),
                    source_mode=None if policy is None else policy.source_mode.value,
                    allowed_source_ids=None if policy is None or policy.allowed_source_ids is None else tuple(str(value) for value in policy.allowed_source_ids),
                    preferred_source_id=None if policy is None or policy.preferred_source_id is None else str(policy.preferred_source_id),
                    path_mode=None if policy is None else policy.path_mode.value,
                    path_preference="balanced" if policy is None else policy.path_preference.value,
                    explicit_path=None if policy is None or policy.explicit_path is None else tuple(str(value) for value in policy.explicit_path),
                    source_candidate_ids=tuple(str(value) for value in options.candidate_source_ids),
                    operational_source_ids=tuple(str(value) for value in options.operational_source_ids),
                    stocked_source_ids=tuple(str(value) for value in options.stocked_source_ids),
                    path_candidates=tuple(
                        (str(source_id), tuple(str(plan_id) for plan_id in plan_ids))
                        for source_id, plan_ids in options.path_candidates
                    ),
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
        result = tuple(rows)
        if cache is not None:
            cache["requirement_rows"] = (execution_allocation, resolutions, result)
        return result

    def _logistics_policy_rows(self) -> tuple[LogisticsPolicyRow, ...]:
        sim = self._simulation
        owners_by_policy: dict[object, list[tuple[str, str]]] = {}
        for assignment in sim.logistics.logistics_policy_assignments():
            owners_by_policy.setdefault(assignment.policy_id, []).append(
                (assignment.owner_kind, str(assignment.owner_id))
            )
        return tuple(
            LogisticsPolicyRow(
                id=str(row.id),
                source_mode=row.source_mode.value,
                allowed_source_ids=None if row.allowed_source_ids is None else tuple(str(value) for value in row.allowed_source_ids),
                preferred_source_id=None if row.preferred_source_id is None else str(row.preferred_source_id),
                path_mode=row.path_mode.value,
                path_preference=row.path_preference.value,
                explicit_path=None if row.explicit_path is None else tuple(str(value) for value in row.explicit_path),
                allowed_handoff_ids=None if row.allowed_handoff_ids is None else tuple(str(value) for value in row.allowed_handoff_ids),
                allowed_service_ids=row.allowed_service_ids,
                is_global=sim.logistics.global_logistics_policy_id() == row.id,
                assigned_owners=tuple(sorted(owners_by_policy.get(row.id, ()))),
            )
            for row in sim.logistics.logistics_policy_rows()
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
