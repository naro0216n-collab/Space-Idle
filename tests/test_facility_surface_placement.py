from __future__ import annotations

import pytest

from space_idle import (
    CreateTransportAllocation,
    GetBuildOptions,
    GetCatalog,
    GetOperationalNode,
    GetSurfaceMap,
    SetFacilityProcess,
    build_game_application,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.facilities import FacilityBook, FacilityPlacementScope
from space_idle.industry import ProcessSpec
from space_idle.shared import DefinitionId, SpatialNodeId


def test_facility_placement_scope_controls_cell_ownership_and_environment_context():
    sim = build_game_application()._simulation

    project_id = sim.projects.plan_build(
        ids.WATER_STORAGE, ids.EARTH, 3, "standard_wait"
    )
    assert sim.projects.projects[project_id].site_cell_id is None
    with pytest.raises(ValueError, match="must not specify"):
        sim.projects.plan_build(
            ids.WATER_STORAGE, ids.EARTH, 3, "standard_wait",
            site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
        )

    definition = sim.facilities.definitions[ids.ROBOTIC_GEOLOGY_STATION]
    assert definition.placement_scope is FacilityPlacementScope.SURFACE_CELL
    with pytest.raises(ValueError, match="requires a surface cell"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION, ids.EARTH, 3, "standard_wait"
        )
    with pytest.raises(ValueError, match="not developed"):
        sim.projects.plan_build(
            ids.ROBOTIC_GEOLOGY_STATION, ids.EARTH, 3, "standard_wait",
            site_cell_id=ids.EARTH_CELL_COASTAL,
        )

    project_id = sim.projects.plan_build(
        ids.ROBOTIC_GEOLOGY_STATION, ids.EARTH, 3, "standard_wait",
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    assert sim.projects.projects[project_id].site_cell_id == ids.EARTH_CELL_INDUSTRIAL

    location_id = SpatialNodeId("test.location.surface_environment")
    sim.graph.found_location(
        location_id, "Test", ids.MOON, ids.MOON_CELL_SOUTH_POLAR_RIDGE
    )
    sim.graph.develop_surface_cell(location_id, ids.MOON_CELL_SOUTH_POLAR_PLAIN)
    definitions = build_facility_definitions()

    ridge = FacilityBook(definitions, sim.facilities.environment)
    ridge_id = ridge.install(
        ids.ROBOTIC_GEOLOGY_STATION, location_id,
        site_cell_id=ids.MOON_CELL_SOUTH_POLAR_RIDGE,
    )
    plain = FacilityBook(definitions, sim.facilities.environment)
    plain_id = plain.install(
        ids.ROBOTIC_GEOLOGY_STATION, location_id,
        site_cell_id=ids.MOON_CELL_SOUTH_POLAR_PLAIN,
    )
    ridge_power = sim.power.snapshot(location_id, ridge, sim.day)
    plain_power = sim.power.snapshot(location_id, plain, sim.day)

    assert ridge.facilities[ridge_id].operational_node_id == location_id
    assert plain.facilities[plain_id].operational_node_id == location_id
    assert ridge_power.generation_mw > plain_power.generation_mw

def test_facility_decision_projection_exposes_buildability_process_choices_and_material_readiness():
    app = build_game_application()
    sim = app._simulation

    build_options = app.query(GetBuildOptions(str(ids.EARTH)))
    assert str(ids.ROBOTIC_GEOLOGY_STATION) not in {
        row.facility_definition_id for row in build_options.items
    }
    # Construction candidates own the player-facing effect summary used by the
    # iPad decision surface; the UI must not reconstruct facility capabilities
    # or service/process effects from unrelated catalog structures.
    candidate = next(row for row in build_options.items if row.facility_definition_id is not None)
    definition = next(
        row for row in sim.facilities.definitions.values()
        if str(row.id) == candidate.facility_definition_id
    )
    assert candidate.capabilities == tuple(sorted(supply.id for supply in definition.capability_supplies))
    assert candidate.service_capacity_supplies == tuple(
        sorted((supply.service_type, supply.nominal_rate) for supply in definition.service_capacity_supplies)
    )
    assert candidate.placement_scope == definition.placement_scope.value
    assert candidate.process_options == tuple(
        (str(process.id), process.display_name)
        for process in sorted(sim.industry.processes.values(), key=lambda row: str(row.id))
        if process.facility_def_id == definition.id
    )
    assert build_options.comparison_axes
    assert any(axis.differs for axis in build_options.comparison_axes)
    assert {axis.key for axis in build_options.comparison_axes} == {
        "construction_work",
        "resource_total_t",
        "resource_type_count",
        "capability_count",
        "service_type_count",
        "process_count",
        "self_deploying",
    }
    comparison_values = {value.axis_key: value for value in candidate.comparison_values}
    assert candidate.comparison_key == candidate.facility_definition_id
    assert set(comparison_values) == {axis.key for axis in build_options.comparison_axes}
    assert comparison_values["resource_total_t"].number_value == pytest.approx(
        sum(resource.required_t for resource in candidate.resources)
    )
    assert comparison_values["self_deploying"].text_value in {"自己展開", "通常施工"}
    assert candidate.projected_material_readiness_day == sim.day
    for resource in candidate.resources:
        assert resource.available_t == pytest.approx(
            sim.inventory.available(ids.EARTH, resource.resource_id)
        )
        assert resource.available_t >= resource.required_t
        assert resource.projected_arrival_day == sim.day
        assert resource.projected_source_id is None

    process = sim.industry.processes[ids.PROCESS_BASIC_STRUCTURAL_MATERIAL]
    facility = next(
        row for row in sim.facilities.facilities.values()
        if row.definition_id == process.facility_def_id
    )
    alternate_process_id = DefinitionId("test.process.alternate_structural_material")
    sim.industry.processes[alternate_process_id] = ProcessSpec(
        alternate_process_id,
        "Alternate structural material",
        process.facility_def_id,
        {},
        {ids.STRUCTURAL_COMPONENTS: 0.01},
    )
    unresolved = next(
        row for row in app.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if row.facility_id == str(facility.id)
    )
    assert unresolved.selection_required
    assert unresolved.process_id is None
    assert tuple(option.process_id for option in unresolved.process_options) == tuple(sorted((
        str(process.id), str(alternate_process_id),
    )))
    assert unresolved.process_comparison_axes
    assert any(axis.differs for axis in unresolved.process_comparison_axes)
    primary_option = next(
        option for option in unresolved.process_options if option.process_id == str(process.id)
    )
    assert primary_option.input_rates_per_day == tuple(
        (str(resource_id), amount)
        for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda row: str(row[0]))
    )
    assert primary_option.output_rates_per_day == tuple(
        (str(resource_id), amount)
        for resource_id, amount in sorted(process.outputs_per_day.items(), key=lambda row: str(row[0]))
    )
    assert primary_option.service_requirements == ((f"process:{process.id}", 1.0),)
    assert {value.axis_key for value in primary_option.comparison_values} == {
        axis.key for axis in unresolved.process_comparison_axes
    }

    app.execute(SetFacilityProcess(str(facility.id), str(process.id)))
    selected = next(
        row for row in app.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if row.facility_id == str(facility.id)
    )
    assert selected.process_id == str(process.id)
    assert not selected.selection_required
    del sim.industry.processes[alternate_process_id]

    capacity = sim.transport.transport_capacity_for_units(
        ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1, day=sim.day
    )
    app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        capacity.forward_t_per_day, capacity.reverse_t_per_day,
    ))
    remote_candidate = next(
        row for row in app.query(GetBuildOptions(str(ids.LEO))).items
        if row.facility_definition_id == candidate.facility_definition_id
    )
    shortages = [
        resource for resource in remote_candidate.resources
        if resource.available_t + 1e-9 < resource.required_t
    ]
    assert shortages
    assert remote_candidate.projected_material_readiness_day == max(
        resource.projected_arrival_day for resource in shortages
    )
    assert remote_candidate.projected_material_readiness_day > sim.day
    assert all(resource.projected_source_id == str(ids.EARTH) for resource in shortages)
    assert all(resource.projected_arrival_day is not None for resource in shortages)

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
    assert {blocker.subject_id for blocker in option.blockers if blocker.code == "technology"} == {
        str(technology_id) for technology_id in recipe.prerequisite_technologies
    }
    assert option.procurement_policy_options == build_options.procurement_policy_options

    catalog = app.query(GetCatalog())
    robotic = next(
        row for row in catalog.facilities if row.id == str(ids.ROBOTIC_GEOLOGY_STATION)
    )
    assert robotic.placement_scope == "SURFACE_CELL"
