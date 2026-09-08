from __future__ import annotations

from .application_project_contracts import ContractProgressionProjectorMixin
from .application_project_research import ResearchProgressionProjectorMixin
from .application_project_surveys import SurveyProgressionProjectorMixin


class ProgressionProjectorMixin(
    ResearchProgressionProjectorMixin,
    SurveyProgressionProjectorMixin,
    ContractProgressionProjectorMixin,
):
    pass
