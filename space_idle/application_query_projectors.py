from __future__ import annotations

from .application_projection_support import ApplicationProjectionSupportMixin
from .application_query_router import ApplicationQueryRouterMixin
from .application_project_catalog import CatalogWorldProjectorMixin
from .application_project_location import LocationProjectorMixin
from .application_project_surface import SurfaceProjectorMixin
from .application_project_projects import ProjectProjectorMixin
from .application_project_logistics import LogisticsProjectorMixin
from .application_project_progression import ProgressionProjectorMixin
from .application_project_reports import ApplicationReportProjectorMixin


class ApplicationQueryMixin(
    ApplicationProjectionSupportMixin,
    ApplicationQueryRouterMixin,
    CatalogWorldProjectorMixin,
    LocationProjectorMixin,
    SurfaceProjectorMixin,
    ProjectProjectorMixin,
    LogisticsProjectorMixin,
    ProgressionProjectorMixin,
    ApplicationReportProjectorMixin,
):
    """Query facade composed from domain-focused projectors."""

    pass
