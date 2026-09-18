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

def test_vehicle_production_progress_uses_same_runtime_site_blockers_as_query():
    from space_idle import AdvanceTime, PauseFacility, ProduceVehicle
    from space_idle.content.base_game import EARTH, ROBOTIC_SURVEY_PACKAGE
    from space_idle.site import CapabilityRequirement, CapabilityRequirementState, SiteRequirements

    app = build_game_application()
    sim = app._simulation
    vehicle_id = REUSABLE_ORBITAL_CARGO_TUG
    definition = sim.transport.vehicle_defs[vehicle_id]
    sim.transport.vehicle_defs[vehicle_id] = replace(
        definition,
        production=replace(
            definition.production,
            site_requirements=SiteRequirements(
                capability_requirements=(
                    CapabilityRequirement("spacecraft_servicing", CapabilityRequirementState.ACTIVE),
                ),
            ),
        ),
    )
    servicing_id = sim.facilities.install(
        ROBOTIC_SURVEY_PACKAGE,
        EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    sim.refresh_storage()

    result = app.execute(ProduceVehicle(str(vehicle_id), str(EARTH)))
    project_id = next(
        pid for pid in sim.transport.vehicle_production_projects
        if str(pid) == result.created_id
    )
    state = sim.transport.vehicle_production_projects[project_id]
    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    started_progress = state.progress_days
    assert started_progress > 0

    app.execute(PauseFacility(str(servicing_id)))
    blockers = sim.transport.vehicle_production_blockers(project_id, day=sim.day)
    assert any("spacecraft_servicing" in blocker for blocker in blockers)

    app.execute(AdvanceTime(1))
    assert state.phase.value == "building"
    assert state.progress_days == pytest.approx(started_progress)


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
