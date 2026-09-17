from __future__ import annotations

from .application_commands import (
    AcceptContract, AdvanceTime, ApplicationError, CancelBuild, ChangeTransportAllocationMode,
    CreateTransportAllocation, DeclineContract,
    DeleteTransportAllocation, SetResearchPriority, GetBottlenecks,
    GetBuildOptions, GetCatalog, GetCargoFlows, GetContracts, GetFleet, GetFleetRelocationPreview, GetFlowReport, GetDependencyAnalytics,
    GetOperationalNode, GetLogistics, GetLogisticsSummary, GetProjects,
    GetResearch, GetMovementPlans, GetScientificExplorations, GetSurveys, GetTransportAllocations,
    GetTransportAllocationOptions, GetWorld, GetSurfaceMap, PauseBuild, PauseFacility,
    PauseResearch, PauseScientificExploration, PauseSurvey, PauseTransportAllocation,
    PauseVehicleProduction, PlanBuild, PlanFacilityUpgrade, FoundLocation, CancelFounding, PauseFounding, ResumeFounding, SetFoundingPriority, DevelopSurfaceCell, ProduceVehicle, RelocateFleet, RetireFleet, CancelFleetRetirement, SetFleetRetirementPriority,
    ResumeBuild, ResumeFacility, ResumeResearch,
    ResumeScientificExploration, ResumeSurvey, ResumeTransportAllocation,
    ResumeVehicleProduction, SetFacilityProcess, SetMaintenancePriority,
    SetFacilityActivityPriority, SetProjectPriority, SetProjectProcurementPolicy,
    SetResearchDemonstrationSite, SetResearchPrototypeSite, SetSurveyPriority,
    SetTimeControl, SetVehicleProductionSettings, StartResearch, StartScientificExploration, SetScientificExplorationPriority,
    StartSurvey, UnassignExplorationFleet, UpdateTransportAllocation, AssignExplorationFleet, CreateResearchProviderAssignment, ResizeResearchProviderAssignment, SetResearchProviderAssignmentPriority, PauseResearchProviderAssignment, ResumeResearchProviderAssignment, ReleaseResearchProviderAssignment, CreateTradeOrder,
    UpdateTradeOrder, CancelTradeOrder, GetMarket,
    SetTargetStock, DeleteTargetStock, CreateLogisticsPolicy, UpdateLogisticsPolicy, AssignLogisticsPolicy, UnassignLogisticsPolicy, SetGlobalLogisticsPolicy, DeleteLogisticsPolicy,
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
        self._query_projection_cache = None

    @property
    def content_id(self) -> str:
        return self._simulation.content_id

    @property
    def world_definition_id(self) -> str:
        return self._simulation.world_definition_id

    @property
    def scenario_id(self) -> str:
        return self._simulation.scenario_id

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
