from __future__ import annotations

from ..contracts_domain import DOMAIN_EXTENSION as CONTRACTS_EXTENSION
from ..construction.domain import DOMAIN_EXTENSION as CONSTRUCTION_EXTENSION
from ..core_domain import DOMAIN_EXTENSION as CORE_EXTENSION
from ..domain import DomainExtension
from ..facilities_domain import DOMAIN_EXTENSION as FACILITIES_EXTENSION
from ..inventory_domain import DOMAIN_EXTENSION as INVENTORY_EXTENSION
from ..production.domain import DOMAIN_EXTENSION as PRODUCTION_EXTENSION
from ..research_domain import DOMAIN_EXTENSION as RESEARCH_EXTENSION
from ..spatial_domain import DOMAIN_EXTENSION as SPATIAL_EXTENSION
from ..storage_domain import DOMAIN_EXTENSION as STORAGE_EXTENSION
from ..survey_domain import EXTRACTION_EXTENSION, SURVEY_EXTENSION
from ..technology_domain import DOMAIN_EXTENSION as TECHNOLOGY_EXTENSION
from ..transport.domain import DOMAIN_EXTENSION as TRANSPORT_EXTENSION

BASE_DOMAIN_EXTENSIONS: tuple[DomainExtension, ...] = (
    CORE_EXTENSION,
    SPATIAL_EXTENSION,
    TECHNOLOGY_EXTENSION,
    FACILITIES_EXTENSION,
    INVENTORY_EXTENSION,
    STORAGE_EXTENSION,
    PRODUCTION_EXTENSION,
    TRANSPORT_EXTENSION,
    CONSTRUCTION_EXTENSION,
    CONTRACTS_EXTENSION,
    RESEARCH_EXTENSION,
    SURVEY_EXTENSION,
    EXTRACTION_EXTENSION,
)
