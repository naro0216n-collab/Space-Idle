from __future__ import annotations

from ..external_procurement import ExternalProcurementServiceDef
from . import base_ids as ids


def build_external_procurement_services() -> dict:
    """Base-game external physical resource offers.

    The Earth industrial market is a delivery endpoint, not an inventory source.
    Purchases are ordered through External Economy policy/funds allocation and
    become Logistics-owned delivery batches before Storage admission.
    """
    service = ExternalProcurementServiceDef(
        id=ids.EARTH_INDUSTRIAL_MARKET,
        display_name="地球産業市場",
        delivery_node_id=ids.EARTH,
        resource_prices_musd_per_t=(
            (ids.STRUCTURAL_COMPONENTS, 0.18),
            (ids.MACHINERY, 0.24),
            (ids.PRECISION_ELECTRONICS, 0.55),
            (ids.CONSTRUCTION_EQUIPMENT, 0.32),
        ),
        delivery_latency_days=2,
    )
    return {service.id: service}
