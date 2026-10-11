from __future__ import annotations

from collections.abc import Callable

from .application import GameApplication
from .content.base_catalog import build_base_catalog
from .content.base_scenario import build_standard_scenario_definition
from .composition.base_simulation import build_base_simulation
from .scenario import ScenarioDefinition
from .validation import validate_catalog_coverage, validate_runtime_state, validate_simulation_configuration


def _compose_base_application(*, apply_scenario: bool, scenario: ScenarioDefinition,
                              definition_transform: Callable | None = None) -> GameApplication:
    catalog = build_base_catalog()
    simulation = build_base_simulation(
        catalog, population_rules=scenario.population_rules,
        external_population_sources=scenario.external_population_sources,
    )
    simulation.scenario_id = scenario.id
    if definition_transform is not None:
        # Definitions are configured before Scenario State is instantiated, then
        # validated through the normal Composition and reference contracts.
        definition_transform(simulation, catalog)
        # Capability / method membership is a derived Composition index, not
        # authoritative State. Recompose it before validation and Scenario
        # application so new Facility or Extraction Definitions behave like
        # existing ones without caller-specific refresh instructions.
        if simulation.extraction is not None:
            simulation.extraction.refresh_definition_compatibility()

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
    return _compose_base_application(apply_scenario=True, scenario=build_standard_scenario_definition())


def build_game_application_for_scenario(
    scenario: ScenarioDefinition, *, definition_transform: Callable | None = None,
) -> GameApplication:
    """Compose and validate a fresh game from the supplied new-game Scenario.

    This is the same composition, validation, and day-0 boundary used by the
    default game. Authored Definitions are configured before runtime State.
    """
    return _compose_base_application(
        apply_scenario=True, scenario=scenario, definition_transform=definition_transform,
    )


def build_game_application_for_load(
    *, scenario: ScenarioDefinition | None = None, definition_transform: Callable | None = None,
) -> GameApplication:
    """Compose validated Definitions without initial State for Persistence restore.

    Rebuild the authored Content/Scenario definition set used by a Snapshot,
    without reapplying Scenario-owned assets or changing live runtime State.
    """
    return _compose_base_application(
        apply_scenario=False,
        scenario=scenario if scenario is not None else build_standard_scenario_definition(),
        definition_transform=definition_transform,
    )
