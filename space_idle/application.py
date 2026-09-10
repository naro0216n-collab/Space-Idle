from __future__ import annotations

from .application_commands import (
    AcceptContract, AdvanceTime, ApplicationError, CancelBuild, CreateLogisticsLane,
    DeclineContract, DeleteLogisticsLane, DispatchContractCargo, DispatchVehicle,
    FundResearchPrototype, GetBuildOptions, GetCatalog, GetContracts, GetLocation,
    GetFlowReport, GetBottlenecks, GetLogistics, GetLogisticsSummary, GetRoutes,
    GetVehicles, GetCargoOrders, GetLogisticsLanes, GetTransportMissions,
    GetProjects, GetResearch, GetScientificExplorations, GetSurveys, GetTransportPlans, GetWorld,
    PauseBuild, PauseFacility, PauseLogisticsLane, PauseResearch, PauseSurvey, PauseScientificExploration,
    PlanBuild, PlanFacilityUpgrade, ProduceVehicle, PauseVehicleProduction, ResumeVehicleProduction, RefuelVehicle, ResumeBuild,
    ResumeFacility, ResumeLogisticsLane, ResumeResearch, ResumeSurvey, ResumeScientificExploration,
    SetConstructionWeight, SetFacilityProcess, SetPowerPriority, SetMaintenancePriority,
    SetProjectImportSource,
    SetProjectPriority, SetProjectSourcingPolicy, SetResearchPrototypeSite,
    SetResearchDemonstrationSite, SetSurveyAllocation, StartResearch, StartSurvey, StartScientificExploration, AssignExplorationVehicle, UnassignExplorationVehicle,
    SubmitCargo, UpdateLogisticsLane,
)
from .application_command_handlers import ApplicationCommandMixin
from .application_query_projectors import ApplicationQueryMixin
from .catalog import GameCatalog
from .simulation import OfflineProgressPolicy, OfflineProgressResult, Simulation


class GameApplication(ApplicationCommandMixin, ApplicationQueryMixin):
    def __init__(self, simulation: Simulation, catalog: GameCatalog):
        self._simulation = simulation
        self._catalog = catalog

    @property
    def content_id(self) -> str:
        return self._simulation.content_id

    def advance_offline(
        self, elapsed_real_seconds: float, policy: OfflineProgressPolicy
    ) -> OfflineProgressResult:
        return self._simulation.advance_offline(elapsed_real_seconds, policy)
