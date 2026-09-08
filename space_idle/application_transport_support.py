from __future__ import annotations

from .logistics import VehicleDisposition


def vehicle_concept(definition: object) -> str:
    """Return the presentation concept implied by transport capabilities and disposition."""
    return (
        "launch_vehicle"
        if definition.powered_ascent is not None
        and definition.default_disposition is VehicleDisposition.RETURN_TO_ORIGIN
        and definition.spaceflight is None
        else "spacecraft"
    )
