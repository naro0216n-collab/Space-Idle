from __future__ import annotations

from .application_commands import (
    CancelBuild,
    Command,
    CommandResult,
    PauseBuild,
    PlanBuild,
    PlanFacilityUpgrade,
    PlanFacilityDecommission,
    PlanOperationalNodeFounding,
    CancelFounding,
    PauseFounding,
    ResumeFounding,
    SetFoundingPriority,
    DevelopSurfaceCell,
    ResumeBuild,
    SetProjectPriority,
    SetProjectProcurementPolicy,
)
from .shared import CelestialBodyId, DefinitionId, EntityId, ProjectId, SpatialNodeId, SurfaceCellId
from .app_contracts.construction import SurfaceLocationFoundingTarget, NonSurfaceOperationalNodeFoundingTarget
from .founding import NonSurfaceOperationalNodeTargetSpec


class ConstructionCommandHandlerMixin:
    def _validated_logistics_policy_id(self, value: str | None) -> EntityId | None:
        if value is None:
            return None
        policy_id = EntityId(value)
        self._simulation.logistics.require_logistics_policy(policy_id)
        return policy_id

    def _handle_construction_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, PlanBuild):
            logistics_policy_id = self._validated_logistics_policy_id(command.logistics_policy_id)
            pid = sim.projects.plan_build(
                DefinitionId(command.facility_id),
                self._require_operational_node(command.operational_node_id),
                command.priority,
                command.procurement_policy,
                day=sim.day,
                site_cell_id=None if command.site_cell_id is None else SurfaceCellId(command.site_cell_id),
            )
            if logistics_policy_id is not None:
                sim.logistics.assign_logistics_policy("project", EntityId(str(pid)), logistics_policy_id)
            return CommandResult(str(pid))
        if isinstance(command, PlanFacilityUpgrade):
            logistics_policy_id = self._validated_logistics_policy_id(command.logistics_policy_id)
            pid = sim.projects.plan_upgrade(
                EntityId(command.facility_id),
                command.priority,
                command.procurement_policy,
                day=sim.day,
            )
            if logistics_policy_id is not None:
                sim.logistics.assign_logistics_policy("project", EntityId(str(pid)), logistics_policy_id)
            return CommandResult(str(pid))
        if isinstance(command, PlanFacilityDecommission):
            logistics_policy_id = self._validated_logistics_policy_id(command.logistics_policy_id)
            pid = sim.projects.plan_decommission(
                EntityId(command.facility_id),
                command.priority,
                command.procurement_policy,
                day=sim.day,
            )
            if logistics_policy_id is not None:
                sim.logistics.assign_logistics_policy("project", EntityId(str(pid)), logistics_policy_id)
            return CommandResult(str(pid))
        if isinstance(command, PlanOperationalNodeFounding):
            logistics_policy_id = self._validated_logistics_policy_id(command.logistics_policy_id)
            if sim.founding is None:
                raise ValueError("founding domain is not configured")
            if isinstance(command.target_spec, SurfaceLocationFoundingTarget):
                target_spec = sim.founding.surface_target_spec(
                    CelestialBodyId(command.target_spec.body_id),
                    SurfaceCellId(command.target_spec.core_cell_id),
                )
            elif isinstance(command.target_spec, NonSurfaceOperationalNodeFoundingTarget):
                target_spec = NonSurfaceOperationalNodeTargetSpec(
                    SpatialNodeId(command.target_spec.spatial_node_id)
                )
            else:
                raise TypeError(f"unsupported founding target: {type(command.target_spec).__name__}")
            pid = sim.founding.plan(
                self._require_operational_node(command.staging_node_id),
                command.display_name,
                target_spec,
                DefinitionId(command.deployment_recipe_id),
                DefinitionId(command.vehicle_definition_id),
                priority=command.priority,
                day=sim.day,
            )
            if logistics_policy_id is not None:
                sim.logistics.assign_logistics_policy("founding", EntityId(str(pid)), logistics_policy_id)
            return CommandResult(str(pid))
        if isinstance(command, CancelFounding):
            if sim.founding is None:
                raise ValueError("founding domain is not configured")
            sim.founding.cancel(ProjectId(command.project_id), sim.day); return CommandResult()
        if isinstance(command, PauseFounding):
            if sim.founding is None:
                raise ValueError("founding domain is not configured")
            sim.founding.pause(ProjectId(command.project_id)); return CommandResult()
        if isinstance(command, ResumeFounding):
            if sim.founding is None:
                raise ValueError("founding domain is not configured")
            sim.founding.resume(ProjectId(command.project_id)); return CommandResult()
        if isinstance(command, SetFoundingPriority):
            if sim.founding is None:
                raise ValueError("founding domain is not configured")
            sim.founding.set_priority(ProjectId(command.project_id), command.priority); return CommandResult()
        if isinstance(command, DevelopSurfaceCell):
            logistics_policy_id = self._validated_logistics_policy_id(command.logistics_policy_id)
            pid = sim.projects.plan_surface_cell_development(
                self._require_operational_node(command.location_id),
                SurfaceCellId(command.cell_id),
                command.priority,
                command.procurement_policy,
                day=sim.day,
            )
            if logistics_policy_id is not None:
                sim.logistics.assign_logistics_policy("project", EntityId(str(pid)), logistics_policy_id)
            return CommandResult(str(pid))
        if isinstance(command, CancelBuild):
            sim.projects.cancel(ProjectId(command.project_id)); return CommandResult()
        if isinstance(command, PauseBuild):
            sim.projects.pause(ProjectId(command.project_id), sim.day); return CommandResult()
        if isinstance(command, ResumeBuild):
            sim.projects.resume(ProjectId(command.project_id), sim.day); return CommandResult()
        if isinstance(command, SetProjectPriority):
            sim.projects.set_priority(ProjectId(command.project_id), command.priority); return CommandResult()
        if isinstance(command, SetProjectProcurementPolicy):
            sim.projects.set_procurement_policy(
                ProjectId(command.project_id), command.procurement_policy, sim.day
            ); return CommandResult()
        return NotImplemented
