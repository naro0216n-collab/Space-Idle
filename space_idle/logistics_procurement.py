from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .external_economy import FundsAllocationPlan, FundsRequest
from .external_procurement import (
    ExternalProcurementPlan,
    ProcurementDeliveryBatch,
    ProcurementDeliveryStatus,
    ProcurementOrder,
)
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, SpatialNodeId

if TYPE_CHECKING:
    from .transport.steady_logistics import LogisticsResourcePlan


class ExternalProcurementMixin:
    """External resource sourcing connected to the normal Logistics pipeline."""

    @staticmethod
    def _procurement_request_id(
        demand_id: EntityId,
        delivery_node_id: SpatialNodeId,
        service_id: DefinitionId,
    ) -> EntityId:
        return EntityId(
            f"funds.procurement:{demand_id}:{delivery_node_id}:{service_id}"
        )

    def procurement_pipeline_t(
        self,
        demand_id: EntityId,
        *,
        delivery_node_id: SpatialNodeId | None = None,
    ) -> float:
        return sum(
            row.amount_t
            for row in self.procurement_deliveries.values()
            if row.demand_id == demand_id
            and (delivery_node_id is None or row.delivery_node_id == delivery_node_id)
        )

    def _procurement_service_for(
        self,
        demand: ResourceDemand,
        delivery_node_id: SpatialNodeId,
    ):
        candidates = []
        for service in self.procurement_services.values():
            if service.delivery_node_id != delivery_node_id:
                continue
            price = service.unit_price_musd_per_t(demand.resource_id)
            if price is None:
                continue
            policy = self.external_economy.resolve_policy(
                service.id, demand.owner_kind, demand.owner_id
            )
            if policy is None:
                continue
            candidates.append((price, str(service.id), service, policy))
        if not candidates:
            return None
        _price, _service_key, service, policy = min(candidates, key=lambda row: row[:2])
        return service, policy

    def _source_procurement_needs(
        self,
        logistics_plan: "LogisticsResourcePlan",
    ) -> tuple[tuple[ResourceDemand, SpatialNodeId, float], ...]:
        """Return source-stock shortages for already selected Logistics dispatches.

        Current source Inventory is shared across planned dispatches by priority
        and proportionally within equal priority.  This is planning credit only;
        current-tick Resource allocation remains authoritative for dispatch.
        """
        planned: dict[tuple[EntityId, SpatialNodeId], tuple[ResourceDemand, float]] = {}
        for row in logistics_plan.dispatches:
            lane = self.lanes[row.lane_id]
            key = (row.demand.id, lane.source_id)
            existing = planned.get(key)
            planned[key] = (
                row.demand,
                row.amount_t + (0.0 if existing is None else existing[1]),
            )

        remaining_rows: list[tuple[ResourceDemand, SpatialNodeId, float]] = []
        for (demand_id, source_id), (demand, amount_t) in planned.items():
            pipeline = self.procurement_pipeline_t(
                demand_id, delivery_node_id=source_id
            )
            need = max(0.0, amount_t - pipeline)
            if need > 1e-12:
                remaining_rows.append((demand, source_id, need))

        grouped: dict[tuple[SpatialNodeId, DefinitionId], list[int]] = {}
        for index, (demand, source_id, _amount) in enumerate(remaining_rows):
            grouped.setdefault((source_id, demand.resource_id), []).append(index)

        shortages = [amount for _demand, _source, amount in remaining_rows]
        for (source_id, resource_id), indices in grouped.items():
            available = max(0.0, self.inventory.available(source_id, resource_id))
            priorities: dict[int, list[int]] = {}
            for index in indices:
                priorities.setdefault(remaining_rows[index][0].priority, []).append(index)
            for priority in sorted(priorities, reverse=True):
                band = priorities[priority]
                total = sum(shortages[index] for index in band)
                if total <= 1e-12 or available <= 1e-12:
                    continue
                covered = min(available, total)
                for index in band:
                    amount = shortages[index]
                    shortages[index] = max(0.0, amount - covered * amount / total)
                available -= covered

        return tuple(
            (demand, source_id, shortages[index])
            for index, (demand, source_id, _amount) in enumerate(remaining_rows)
            if shortages[index] > 1e-12
        )

    def plan_external_procurement(
        self,
        day: int,
        demands: tuple[ResourceDemand, ...],
        logistics_plan: "LogisticsResourcePlan",
    ) -> ExternalProcurementPlan:
        del day  # Planning is snapshot-based; latency starts only on execution.
        planned_transport_by_demand: dict[EntityId, float] = {}
        for row in logistics_plan.dispatches:
            planned_transport_by_demand[row.demand.id] = (
                planned_transport_by_demand.get(row.demand.id, 0.0) + row.amount_t
            )

        needs: list[tuple[ResourceDemand, SpatialNodeId, float]] = []
        for demand in demands:
            if demand.source_id is not None:
                continue
            delivered_or_planned = (
                self.cargo_flow_pipeline_t(demand.id)
                + planned_transport_by_demand.get(demand.id, 0.0)
                + self.procurement_pipeline_t(
                    demand.id, delivery_node_id=demand.destination_id
                )
            )
            direct_need = max(0.0, demand.amount_t - delivered_or_planned)
            if direct_need > 1e-12:
                needs.append((demand, demand.destination_id, direct_need))
        needs.extend(self._source_procurement_needs(logistics_plan))

        orders: list[ProcurementOrder] = []
        requests: list[FundsRequest] = []
        for demand, delivery_node_id, amount_t in sorted(
            needs,
            key=lambda row: (
                -row[0].priority,
                str(row[0].id),
                str(row[1]),
            ),
        ):
            resolved = self._procurement_service_for(demand, delivery_node_id)
            if resolved is None:
                continue
            service, policy = resolved
            unit_price = service.unit_price_musd_per_t(demand.resource_id)
            assert unit_price is not None
            request_id = self._procurement_request_id(
                demand.id, delivery_node_id, service.id
            )
            request = FundsRequest(
                request_id,
                policy.id,
                service.id,
                amount_t * unit_price,
                demand.priority,
                demand.owner_kind,
                demand.owner_id,
                f"procurement:{demand.resource_id}:{delivery_node_id}",
            )
            requests.append(request)
            orders.append(
                ProcurementOrder(
                    service.id,
                    demand,
                    delivery_node_id,
                    amount_t,
                    amount_t,
                    unit_price,
                    request_id,
                )
            )
        return ExternalProcurementPlan(
            tuple(orders), tuple(sorted(requests, key=lambda row: str(row.id)))
        )

    def authorize_external_procurement(
        self,
        plan: ExternalProcurementPlan,
        funds: FundsAllocationPlan,
    ) -> ExternalProcurementPlan:
        rows: list[ProcurementOrder] = []
        for order in plan.orders:
            authorization = funds.authorization(order.funds_request_id)
            requested_cost = order.requested_amount_t * order.unit_price_musd_per_t
            if requested_cost <= 1e-12:
                amount_t = order.requested_amount_t
            else:
                amount_t = min(
                    order.requested_amount_t,
                    order.requested_amount_t
                    * max(0.0, authorization.authorized_musd)
                    / requested_cost,
                )
            if amount_t > 1e-12:
                rows.append(replace(order, amount_t=amount_t))
        return ExternalProcurementPlan(tuple(rows), plan.spending_requests)

    def advance_external_procurement(
        self,
        day: int,
        plan: ExternalProcurementPlan,
        funds: FundsAllocationPlan,
    ) -> None:
        requests_by_id = {request.id: request for request in plan.spending_requests}
        for order in plan.orders:
            service = self.procurement_services[order.service_id]
            authorization = funds.authorization(order.funds_request_id)
            actual_cost = order.amount_t * order.unit_price_musd_per_t
            if actual_cost > authorization.authorized_musd + 1e-8:
                raise RuntimeError("external procurement spend exceeded authorization")
            self.external_economy.spend_authorized(authorization, actual_cost, day)
            self._procurement_delivery_counter += 1
            delivery_id = EntityId(
                f"procurement.delivery.{self._procurement_delivery_counter}"
            )
            self.procurement_deliveries[delivery_id] = ProcurementDeliveryBatch(
                delivery_id,
                service.id,
                order.demand.id,
                order.demand.owner_kind,
                order.demand.owner_id,
                order.delivery_node_id,
                order.demand.resource_id,
                order.amount_t,
                day,
                day + service.delivery_latency_days,
            )

    def settle_procurement_arrivals(self, day: int) -> None:
        for delivery_id in sorted(tuple(self.procurement_deliveries), key=str):
            row = self.procurement_deliveries[delivery_id]
            if (
                row.status is ProcurementDeliveryStatus.IN_TRANSIT
                and row.ready_day <= day
            ):
                row.status = ProcurementDeliveryStatus.ARRIVAL_WAITING
            if row.status is not ProcurementDeliveryStatus.ARRIVAL_WAITING:
                continue
            accepted = self.inventory.add_up_to(
                row.delivery_node_id, row.resource_id, row.amount_t
            )
            row.amount_t = max(0.0, row.amount_t - accepted)
            if row.amount_t <= 1e-9:
                del self.procurement_deliveries[delivery_id]
