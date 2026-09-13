from __future__ import annotations

from dataclasses import dataclass, field

from .shared import DefinitionId, EntityId, SpatialNodeId


@dataclass
class MarketState:
    id: EntityId
    participant_organization_ids: set[EntityId] = field(default_factory=set)
    accessible_location_ids: set[SpatialNodeId] = field(default_factory=set)
    reference_prices: dict[DefinitionId, float] = field(default_factory=dict)
    demand: dict[DefinitionId, float] = field(default_factory=dict)
    supply: dict[DefinitionId, float] = field(default_factory=dict)

    def clear_price(self, resource_id: DefinitionId) -> float:
        base = self.reference_prices.get(resource_id, 1.0)
        if base < 0:
            raise ValueError("reference price must be non-negative")
        demand = self.demand.get(resource_id, 0.0)
        supply = self.supply.get(resource_id, 0.0)
        if demand < 0 or supply < 0:
            raise ValueError("market demand and supply must be non-negative")
        pressure = (demand + 1.0) / (supply + 1.0)
        return base * max(0.25, min(4.0, pressure))
