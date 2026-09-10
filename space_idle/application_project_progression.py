from __future__ import annotations

from .application_project_contracts import ContractProgressionProjectorMixin
from .application_project_research import ResearchProgressionProjectorMixin
from .application_project_surveys import SurveyProgressionProjectorMixin
from .application_project_scientific_exploration import ScientificExplorationProgressionProjectorMixin


class ProgressionProjectorMixin(
    ResearchProgressionProjectorMixin,
    ScientificExplorationProgressionProjectorMixin,
    SurveyProgressionProjectorMixin,
    ContractProgressionProjectorMixin,
):
    pass
