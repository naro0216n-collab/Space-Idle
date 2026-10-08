from __future__ import annotations

from space_idle import build_game_application
from space_idle.content.base_research import build_research_definitions
from space_idle.content.base_spatial import build_world_definition


def test_base_technology_graph_has_resolvable_acyclic_prerequisites_and_independent_branches():
    """Content validation, not a snapshot of its current size or research order."""
    definitions = build_research_definitions()
    assert definitions
    assert all(definition.progression_stage >= 1 and definition.category and definition.series
               for definition in definitions.values())

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

    # The graph permits independent starts and interdisciplinary prerequisites;
    # neither stage metadata nor series identity imposes a linear unlock order.
    assert len([row for row in definitions.values() if not row.prerequisites]) > 1
    assert any(
        any(definitions[prerequisite].category != row.category for prerequisite in row.prerequisites)
        for row in definitions.values()
    )


def test_base_resource_methods_connect_surveyed_geology_to_processing_and_construction():
    """Check playable content connectivity without preserving old IDs or balance values."""
    app = build_game_application()
    sim = app._simulation
    graph, _ = build_world_definition()
    definitions = build_research_definitions()
    resource_ids = set(sim.inventory.resource_definitions)
    potential_resources = {
        resource_id
        for cell in graph.surface_cells.values()
        for resource_id in cell.resource_potential_by_resource
    }

    extraction_outputs = {
        spec.output_resource_id for spec in sim.extraction.specs.values()
        if spec.resource_id in potential_resources
    }
    assert extraction_outputs
    assert extraction_outputs <= resource_ids

    processes = tuple(sim.industry.processes.values())
    assert processes
    assert all(set(process.inputs_per_day) | set(process.outputs_per_day) <= resource_ids
               for process in processes)
    assert all(process.facility_def_id in sim.facilities.definitions for process in processes)

    # Reachability is through explicitly described input/output edges. There is
    # no assumption that all resources substitute for one another.
    reachable = set(extraction_outputs)
    while True:
        newly_reachable = reachable | {
            output_id
            for process in processes
            if set(process.inputs_per_day) <= reachable
            for output_id in process.outputs_per_day
        }
        if newly_reachable == reachable:
            break
        reachable = newly_reachable

    construction_resources = {
        requirement.resource_id
        for recipe in sim.projects.recipes.values()
        for requirement in recipe.resources
    }
    assert (reachable - extraction_outputs) & construction_resources

    # Technology gates operational methods; resource definitions remain usable
    # independent of the game's particular DAG/content naming scheme.
    assert any(recipe.prerequisite_technologies for recipe in sim.projects.recipes.values())
    assert all(
        recipe.prerequisite_technologies <= definitions.keys()
        and recipe.prerequisite_technologies.isdisjoint(resource_ids)
        for recipe in sim.projects.recipes.values()
    )


def test_research_display_stage_does_not_derive_cost_or_limit_stage_range(monkeypatch):
    """Cost is a typed Research Stage requirement, not a table indexed by display stage."""
    from space_idle.content import base_research
    from space_idle.research import ResearchTheoryStageSpec
    from space_idle.shared import DefinitionId

    stage = 9
    explicit_cost = 425.0
    additional_row = (
        "test.future-stage", stage, "advanced", "independent", "Future research", (), explicit_cost,
    )
    monkeypatch.setattr(base_research, "RESEARCH_DAG_ROWS", (additional_row,))
    definition = base_research.build_research_definitions()[DefinitionId("test.future-stage")]
    assert definition.progression_stage == stage
    assert isinstance(definition.stage_specs[0], ResearchTheoryStageSpec)
    assert definition.stage_specs[0].research_point_cost == explicit_cost
