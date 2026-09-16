from __future__ import annotations

from dataclasses import dataclass
from ..priority import ActivityPriority


@dataclass(frozen=True)
class MarketOfferRow:
    resource_id: str
    buy_price_musd_per_t: float | None
    sell_price_musd_per_t: float | None
    provider_supply_available_t: float
    provider_demand_available_t: float


@dataclass(frozen=True)
class MarketInterfaceRow:
    id: str
    provider_id: str
    provider_name: str
    operational_node_id: str
    enabled: bool
    offers: tuple[MarketOfferRow, ...]


@dataclass(frozen=True)
class TradeOrderRow:
    id: str
    direction: str
    resource_id: str
    market_interface_id: str
    priority: ActivityPriority
    control_mode: str
    quantity_target_t: float | None
    rate_target_t_per_day: float | None
    price_limit_musd_per_t: float | None
    current_offer_price_musd_per_t: float | None
    committed_quantity_t: float
    in_flight_quantity_t: float
    presented_quantity_t: float
    settled_quantity_t: float
    blockers: tuple[str, ...]
    limiting_factors: tuple[str, ...]


@dataclass(frozen=True)
class BuyCommitmentRow:
    id: str
    order_id: str
    resource_id: str
    remaining_quantity_t: float
    committed_price_musd_per_t: float
    reserved_funds_musd: float
    maturity_day: int
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketView:
    funds_total_musd: float
    funds_available_musd: float
    interfaces: tuple[MarketInterfaceRow, ...]
    orders: tuple[TradeOrderRow, ...]
    buy_commitments: tuple[BuyCommitmentRow, ...]
