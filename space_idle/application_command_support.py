from __future__ import annotations

from .application_commands import ApplicationError, Command, CommandResult
from .shared import DefinitionId, SpatialNodeId


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

    def execute(self, command: Command) -> CommandResult:
        try:
            result = self._execute(command)
            self._simulation.refresh_resource_claims()
            return result
        except ApplicationError:
            raise
        except KeyError as exc:
            raise ApplicationError("not_found", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationError("invalid_command", str(exc)) from exc
        except RuntimeError as exc:
            raise ApplicationError("state_conflict", str(exc)) from exc
