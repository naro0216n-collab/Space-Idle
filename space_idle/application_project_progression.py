from __future__ import annotations

from .application_project_contracts import ContractProgressionProjectorMixin
from .application_project_research import ResearchProgressionProjectorMixin
from .application_project_surveys import SurveyProgressionProjectorMixin
from .application_project_scientific_exploration import ScientificExplorationProjectorMixin


class ProgressionProjectorMixin(
    ResearchProgressionProjectorMixin,
    ScientificExplorationProjectorMixin,
    SurveyProgressionProjectorMixin,
    ContractProgressionProjectorMixin,
):
    pass
