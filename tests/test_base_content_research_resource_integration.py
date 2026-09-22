from __future__ import annotations

from space_idle import build_game_application
from space_idle.content import base_ids as ids
from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_industry import build_process_specs
from space_idle.content.base_research import build_research_definitions
from space_idle.content.base_spatial import build_world_definition
from space_idle.survey import KnowledgeLevel


def test_base_research_dag_is_complete_acyclic_and_uses_direct_prerequisites_only():
    definitions = build_research_definitions()
    assert len(definitions) == 255
    assert sum(len(row.prerequisites) for row in definitions.values()) == 470
    assert all(row.progression_stage in {1, 2, 3, 4} for row in definitions.values())
    assert all(row.category and row.series for row in definitions.values())

    visiting = set()
    visited = set()

    def visit(research_id):
        if research_id in visited:
            return
        assert research_id not in visiting
        visiting.add(research_id)
        for prerequisite_id in definitions[research_id].prerequisites:
            assert prerequisite_id in definitions
            assert definitions[prerequisite_id].progression_stage <= definitions[research_id].progression_stage
            visit(prerequisite_id)
        visiting.remove(research_id)
        visited.add(research_id)

    for research_id in definitions:
        visit(research_id)

    expected_resource_branch = {
        "RP-RESOURCE-CHAIN-02": {"RP-RESOURCE-CHAIN-01", "SM-SURFACE-MOBILITY-03"},
        "RP-RESOURCE-CHAIN-04": {"RP-RESOURCE-CHAIN-03", "SS-SENSING-05"},
        "RP-RESOURCE-CHAIN-05": {"RP-RESOURCE-CHAIN-02", "AR-AUTONOMY-ROBOTICS-03"},
        "RP-RESOURCE-CHAIN-06": {"RP-RESOURCE-CHAIN-03", "TH-THERMAL-TRANSPORT-04", "SS-SENSING-05"},
        "RP-RESOURCE-CHAIN-07": {"RP-RESOURCE-CHAIN-04", "SS-SENSING-08"},
        "RP-RESOURCE-CHAIN-08": {"RP-RESOURCE-CHAIN-03", "LM-LOGISTICS-MAINTENANCE-05"},
        "RP-RESOURCE-CHAIN-09": {"RP-RESOURCE-CHAIN-05", "RP-RESOURCE-CHAIN-08", "AR-AUTONOMY-ROBOTICS-09", "SM-SURFACE-MOBILITY-08"},
        "RP-RESOURCE-CHAIN-10": {"RP-RESOURCE-CHAIN-07", "CP-COMPUTING-RELIABILITY-08"},
        "RP-RESOURCE-CHAIN-11": {"RP-RESOURCE-CHAIN-06", "RP-RESOURCE-CHAIN-09", "TH-THERMAL-TRANSPORT-08"},
        "RP-RESOURCE-CHAIN-12": {"RP-RESOURCE-CHAIN-11", "PD-STORAGE-DISTRIBUTION-11", "LS-ATMOSPHERE-WATER-WASTE-07"},
        "RP-RESOURCE-CHAIN-13": {"RP-RESOURCE-CHAIN-10", "TH-THERMAL-TRANSPORT-08", "PD-STORAGE-DISTRIBUTION-11"},
        "RP-RESOURCE-CHAIN-14": {"RP-RESOURCE-CHAIN-13", "LM-LOGISTICS-MAINTENANCE-07"},
        "RP-RESOURCE-CHAIN-15": {"RP-RESOURCE-CHAIN-10", "RP-RESOURCE-CHAIN-13", "SS-SENSING-10", "CP-COMPUTING-RELIABILITY-08"},
    }
    for research_id, prerequisites in expected_resource_branch.items():
        assert {str(item) for item in definitions[ids.research_id(research_id)].prerequisites} == prerequisites


def test_base_primary_resource_and_processing_chain_has_no_legacy_resource_path():
    catalog = build_base_catalog()
    graph, _ = build_world_definition()
    processes = build_process_specs()
    app = build_game_application()
    sim = app._simulation

    legacy_ids = {
        "base.resource.regolith",
        "base.resource.aggregate",
        "base.facility.regolith_harvester",
        "base.facility.surface_aggregate_quarry",
        "base.facility.regolith_sintering",
        "base.process.regolith_sintering",
    }
    active_ids = {str(item) for item in catalog.resources}
    active_ids.update(str(item) for item in sim.facilities.definitions)
    active_ids.update(str(item) for item in processes)
    assert active_ids.isdisjoint(legacy_ids)

    lunar_cells = [cell for cell in graph.surface_cells.values() if cell.body_id == ids.MOON]
    assert lunar_cells
    for cell in lunar_cells:
        assert ids.MINERAL_FEEDSTOCK in cell.resource_potential_by_resource
        assert ids.METAL_ORE in cell.resource_potential_by_resource
        assert ids.VOLATILE_BEARING_MATERIAL in cell.resource_potential_by_resource
        assert ids.WATER not in cell.resource_potential_by_resource

    extraction = sim.extraction.specs
    assert extraction[ids.VACUUM_MINERAL_HARVESTER].resource_id == ids.MINERAL_FEEDSTOCK
    assert extraction[ids.VOLATILE_EXTRACTOR].output_resource_id == ids.VOLATILE_BEARING_MATERIAL
    assert all(
        spec.minimum_knowledge_level is KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
        for spec in extraction.values()
    )

    assert processes[ids.PROCESS_MINERAL_SINTER].inputs_per_day == {ids.MINERAL_FEEDSTOCK: 1.0}
    assert set(processes[ids.PROCESS_MINERAL_SINTER].outputs_per_day) == {ids.CERAMICS_GLASS}
    assert processes[ids.PROCESS_ORE_PROCESS].inputs_per_day == {ids.METAL_ORE: 2.5}
    assert set(processes[ids.PROCESS_ORE_PROCESS].outputs_per_day) == {ids.METAL_FEEDSTOCK}
    assert processes[ids.PROCESS_VOLATILE_WATER_RECOVERY].inputs_per_day == {ids.VOLATILE_BEARING_MATERIAL: 1.0}
    assert set(processes[ids.PROCESS_VOLATILE_WATER_RECOVERY].outputs_per_day) == {ids.WATER}


def test_research_gates_resource_methods_not_resource_definitions_and_local_outputs_feed_construction():
    app = build_game_application()
    sim = app._simulation
    resource_ids = set(sim.inventory.resource_definitions)

    for recipe in sim.projects.recipes.values():
        assert recipe.prerequisite_technologies.isdisjoint(resource_ids)
        assert all(not str(item).startswith("base.tech.") for item in recipe.prerequisite_technologies)

    assert sim.projects.recipes[ids.VACUUM_MINERAL_HARVESTER].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_02}
    assert sim.projects.recipes[ids.VOLATILE_EXTRACTOR].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_05}
    assert sim.projects.recipes[ids.VOLATILE_PROCESSING].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_06}
    assert sim.projects.recipes[ids.ORE_PROCESSING].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_04}
    assert sim.projects.recipes[ids.ELECTROLYSIS_PLANT].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_12}
    assert sim.projects.recipes[ids.METALLURGY].prerequisite_technologies == {ids.RP_RESOURCE_CHAIN_13}
    assert sim.projects.recipes[ids.MINERAL_SINTERING].prerequisite_technologies == {ids.MC_MANUFACTURING_CONSTRUCTION_10}

    consumed_locally = {
        requirement.resource_id
        for recipe in sim.projects.recipes.values()
        for requirement in recipe.resources
    }
    assert {
        ids.CERAMICS_GLASS,
        ids.FABRICATED_STRUCTURE,
        ids.BASIC_MACHINE_PARTS,
        ids.PRECISION_COMPONENTS,
    } <= consumed_locally
