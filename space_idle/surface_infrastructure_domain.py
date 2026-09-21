from __future__ import annotations

from .domain import DomainExtension


DOMAIN_EXTENSION = DomainExtension(
    "surface_infrastructure",
    service_capacity_request_provider=lambda sim: sim.surface_infrastructure,
)
