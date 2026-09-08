from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .logistics import LogisticsService
from .power import PowerService, PowerSnapshot
from .shared import AccountState, CargoOrderId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from .technology import TechnologyState
from .construction.models import (ProjectStatus, LocalSubstitutionTier, BuildComponentRequirement, ConstructionRecipe, ConstructionProviderSpec, ConstructionResourceProviderSpec, ProjectComponentState, BuildProject, ProjectBlocker)
from .construction.rules import ConstructionRulesMixin
from .construction.planning import ConstructionPlanningMixin
from .construction.procurement import ConstructionProcurementMixin
from .construction.execution import ConstructionExecutionMixin


@dataclass
class ProjectService(ConstructionRulesMixin, ConstructionPlanningMixin, ConstructionProcurementMixin, ConstructionExecutionMixin):
        recipes: dict[DefinitionId, ConstructionRecipe]
        construction_providers: dict[DefinitionId, ConstructionProviderSpec]
        inventory: InventoryBook
        facilities: FacilityBook
        power: PowerService
        logistics: LogisticsService
        account: AccountState
        sourcing_wait_days: dict[SourcingPolicy, int]
        technology_state: TechnologyState = field(default_factory=TechnologyState)
        construction_resource_providers: dict[DefinitionId, ConstructionResourceProviderSpec] = field(default_factory=dict)
        projects: dict[ProjectId, BuildProject] = field(default_factory=dict)
        _counter: int = 0

        @property
        def unlocked_technologies(self) -> set[DefinitionId]:
            return self.technology_state.completed
