from __future__ import annotations

from .application_project_movement_plans import LogisticsMovementPlanProjectorMixin
from .application_project_logistics_state import LogisticsStateProjectorMixin
from .application_project_supply import SupplyPlanningProjectorMixin
from .application_views import LogisticsSummaryView, LogisticsView


class LogisticsProjectorMixin(
    LogisticsMovementPlanProjectorMixin,
    LogisticsStateProjectorMixin,
    SupplyPlanningProjectorMixin,
):
    def _logistics_view(self) -> LogisticsView:
        sim = self._simulation
        decision = self._tick_decision_projection()
        return LogisticsView(
            movement_plans=self._movement_plan_rows(),
            fleet_pools=self._fleet_pool_rows(),
            relocations=self._fleet_relocation_rows(),
            releases=self._fleet_release_rows(),
            retirements=self._fleet_retirement_rows(),
            allocations=self._transport_allocation_rows(),
            vehicle_production_options=self._vehicle_production_option_rows(),
            vehicle_production=self._vehicle_production_rows(),
            cargo_flows=self._cargo_flow_rows(),
            logistics_policies=self._logistics_policy_rows(),
            target_stocks=self._target_stock_rows(),
            requirements=self._requirement_rows(
                execution_allocation=decision.allocations.transport,
                resolutions=decision.plan.requirement_resolutions,
            ),
        )

    def _logistics_summary_view(self) -> LogisticsSummaryView:
        sim = self._simulation
        movement_plans = self._movement_plan_rows(include_modes=False)
        pools = self._fleet_pool_rows()
        allocations = self._transport_allocation_rows()
        flows = self._cargo_flow_rows()
        decision = self._tick_decision_projection()
        requirement_rows = self._requirement_rows(
            execution_allocation=decision.allocations.transport,
            resolutions=decision.plan.requirement_resolutions,
        )
        return LogisticsSummaryView(
            movement_plan_count=len(movement_plans),
            usable_movement_plan_count=sum(1 for row in movement_plans if row.service_feasible_now),
            fleet_units=sum(row.total_units for row in pools),
            free_fleet_units=sum(row.free_units for row in pools),
            allocation_count=len(allocations),
            unfilled_allocation_units=sum(row.unfilled_units for row in allocations),
            cargo_flow_count=len(flows),
            logistics_policy_count=len(sim.logistics.logistics_policy_rows()),
            target_stock_count=len(sim.logistics.target_stock_policies()),
            requirement_count=len(requirement_rows),
            queued_supply_t=sum(row.remaining_t for row in requirement_rows),
            in_transit_t=sum(row.amount_t for row in flows if row.status == "in_transit"),
            arrival_waiting_t=sum(row.amount_t for row in flows if row.status == "arrival_waiting"),
        )
