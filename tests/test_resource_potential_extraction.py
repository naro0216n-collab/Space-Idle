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
    spec = sim.extraction.specs[initial.facility_def_id]
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
