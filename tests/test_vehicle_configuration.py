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
