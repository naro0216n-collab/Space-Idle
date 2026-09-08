from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .logistics import LogisticsService
from .power import PowerService
from .shared import AccountState, DefinitionId, ProjectId
from .technology import TechnologyState
from .construction.models import (
    ProjectStatus,
    LocalSubstitutionTier,
    BuildComponentRequirement,
    ConstructionRecipe,
    FacilityUpgradeRecipe,
    ConstructionProviderSpec,
    ConstructionResourceProviderSpec,
    ProjectComponentState,
    ConstructionProject,
    NewFacilityTarget,
    FacilityUpgradeTarget,
    ProjectBlocker,
    SourcingPolicy,
)
from .construction.rules import ConstructionRulesMixin
from .construction.planning import ConstructionPlanningMixin
from .construction.procurement import ConstructionProcurementMixin
from .construction.execution import ConstructionExecutionMixin


@dataclass
class ProjectService(ConstructionRulesMixin, ConstructionPlanningMixin, ConstructionProcurementMixin, ConstructionExecutionMixin):
    recipes: dict[DefinitionId, ConstructionRecipe]
    upgrade_recipes: dict[tuple[DefinitionId, int], FacilityUpgradeRecipe]
    construction_providers: dict[DefinitionId, ConstructionProviderSpec]
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    logistics: LogisticsService
    account: AccountState
    sourcing_wait_days: dict[SourcingPolicy, int]
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    construction_resource_providers: dict[DefinitionId, ConstructionResourceProviderSpec] = field(default_factory=dict)
    projects: dict[ProjectId, ConstructionProject] = field(default_factory=dict)
    _counter: int = 0

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed
