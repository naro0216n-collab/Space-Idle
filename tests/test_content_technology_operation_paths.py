"""Research unlocks real alternative operations on shared physical equipment."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime, ApplicationError, GetOperationalNode, GetResearch, SetFacilityProcess,
)
from space_idle.bootstrap import (
    build_game_application_for_load, build_game_application_for_scenario,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.scenario import ScenarioFacility, ScenarioInventoryStock


def _refinery_game():
    base = build_standard_scenario_definition()
    scenario = replace(base,
        facilities=base.facilities + (ScenarioFacility(
            ids.METALLURGY, ids.EARTH,
            invested_resources=((ids.STRUCTURAL_COMPONENTS, 12.0), (ids.MACHINERY, 8.0)),
        ),),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 35.0),
            ScenarioInventoryStock(ids.EARTH, ids.MINERAL_FEEDSTOCK, 35.0),
        ),
    )
    return build_game_application_for_scenario(scenario)


def _refinery_row(app):
    return next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                if row.facility_definition_id == str(ids.METALLURGY))


def test_research_outlet_eligibility_and_real_alternative_resource_flow_roundtrip(tmp_path):
    app = _refinery_game()
    sim = app._simulation
    row = _refinery_row(app)
    options = {option.process_id: option for option in row.process_options}
    alternatives = {
        ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY: ids.RP_RESOURCE_CHAIN_14,
        ids.PROCESS_METALLURGY_VARIABLE_FEED: ids.RP_RESOURCE_CHAIN_15,
    }
    assert row.selection_required
    assert set(str(key) for key in alternatives) <= set(options)
    assert options[str(ids.PROCESS_METALLURGY)].can_select
    for method_id, technology_id in alternatives.items():
        option = options[str(method_id)]
        assert not option.can_select
        assert any(blocker.kind == 'technology' and blocker.subject_id == str(technology_id)
                   for blocker in option.blockers)
        with pytest.raises(ApplicationError, match='technology'):
            app.execute(SetFacilityProcess(row.facility_id, str(method_id)))
    unlocks = { (unlock.kind, unlock.id) for item in app.query(GetResearch()).items
                for unlock in item.unlocks }
    assert {('process', str(method)) for method in alternatives} <= unlocks

    # The same physical plant provides all three method choices. Research alone
    # changes eligibility, not selected Process or installed Equipment.
    app.execute(SetFacilityProcess(row.facility_id, str(ids.PROCESS_METALLURGY)))
    sim.technology.completed.update(alternatives.values())
    assert _refinery_row(app).process_id == str(ids.PROCESS_METALLURGY)
    method_id = ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY
    assert next(option for option in _refinery_row(app).process_options
                if option.process_id == str(method_id)).can_select
    app.execute(SetFacilityProcess(row.facility_id, str(method_id)))
    assert _refinery_row(app).process_id == str(method_id)
    resource_ids = (ids.METAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK, ids.WATER,
                    ids.BULK_STRUCTURE, ids.OXYGEN)
    before = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    app.execute(AdvanceTime(1))
    after = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    assert after[ids.METAL_FEEDSTOCK] < before[ids.METAL_FEEDSTOCK]
    assert after[ids.BULK_STRUCTURE] > before[ids.BULK_STRUCTURE]
    assert after[ids.OXYGEN] > before[ids.OXYGEN]

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    path = tmp_path / 'refinery.json'
    save_game(app, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded.execute(SetFacilityProcess(row.facility_id, str(ids.PROCESS_METALLURGY_VARIABLE_FEED)))
    # Alternative method requires both physically available feedstocks, not
    # an invented substitution of Resource identity in generic Core.
    another = {rid: loaded._simulation.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    loaded.execute(AdvanceTime(1))
    app.execute(AdvanceTime(1))
    final = {rid: loaded._simulation.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    unchanged_method = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    # The two instances have identical physical State before this tick; net
    # stock alone is not a reliable process measure when Extraction also adds
    # feedstock. Compare the alternative to the unchanged-process counterfactual.
    assert final[ids.MINERAL_FEEDSTOCK] < unchanged_method[ids.MINERAL_FEEDSTOCK]
    assert final[ids.METAL_FEEDSTOCK] > unchanged_method[ids.METAL_FEEDSTOCK]
    assert final[ids.BULK_STRUCTURE] < unchanged_method[ids.BULK_STRUCTURE]
    assert _refinery_row(loaded).process_id == str(ids.PROCESS_METALLURGY_VARIABLE_FEED)


def test_authored_technology_prerequisites_are_nonredundant_and_reach_application_research():
    """An inferred ancestor is not an independent second eligibility demand.

    Direct Research prerequisites represent necessary authored choices; the
    Application exposes that same direct DAG instead of reconstructing a
    differently expanded one from category or progression-stage metadata.
    """
    from space_idle import build_game_application

    app = build_game_application()
    definitions = app._simulation.research.definitions
    ancestors_by_id = {}

    def ancestors(research_id):
        if research_id not in ancestors_by_id:
            parents = set(definitions[research_id].prerequisites)
            for parent in tuple(parents):
                parents.update(ancestors(parent))
            ancestors_by_id[research_id] = parents
        return ancestors_by_id[research_id]

    view = app.query(GetResearch())
    rows = {row.id: row for row in view.items}
    assert set(rows) == set(map(str, definitions))
    for research_id, definition in definitions.items():
        required = definition.prerequisites
        assert not any(
            parent in ancestors(other)
            for parent in required for other in required if other != parent
        ), f"transitively duplicated Research prerequisite: {research_id}"
        assert set(rows[str(research_id)].prerequisites) == set(map(str, required))
        for parent in required:
            unlocks = rows[str(parent)].unlocks
            assert any(unlock.kind == 'research' and unlock.id == str(research_id)
                       for unlock in unlocks)

    # Air chemistry, potable water, crew radiation exposure, and landing
    # navigation are separate engineering questions. Neither the ordering of
    # their authored series nor their shared Stage is an implicit prerequisite.
    from space_idle.application_commands import StartResearch
    independent = ("LS-ATMOSPHERE-WATER-WASTE-02", "BIO-HUMAN-BIOLOGY-MEDICINE-02")
    for research_id in independent:
        assert not definitions[research_id].prerequisites
        assert rows[research_id].can_start
        app.execute(StartResearch(research_id))
    prerequisites = rows["EDL-EDL-03"].prerequisites
    assert prerequisites == ("GN-NAVIGATION-01",)
    assert all(blocker.kind == "prerequisite" for blocker in rows["EDL-EDL-03"].start_blockers)
    with pytest.raises(ApplicationError) as rejected:
        app.execute(StartResearch("EDL-EDL-03"))
    assert rejected.value.code == "prerequisite"
    assert "GN-NAVIGATION-01" in rejected.value.message
    app.execute(AdvanceTime(1))
    updated = {row.id: row for row in app.query(GetResearch()).items}
    assert all(updated[research_id].status != "not_started" for research_id in independent)


def test_energy_generation_and_wet_beneficiation_keep_physical_choices_after_unlock(tmp_path):
    """Tech gates acquisition/method choice, not existing machine configuration.

    Two orbital generator generations use distinct construction work, material
    investment, sunlight response and service loads. The ore separator remains
    a single installed asset when a water-intensive recovery method is chosen.
    """
    from space_idle import GetBuildOptions, GetProjects, PlanBuild
    from space_idle.content.base_research import build_research_definitions

    needed = {
        ids.research_id(name) for name in (
            "PG-SOLAR-POWER-04", "MC-MANUFACTURING-CONSTRUCTION-04",
            "FP-REACTOR-POWER-04",
            "RP-RESOURCE-CHAIN-10",
        )
    }
    research_defs = build_research_definitions()
    completed = set(needed)
    frontier = list(needed)
    while frontier:
        new = research_defs[frontier.pop()].prerequisites - completed
        completed.update(new)
        frontier.extend(new)

    base = build_standard_scenario_definition()
    investments = (
        (ids.STRUCTURAL_COMPONENTS, 4.0), (ids.MACHINERY, 3.0),
        (ids.PRECISION_ELECTRONICS, 1.5),
    )
    scenario = replace(
        base,
        facilities=base.facilities + (
            ScenarioFacility(ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.LEO,
                             invested_resources=investments),
            ScenarioFacility(ids.ORE_PROCESSING, ids.EARTH,
                             invested_resources=((ids.STRUCTURAL_COMPONENTS, 10.0),
                                                 (ids.MACHINERY, 7.0))),
        ),
        inventory_stock=base.inventory_stock + tuple(
            ScenarioInventoryStock(ids.LEO, resource_id, 100.0)
            for resource_id in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY,
                                ids.PRECISION_ELECTRONICS)
        ) + (
            ScenarioInventoryStock(ids.EARTH, ids.METAL_ORE, 120.0),
            ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 0.0),
        ),
    )

    locked = build_game_application_for_scenario(scenario)
    build_ids = {ids.TRACKING_ORBITAL_SOLAR_ARRAY, ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER}
    research_unlocks = {row.id: {(unlock.kind, unlock.id) for unlock in row.unlocks}
                        for row in locked.query(GetResearch()).items}
    for technology in ("PG-SOLAR-POWER-04", "MC-MANUFACTURING-CONSTRUCTION-04"):
        assert ("facility", str(ids.TRACKING_ORBITAL_SOLAR_ARRAY)) in research_unlocks[technology]
    for technology in ("FP-REACTOR-POWER-04",):
        assert ("facility", str(ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER)) in research_unlocks[technology]
    assert ("process", str(ids.PROCESS_WET_ORE_BENEFICIATION)) in research_unlocks["RP-RESOURCE-CHAIN-10"]
    locked_builds = {row.facility_definition_id: row for row in
                     locked.query(GetBuildOptions(str(ids.LEO))).items}
    for definition_id in build_ids:
        row = locked_builds[str(definition_id)]
        assert any(blocker.kind == "technology" for blocker in row.blockers)
        assert row.construction_required > 0 and not row.self_deploying
        assert row.power_nominal_generation_mw > 0
        assert row.power_nominal_load_mw > 0
    assert (locked_builds[str(ids.TRACKING_ORBITAL_SOLAR_ARRAY)].power_nominal_generation_mw
            > locked_builds[str(ids.ORBITAL_SOLAR_ARRAY)].power_nominal_generation_mw)
    ore = next(row for row in locked.query(GetOperationalNode(str(ids.EARTH))).industry
               if row.facility_definition_id == str(ids.ORE_PROCESSING))
    wet = next(option for option in ore.process_options
               if option.process_id == str(ids.PROCESS_WET_ORE_BENEFICIATION))
    assert not wet.can_select
    assert any(blocker.kind == "technology" for blocker in wet.blockers)
    with pytest.raises(ApplicationError, match="technology"):
        locked.execute(SetFacilityProcess(ore.facility_id, wet.process_id))

    unlocked_scenario = replace(scenario, completed_technologies=tuple(sorted(completed)))
    app = build_game_application_for_scenario(unlocked_scenario)
    dry = build_game_application_for_scenario(unlocked_scenario)
    sim = app._simulation
    unlocked_builds = {row.facility_definition_id: row for row in
                       app.query(GetBuildOptions(str(ids.LEO))).items}
    for definition_id in build_ids:
        row = unlocked_builds[str(definition_id)]
        assert not any(blocker.kind == "technology" for blocker in row.blockers)
        app.execute(PlanBuild(str(ids.LEO), str(definition_id),
                              procurement_policy="extended_wait"))

    ore = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
               if row.facility_definition_id == str(ids.ORE_PROCESSING))
    assert any(option.process_id == str(ids.PROCESS_ORE_PROCESS)
               and option.can_select for option in ore.process_options)
    app.execute(SetFacilityProcess(ore.facility_id, str(ids.PROCESS_WET_ORE_BENEFICIATION)))
    dry_ore = next(row for row in dry.query(GetOperationalNode(str(ids.EARTH))).industry
                   if row.facility_definition_id == str(ids.ORE_PROCESSING))
    dry.execute(SetFacilityProcess(dry_ore.facility_id, str(ids.PROCESS_ORE_PROCESS)))
    app.execute(AdvanceTime(1))
    dry.execute(AdvanceTime(1))
    # Mining and water intake run concurrently at this site. Compare net stock
    # with the same-world, same-day dry Process rather than treating stock delta
    # as gross consumption; the physical difference is the chosen Recipe.
    assert sim.inventory.amount(ids.EARTH, ids.METAL_ORE) == pytest.approx(
        dry._simulation.inventory.amount(ids.EARTH, ids.METAL_ORE))
    assert sim.inventory.amount(ids.EARTH, ids.WATER) < dry._simulation.inventory.amount(ids.EARTH, ids.WATER)
    assert sim.inventory.amount(ids.EARTH, ids.METAL_FEEDSTOCK) > dry._simulation.inventory.amount(ids.EARTH, ids.METAL_FEEDSTOCK)

    app.execute(AdvanceTime(149))
    node_facilities = {item.definition_id: item for item in sim.facilities.all_at(ids.LEO)}
    assert build_ids <= set(node_facilities)
    assert all(row.status.value == "complete" for row in app.query(GetProjects()).items
               if row.facility_definition_id in set(map(str, build_ids)))
    # Current physical supply is the sum of real installed/operational sources.
    power = sim.power.snapshot(ids.LEO, sim.facilities, sim.day)
    assert power.generation_mw > 15.0
    # Solar output follows each registered Body's illumination, while fixed
    # nuclear generation does not depend on that body or a named location.
    solar_leo, _ = sim.power.nominal_for_definition_at_context(
        ids.TRACKING_ORBITAL_SOLAR_ARRAY, ids.LEO, sim.day)
    solar_mars, _ = sim.power.nominal_for_definition_at_context(
        ids.TRACKING_ORBITAL_SOLAR_ARRAY, ids.MARS_ORBIT, sim.day)
    reactor_leo, _ = sim.power.nominal_for_definition_at_context(
        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER, ids.LEO, sim.day)
    reactor_mars, _ = sim.power.nominal_for_definition_at_context(
        ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER, ids.MARS_ORBIT, sim.day)
    assert 0.0 < solar_mars < solar_leo
    assert reactor_mars == pytest.approx(reactor_leo)
    assert sim.power.specs[ids.ORBITAL_SOLAR_ARRAY].generation != sim.power.specs[ids.TRACKING_ORBITAL_SOLAR_ARRAY].generation
    assert sim.power.specs[ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER].generation != sim.power.specs[ids.ORBITAL_FISSION_POWER].generation
    assert next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                if row.facility_id == ore.facility_id).process_id == str(ids.PROCESS_WET_ORE_BENEFICIATION)

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / "multi-generation-state.json"
    save_game(app, path, saved_at=now)
    reloaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(reloaded._simulation) == capture_state(sim)
    reloaded.execute(AdvanceTime(3))
    app.execute(AdvanceTime(3))
    assert capture_state(reloaded._simulation) == capture_state(sim)
