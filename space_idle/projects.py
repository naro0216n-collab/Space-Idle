from __future__ import annotations

from dataclasses import dataclass, field

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService
from .shared import DefinitionId, ProjectId
from .technology import TechnologyState
from .surface_infrastructure import SurfaceInfrastructureService
from .construction.models import (
    ProjectStatus,
    BuildResourceRequirement,
    ConstructionRecipe,
    FacilityUpgradeRecipe,
    SpatialDevelopmentRecipe,
    ConstructionProviderSpec,
    ConstructionResourceProviderSpec,
    ProjectResourceState,
    ConstructionProject,
    NewFacilityTarget,
    FacilityUpgradeTarget,
    LocationFoundingTarget,
    SurfaceCellDevelopmentTarget,
    ProjectBlocker,
    SourcingPolicy,
)
from .construction.rules import ConstructionRulesMixin
from .construction.accounting import ConstructionAccountingMixin
from .construction.planning import ConstructionPlanningMixin
from .construction.procurement import ConstructionProcurementMixin
from .construction.execution import ConstructionExecutionMixin


@dataclass
class ProjectService(ConstructionRulesMixin, ConstructionAccountingMixin, ConstructionPlanningMixin, ConstructionProcurementMixin, ConstructionExecutionMixin):
    recipes: dict[DefinitionId, ConstructionRecipe]
    upgrade_recipes: dict[tuple[DefinitionId, int], FacilityUpgradeRecipe]
    construction_providers: dict[DefinitionId, ConstructionProviderSpec]
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    sourcing_wait_days: dict[SourcingPolicy, int]
    surface_infrastructure: SurfaceInfrastructureService | None = None
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    construction_resource_providers: dict[DefinitionId, ConstructionResourceProviderSpec] = field(default_factory=dict)
    spatial_recipes: dict[DefinitionId, SpatialDevelopmentRecipe] = field(default_factory=dict)
    location_founding_recipe_id: DefinitionId | None = None
    surface_cell_development_recipe_id: DefinitionId | None = None
    projects: dict[ProjectId, ConstructionProject] = field(default_factory=dict)
    _counter: int = 0

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed
