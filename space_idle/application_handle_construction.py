from __future__ import annotations

from .application_commands import (
    CancelBuild,
    Command,
    CommandResult,
    PauseBuild,
    PlanBuild,
    PlanFacilityUpgrade,
    FoundLocation,
    DevelopSurfaceCell,
    ResumeBuild,
    SetConstructionWeight,
    SetProjectImportSource,
    SetProjectPriority,
    SetProjectSourcingPolicy,
)
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId


class ConstructionCommandHandlerMixin:
    def _handle_construction_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, PlanBuild):
            pid = sim.projects.plan_build(
                DefinitionId(command.facility_id),
                self._require_location(command.location_id),
                command.priority,
                command.sourcing_policy,
                day=sim.day,
                import_source_id=(
                    None if command.import_source_id is None else self._require_location(command.import_source_id)
                ),
                site_cell_id=None if command.site_cell_id is None else SurfaceCellId(command.site_cell_id),
            )
            return CommandResult(str(pid))
        if isinstance(command, PlanFacilityUpgrade):
            pid = sim.projects.plan_upgrade(
                EntityId(command.facility_id),
                command.priority,
                command.sourcing_policy,
                day=sim.day,
                import_source_id=(
                    None if command.import_source_id is None else self._require_location(command.import_source_id)
                ),
            )
            return CommandResult(str(pid))
        if isinstance(command, FoundLocation):
            pid = sim.projects.plan_location_founding(
                self._require_location(command.provider_location_id),
                SpatialNodeId(command.new_location_id),
                command.display_name,
                CelestialBodyId(command.body_id),
                SurfaceCellId(command.core_cell_id),
                command.priority,
                command.sourcing_policy,
                day=sim.day,
                import_source_id=(None if command.import_source_id is None else self._require_location(command.import_source_id)),
            )
            return CommandResult(str(pid))
        if isinstance(command, DevelopSurfaceCell):
            pid = sim.projects.plan_surface_cell_development(
                self._require_location(command.location_id),
                SurfaceCellId(command.cell_id),
                command.priority,
                command.sourcing_policy,
                day=sim.day,
                import_source_id=(None if command.import_source_id is None else self._require_location(command.import_source_id)),
            )
            return CommandResult(str(pid))
        if isinstance(command, CancelBuild):
            sim.projects.cancel(ProjectId(command.project_id)); return CommandResult()
        if isinstance(command, PauseBuild):
            sim.projects.pause(ProjectId(command.project_id), sim.day); return CommandResult()
        if isinstance(command, ResumeBuild):
            sim.projects.resume(ProjectId(command.project_id), sim.day); return CommandResult()
        if isinstance(command, SetProjectPriority):
            sim.projects.set_priority(ProjectId(command.project_id), command.priority); return CommandResult()
        if isinstance(command, SetProjectSourcingPolicy):
            sim.projects.set_sourcing_policy(ProjectId(command.project_id), command.sourcing_policy); return CommandResult()
        if isinstance(command, SetConstructionWeight):
            sim.projects.set_construction_weight(ProjectId(command.project_id), command.weight); return CommandResult()
        if isinstance(command, SetProjectImportSource):
            sim.projects.set_import_source(
                ProjectId(command.project_id),
                None if command.location_id is None else self._require_location(command.location_id),
            ); return CommandResult()
        return NotImplemented
