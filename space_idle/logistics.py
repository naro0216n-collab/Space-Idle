from __future__ import annotations

from dataclasses import dataclass, field

from .external_economy import ExternalEconomyState
from .external_procurement import ExternalProcurementServiceDef, ProcurementDeliveryBatch
from .facilities import FacilityBook
from .inventory import InventoryBook
from .logistics_procurement import ExternalProcurementMixin
from .shared import DefinitionId, EntityId
from .logistics_lanes import LaneRuntimeMetrics, LogisticsLaneMixin, LogisticsLaneSnapshot
from .logistics_models import CargoFlowBatch, LogisticsLane
from .transport.service import TransportService
from .logistics_flow import LogisticsFlowMixin


@dataclass
class LogisticsService(LogisticsLaneMixin, LogisticsFlowMixin, ExternalProcurementMixin):
    """Logistics demand/capacity allocation and Cargo Flow state owner."""

    transport: TransportService
    inventory: InventoryBook
    external_economy: ExternalEconomyState
    facilities: FacilityBook
    cargo_flows: dict[EntityId, CargoFlowBatch] = field(default_factory=dict)
    lanes: dict[EntityId, LogisticsLane] = field(default_factory=dict)
    procurement_services: dict[DefinitionId, ExternalProcurementServiceDef] = field(default_factory=dict)
    procurement_deliveries: dict[EntityId, ProcurementDeliveryBatch] = field(default_factory=dict)
    _lane_counter: int = 0
    _cargo_flow_counter: int = 0
    _procurement_delivery_counter: int = 0


__all__ = [
    "LaneRuntimeMetrics",
    "LogisticsLane",
    "LogisticsLaneSnapshot",
    "LogisticsService",
]
