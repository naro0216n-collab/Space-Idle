from __future__ import annotations

import pytest

from space_idle import GetOperationalNode, GetSurfaceMap, build_game_application
from space_idle.content import base_ids as ids
from space_idle.content.base_facilities import build_facility_definitions
from space_idle.extraction_service import ExtractionService
from space_idle.facilities import FacilityBook
from space_idle.power import PowerSnapshot
from space_idle.execution_requirements import allocate_execution_requirements


def _execution_plan(sim, facilities, power):
    bundles = sim.extraction.execution_requirement_bundles(
        ids.EARTH, facilities, sim.inventory, sim.day
    )
    _nominal, enabled = sim.extraction.service_supply(
        ids.EARTH, facilities, power, sim.day
    )
    capacities = {}
    for bundle in bundles:
        for requirement in bundle.requirements:
            key = requirement.constraint_key(bundle.operational_node_id)
            if key.kind == "service":
                capacities[key] = enabled.get((bundle.operational_node_id, key.name), 0.0)
            elif key.kind == "admission":
                capacities[key] = float("inf")
    return allocate_execution_requirements(bundles, capacities)


def _resource_snapshot(sim, resource_id):
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    return next(
        row
        for row in sim.extraction.resource_snapshots(
            ids.EARTH, sim.facilities, power, sim.day, decision.allocations.execution
        )
        if row.resource_id == resource_id
    )


def test_extraction_requires_content_defined_knowledge_without_mutating_static_potential():
    app = build_game_application()
    sim = app._simulation
    key = (ids.EARTH_CELL_INDUSTRIAL, ids.METAL_ORE)
    before_potential = {
        cell_id: dict(cell.resource_potential_by_resource)
        for cell_id, cell in sim.graph.surface_cells.items()
    }

    sim.survey.knowledge_progress[key] = 0.0
    unknown = _resource_snapshot(sim, ids.METAL_ORE)
    assert unknown.static_opportunity > 0.0
    assert unknown.effective_opportunity == 0.0
    assert unknown.knowledge_blocked_cell_count == 1
    assert unknown.output_t_per_day == 0.0

    sim.survey.initialize_known(*key)
    known = _resource_snapshot(sim, ids.METAL_ORE)
    assert known.static_opportunity == unknown.static_opportunity
    assert known.effective_opportunity > 0.0
    assert known.knowledge_eligible_cell_count == 1
    assert known.output_t_per_day > 0.0

    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    before_stock = sim.inventory.amount(ids.EARTH, ids.MINERAL_FEEDSTOCK)
    mineral = _resource_snapshot(sim, ids.MINERAL_FEEDSTOCK)
    assert mineral.output_t_per_day > 0.0

    sim.extraction.advance_day(
        ids.EARTH, sim.facilities, sim.inventory, power, sim.day,
        decision.allocations.execution,
    )
    assert sim.inventory.amount(ids.EARTH, ids.MINERAL_FEEDSTOCK) > before_stock
    assert {
        cell_id: dict(cell.resource_potential_by_resource)
        for cell_id, cell in sim.graph.surface_cells.items()
    } == before_potential

def test_soft_saturation_response_is_monotonic_diminishing_and_opportunity_sensitive():
    opportunity = 10.0
    outputs = [
        ExtractionService.diminishing_response(capacity, opportunity)
        for capacity in (1.0, 2.0, 3.0)
    ]
    assert outputs[0] < outputs[1] < outputs[2]
    assert outputs[1] - outputs[0] > outputs[2] - outputs[1]
    assert ExtractionService.marginal_response(1.0, opportunity) > (
        ExtractionService.marginal_response(3.0, opportunity)
    )
    assert ExtractionService.diminishing_response(1000.0, opportunity) > opportunity

    capacity = 10.0
    low = ExtractionService.diminishing_response(capacity, 5.0)
    high = ExtractionService.diminishing_response(capacity, 50.0)
    assert high > low
    assert ExtractionService.marginal_response(capacity, 50.0) > (
        ExtractionService.marginal_response(capacity, 5.0)
    )

def test_extraction_throughput_derives_from_installed_capacity_and_operational_fulfillment():
    base = build_game_application()._simulation
    definitions = build_facility_definitions()

    facilities = FacilityBook(definitions, base.facilities.environment)
    facility_id = facilities.install(ids.METAL_ORE_MINE, ids.EARTH)
    full_power = PowerSnapshot(0.0, 0.0, 0.0, {facility_id: 1.0}, {facility_id: 1.0})
    half_power = PowerSnapshot(0.0, 0.0, 0.0, {facility_id: 0.5}, {facility_id: 1.0})
    full_execution = _execution_plan(base, facilities, full_power)
    half_execution = _execution_plan(base, facilities, half_power)
    full = next(
        row for row in base.extraction.resource_snapshots(
            ids.EARTH, facilities, full_power, base.day, full_execution
        )
        if row.resource_id == ids.METAL_ORE
    )
    half = next(
        row for row in base.extraction.resource_snapshots(
            ids.EARTH, facilities, half_power, base.day, half_execution
        )
        if row.resource_id == ids.METAL_ORE
    )
    assert full.operational_fulfillment == 1.0
    assert half.operational_fulfillment == 0.5
    assert half.output_t_per_day == pytest.approx(full.output_t_per_day * 0.5)
    assert half.marginal_efficiency == pytest.approx(full.marginal_efficiency * 0.5)

    neutral_power = PowerSnapshot(0.0, 0.0, 0.0, {}, {})

    def resource_row(levels):
        capacity_facilities = FacilityBook(definitions, base.facilities.environment)
        for level in levels:
            capacity_facilities.install(ids.METAL_ORE_MINE, ids.EARTH, level=level)
        execution = _execution_plan(base, capacity_facilities, neutral_power)
        return next(
            row
            for row in base.extraction.resource_snapshots(
                ids.EARTH,
                capacity_facilities,
                neutral_power,
                base.day,
                execution,
            )
            if row.resource_id == ids.METAL_ORE
        )

    one = resource_row((1,))
    expanded_a = resource_row((1, 2, 3))
    expanded_b = resource_row((3, 1, 2))
    assert (
        expanded_a.installed_nominal_capacity_t_per_day
        > one.installed_nominal_capacity_t_per_day
    )
    assert expanded_a.output_t_per_day > one.output_t_per_day
    assert expanded_a == expanded_b

def test_application_queries_expose_surface_knowledge_and_extraction_decision_state():
    app = build_game_application()

    surface = app.query(GetSurfaceMap(str(ids.EARTH_BODY)))
    industrial = next(cell for cell in surface.cells if cell.id == str(ids.EARTH_CELL_INDUSTRIAL))
    metal = next(row for row in industrial.resources if row.resource_id == str(ids.METAL_ORE))
    sim = app._simulation
    assert metal.knowledge_level == sim.survey.knowledge_level(ids.EARTH_CELL_INDUSTRIAL, ids.METAL_ORE)
    assert metal.visible_potential == sim.survey.visible_potential(ids.EARTH_CELL_INDUSTRIAL, ids.METAL_ORE)
    assert metal.visible_potential_precision_fraction == sim.survey.visible_potential_precision_fraction(
        ids.EARTH_CELL_INDUSTRIAL, ids.METAL_ORE
    )

    location = app.query(GetOperationalNode(str(ids.EARTH)))
    extraction = next(row for row in location.extraction_resources if row.resource_id == str(ids.METAL_ORE))
    assert extraction.effective_opportunity > 0.0
    assert extraction.installed_nominal_capacity_t_per_day > 0.0
    assert 0.0 <= extraction.operational_fulfillment <= 1.0
    assert extraction.marginal_efficiency > 0.0
    assert extraction.output_t_per_day > 0.0


def test_extraction_stops_when_output_storage_admission_is_full():
    app = build_game_application()
    sim = app._simulation
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    execution = decision.allocations.execution
    initial = next(
        row
        for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day, execution
        )
        if row.output_t_per_day > 0
    )
    spec = sim.extraction.method_for_facility(sim.facilities.facilities[initial.facility_id])
    free = sim.inventory.admission_state(
        ids.EARTH, spec.output_resource_id
    ).admission_capacity_t
    assert free is not None and free > 0

    sim.inventory.add(ids.EARTH, spec.output_resource_id, free)
    before = sim.inventory.amount(ids.EARTH, spec.output_resource_id)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[ids.EARTH]
    execution = decision.allocations.execution
    blocked = next(
        row
        for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day, execution
        )
        if row.facility_id == initial.facility_id
    )
    assert blocked.output_t_per_day == 0.0
    assert any(reason.startswith("storage:") for reason in blocked.limiting_factors)

    sim.extraction.advance_day(
        ids.EARTH, sim.facilities, sim.inventory, power, sim.day, execution
    )
    assert sim.inventory.amount(ids.EARTH, spec.output_resource_id) == before


def test_independently_named_facility_reuses_extraction_method_and_preserves_shared_opportunity():
    from dataclasses import replace
    from space_idle.shared import DefinitionId

    app = build_game_application()
    sim = app._simulation
    before = _resource_snapshot(sim, ids.METAL_ORE)
    original = sim.facilities.definitions[ids.METAL_ORE_MINE]
    alternate_id = DefinitionId("test.high_capacity_borehole")
    sim.facilities.definitions[alternate_id] = replace(
        original, id=alternate_id, display_name="Experimental borehole",
        extraction_capacity_t_per_day=original.extraction_capacity_t_per_day * 2,
    )
    sim.extraction = ExtractionService(
        sim.extraction.specs, sim.graph, sim.environment,
        sim.surface_infrastructure, sim.survey, sim.facilities.definitions,
    )
    assert sim.extraction.compatible_methods(alternate_id) == sim.extraction.compatible_methods(ids.METAL_ORE_MINE)
    alternate = sim.facilities.install(alternate_id, ids.EARTH)
    after = _resource_snapshot(sim, ids.METAL_ORE)
    assert after.installed_nominal_capacity_t_per_day == pytest.approx(
        before.installed_nominal_capacity_t_per_day + sim.extraction.nominal_capacity(sim.facilities.facilities[alternate])
    )
    assert after.output_t_per_day > before.output_t_per_day
    assert after.effective_opportunity == before.effective_opportunity
    assert after.output_t_per_day < before.output_t_per_day + sim.extraction.nominal_capacity(sim.facilities.facilities[alternate])

    projected = app.query(GetOperationalNode(str(ids.EARTH)))
    resource = next(row for row in projected.extraction_resources if row.resource_id == str(ids.METAL_ORE))
    assert resource.installed_nominal_capacity_t_per_day == pytest.approx(after.installed_nominal_capacity_t_per_day)
    assert resource.output_t_per_day == pytest.approx(after.output_t_per_day)

    power = sim.tick_decision_projection().allocations.power_by_location[ids.EARTH]
    allocation = sim.tick_decision_projection().allocations.execution
    output = sum(
        row.output_t_per_day for row in sim.extraction.snapshots(
            ids.EARTH, sim.facilities, sim.inventory, power, sim.day, allocation
        ) if row.resource_id == ids.METAL_ORE
    )
    assert output == pytest.approx(after.output_t_per_day)


def test_extraction_method_requires_physical_capability_and_explicit_selection_when_ambiguous():
    from dataclasses import replace
    from space_idle.shared import DefinitionId

    sim = build_game_application()._simulation
    source = sim.facilities.definitions[ids.METAL_ORE_MINE]
    method = sim.extraction.compatible_methods(source.id)[0]
    unqualified = replace(source, id=DefinitionId("test.unqualified"), capability_supplies=())
    with pytest.raises(ValueError, match="no compatible extraction method"):
        ExtractionService(
            sim.extraction.specs, sim.graph, sim.environment,
            sim.surface_infrastructure, sim.survey,
            {unqualified.id: unqualified},
        )
    second = replace(method, id=DefinitionId("test.equivalent_method"))
    service = ExtractionService(
        {method.id: method, second.id: second}, sim.graph, sim.environment,
        sim.surface_infrastructure, sim.survey,
        {source.id: source},
    )
    assert len(service.compatible_methods(source.id)) == 2
    # Two methods share one installed capacity; no implicit first-candidate use.
    facility_id = sim.facilities.install(source.id, ids.EARTH)
    facility = sim.facilities.facilities[facility_id]
    assert service.method_for_facility(facility) is None
    service.set_method(facility, second.id)
    assert service.method_for_facility(facility) == second


def test_multi_method_extraction_is_a_physical_choice_from_application_to_save_and_offline(tmp_path):
    """One installed mining Capacity cannot run two compatible methods at once.

    An alternate Content definition changes output Resource and Opportunity. Its
    Technology gate affects selection and execution but not installed hardware.
    The same composition also supports replay, restoration, and offline days.
    """
    from dataclasses import replace
    from datetime import datetime, timezone

    from space_idle import (
        AdvanceTime, ApplicationError, GetResearch, SetFacilityExtractionMethod,
    )
    from space_idle.analysis_execution import observe_canonical_day
    from space_idle.bootstrap import build_game_application_for_scenario, build_game_application_for_load
    from space_idle.content.base_scenario import build_standard_scenario_definition
    from space_idle.persistence import capture_state, save_game, load_game, SaveFormatError
    from space_idle.simulation import OfflineProgressPolicy
    from space_idle.shared import DefinitionId
    from space_idle.validation_support import ConfigurationError

    alternative_id = DefinitionId('test.extraction.alternate_mineral')
    tech_id = ids.RP_RESOURCE_CHAIN_04
    source_id = ids.EXTRACTION_CRUST_ORE

    def alternate_definitions(sim, _catalog):
        original = sim.extraction.specs[source_id]
        sim.extraction.specs[alternative_id] = replace(
            original, id=alternative_id, resource_id=ids.MINERAL_FEEDSTOCK,
            output_resource_id=ids.MINERAL_FEEDSTOCK,
            prerequisite_technologies=frozenset((tech_id,)),
            display_name='Alternative mineral recovery',
        )
        sim.extraction.refresh_definition_compatibility()

    def compose():
        return build_game_application_for_scenario(
            build_standard_scenario_definition(), definition_transform=alternate_definitions,
        )

    app = compose()
    sim = app._simulation
    facility = next(row for row in sim.facilities.facilities.values()
                    if row.definition_id == ids.METAL_ORE_MINE)
    facility_id = str(facility.id)
    view = app.query(GetOperationalNode(str(ids.EARTH)))
    extraction = next(row for row in view.extraction if row.facility_id == facility_id)
    assert extraction.selection_required and extraction.method_id is None
    assert extraction.output_t_per_day == 0
    assert extraction.nominal_capacity_t_per_day > 0
    assert len(extraction.method_options) == 2
    options = {row.method_id: row for row in extraction.method_options}
    assert options[str(source_id)].can_select
    assert not options[str(alternative_id)].can_select
    assert any(row.kind == 'technology' and row.subject_id == str(tech_id)
               for row in options[str(alternative_id)].blockers)
    with pytest.raises(ApplicationError, match='technology'):
        app.execute(SetFacilityExtractionMethod(facility_id, str(alternative_id)))
    assert facility.selected_extraction_method_id is None

    app.execute(SetFacilityExtractionMethod(facility_id, str(source_id)))
    assert sim.extraction.method_for_facility(facility).id == source_id
    with observe_canonical_day(sim) as baseline_trace:
        app.execute(AdvanceTime(1))
    assert any(row.activity_id == f'extraction:{facility_id}:{ids.METAL_ORE}:{source_id}'
               for row in baseline_trace.activity_flows())
    assert not any(row.activity_id == f'extraction:{facility_id}:{ids.MINERAL_FEEDSTOCK}:{alternative_id}'
                   for row in baseline_trace.activity_flows())

    sim.technology.unlock(tech_id)
    unlock_rows = {row.id: row for row in app.query(GetResearch()).items}
    assert any(item.kind == 'extraction_method' and item.id == str(alternative_id)
               for item in unlock_rows[str(tech_id)].unlocks)
    app.execute(SetFacilityExtractionMethod(facility_id, str(alternative_id)))
    altered = next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).extraction
                   if row.facility_id == facility_id)
    assert altered.method_id == str(alternative_id)
    assert altered.resource_id == str(ids.MINERAL_FEEDSTOCK)
    assert not altered.selection_required
    assert altered.output_t_per_day >= 0

    with observe_canonical_day(sim) as alternative_trace:
        app.execute(AdvanceTime(1))
    assert any(row.activity_id == f'extraction:{facility_id}:{ids.MINERAL_FEEDSTOCK}:{alternative_id}'
               for row in alternative_trace.activity_flows())
    assert not any(row.activity_id == f'extraction:{facility_id}:{ids.METAL_ORE}:{source_id}'
                   for row in alternative_trace.activity_flows())

    saved_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
    save_path = tmp_path / 'multi-method.json'
    save_game(app, save_path, saved_at=saved_at)
    load_factory = lambda: build_game_application_for_load(
        definition_transform=alternate_definitions,
    )
    loaded, _ = load_game(save_path, load_factory, now=saved_at)
    assert capture_state(loaded._simulation) == capture_state(sim)
    # The saved method and real inventory flow survive ordinary and offline time.
    app.execute(AdvanceTime(2))
    loaded.advance_offline(2.0, OfflineProgressPolicy(
        real_seconds_per_game_day=1.0, max_game_days_per_resume=20,
    ))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    # Initial Facilities use the identical Domain method compatibility and
    # Technology gate: Scenario ownership never bypasses ordinary eligibility.
    original_scenario = build_standard_scenario_definition()
    initially_selected = replace(original_scenario, facilities=tuple(
        replace(row, selected_extraction_method_id=alternative_id)
        if row.definition_id == ids.METAL_ORE_MINE else row
        for row in original_scenario.facilities
    ))
    with pytest.raises(ValueError, match='technology'):
        build_game_application_for_scenario(
            initially_selected, definition_transform=alternate_definitions,
        )
    unlocked_scenario = replace(
        initially_selected,
        completed_technologies=tuple(sorted(
            set(initially_selected.completed_technologies) | {tech_id}
        )),
    )
    initial = build_game_application_for_scenario(
        unlocked_scenario, definition_transform=alternate_definitions,
    )
    initial_mine = next(row for row in initial._simulation.facilities.facilities.values()
                        if row.definition_id == ids.METAL_ORE_MINE)
    assert initial_mine.selected_extraction_method_id == alternative_id
    assert any(row.facility_id == str(initial_mine.id) and row.resource_id == str(ids.MINERAL_FEEDSTOCK)
               for row in initial.query(GetOperationalNode(str(ids.EARTH))).extraction)

    # Two actual Facilities with the same Definition own independent choices;
    # the shared physical Opportunity, installed capacity and stock settlement
    # remain single-counted, regardless of registration order.
    original_mine = next(row for row in unlocked_scenario.facilities
                         if row.definition_id == ids.METAL_ORE_MINE)
    paired = replace(unlocked_scenario, facilities=unlocked_scenario.facilities + (
        replace(original_mine, selected_extraction_method_id=source_id),
    ))
    paired_app = build_game_application_for_scenario(
        paired, definition_transform=alternate_definitions,
    )
    paired_rows = [row for row in paired_app.query(GetOperationalNode(str(ids.EARTH))).extraction
                   if row.facility_definition_id == str(ids.METAL_ORE_MINE)]
    assert len(paired_rows) == 2
    assert {row.method_id for row in paired_rows} == {str(source_id), str(alternative_id)}
    with observe_canonical_day(paired_app._simulation) as paired_trace:
        paired_app.execute(AdvanceTime(1))
    mine_flows = [flow for flow in paired_trace.activity_flows()
                  if flow.activity_id.startswith('extraction:')
                  and flow.resource_id in (str(ids.METAL_ORE), str(ids.MINERAL_FEEDSTOCK))]
    assert {flow.activity_id.split(':')[-2] for flow in mine_flows} >= {
        str(ids.METAL_ORE), str(ids.MINERAL_FEEDSTOCK),
    }

    # The same Save cannot be silently mapped onto Content missing its method.
    with pytest.raises(SaveFormatError, match='extraction selection'):
        load_game(save_path, build_game_application_for_load, now=saved_at)

    # Removal with a remaining valid method is still rejected if a persisted
    # player choice references the removed method, rather than auto-selecting.
    def only_original(sim, catalog):
        alternate_definitions(sim, catalog)
        del sim.extraction.specs[alternative_id]
        sim.extraction.refresh_definition_compatibility()

    with pytest.raises(SaveFormatError, match='extraction selection'):
        load_game(save_path, lambda: build_game_application_for_load(
            definition_transform=only_original,
        ), now=saved_at)
