from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

EntityId = NewType("EntityId", str)
DefinitionId = NewType("DefinitionId", str)
CelestialBodyId = NewType("CelestialBodyId", str)
VehicleId = NewType("VehicleId", str)
SpatialNodeId = NewType("SpatialNodeId", str)
RouteId = NewType("RouteId", str)
ProjectId = NewType("ProjectId", str)
CargoOrderId = NewType("CargoOrderId", str)
ContractId = NewType("ContractId", str)


@dataclass
class AccountState:
    """Auxiliary monetary balance used by explicitly financial domain boundaries."""

    funds_musd: float

    def can_spend(self, amount: float) -> bool:
        if amount < -1e-9:
            raise ValueError("spend amount must be non-negative")
        return self.funds_musd + 1e-9 >= amount

    def spend(self, amount: float) -> bool:
        if amount < -1e-9:
            raise ValueError("spend amount must be non-negative")
        if not self.can_spend(amount):
            return False
        self.funds_musd -= amount
        return True

    def earn(self, amount: float) -> None:
        if amount < -1e-9:
            raise ValueError("income amount must be non-negative")
        self.funds_musd += amount
