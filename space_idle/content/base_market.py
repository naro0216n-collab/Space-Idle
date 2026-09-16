from __future__ import annotations

from ..market import MarketAvailabilityDef, MarketInterfaceState, MarketProviderDef
from ..shared import DefinitionId, EntityId
from . import base_ids as ids

EARTH_MARKET_PROVIDER = DefinitionId("base.market_provider.earth_industrial")
EARTH_MARKET_INTERFACE = EntityId("base.market_interface.earth_industrial")


def build_market_provider_definitions() -> dict[DefinitionId, MarketProviderDef]:
    provider = MarketProviderDef(
        id=EARTH_MARKET_PROVIDER,
        display_name="地球産業市場",
        buy_offers_musd_per_t=(
            (ids.STRUCTURAL_COMPONENTS, 0.18),
            (ids.MACHINERY, 0.24),
            (ids.PRECISION_ELECTRONICS, 0.55),
            (ids.CONSTRUCTION_EQUIPMENT, 0.32),
        ),
        sell_offers_musd_per_t=(
            (ids.STRUCTURAL_COMPONENTS, 0.12),
            (ids.MACHINERY, 0.16),
            (ids.PRECISION_ELECTRONICS, 0.36),
            (ids.CONSTRUCTION_EQUIPMENT, 0.20),
            (ids.METAL_FEEDSTOCK, 0.07),
            (ids.WATER, 0.015),
        ),
        supply=(
            MarketAvailabilityDef(ids.STRUCTURAL_COMPONENTS, 800.0, 1200.0, 80.0),
            MarketAvailabilityDef(ids.MACHINERY, 400.0, 600.0, 40.0),
            MarketAvailabilityDef(ids.PRECISION_ELECTRONICS, 160.0, 240.0, 16.0),
            MarketAvailabilityDef(ids.CONSTRUCTION_EQUIPMENT, 240.0, 360.0, 24.0),
        ),
        demand=(
            MarketAvailabilityDef(ids.STRUCTURAL_COMPONENTS, 500.0, 800.0, 50.0),
            MarketAvailabilityDef(ids.MACHINERY, 300.0, 450.0, 30.0),
            MarketAvailabilityDef(ids.PRECISION_ELECTRONICS, 120.0, 180.0, 12.0),
            MarketAvailabilityDef(ids.CONSTRUCTION_EQUIPMENT, 180.0, 270.0, 18.0),
            MarketAvailabilityDef(ids.METAL_FEEDSTOCK, 800.0, 1200.0, 80.0),
            MarketAvailabilityDef(ids.WATER, 1600.0, 2400.0, 160.0),
        ),
        lead_time_days=2,
    )
    return {provider.id: provider}


def build_market_interfaces() -> tuple[MarketInterfaceState, ...]:
    return (MarketInterfaceState(EARTH_MARKET_INTERFACE, EARTH_MARKET_PROVIDER, ids.EARTH, True),)
