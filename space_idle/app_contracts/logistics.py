from __future__ import annotations

from dataclasses import dataclass

from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .transport import PathPolicyLiteral


@dataclass(frozen=True)
class SetTargetStock:
    destination_id: str
    resource_id: str
    target_quantity_t: float
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY


@dataclass(frozen=True)
class DeleteTargetStock:
    destination_id: str
    resource_id: str


@dataclass(frozen=True)
class SetSupplyPolicy:
    destination_id: str
    resource_id: str
    preferred_source_id: str | None = None
    path_policy: PathPolicyLiteral = "fastest"
    explicit_path: tuple[str, ...] | None = None


@dataclass(frozen=True)
class DeleteSupplyPolicy:
    destination_id: str
    resource_id: str
