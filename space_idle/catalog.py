from __future__ import annotations

from dataclasses import dataclass

from .shared import DefinitionId


@dataclass(frozen=True)
class ResourceDef:
    id: DefinitionId
    display_name: str
    unit: str = "t"
    category: str = "material"


@dataclass(frozen=True)
class GameCatalog:
    resources: dict[DefinitionId, ResourceDef]
