from __future__ import annotations

from .application_commands import ApplicationError, Command, CommandResult
from .shared import DefinitionId, SpatialNodeId


class ApplicationCommandSupportMixin:
    def _require_operational_node(self, operational_node_id: str) -> SpatialNodeId:
        value = SpatialNodeId(operational_node_id)
        if not self._simulation.graph.has_operational_node(value):
            raise KeyError(value)
        return value

    def _require_resource(self, resource_id: str) -> DefinitionId:
        value = DefinitionId(resource_id)
        if value not in self._catalog.resources:
            raise KeyError(value)
        return value

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
