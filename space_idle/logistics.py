from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable

from .facilities import FacilityBook
from .inventory import InventoryBook
from .shared import DefinitionId, EntityId
from .supply_planning import SupplyPlanningMixin
from .logistics_models import CargoArrivalWaiting, CargoFlowSegment
from .supply import LogisticsPolicyAssignmentState, LogisticsPolicyState, TargetStockPolicy
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
    target_stocks: dict[EntityId, TargetStockPolicy] = field(default_factory=dict)
    logistics_policies: dict[EntityId, LogisticsPolicyState] = field(default_factory=dict)
    policy_assignments: dict[tuple[str, EntityId], LogisticsPolicyAssignmentState] = field(default_factory=dict)
    global_policy_id: EntityId | None = None
    _policy_owner_resolvers: dict[str, Callable[[EntityId], bool]] = field(default_factory=dict, repr=False)
    _cargo_flow_counter: int = 0
    _arrival_waiting_counter: int = 0

    def __post_init__(self) -> None:
        self.register_policy_owner_resolver(
            "target_stock", lambda owner_id: owner_id in self.target_stocks
        )


__all__ = ["LogisticsService"]
