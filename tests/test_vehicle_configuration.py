from dataclasses import replace

import pytest

from space_idle import build_game_application
from space_idle.content.base_game import MACHINERY, REUSABLE_ORBITAL_CARGO_TUG
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
