from dataclasses import replace

import pytest

from space_idle import build_game_application
from space_idle.content.base_game import MACHINERY, REUSABLE_ORBITAL_CARGO_TUG
from space_idle.transport import ResourceSupportRequirement
from space_idle.validation import validate_simulation_configuration
from space_idle.validation_support import ConfigurationError


def test_vehicle_resource_specs_reject_duplicate_resource_ids():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.logistics.vehicle_defs[vehicle_id]

    sim.logistics.vehicle_defs[vehicle_id] = replace(
        definition,
        production=replace(
            definition.production,
            resources=((MACHINERY, 1.0), (MACHINERY, 2.0)),
        ),
    )
    with pytest.raises(ConfigurationError, match="duplicate vehicle resource input: production"):
        validate_simulation_configuration(sim)

    sim.logistics.vehicle_defs[vehicle_id] = replace(
        definition,
        maintenance=replace(
            definition.maintenance,
            resources=((MACHINERY, 1.0), (MACHINERY, 2.0)),
        ),
    )
    with pytest.raises(ConfigurationError, match="duplicate vehicle resource input: maintenance"):
        validate_simulation_configuration(sim)


def test_vehicle_resource_support_requires_declared_vehicle_interface():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.logistics.vehicle_defs[vehicle_id]

    sim.logistics.vehicle_defs[vehicle_id] = replace(
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


def test_vehicle_production_progress_uses_same_runtime_site_blockers_as_query():
    from space_idle import AdvanceTime, PauseFacility, ProduceVehicle
    from space_idle.content.base_game import EARTH, ROBOTIC_SURVEY_PACKAGE
    from space_idle.site import CapabilityRequirement, SiteRequirements

    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.logistics.vehicle_defs[vehicle_id]
    sim.logistics.vehicle_defs[vehicle_id] = replace(
        definition,
        production=replace(
            definition.production,
            site_requirements=SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement("spacecraft_servicing", 0.01, "available"),
                ),
            ),
        ),
    )
    servicing_id = sim.facilities.install(ROBOTIC_SURVEY_PACKAGE, EARTH)
    sim.refresh_storage()

    result = app.execute(ProduceVehicle(str(vehicle_id), str(EARTH)))
    project_id = next(
        pid for pid in sim.logistics.vehicle_production_projects
        if str(pid) == result.created_id
    )
    state = sim.logistics.vehicle_production_projects[project_id]
    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    started_progress = state.progress_days
    assert started_progress > 0

    app.execute(PauseFacility(str(servicing_id)))
    blockers = sim.logistics.vehicle_production_blockers(project_id, day=sim.day)
    assert any("spacecraft_servicing" in blocker for blocker in blockers)

    app.execute(AdvanceTime(2))
    assert state.phase.value == "building"
    assert state.progress_days == pytest.approx(started_progress)


def test_operation_asset_disposition_prevents_route_continuation_after_recovery():
    from space_idle.content.base_game import EARTH, SOUTH_POLAR_RIDGE
    from space_idle.logistics import (
        LandingCapability,
        OperationAssetDisposition,
        PoweredAscentCapability,
        SpaceflightCapability,
        TransportPerformanceProfile,
    )
    from space_idle.shared import RouteId

    app = build_game_application()
    sim = app._simulation
    route = sim.logistics.routes[RouteId("base.route.earth_ridge_direct")]
    profile = TransportPerformanceProfile(
        dry_mass_t=10.0,
        payload_t=1.0,
        operation_capabilities=(
            PoweredAscentCapability(10.0, 11.0, 120000.0, OperationAssetDisposition.ORIGIN),
            SpaceflightCapability(5.0),
            LandingCapability(2.5, 2.5, 2000.0),
        ),
    )

    failures = sim.logistics.performance_route_failures(route, profile, sim.day)

    assert EARTH == route.origin_id and SOUTH_POLAR_RIDGE == route.destination_id
    assert "operation:powered_ascent:asset_returns_before_route_complete" in failures


def test_transport_endurance_is_profile_level_and_validated():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.logistics.vehicle_defs[vehicle_id]

    sim.logistics.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(definition.performance, endurance_days=0.0),
    )
    with pytest.raises(ConfigurationError, match="non-positive transport endurance"):
        validate_simulation_configuration(sim)


def test_generic_vehicle_capabilities_are_intrinsic_and_unique():
    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.logistics.vehicle_defs[vehicle_id]

    sim.logistics.vehicle_defs[vehicle_id] = replace(
        definition,
        performance=replace(
            definition.performance,
            generic_capabilities=("docking", "docking"),
        ),
    )
    with pytest.raises(ConfigurationError, match="duplicate generic vehicle capability"):
        validate_simulation_configuration(sim)


def test_transport_endurance_applies_independently_of_operation_kind():
    from space_idle.logistics import PoweredAscentCapability, TransportPerformanceProfile
    from space_idle.shared import RouteId

    app = build_game_application()
    sim = app._simulation
    route = sim.logistics.routes[RouteId("base.route.earth_leo")]
    profile = TransportPerformanceProfile(
        dry_mass_t=10.0,
        payload_t=1.0,
        operation_capabilities=(PoweredAscentCapability(10.0, 11.0, 120000.0),),
        endurance_days=1.0,
    )

    failures = sim.logistics.performance_route_failures(route, profile, sim.day)

    assert "endurance:2/1" in failures
