from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .transport import PathPolicyLiteral

SourceSelectionModeLiteral = Literal["pinned", "preferred", "allow_any"]
PathSelectionModeLiteral = Literal["pinned", "preferred", "allow_any"]


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
class CreateLogisticsPolicy:
    policy_id: str
    source_mode: SourceSelectionModeLiteral = "allow_any"
    allowed_source_ids: tuple[str, ...] | None = None
    preferred_source_id: str | None = None
    path_mode: PathSelectionModeLiteral = "allow_any"
    explicit_path: tuple[str, ...] | None = None
    allowed_handoff_ids: tuple[str, ...] | None = None
    allowed_service_ids: tuple[str, ...] | None = None
    path_preference: PathPolicyLiteral = "balanced"


@dataclass(frozen=True)
class UpdateLogisticsPolicy:
    policy_id: str
    source_mode: SourceSelectionModeLiteral
    allowed_source_ids: tuple[str, ...] | None = None
    preferred_source_id: str | None = None
    path_mode: PathSelectionModeLiteral = "allow_any"
    explicit_path: tuple[str, ...] | None = None
    allowed_handoff_ids: tuple[str, ...] | None = None
    allowed_service_ids: tuple[str, ...] | None = None
    path_preference: PathPolicyLiteral = "balanced"


@dataclass(frozen=True)
class AssignLogisticsPolicy:
    owner_kind: str
    owner_id: str
    policy_id: str


@dataclass(frozen=True)
class UnassignLogisticsPolicy:
    owner_kind: str
    owner_id: str


@dataclass(frozen=True)
class SetGlobalLogisticsPolicy:
    policy_id: str | None


@dataclass(frozen=True)
class DeleteLogisticsPolicy:
    policy_id: str
