from dataclasses import replace

import pytest

from space_idle import build_game_application
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO, MACHINERY, REUSABLE_ORBITAL_CARGO_TUG
from space_idle.transport import ResourceSupportRequirement
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError


def test_vehicle_definition_validation_rejects_invalid_resource_and_interface_contracts():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.transport.vehicle_defs[vehicle_id]

    for field in ("production", "maintenance"):
        invalid = replace(
            getattr(definition, field),
            resources=((MACHINERY, 1.0), (MACHINERY, 2.0)),
        )
        sim.transport.vehicle_defs[vehicle_id] = replace(
            definition,
            **{field: invalid},
        )
        with pytest.raises(
            ConfigurationError,
            match=rf"duplicate vehicle resource input: {field}",
        ):
            validate_simulation_configuration(sim)

    sim.transport.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(
            definition.performance,
            generic_capabilities=tuple(
                capability
                for capability in definition.generic_capabilities
                if capability != "refueling_interface"
            ),
            resource_support_requirements=(
                ResourceSupportRequirement(
                    definition.propellant_resource_id,
                    "vehicle_refueling",
                    "refueling_interface",
                ),
            ),
        ),
    )
    with pytest.raises(
        ConfigurationError,
        match="transport resource support requires undeclared vehicle capability",
    ):
        validate_simulation_configuration(sim)

    sim.transport.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(definition.performance, endurance_days=0.0),
    )
    with pytest.raises(ConfigurationError, match="non-positive transport endurance"):
        validate_simulation_configuration(sim)

    sim.transport.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(
            definition.performance,
            generic_capabilities=("docking", "docking"),
        ),
    )
    with pytest.raises(ConfigurationError, match="duplicate generic vehicle capability"):
        validate_simulation_configuration(sim)


def test_transport_performance_enforces_operation_continuity_and_endurance():
    from space_idle.content import base_ids as ids
    from space_idle.transport import (
        LandingCapability, MovementEndpoint, MovementPlan, OperationAssetDisposition,
        PoweredAscentCapability, SpaceflightCapability, SpatialRelation,
        TransportOperationKind, TransportOperationRequirement, TransportPerformanceProfile,
    )
    from space_idle.shared import MovementPlanId

    app = build_game_application()
    sim = app._simulation
    plan = MovementPlan(
        MovementPlanId("test.movement.multi_operation_recovery"),
        MovementEndpoint(ids.EARTH, access_cell_id=ids.EARTH_CELL_INDUSTRIAL),
        MovementEndpoint(ids.LEO, non_surface_interface="operational_node"),
        SpatialRelation(ids.EARTH_CELL_INDUSTRIAL, ids.LEO, "test"),
        transit_days=3,
        operations=(
            TransportOperationRequirement(TransportOperationKind.POWERED_ASCENT, 9.4),
            TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 0.5),
        ),
    )
    profile = TransportPerformanceProfile(
        dry_mass_t=10.0, payload_t=1.0,
        operation_capabilities=(
            PoweredAscentCapability(10.0, 11.0, 120000.0, OperationAssetDisposition.ORIGIN),
            SpaceflightCapability(5.0), LandingCapability(2.5, 2.5, 2000.0),
        ),
    )
    failures = sim.transport.performance_movement_failures(plan, profile, sim.day)
    assert "operation:powered_ascent:asset_returns_before_movement_complete" in failures

    canonical_plan = sim.transport.movement_plan_candidates(EARTH, LEO)[0]
    endurance_profile = TransportPerformanceProfile(
        dry_mass_t=10.0,
        payload_t=1.0,
        operation_capabilities=(PoweredAscentCapability(10.0, 11.0, 120000.0),),
        endurance_days=1.0,
    )
    endurance_failures = sim.transport.performance_movement_failures(
        canonical_plan, endurance_profile, sim.day
    )
    assert "endurance:2/1" in endurance_failures

    fractional_plan = replace(canonical_plan, transit_days=5)
    fractional_performance = replace(
        sim.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG].performance,
        transit_time_multiplier=0.7,
    )
    assert fractional_plan.transit_days * fractional_performance.transit_time_multiplier == 3.5
    assert sim.transport.performance_movement_transit_days(
        fractional_plan, fractional_performance
    ) == 4
