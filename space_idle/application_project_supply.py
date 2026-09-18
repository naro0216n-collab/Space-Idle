from __future__ import annotations

from .application_views import SupplyRequirementRow, SupplyRoutingConstraintRow, TargetStockRow


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

            constraint = sim.logistics.routing_constraint_for(requirement)
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
                    routing_constraint_source_id=(
                        None if constraint is None or constraint.source_node_id is None
                        else str(constraint.source_node_id)
                    ),
                    routing_constraint_via_node_ids=(
                        () if constraint is None
                        else tuple(str(value) for value in constraint.required_via_node_ids)
                    ),
                    routing_constraint_transport_allocation_ids=(
                        () if constraint is None
                        else tuple(
                            str(value)
                            for value in constraint.required_transport_allocation_ids
                        )
                    ),
                    selected_source_id=(
                        None if options.selected_source_id is None
                        else str(options.selected_source_id)
                    ),
                    selected_service_ids=options.selected_service_ids,
                    selected_movement_plan_ids=tuple(
                        str(value) for value in options.selected_movement_plan_ids
                    ),
                    projected_arrival_day=options.projected_arrival_day,
                    selected_latency_days=options.selected_latency_days,
                    selected_propellant_t_per_t=options.selected_propellant_t_per_t,
                    selected_handoff_count=options.selected_handoff_count,
                    selected_bottleneck_capacity_t_per_day=(
                        options.selected_bottleneck_capacity_t_per_day
                    ),
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

    def _routing_constraint_rows(self) -> tuple[SupplyRoutingConstraintRow, ...]:
        return tuple(
            SupplyRoutingConstraintRow(
                destination_id=str(row.scope.destination_id),
                owner_kind=row.scope.owner_kind,
                owner_id=None if row.scope.owner_id is None else str(row.scope.owner_id),
                resource_id=(
                    None if row.scope.resource_id is None else str(row.scope.resource_id)
                ),
                source_node_id=(
                    None if row.source_node_id is None else str(row.source_node_id)
                ),
                required_via_node_ids=tuple(
                    str(value) for value in row.required_via_node_ids
                ),
                required_transport_allocation_ids=tuple(
                    str(value) for value in row.required_transport_allocation_ids
                ),
            )
            for row in self._simulation.logistics.routing_constraint_rows()
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
