from __future__ import annotations

from .application_commands import (
    Command, CommandResult, FundResearchPrototype, PauseResearch, PauseSurvey,
    ResumeResearch, ResumeSurvey, SetResearchDemonstrationSite,
    SetResearchPrototypeSite, SetSurveyAllocation, StartResearch, StartSurvey, StartScientificExploration, PauseScientificExploration, ResumeScientificExploration, AssignExplorationFleet, UnassignExplorationFleet,
)
from .shared import DefinitionId


class ProgressionCommandHandlerMixin:
    def _handle_progression_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, (
            StartResearch, PauseResearch, ResumeResearch, SetResearchPrototypeSite,
            FundResearchPrototype, SetResearchDemonstrationSite,
        )):
            if sim.research is None:
                raise RuntimeError("research is not configured")
            rid = DefinitionId(command.research_id)
            if isinstance(command, StartResearch):
                sim.research.start(rid, day=sim.day)
            elif isinstance(command, PauseResearch):
                sim.research.pause(rid)
            elif isinstance(command, ResumeResearch):
                sim.research.resume(rid)
            elif isinstance(command, SetResearchPrototypeSite):
                sim.research.set_prototype_site(rid, self._require_location(command.location_id), sim.day)
            elif isinstance(command, FundResearchPrototype):
                sim.refresh_resource_claims()
                sim.research.fund_prototype(rid, sim.day)
            else:
                sim.research.set_demonstration_site(rid, self._require_location(command.location_id), sim.day)
            return CommandResult()
        if isinstance(command, (
            StartScientificExploration, PauseScientificExploration, ResumeScientificExploration,
            AssignExplorationFleet, UnassignExplorationFleet,
        )):
            if sim.scientific_exploration is None:
                raise RuntimeError("scientific exploration is not configured")
            exploration_id = DefinitionId(command.exploration_id)
            if isinstance(command, StartScientificExploration):
                sim.scientific_exploration.start(exploration_id, day=sim.day)
            elif isinstance(command, PauseScientificExploration):
                sim.scientific_exploration.pause(exploration_id)
            elif isinstance(command, ResumeScientificExploration):
                sim.scientific_exploration.resume(exploration_id)
            elif isinstance(command, AssignExplorationFleet):
                sim.scientific_exploration.assign_fleet(exploration_id, DefinitionId(command.vehicle_definition_id), day=sim.day)
            else:
                sim.scientific_exploration.unassign_fleet(exploration_id, day=sim.day)
            return CommandResult()
        if isinstance(command, (StartSurvey, PauseSurvey, ResumeSurvey, SetSurveyAllocation)):
            if sim.survey is None:
                raise RuntimeError("survey is not configured")
            loc = self._require_location(command.location_id)
            res = self._require_resource(command.resource_id)
            if isinstance(command, StartSurvey):
                sim.survey.start(loc, res, allocation_weight=command.allocation_weight)
            elif isinstance(command, PauseSurvey):
                sim.survey.pause(loc, res)
            elif isinstance(command, ResumeSurvey):
                sim.survey.resume(loc, res)
            else:
                sim.survey.set_allocation_weight(loc, res, command.weight)
            return CommandResult()
        return NotImplemented
