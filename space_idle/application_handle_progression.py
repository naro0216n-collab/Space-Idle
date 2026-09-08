from __future__ import annotations

from .application_commands import Command, CommandResult, FundResearchPrototype, PauseResearch, PauseSurvey, ResumeResearch, ResumeSurvey, SetResearchAllocation, SetResearchDemonstrationSite, SetSurveyAllocation, StartResearch, StartSurvey
from .shared import DefinitionId


class ProgressionCommandHandlerMixin:
    def _handle_progression_command(self, command: Command):
        sim = self._simulation
        if isinstance(command, (StartResearch, PauseResearch, ResumeResearch, SetResearchAllocation, FundResearchPrototype, SetResearchDemonstrationSite)):
            if sim.research is None:
                raise RuntimeError("research is not configured")
            rid = DefinitionId(command.research_id)
            if isinstance(command, StartResearch): sim.research.start(rid, allocation_weight=command.allocation_weight)
            elif isinstance(command, PauseResearch): sim.research.pause(rid)
            elif isinstance(command, ResumeResearch): sim.research.resume(rid)
            elif isinstance(command, SetResearchAllocation): sim.research.set_allocation_weight(rid, command.weight)
            elif isinstance(command, FundResearchPrototype): sim.research.fund_prototype(rid, self._require_location(command.location_id), sim.day)
            else: sim.research.set_demonstration_site(rid, self._require_location(command.location_id), sim.day)
            return CommandResult()
        if isinstance(command, (StartSurvey, PauseSurvey, ResumeSurvey, SetSurveyAllocation)):
            if sim.survey is None:
                raise RuntimeError("survey is not configured")
            loc = self._require_location(command.location_id)
            res = self._require_resource(command.resource_id)
            if isinstance(command, StartSurvey): sim.survey.start(loc, res, allocation_weight=command.allocation_weight)
            elif isinstance(command, PauseSurvey): sim.survey.pause(loc, res)
            elif isinstance(command, ResumeSurvey): sim.survey.resume(loc, res)
            else: sim.survey.set_allocation_weight(loc, res, command.weight)
            return CommandResult()
        return NotImplemented
