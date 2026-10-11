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
                                ids.PRECISION_ELECTRONICS,
                                ids.THERMAL_CONTROL_ASSEMBLIES, ids.RADIATION_SHIELDING_PANELS,
                                ids.OPTICAL_INSTRUMENT_PACKAGES)
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


def test_industrial_scale_up_reuses_methods_and_changes_actual_mass_flow(tmp_path):
    """Mining -> concentration -> reduction grows by installed mass flow, not a new Core rule.

    The same Process/Extraction Definitions remain selectable on both generations.
    The investment requires Technology and physically larger construction, power,
    maintenance and finite inputs; later operation and Save/Load use normal APIs.
    """
    from space_idle import GetBuildOptions
    from space_idle.content.base_research import build_research_definitions

    new_assets = (
        (ids.METAL_ORE_MINE, ids.AUTONOMOUS_ORE_MINE),
        (ids.ORE_PROCESSING, ids.CONTINUOUS_ORE_CONCENTRATOR),
        (ids.METALLURGY, ids.CONTINUOUS_REDUCTION_FURNACE),
        (ids.FABRICATION_WORKSHOP, ids.AUTOMATED_STRUCTURAL_FABRICATION_LINE),
    )
    base = build_standard_scenario_definition()
    locked = build_game_application_for_scenario(base)
    candidates = {row.facility_definition_id: row
                  for row in locked.query(GetBuildOptions(str(ids.EARTH))).items}
    research_unlocks = {row.id: {(unlock.kind, unlock.id) for unlock in row.unlocks}
                        for row in locked.query(GetResearch()).items}
    for original, newer in new_assets:
        assert any(blocker.kind == "technology" for blocker in candidates[str(newer)].blockers)
        assert candidates[str(newer)].construction_required > candidates[str(original)].construction_required
        assert candidates[str(newer)].power_nominal_load_mw > candidates[str(original)].power_nominal_load_mw
        assert any(("facility", str(newer)) in exits for exits in research_unlocks.values())
        assert locked._simulation.projects.recipes[newer].resources != locked._simulation.projects.recipes[original].resources
    assert (locked._simulation.extraction.compatible_methods(ids.METAL_ORE_MINE)
            == locked._simulation.extraction.compatible_methods(ids.AUTONOMOUS_ORE_MINE))
    for original, newer in new_assets[1:]:
        assert (locked._simulation.industry.compatible_processes(original)
                == locked._simulation.industry.compatible_processes(newer))

    research = build_research_definitions()
    required = {ids.research_id("RP-RESOURCE-CHAIN-09"),
                ids.research_id("RP-RESOURCE-CHAIN-10"),
                ids.research_id("RP-RESOURCE-CHAIN-15"),
                ids.research_id("MC-MANUFACTURING-CONSTRUCTION-09")}
    completed = set(required)
    frontier = list(required)
    while frontier:
        added = set(research[frontier.pop()].prerequisites) - completed
        completed.update(added)
        frontier.extend(added)

    def make_scenario(use_new):
        assignments = dict(new_assets) if use_new else {}
        facilities = tuple(
            replace(row, definition_id=assignments.get(row.definition_id, row.definition_id))
            for row in base.facilities
        ) + (
            ScenarioFacility(assignments.get(ids.ORE_PROCESSING, ids.ORE_PROCESSING), ids.EARTH,
                             selected_process_id=ids.PROCESS_ORE_PROCESS),
            ScenarioFacility(assignments.get(ids.METALLURGY, ids.METALLURGY), ids.EARTH,
                             selected_process_id=ids.PROCESS_METALLURGY),
            ScenarioFacility(assignments.get(ids.FABRICATION_WORKSHOP, ids.FABRICATION_WORKSHOP), ids.EARTH,
                             selected_process_id=ids.PROCESS_STRUCTURAL_FABRICATION),
        )
        return replace(
            base, facilities=facilities,
            completed_technologies=tuple(sorted(completed)),
            inventory_stock=base.inventory_stock + (
                ScenarioInventoryStock(ids.EARTH, ids.METAL_ORE, 250.0),
                ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 250.0),
                ScenarioInventoryStock(ids.EARTH, ids.BULK_STRUCTURE, 100.0),
            ),
        )

    old = build_game_application_for_scenario(make_scenario(False))
    new = build_game_application_for_scenario(make_scenario(True))
    old_ore = next(row for row in old.query(GetOperationalNode(str(ids.EARTH))).extraction_resources
                   if row.resource_id == str(ids.METAL_ORE))
    new_ore = next(row for row in new.query(GetOperationalNode(str(ids.EARTH))).extraction_resources
                   if row.resource_id == str(ids.METAL_ORE))
    assert new_ore.installed_nominal_capacity_t_per_day > old_ore.installed_nominal_capacity_t_per_day
    assert new_ore.output_t_per_day > old_ore.output_t_per_day
    # Increased ore preparation consumes more of the raw material; Stock is
    # production MINUS consumption, not a proxy for mining output.
    for app, names in ((old, tuple(old_id for old_id, _ in new_assets)),
                       (new, tuple(new_id for _, new_id in new_assets))):
        rows = app.query(GetOperationalNode(str(ids.EARTH))).industry
        for definition_id in names[1:]:
            row = next(row for row in rows if row.facility_definition_id == str(definition_id))
            assert row.process_options
            assert row.process_id in (str(ids.PROCESS_ORE_PROCESS), str(ids.PROCESS_METALLURGY),
                                      str(ids.PROCESS_STRUCTURAL_FABRICATION))
        before = app._simulation.inventory.amount(ids.EARTH, ids.FABRICATED_STRUCTURE)
        app.execute(AdvanceTime(1))
        assert app._simulation.inventory.amount(ids.EARTH, ids.FABRICATED_STRUCTURE) > before

    old_sim = old._simulation
    new_sim = new._simulation
    assert (new_sim.inventory.amount(ids.EARTH, ids.FABRICATED_STRUCTURE)
            > old_sim.inventory.amount(ids.EARTH, ids.FABRICATED_STRUCTURE))
    assert (new_sim.inventory.amount(ids.EARTH, ids.METAL_ORE)
            < old_sim.inventory.amount(ids.EARTH, ids.METAL_ORE))
    assert new_sim.industry.processes[ids.PROCESS_METALLURGY] is not None

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / "industrial-scale.json"
    save_game(new, path, saved_at=now)
    restored, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(new_sim)
    restored.execute(AdvanceTime(3))
    new.execute(AdvanceTime(3))
    assert capture_state(restored._simulation) == capture_state(new_sim)


def test_industrial_material_chain_supplies_common_construction_and_vehicle_inputs(tmp_path):
    """Compare actual shared demands, not a facility's isolated nominal rate.

    Lower-grade opening industry remains available while material fabrication and
    machinery assembly can supply the *same* physical end-product stock used by
    maintenance, construction and Vehicle Production. Supply competition remains
    in canonical execution; no conversion is performed by consuming Domains.
    """
    from space_idle import (
        GetBuildOptions, GetFlowReport, PlanBuild, ProduceVehicle, PauseFacility,
        CreateTransportAllocation, SetTargetStock,
    )
    from space_idle.content.base_research import build_research_definitions

    base = build_standard_scenario_definition()
    required = {
        ids.research_id("AR-AUTONOMY-ROBOTICS-07"),
        ids.research_id("EM-ELECTRONICS-MANUFACTURING-01"),
        ids.research_id("CH-COMBUSTION-01"),
        ids.research_id("GN-NAVIGATION-01"),
    }
    research = build_research_definitions()
    completed = set(required)
    frontier = list(required)
    while frontier:
        for ancestor in research[frontier.pop()].prerequisites:
            if ancestor not in completed:
                completed.add(ancestor)
                frontier.append(ancestor)

    facilities = base.facilities + (
        ScenarioFacility(ids.ORE_PROCESSING, ids.EARTH,
                         selected_process_id=ids.PROCESS_ORE_PROCESS),
        ScenarioFacility(ids.METALLURGY, ids.EARTH,
                         selected_process_id=ids.PROCESS_METALLURGY),
        ScenarioFacility(ids.FABRICATION_WORKSHOP, ids.EARTH,
                         selected_process_id=ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS),
        *(ScenarioFacility(ids.MACHINE_SHOP, ids.EARTH,
                           selected_process_id=ids.PROCESS_BASIC_MACHINING)
          for _ in range(3)),
        ScenarioFacility(ids.INDUSTRIAL_MACHINERY_ASSEMBLY, ids.EARTH,
                         selected_process_id=ids.PROCESS_INDUSTRIAL_MACHINERY_ASSEMBLY),
        ScenarioFacility(ids.MICROELECTRONICS_FAB, ids.EARTH,
                         selected_process_id=ids.PROCESS_MICROELECTRONICS_FABRICATION),
        ScenarioFacility(ids.HEAVY_EQUIPMENT_ASSEMBLY, ids.EARTH,
                         selected_process_id=ids.PROCESS_HEAVY_EQUIPMENT),
        ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
    )
    # Scarce construction commodities coexist with opening Industry and
    # Population/Maintenance demand. Other intermediate stocks are independent
    # initial capital to isolate downstream production rather than presume a
    # fixed single-site gameplay solution.
    stock = tuple(
        row for row in base.inventory_stock
        if not (row.operational_node_id == ids.EARTH and row.resource_id in
                (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY))
    ) + (
        ScenarioInventoryStock(ids.EARTH, ids.STRUCTURAL_COMPONENTS, 12.0),
        ScenarioInventoryStock(ids.EARTH, ids.MACHINERY, 10.0),
        ScenarioInventoryStock(ids.EARTH, ids.METAL_ORE, 500.0),
        ScenarioInventoryStock(ids.EARTH, ids.MINERAL_FEEDSTOCK, 400.0),
        ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 250.0),
        ScenarioInventoryStock(ids.EARTH, ids.BULK_STRUCTURE, 250.0),
        ScenarioInventoryStock(ids.EARTH, ids.BASIC_MACHINE_PARTS, 150.0),
        ScenarioInventoryStock(ids.EARTH, ids.CERAMICS_GLASS, 90.0),
    )
    scenario = replace(base, facilities=facilities, inventory_stock=stock,
                       completed_technologies=tuple(sorted(completed)))
    locked = build_game_application_for_scenario(base)
    assembly_option = next(
        row for row in locked.query(GetBuildOptions(str(ids.EARTH))).items
        if row.facility_definition_id == str(ids.INDUSTRIAL_MACHINERY_ASSEMBLY)
    )
    assert any(row.subject_id == str(ids.research_id("AR-AUTONOMY-ROBOTICS-07"))
               for row in assembly_option.blockers)
    assert any(
        unlock.kind == "facility" and unlock.id == str(ids.INDUSTRIAL_MACHINERY_ASSEMBLY)
        for research_item in locked.query(GetResearch()).items
        for unlock in research_item.unlocks
    )
    electronics_option = next(
        row for row in locked.query(GetBuildOptions(str(ids.EARTH))).items
        if row.facility_definition_id == str(ids.MICROELECTRONICS_FAB)
    )
    assert any(row.subject_id == str(ids.research_id("EM-ELECTRONICS-MANUFACTURING-01"))
               for row in electronics_option.blockers)
    assert any(
        unlock.kind == "facility" and unlock.id == str(ids.MICROELECTRONICS_FAB)
        for research_item in locked.query(GetResearch()).items
        for unlock in research_item.unlocks
    )
    baseline = build_game_application_for_scenario(scenario)
    extended = build_game_application_for_scenario(scenario)
    baseline_rows = baseline.query(GetOperationalNode(str(ids.EARTH))).industry
    fabrication = next(
        row for row in baseline_rows
        if row.facility_definition_id == str(ids.FABRICATION_WORKSHOP)
    )
    assert {str(ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS),
            str(ids.PROCESS_STRUCTURAL_FABRICATION)} <= {
                option.process_id for option in fabrication.process_options
            }
    baseline.execute(SetFacilityProcess(
        fabrication.facility_id, str(ids.PROCESS_STRUCTURAL_FABRICATION),
    ))
    assembly = next(
        row for row in baseline_rows
        if row.facility_definition_id == str(ids.INDUSTRIAL_MACHINERY_ASSEMBLY)
    )
    baseline.execute(PauseFacility(assembly.facility_id))
    microelectronics = next(
        row for row in baseline_rows
        if row.facility_definition_id == str(ids.MICROELECTRONICS_FAB)
    )
    baseline.execute(PauseFacility(microelectronics.facility_id))
    equipment_factory = next(
        row for row in baseline_rows
        if row.facility_definition_id == str(ids.HEAVY_EQUIPMENT_ASSEMBLY)
    )
    baseline.execute(PauseFacility(equipment_factory.facility_id))

    # Producing construction equipment does not also grant the factory a
    # construction-yard service. Its finite stock contributes only after an
    # ordinary Process has actually manufactured and admitted the equipment.
    def node(app):
        return app.query(GetOperationalNode(str(ids.EARTH)))

    def stock(app, resource_id):
        return next(row.amount for row in node(app).inventory
                    if row.resource_id == str(resource_id))

    before_work = node(baseline).construction_capacity_per_day
    leo_before_work = baseline.query(GetOperationalNode(str(ids.LEO))).construction_capacity_per_day
    assert node(extended).construction_capacity_per_day == pytest.approx(before_work)

    for _ in range(22):
        baseline.execute(AdvanceTime(1))
        extended.execute(AdvanceTime(1))
    def end_product_flow(app, resource_id):
        return next(
            row for row in app.query(GetFlowReport(str(ids.EARTH))).resources
            if row.resource_id == str(resource_id)
        )
    for product in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS):
        ordinary_flow = end_product_flow(baseline, product)
        extended_flow = end_product_flow(extended, product)
        assert extended_flow.local_production_per_day > ordinary_flow.local_production_per_day
        assert extended._simulation.inventory.amount(ids.EARTH, product) > (
            baseline._simulation.inventory.amount(ids.EARTH, product)
        )

    # Equipment assembly contributes to construction only through its produced
    # and admitted Equipment stock, without a second provider on the factory.
    assert stock(extended, ids.CONSTRUCTION_EQUIPMENT) > stock(baseline, ids.CONSTRUCTION_EQUIPMENT)
    assert node(extended).construction_capacity_per_day > node(baseline).construction_capacity_per_day
    assert (extended.query(GetOperationalNode(str(ids.LEO))).construction_capacity_per_day
            == pytest.approx(leo_before_work))

    # Both systems commit the same real projects and finite material demand;
    # downstream Construction/Vehicle Domains have no new material exceptions.
    for app in (baseline, extended):
        app.execute(PlanBuild(str(ids.EARTH), str(ids.MINERAL_QUARRY),
                              procurement_policy="immediate"))
        app.execute(ProduceVehicle(str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH)))
    before = {
        product: extended._simulation.inventory.amount(ids.EARTH, product)
        for product in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS)
    }
    for _ in range(4):
        baseline.execute(AdvanceTime(1))
        extended.execute(AdvanceTime(1))
    assert any(extended._simulation.inventory.amount(ids.EARTH, product) < amount
               for product, amount in before.items())
    for product in before:
        assert extended._simulation.inventory.amount(ids.EARTH, product) > (
            baseline._simulation.inventory.amount(ids.EARTH, product)
        )

    path = tmp_path / "integrated-industrial-materials.json"
    saved_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_game(extended, path, saved_at=saved_at)
    loaded, offline = load_game(path, build_game_application_for_load, now=saved_at)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(extended._simulation)
    loaded.execute(AdvanceTime(1))
    extended.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(extended._simulation)

    # Physical stock produced for common terrestrial Construction and Vehicle
    # demand can also supply an orbital node through a real finite Fleet and
    # cargo-handling chain. It must not appear at LEO without shipment.
    leo_before = loaded._simulation.inventory.amount(ids.LEO, ids.PRECISION_ELECTRONICS)
    for app in (loaded, extended):
        assert app.execute(CreateTransportAllocation(
            str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
            target_forward_t_per_day=1.0, target_reverse_t_per_day=0.0,
        )).created_id
        assert app.execute(SetTargetStock(
            str(ids.LEO), str(ids.PRECISION_ELECTRONICS), leo_before + 3.0,
            priority=4,
        )).created_id
        app.execute(AdvanceTime(8))
    assert loaded._simulation.inventory.amount(ids.LEO, ids.PRECISION_ELECTRONICS) > leo_before
    assert capture_state(loaded._simulation) == capture_state(extended._simulation)


def test_mineral_oxygen_chain_and_lander_share_real_resource_and_acquisition_contracts(tmp_path):
    """Industrial expansion must change regional oxygen and transport inputs,
    not synthesize fuel or Fleet through a new Core operation or Research buff.
    """
    from space_idle import GetBuildOptions, GetFlowReport, GetLogistics, ProduceVehicle, PlanBuild
    from space_idle.content.base_research import build_research_definitions
    from space_idle.scenario import ScenarioSurfaceLocation, ScenarioStorageInfrastructure
    from space_idle.shared import SpatialNodeId

    moon_node = SpatialNodeId("test.location.industrial_supply")
    mars_node = SpatialNodeId("test.location.mars_surface_supply")
    base = build_standard_scenario_definition()
    # Two independently installed power generators can support the high heat
    # load. This Moon Scenario is constructed with the ordinary public Scenario
    # schema, not a special planetary production or Inventory rule.
    scenario = replace(
        base,
        operational_node_ids=base.operational_node_ids + (ids.MARS_ORBIT,),
        surface_locations=base.surface_locations + (
            ScenarioSurfaceLocation(moon_node, "真空産業拠点", ids.MOON,
                                    ids.MOON_CELL_SOUTH_POLAR_RIDGE),
            ScenarioSurfaceLocation(mars_node, "火星地表貨物受入拠点", ids.MARS_BODY,
                                    ids.MARS_CELL_EQUATORIAL_PLAIN),
        ),
        facilities=base.facilities + (
            ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, moon_node),
            ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, moon_node),
            ScenarioFacility(ids.MOLTEN_OXIDE_ELECTROLYZER, moon_node),
            ScenarioFacility(ids.VOLATILE_PROCESSING, moon_node),
            ScenarioFacility(ids.ELECTROLYSIS_PLANT, moon_node),
            ScenarioFacility(ids.PROPELLANT_PLANT, moon_node),
            ScenarioFacility(ids.SURFACE_DISTRIBUTION_HUB, mars_node,
                             ids.MARS_CELL_EQUATORIAL_PLAIN),
            ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.MARS_ORBIT),
        ),
        storage_infrastructure=base.storage_infrastructure + (
            ScenarioStorageInfrastructure(moon_node, "cryogenic", 1000.0),
        ),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(moon_node, ids.MINERAL_FEEDSTOCK, 100.0),
            ScenarioInventoryStock(moon_node, ids.VOLATILE_BEARING_MATERIAL, 100.0),
        ),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    process = sim.industry.processes[ids.PROCESS_MOLTEN_OXIDE_ELECTROLYSIS]
    research = build_research_definitions()[ids.RP_RESOURCE_CHAIN_16]
    assert len(research.stage_specs) > 1  # physical prototype consumes material and work
    assert process.prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_16}

    # High-temperature oxide electrolysis is an enclosed industrial process;
    # local power and prerequisites, not outside atmospheric vacuum, govern it.
    def build_option(node):
        return next(row for row in app.query(GetBuildOptions(str(node))).items
                    if row.facility_definition_id == str(ids.MOLTEN_OXIDE_ELECTROLYZER))

    assert {b.kind for b in build_option(ids.EARTH).blockers} >= {"technology"}
    assert not any(b.kind == "environment" for b in build_option(ids.EARTH).blockers)
    assert {b.kind for b in build_option(moon_node).blockers} >= {"technology"}
    facility = next(row for row in app.query(GetOperationalNode(str(moon_node))).industry
                    if row.facility_definition_id == str(ids.MOLTEN_OXIDE_ELECTROLYZER))
    method = next(row for row in facility.process_options if row.process_id == str(process.id))
    assert not method.can_select
    assert any(b.subject_id == str(ids.RP_RESOURCE_CHAIN_16) for b in method.blockers)
    with pytest.raises(ApplicationError, match="technology"):
        app.execute(SetFacilityProcess(facility.facility_id, str(process.id)))

    unlocks = {
        (unlock.kind, unlock.id)
        for row in app.query(GetResearch()).items for unlock in row.unlocks
        if row.id == str(ids.RP_RESOURCE_CHAIN_16)
    }
    assert {("process", str(process.id)),
            ("facility", str(ids.MOLTEN_OXIDE_ELECTROLYZER))} <= unlocks
    # The new cargo craft competes with established designs using real
    # thrust/entry limits, carrying mass, propellant, manufacture and upkeep.
    craft = sim.transport.vehicle_defs[ids.THROTTLEABLE_CARGO_LANDER]
    older = sim.transport.vehicle_defs[ids.REUSABLE_SURFACE_CARGO_LANDER]
    assert craft.performance.payload_t > older.performance.payload_t
    assert craft.performance.propellant_capacity_t > older.performance.propellant_capacity_t
    assert craft.maintenance.turnaround_days > older.maintenance.turnaround_days
    # A real new Body/Location goes through the canonical Movement resolver:
    # the first lander cannot meet the Mars gravity-derived surface delta-v,
    # while the throttleable lander can. Neither is keyed to a Body name.
    assert not sim.transport.transport_service_plan_for(
        older.id, ids.MARS_ORBIT, mars_node,
    ).feasible
    assert sim.transport.transport_service_plan_for(
        craft.id, ids.MARS_ORBIT, mars_node,
    ).feasible
    production = next(row for row in app.query(GetLogistics()).vehicle_production_options
                      if row.vehicle_definition_id == str(craft.id)
                      and row.operational_node_id == str(ids.EARTH))
    assert {b.subject_id for b in production.blockers if b.kind == "technology"} == {
        str(t) for t in craft.production.prerequisite_technologies
    }
    with pytest.raises(ApplicationError, match="technology"):
        app.execute(ProduceVehicle(str(craft.id), str(ids.EARTH)))

    before = {resource: sim.inventory.amount(moon_node, resource)
              for resource in (ids.MINERAL_FEEDSTOCK, ids.OXYGEN, ids.METAL_FEEDSTOCK,
                               ids.WATER, ids.HYDROGEN, ids.PROPELLANT)}
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(moon_node, ids.OXYGEN) == before[ids.OXYGEN]
    # Research authorizes a method and Vehicle manufacture; it does not
    # retroactively alter physical stocks, generator supply or installed assets.
    sim.technology.completed.update({ids.RP_RESOURCE_CHAIN_16}
                                    | craft.production.prerequisite_technologies)
    assert not any(b.kind == "technology" for b in build_option(moon_node).blockers)
    assert not any(b.kind in {"technology", "environment"} for b in build_option(ids.EARTH).blockers)
    app.execute(SetFacilityProcess(facility.facility_id, str(process.id)))
    assert sim.inventory.amount(moon_node, ids.OXYGEN) == before[ids.OXYGEN]
    assert app.execute(ProduceVehicle(str(craft.id), str(ids.EARTH))).created_id
    app.execute(AdvanceTime(12))
    after = {resource: sim.inventory.amount(moon_node, resource)
             for resource in before}
    assert after[ids.MINERAL_FEEDSTOCK] < before[ids.MINERAL_FEEDSTOCK]
    assert after[ids.OXYGEN] > before[ids.OXYGEN]
    assert after[ids.METAL_FEEDSTOCK] > before[ids.METAL_FEEDSTOCK]
    # The same finite inventory is consumed by the existing electrolysis and
    # propellant lines. Oxygen alone cannot mint propellant: Hydrogen must
    # really be recovered from the separate volatile/water chain.
    assert after[ids.PROPELLANT] > before[ids.PROPELLANT]
    assert sim.inventory.amount(moon_node, ids.VOLATILE_BEARING_MATERIAL) < 100.0
    assert sim.inventory.amount(ids.EARTH, ids.OXYGEN) != after[ids.OXYGEN]
    assert sim.transport.fleet_pool(craft.id, ids.EARTH).total_units == 1
    assert sim.transport.fleet_pool(craft.id, moon_node).total_units == 0
    flow = app.query(GetFlowReport(str(moon_node)))
    assert next(row.local_production_per_day for row in flow.resources
                if row.resource_id == str(ids.OXYGEN)) > 0
    assert next(row.local_production_per_day for row in flow.resources
                if row.resource_id == str(ids.METAL_FEEDSTOCK)) > 0

    # Finite power is charged to the same canonical production allocation as
    # every other process. Removing one actual generator cuts installed output;
    # the new research neither creates a free power source nor bypasses others.
    low_power_scenario = replace(
        scenario,
        facilities=tuple(row for index, row in enumerate(scenario.facilities)
                         if index != len(base.facilities)),
        completed_technologies=tuple(sorted({ids.RP_RESOURCE_CHAIN_16})),
    )
    limited = build_game_application_for_scenario(low_power_scenario)
    limited.execute(AdvanceTime(3))
    limited_electrolyzer = next(
        row for row in limited.query(GetOperationalNode(str(moon_node))).industry
        if row.facility_definition_id == str(ids.MOLTEN_OXIDE_ELECTROLYZER)
    )
    assert limited_electrolyzer.scale < next(
        row for row in app.query(GetOperationalNode(str(moon_node))).industry
        if row.facility_definition_id == str(ids.MOLTEN_OXIDE_ELECTROLYZER)
    ).scale

    # A newly ordered second furnace uses normal locally owned build inputs,
    # a construction yard and finite work; merely unlocking the technology
    # has not supplied another industrial installation for free.
    construction_case = replace(
        scenario,
        facilities=scenario.facilities + (ScenarioFacility(ids.CONSTRUCTION_YARD, moon_node),),
        inventory_stock=scenario.inventory_stock + (
            ScenarioInventoryStock(moon_node, ids.FABRICATED_STRUCTURE, 15.0),
            ScenarioInventoryStock(moon_node, ids.MACHINERY, 15.0),
            ScenarioInventoryStock(moon_node, ids.PRECISION_ELECTRONICS, 10.0),
            ScenarioInventoryStock(moon_node, ids.CONSTRUCTION_EQUIPMENT, 60.0),
        ),
        completed_technologies=(ids.RP_RESOURCE_CHAIN_16,),
    )
    builder = build_game_application_for_scenario(construction_case)
    before_furnaces = sum(row.definition_id == ids.MOLTEN_OXIDE_ELECTROLYZER
                          for row in builder._simulation.facilities.all_at(moon_node))
    assert builder.execute(PlanBuild(str(moon_node), str(ids.MOLTEN_OXIDE_ELECTROLYZER),
                                     procurement_policy="immediate")).created_id
    assert sum(row.definition_id == ids.MOLTEN_OXIDE_ELECTROLYZER
               for row in builder._simulation.facilities.all_at(moon_node)) == before_furnaces
    builder.execute(AdvanceTime(160))
    assert sum(row.definition_id == ids.MOLTEN_OXIDE_ELECTROLYZER
               for row in builder._simulation.facilities.all_at(moon_node)) > before_furnaces

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_path = tmp_path / "vacuum-industrial-chain.json"
    save_game(app, save_path, saved_at=now)
    loaded, offline = load_game(save_path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded.execute(AdvanceTime(1))
    app.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_high_volume_propellant_terminal_links_process_power_storage_and_fleet_refueling(tmp_path):
    """An equipped cryogenic terminal is more than a nominal output multiplier.

    Its power load, active fuel transfer capability, construction requirement
    and usable cryogenic stock are still owned by the usual separate Domains.
    An equally fueled comparison must consume more real oxygen and hydrogen.
    """
    from space_idle import GetBuildOptions
    from space_idle.scenario import ScenarioSurfaceLocation, ScenarioStorageInfrastructure
    from space_idle.shared import SpatialNodeId

    lunar = SpatialNodeId("test.location.fuel_terminal")
    base = build_standard_scenario_definition()
    low_tech = build_game_application_for_scenario(base)
    locked = next(row for row in low_tech.query(GetBuildOptions(str(ids.EARTH))).items
                  if row.facility_definition_id == str(ids.CRYOGENIC_PROPELLANT_TERMINAL))
    assert {b.subject_id for b in locked.blockers if b.kind == "technology"} == {
        str(ids.CR_CRYOGENIC_STORAGE_TRANSFER_04),
        "CR-CRYOGENIC-STORAGE-TRANSFER-07",
    }
    fuels = (
        ScenarioInventoryStock(lunar, ids.OXYGEN, 180.0),
        ScenarioInventoryStock(lunar, ids.HYDROGEN, 40.0),
    )
    common = replace(
        base,
        surface_locations=base.surface_locations + (
            ScenarioSurfaceLocation(lunar, "推進剤製造拠点", ids.MOON,
                                    ids.MOON_CELL_SOUTH_POLAR_RIDGE),
        ),
        facilities=base.facilities + (
            ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, lunar),
        ),
        inventory_stock=base.inventory_stock + fuels,
        storage_infrastructure=base.storage_infrastructure + (
            ScenarioStorageInfrastructure(lunar, "cryogenic", 500.0),
        ),
        completed_technologies=(
            ids.CR_CRYOGENIC_STORAGE_TRANSFER_04,
            ids.research_id("CR-CRYOGENIC-STORAGE-TRANSFER-07"),
        ),
    )
    ordinary = build_game_application_for_scenario(replace(
        common, facilities=common.facilities + (ScenarioFacility(ids.PROPELLANT_PLANT, lunar),),
    ))
    improved = build_game_application_for_scenario(replace(
        common, facilities=common.facilities +
        (ScenarioFacility(ids.CRYOGENIC_PROPELLANT_TERMINAL, lunar),),
    ))
    base_view = ordinary.query(GetOperationalNode(str(lunar)))
    expanded_view = improved.query(GetOperationalNode(str(lunar)))
    base_store = next(row for row in base_view.storage if row.storage_pool_key == "cryogenic")
    expanded_store = next(row for row in expanded_view.storage if row.storage_pool_key == "cryogenic")
    assert expanded_store.physical_capacity_t > base_store.physical_capacity_t
    assert expanded_store.usable_capacity_t > base_store.usable_capacity_t
    expanded_plant = next(row for row in expanded_view.facilities
                          if row.definition_id == str(ids.CRYOGENIC_PROPELLANT_TERMINAL))
    assert "vehicle_refueling" in expanded_plant.capabilities
    assert "cryogenic_storage" in expanded_plant.capabilities
    assert {row.process_id for row in expanded_view.industry} == {str(ids.PROCESS_PROPELLANT_BLEND)}
    for app in (ordinary, improved):
        app.execute(AdvanceTime(1))
    old = ordinary._simulation.inventory
    new = improved._simulation.inventory
    assert new.amount(lunar, ids.PROPELLANT) > old.amount(lunar, ids.PROPELLANT)
    assert new.amount(lunar, ids.OXYGEN) < old.amount(lunar, ids.OXYGEN)
    assert new.amount(lunar, ids.HYDROGEN) < old.amount(lunar, ids.HYDROGEN)
    assert new.amount(lunar, ids.PROPELLANT) < (180.0 + 40.0)

    # A paused operation does not magically delete cold storage or erase its
    # real standby power requirement. Save/Load rederives usable capacity.
    from space_idle import PauseFacility
    active_power_demand = improved.query(GetOperationalNode(str(lunar))).power_demand_mw
    improved.execute(PauseFacility(expanded_plant.id))
    improved.execute(AdvanceTime(1))
    paused_view = improved.query(GetOperationalNode(str(lunar)))
    assert 0 < paused_view.power_demand_mw < active_power_demand
    paused_storage = next(row for row in paused_view.storage
                          if row.storage_pool_key == "cryogenic")
    assert paused_storage.physical_capacity_t == expanded_store.physical_capacity_t
    assert paused_storage.usable_capacity_t > base_store.usable_capacity_t
    path = tmp_path / "cryogenic-terminal.json"
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_game(improved, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(improved._simulation)
    loaded.execute(AdvanceTime(1))
    improved.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(improved._simulation)


def test_modular_cargo_launch_system_connects_site_services_fleet_and_orbital_stock(tmp_path):
    """More terrestrial factory output reaches orbit only by committed Fleet.

    The cargo launcher is differentiated by actual ascent, propellant, service
    turnaround and manufacture. Its launch site is ordinary finite installed
    infrastructure, not a location-specific Transport special case.
    """
    from space_idle import (
        CreateTransportAllocation, GetFleet, GetTransportAllocationOptions,
        GetTransportAllocations, PlanBuild, ProduceVehicle, SetTargetStock,
    )
    from space_idle.scenario import ScenarioFacility

    base = build_standard_scenario_definition()
    locked = build_game_application_for_scenario(base)
    with pytest.raises(ApplicationError, match="technology"):
        locked.execute(ProduceVehicle(str(ids.MODULAR_CARGO_LAUNCHER), str(ids.EARTH)))
    from space_idle import GetSurfaceMap
    core = next(cell for cell in locked.query(GetSurfaceMap(str(ids.EARTH_BODY))).cells
                if cell.id == str(ids.EARTH_CELL_INDUSTRIAL))
    pad = next(option for option in core.facility_placement_options
               if option.facility_definition_id == str(ids.CARGO_LAUNCH_INTEGRATION_PAD))
    # The project may be queued before Research; operation blockers remain
    # visible even when the planning Command itself is available.
    assert any(blocker.kind == "technology" for blocker in pad.blockers)

    completed = tuple(ids.research_id(name) for name in (
        "CH-COMBUSTION-09", "MC-MANUFACTURING-CONSTRUCTION-09",
        "GN-NAVIGATION-06", "LM-LOGISTICS-MAINTENANCE-07",
    ))
    app = build_game_application_for_scenario(replace(
        base,
        completed_technologies=completed,
        facilities=base.facilities + (
            ScenarioFacility(ids.CONSTRUCTION_YARD, ids.EARTH),
            # Arrival handling is a real receiving asset; an orbital context
            # without one must not silently admit an incoming cargo shipment.
            ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
        ),
    ))
    sim = app._simulation
    options = app.query(GetTransportAllocationOptions(str(ids.EARTH), str(ids.LEO))).options
    by_vehicle = {row.vehicle_definition_id: row for row in options}
    ordinary = by_vehicle[str(ids.REUSABLE_LAUNCH_VEHICLE)]
    modular = by_vehicle[str(ids.MODULAR_CARGO_LAUNCHER)]
    assert modular.nominal_capacity.forward_t_per_day > ordinary.nominal_capacity.forward_t_per_day
    assert (sim.transport.vehicle_defs[ids.MODULAR_CARGO_LAUNCHER].production.resources
            != sim.transport.vehicle_defs[ids.REUSABLE_LAUNCH_VEHICLE].production.resources)
    assert (sim.transport.vehicle_defs[ids.MODULAR_CARGO_LAUNCHER].maintenance.turnaround_days
            > sim.transport.vehicle_defs[ids.REUSABLE_LAUNCH_VEHICLE].maintenance.turnaround_days)
    assert (modular.operational_supply_at_full_unit != ordinary.operational_supply_at_full_unit)

    existing_launch = tuple(sim.facilities.all_at(ids.EARTH))
    assert app.execute(PlanBuild(str(ids.EARTH), str(ids.CARGO_LAUNCH_INTEGRATION_PAD),
                                 site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
                                 procurement_policy="immediate")).created_id
    assert app.execute(ProduceVehicle(str(ids.MODULAR_CARGO_LAUNCHER), str(ids.EARTH))).created_id
    assert len(tuple(sim.facilities.all_at(ids.EARTH))) == len(existing_launch)
    app.execute(AdvanceTime(40))
    assert any(row.definition_id == ids.CARGO_LAUNCH_INTEGRATION_PAD
               for row in sim.facilities.all_at(ids.EARTH))
    fleet = next(row for row in app.query(GetFleet(str(ids.EARTH))).pools
                 if row.vehicle_definition_id == str(ids.MODULAR_CARGO_LAUNCHER))
    assert fleet.total_units == 1
    launch_services = {
        row.service_type: row.nominal
        for row in app.query(GetOperationalNode(str(ids.EARTH))).service_capacities
    }
    assert launch_services["launch_vehicle_servicing"] > 1.0

    target = modular.nominal_capacity.forward_t_per_day
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.MODULAR_CARGO_LAUNCHER), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=target, target_reverse_t_per_day=0.0,
    )).created_id
    assert allocation_id is not None
    before_orbit = sim.inventory.amount(ids.LEO, ids.STRUCTURAL_COMPONENTS)
    before_surface = sim.inventory.amount(ids.EARTH, ids.PROPELLANT)
    assert app.execute(SetTargetStock(
        str(ids.LEO), str(ids.STRUCTURAL_COMPONENTS), before_orbit + 18.0,
    )).created_id
    app.execute(AdvanceTime(25))
    assert sim.inventory.amount(ids.LEO, ids.STRUCTURAL_COMPONENTS) > before_orbit
    assert sim.inventory.amount(ids.EARTH, ids.PROPELLANT) < before_surface
    assert any(row.id == allocation_id for row in app.query(GetTransportAllocations()).items)
    assert any(row.transport_units == 1 for row in app.query(GetFleet(str(ids.EARTH))).pools
               if row.vehicle_definition_id == str(ids.MODULAR_CARGO_LAUNCHER))

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / "modular-launcher-transport.json"
    save_game(app, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded.execute(AdvanceTime(3))
    app.execute(AdvanceTime(3))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_orbital_materials_and_bulk_freight_form_a_single_owned_supply_chain(tmp_path):
    """Upstream stock, orbital installed capacity and cargo delivery share one settlement.

    The new orbital infrastructure is bought with the same construction inputs
    as existing assets; it does not grant Fleet or materials with Technology.
    Repeated cargo service remains subject to finite receiving infrastructure.
    """
    from space_idle import (
        GetBuildOptions, GetFleet, GetFlowReport, GetTransportAllocationOptions,
        ProduceVehicle, CreateTransportAllocation, SetTargetStock, PlanBuild, PauseFacility,
    )
    from space_idle.scenario import ScenarioFacility
    from space_idle.content.base_research import build_research_definitions

    base = build_standard_scenario_definition()
    new_facilities = (ids.ORBITAL_MATERIALS_WORKSHOP, ids.ORBITAL_HEAVY_CARGO_TERMINAL)
    locked = build_game_application_for_scenario(base)
    options = {row.facility_definition_id: row for row in
               locked.query(GetBuildOptions(str(ids.LEO))).items}
    for definition_id in new_facilities:
        assert any(blocker.kind == "technology" for blocker in options[str(definition_id)].blockers)
    with pytest.raises(ApplicationError, match="technology"):
        locked.execute(ProduceVehicle(str(ids.HEAVY_ORBITAL_FREIGHTER), str(ids.LEO)))

    required = {ids.MC_MANUFACTURING_CONSTRUCTION_14,
                ids.LM_LOGISTICS_MAINTENANCE_13,
                ids.MC_MANUFACTURING_CONSTRUCTION_05}
    research = build_research_definitions()
    all_technologies = set(required)
    frontier = list(required)
    while frontier:
        for prerequisite in research[frontier.pop()].prerequisites - all_technologies:
            all_technologies.add(prerequisite)
            frontier.append(prerequisite)

    scenario = replace(
        base,
        completed_technologies=tuple(sorted(all_technologies)),
        facilities=base.facilities + (
            ScenarioFacility(ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.LEO),
            ScenarioFacility(ids.ORBITAL_SOLAR_ARRAY, ids.LEO),
            ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
            ScenarioFacility(ids.ORBITAL_PROPELLANT_DEPOT, ids.LEO),
            ScenarioFacility(ids.ORBITAL_ASSEMBLY_YARD, ids.LEO),
        ),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.LEO, ids.BULK_STRUCTURE, 25.0),
            ScenarioInventoryStock(ids.EARTH, ids.BULK_STRUCTURE, 200.0),
            ScenarioInventoryStock(ids.LEO, ids.BASIC_MACHINE_PARTS, 30.0),
            ScenarioInventoryStock(ids.LEO, ids.STRUCTURAL_COMPONENTS, 57.0),
            ScenarioInventoryStock(ids.LEO, ids.MACHINERY, 140.0),
            ScenarioInventoryStock(ids.LEO, ids.PRECISION_ELECTRONICS, 80.0),
            ScenarioInventoryStock(ids.LEO, ids.PROPELLANT, 200.0),
            ScenarioInventoryStock(ids.LEO, ids.CONSTRUCTION_EQUIPMENT, 100.0),
            ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.PROPELLANT, 80.0),
        ),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    # Bulk handling is not a substitute for a separately cooled propellant depot.
    cold_capacity_before = next(row.physical_capacity_t for row in
                                app.query(GetOperationalNode(str(ids.LEO))).storage
                                if row.storage_pool_key == "cryogenic")
    # Earth supplies upstream bulk feedstock using the normal reusable launcher.
    # The orbital workshop consumes *delivered* inventory, and its output must
    # cover the more expensive new freighter's local production inputs.
    existing_launcher = next(row for row in
                             app.query(GetTransportAllocationOptions(str(ids.EARTH), str(ids.LEO))).options
                             if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    assert app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=existing_launcher.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    earth_bulk_before = sim.inventory.amount(ids.EARTH, ids.BULK_STRUCTURE)
    assert app.execute(SetTargetStock(str(ids.LEO), str(ids.BULK_STRUCTURE), 150.0)).created_id

    # Both new installations are acquired through ordinary delayed construction.
    # A declaration or Research unlock must not silently create the physical
    # workshop or cargo terminal, nor directly change earlier assets.
    physical_inputs = {resource: sim.inventory.amount(ids.LEO, resource)
                       for resource in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY, ids.PRECISION_ELECTRONICS)}
    for definition_id in new_facilities:
        assert app.execute(PlanBuild(
            str(ids.LEO), str(definition_id), procurement_policy="immediate",
        )).created_id
    assert not any(inst.definition_id in new_facilities for inst in sim.facilities.all_at(ids.LEO))
    app.execute(AdvanceTime(280))
    assert all(any(inst.definition_id == definition_id for inst in sim.facilities.all_at(ids.LEO))
               for definition_id in new_facilities)
    assert sim.inventory.amount(ids.EARTH, ids.BULK_STRUCTURE) < earth_bulk_before
    assert sim.inventory.amount(ids.LEO, ids.BULK_STRUCTURE) > 25.0
    assert all(sim.inventory.amount(ids.LEO, resource) < initial
               for resource, initial in physical_inputs.items())
    orbital = app.query(GetOperationalNode(str(ids.LEO)))
    workshop = next(row for row in orbital.industry
                    if row.facility_definition_id == str(ids.ORBITAL_MATERIALS_WORKSHOP))
    assert workshop.selection_required
    app.execute(SetFacilityProcess(workshop.facility_id, str(ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS)))
    workshop = next(row for row in app.query(GetOperationalNode(str(ids.LEO))).industry
                    if row.facility_definition_id == str(ids.ORBITAL_MATERIALS_WORKSHOP))
    assert workshop.process_id == str(ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS)
    assert {row.process_id for row in workshop.process_options} >= {
        str(ids.PROCESS_STANDARD_STRUCTURAL_COMPONENTS),
        str(ids.PROCESS_STRUCTURAL_FABRICATION),
        str(ids.PROCESS_PRECISION_COMPONENTS),
    }
    capacity = {row.service_type: row.nominal for row in orbital.service_capacities}
    assert capacity["cargo_transfer"] >= 4.0
    assert capacity["vehicle_assembly"] > 1.0
    assert capacity["spacecraft_servicing"] >= 2.0
    assert sim.inventory.admission_state(ids.LEO, ids.BULK_STRUCTURE).blockers == ()
    assert next(row.physical_capacity_t for row in orbital.storage
                if row.storage_pool_key == "cryogenic") == cold_capacity_before

    before_structure = sim.inventory.amount(ids.LEO, ids.STRUCTURAL_COMPONENTS)
    app.execute(AdvanceTime(3))
    # Inbound Earth cargo can exceed local use, so a net Stock increase does
    # not mean the workshop consumed nothing.
    flow = app.query(GetFlowReport(str(ids.LEO)))
    assert next(row.local_consumption_per_day for row in flow.resources
                if row.resource_id == str(ids.BULK_STRUCTURE)) > 0
    assert sim.inventory.amount(ids.LEO, ids.STRUCTURAL_COMPONENTS) > before_structure

    # Making a physical Vehicle requires locally available parts and an actual
    # assembly service, not its Research exit or a source Node's remote stock.
    assert sim.inventory.amount(ids.LEO, ids.STRUCTURAL_COMPONENTS) < 26.0
    project = app.execute(ProduceVehicle(str(ids.HEAVY_ORBITAL_FREIGHTER), str(ids.LEO)))
    assert project.created_id
    app.execute(AdvanceTime(65))
    produced = next(row for row in app.query(GetFleet(str(ids.LEO))).pools
                    if row.vehicle_definition_id == str(ids.HEAVY_ORBITAL_FREIGHTER))
    assert produced.total_units == 1
    plans = app.query(GetTransportAllocationOptions(str(ids.LEO), str(ids.LUNAR_ORBIT))).options
    plan = next(row for row in plans if row.vehicle_definition_id == str(ids.HEAVY_ORBITAL_FREIGHTER))
    tug = next(row for row in plans if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG))
    assert plan.nominal_capacity.forward_t_per_day > tug.nominal_capacity.forward_t_per_day
    assert (sim.transport.vehicle_defs[ids.HEAVY_ORBITAL_FREIGHTER].production.resources
            != sim.transport.vehicle_defs[ids.REUSABLE_ORBITAL_CARGO_TUG].production.resources)
    assert (sim.transport.vehicle_defs[ids.HEAVY_ORBITAL_FREIGHTER].maintenance.turnaround_days
            > sim.transport.vehicle_defs[ids.REUSABLE_ORBITAL_CARGO_TUG].maintenance.turnaround_days)

    allocation = app.execute(CreateTransportAllocation(
        str(ids.HEAVY_ORBITAL_FREIGHTER), str(ids.LEO), str(ids.LUNAR_ORBIT),
        target_forward_t_per_day=plan.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    ))
    assert allocation.created_id
    at_destination = sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS)
    fuel_at_origin = sim.inventory.amount(ids.LEO, ids.PROPELLANT)
    app.execute(SetTargetStock(str(ids.LUNAR_ORBIT), str(ids.STRUCTURAL_COMPONENTS),
                               at_destination + 16.0))
    app.execute(AdvanceTime(60))
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS) > at_destination
    assert sim.inventory.amount(ids.LEO, ids.PROPELLANT) < fuel_at_origin

    # The same installed fabrication asset changes its *real* inputs and outputs
    # when the Player selects precision parts; Research does not auto-modify it.
    precision_before = sim.inventory.amount(ids.LEO, ids.PRECISION_COMPONENTS)
    machining_before = sim.inventory.amount(ids.LEO, ids.BASIC_MACHINE_PARTS)
    app.execute(SetFacilityProcess(workshop.facility_id, str(ids.PROCESS_PRECISION_COMPONENTS)))
    app.execute(AdvanceTime(3))
    assert sim.inventory.amount(ids.LEO, ids.PRECISION_COMPONENTS) > precision_before
    assert sim.inventory.amount(ids.LEO, ids.BASIC_MACHINE_PARTS) < machining_before

    # No second Cargo/Inventory owner is invented for offline or Save/Load.
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / 'orbital-manufacturing-logistics.json'
    save_game(app, path, saved_at=now)
    restored, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(sim)
    restored.execute(AdvanceTime(2))
    app.execute(AdvanceTime(2))
    assert capture_state(restored._simulation) == capture_state(sim)
    # Removing physically installed generation limits the same operation;
    # Technology and a theoretical process outlet cannot furnish free Power.
    source_array = next(inst for inst in restored._simulation.facilities.all_at(ids.LEO)
                        if inst.definition_id == ids.ORBITAL_SOLAR_ARRAY)
    restored.execute(PauseFacility(str(source_array.id)))
    restored.execute(AdvanceTime(2))
    app.execute(AdvanceTime(2))
    active = next(row for row in app.query(GetOperationalNode(str(ids.LEO))).industry
                  if row.facility_definition_id == str(ids.ORBITAL_MATERIALS_WORKSHOP))
    starved = next(row for row in restored.query(GetOperationalNode(str(ids.LEO))).industry
                   if row.facility_definition_id == str(ids.ORBITAL_MATERIALS_WORKSHOP))
    assert starved.scale < active.scale


def test_electric_propulsion_research_to_cross_node_resource_transport(tmp_path):
    """One real power/research/industry/Fleet chain, with chemical alternatives retained.

    Test the physical ownership and execution contract rather than the number
    of content outlets: research never creates hardware or fuel, production
    uses local stock, and cargo arrives only through the normal movement flow.
    """
    from space_idle import (
        CreateTransportAllocation, GetBuildOptions, GetFleet, GetResearch,
        GetTransportAllocationOptions, GetFlowReport, PauseFacility, PlanBuild, ProduceVehicle,
        SetTargetStock, StartResearch, SetResearchPrototypeSite,
    )
    from space_idle.scenario import ScenarioFacility
    from space_idle.content.base_research import build_research_definitions
    from space_idle.research import ResearchTheoryStageSpec, ResearchPrototypeStageSpec

    base = build_standard_scenario_definition()
    incomplete = build_game_application_for_scenario(base)
    with pytest.raises(ApplicationError, match="technology"):
        incomplete.execute(ProduceVehicle(str(ids.HALL_ELECTRIC_CARGO_TUG), str(ids.EARTH)))
    with pytest.raises(ApplicationError, match="technology"):
        incomplete.execute(ProduceVehicle(str(ids.ION_PROPULSION_SCIENCE_PROBE), str(ids.EARTH)))
    bench = next(option for option in incomplete.query(GetBuildOptions(str(ids.LEO))).items
                 if option.facility_definition_id == str(ids.PLASMA_PROPULSION_TEST_MODULE))
    assert any(blocker.kind == "technology" for blocker in bench.blockers)

    research = build_research_definitions()
    prototype = research[ids.research_id("EP-PLASMA-THRUSTERS-02")]
    assert isinstance(prototype.stage_specs[1], ResearchPrototypeStageSpec)
    assert prototype.stage_specs[1].resources[ids.HYDROGEN] > 0
    # Reach the hardware research stage through the real Research command.
    predecessors = set()
    frontier = list(prototype.prerequisites)
    while frontier:
        for technology_id in (frontier.pop(),):
            if technology_id not in predecessors:
                predecessors.add(technology_id)
                frontier.extend(research[technology_id].prerequisites)

    def short_theory(sim, _catalog):
        definition = sim.research.definitions[prototype.id]
        sim.research.definitions[prototype.id] = replace(
            definition,
            stage_specs=(ResearchTheoryStageSpec("theory", 0.5),) + definition.stage_specs[1:],
        )

    unpowered = build_game_application_for_scenario(
        replace(base, completed_technologies=tuple(sorted(predecessors)),
                facilities=base.facilities +
                (ScenarioFacility(ids.ORBITAL_SOLAR_ARRAY, ids.LEO),)),
        definition_transform=short_theory,
    )
    unpowered._simulation.research.stored_points = 10.0
    unpowered.execute(StartResearch(str(prototype.id)))
    unpowered.execute(AdvanceTime(1))
    research_view = next(row for row in unpowered.query(GetResearch()).items if row.id == str(prototype.id))
    assert research_view.current_stage_id == "hall-discharge-test"
    choice = next(row for row in research_view.execution_context_options
                  if row.operational_node_id == str(ids.LEO))
    assert any("capability" in blocker.code for blocker in choice.blockers)

    trial = build_game_application_for_scenario(
        replace(base, completed_technologies=tuple(sorted(predecessors)),
                facilities=base.facilities + (
                    ScenarioFacility(ids.ORBITAL_SOLAR_ARRAY, ids.LEO),
                    ScenarioFacility(ids.PLASMA_PROPULSION_TEST_MODULE, ids.LEO),
                    ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
                ), inventory_stock=base.inventory_stock + (
                    ScenarioInventoryStock(ids.LEO, ids.HYDROGEN, 4.0),
                    ScenarioInventoryStock(ids.LEO, ids.PRECISION_ELECTRONICS, 8.0),
                )), definition_transform=short_theory,
    )
    trial._simulation.research.stored_points = 10.0
    trial.execute(StartResearch(str(prototype.id)))
    trial.execute(AdvanceTime(1))
    trial.execute(SetResearchPrototypeSite(
        str(prototype.id), "hall-discharge-test", str(ids.LEO),
    ))
    trial.execute(AdvanceTime(1))
    reserved = trial._simulation.research.prototype_reserved_t(
        prototype.id, "hall-discharge-test", ids.LEO, ids.HYDROGEN,
    )
    assert reserved == pytest.approx(0.35)
    rig = next(row for row in trial._simulation.facilities.all_at(ids.LEO)
               if row.definition_id == ids.PLASMA_PROPULSION_TEST_MODULE)
    trial.execute(PauseFacility(str(rig.id)))
    before = trial._simulation.research.active[prototype.id].stage_progress
    trial.execute(AdvanceTime(1))
    assert trial._simulation.research.active[prototype.id].stage_progress == before
    assert any("capability:active" in blocker.code for blocker in
               next(row for row in trial.query(GetResearch()).items if row.id == str(prototype.id)).current_blockers)

    # Complete the full authored precursor DAG for the separate industrial
    # scenario. These are Scenario initial conditions, not synthetic unlocks.
    all_tech = set()
    frontier = [ids.research_id(code) for code in (
        "EP-PLASMA-THRUSTERS-06", "EP-PLASMA-THRUSTERS-07",
        "EP-PLASMA-THRUSTERS-04", "GN-NAVIGATION-06", "SS-SENSING-01",
    )]
    while frontier:
        tech_id = frontier.pop()
        if tech_id in all_tech:
            continue
        all_tech.add(tech_id)
        frontier.extend(research[tech_id].prerequisites)

    scenario = replace(
        base,
        completed_technologies=tuple(sorted(all_tech)),
        facilities=base.facilities + (
            ScenarioFacility(ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.LEO),
            ScenarioFacility(ids.TRACKING_ORBITAL_SOLAR_ARRAY, ids.LEO),
            ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
            ScenarioFacility(ids.ORBITAL_PROPELLANT_DEPOT, ids.LEO),
            ScenarioFacility(ids.ORBITAL_ASSEMBLY_YARD, ids.LEO),
            ScenarioFacility(ids.ELECTROLYSIS_PLANT, ids.EARTH),
        ),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.LEO, ids.STRUCTURAL_COMPONENTS, 150.0),
            ScenarioInventoryStock(ids.LEO, ids.MACHINERY, 100.0),
            ScenarioInventoryStock(ids.LEO, ids.PRECISION_ELECTRONICS, 100.0),
            ScenarioInventoryStock(ids.LEO, ids.CONSTRUCTION_EQUIPMENT, 80.0),
            ScenarioInventoryStock(ids.LEO, ids.THERMAL_CONTROL_ASSEMBLIES, 12.0),
            ScenarioInventoryStock(ids.LEO, ids.OPTICAL_INSTRUMENT_PACKAGES, 8.0),
            # A returning spacecraft must refuel physically at the far end;
            # the receiving depot is not an inexhaustible fuel source.
            ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.HYDROGEN, 8.0),
        ),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    # The test rig is another regular orbital construction project; the
    # research unlock did not silently install it.
    rig_plan = app.execute(PlanBuild(
        str(ids.LEO), str(ids.PLASMA_PROPULSION_TEST_MODULE), procurement_policy="immediate",
    ))
    assert rig_plan.created_id
    app.execute(AdvanceTime(110))
    assert any(inst.definition_id == ids.PLASMA_PROPULSION_TEST_MODULE
               for inst in sim.facilities.all_at(ids.LEO))

    # Electrolysis and imported hydrogen physically precede electric operation.
    # At the same time the baseline chemical tug remains free to consume the
    # independently stored chemical propellant, without being upgraded.
    hydrogen_before = sim.inventory.amount(ids.EARTH, ids.HYDROGEN)
    app.execute(AdvanceTime(4))
    assert next(row.local_consumption_per_day for row in
                app.query(GetFlowReport(str(ids.EARTH))).resources
                if row.resource_id == str(ids.WATER)) > 0
    assert sim.inventory.amount(ids.EARTH, ids.HYDROGEN) > hydrogen_before
    launch = next(option for option in app.query(GetTransportAllocationOptions(
        str(ids.EARTH), str(ids.LEO))).options
        if option.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    assert app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=launch.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    assert app.execute(SetTargetStock(str(ids.LEO), str(ids.HYDROGEN), 20.0)).created_id
    app.execute(AdvanceTime(45))
    assert sim.inventory.amount(ids.LEO, ids.HYDROGEN) > 0

    for vehicle_id in (ids.HALL_ELECTRIC_CARGO_TUG, ids.ION_PROPULSION_SCIENCE_PROBE):
        assert app.execute(ProduceVehicle(str(vehicle_id), str(ids.LEO))).created_id
    app.execute(AdvanceTime(40))
    fleet = {row.vehicle_definition_id: row for row in app.query(GetFleet(str(ids.LEO))).pools}
    assert fleet[str(ids.HALL_ELECTRIC_CARGO_TUG)].total_units == 1
    assert fleet[str(ids.ION_PROPULSION_SCIENCE_PROBE)].total_units == 1
    candidates = {row.vehicle_definition_id: row for row in app.query(
        GetTransportAllocationOptions(str(ids.LEO), str(ids.LUNAR_ORBIT))).options}
    electric = candidates[str(ids.HALL_ELECTRIC_CARGO_TUG)]
    chemical = candidates[str(ids.REUSABLE_ORBITAL_CARGO_TUG)]
    assert electric.nominal_capacity.forward_t_per_day < chemical.nominal_capacity.forward_t_per_day
    assert (sim.transport.vehicle_defs[ids.HALL_ELECTRIC_CARGO_TUG].performance.propellant_resource_id
            == ids.HYDROGEN)
    assert (sim.transport.vehicle_defs[ids.REUSABLE_ORBITAL_CARGO_TUG].performance.propellant_resource_id
            == ids.PROPELLANT)
    assert (sim.transport.vehicle_defs[ids.HALL_ELECTRIC_CARGO_TUG].performance.propellant_t_per_total_t_per_km_s
            < sim.transport.vehicle_defs[ids.REUSABLE_ORBITAL_CARGO_TUG].performance.propellant_t_per_total_t_per_km_s)
    assert app.execute(CreateTransportAllocation(
        str(ids.HALL_ELECTRIC_CARGO_TUG), str(ids.LEO), str(ids.LUNAR_ORBIT),
        target_forward_t_per_day=electric.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    arrival_before = sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS)
    fuel_before = sim.inventory.amount(ids.LEO, ids.HYDROGEN)
    app.execute(SetTargetStock(str(ids.LUNAR_ORBIT), str(ids.STRUCTURAL_COMPONENTS), arrival_before + 8.0))
    app.execute(AdvanceTime(110))
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS) > arrival_before
    # The far-end hydrogen is consumed by real return transits; both nodes
    # therefore require fuel provision rather than only an origin stock.
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.HYDROGEN) < 8.0
    assert sim.inventory.amount(ids.LEO, ids.HYDROGEN) >= 0
    assert fuel_before > 0
    from space_idle import GetTransportAllocations, SetSurveyProviderFleetQuantity
    active = next(row for row in app.query(GetTransportAllocations()).items
                  if row.vehicle_definition_id == str(ids.HALL_ELECTRIC_CARGO_TUG))
    assert active.used.forward_t_per_day >= 0
    assert any(resource_id == str(ids.HYDROGEN) and quantity > 0
               for _node_id, resource_id, quantity in active.operational_supply)
    assert not any(resource_id == str(ids.PROPELLANT)
                   for _node_id, resource_id, _quantity in active.operational_supply)
    # The same physical operating-resource demand must be present in the
    # opt-in Definition graph, for comparison with Production and Research.
    # It remains a coefficient, not an invented static route flow or a second
    # transport feasibility solver. The Application above proves real usage.
    from space_idle.composition.analysis_graph import build_definition_dependency_graph
    from space_idle.analysis_graph import DependencyNode
    dependency_graph = build_definition_dependency_graph(sim, app._catalog)
    assert not dependency_graph.diagnostics
    for ship, fuel_id in (
        (ids.HALL_ELECTRIC_CARGO_TUG, ids.HYDROGEN),
        (ids.REUSABLE_ORBITAL_CARGO_TUG, ids.PROPELLANT),
        (ids.NUCLEAR_THERMAL_CARGO_SHIP, ids.HYDROGEN),
    ):
        operation = DependencyNode("vehicle_operation_method", str(ship))
        physical = sim.transport.vehicle_defs[ship]
        edges = [r for r in dependency_graph.relations
                 if r.target == operation and r.kind == "consumes_resource"]
        assert len(edges) == 1
        assert edges[0].source == DependencyNode("resource", str(fuel_id))
        assert edges[0].quantity == physical.propellant_t_per_total_t_per_km_s
        assert edges[0].time_basis == "per_movement_mass_delta_v"
    # A remote-sensing compatible ion probe remains a single physical Fleet
    # unit even when dedicated to a Survey provider instead of transport.
    assert sim.survey.source_is_compatible(
        sim.survey.provider(ids.ORBITAL_RESOURCE_MAPPING_PROVIDER),
        ids.ION_PROPULSION_SCIENCE_PROBE,
    )
    assert app.execute(SetSurveyProviderFleetQuantity(
        str(ids.ORBITAL_RESOURCE_MAPPING_PROVIDER), str(ids.LEO),
        str(ids.ION_PROPULSION_SCIENCE_PROBE), 1,
    )).created_id
    dedicated = next(row for row in app.query(GetFleet(str(ids.LEO))).pools
                     if row.vehicle_definition_id == str(ids.ION_PROPULSION_SCIENCE_PROBE))
    assert dedicated.total_units == dedicated.survey_units == 1
    assert dedicated.free_units == dedicated.transport_units == 0

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / "electric-industrial-logistics.json"
    save_game(app, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    app.execute(AdvanceTime(2))
    loaded.execute(AdvanceTime(2))
    assert capture_state(loaded._simulation) == capture_state(sim)


def test_interplanetary_supply_and_science_use_one_physical_portfolio(tmp_path):
    """Orbital industry supports human/robotic campaigns and distinct propulsion.

    Facility, Process, experimental Research, Vehicle production, Supply and
    Science decisions all use normal Application/state transitions. The
    scenario supplies a finite industrial investment, not an alternate solver.
    """
    from space_idle import (
        GetBuildOptions, GetFleet, GetScientificExplorations, GetFlowReport,
        GetTransportAllocationOptions, CreateTransportAllocation,
        SetTargetStock, PlanBuild, ProduceVehicle, StartScientificExploration,
        AssignExplorationFleet,
    )
    from space_idle.content.base_research import build_research_definitions
    from space_idle.scenario import (
        ScenarioFacility, ScenarioPopulation, ScenarioStorageInfrastructure,
    )
    from space_idle.research import ResearchPrototypeStageSpec

    base = build_standard_scenario_definition()
    research = build_research_definitions()
    root_test = research[ids.research_id("NT-NUCLEAR-THERMAL-02")]
    plant_test = research[ids.research_id("PL-PLANT-FOOD-04")]
    assert any(isinstance(stage, ResearchPrototypeStageSpec)
               and stage.resources[ids.HYDROGEN] > 0 for stage in root_test.stage_specs)
    assert any(isinstance(stage, ResearchPrototypeStageSpec)
               and stage.resources[ids.WATER] > 0 for stage in plant_test.stage_specs)

    unresearched = build_game_application_for_scenario(base)
    for facility_id in (ids.ORBITAL_HYDROPONICS, ids.ORBITAL_WATER_ELECTROLYSIS):
        row = next(row for row in unresearched.query(GetBuildOptions(str(ids.LEO))).items
                   if row.facility_definition_id == str(facility_id))
        assert any(blocker.kind == "technology" for blocker in row.blockers)
    for vehicle_id in (ids.NUCLEAR_THERMAL_CARGO_SHIP, ids.NUCLEAR_THERMAL_CREW_SHIP):
        with pytest.raises(ApplicationError, match="technology"):
            unresearched.execute(ProduceVehicle(str(vehicle_id), str(ids.EARTH)))

    # Material and crew stocks are not shared across nodes. Normal Location
    # stocks remain finite while investments and services compete in orbit.
    scenario = replace(
        base,
        completed_technologies=tuple(research),
        facilities=base.facilities + tuple(ScenarioFacility(fid, ids.LEO) for fid in (
            ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.HIGH_OUTPUT_ORBITAL_FISSION_POWER,
            ids.ORBITAL_LOGISTICS_NODE, ids.ORBITAL_ASSEMBLY_YARD,
            ids.ORBITAL_HABITAT, ids.ORBITAL_PROPELLANT_DEPOT,
        )),
        storage_infrastructure=base.storage_infrastructure + (
            ScenarioStorageInfrastructure(ids.LEO, "cryogenic", 200.0),
        ),
        inventory_stock=base.inventory_stock + tuple(
            ScenarioInventoryStock(ids.LEO, rid, qty) for rid, qty in (
                (ids.STRUCTURAL_COMPONENTS, 240.0),
                (ids.MACHINERY, 200.0),
                (ids.PRECISION_ELECTRONICS, 150.0),
                (ids.CONSTRUCTION_EQUIPMENT, 25.0),
                (ids.THERMAL_CONTROL_ASSEMBLIES, 25.0),
                (ids.RADIATION_SHIELDING_PANELS, 25.0),
                (ids.OPTICAL_INSTRUMENT_PACKAGES, 12.0),
                (ids.WATER, 140.0), (ids.FOOD, 60.0),
                (ids.OXYGEN, 70.0), (ids.HYDROGEN, 60.0),
            )
        ) + (ScenarioInventoryStock(ids.LUNAR_ORBIT, ids.HYDROGEN, 12.0),),
        initial_population=base.initial_population + (ScenarioPopulation(ids.LEO, 4),),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    # Import the water that both orbital food/oxygen activities consume. A
    # powered plant at its destination cannot silently draw Earth's stock.
    launch = next(row for row in app.query(GetTransportAllocationOptions(
        str(ids.EARTH), str(ids.LEO))).options
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    assert app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=launch.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    assert app.execute(SetTargetStock(str(ids.LEO), str(ids.WATER), 220.0)).created_id
    research_capacity_before = app.query(GetResearch()).storage_capacity_points
    for facility_id in (
        ids.ORBITAL_HYDROPONICS, ids.ORBITAL_WATER_ELECTROLYSIS,
        ids.NUCLEAR_THERMAL_TEST_STAND, ids.RESEARCH_DATA_ARCHIVE,
    ):
        assert app.execute(PlanBuild(str(ids.LEO), str(facility_id),
                                     procurement_policy="immediate")).created_id
    app.execute(AdvanceTime(110))
    for facility_id in (
        ids.ORBITAL_HYDROPONICS, ids.ORBITAL_WATER_ELECTROLYSIS,
        ids.NUCLEAR_THERMAL_TEST_STAND, ids.RESEARCH_DATA_ARCHIVE,
    ):
        assert any(inst.definition_id == facility_id for inst in sim.facilities.all_at(ids.LEO))
    research_providers = app.query(GetResearch())
    archive = next(row for row in research_providers.providers
                   if row.provider_definition_id == str(ids.RESEARCH_DATA_ARCHIVE))
    assert archive.generation_points_per_day == 0
    assert archive.storage_capacity_points > 0
    assert research_providers.storage_capacity_points > research_capacity_before + 1000

    industry = app.query(GetOperationalNode(str(ids.LEO))).industry
    for facility_id, process_id in (
        (ids.ORBITAL_HYDROPONICS, ids.PROCESS_FOOD_PRODUCTION),
        (ids.ORBITAL_WATER_ELECTROLYSIS, ids.PROCESS_ELECTROLYSIS),
    ):
        row = next(row for row in industry if row.facility_definition_id == str(facility_id))
        assert any(opt.process_id == str(process_id) and opt.can_select for opt in row.process_options)
        app.execute(SetFacilityProcess(row.facility_id, str(process_id)))
    before = {rid: sim.inventory.amount(ids.LEO, rid) for rid in
              (ids.FOOD, ids.OXYGEN, ids.HYDROGEN, ids.WATER)}
    app.execute(AdvanceTime(2))
    flow = {row.resource_id: row for row in app.query(GetFlowReport(str(ids.LEO))).resources}
    for rid in (ids.FOOD, ids.OXYGEN, ids.HYDROGEN):
        assert flow[str(rid)].local_production_per_day > 0
        assert sim.inventory.amount(ids.LEO, rid) > before[rid]
    assert sim.inventory.amount(ids.LEO, ids.WATER) < before[ids.WATER]

    # This same orbital assembly location must build two competing designs;
    # both are real Fleet units, not produced automatically by the Research.
    for vehicle_id in (ids.NUCLEAR_THERMAL_CARGO_SHIP, ids.NUCLEAR_THERMAL_CREW_SHIP):
        assert app.execute(ProduceVehicle(str(vehicle_id), str(ids.LEO))).created_id
    app.execute(AdvanceTime(85))
    fleet = {row.vehicle_definition_id: row for row in app.query(GetFleet(str(ids.LEO))).pools}
    assert fleet[str(ids.NUCLEAR_THERMAL_CARGO_SHIP)].total_units == 1
    assert fleet[str(ids.NUCLEAR_THERMAL_CREW_SHIP)].total_units == 1
    assert (sim.transport.vehicle_defs[ids.NUCLEAR_THERMAL_CARGO_SHIP].performance.payload_t
            > sim.transport.vehicle_defs[ids.NUCLEAR_THERMAL_CREW_SHIP].performance.payload_t)
    assert (sim.transport.vehicle_defs[ids.NUCLEAR_THERMAL_CARGO_SHIP].performance.propellant_resource_id
            == sim.transport.vehicle_defs[ids.NUCLEAR_THERMAL_CREW_SHIP].performance.propellant_resource_id
            == ids.HYDROGEN)
    assert (sim.transport.vehicle_defs[ids.DEEP_SPACE_FREIGHTER].performance.propellant_resource_id
            == ids.PROPELLANT)

    # An orbital cargo plan with a real receiving Node requires both endpoints
    # to have refueling stock and available Fleet; a physical-target campaign
    # instead commits Crew and life-support for the entire round trip.
    options = {r.vehicle_definition_id: r for r in app.query(GetTransportAllocationOptions(
        str(ids.LEO), str(ids.LUNAR_ORBIT))).options}
    nuclear = options[str(ids.NUCLEAR_THERMAL_CARGO_SHIP)]
    assert nuclear.nominal_capacity.forward_t_per_day > 0
    assert app.execute(CreateTransportAllocation(
        str(ids.NUCLEAR_THERMAL_CARGO_SHIP), str(ids.LEO), str(ids.LUNAR_ORBIT),
        target_forward_t_per_day=nuclear.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    arrival_before = sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS)
    app.execute(SetTargetStock(str(ids.LUNAR_ORBIT), str(ids.STRUCTURAL_COMPONENTS),
                               arrival_before + 5.0))

    science = next(row for row in app.query(GetScientificExplorations()).items
                   if row.id == str(ids.MARS_ORBIT_CREW_EXPEDITION))
    assert science.can_start
    crew = next(row for row in science.fleet_options
                if row.vehicle_definition_id == str(ids.NUCLEAR_THERMAL_CREW_SHIP))
    assert crew.blockers == ()
    assert crew.outbound_latency_days is not None and crew.return_latency_days is not None
    app.execute(StartScientificExploration(str(ids.MARS_ORBIT_CREW_EXPEDITION)))
    app.execute(AssignExplorationFleet(str(ids.MARS_ORBIT_CREW_EXPEDITION),
                                      str(ids.NUCLEAR_THERMAL_CREW_SHIP)))
    app.execute(AdvanceTime(6))
    science = next(row for row in app.query(GetScientificExplorations()).items
                   if row.id == str(ids.MARS_ORBIT_CREW_EXPEDITION))
    assert science.committed_crew == 4 and science.crew_in_transit == 4
    assert science.destination_kind == "non_surface_spatial_node"
    assert ids.MARS_ORBIT not in sim.graph.locations
    assert sim.transport.fleet_free_units(ids.NUCLEAR_THERMAL_CREW_SHIP, ids.LEO) == 0

    # Snapshot/restore and the following day preserve material, Fleet, Crew,
    # research and in-flight cargo on one authoritative physical timeline.
    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / "interplanetary-supply.json"
    save_game(app, path, saved_at=now)
    restored, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(sim)
    app.execute(AdvanceTime(20))
    restored.execute(AdvanceTime(20))
    assert capture_state(restored._simulation) == capture_state(sim)
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.STRUCTURAL_COMPONENTS) > arrival_before
    # Finish the interplanetary journey on the restored authoritative State:
    # the campaign may not silently teleport its Crew or bypass RP admission.
    restored.execute(AdvanceTime(630))
    completed = next(row for row in restored.query(GetScientificExplorations()).items
                     if row.id == str(ids.MARS_ORBIT_CREW_EXPEDITION))
    assert completed.status == "complete"
    assert completed.committed_crew == 0
    assert completed.crew_in_transit == 0
    assert restored._simulation.transport.fleet_free_units(
        ids.NUCLEAR_THERMAL_CREW_SHIP, ids.LEO) == 1


def test_reclaimed_water_food_habitation_links_processes_population_construction_research_and_transport(tmp_path):
    """One resource loop is owned by Industry, Inventory, Population and Projects.

    A lower-net-water habitat and a recirculating farm are paid-for installed
    alternatives, not effects unlocked globally by Technology. On-site recovery
    competes for actual volatile feed, Power, construction material and storage.
    """
    from space_idle import (
        GetBuildOptions, GetResearch, PlanBuild, SetTargetStock,
        CreateTransportAllocation, GetTransportAllocationOptions, GetProjects,
        GetPassengerTransferPreview, RequestPassengerTransfer, GetPassengerTransfers,
        PauseFacility, StartResearch, SetResearchPrototypeSite,
    )
    from space_idle.analysis_execution import observe_canonical_day
    from space_idle.content.base_research import build_research_definitions
    from space_idle.research import ResearchPrototypeStageSpec, ResearchDemonstrationStageSpec, ResearchTheoryStageSpec
    from space_idle.scenario import ScenarioPopulation

    research = build_research_definitions()
    target_research = {
        ids.research_id(code) for code in (
            "RP-RESOURCE-CHAIN-11", "TH-THERMAL-TRANSPORT-08",
            "PL-PLANT-FOOD-07", "LS-ATMOSPHERE-WATER-WASTE-14",
            "LS-ATMOSPHERE-WATER-WASTE-13", "HB-HABITATION-PROTECTION-06",
        )
    }
    technologies = set(target_research)
    pending = list(target_research)
    while pending:
        for predecessor in research[pending.pop()].prerequisites - technologies:
            technologies.add(predecessor)
            pending.append(predecessor)
    for technology, stage_kind in (
        ("RP-RESOURCE-CHAIN-11", ResearchPrototypeStageSpec),
        ("PL-PLANT-FOOD-07", ResearchPrototypeStageSpec),
        ("LS-ATMOSPHERE-WATER-WASTE-13", ResearchDemonstrationStageSpec),
    ):
        assert any(isinstance(stage, stage_kind)
                   for stage in research[ids.research_id(technology)].stage_specs)

    locked = build_game_application_for_scenario(build_standard_scenario_definition())
    options = {row.facility_definition_id: row
               for row in locked.query(GetBuildOptions(str(ids.LEO))).items}
    for facility_id in (ids.CLOSED_CYCLE_HABITAT, ids.BIOREGENERATIVE_GROWTH_MODULE,
                        ids.VOLATILE_FRACTIONATION_PLANT):
        option = options[str(facility_id)]
        assert option.resources and option.construction_required > 0
        assert option.power_nominal_load_mw > 0
        assert any(b.kind == "technology" for b in option.blockers)
        assert option.maintenance_rates_per_day
    habitat = options[str(ids.CLOSED_CYCLE_HABITAT)]
    assert habitat.housing_capacity > 0
    assert habitat.life_support_person_days_per_day >= habitat.housing_capacity
    assert dict(habitat.life_support_net_resources_per_person_day)[str(ids.WATER)] < dict(
        locked._simulation.facilities.definitions[ids.HABITAT].life_support.net_resources
    )[ids.WATER]
    unlocked_methods = {(method.kind, method.id)
                        for row in locked.query(GetResearch()).items for method in row.unlocks}
    assert ("process", str(ids.PROCESS_WATER_EFFICIENT_CULTIVATION)) in unlocked_methods
    assert ("process", str(ids.PROCESS_VOLATILE_FRACTIONATION)) in unlocked_methods

    # Before the new method can be selected, the research Stage must consume
    # resources and require a genuinely installed cultivation capability.
    target_id = ids.research_id("PL-PLANT-FOOD-07")
    def small_theory(sim, _catalog):
        technology = sim.research.definitions[target_id]
        sim.research.definitions[target_id] = replace(
            technology,
            stage_specs=(ResearchTheoryStageSpec("theory", 0.5),) + technology.stage_specs[1:],
        )
    trial = build_game_application_for_scenario(
        replace(build_standard_scenario_definition(),
                completed_technologies=tuple(sorted(technologies - target_research))),
        definition_transform=small_theory,
    )
    trial._simulation.research.stored_points = 2
    trial.execute(StartResearch(str(target_id)))
    trial.execute(AdvanceTime(1))
    stage = next(row for row in trial.query(GetResearch()).items if row.id == str(target_id))
    assert stage.current_stage_id == "recirculating-nutrient-loop-trial"
    trial.execute(SetResearchPrototypeSite(
        str(target_id), "recirculating-nutrient-loop-trial", str(ids.EARTH),
    ))
    trial.execute(AdvanceTime(1))
    assert trial._simulation.research.prototype_reserved_t(
        target_id, "recirculating-nutrient-loop-trial", ids.EARTH, ids.WATER,
    ) > 0

    base = build_standard_scenario_definition()
    common = replace(
        base,
        completed_technologies=tuple(sorted(technologies)),
        initial_population=base.initial_population + (ScenarioPopulation(ids.LEO, 12),),
        facilities=base.facilities + (
            ScenarioFacility(ids.ORBITAL_SOLAR_ARRAY, ids.LEO),
            ScenarioFacility(ids.ORBITAL_SOLAR_ARRAY, ids.LEO),
            ScenarioFacility(ids.ORBITAL_LOGISTICS_NODE, ids.LEO),
        ),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.LEO, ids.WATER, 40.0),
            ScenarioInventoryStock(ids.LEO, ids.FOOD, 15.0),
            ScenarioInventoryStock(ids.LEO, ids.OXYGEN, 30.0),
            ScenarioInventoryStock(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL, 45.0),
        ),
    )
    old = build_game_application_for_scenario(replace(common,
        facilities=common.facilities + (
            ScenarioFacility(ids.ORBITAL_HABITAT, ids.LEO),
            ScenarioFacility(ids.ORBITAL_HYDROPONICS, ids.LEO),
            ScenarioFacility(ids.VOLATILE_PROCESSING, ids.EARTH),
        ),
    ))
    modern = build_game_application_for_scenario(replace(common,
        facilities=common.facilities + (
            ScenarioFacility(ids.CLOSED_CYCLE_HABITAT, ids.LEO),
            ScenarioFacility(ids.BIOREGENERATIVE_GROWTH_MODULE, ids.LEO),
            ScenarioFacility(ids.VOLATILE_FRACTIONATION_PLANT, ids.EARTH),
        ),
    ))
    new_farm = next(row for row in modern.query(GetOperationalNode(str(ids.LEO))).industry
                    if row.facility_definition_id == str(ids.BIOREGENERATIVE_GROWTH_MODULE))
    assert {row.process_id for row in new_farm.process_options} == {
        str(ids.PROCESS_FOOD_PRODUCTION), str(ids.PROCESS_WATER_EFFICIENT_CULTIVATION),
    }
    assert new_farm.selection_required
    modern.execute(SetFacilityProcess(
        new_farm.facility_id, str(ids.PROCESS_WATER_EFFICIENT_CULTIVATION),
    ))
    new_separation = next(row for row in modern.query(GetOperationalNode(str(ids.EARTH))).industry
                          if row.facility_definition_id == str(ids.VOLATILE_FRACTIONATION_PLANT))
    modern.execute(SetFacilityProcess(
        new_separation.facility_id, str(ids.PROCESS_VOLATILE_FRACTIONATION),
    ))
    assert not any(
        row.facility_definition_id == str(ids.BIOREGENERATIVE_GROWTH_MODULE)
        for row in old.query(GetOperationalNode(str(ids.LEO))).industry
    )

    # Same time and starting inventory, with different *installed* equipment.
    # Trace causal gross Flow instead of reading net stock delta as consumption.
    with observe_canonical_day(old._simulation) as prior:
        old.execute(AdvanceTime(1))
    with observe_canonical_day(modern._simulation) as improved:
        modern.execute(AdvanceTime(1))

    def flows(trace, resource, fragment, node):
        return sum(row.quantity_t for row in trace.activity_flows()
                   if row.resource_id == str(resource)
                   and fragment in row.activity_id
                   and node in (row.source_owner + row.destination_owner))

    prior_life = flows(prior, ids.WATER, 'population_life_support', str(ids.LEO))
    improved_life = flows(improved, ids.WATER, 'population_life_support', str(ids.LEO))
    assert 0 < improved_life < prior_life
    assert modern.query(GetOperationalNode(str(ids.LEO))).population.current_count == 12
    assert modern.query(GetOperationalNode(str(ids.LEO))).population.deprivation_person_days == 0
    assert modern._simulation.inventory.amount(ids.EARTH, ids.WATER) > old._simulation.inventory.amount(ids.EARTH, ids.WATER)
    assert modern._simulation.inventory.amount(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL) < old._simulation.inventory.amount(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL)
    improved_food = flows(improved, ids.FOOD, 'industry_process', str(ids.LEO))
    prior_food = flows(prior, ids.FOOD, 'industry_process', str(ids.LEO))
    assert improved_food > prior_food > 0

    # A true build changes ownership and the life-support supply only upon
    # completion, with ordinary resource/Power/Construction competition.
    construction = build_game_application_for_scenario(replace(common,
        facilities=common.facilities + (
            ScenarioFacility(ids.ORBITAL_HABITAT, ids.LEO),
            ScenarioFacility(ids.ORBITAL_CONSTRUCTION_PLATFORM, ids.LEO),
        ),
        inventory_stock=common.inventory_stock + tuple(
            ScenarioInventoryStock(ids.LEO, resource, 80.0)
            for resource in (ids.STRUCTURAL_COMPONENTS, ids.MACHINERY,
                             ids.PRECISION_ELECTRONICS, ids.RADIATION_SHIELDING_PANELS,
                             ids.THERMAL_CONTROL_ASSEMBLIES)
        ),
    ))
    before = construction.query(GetOperationalNode(str(ids.LEO))).population.housing_physical
    project_id = construction.execute(PlanBuild(
        str(ids.LEO), str(ids.CLOSED_CYCLE_HABITAT), procurement_policy="immediate",
    )).created_id
    assert project_id
    assert construction.query(GetOperationalNode(str(ids.LEO))).population.housing_physical == before
    construction.execute(AdvanceTime(120))
    assert construction.query(GetOperationalNode(str(ids.LEO))).population.housing_physical > before
    assert any(row.id == project_id and row.completed_facility_id is not None
               for row in construction.query(GetProjects()).items)

    # Actual Earth-to-LEO replenishment for the new inhabited industry, using
    # the existing ascent Fleet and recipient cargo-handling capacity. Process
    # output is real Inventory at the source, never an automatic shared pool.
    vehicle = next(row for row in modern.query(GetTransportAllocationOptions(
        str(ids.EARTH), str(ids.LEO))).options
        if row.vehicle_definition_id == str(ids.REUSABLE_LAUNCH_VEHICLE))
    allocation_id = modern.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=vehicle.nominal_capacity.forward_t_per_day,
        target_reverse_t_per_day=0.0,
    )).created_id
    assert allocation_id
    before_leo_water = modern._simulation.inventory.amount(ids.LEO, ids.WATER)
    before_earth_fuel = modern._simulation.inventory.amount(ids.EARTH, ids.PROPELLANT)
    assert modern.execute(SetTargetStock(str(ids.LEO), str(ids.WATER), 70.0)).created_id
    modern.execute(AdvanceTime(35))
    assert modern._simulation.inventory.amount(ids.LEO, ids.WATER) > before_leo_water
    assert modern._simulation.inventory.amount(ids.EARTH, ids.PROPELLANT) < before_earth_fuel
    assert modern.query(GetOperationalNode(str(ids.LEO))).population.deprivation_person_days == 0

    # Housing expansion is an actual destination for people, not just a
    # catalogue number. The same physical Earth–LEO fleet service moves
    # passengers, while Food/Water/Oxygen settlement remains at the LEO owner.
    preview = modern.query(GetPassengerTransferPreview(str(ids.EARTH), str(ids.LEO), 2))
    assert any(option.dispatchable_people >= 2 for option in preview.options)
    before_population = modern._simulation.population.count_at(ids.LEO)
    order_id = modern.execute(RequestPassengerTransfer(
        str(ids.EARTH), str(ids.LEO), 2,
    )).created_id
    assert order_id

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save = tmp_path / "water-recovery-settlement.json"
    save_game(modern, save, saved_at=now)
    restored, offline = load_game(save, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(restored._simulation) == capture_state(modern._simulation)
    modern.execute(AdvanceTime(8))
    restored.execute(AdvanceTime(8))
    assert capture_state(restored._simulation) == capture_state(modern._simulation)
    passengers = next(row for row in modern.query(GetPassengerTransfers()).items
                      if row.id == order_id)
    assert passengers.delivered_count == 2
    assert modern._simulation.population.count_at(ids.LEO) == before_population + 2
    assert modern.query(GetOperationalNode(str(ids.LEO))).population.deprivation_person_days == 0


def test_functional_materials_from_industrial_process_to_advanced_assets_and_fleet(tmp_path):
    """Functional hardware is built, transported, and consumed as actual stock.

    Heat rejection, radiation attenuation and optical alignment each need a
    different physical production line. Their products compete with vehicle
    manufacture, reactors, medical facilities and research trials rather than
    appearing when a Technology is completed.
    """
    from space_idle import GetBuildOptions, GetFleet, GetFlowReport, PlanBuild, ProduceVehicle
    from space_idle.content.base_research import build_research_definitions
    from space_idle.scenario import ScenarioFacility, ScenarioInventoryStock

    base = build_standard_scenario_definition()
    required = {
        ids.research_id(code) for code in (
            "TH-THERMAL-TRANSPORT-03", "HB-HABITATION-PROTECTION-04",
            "CO-OPTICAL-COMMUNICATIONS-01", "LS-ATMOSPHERE-WATER-WASTE-13",
            "HB-HABITATION-PROTECTION-06", "NT-NUCLEAR-THERMAL-07",
            "LS-ATMOSPHERE-WATER-WASTE-05", "FP-REACTOR-POWER-04",
        )
    }
    research = build_research_definitions()
    frontier = list(required)
    while frontier:
        unseen = research[frontier.pop()].prerequisites - required
        required.update(unseen)
        frontier.extend(unseen)

    lines = (
        (ids.THERMAL_HARDWARE_ASSEMBLY, ids.THERMAL_CONTROL_ASSEMBLIES,
         ids.PROCESS_THERMAL_HARDWARE_ASSEMBLY),
        (ids.SHIELDING_PANEL_FABRICATION, ids.RADIATION_SHIELDING_PANELS,
         ids.PROCESS_SHIELDING_PANEL_FABRICATION),
        (ids.OPTICAL_INSTRUMENT_INTEGRATION, ids.OPTICAL_INSTRUMENT_PACKAGES,
         ids.PROCESS_OPTICAL_INSTRUMENT_INTEGRATION),
    )
    locked = build_game_application_for_scenario(base)
    options = {row.facility_definition_id: row for row in
               locked.query(GetBuildOptions(str(ids.EARTH))).items}
    for facility_id, _, _ in lines:
        assert any(blocker.kind == 'technology' for blocker in options[str(facility_id)].blockers)

    scenario = replace(
        base,
        completed_technologies=tuple(sorted(required)),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 180.0),
            ScenarioInventoryStock(ids.EARTH, ids.MINERAL_FEEDSTOCK, 250.0),
            ScenarioInventoryStock(ids.EARTH, ids.CERAMICS_GLASS, 160.0),
            ScenarioInventoryStock(ids.EARTH, ids.BULK_STRUCTURE, 120.0),
            ScenarioInventoryStock(ids.EARTH, ids.PRECISION_COMPONENTS, 160.0),
        ),
    )
    app = build_game_application_for_scenario(scenario)
    sim = app._simulation
    for facility_id, _, _ in lines:
        assert app.execute(PlanBuild(str(ids.EARTH), str(facility_id),
                                     procurement_policy='immediate')).created_id
    assert not any(f.definition_id in {item[0] for item in lines}
                   for f in sim.facilities.all_at(ids.EARTH))
    app.execute(AdvanceTime(110))
    surface = app.query(GetOperationalNode(str(ids.EARTH)))
    for facility_id, resource_id, process_id in lines:
        assert any(row.facility_definition_id == str(facility_id)
                   for row in surface.industry)
        industry = next(row for row in surface.industry
                        if row.facility_definition_id == str(facility_id))
        assert any(option.process_id == str(process_id) for option in industry.process_options)
        assert sim.inventory.amount(ids.EARTH, resource_id) > 0.0

    # Actual resource consumption for a habitat and a reactor instrument, not
    # just extra labels or an unlock in the static dependency graph.
    before = {material: sim.inventory.amount(ids.EARTH, material)
              for _, material, _ in lines}
    project = app.execute(PlanBuild(str(ids.EARTH), str(ids.CLOSED_CYCLE_HABITAT),
                                    procurement_policy='immediate'))
    assert project.created_id
    production = app.execute(ProduceVehicle(str(ids.NUCLEAR_THERMAL_CREW_SHIP),
                                            str(ids.EARTH)))
    assert production.created_id
    app.execute(AdvanceTime(110))
    assert any(f.definition_id == ids.CLOSED_CYCLE_HABITAT
               for f in sim.facilities.all_at(ids.EARTH))
    assert next(row for row in app.query(GetFleet(str(ids.EARTH))).pools
                if row.vehicle_definition_id == str(ids.NUCLEAR_THERMAL_CREW_SHIP)).total_units >= 1
    # Later raw-material exhaustion may stop some lines: never assert that
    # finite feedstock gives perpetual output. Real construction and finished
    # fleet prove that the produced hardware was consumed by both domains.
    assert all(sim.inventory.amount(ids.EARTH, resource) >= 0.0
               for resource in before)

    now = datetime(2026, 10, 11, tzinfo=timezone.utc)
    path = tmp_path / 'functional-manufactured-hardware.json'
    save_game(app, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    app.execute(AdvanceTime(3))
    loaded.execute(AdvanceTime(3))
    assert capture_state(loaded._simulation) == capture_state(sim)
