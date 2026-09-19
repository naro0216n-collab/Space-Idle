from __future__ import annotations
from typing import TypeAlias
from .app_contracts.common import ApplicationError, CommandResult
from .app_contracts.construction import (
    PlanBuild, PlanFacilityUpgrade, PlanFacilityDecommission, SurfaceLocationFoundingTarget, NonSurfaceOperationalNodeFoundingTarget, PlanOperationalNodeFounding, CancelFounding, PauseFounding, ResumeFounding, SetFoundingPriority, DevelopSurfaceCell, CancelBuild, PauseBuild, ResumeBuild, SetProjectPriority,
    SetProjectProcurementPolicy,
)
from .app_contracts.operations import (
    PauseFacility, ResumeFacility, SetFacilityProcess, SetFacilityActivityPriority,
    SetMaintenancePriority, SetTimeControl, AdvanceTime,
)
from .app_contracts.progression import (
    StartResearch, PauseResearch, ResumeResearch, SetResearchPrototypeSite,
    SetResearchPriority, SetResearchDemonstrationSite, SurveyProviderConstraintInput, StartSurvey, UpdateSurvey,
    PauseSurvey, ResumeSurvey, SetSurveyPriority, StartScientificExploration, SetScientificExplorationPriority,
    PauseScientificExploration, ResumeScientificExploration,
    AssignExplorationFleet, UnassignExplorationFleet,
    SetResearchProviderFleetQuantity,
    SetResearchProviderAssignmentPriority, PauseResearchProviderAssignment,
    ResumeResearchProviderAssignment, SetSurveyProviderFleetQuantity,
)
from .app_contracts.transport import (
    ProduceVehicle, PauseVehicleProduction, ResumeVehicleProduction,
    SetVehicleProductionSettings, CreateTransportAllocation, UpdateTransportAllocation,
    SetTransportMovementConstraint, ClearTransportMovementConstraint,
    PauseTransportAllocation, ResumeTransportAllocation,
    DeleteTransportAllocation, RelocateFleet, RetireFleet, CancelFleetRetirement, SetFleetRetirementPriority,
)
from .app_contracts.logistics import (
    SetTargetStock, DeleteTargetStock, SetSupplyRoutingConstraint, ClearSupplyRoutingConstraint,
)
from .app_contracts.contracts import AcceptContract, DeclineContract
from .app_contracts.economy import (
    CancelTradeOrder, CreateTradeOrder, UpdateTradeOrder,
)
from .app_contracts.queries import (
    GetCatalog, GetWorld, GetSurfaceMap, GetOperationalNode, GetFlowReport, GetDependencyAnalytics, GetBottlenecks, GetAttention, GetProjects,
    GetBuildOptions, GetLogistics, GetLogisticsSummary, GetMovementPlans, GetFleet,
    GetFleetRelocationPreview, GetTransportAllocations, GetCargoFlows, GetTransportAllocationOptions,
    GetResearch, GetScientificExplorations, GetSurveys, GetSurveyCampaignIntentPreview, GetContracts, GetMarket,
)

Command: TypeAlias = (
    PlanBuild | PlanFacilityUpgrade | PlanFacilityDecommission | PlanOperationalNodeFounding | CancelFounding | PauseFounding | ResumeFounding | SetFoundingPriority | DevelopSurfaceCell | CancelBuild | PauseBuild | ResumeBuild | SetProjectPriority |
    SetProjectProcurementPolicy |
    PauseFacility | ResumeFacility | SetFacilityProcess | SetFacilityActivityPriority | SetMaintenancePriority |
    SetTimeControl | StartResearch | PauseResearch | ResumeResearch | SetResearchPrototypeSite |
    SetResearchPriority | SetResearchDemonstrationSite | StartSurvey | UpdateSurvey | PauseSurvey |
    ResumeSurvey | SetSurveyPriority | StartScientificExploration | SetScientificExplorationPriority | PauseScientificExploration |
    ResumeScientificExploration | AssignExplorationFleet | UnassignExplorationFleet |
    SetResearchProviderFleetQuantity |
    SetResearchProviderAssignmentPriority | PauseResearchProviderAssignment |
    ResumeResearchProviderAssignment | SetSurveyProviderFleetQuantity |
    ProduceVehicle | PauseVehicleProduction | ResumeVehicleProduction | SetVehicleProductionSettings |
    CreateTransportAllocation | UpdateTransportAllocation | SetTransportMovementConstraint |
    ClearTransportMovementConstraint |
    PauseTransportAllocation | ResumeTransportAllocation | DeleteTransportAllocation | RelocateFleet |
    RetireFleet | CancelFleetRetirement | SetFleetRetirementPriority |
    SetTargetStock | DeleteTargetStock | SetSupplyRoutingConstraint | ClearSupplyRoutingConstraint | AcceptContract |
    DeclineContract | CreateTradeOrder | UpdateTradeOrder | CancelTradeOrder | AdvanceTime
)
Query: TypeAlias = (
    GetCatalog | GetWorld | GetSurfaceMap | GetOperationalNode | GetFlowReport | GetDependencyAnalytics | GetBottlenecks | GetAttention | GetProjects |
    GetBuildOptions | GetLogistics | GetLogisticsSummary | GetMovementPlans | GetFleet |
    GetFleetRelocationPreview | GetTransportAllocations | GetCargoFlows | GetTransportAllocationOptions |
    GetResearch | GetScientificExplorations | GetSurveys | GetSurveyCampaignIntentPreview | GetContracts | GetMarket
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
