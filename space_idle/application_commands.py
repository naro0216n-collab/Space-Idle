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
    SetResearchPriority, SetResearchDemonstrationSite, StartSurvey,
    PauseSurvey, ResumeSurvey, SetSurveyPriority, StartScientificExploration, SetScientificExplorationPriority,
    PauseScientificExploration, ResumeScientificExploration,
    AssignExplorationFleet, UnassignExplorationFleet,
    CreateResearchProviderAssignment, ResizeResearchProviderAssignment,
    SetResearchProviderAssignmentPriority, PauseResearchProviderAssignment,
    ResumeResearchProviderAssignment, ReleaseResearchProviderAssignment, CreateSurveyProviderAssignment, ResizeSurveyProviderAssignment, ReleaseSurveyProviderAssignment,
)
from .app_contracts.transport import (
    ProduceVehicle, PauseVehicleProduction, ResumeVehicleProduction,
    SetVehicleProductionSettings, CreateTransportAllocation, UpdateTransportAllocation,
    ChangeTransportAllocationMode, PauseTransportAllocation, ResumeTransportAllocation,
    DeleteTransportAllocation, RelocateFleet, RetireFleet, CancelFleetRetirement, SetFleetRetirementPriority,
)
from .app_contracts.logistics import (
    SetTargetStock, DeleteTargetStock, CreateLogisticsPolicy, UpdateLogisticsPolicy, AssignLogisticsPolicy, UnassignLogisticsPolicy, SetGlobalLogisticsPolicy, DeleteLogisticsPolicy,
)
from .app_contracts.contracts import AcceptContract, DeclineContract
from .app_contracts.economy import (
    CancelTradeOrder, CreateTradeOrder, UpdateTradeOrder,
)
from .app_contracts.queries import (
    GetCatalog, GetWorld, GetSurfaceMap, GetOperationalNode, GetFlowReport, GetDependencyAnalytics, GetBottlenecks, GetProjects,
    GetBuildOptions, GetLogistics, GetLogisticsSummary, GetMovementPlans, GetFleet,
    GetFleetRelocationPreview, GetTransportAllocations, GetCargoFlows, GetTransportAllocationOptions,
    GetResearch, GetScientificExplorations, GetSurveys, GetContracts, GetMarket,
)

Command: TypeAlias = (
    PlanBuild | PlanFacilityUpgrade | PlanFacilityDecommission | PlanOperationalNodeFounding | CancelFounding | PauseFounding | ResumeFounding | SetFoundingPriority | DevelopSurfaceCell | CancelBuild | PauseBuild | ResumeBuild | SetProjectPriority |
    SetProjectProcurementPolicy |
    PauseFacility | ResumeFacility | SetFacilityProcess | SetFacilityActivityPriority | SetMaintenancePriority |
    SetTimeControl | StartResearch | PauseResearch | ResumeResearch | SetResearchPrototypeSite |
    SetResearchPriority | SetResearchDemonstrationSite | StartSurvey | PauseSurvey |
    ResumeSurvey | SetSurveyPriority | StartScientificExploration | SetScientificExplorationPriority | PauseScientificExploration |
    ResumeScientificExploration | AssignExplorationFleet | UnassignExplorationFleet |
    CreateResearchProviderAssignment | ResizeResearchProviderAssignment |
    SetResearchProviderAssignmentPriority | PauseResearchProviderAssignment |
    ResumeResearchProviderAssignment | ReleaseResearchProviderAssignment | CreateSurveyProviderAssignment | ResizeSurveyProviderAssignment | ReleaseSurveyProviderAssignment |
    ProduceVehicle | PauseVehicleProduction | ResumeVehicleProduction | SetVehicleProductionSettings |
    CreateTransportAllocation | UpdateTransportAllocation | ChangeTransportAllocationMode |
    PauseTransportAllocation | ResumeTransportAllocation | DeleteTransportAllocation | RelocateFleet |
    RetireFleet | CancelFleetRetirement | SetFleetRetirementPriority |
    SetTargetStock | DeleteTargetStock | CreateLogisticsPolicy | UpdateLogisticsPolicy | AssignLogisticsPolicy | UnassignLogisticsPolicy | SetGlobalLogisticsPolicy | DeleteLogisticsPolicy | AcceptContract |
    DeclineContract | CreateTradeOrder | UpdateTradeOrder | CancelTradeOrder | AdvanceTime
)
Query: TypeAlias = (
    GetCatalog | GetWorld | GetSurfaceMap | GetOperationalNode | GetFlowReport | GetDependencyAnalytics | GetBottlenecks | GetProjects |
    GetBuildOptions | GetLogistics | GetLogisticsSummary | GetMovementPlans | GetFleet |
    GetFleetRelocationPreview | GetTransportAllocations | GetCargoFlows | GetTransportAllocationOptions |
    GetResearch | GetScientificExplorations | GetSurveys | GetContracts | GetMarket
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
