from __future__ import annotations

from .application_commands import (
    ApplicationError, GetBottlenecks, GetBuildOptions, GetCargoOrders,
    GetCatalog, GetContracts, GetFlowReport, GetLocation, GetLogistics,
    GetLogisticsLanes, GetLogisticsSummary, GetProjects, GetResearch, GetRoutes,
    GetSurveys, GetTransportMissions, GetTransportPlans, GetVehicles, GetWorld,
    Query,
)
from .application_views import ProjectsView, QueryResult


class ApplicationQueryRouterMixin:
    def query(self, query: Query) -> QueryResult:
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

    def _query(self, query: Query) -> QueryResult:
        if isinstance(query, GetCatalog):
            return self._catalog_view()
        if isinstance(query, GetWorld):
            return self._world_view()
        if isinstance(query, GetLocation):
            return self._location_view(self._require_location(query.location_id))
        if isinstance(query, GetFlowReport):
            return self._flow_report_view(self._require_location(query.location_id))
        if isinstance(query, GetBottlenecks):
            return self._bottlenecks_view(None if query.location_id is None else self._require_location(query.location_id))
        if isinstance(query, GetProjects):
            rows = self._project_rows(None if query.location_id is None else self._require_location(query.location_id))
            return ProjectsView(rows)
        if isinstance(query, GetBuildOptions):
            return self._build_options_view(self._require_location(query.location_id))
        if isinstance(query, GetLogistics):
            return self._logistics_view()
        if isinstance(query, GetLogisticsSummary):
            return self._logistics_summary_view()
        if isinstance(query, GetRoutes):
            if query.origin_id is not None:
                self._require_location(query.origin_id)
            if query.destination_id is not None:
                self._require_location(query.destination_id)
            return self._routes_view(query)
        if isinstance(query, GetVehicles):
            if query.location_id is not None:
                self._require_location(query.location_id)
            return self._vehicles_view(query)
        if isinstance(query, GetCargoOrders):
            return self._cargo_orders_view()
        if isinstance(query, GetLogisticsLanes):
            return self._logistics_lanes_view()
        if isinstance(query, GetTransportMissions):
            return self._transport_missions_view()
        if isinstance(query, GetTransportPlans):
            return self._transport_plans_view(
                self._require_location(query.source_id),
                self._require_location(query.destination_id),
            )
        if isinstance(query, GetResearch):
            return self._research_view()
        if isinstance(query, GetSurveys):
            return self._surveys_view(
                None if query.location_id is None else self._require_location(query.location_id)
            )
        if isinstance(query, GetContracts):
            return self._contracts_view()
        raise TypeError(f"unsupported query: {type(query).__name__}")
