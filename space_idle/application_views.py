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
    ProjectResourceRow, BuildResourceOption, BuildOptionRow, FacilityUpgradeOption,
    BuildOptionsView, ProjectKnowledgeRequirementRow, ProjectRow, ProjectsView,
)
from .app_contracts.location_views import (
    InventoryRow, ResourceAllocationRow, StorageRow, FacilityRow, CapabilityRow, ServiceCapacityRow, IndustryRow,
    SurfaceInfrastructureLoadRow, SurfaceInfrastructureRow,
    EnvironmentFacetRow, LocationEnvironmentSummaryRow, SurfaceAccessAnchorRow,
    SurfaceLocationDecisionRow, ExtractionRow, ExtractionResourceRow, OperationalNodeView,
)
from .app_contracts.logistics_views import (
    InfrastructureRequirementRow, MovementEndpointRow, MovementServiceModeRow, MovementPlanRow, DirectionalCapacityRow, FleetPoolRow, FleetCommitmentRow, TransportAllocationRow,
    FleetRelocationResourceRequirementRow, FleetRelocationRow, FleetReleaseRow, FleetRetirementRow, CargoFlowRow, VehicleProductionOptionRow, VehicleProductionRow,
    SupplyRequirementRow, SupplyRoutingConstraintRow, TargetStockRow, LogisticsView, TransportAllocationOptionRow,
    TransportAllocationOptionsView,
)
from .app_contracts.logistics_reports import (
    LogisticsSummaryView, MovementPlansView, FleetView, FleetRelocationPreviewView, TransportAllocationsView,
    CargoFlowsView,
)
from .app_contracts.progression_views import (
    ResearchProviderRow, ResearchProviderFleetRow, ResearchPrototypeResourceRow, ResearchExperienceRow, ResearchKnowledgeRow,
    ResearchStageRow, ResearchRow, ResearchView, ScientificExplorationFleetOptionRow,
    ScientificExplorationRow, ScientificExplorationsView, SurveyProviderFleetRow, SurveyCandidateRow, SurveyCampaignTargetRow, SurveyCampaignRow, SurveyRow, SurveyCampaignIntentPreviewView, SurveysView,
    ContractRow, ContractsView,
)
from .app_contracts.ui_reports import DecisionContextTarget, IssueRow, ResourceFlowRow, FlowReportView, BottlenecksView
from .app_contracts.analytics_views import CurrentDependencyMetricRow, ForecastDependencyMetricRow, DependencyAnalyticsView
from .app_contracts.surface_views import (
    SurfaceCellDevelopmentOption, SurfaceCellFoundationOption, SurfaceCellRow, SurfaceFacilityPlacementOption,
    SurfaceLocationTerritoryRow, SurfaceMapView, SurfaceResourceKnowledgeRow,
)
from .app_contracts.economy_views import (
    BuyCommitmentRow, MarketInterfaceRow, MarketOfferRow, MarketView, TradeOrderRow,
)

QueryResult: TypeAlias = (
    CatalogView | WorldView | SurfaceMapView | OperationalNodeView | FlowReportView | BottlenecksView |
    DependencyAnalyticsView |
    ProjectsView | BuildOptionsView | LogisticsView | LogisticsSummaryView |
    MovementPlansView | FleetView | FleetRelocationPreviewView | TransportAllocationsView | CargoFlowsView |
    TransportAllocationOptionsView | ResearchView |
    ScientificExplorationsView | SurveysView | SurveyCampaignIntentPreviewView | ContractsView | MarketView
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
