from __future__ import annotations

from dataclasses import dataclass, field

from .shared import DefinitionId


@dataclass(frozen=True)
class ResourceDef:
    id: DefinitionId
    display_name: str
    unit: str = "t"
    category: str = "material"


@dataclass(frozen=True)
class ResourceGroupDef:
    """Content-defined analytics grouping; never a physical resource authority."""

    id: DefinitionId
    display_name: str
    resource_ids: tuple[DefinitionId, ...]


@dataclass(frozen=True)
class GameCatalog:
    resources: dict[DefinitionId, ResourceDef]
    resource_groups: dict[DefinitionId, ResourceGroupDef] = field(default_factory=dict)
