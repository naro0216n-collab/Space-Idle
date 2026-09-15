from __future__ import annotations

from dataclasses import dataclass, field

from .external_economy import ExternalEconomyState
from .external_procurement import ExternalProcurementServiceDef, ProcurementDeliveryBatch
from .facilities import FacilityBook
from .inventory import InventoryBook
from .logistics_procurement import ExternalProcurementMixin
from .shared import DefinitionId, EntityId
from .supply_planning import SupplyPlanningMixin
from .logistics_models import CargoFlowBatch
from .supply import SupplyPolicy, TargetStockPolicy
from .transport.service import TransportService
from .logistics_flow import LogisticsFlowMixin


@dataclass
class LogisticsService(SupplyPlanningMixin, LogisticsFlowMixin, ExternalProcurementMixin):
    """Logistics demand/capacity allocation and Cargo Flow state owner."""

    transport: TransportService
    inventory: InventoryBook
    external_economy: ExternalEconomyState
    facilities: FacilityBook
    cargo_flows: dict[EntityId, CargoFlowBatch] = field(default_factory=dict)
    target_stocks: dict[EntityId, TargetStockPolicy] = field(default_factory=dict)
    supply_policies: dict[EntityId, SupplyPolicy] = field(default_factory=dict)
    procurement_services: dict[DefinitionId, ExternalProcurementServiceDef] = field(default_factory=dict)
    procurement_deliveries: dict[EntityId, ProcurementDeliveryBatch] = field(default_factory=dict)
    _cargo_flow_counter: int = 0
    _procurement_delivery_counter: int = 0


__all__ = ["LogisticsService"]
