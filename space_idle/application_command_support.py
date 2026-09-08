from __future__ import annotations

from .application_commands import ApplicationError, Command, CommandResult
from .shared import DefinitionId, RouteId, SpatialNodeId


class ApplicationCommandSupportMixin:
    def _require_location(self, location_id: str) -> SpatialNodeId:
        value = SpatialNodeId(location_id)
        if value not in self._simulation.graph.nodes:
            raise KeyError(value)
        return value

    def _require_resource(self, resource_id: str) -> DefinitionId:
        value = DefinitionId(resource_id)
        if value not in self._catalog.resources:
            raise KeyError(value)
        return value

    def _route_mode_map(self, rows: tuple[tuple[str, str], ...]) -> dict[RouteId, str]:
        result: dict[RouteId, str] = {}
        for route_id_raw, mode_id in rows:
            route_id = RouteId(route_id_raw)
            if route_id not in self._simulation.logistics.routes:
                raise KeyError(route_id)
            if route_id in result:
                raise ValueError(f"duplicate transport mode selection for route: {route_id}")
            if not mode_id:
                raise ValueError("transport mode id must not be empty")
            result[route_id] = mode_id
        return result

    def execute(self, command: Command) -> CommandResult:
        try:
            return self._execute(command)
        except ApplicationError:
            raise
        except KeyError as exc:
            raise ApplicationError("not_found", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationError("invalid_command", str(exc)) from exc
        except RuntimeError as exc:
            raise ApplicationError("state_conflict", str(exc)) from exc
