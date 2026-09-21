from __future__ import annotations

from .application_constraints import constraints_from_codes, limiting_factors_from_codes
from .application_views import (
    BuyCommitmentRow, MarketInterfaceRow, MarketOfferRow, MarketView, TradeOrderRow,
)
from .market import TradeDirection


class MarketProjectorMixin:
    def _market_view(self) -> MarketView:
        sim = self._simulation
        market = sim.market
        interfaces = []
        for interface in sorted(market.interfaces.values(), key=lambda row: str(row.id)):
            provider = market.provider_defs[interface.provider_id]
            resources = sorted(
                {rid for rid, _ in provider.buy_offers_musd_per_t}
                | {rid for rid, _ in provider.sell_offers_musd_per_t},
                key=str,
            )
            interfaces.append(MarketInterfaceRow(
                str(interface.id), str(provider.id), provider.display_name,
                str(interface.operational_node_id), interface.enabled,
                tuple(MarketOfferRow(
                    str(resource_id), provider.buy_price(resource_id), provider.sell_price(resource_id),
                    market.available_provider_supply_t(provider.id, resource_id),
                    market.available_provider_demand_t(provider.id, resource_id),
                ) for resource_id in resources),
            ))

        buy_plan = market.plan_buy_allocations()
        buy_limiting = {row.order_id: row.limiting_factors for row in buy_plan.rows}
        orders = []
        for order in sorted(market.orders.values(), key=lambda row: str(row.id)):
            interface = market.interfaces[order.market_interface_id]
            provider = market.provider_defs[interface.provider_id]
            price = provider.buy_price(order.resource_id) if order.direction is TradeDirection.BUY else provider.sell_price(order.resource_id)
            committed = sum(
                row.remaining_quantity_t for row in market.buy_commitments.values()
                if row.order_id == order.id
            )
            in_flight = 0.0
            presented = 0.0
            blockers: list[str] = []
            limiting = list(buy_limiting.get(order.id, ()))
            if not interface.enabled:
                blockers.append("market_interface_disabled")
            if price is None:
                blockers.append("offer_unavailable")
            elif not order.accepts_offer_price(price):
                blockers.append("price_condition")
            if order.direction is TradeDirection.SELL:
                requirement_id = market.sell_requirement_id(order.id)
                in_flight = sim.logistics.cargo_flow_pipeline_t(requirement_id)
                presented = sim.inventory.available(interface.operational_node_id, order.resource_id)
                if market.available_provider_demand_t(interface.provider_id, order.resource_id) <= 1e-9:
                    limiting.append("provider_demand")
                if presented <= 1e-9 and in_flight <= 1e-9:
                    blockers.append("resource_not_at_market_interface")
            orders.append(TradeOrderRow(
                str(order.id), order.direction.value, str(order.resource_id), str(order.market_interface_id),
                order.priority, order.control_mode.value, order.quantity_target_t, order.rate_target_t_per_day,
                order.price_limit_musd_per_t, price, committed, in_flight, presented,
                order.settled_quantity_t,
                constraints_from_codes(
                    tuple(dict.fromkeys(blockers)),
                    affected_action="execute_market_order",
                    related_entity_kind="trade_order",
                    related_entity_id=str(order.id),
                ),
                limiting_factors_from_codes(
                    tuple(dict.fromkeys(limiting)),
                    affected_action="execute_market_order",
                    related_entity_kind="trade_order",
                    related_entity_id=str(order.id),
                ),
            ))
        commitments = tuple(
            BuyCommitmentRow(
                str(row.id), str(row.order_id), str(row.resource_id), row.remaining_quantity_t,
                row.committed_price_musd_per_t, row.reserved_funds_musd, row.maturity_day,
                constraints_from_codes(
                    sim.inventory.admission_state(
                        market.interfaces[market.orders[row.order_id].market_interface_id].operational_node_id,
                        row.resource_id,
                    ).blockers if row.maturity_day <= sim.day else (),
                    affected_action="settle_market_buy",
                    related_entity_kind="buy_commitment",
                    related_entity_id=str(row.id),
                ),
            )
            for row in sorted(market.buy_commitments.values(), key=lambda value: str(value.id))
        )
        return MarketView(
            market.funds.balance, market.available_funds_musd, tuple(interfaces), tuple(orders), commitments
        )
