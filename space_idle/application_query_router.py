from __future__ import annotations

from .application_commands import (
    ApplicationError, GetBottlenecks, GetBuildOptions, GetCatalog, GetCargoFlows,
    GetContracts, GetFleet, GetFleetRelocationPreview, GetFlowReport, GetDependencyAnalytics, GetOperationalNode, GetLogistics,
    GetLogisticsSummary, GetProjects, GetResearch, GetMovementPlans,
    GetScientificExplorations, GetSurveys, GetTransportAllocations,
    GetTransportAllocationOptions, GetWorld, GetSurfaceMap, Query,
    GetMarket,
)
from .application_views import ProjectsView, QueryResult


class ApplicationQueryRouterMixin:
    def query_many(self, queries):
        """Project several Queries against one transient derived-state snapshot."""
        existing = getattr(self, "_query_projection_cache", None)
        if existing is not None:
            return {name: self.query(query) for name, query in queries.items()}
        self._query_projection_cache = {}
        try:
            with self._simulation.derived_projection_scope():
                return {name: self.query(query) for name, query in queries.items()}
        finally:
            self._query_projection_cache = None

    def query(self, query: Query) -> QueryResult:
        existing = getattr(self, "_query_projection_cache", None)
        root_query = existing is None
        if root_query:
            self._query_projection_cache = {}
        try:
            with self._simulation.derived_projection_scope():
                try:
                    return self._query(query)
                except ApplicationError:
                    raise
                except KeyError as exc:
                    raise ApplicationError("not_found", str(exc)) from exc
                except ValueError as exc:
                    raise ApplicationError("invalid_query", str(exc)) from exc
                except RuntimeError as exc:
                    raise ApplicationError("state_conflict", str(exc)) from exc
        finally:
            if root_query:
                self._query_projection_cache = None

    def _query(self, query: Query) -> QueryResult:
        if isinstance(query, GetCatalog):
            return self._catalog_view()
        if isinstance(query, GetWorld):
            return self._world_view()
        if isinstance(query, GetSurfaceMap):
            from .shared import CelestialBodyId
            body_id = CelestialBodyId(query.body_id)
            if body_id not in self._simulation.graph.bodies:
                raise KeyError(body_id)
            return self._surface_map_view(body_id)
        if isinstance(query, GetOperationalNode):
            return self._operational_node_view(self._require_operational_node(query.operational_node_id))
        if isinstance(query, GetFlowReport):
            return self._flow_report_view(self._require_operational_node(query.operational_node_id))
        if isinstance(query, GetDependencyAnalytics):
            return self._dependency_analytics_view(query)
        if isinstance(query, GetBottlenecks):
            return self._bottlenecks_view(None if query.operational_node_id is None else self._require_operational_node(query.operational_node_id))
        if isinstance(query, GetProjects):
            rows = self._project_rows(None if query.operational_node_id is None else self._require_operational_node(query.operational_node_id))
            return ProjectsView(rows)
        if isinstance(query, GetBuildOptions):
            return self._build_options_view(self._require_operational_node(query.operational_node_id))
        if isinstance(query, GetLogistics):
            return self._logistics_view()
        if isinstance(query, GetLogisticsSummary):
            return self._logistics_summary_view()
        if isinstance(query, GetMovementPlans):
            if query.origin_id is not None:
                self._require_operational_node(query.origin_id)
            if query.destination_id is not None:
                self._require_operational_node(query.destination_id)
            return self._movement_plans_view(query)
        if isinstance(query, GetFleet):
            if query.operational_node_id is not None:
                self._require_operational_node(query.operational_node_id)
            if query.vehicle_definition_id is not None and query.vehicle_definition_id not in {str(value.id) for value in self._simulation.transport.vehicle_definitions()}:
                raise KeyError(query.vehicle_definition_id)
            return self._fleet_view(query)
        if isinstance(query, GetFleetRelocationPreview):
            self._require_operational_node(query.source_id)
            self._require_operational_node(query.destination_id)
            if query.vehicle_definition_id not in {
                str(value.id) for value in self._simulation.transport.vehicle_definitions()
            }:
                raise KeyError(query.vehicle_definition_id)
            return self._fleet_relocation_preview_view(query)
        if isinstance(query, GetTransportAllocations):
            return self._transport_allocations_view()
        if isinstance(query, GetCargoFlows):
            return self._cargo_flows_view()
        if isinstance(query, GetTransportAllocationOptions):
            return self._transport_allocation_options_view(
                self._require_operational_node(query.source_id),
                self._require_operational_node(query.destination_id),
            )
        if isinstance(query, GetResearch):
            return self._research_view()
        if isinstance(query, GetScientificExplorations):
            return self._scientific_explorations_view()
        if isinstance(query, GetSurveys):
            return self._surveys_view(
                None if query.provider_operational_node_id is None else self._require_operational_node(query.provider_operational_node_id)
            )
        if isinstance(query, GetContracts):
            return self._contracts_view()
        if isinstance(query, GetMarket):
            return self._market_view()
        raise TypeError(f"unsupported query: {type(query).__name__}")
