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
    ProjectComponentRow, BuildComponentOption, BuildOptionRow, BuildOptionsView,
    ProjectRow, ProjectsView,
)
from .app_contracts.location_views import (
    InventoryRow, StorageRow, FacilityRow, CapabilityRow, IndustryRow,
    EnvironmentFacetRow, ExtractionRow, LocationView,
)
from .app_contracts.logistics_views import (
    RouteModeRow, RouteRow, VehicleRow, CargoOrderRow, LogisticsRuleRow,
    TransportMissionRow, LogisticsView, TransportPathOptionRow, TransportPlansView,
)
from .app_contracts.logistics_reports import (
    LogisticsSummaryView, RoutesView, VehiclesView, CargoOrdersView,
    LogisticsRulesView, TransportMissionsView,
)
from .app_contracts.progression_views import (
    ResearchProviderRow, ResearchRow, ResearchView, SurveyRow, SurveysView, ContractRow, ContractsView,
)
from .app_contracts.ui_reports import IssueRow, ResourceFlowRow, FlowReportView, BottlenecksView

QueryResult: TypeAlias = (
    CatalogView | WorldView | LocationView | FlowReportView | BottlenecksView |
    ProjectsView | BuildOptionsView | LogisticsView | LogisticsSummaryView |
    RoutesView | VehiclesView | CargoOrdersView | LogisticsRulesView |
    TransportMissionsView | TransportPlansView | ResearchView | SurveysView |
    ContractsView
)

__all__ = [
    "RequirementConditionRow", "CapabilityRequirementRow", "SiteRequirementsDefinitionRow",
    "OperationCapabilityDefinitionRow", "ResourceDefinitionRow", "FacilityDefinitionRow",
    "ProcessDefinitionRow", "ResearchDefinitionRow", "VehicleDefinitionRow", "RouteDefinitionRow",
    "TransportServiceDefinitionRow", "CelestialBodyDefinitionRow", "LocationDefinitionRow",
    "CatalogView", "LocationSummary", "WorldView",
    "ProjectComponentRow", "BuildComponentOption", "BuildOptionRow", "BuildOptionsView", "ProjectRow", "ProjectsView",
    "InventoryRow", "StorageRow", "FacilityRow", "CapabilityRow", "IndustryRow", "EnvironmentFacetRow", "ExtractionRow", "LocationView",
    "RouteModeRow", "RouteRow", "VehicleRow", "CargoOrderRow", "LogisticsRuleRow", "TransportMissionRow", "LogisticsView", "TransportPathOptionRow", "TransportPlansView",
    "LogisticsSummaryView", "RoutesView", "VehiclesView", "CargoOrdersView", "LogisticsRulesView", "TransportMissionsView",
    "IssueRow", "ResourceFlowRow", "FlowReportView", "BottlenecksView",
    "ResearchProviderRow", "ResearchRow", "ResearchView", "SurveyRow", "SurveysView", "ContractRow", "ContractsView", "QueryResult",
]
