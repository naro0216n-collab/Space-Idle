from __future__ import annotations
from typing import TypeAlias
from .app_contracts.catalog_views import (
    RequirementConditionRow, CapabilityRequirementRow, SiteRequirementsDefinitionRow,
    OperationCapabilityDefinitionRow, ResourceDefinitionRow, FacilityDefinitionRow,
    ProcessDefinitionRow, ResearchDefinitionRow, VehicleDefinitionRow, RouteDefinitionRow,
    TransportServiceDefinitionRow, CelestialBodyDefinitionRow, LocationDefinitionRow,
    CatalogView, LocationSummary, WorldView,
)
from .app_contracts.project_views import (
    ProjectResourceRow, BuildResourceOption, BuildOptionRow, FacilityUpgradeOption,
    BuildOptionsView, ProjectRow, ProjectsView,
)
from .app_contracts.location_views import (
    InventoryRow, StorageRow, FacilityRow, CapabilityRow, IndustryRow,
    EnvironmentFacetRow, ExtractionRow, ExtractionResourceRow, LocationView,
)
from .app_contracts.logistics_views import (
    InfrastructureRequirementRow, RouteModeRow, RouteRow, DirectionalCapacityRow, FleetPoolRow, TransportAllocationRow,
    FleetRelocationResourceRequirementRow, FleetRelocationRow, FleetReleaseRow, CargoFlowRow, VehicleProductionOptionRow, VehicleProductionRow,
    ResourceDemandRow, LogisticsLaneRow, LogisticsView, TransportAllocationOptionRow,
    TransportAllocationOptionsView,
)
from .app_contracts.logistics_reports import (
    LogisticsSummaryView, RoutesView, FleetView, FleetRelocationPreviewView, TransportAllocationsView,
    CargoFlowsView, LogisticsLanesView,
)
from .app_contracts.progression_views import (
    ResearchProviderRow, ResearchRow, ResearchView, ScientificExplorationFleetOptionRow,
    ScientificExplorationRow, ScientificExplorationsView, SurveyRow, SurveysView,
    ContractRow, ContractsView,
)
from .app_contracts.ui_reports import IssueRow, ResourceFlowRow, FlowReportView, BottlenecksView
from .app_contracts.surface_views import (
    SurfaceCellRow, SurfaceLocationTerritoryRow, SurfaceMapView, SurfaceResourceKnowledgeRow,
)

QueryResult: TypeAlias = (
    CatalogView | WorldView | SurfaceMapView | LocationView | FlowReportView | BottlenecksView |
    ProjectsView | BuildOptionsView | LogisticsView | LogisticsSummaryView |
    RoutesView | FleetView | FleetRelocationPreviewView | TransportAllocationsView | CargoFlowsView |
    LogisticsLanesView | TransportAllocationOptionsView | ResearchView |
    ScientificExplorationsView | SurveysView | ContractsView
)

__all__ = [name for name in globals() if not name.startswith('_') and name not in {'TypeAlias'}]
