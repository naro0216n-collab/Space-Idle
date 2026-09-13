from __future__ import annotations

from .application import GameApplication
from .content.base_catalog import build_base_catalog
from .composition.base_simulation import build_base_simulation
from .validation import validate_catalog_coverage, validate_simulation_configuration


def build_game_application() -> GameApplication:
    """Compose the base content, domain simulation and application boundary."""
    simulation = build_base_simulation()
    catalog = build_base_catalog()
    validate_simulation_configuration(simulation)
    validate_catalog_coverage(simulation, catalog)
    return GameApplication(simulation, catalog)
