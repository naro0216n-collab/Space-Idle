from __future__ import annotations

import pytest

from space_idle import (
    GetBuildOptions,
    GetCatalog,
    GetSurfaceMap,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.facilities import FacilityBook, FacilityPlacementScope
from space_idle.shared import SpatialNodeId


def test_facility_placement_scope_controls_surface_cell_requirement():
    sim = build_game_application()._simulation

    # Operational-node facilities neither require nor accept a surface cell.
    project_id = sim.projects.plan_build(
        ids.WATER_STORAGE,
        ids.EARTH,
        3,
        "mixed",
    )
    assert sim.projects.projects[project_id].site_cell_id is None
    with pytest.raises(ValueError, match="must not specify"):
        sim.projects.plan_build(
            ids.WATER_STORAGE,
            ids.EARTH,
            3,
            "mixed",
            site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
        )

    # Surface-cell facilities require a developed cell owned by the location.
    definition = sim.facilities.definitions[ids.ROBOTIC_GEOLOGY_STATION]
    assert definition.placement_scope is FacilityPlacementScope.SURFACE_CELL
    with pytest.raises(ValueError, match="requires a surface cell"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION,
            ids.EARTH,
            3,
            "mixed",
        )
    with pytest.raises(ValueError, match="not developed"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION,
            ids.EARTH,
            3,
            "mixed",
            site_cell_id=ids.EARTH_CELL_COASTAL,
        )

    project_id = sim.projects.plan_build(
        ids.ROBOTIC_GEOLOGY_STATION,
        ids.EARTH,
        3,
        "mixed",
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    assert sim.projects.projects[project_id].site_cell_id == ids.EARTH_CELL_INDUSTRIAL

def test_surface_cell_facility_uses_site_environment_while_remaining_location_owned():
    base = build_game_application()._simulation
    location_id = SpatialNodeId("test.location.surface_environment")
    base.graph.found_location(location_id, "Test", ids.MOON, ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    base.graph.develop_surface_cell(location_id, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    definitions = build_facility_definitions()

    ridge = FacilityBook(definitions, base.facilities.environment)
    ridge_id = ridge.install(ids.ROBOTIC_GEOLOGY_STATION, location_id, site_cell_id=ids.MOON_CELL_SOUTH_POLAR_RIDGE)
    plain = FacilityBook(definitions, base.facilities.environment)
    plain_id = plain.install(ids.ROBOTIC_GEOLOGY_STATION, location_id, site_cell_id=ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    ridge_power = base.power.snapshot(location_id, ridge, base.day)
    plain_power = base.power.snapshot(location_id, plain, base.day)

    assert ridge.facilities[ridge_id].operational_node_id == location_id
    assert plain.facilities[plain_id].operational_node_id == location_id
    assert ridge_power.generation_mw > plain_power.generation_mw


def test_surface_map_owns_surface_buildability_and_location_build_options_do_not_request_cells():
    app = build_game_application()
    sim = app._simulation

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
    assert option.can_plan
    recipe = sim.projects.recipes[ids.ROBOTIC_GEOLOGY_STATION]
    assert {detail for code, detail in option.blockers if code == "technology"} == {
        str(technology_id) for technology_id in recipe.prerequisite_technologies
    }
    assert option.sourcing_policy_options == build_options.sourcing_policy_options
    assert option.import_source_options == build_options.import_source_options

    catalog = app.query(GetCatalog())
    robotic = next(
        row for row in catalog.facilities if row.id == str(ids.ROBOTIC_GEOLOGY_STATION)
    )
    assert robotic.placement_scope == "SURFACE_CELL"
