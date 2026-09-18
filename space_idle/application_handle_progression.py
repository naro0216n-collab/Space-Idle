from __future__ import annotations

from .application_commands import (
    Command, CommandResult, SetResearchPriority, PauseResearch, PauseSurvey,
    ResumeResearch, ResumeSurvey, SetResearchDemonstrationSite,
    SetResearchProviderFleetQuantity,
    SetResearchProviderAssignmentPriority, PauseResearchProviderAssignment,
    ResumeResearchProviderAssignment, SetSurveyProviderFleetQuantity,
    SetResearchPrototypeSite, SetSurveyPriority, StartResearch, StartSurvey, StartScientificExploration, SetScientificExplorationPriority, PauseScientificExploration, ResumeScientificExploration, AssignExplorationFleet, UnassignExplorationFleet,
)
from .exploration_models import KnowledgeLevel
from .shared import DefinitionId, EntityId, SurfaceCellId


class ProgressionCommandHandlerMixin:
    def _handle_progression_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, (
            StartResearch, PauseResearch, ResumeResearch, SetResearchPrototypeSite,
            SetResearchPriority, SetResearchDemonstrationSite,
        )):
            if sim.research is None:
                raise RuntimeError("research is not configured")
            rid = DefinitionId(command.research_id)
            if isinstance(command, StartResearch):
                sim.research.start(rid, day=sim.day, priority=command.priority)
            elif isinstance(command, PauseResearch):
                sim.research.pause(rid)
            elif isinstance(command, ResumeResearch):
                sim.research.resume(rid)
            elif isinstance(command, SetResearchPrototypeSite):
                sim.research.set_prototype_site(
                    rid,
                    command.stage_id,
                    self._require_operational_node(command.operational_node_id),
                    sim.day,
                    None if command.surface_cell_id is None else SurfaceCellId(command.surface_cell_id),
                )
            elif isinstance(command, SetResearchPriority):
                sim.research.set_priority(rid, command.priority)
            else:
                sim.research.set_demonstration_site(
                    rid,
                    command.stage_id,
                    self._require_operational_node(command.operational_node_id),
                    sim.day,
                    None if command.surface_cell_id is None else SurfaceCellId(command.surface_cell_id),
                )
            return CommandResult()
        if isinstance(command, (
            SetResearchProviderFleetQuantity, SetResearchProviderAssignmentPriority,
            PauseResearchProviderAssignment, ResumeResearchProviderAssignment,
        )):
            if sim.research is None:
                raise RuntimeError("research is not configured")
            if isinstance(command, SetResearchProviderFleetQuantity):
                assignment_id = sim.research.set_provider_fleet_quantity(
                    DefinitionId(command.provider_definition_id),
                    self._require_operational_node(command.operational_node_id),
                    DefinitionId(command.vehicle_definition_id),
                    int(command.quantity),
                    day=sim.day,
                )
                return CommandResult(None if assignment_id is None else str(assignment_id))
            assignment_id = EntityId(command.assignment_id)
            if isinstance(command, SetResearchProviderAssignmentPriority):
                sim.research.set_provider_assignment_priority(assignment_id, command.priority)
            elif isinstance(command, PauseResearchProviderAssignment):
                sim.research.pause_provider_assignment(assignment_id)
            else:
                sim.research.resume_provider_assignment(assignment_id)
            return CommandResult()
        if isinstance(command, (
            StartScientificExploration, SetScientificExplorationPriority, PauseScientificExploration, ResumeScientificExploration,
            AssignExplorationFleet, UnassignExplorationFleet,
        )):
            if sim.scientific_exploration is None:
                raise RuntimeError("scientific exploration is not configured")
            exploration_id = DefinitionId(command.exploration_id)
            if isinstance(command, StartScientificExploration):
                sim.scientific_exploration.start(exploration_id, day=sim.day, priority=command.priority)
            elif isinstance(command, SetScientificExplorationPriority):
                sim.scientific_exploration.set_priority(exploration_id, command.priority)
            elif isinstance(command, PauseScientificExploration):
                sim.scientific_exploration.pause(exploration_id)
            elif isinstance(command, ResumeScientificExploration):
                sim.scientific_exploration.resume(exploration_id)
            elif isinstance(command, AssignExplorationFleet):
                powers = sim.tick_decision_projection().allocations.power_by_location
                sim.scientific_exploration.assign_fleet(
                    exploration_id,
                    DefinitionId(command.vehicle_definition_id),
                    day=sim.day,
                    power_by_location=powers,
                )
            else:
                sim.scientific_exploration.unassign_fleet(exploration_id, day=sim.day)
            return CommandResult()
        if isinstance(command, SetSurveyProviderFleetQuantity):
            if sim.survey is None:
                raise RuntimeError("survey is not configured")
            assignment_id = sim.survey.set_provider_fleet_quantity(
                DefinitionId(command.provider_definition_id),
                self._require_operational_node(command.operational_node_id),
                DefinitionId(command.vehicle_definition_id),
                int(command.quantity),
                day=sim.day,
            )
            return CommandResult(None if assignment_id is None else str(assignment_id))
        if isinstance(command, (StartSurvey, PauseSurvey, ResumeSurvey, SetSurveyPriority)):
            if sim.survey is None:
                raise RuntimeError("survey is not configured")
            cell_id = SurfaceCellId(command.cell_id)
            if cell_id not in sim.graph.surface_cells:
                raise KeyError(command.cell_id)
            resource_id = self._require_resource(command.resource_id)
            if isinstance(command, StartSurvey):
                provider_operational_node_id = self._require_operational_node(command.provider_operational_node_id)
                sim.survey.start(
                    provider_operational_node_id,
                    DefinitionId(command.provider_definition_id),
                    command.observation_mode_id,
                    cell_id,
                    resource_id,
                    KnowledgeLevel(command.target_knowledge_level),
                    priority=command.priority,
                    day=sim.day,
                )
            elif isinstance(command, PauseSurvey):
                sim.survey.pause(cell_id, resource_id)
            elif isinstance(command, ResumeSurvey):
                sim.survey.resume(cell_id, resource_id)
            else:
                sim.survey.set_priority(cell_id, resource_id, command.priority)
            return CommandResult()
        return NotImplemented
