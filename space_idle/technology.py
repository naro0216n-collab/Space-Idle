from __future__ import annotations

from dataclasses import dataclass, field

from .shared import DefinitionId


@dataclass
class TechnologyState:
    """Single mutable owner of technology unlock state.

    Research mutates this state; construction, logistics and other domains read
    it. Sharing one state object is intentional, while sharing a bare mutable
    set across services is not.
    """

    completed: set[DefinitionId] = field(default_factory=set)

    def is_unlocked(self, technology_id: DefinitionId) -> bool:
        return technology_id in self.completed

    def unlock(self, technology_id: DefinitionId) -> None:
        self.completed.add(technology_id)

    def replace(self, technology_ids: set[DefinitionId]) -> None:
        self.completed.clear()
        self.completed.update(technology_ids)
