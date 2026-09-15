from __future__ import annotations

from ..external_procurement import ExternalProcurementServiceDef
from . import base_ids as ids


def build_external_procurement_services() -> dict:
    """Base-game external physical resource offers.

    The Earth industrial market is an external Supply Endpoint. Purchases are
    authorized through External Economy policy/funds allocation, then enter
    player-owned state only through Inventory Admission at Earth. Any onward
    movement uses the normal Transport / Cargo Flow lifecycle.
    """
    service = ExternalProcurementServiceDef(
        id=ids.EARTH_INDUSTRIAL_MARKET,
        display_name="地球産業市場",
        supply_node_id=ids.EARTH,
        resource_prices_musd_per_t=(
            (ids.STRUCTURAL_COMPONENTS, 0.18),
            (ids.MACHINERY, 0.24),
            (ids.PRECISION_ELECTRONICS, 0.55),
            (ids.CONSTRUCTION_EQUIPMENT, 0.32),
        ),
        supply_latency_days=2,
    )
    return {service.id: service}
