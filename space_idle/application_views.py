from __future__ import annotations
from typing import TypeAlias
from .app_contracts.catalog_views import (
    RequirementConditionRow, CapabilityRequirementRow,
    SiteRequirementsDefinitionRow,
    OperationCapabilityDefinitionRow, ResourceDefinitionRow, FacilityDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, ResearchStageDefinitionRow, VehicleDefinitionRow, MovementPlanDefinitionRow,
    CelestialBodyDefinitionRow, OperationalNodeDefinitionRow,
    CatalogView, OperationalNodeSummary, WorldView,
)
from .app_contracts.project_views import (
    ProjectResourceRow, BuildResourceOption, BuildOptionRow, FacilityUpgradeOption, FacilityUpgradeDifferenceRow,
    BuildOptionsView, ProjectKnowledgeRequirementRow, ProjectRow, ProjectsView,
)
from .app_contracts.location_views import (
    InventoryRow, ResourceAllocationRow, StorageRow, FacilityRow, CapabilityRow, ServiceCapacityRow, IndustryProcessOptionRow, IndustryRow,
    SurfaceInfrastructureLoadRow, SurfaceInfrastructureRow,
    EnvironmentFacetRow, LocationEnvironmentSummaryRow, SurfaceAccessAnchorRow,
    SurfaceLocationDecisionRow, ExtractionRow, ExtractionResourceRow, OperationalNodeView,
    PopulationView, ExternalPopulationSourceRow,
)
from .app_contracts.logistics_views import (
    InfrastructureRequirementRow, MovementEndpointRow, MovementServiceModeRow, MovementPlanRow, DirectionalCapacityRow, FleetPoolRow, FleetCommitmentRow, TransportAllocationRow,
    FleetRelocationResourceRequirementRow, FleetRelocationRow, FleetReleaseRow, FleetRetirementRow, CargoFlowRow, VehicleProductionOptionRow, VehicleProductionRow,
    SupplyRequirementRow, SupplyRoutingConstraintRow, TargetStockRow, TargetStockPresetRow, TargetStockOptionsView, LogisticsView, TransportAllocationOptionRow,
    TransportAllocationOptionsView, TransportAllocationPreviewView, TransportCapacityPresetRow,
)
from .app_contracts.logistics_reports import (
    LogisticsSummaryView, MovementPlansView, FleetView, FleetRelocationPreviewView, TransportAllocationsView,
    CargoFlowsView,
)
from .app_contracts.progression_views import (
    ResearchProviderRow, ResearchProviderFleetRow, ResearchPrototypeResourceRow, ResearchExperienceRow, ResearchKnowledgeRow,
    ResearchStageRow, ResearchUnlockRow, ResearchRow, ResearchView, ScientificExplorationFleetOptionRow,
    ScientificExplorationRow, ScientificExplorationsView, SurveyProviderFleetRow, SurveyCandidateRow, SurveyCampaignTargetRow, SurveyCampaignRow, SurveyRow, SurveyCampaignIntentPreviewView, SurveysView,
    ContractRow, ContractsView,
)
from .app_contracts.ui_reports import DecisionContextTarget, IssueRow, ResourceFlowRow, FlowReportView, BottlenecksView
from .app_contracts.analytics_views import (
    CurrentDependencyMetricRow, ForecastDependencyMetricRow,
    CurrentServiceDependencyMetricRow, ForecastServiceDependencyMetricRow,
    DependencyAnalyticsView, DetailedForecastInventoryRow, DetailedForecastInventoryRangeRow, DetailedForecastImpactRow,
    DetailedForecastSupplyGapRow, DetailedForecastArrivalWaitingRow,
    DetailedForecastLogisticsRow, DetailedForecastView,
)
from .app_contracts.surface_views import (
    SurfaceCellDevelopmentOption, FoundingOption, NonSurfaceFoundingContextRow, NonSurfaceFoundingView, SurfaceCellRow, SurfaceFacilityPlacementOption,
    SurfaceLocationTerritoryRow, SurfaceMapView, SurfaceResourceKnowledgeRow,
)
from .app_contracts.economy_views import (
    BuyCommitmentRow, MarketInterfaceRow, MarketOfferRow, MarketView, TradeOrderRow,
)
from .app_contracts.passenger_views import (
    PassengerDispatchOptionRow, PassengerTransferPreviewView,
    PassengerTransferRow, PassengerTransfersView,
)

QueryResult: TypeAlias = (
    CatalogView | WorldView | SurfaceMapView | NonSurfaceFoundingView | OperationalNodeView | FlowReportView | BottlenecksView |
    DependencyAnalyticsView | DetailedForecastView |
    ProjectsView | BuildOptionsView | LogisticsView | LogisticsSummaryView |
    MovementPlansView | FleetView | FleetRelocationPreviewView | TransportAllocationsView | CargoFlowsView |
    TransportAllocationOptionsView | TransportAllocationPreviewView | TargetStockOptionsView | ResearchView |
    ScientificExplorationsView | SurveysView | SurveyCampaignIntentPreviewView | ContractsView | MarketView |
    PassengerTransferPreviewView | PassengerTransfersView
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
