from __future__ import annotations

from .application_commands import (
    AcceptContract, AdvanceTime, ApplicationError, CancelBuild, ChangeTransportAllocationMode,
    CreateLogisticsLane, CreateTransportAllocation, DeclineContract, DeleteLogisticsLane,
    DeleteTransportAllocation, FundResearchPrototype, GetBottlenecks,
    GetBuildOptions, GetCatalog, GetCargoFlows, GetContracts, GetFleet, GetFlowReport,
    GetLocation, GetLogistics, GetLogisticsLanes, GetLogisticsSummary, GetProjects,
    GetResearch, GetRoutes, GetScientificExplorations, GetSurveys, GetTransportAllocations,
    GetTransportAllocationOptions, GetWorld, PauseBuild, PauseFacility, PauseLogisticsLane,
    PauseResearch, PauseScientificExploration, PauseSurvey, PauseTransportAllocation,
    PauseVehicleProduction, PlanBuild, PlanFacilityUpgrade, ProduceVehicle, RelocateFleet,
    ResumeBuild, ResumeFacility, ResumeLogisticsLane, ResumeResearch,
    ResumeScientificExploration, ResumeSurvey, ResumeTransportAllocation,
    ResumeVehicleProduction, SetConstructionWeight, SetFacilityProcess, SetMaintenancePriority,
    SetPowerPriority, SetProjectImportSource, SetProjectPriority, SetProjectSourcingPolicy,
    SetResearchDemonstrationSite, SetResearchPrototypeSite, SetSurveyAllocation,
    SetTimeControl, SetVehicleProductionSettings, StartResearch, StartScientificExploration,
    StartSurvey, UnassignExplorationFleet, UpdateLogisticsLane,
    UpdateTransportAllocation, AssignExplorationFleet,
)

from .application_command_handlers import ApplicationCommandMixin
from .application_query_projectors import ApplicationQueryMixin
from .catalog import GameCatalog
from .simulation import OfflineProgressPolicy, OfflineProgressResult, Simulation


class GameApplication(ApplicationCommandMixin, ApplicationQueryMixin):
    def __init__(self, simulation: Simulation, catalog: GameCatalog):
        self._simulation = simulation
        self._catalog = catalog
        self._time_paused = False
        self._time_speed_multiplier = 1.0

    @property
    def content_id(self) -> str:
        return self._simulation.content_id

    @property
    def time_paused(self) -> bool:
        return self._time_paused

    @property
    def time_speed_multiplier(self) -> float:
        return self._time_speed_multiplier

    def advance_offline(
        self, elapsed_real_seconds: float, policy: OfflineProgressPolicy
    ) -> OfflineProgressResult:
        return self._simulation.advance_offline(elapsed_real_seconds, policy)
