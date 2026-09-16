from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .shared import DefinitionId, EntityId
from .supply_planning import SupplyPlanningMixin
from .logistics_models import CargoArrivalWaiting, CargoFlowSegment, CargoHandoffStaging
from .supply import SupplyPolicy, TargetStockPolicy
from .transport.service import TransportService
from .logistics_flow import LogisticsFlowMixin


@dataclass
class LogisticsService(SupplyPlanningMixin, LogisticsFlowMixin):
    """Supply Requirement / transport-capacity allocation and Cargo Flow state owner."""

    transport: TransportService
    inventory: InventoryBook
    facilities: FacilityBook
    cargo_flows: dict[EntityId, CargoFlowSegment] = field(default_factory=dict)
    arrival_waiting: dict[EntityId, CargoArrivalWaiting] = field(default_factory=dict)
    handoff_staging: dict[EntityId, CargoHandoffStaging] = field(default_factory=dict)
    target_stocks: dict[EntityId, TargetStockPolicy] = field(default_factory=dict)
    supply_policies: dict[EntityId, SupplyPolicy] = field(default_factory=dict)
    _cargo_flow_counter: int = 0
    _arrival_waiting_counter: int = 0
    _handoff_staging_counter: int = 0


__all__ = ["LogisticsService"]
