from __future__ import annotations
from typing import TypeAlias
from .app_contracts.catalog_views import (
    RequirementConditionRow, CapabilityRequirementRow, ServiceCapacityRequirementRow,
    SiteRequirementsDefinitionRow,
    OperationCapabilityDefinitionRow, ResourceDefinitionRow, FacilityDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, VehicleDefinitionRow, RouteDefinitionRow,
    TransportServiceDefinitionRow, ProcurementServiceDefinitionRow, CelestialBodyDefinitionRow, OperationalNodeDefinitionRow,
    CatalogView, OperationalNodeSummary, WorldView,
)
from .app_contracts.project_views import (
    ProjectResourceRow, BuildResourceOption, BuildOptionRow, FacilityUpgradeOption,
    BuildOptionsView, ProjectRow, ProjectsView,
)
from .app_contracts.location_views import (
    InventoryRow, ResourceClaimRow, StorageRow, FacilityRow, CapabilityRow, ServiceCapacityRow, IndustryRow,
    SurfaceInfrastructureLoadRow, SurfaceInfrastructureRow,
    EnvironmentFacetRow, ExtractionRow, ExtractionResourceRow, OperationalNodeView,
)
from .app_contracts.logistics_views import (
    InfrastructureRequirementRow, RouteEndpointRow, RouteModeRow, RouteRow, DirectionalCapacityRow, FleetPoolRow, TransportAllocationRow,
    FleetRelocationResourceRequirementRow, FleetRelocationRow, FleetReleaseRow, CargoFlowRow, ProcurementDeliveryRow, VehicleProductionOptionRow, VehicleProductionRow,
    ResourceDemandRow, LogisticsLaneRow, LogisticsView, TransportAllocationOptionRow,
    TransportAllocationOptionsView,
)
from .app_contracts.logistics_reports import (
    LogisticsSummaryView, RoutesView, FleetView, FleetRelocationPreviewView, TransportAllocationsView,
    CargoFlowsView, LogisticsLanesView,
)
from .app_contracts.progression_views import (
    ResearchProviderRow, ResearchPrototypeResourceRow, ResearchExperienceRow, ResearchKnowledgeRow,
    ResearchRow, ResearchView, ScientificExplorationFleetOptionRow,
    ScientificExplorationRow, ScientificExplorationsView, SurveyRow, SurveysView,
    ContractRow, ContractsView,
)
from .app_contracts.ui_reports import IssueRow, ResourceFlowRow, FlowReportView, BottlenecksView
from .app_contracts.analytics_views import DependencyMetricRow, DependencyAnalyticsView
from .app_contracts.surface_views import (
    SurfaceCellDevelopmentOption, SurfaceCellFoundationOption, SurfaceCellRow, SurfaceFacilityPlacementOption,
    SurfaceLocationTerritoryRow, SurfaceMapView, SurfaceResourceKnowledgeRow,
)
from .app_contracts.economy_views import (
    ExternalEconomyView, ExternalServicePolicyRow, FundsAuthorizationRow,
)

QueryResult: TypeAlias = (
    CatalogView | WorldView | SurfaceMapView | OperationalNodeView | FlowReportView | BottlenecksView |
    DependencyAnalyticsView |
    ProjectsView | BuildOptionsView | LogisticsView | LogisticsSummaryView |
    RoutesView | FleetView | FleetRelocationPreviewView | TransportAllocationsView | CargoFlowsView |
    LogisticsLanesView | TransportAllocationOptionsView | ResearchView |
    ScientificExplorationsView | SurveysView | ContractsView | ExternalEconomyView
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
