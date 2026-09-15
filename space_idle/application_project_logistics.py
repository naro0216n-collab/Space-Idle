from __future__ import annotations

from .application_project_logistics_routes import LogisticsRouteProjectorMixin
from .application_project_logistics_state import LogisticsStateProjectorMixin
from .application_project_supply import SupplyPlanningProjectorMixin
from .application_views import LogisticsSummaryView, LogisticsView


class LogisticsProjectorMixin(
    LogisticsRouteProjectorMixin,
    LogisticsStateProjectorMixin,
    SupplyPlanningProjectorMixin,
):
    def _logistics_view(self) -> LogisticsView:
        sim = self._simulation
        decision = sim.tick_decision_projection()
        return LogisticsView(
            routes=self._route_rows(),
            fleet_pools=self._fleet_pool_rows(),
            relocations=self._fleet_relocation_rows(),
            releases=self._fleet_release_rows(),
            allocations=self._transport_allocation_rows(),
            vehicle_production_options=self._vehicle_production_option_rows(),
            vehicle_production=self._vehicle_production_rows(),
            cargo_flows=self._cargo_flow_rows(),
            external_supply_batches=self._external_supply_rows(),
            supply_policies=self._supply_policy_rows(),
            target_stocks=self._target_stock_rows(),
            requirements=self._requirement_rows(
                execution_allocation=decision.allocations.transport,
                resolutions=decision.plan.demand_resolutions,
            ),
        )

    def _logistics_summary_view(self) -> LogisticsSummaryView:
        sim = self._simulation
        routes = self._route_rows(include_modes=False)
        pools = self._fleet_pool_rows()
        allocations = self._transport_allocation_rows()
        flows = self._cargo_flow_rows()
        decision = sim.tick_decision_projection()
        requirement_rows = self._requirement_rows(
            execution_allocation=decision.allocations.transport,
            resolutions=decision.plan.demand_resolutions,
        )
        return LogisticsSummaryView(
            route_count=len(routes),
            usable_route_count=sum(1 for row in routes if row.service_feasible_now),
            fleet_units=sum(row.total_units for row in pools),
            free_fleet_units=sum(row.free_units for row in pools),
            allocation_count=len(allocations),
            unfilled_allocation_units=sum(row.unfilled_units for row in allocations),
            cargo_flow_count=len(flows),
            supply_policy_count=len(sim.logistics.supply_policy_rows()),
            target_stock_count=len(sim.logistics.target_stock_policies()),
            requirement_count=len(requirement_rows),
            queued_supply_t=sum(row.remaining_t for row in requirement_rows),
            in_transit_t=sum(row.amount_t for row in flows if row.status == "in_transit"),
            arrival_waiting_t=sum(row.amount_t for row in flows if row.status == "arrival_waiting"),
        )
