from __future__ import annotations

from .app_contracts.logistics_views import InfrastructureRequirementRow
from .logistics import OperationAssetDisposition


def vehicle_concept(definition: object) -> str:
    """Return the presentation concept implied by transport capabilities and disposition."""
    return (
        "launch_vehicle"
        if definition.powered_ascent is not None
        and definition.powered_ascent.asset_disposition is OperationAssetDisposition.ORIGIN
        and definition.spaceflight is None
        else "spacecraft"
    )


def infrastructure_requirement_rows(plan: object) -> tuple[InfrastructureRequirementRow, ...]:
    return tuple(
        InfrastructureRequirementRow(
            str(location_id), capability_id, minimum_capacity, mode
        )
        for location_id, capability_id, minimum_capacity, mode
        in plan.infrastructure_requirements
    )
