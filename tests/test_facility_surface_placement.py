from __future__ import annotations

from pathlib import Path

import pytest

from space_idle import (
    AdvanceTime,
    GetBuildOptions,
    GetCatalog,
    GetSurfaceMap,
    PlanBuild,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.facilities import FacilityBook, FacilityPlacementScope
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.validation import validate_runtime_state


def test_location_facility_does_not_require_cell_and_rejects_cell_selection():
    sim = build_game_application()._simulation

    project_id = sim.projects.plan_build(
        ids.WATER_STORAGE,
        ids.EARTH,
        50,
        "mixed",
    )
    assert sim.projects.projects[project_id].site_cell_id is None

    with pytest.raises(ValueError, match="must not specify"):
        sim.projects.plan_build(
            ids.WATER_STORAGE,
            ids.EARTH,
            50,
            "mixed",
            site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
        )


def test_surface_cell_facility_requires_a_developed_cell_owned_by_location():
    sim = build_game_application()._simulation
    definition = sim.facilities.definitions[ids.ROBOTIC_GEOLOGY_STATION]
    assert definition.placement_scope is FacilityPlacementScope.SURFACE_CELL

    with pytest.raises(ValueError, match="requires a surface cell"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION,
            ids.EARTH,
            50,
            "mixed",
        )

    with pytest.raises(ValueError, match="not developed"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION,
            ids.EARTH,
            50,
            "mixed",
            site_cell_id=ids.EARTH_CELL_COASTAL,
        )

    project_id = sim.projects.plan_build(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        50,
        "mixed",
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    assert sim.projects.projects[project_id].site_cell_id == ids.EARTH_CELL_INDUSTRIAL


def test_surface_cell_facility_uses_site_environment_while_remaining_location_owned():
    base = build_game_application()._simulation
    base.graph.develop_surface_cell(ids.SOUTH_POLAR_RIDGE, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    definitions = build_facility_definitions()

    ridge = FacilityBook(definitions, base.facilities.environment)
    ridge_id = ridge.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.SOUTH_POLAR_RIDGE,
        site_cell_id=ids.MOON_CELL_SOUTH_POLAR_RIDGE,
    )
    plain = FacilityBook(definitions, base.facilities.environment)
    plain_id = plain.install(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.SOUTH_POLAR_RIDGE,
        site_cell_id=ids.MOON_CELL_SOUTH_POLAR_PLAIN,
    )

    ridge_power = base.power.snapshot(ids.SOUTH_POLAR_RIDGE, ridge, base.day)
    plain_power = base.power.snapshot(ids.SOUTH_POLAR_RIDGE, plain, base.day)

    assert ridge.facilities[ridge_id].location_id == ids.SOUTH_POLAR_RIDGE
    assert plain.facilities[plain_id].location_id == ids.SOUTH_POLAR_RIDGE
    assert ridge_power.generation_mw > plain_power.generation_mw


def test_surface_map_owns_surface_buildability_and_location_build_options_do_not_request_cells():
    app = build_game_application()

    build_options = app.query(GetBuildOptions(str(ids.EARTH)))
    assert str(ids.ROBOTIC_GEOLOGY_STATION) not in {
        row.facility_definition_id for row in build_options.items
    }

    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    industrial = next(row for row in surface.cells if row.id == str(ids.EARTH_CELL_INDUSTRIAL))
    option = next(
        row
        for row in industrial.facility_placement_options
        if row.facility_definition_id == str(ids.ROBOTIC_GEOLOGY_STATION)
    )
    assert option.location_id == str(ids.EARTH)
    assert option.site_blockers == ()

    catalog = app.query(GetCatalog())
    robotic = next(
        row for row in catalog.facilities if row.id == str(ids.ROBOTIC_GEOLOGY_STATION)
    )
    assert robotic.placement_scope == "SURFACE_CELL"


def test_completed_surface_build_preserves_site_cell_through_save_load(tmp_path: Path):
    app = build_game_application()
    sim = app._simulation
    sim.technology.unlock(ids.TECH_ROBOTIC_FIELD_GEOLOGY)

    result = app.execute(
        PlanBuild(
            str(ids.EARTH),
            str(ids.ROBOTIC_GEOLOGY_STATION),
            sourcing_policy="local_priority",
            site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
        )
    )
    assert result.created_id is not None
    for _ in range(4):
        app.execute(AdvanceTime(1))
        project = next(
            row for row in sim.projects.projects.values() if str(row.id) == result.created_id
        )
        if project.completed_facility_id is not None:
            break

    assert project.completed_facility_id is not None
    facility = sim.facilities.facilities[project.completed_facility_id]
    assert project.site_cell_id == ids.EARTH_CELL_INDUSTRIAL
    assert facility.site_cell_id == ids.EARTH_CELL_INDUSTRIAL
    validate_runtime_state(sim)

    path = tmp_path / "surface-facility.json"
    save_game(app, path)
    loaded, _ = load_game(path, build_game_application)

    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded_project = loaded._simulation.projects.projects[project.id]
    loaded_facility = loaded._simulation.facilities.facilities[facility.id]
    assert loaded_project.site_cell_id == ids.EARTH_CELL_INDUSTRIAL
    assert loaded_facility.site_cell_id == ids.EARTH_CELL_INDUSTRIAL
