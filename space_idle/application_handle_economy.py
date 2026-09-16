from __future__ import annotations

from .application_commands import (
    CancelTradeOrder, Command, CommandResult, CreateTradeOrder, UpdateTradeOrder,
)
from .market import TradeControlMode, TradeDirection
from .priority import ActivityPriority
from .shared import DefinitionId, EntityId


class MarketCommandHandlerMixin:
    def _handle_market_command(self, command: Command):
        market = self._simulation.market
        if isinstance(command, CreateTradeOrder):
            order_id = market.create_order(
                direction=TradeDirection(command.direction),
                resource_id=DefinitionId(command.resource_id),
                market_interface_id=EntityId(command.market_interface_id),
                priority=ActivityPriority(command.priority),
                control_mode=TradeControlMode(command.control_mode),
                quantity_target_t=command.quantity_target_t,
                rate_target_t_per_day=command.rate_target_t_per_day,
                price_limit_musd_per_t=command.price_limit_musd_per_t,
            )
            return CommandResult(str(order_id))
        if isinstance(command, UpdateTradeOrder):
            market.update_order(
                EntityId(command.order_id),
                priority=ActivityPriority(command.priority),
                control_mode=TradeControlMode(command.control_mode),
                quantity_target_t=command.quantity_target_t,
                rate_target_t_per_day=command.rate_target_t_per_day,
                price_limit_musd_per_t=command.price_limit_musd_per_t,
                replace_price_limit=True,
            )
            return CommandResult()
        if isinstance(command, CancelTradeOrder):
            market.cancel_order(EntityId(command.order_id))
            return CommandResult()
        return NotImplemented
