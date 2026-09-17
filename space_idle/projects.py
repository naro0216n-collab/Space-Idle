from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .facilities import FacilityBook
from .facility_lifecycle import FacilityLifecycleRegistry
from .inventory import InventoryBook
from .power import PowerService
from .service_capacity import ServiceCapacityRegistry
from .shared import DefinitionId, ProjectId, SurfaceCellId
from .spatial_claims import SurfaceCellClaimRegistry
from .technology import TechnologyState
from .surface_infrastructure import SurfaceInfrastructureService
from .construction.models import (
    ProjectStatus,
    BuildResourceRequirement,
    ConstructionRecipe,
    FacilityUpgradeRecipe,
    FacilityDecommissionRecipe,
    SpatialDevelopmentRecipe,
    ConstructionProviderSpec,
    ConstructionResourceProviderSpec,
    ProjectResourceState,
    ConstructionProject,
    NewFacilityTarget,
    FacilityUpgradeTarget,
    FacilityDecommissionTarget,
    SurfaceCellDevelopmentTarget,
    ProcurementTimingPolicy,
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
    decommission_recipes: dict[DefinitionId, FacilityDecommissionRecipe]
    construction_providers: dict[DefinitionId, ConstructionProviderSpec]
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    service_capacity_registry: ServiceCapacityRegistry
    procurement_wait_days: dict[ProcurementTimingPolicy, int]
    surface_infrastructure: SurfaceInfrastructureService | None = None
    surface_knowledge_level_provider: Callable[[SurfaceCellId], int] | None = None
    surface_cell_claim_registry: SurfaceCellClaimRegistry = field(default_factory=SurfaceCellClaimRegistry)
    facility_lifecycle_registry: FacilityLifecycleRegistry = field(default_factory=FacilityLifecycleRegistry)
    technology_state: TechnologyState = field(default_factory=TechnologyState)
    construction_resource_providers: dict[DefinitionId, ConstructionResourceProviderSpec] = field(default_factory=dict)
    spatial_recipes: dict[DefinitionId, SpatialDevelopmentRecipe] = field(default_factory=dict)
    surface_cell_development_recipe_id: DefinitionId | None = None
    projects: dict[ProjectId, ConstructionProject] = field(default_factory=dict)
    _counter: int = 0

    def __post_init__(self) -> None:
        self.surface_cell_claim_registry.register(self)

    @property
    def unlocked_technologies(self) -> set[DefinitionId]:
        return self.technology_state.completed
