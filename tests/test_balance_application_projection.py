"""One Application projection feeds the GUI and the top-down balance CLI."""
from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

from space_idle.app_contracts.catalog_views import ProcessDefinitionRow
from space_idle.app_contracts.queries import (
    GetCatalog, GetDevelopmentWorldReference, GetFleet, GetOperationalNode, GetResearch,
)
from space_idle.api.codec import QUERY_TYPES
from space_idle.balance.application_inputs import collect_application_inputs
from space_idle.bootstrap import build_game_application


def test_registered_definitions_and_actual_state_are_shared_with_gui_queries():
    app = build_game_application()
    inputs = collect_application_inputs(app)
    catalog = app.query(GetCatalog())
    assert set(inputs["facilities"]) == {row.id for row in catalog.facilities}
    assert set(inputs["research"]) == {row.id for row in catalog.research}
    assert set(inputs["vehicles"]) == {row.id for row in catalog.vehicles}
    assert set(inputs["processes"]) == {row.id for row in catalog.processes}
    assert set(inputs["extraction"]) == {row.id for row in catalog.extraction_methods}
    assert set(inputs["resources"]) == {row.id for row in catalog.resources}
    for row in catalog.facilities:
        assert row.design is not None
        assert inputs["facilities"][row.id]["construction_work"] == row.design.construction_work
        assert inputs["facilities"][row.id]["process_throughput_per_day"] == row.design.process_throughput_per_day
    for row in catalog.research:
        assert inputs["research"][row.id]["stage"] == row.progression_stage
        assert [s["kind"] for s in inputs["research"][row.id]["stages"]] == [s.stage_type for s in row.stages]
    for row in catalog.processes:
        assert inputs["processes"][row.id]["inputs_per_unit_t"] == dict(row.inputs_per_day)
        assert inputs["processes"][row.id]["outputs_per_unit_t"] == dict(row.outputs_per_day)
        assert inputs["processes"][row.id]["provider_facilities"] == list(row.provider_facilities)
    for row in catalog.operational_nodes:
        state = app.query(GetOperationalNode(row.id))
        installed = [r for r in inputs["owned"]["installed_facilities"] if r["node"] == row.id]
        assert len(installed) == len(state.facilities)
        for facility in state.facilities:
            actual = next(f for f in installed if f["facility"] == facility.definition_id
                          and f["invested_resources_t"] == dict(facility.invested_resources)
                          and f["process"] == facility.selected_process_id
                          and f["extraction_method"] == facility.selected_extraction_method_id)
            assert actual["level"] == facility.level
        assert {(r["resource"], r["available_t"]) for r in inputs["owned"]["available_inventory"] if r["node"] == row.id} == {
            (r.resource_id, r.available) for r in state.inventory if r.available > 0
        }
    assert inputs["owned"]["stored_research_points"] == app.query(GetResearch()).stored_points
    fleet = app.query(GetFleet())
    assert sum(f["count"] for f in inputs["owned"]["fleet"]) == sum(r.total_units for r in fleet.pools)


def test_catalog_is_the_only_registered_definition_input_and_updates_propagate():
    app = build_game_application()
    original = app.query(GetCatalog())
    facility = original.facilities[0]
    process = original.processes[0]
    research = next(row for row in original.research if row.stages)
    stage = research.stages[0]
    changed_facility = replace(facility, design=replace(
        facility.design, construction_work=(facility.design.construction_work or 0) + 11,
    ))
    changed_process = replace(process, outputs_per_day=((process.outputs_per_day[0][0], 987.0),))
    changed_research = replace(research, stages=(replace(stage, required_progress=123456.0),) + research.stages[1:])
    added = ProcessDefinitionRow(
        "synthetic.process", "new", process.required_capabilities,
        process.inputs_per_day, process.outputs_per_day, process.prerequisites,
    )
    extended_catalog = replace(
        original,
        facilities=(changed_facility,) + original.facilities[1:],
        processes=(changed_process,) + original.processes[1:] + (added,),
        research=tuple(changed_research if row.id == research.id else row for row in original.research),
    )

    class AppWithDifferentPublicCatalog:
        # Intentionally no _simulation: the balance adapter must not ask for one.
        content_id = app.content_id
        world_definition_id = app.world_definition_id
        scenario_id = app.scenario_id
        game_day = app.game_day
        def query_many(self, queries):
            rows = app.query_many(queries)
            if "catalog" in rows:
                rows["catalog"] = extended_catalog
            return rows

    derived = collect_application_inputs(AppWithDifferentPublicCatalog())
    assert derived["facilities"][facility.id]["construction_work"] == changed_facility.design.construction_work
    assert derived["processes"][process.id]["outputs_per_unit_t"] == dict(changed_process.outputs_per_day)
    assert derived["research"][research.id]["stages"][0]["kind"] == stage.stage_type
    assert "synthetic.process" in derived["processes"]


def test_unprojected_definition_does_not_silently_become_zero():
    app = build_game_application()
    original = app.query(GetCatalog())
    broken = replace(original.facilities[0], design=None)
    class MissingDefinitionApp:
        content_id, world_definition_id, scenario_id, game_day = (
            app.content_id, app.world_definition_id, app.scenario_id, app.game_day)
        def query_many(self, queries):
            rows = app.query_many(queries)
            if "catalog" in rows:
                rows["catalog"] = replace(original, facilities=(broken,) + original.facilities[1:])
            return rows
    with pytest.raises(ValueError, match="omitted design coefficients"):
        collect_application_inputs(MissingDefinitionApp())


def test_internal_design_world_is_not_exposed_by_http_query_decoder():
    app = build_game_application()
    reference = app.query(GetDevelopmentWorldReference())
    assert reference.surface_resource_distribution
    assert "GetDevelopmentWorldReference" not in QUERY_TYPES
    import space_idle.balance.application_inputs as module
    source = inspect.getsource(module)
    assert "_simulation" not in source
    assert "application_balance" not in source
    assert "project_balance_definitions" not in source


def test_application_state_after_time_progression_and_save_load_is_the_same_input(tmp_path):
    from datetime import datetime, timezone
    from space_idle.application_commands import AdvanceTime
    from space_idle.bootstrap import build_game_application_for_load
    from space_idle.persistence import save_game, load_game

    app = build_game_application()
    app.execute(AdvanceTime(3))
    expected = collect_application_inputs(app)
    save_path = tmp_path / "state.json"
    save_game(app, save_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(save_path, build_game_application_for_load)
    assert collect_application_inputs(loaded) == expected
    assert expected["owned"]["completed_technologies"] == list(app.query(GetResearch()).completed_technologies)
