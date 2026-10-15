"""Physical integration contracts of the eight-stage research Content.

These are Content consistency checks, not Core invariants freezing a balance
number, a particular playthrough, or an arbitrary facility-count milestone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from space_idle import (
    AdvanceTime, GetOperationalNode, GetResearch, SetFacilityProcess,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content.base_extended_assets import (
    _EXTENDED_FACILITY_ROWS, _PHYSICAL_ROLES,
)
from space_idle.content.base_extended_industry import build_extended_process_specs
from space_idle.content.base_extended_vehicles import build_extended_vehicle_defs
from space_idle.content.base_research_dag import RESEARCH_DAG_ROWS
from space_idle.content.base_research_details import RESEARCH_DETAILS
from space_idle.content.base_research_stages import build_new_stage_specs
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId


def test_all_research_definitions_have_acyclic_direct_prerequisites_and_display_metadata():
    app = build_game_application()
    sim = app._simulation
    definitions = sim.research.definitions
    authored_ids = {DefinitionId(row[0]) for row in RESEARCH_DAG_ROWS}
    assert authored_ids == definitions.keys() == {DefinitionId(key) for key in RESEARCH_DETAILS}
    assert not any('HB-HABITATION-PROTECTION-12' in str(item) for item in definitions)
    by_id = {item.id: item for item in app.query(GetResearch()).items}
    assert set(by_id) == {str(identity) for identity in authored_ids}
    for identity, definition in definitions.items():
        row = by_id[str(identity)]
        assert row.engineering_problem == definition.engineering_problem
        assert row.technical_outcome == definition.technical_outcome
        assert row.application_domain == definition.application_domain
        assert row.engineering_problem and row.technical_outcome
        assert set(definition.prerequisites) <= authored_ids
        assert all(
            definitions[parent].progression_stage <= definition.progression_stage
            for parent in definition.prerequisites
        )
        assert len({spec.stage_id for spec in definition.stage_specs}) == len(definition.stage_specs)
    # Topological validation is independent of the original authored row order.
    indegree = {identity: len(row.prerequisites) for identity, row in definitions.items()}
    successors = {identity: set() for identity in definitions}
    for identity, row in definitions.items():
        for parent in row.prerequisites:
            successors[parent].add(identity)
    roots = [identity for identity, number in indegree.items() if number == 0]
    visited = set()
    while roots:
        identity = roots.pop()
        visited.add(identity)
        for child in successors[identity]:
            indegree[child] -= 1
            if indegree[child] == 0:
                roots.append(child)
    assert visited == authored_ids


def test_extended_physical_methods_are_owned_by_existing_domains():
    sim = build_game_application()._simulation
    facilities = sim.facilities.definitions
    processes = sim.industry.processes
    vehicles = sim.transport.vehicle_defs
    research = sim.research.definitions
    capabilities = {cap.id for facility in facilities.values() for cap in facility.capability_supplies}
    extended_facilities = {DefinitionId('planned.facility.' + slug) for slug, *_ in _EXTENDED_FACILITY_ROWS}
    assert extended_facilities <= facilities.keys()
    assert len(extended_facilities) == len(_PHYSICAL_ROLES)
    assert set(build_extended_process_specs()) <= processes.keys()
    assert {ship.id for ship in build_extended_vehicle_defs()} <= vehicles.keys()
    for facility in extended_facilities:
        definition = facilities[facility]
        recipe = sim.projects.recipes[facility]
        assert recipe.prerequisite_technologies <= research.keys()
        assert recipe.resources and all(item.amount_t > 0 for item in recipe.resources)
        assert facility in sim.power.specs
        assert definition.maintenance_fraction_per_year > 0
    for process in build_extended_process_specs().values():
        assert process.required_capabilities <= capabilities
        assert process.prerequisite_technologies <= research.keys()
        assert process.inputs_per_day and process.outputs_per_day
        assert set(process.inputs_per_day) | set(process.outputs_per_day) <= sim.inventory.resource_definitions.keys()
        assert sum(process.outputs_per_day.values()) <= sum(process.inputs_per_day.values()) + 1e-9
    for ship in build_extended_vehicle_defs():
        assert ship.production.prerequisite_technologies <= research.keys()
        assert ship.production.resources
        assert ship.production.days > 0
        assert ship.retirement.enabled
        assert ship.maintenance.resources
        assert ship.performance.propellant_capacity_t > 0
        assert ship.performance.propellant_t_per_total_t_per_km_s > 0
    for identity, stages in build_new_stage_specs().items():
        assert stages == research[identity].stage_specs[1:]
    for resource in (ids.CARBON_NUTRIENT_FEEDSTOCK, ids.REFRACTORY_ALLOY, ids.HARDENED_ELECTRONICS, ids.RECOVERY_SCRAP):
        assert any(resource in process.outputs_per_day for process in processes.values())
        assert any(resource in process.inputs_per_day for process in processes.values())


def test_extended_manufacturing_process_runs_through_application_and_survives_save_offline(tmp_path):
    app = build_game_application()
    sim = app._simulation
    facility = DefinitionId('planned.facility.earth_basic_electronics_shop')
    process = DefinitionId('planned.process.earth_basic_electronics')
    # This is a Content validation setup: technology/preexisting installed
    # assets are input conditions, never implied automatically by Research.
    sim.technology.completed.add(DefinitionId('PL-EARTH-PRECISION-PARTS'))
    facility_id = sim.facilities.install(facility, ids.EARTH)
    sim.inventory.add(ids.EARTH, ids.METAL_ORE, 3)
    sim.inventory.add(ids.EARTH, ids.MINERAL_FEEDSTOCK, 3)
    sim.inventory.add(ids.EARTH, ids.WATER, 3)
    option = next(option for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                  if row.facility_id == str(facility_id)
                  for option in row.process_options if option.process_id == str(process))
    assert option.can_select
    app.execute(SetFacilityProcess(str(facility_id), str(process)))
    before = sim.inventory.amount(ids.EARTH, ids.PRECISION_ELECTRONICS)
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(ids.EARTH, ids.PRECISION_ELECTRONICS) > before

    path = tmp_path / 'extended-research-state.json'
    saved_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
    save_game(app, path, saved_at=saved_at)
    loaded, result = load_game(path, build_game_application_for_load)
    assert result is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    app.execute(AdvanceTime(2))
    loaded.execute(AdvanceTime(2))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_new_prototype_stage_uses_existing_application_stage_selection_and_reservation():
    from dataclasses import replace
    from space_idle import StartResearch, SetResearchPrototypeSite
    from space_idle.research import ResearchTheoryStageSpec

    target = DefinitionId('X2-REMOTE-OPERATIONS-LAB')
    app = build_game_application()
    sim = app._simulation
    definition = sim.research.definitions[target]
    assert definition.stage_specs[1].stage_id == 'prototype_2'
    sim.technology.completed.update(definition.prerequisites)
    # Isolate the stage transition from RP quantity balancing; use the exact
    # registered physical prototype spec with real Application commands.
    sim.research.definitions[target] = replace(
        definition,
        stage_specs=(ResearchTheoryStageSpec('theory', .5),) + definition.stage_specs[1:],
    )
    sim.research.stored_points = 12
    app.execute(StartResearch(str(target)))
    app.execute(AdvanceTime(1))
    row = next(row for row in app.query(GetResearch()).items if row.id == str(target))
    assert row.current_stage_type == 'prototype'
    app.execute(SetResearchPrototypeSite(str(target), 'prototype_2', str(ids.EARTH)))
    app.execute(AdvanceTime(1))
    row = next(row for row in app.query(GetResearch()).items if row.id == str(target))
    assert row.stage_resources
    assert row.execution_context.operational_node_id == str(ids.EARTH)
    assert sim.research.prototype_reserved_t(target, 'prototype_2', ids.EARTH, ids.MACHINERY) > 0
