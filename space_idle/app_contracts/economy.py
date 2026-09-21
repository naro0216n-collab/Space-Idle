from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateTradeOrder:
    direction: str
    resource_id: str
    market_interface_id: str
    priority: int = 3
    control_mode: str = "quantity"
    quantity_target_t: float | None = None
    rate_target_t_per_day: float | None = None
    price_limit_musd_per_t: float | None = None


@dataclass(frozen=True)
class UpdateTradeOrder:
    order_id: str
    priority: int
    control_mode: str
    quantity_target_t: float | None = None
    rate_target_t_per_day: float | None = None
    price_limit_musd_per_t: float | None = None


@dataclass(frozen=True)
class CancelTradeOrder:
    order_id: str
