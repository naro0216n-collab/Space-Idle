from __future__ import annotations
from typing import TypeAlias
from .app_contracts.common import ApplicationError, CommandResult
from .app_contracts.construction import (
    PlanBuild, PlanFacilityUpgrade, CancelBuild, PauseBuild, ResumeBuild, SetProjectPriority,
    SetProjectSourcingPolicy, SetConstructionWeight, SetProjectImportSource,
    SetProjectLocalFraction, SetProjectLocalMaterial,
)
from .app_contracts.operations import PauseFacility, ResumeFacility, SetFacilityProcess, SetPowerPriority, AdvanceTime
from .app_contracts.progression import (
    StartResearch, PauseResearch, ResumeResearch, SetResearchPrototypeSite,
    FundResearchPrototype, SetResearchDemonstrationSite, StartSurvey,
    PauseSurvey, ResumeSurvey, SetSurveyAllocation,
)
from .app_contracts.transport import (
    DispatchVehicle, RefuelVehicle, ProduceVehicle, SubmitCargo, CreateLogisticsLane,
    UpdateLogisticsLane, PauseLogisticsLane, ResumeLogisticsLane, DeleteLogisticsLane,
)
from .app_contracts.contracts import AcceptContract, DispatchContractCargo, DeclineContract
from .app_contracts.queries import (
    GetCatalog, GetWorld, GetLocation, GetFlowReport, GetBottlenecks, GetProjects, GetBuildOptions, GetLogistics,
    GetLogisticsSummary, GetRoutes, GetVehicles, GetCargoOrders, GetLogisticsLanes, GetTransportMissions,
    GetTransportPlans, GetResearch, GetSurveys, GetContracts,
)

Command: TypeAlias = (
    PlanBuild | PlanFacilityUpgrade | CancelBuild | PauseBuild | ResumeBuild | SetProjectPriority |
    SetProjectSourcingPolicy | SetConstructionWeight | SetProjectImportSource |
    SetProjectLocalFraction | SetProjectLocalMaterial |
    PauseFacility | ResumeFacility | SetFacilityProcess | SetPowerPriority |
    StartResearch | PauseResearch | ResumeResearch | SetResearchPrototypeSite |
    FundResearchPrototype | SetResearchDemonstrationSite | StartSurvey | PauseSurvey |
    ResumeSurvey | SetSurveyAllocation | DispatchVehicle | RefuelVehicle | ProduceVehicle |
    SubmitCargo | CreateLogisticsLane | UpdateLogisticsLane | PauseLogisticsLane |
    ResumeLogisticsLane | DeleteLogisticsLane | AcceptContract | DispatchContractCargo |
    DeclineContract | AdvanceTime
)
Query: TypeAlias = GetCatalog | GetWorld | GetLocation | GetFlowReport | GetBottlenecks | GetProjects | GetBuildOptions | GetLogistics | GetLogisticsSummary | GetRoutes | GetVehicles | GetCargoOrders | GetLogisticsLanes | GetTransportMissions | GetTransportPlans | GetResearch | GetSurveys | GetContracts

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
