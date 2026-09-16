from __future__ import annotations

from .application import GameApplication
from .content.base_catalog import build_base_catalog
from .content.base_scenario import build_standard_scenario_definition
from .composition.base_simulation import build_base_simulation
from .validation import validate_catalog_coverage, validate_runtime_state, validate_simulation_configuration


def _compose_base_application(*, apply_scenario: bool) -> GameApplication:
    scenario = build_standard_scenario_definition()
    simulation = build_base_simulation()
    simulation.scenario_id = scenario.id
    catalog = build_base_catalog()

    # Static World / Content definitions must be valid independently of any
    # Scenario-owned runtime State.  This same validated composition is used
    # for both new games and save restoration.
    validate_simulation_configuration(simulation)
    validate_catalog_coverage(simulation, catalog)

    if apply_scenario:
        scenario.apply(simulation)
        simulation.refresh_storage()
        # A composed runtime is externally visible only after the canonical
        # day-0 Boundary has been settled.  Scenario State is already owned by
        # its normal Domains before this transition.
        simulation.prepare_player_command()
        validate_runtime_state(simulation)
    return GameApplication(simulation, catalog)


def build_game_application() -> GameApplication:
    """Compose a new standard-scenario game."""
    return _compose_base_application(apply_scenario=True)


def build_game_application_for_load() -> GameApplication:
    """Compose the base definitions with empty runtime State for Persistence restore."""
    return _compose_base_application(apply_scenario=False)
