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
    assert tuple((option.process_id, option.display_name) for option in candidate.process_options) == tuple(
        (str(process.id), process.display_name)
        for process in sorted(sim.industry.processes.values(), key=lambda row: str(row.id))
        if process in sim.industry.compatible_processes(definition.id)
    )
    assert candidate.process_nominal_throughput_per_day == (
        definition.process_throughput_per_day if candidate.process_options else None
    )
    for option in candidate.process_options:
        process = sim.industry.processes[DefinitionId(option.process_id)]
        assert dict(option.input_rates_per_day) == {
            str(resource_id): rate * definition.process_throughput_per_day
            for resource_id, rate in process.inputs_per_day.items()
        }
        assert dict(option.output_rates_per_day) == {
            str(resource_id): rate * definition.process_throughput_per_day
            for resource_id, rate in process.outputs_per_day.items()
        }
        assert option.missing_technology_ids == tuple(
            str(technology) for technology in sim.industry.missing_process_technologies(process)
        )
    nominal_generation, nominal_load = sim.power.nominal_for_definition_at_context(
        definition.id, ids.EARTH, sim.day,
    )
    assert candidate.power_nominal_generation_mw == pytest.approx(nominal_generation)
    assert candidate.power_nominal_load_mw == pytest.approx(nominal_load)
    expected_extraction = definition.extraction_capacity_t_per_day or None
    assert candidate.extraction_nominal_capacity_t_per_day == expected_extraction
    # A new build's recurring Resource demand comes from the same Facility
    # calculation used by runtime maintenance and Upgrade previews.
    recipe = sim.projects.recipes[definition.id]
    invested = {}
    for requirement in recipe.resources:
        invested[requirement.resource_id] = (
            invested.get(requirement.resource_id, 0.0) + requirement.amount_t
        )
    predicted = dict(candidate.maintenance_rates_per_day)
    installed = sim.facilities.maintenance_requirements_for_investment(definition.id, invested)
    assert predicted == {str(resource): rate for resource, rate in installed.items()}
    # The projection is a read-only calculation, not an extra maintenance owner.
    assert all(rate >= 0 for rate in predicted.values())
    # Unlike build inputs, heterogeneous facility effects have no shared
    # comparison score or comparison pinning contract.
    assert not hasattr(build_options, "comparison_axes")
    assert not hasattr(candidate, "comparison_values")
    rows_by_id = {DefinitionId(row.facility_definition_id): row for row in build_options.items}
    # Research generation and storage are first-class idle scale: the
    # prospective Facility uses the same provider as the installed asset.
    for facility_id in (ids.GENERAL_RESEARCH_LAB, ids.VACUUM_REGOLITH_PROCESS_LABORATORY):
        assert facility_id in rows_by_id
        provider = sim.research.facility_provider_for_definition(facility_id)
        assert provider is not None
        spec = provider.level_spec(1)
        projected = rows_by_id[facility_id].research_capacity
        assert projected is not None
        assert projected.provider_tier == provider.tier
        assert projected.generation_points_per_day == spec.generation_points_per_day
        assert projected.storage_capacity_points == spec.storage_capacity_points
        assert projected.execution_work_per_day == spec.research_execution_per_day
        assert projected.crew_person_days_per_research_point == provider.crew_person_days_per_research_point
    # The build decision includes Construction-owned site work as a nominal
    # service, but not the manufacturing of finite Construction Equipment.
    from space_idle.construction.models import CONSTRUCTION_SERVICE_TYPE
    yard = rows_by_id[ids.CONSTRUCTION_YARD]
    assert (CONSTRUCTION_SERVICE_TYPE, sim.projects.construction_providers[ids.CONSTRUCTION_YARD].work_per_day) in yard.service_capacity_supplies
    equipment = rows_by_id[ids.HEAVY_EQUIPMENT_ASSEMBLY]
    assert all(service != CONSTRUCTION_SERVICE_TYPE for service, _ in equipment.service_capacity_supplies)
    # Existing and advanced fabricators expose the resulting rates for the
    # *same* downstream Process. The comparison must reflect material flow,
    # not just a list of available Process names.
    base = rows_by_id[ids.FABRICATION_WORKSHOP]
    advanced = rows_by_id[ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE]
    assert advanced.process_nominal_throughput_per_day > base.process_nominal_throughput_per_day
    common_process = str(ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS)
    base_flows = next(option for option in base.process_options if option.process_id == common_process)
    advanced_flows = next(option for option in advanced.process_options if option.process_id == common_process)
    resource = str(ids.STRUCTURAL_COMPONENTS)
    assert dict(advanced_flows.output_rates_per_day)[resource] > dict(base_flows.output_rates_per_day)[resource]
    assert (rows_by_id[ids.AUTONOMOUS_ORE_MINE].extraction_nominal_capacity_t_per_day
            > rows_by_id[ids.METAL_ORE_MINE].extraction_nominal_capacity_t_per_day)
    ore = rows_by_id[ids.ORE_PROCESSING]
    wet = next(option for option in ore.process_options
               if option.process_id == str(ids.PROCESS_WET_ORE_BENEFICIATION))
    assert str(ids.research_id("RP-RESOURCE-CHAIN-10")) in wet.missing_technology_ids
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
        if process in sim.industry.compatible_processes(row.definition_id)
    )
    alternate_process_id = DefinitionId("test.process.alternate_structural_material")
    sim.industry.processes[alternate_process_id] = ProcessSpec(
        alternate_process_id,
        "Alternate structural material",
        process.required_capabilities,
        {},
        {ids.STRUCTURAL_COMPONENTS: 0.01},
    )
    unresolved = next(
        row for row in app.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if row.facility_id == str(facility.id)
    )
    assert unresolved.selection_required
    assert unresolved.process_id is None
    assert not hasattr(unresolved, "process_comparison_axes")
    assert tuple(option.process_id for option in unresolved.process_options) == tuple(sorted((
        str(process.id), str(alternate_process_id),
    )))
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
    assert not hasattr(primary_option, "comparison_values")
    # The alternative process is selectable via its individual material
    # flows, not a shared score or a separately pinned comparison.
    assert all(option.input_rates_per_day is not None and option.output_rates_per_day is not None
               for option in unresolved.process_options)

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
    assert all(row.shortage_t == pytest.approx(row.required_t - row.available_t) for row in shortages)
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
    assert {row.resource_id: row.required_t for row in option.resources} == {
        str(req.resource_id): req.amount_t for req in recipe.resources
    }
    for resource in option.resources:
        assert resource.available_t == pytest.approx(
            sim.inventory.available(ids.EARTH, resource.resource_id)
        )
        assert resource.shortage_t == pytest.approx(
            max(0.0, resource.required_t - resource.available_t)
        )
    assert option.projected_material_readiness_day == sim.day
    # Surface placement is a physical Facility investment like node construction:
    # project the same actual upkeep, research and power contracts at the Cell.
    invested = {req.resource_id: req.amount_t for req in recipe.resources}
    expected_upkeep = sim.facilities.maintenance_requirements_for_investment(
        recipe.facility_def_id, invested
    )
    assert dict(option.maintenance_rates_per_day) == {
        str(resource): rate for resource, rate in expected_upkeep.items()
    }
    provider = sim.research.facility_provider_for_definition(recipe.facility_def_id)
    assert provider is not None
    assert option.research_capacity.provider_tier == provider.tier
    assert option.research_capacity.generation_points_per_day == provider.level_spec(1).generation_points_per_day
    assert option.research_capacity.storage_capacity_points == provider.level_spec(1).storage_capacity_points
    survey = sim.survey.providers[ids.ROBOTIC_GEOLOGY_STATION]
    assert len(option.survey_providers) == 1
    assert option.survey_providers[0].provider_id == str(survey.id)
    assert option.survey_providers[0].capacity_units_per_source_per_day == survey.capacity_units_per_source_per_day
    assert tuple((mode.display_name, mode.survey_rate, mode.max_knowledge_level)
                 for mode in option.survey_providers[0].observation_modes) == tuple(
        (mode.display_name or mode.id, mode.survey_rate, int(mode.max_knowledge_level))
        for mode in survey.observation_modes
    )
    assert (option.power_nominal_generation_mw, option.power_nominal_load_mw) == pytest.approx(
        sim.power.nominal_for_definition_at_context(recipe.facility_def_id, ids.EARTH_CELL_INDUSTRIAL, sim.day)
    )
    assert option.capabilities == tuple(sorted(
        supply.id for supply in sim.facilities.definitions[recipe.facility_def_id].capability_supplies
    ))
    # Planning eligibility does not hide physical investment effects when a
    # Technology is missing; nor does preview create a new Facility or State.
    facility_count = len(sim.facilities.facilities)
    assert app.query(GetSurfaceMap(str(ids.EARTH_BODY))) == surface
    assert len(sim.facilities.facilities) == facility_count

    catalog = app.query(GetCatalog())
    robotic = next(
        row for row in catalog.facilities if row.id == str(ids.ROBOTIC_GEOLOGY_STATION)
    )
    assert robotic.placement_scope == "SURFACE_CELL"
    # Capability-compatible new Content receives the same Research/Survey
    # preview without adding a Facility ID branch to Application/UI.
    from dataclasses import replace
    peer_id = DefinitionId("test.facility.geology_survey_peer")
    sim.facilities.definitions[peer_id] = replace(
        sim.facilities.definitions[ids.ROBOTIC_GEOLOGY_STATION],
        id=peer_id, display_name="追加地質観測所",
    )
    sim.industry.facility_defs[peer_id] = sim.facilities.definitions[peer_id]
    sim.projects.recipes[peer_id] = replace(recipe, facility_def_id=peer_id)
    with_peer = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    peer = next(
        candidate for cell in with_peer.cells if cell.id == str(ids.EARTH_CELL_INDUSTRIAL)
        for candidate in cell.facility_placement_options
        if candidate.facility_definition_id == str(peer_id)
    )
    assert peer.research_capacity == option.research_capacity
    assert peer.survey_providers == option.survey_providers
    assert peer.maintenance_rates_per_day == option.maintenance_rates_per_day
    assert peer.resources == option.resources
    assert peer.projected_material_readiness_day == option.projected_material_readiness_day


def test_process_interface_can_be_shared_by_a_differently_named_higher_throughput_facility():
    """Facility identity is not an Industry permission or an execution-rate ceiling."""
    from dataclasses import replace

    from space_idle import AdvanceTime
    from space_idle.validation import validate_runtime_state, validate_simulation_configuration

    app = build_game_application()
    sim = app._simulation
    source_def = sim.facilities.definitions[ids.BASIC_STRUCTURAL_MATERIAL_PLANT]
    process = sim.industry.processes[ids.PROCESS_BASIC_STRUCTURAL_MATERIAL]
    alternative_id = DefinitionId('test.facility.independent_interface')
    sim.facilities.definitions[alternative_id] = replace(
        source_def, id=alternative_id, process_throughput_per_day=2.0,
    )
    assert sim.industry.compatible_processes(alternative_id) == (process,)
    # Missing or partial interfaces must not silently permit a precise Process.
    basic_only_id = DefinitionId('test.facility.basic_only')
    machine_shop = sim.facilities.definitions[ids.MACHINE_SHOP]
    from space_idle.facilities import CapabilitySupply
    sim.facilities.definitions[basic_only_id] = replace(
        machine_shop, id=basic_only_id,
        capability_supplies=(CapabilitySupply('basic_machine_shop'),),
    )
    assert ids.PROCESS_BASIC_MACHINING in {
        row.id for row in sim.industry.compatible_processes(basic_only_id)
    }
    assert ids.PROCESS_PRECISION_COMPONENTS not in {
        row.id for row in sim.industry.compatible_processes(basic_only_id)
    }
    new_id = sim.facilities.install(alternative_id, ids.EARTH)
    # Disable only the old producer so its effect cannot mask the new Asset's flow.
    for facility in sim.facilities.facilities.values():
        if facility.definition_id == source_def.id:
            facility.paused = True

    sim.inventory.add(ids.EARTH, ids.MINERAL_FEEDSTOCK, 50.0)
    sim.inventory.add(ids.EARTH, ids.METAL_ORE, 50.0)
    validate_simulation_configuration(sim)
    validate_runtime_state(sim)
    bundle = next(row for row in sim.industry.execution_requirement_bundles(
        ids.EARTH, sim.facilities, sim.inventory, sim.day
    ) if row.owner_id == new_id)
    assert bundle.requested_execution == pytest.approx(2.0)

    projection = sim.tick_decision_projection()
    allocation = projection.allocations.execution.allocation(bundle.id)
    assert allocation.allocated_execution > 0
    row = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
               if row.facility_id == str(new_id))
    assert row.process_id == str(process.id)
    assert dict(row.input_rates_per_day)[str(ids.MINERAL_FEEDSTOCK)] == pytest.approx(
        process.inputs_per_day[ids.MINERAL_FEEDSTOCK] * allocation.allocated_execution
    )
    assert dict(row.output_rates_per_day)[str(ids.STRUCTURAL_COMPONENTS)] == pytest.approx(
        process.outputs_per_day[ids.STRUCTURAL_COMPONENTS] * allocation.allocated_execution
    )
    app.execute(AdvanceTime(1))
    assert sim.day > 0


def test_scenario_facilities_have_the_same_normal_construction_contract_as_later_assets(tmp_path):
    """Scenario ownership cannot create a class of otherwise unobtainable facilities."""
    from datetime import datetime, timezone

    from space_idle import PlanBuild, GetProjects
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.facilities import FacilityPlacementScope
    from space_idle.persistence import load_game, save_game

    app = build_game_application()
    sim = app._simulation
    initial = build_standard_scenario_definition().facilities
    assert {row.definition_id for row in initial} <= set(sim.projects.recipes)
    assert set(sim.facilities.definitions) == set(sim.projects.recipes)

    node_options = {
        row.facility_definition_id for row in app.query(GetBuildOptions(str(ids.EARTH))).items
    }
    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    core = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_INDUSTRIAL))
    cell_options = {row.facility_definition_id for row in core.facility_placement_options}

    for asset in initial:
        definition = sim.facilities.definitions[asset.definition_id]
        if definition.placement_scope is FacilityPlacementScope.OPERATIONAL_NODE:
            assert str(asset.definition_id) in node_options
        elif asset.operational_node_id == ids.EARTH:
            assert str(asset.definition_id) in cell_options

    # A new instance follows the same public Project command/persistence path.
    project_id = app.execute(PlanBuild(str(ids.EARTH), str(ids.GENERAL_RESEARCH_LAB))).created_id
    assert project_id is not None
    assert any(row.id == project_id for row in app.query(GetProjects(str(ids.EARTH))).items)
    path = tmp_path / 'construction.json'
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    save_game(app, path, saved_at=now)
    restored, _ = load_game(path, build_game_application_for_load, now=now)
    assert any(row.id == project_id for row in restored.query(GetProjects(str(ids.EARTH))).items)


def test_external_power_uses_world_site_eligibility_not_initial_asset_identity():
    from space_idle.spatial import ExternalGridConnectionField

    app = build_game_application()
    sim = app._simulation
    grid = ids.GRID_POWER_SUPPLY
    initial = next(row for row in sim.facilities.all_at(ids.EARTH) if row.definition_id == grid)
    assert initial.site_cell_id == ids.EARTH_CELL_INDUSTRIAL
    assert sim.power.snapshot(ids.EARTH, sim.facilities, sim.day).generation_mw >= 20.0

    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    blocked = sim.projects.site_failures(grid, ids.EARTH, sim.day, site_cell_id=ids.EARTH_CELL_COASTAL)
    assert any(row.code == 'world:external_grid_connection' for row in blocked)

    # With the same World-side connection, another developed Cell can use the
    # same Facility Definition and the same installation/operation evaluator.
    sim.facilities.environment.static.set(ids.EARTH_CELL_COASTAL, ExternalGridConnectionField())
    assert not sim.projects.site_failures(grid, ids.EARTH, sim.day, site_cell_id=ids.EARTH_CELL_COASTAL)
    second = sim.facilities.install(grid, ids.EARTH, site_cell_id=ids.EARTH_CELL_COASTAL)
    assert sim.facilities.is_environmentally_compatible(sim.facilities.facilities[second], sim.day)
    assert sim.power.snapshot(ids.EARTH, sim.facilities, sim.day).generation_mw >= 40.0
