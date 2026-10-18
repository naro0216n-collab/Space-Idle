from __future__ import annotations

from math import sqrt

from ..shared import DefinitionId
from ..spatial import AtmosphereField, EnvironmentResolver, PhysicalSurface, SpatialGraph
from ..transport import TransportOperationKind, TransportOperationRequirement
from ..transport.movement import SpaceflightMovementRule, SurfaceAccessMovementRule, SurfaceTransportMovementRule
from . import base_requirements as req

def build_surface_movement_rules() -> tuple[SurfaceTransportMovementRule, ...]:
    return (
        SurfaceTransportMovementRule(
            id=DefinitionId("base.movement.surface_transport"),
            display_name="地表輸送",
            operation=TransportOperationRequirement(TransportOperationKind.SURFACE_TRANSPORT, 0.0),
            gateway_capability_id="surface_distribution",
            transit_days=1,
        ),
    )


def build_surface_access_movement_rules(
    graph: SpatialGraph, environment: EnvironmentResolver,
) -> tuple[SurfaceAccessMovementRule, ...]:
    """Build surface access for every solid Body from physical World conditions.

    Vehicle and gateway eligibility use one ordinary Movement contract; named
    planets are not privileged and no per-origin/destination table exists.
    """
    rules: list[SurfaceAccessMovementRule] = []
    for body in sorted(graph.bodies.values(), key=lambda row: str(row.id)):
        if body.physical_surface is not PhysicalSurface.SOLID:
            continue
        gravity = body.representative_gravity_m_s2
        if gravity is None:
            continue  # Unknown physical input is not an artificial zero-gravity route.
        # Body definitions are physical subjects rather than Environment query
        # contexts. Read their statically owned BODY_GLOBAL facet directly.
        atmosphere = environment.static.body_facets.get((body.id, AtmosphereField))
        if atmosphere is None:
            continue  # The operation type cannot be selected without a known atmosphere.
        # Surface-to-low-orbit demand is an approximation of local escape speed.
        # Vehicle Delta-V and propellant share this one Content-derived value.
        has_dense_atmosphere = atmosphere.pressure_pa >= 50_000.0
        # Atmospheric launch requires additional ascent margin beyond a vacuum
        # ascent. Both cases derive from the same Body physics, without named
        # planet surface-access exceptions.
        ascent_factor = 0.84 if has_dense_atmosphere else 0.8
        characteristic_delta_v = max(0.05, ascent_factor * sqrt(2.0 * gravity * body.mean_radius_km * 1000.0) / 1000.0)
        descent_kind = (
            TransportOperationKind.ATMOSPHERIC_ENTRY if has_dense_atmosphere
            else TransportOperationKind.LANDING
        )
        rules.append(SurfaceAccessMovementRule(
            id=DefinitionId(f"base.movement.surface_access.{body.id}"),
            display_name=f"{body.display_name}地表アクセス",
            body_id=body.id,
            descent_operations=(TransportOperationRequirement(
                descent_kind, 0.0 if has_dense_atmosphere else characteristic_delta_v,
            ),),
            ascent_operations=(TransportOperationRequirement(
                TransportOperationKind.POWERED_ASCENT, characteristic_delta_v,
            ),),
            transit_days=2,
            gateway_capability_id="launch_operations" if has_dense_atmosphere else "surface_distribution",
            space_requirements=req.ORBIT_SITE,
            surface_requirements=req.ATMOSPHERIC_SURFACE_SITE if has_dense_atmosphere else req.SURFACE_SITE,
        ))
    return tuple(rules)


def build_spaceflight_movement_rules() -> tuple[SpaceflightMovementRule, ...]:
    # 384,400 km / 76,880 km/day = 5 characteristic days for the baseline
    # Earth-Moon anchors. New bodies reuse this profile from their own Spatial
    # transport geometry rather than adding OD-specific definitions.
    return (
        SpaceflightMovementRule(
            id=DefinitionId("base.movement.spaceflight"),
            display_name="宇宙航行",
            operation_type=TransportOperationKind.SPACEFLIGHT,
            characteristic_speed_km_per_day=76_880.0,
            minimum_transit_days=1,
        ),
    )
