from __future__ import annotations
from typing import TypeAlias
from .app_contracts.common import ApplicationError, CommandResult
from .app_contracts.construction import (
    PlanBuild, PlanFacilityUpgrade, FoundLocation, CancelFounding, PauseFounding, ResumeFounding, SetFoundingPriority, DevelopSurfaceCell, CancelBuild, PauseBuild, ResumeBuild, SetProjectPriority,
    SetProjectSourcingPolicy, SetProjectImportSource,
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
)
from .app_contracts.transport import (
    ProduceVehicle, PauseVehicleProduction, ResumeVehicleProduction,
    SetVehicleProductionSettings, CreateTransportAllocation, UpdateTransportAllocation,
    ChangeTransportAllocationMode, PauseTransportAllocation, ResumeTransportAllocation,
    DeleteTransportAllocation, RelocateFleet,
)
from .app_contracts.logistics import (
    SetTargetStock, DeleteTargetStock, SetSupplyPolicy, DeleteSupplyPolicy,
)
from .app_contracts.contracts import AcceptContract, DeclineContract
from .app_contracts.economy import (
    CreateExternalServicePolicy, DeleteExternalServicePolicy, SetExternalServicePolicy,
)
from .app_contracts.queries import (
    GetCatalog, GetWorld, GetSurfaceMap, GetOperationalNode, GetFlowReport, GetDependencyAnalytics, GetBottlenecks, GetProjects,
    GetBuildOptions, GetLogistics, GetLogisticsSummary, GetRoutes, GetFleet,
    GetFleetRelocationPreview, GetTransportAllocations, GetCargoFlows, GetTransportAllocationOptions,
    GetResearch, GetScientificExplorations, GetSurveys, GetContracts, GetExternalEconomy,
)

Command: TypeAlias = (
    PlanBuild | PlanFacilityUpgrade | FoundLocation | CancelFounding | PauseFounding | ResumeFounding | SetFoundingPriority | DevelopSurfaceCell | CancelBuild | PauseBuild | ResumeBuild | SetProjectPriority |
    SetProjectSourcingPolicy | SetProjectImportSource |
    PauseFacility | ResumeFacility | SetFacilityProcess | SetFacilityActivityPriority | SetMaintenancePriority |
    SetTimeControl | StartResearch | PauseResearch | ResumeResearch | SetResearchPrototypeSite |
    SetResearchPriority | SetResearchDemonstrationSite | StartSurvey | PauseSurvey |
    ResumeSurvey | SetSurveyPriority | StartScientificExploration | SetScientificExplorationPriority | PauseScientificExploration |
    ResumeScientificExploration | AssignExplorationFleet | UnassignExplorationFleet |
    ProduceVehicle | PauseVehicleProduction | ResumeVehicleProduction | SetVehicleProductionSettings |
    CreateTransportAllocation | UpdateTransportAllocation | ChangeTransportAllocationMode |
    PauseTransportAllocation | ResumeTransportAllocation | DeleteTransportAllocation | RelocateFleet |
    SetTargetStock | DeleteTargetStock | SetSupplyPolicy | DeleteSupplyPolicy | AcceptContract |
    DeclineContract | CreateExternalServicePolicy | SetExternalServicePolicy |
    DeleteExternalServicePolicy | AdvanceTime
)
Query: TypeAlias = (
    GetCatalog | GetWorld | GetSurfaceMap | GetOperationalNode | GetFlowReport | GetDependencyAnalytics | GetBottlenecks | GetProjects |
    GetBuildOptions | GetLogistics | GetLogisticsSummary | GetRoutes | GetFleet |
    GetFleetRelocationPreview | GetTransportAllocations | GetCargoFlows | GetTransportAllocationOptions |
    GetResearch | GetScientificExplorations | GetSurveys | GetContracts | GetExternalEconomy
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
