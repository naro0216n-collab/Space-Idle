"""Research unlocks real alternative operations on shared physical equipment."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime, ApplicationError, GetOperationalNode, GetResearch, SetFacilityProcess,
    build_game_application,
)
from space_idle.bootstrap import (
    build_game_application_for_load, build_game_application_for_scenario,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.scenario import ScenarioFacility, ScenarioInventoryStock


def test_energy_generation_and_wet_beneficiation_keep_physical_choices_after_unlock():
    """Tech gates acquisition/method choice, not existing machine configuration.

    Two orbital generator generations use distinct construction work, material
    investment, sunlight response and service loads. The ore separator remains
    a single installed asset when a water-intensive recovery method is chosen.
    """
    from space_idle import GetBuildOptions
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

    # Technology permits the same ordinary Facility installation. The generic
    # Construction lifecycle is verified in its owning test suite; seed installed
    # equipment here to test physical generation and Process differences directly.
    unlocked_scenario = replace(
        scenario,
        completed_technologies=tuple(sorted(completed)),
        facilities=scenario.facilities + tuple(
            ScenarioFacility(definition_id, ids.LEO) for definition_id in build_ids
        ),
    )
    app = build_game_application_for_scenario(unlocked_scenario)
    dry = build_game_application_for_scenario(unlocked_scenario)
    sim = app._simulation
    unlocked_builds = {row.facility_definition_id: row for row in
                       app.query(GetBuildOptions(str(ids.LEO))).items}
    for definition_id in build_ids:
        row = unlocked_builds[str(definition_id)]
        assert not any(blocker.kind == "technology" for blocker in row.blockers)
        assert row.construction_required > 0

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

    assert build_ids <= {item.definition_id for item in sim.facilities.all_at(ids.LEO)}
    # Compare physical generation with the current installed equipment, not a
    # catalog-pinned throughput threshold or a 150-day construction schedule.
    power = sim.power.snapshot(ids.LEO, sim.facilities, sim.day)
    assert power.generation_mw > 0
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


def test_industrial_scale_up_reuses_methods_and_changes_actual_mass_flow():
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


def test_industrial_material_chain_supplies_common_construction_and_vehicle_inputs():
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

    # Physical stock becomes available at LEO only through ordinary Fleet
    # allocation and cargo handling; persistence equivalence is owned elsewhere.
    leo_before = extended._simulation.inventory.amount(ids.LEO, ids.PRECISION_ELECTRONICS)
    assert extended.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        target_forward_t_per_day=1.0, target_reverse_t_per_day=0.0,
    )).created_id
    assert extended.execute(SetTargetStock(
        str(ids.LEO), str(ids.PRECISION_ELECTRONICS), leo_before + 3.0,
        priority=4,
    )).created_id
    extended.execute(AdvanceTime(8))
    assert extended._simulation.inventory.amount(ids.LEO, ids.PRECISION_ELECTRONICS) > leo_before


def test_mineral_oxygen_chain_and_lander_share_real_resource_and_acquisition_contracts():
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


def test_modular_cargo_launch_system_connects_site_services_fleet_and_orbital_stock():
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
    assert modular.nominal_capacity.forward_t_per_day > 0
    assert ordinary.nominal_capacity.forward_t_per_day > 0
    assert modular.operational_supply_at_full_unit

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
    # Planning the Facility preserves existing Housing; installed capacity only
    # changes after normal Construction settlement (covered by its owner suite).
    assert any(row.id == project_id for row in construction.query(GetProjects()).items)

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


def test_content_site_and_extraction_choices_across_worlds():
    """Compare authored site eligibility and actual extraction across unlike worlds."""
    from space_idle.content import base_ids as ids
    from space_idle.site import evaluate_physical_site_requirements
    from space_idle.shared import SurfaceCellId

    sim = build_game_application()._simulation
    environment = sim.facilities.environment
    surface_contexts = (
        ids.EARTH_CELL_INDUSTRIAL,
        ids.MOON_CELL_SOUTH_POLAR_PLAIN,
        ids.MARS_CELL_EQUATORIAL_PLAIN,
        SurfaceCellId('base.cell.venus.highland'),
    )
    # A robotic staging package and enclosed oxide processor are not Moon
    # properties. Outpost thermal limits reject extreme sites, while the
    # enclosed oxide reactor is governed by its own power and materials.
    deploy = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
    oxide = sim.facilities.definitions[ids.MOLTEN_OXIDE_ELECTROLYZER]
    for cell in surface_contexts:
        assert bool(evaluate_physical_site_requirements(deploy.target_requirements, cell, sim.day, environment)) == (cell == SurfaceCellId("base.cell.venus.highland"))
        assert not evaluate_physical_site_requirements(oxide.installation_requirements, cell, sim.day, environment)
        assert not evaluate_physical_site_requirements(oxide.operating_requirements, cell, sim.day, environment)
    assert evaluate_physical_site_requirements(oxide.installation_requirements, ids.LEO, sim.day, environment)

    # Cold volatile deposits occur in both near-vacuum icy regions and dense
    # cold atmospheres. Pressure alone must not turn a Titan resource into an
    # unobtainable, Moon-specific raw material.
    from space_idle.content import base_requirements as req
    titan = SurfaceCellId('base.cell.titan.highland')
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, titan, sim.day, environment)
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, ids.MOON_CELL_POLAR_COLD_TRAP, sim.day, environment)
    assert evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, ids.MOON_CELL_EQUATORIAL_HIGHLANDS, sim.day, environment)
    assert not evaluate_physical_site_requirements(req.COLD_VOLATILE_SURFACE_SITE, SurfaceCellId("base.cell.mercury.polar"), sim.day, environment)

    # Atmospheric and low-pressure infrastructure stay physically distinct.
    low_pressure = sim.facilities.definitions[ids.VACUUM_CARGO_HANDLING_TERMINAL]
    ambient = sim.facilities.definitions[ids.BREATHABLE_SURFACE_LIFE_SUPPORT]
    for cell in (ids.MOON_CELL_SOUTH_POLAR_PLAIN, ids.MARS_CELL_EQUATORIAL_PLAIN):
        assert not evaluate_physical_site_requirements(low_pressure.installation_requirements, cell, sim.day, environment)
        assert evaluate_physical_site_requirements(ambient.operating_requirements, cell, sim.day, environment)
    for cell in (ids.EARTH_CELL_INDUSTRIAL, SurfaceCellId('base.cell.venus.highland')):
        assert evaluate_physical_site_requirements(low_pressure.installation_requirements, cell, sim.day, environment)
    assert not evaluate_physical_site_requirements(ambient.operating_requirements, ids.EARTH_CELL_INDUSTRIAL, sim.day, environment)

    # Evaluate actual Resource ownership and extraction in distinct physical contexts
    from dataclasses import replace
    from space_idle import AdvanceTime, GetOperationalNode
    from space_idle.bootstrap import build_game_application_for_scenario
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.scenario import (
        ScenarioSurfaceLocation, ScenarioFacility,
    )
    from space_idle.shared import SpatialNodeId, CelestialBodyId
    base = build_standard_scenario_definition()
    regions = (
        (ids.MOON, ids.MOON_CELL_POLAR_COLD_TRAP),
        (CelestialBodyId('base.body.titan'), titan),
        (CelestialBodyId('base.body.mercury'), SurfaceCellId('base.cell.mercury.polar')),
    )
    for body, cell in regions:
        location = SpatialNodeId(f'test.cold_volatile.{body}')
        scenario = replace(
            base,
            surface_locations=base.surface_locations + (
                ScenarioSurfaceLocation(location, 'Volatile production site', body, cell),
            ),
            facilities=base.facilities + (
                ScenarioFacility(ids.INDUSTRIAL_POWER_BLOCK, location),
                ScenarioFacility(ids.SURFACE_DISTRIBUTION_HUB, location, cell),
                ScenarioFacility(ids.VOLATILE_EXTRACTOR, location, cell),
            ),
            known_surface_resources=base.known_surface_resources + (
                (cell, ids.VOLATILE_BEARING_MATERIAL),
            ),
        )
        case = build_game_application_for_scenario(scenario)
        actual = case._simulation
        before = actual.inventory.amount(location, ids.VOLATILE_BEARING_MATERIAL)
        case.execute(AdvanceTime(3))
        after = actual.inventory.amount(location, ids.VOLATILE_BEARING_MATERIAL)
        assert after > before
        production = next(row for row in case.query(GetOperationalNode(str(location))).extraction
                          if row.resource_id == str(ids.VOLATILE_BEARING_MATERIAL))
        assert production.output_t_per_day > 0
