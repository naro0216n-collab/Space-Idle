from __future__ import annotations

import pytest

from space_idle import (
    GetDependencyAnalytics,
    GetDetailedForecast,
    GetFlowReport,
    build_game_application,
)
from space_idle.app_contracts.common import ApplicationError
from space_idle.catalog import ResourceGroupDef
from space_idle.facilities import FacilityDef
from space_idle.content import base_ids as ids
from space_idle.content.base_game import EARTH, LEO
from space_idle.shared import DefinitionId, EntityId
from space_idle.validation import validate_catalog_coverage
from space_idle.validation_support import ConfigurationError
from space_idle.logistics_models import CargoFlowSegment, CargoServiceLeg, CargoArrivalWaiting
from space_idle.construction.models import BuildResourceRequirement
from dataclasses import replace
from space_idle.production import ProcessSpec
from space_idle.supply import SupplyRoutingConstraintScope


def _resource(view, resource_id):
    return next(row for row in view.current_resources if row.id == str(resource_id))


def _service(view, service_type):
    return next(row for row in view.current_services if row.service_type == service_type)


def test_scope_boundary_changes_import_export_without_double_counting_internal_flow():
    app = build_game_application()
    sim = app._simulation
    sim.logistics.cargo_flows[EntityId("flow.analytics.scope")] = CargoFlowSegment(
        id=EntityId("flow.analytics.scope"), resource_id=ids.WATER, amount_t=12.0,
        source_id=EARTH, final_destination_id=LEO, requirement_id=None,
        owner_kind="test", owner_id=EntityId("analytics.owner"), priority=3,
        leg=CargoServiceLeg(
            "analytics.service", EARTH, LEO, 2, 2.0,
            EntityId("analytics.transport-allocation"), "forward",
        ),
        remaining_legs=(), dispatch_start_day=sim.day, dispatch_end_day=sim.day + 1,
        dispatch_rate_t_per_day=12.0,
    )

    earth = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    leo = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))
    combined = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO), str(EARTH))
    ))

    assert _resource(earth, ids.WATER).exports_pipeline_t == pytest.approx(12.0)
    assert _resource(earth, ids.WATER).imports_pipeline_t == pytest.approx(0.0)
    assert _resource(leo, ids.WATER).imports_pipeline_t == pytest.approx(12.0)
    assert _resource(leo, ids.WATER).exports_pipeline_t == pytest.approx(0.0)
    assert str(EARTH) in _resource(leo, ids.WATER).dependency_source_node_ids
    assert _resource(combined, ids.WATER).imports_pipeline_t == pytest.approx(0.0)
    assert _resource(combined, ids.WATER).exports_pipeline_t == pytest.approx(0.0)
    assert _resource(combined, ids.WATER).internal_pipeline_t == pytest.approx(12.0)
    assert _resource(earth, ids.WATER).internal_pipeline_t == pytest.approx(0.0)
    assert _resource(leo, ids.WATER).internal_pipeline_t == pytest.approx(0.0)
    assert combined.node_ids == tuple(sorted((str(EARTH), str(LEO))))

    body_id = sim.graph.context_body_id(EARTH)
    assert body_id is not None
    body = app.query(GetDependencyAnalytics("body", str(body_id)))
    player = app.query(GetDependencyAnalytics())
    assert set(body.node_ids) == {
        str(value) for value in sim.graph.nodes_for_body(body_id)
    }
    assert set(player.node_ids) == {
        str(value) for value in sim.graph.operational_node_ids()
    }


def test_content_defined_resource_group_aggregates_members_without_cross_resource_substitution():
    app = build_game_application()
    group_id = DefinitionId("test.group.non_substitutable")
    app._catalog.resource_groups[group_id] = ResourceGroupDef(
        group_id, "Non-substitutable", (ids.WATER, ids.MACHINERY)
    )
    # Build an explicit recurring Machinery requirement instead of depending on
    # the opening scenario's temporary balance. The existing Earth facility is
    # only a fixture carrier; the contract under test is that Water production
    # cannot satisfy Machinery demand merely because both belong to one group.
    process = app._simulation.industry.processes[ids.PROCESS_BASIC_MACHINERY]
    app._simulation.industry.processes[ids.PROCESS_BASIC_MACHINERY] = ProcessSpec(
        process.id,
        process.display_name,
        process.facility_def_id,
        {ids.MACHINERY: 0.5},
        {ids.STRUCTURAL_COMPONENTS: 0.1},
    )

    view = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    water = _resource(view, ids.WATER)
    machinery = _resource(view, ids.MACHINERY)
    group = next(row for row in view.current_resource_groups if row.id == str(group_id))
    members = (water, machinery)

    assert group.production_per_day == pytest.approx(
        sum(row.production_per_day for row in members)
    )
    assert group.consumption_per_day == pytest.approx(
        sum(row.consumption_per_day for row in members)
    )
    assert group.imports_pipeline_t == pytest.approx(sum(row.imports_pipeline_t for row in members))
    assert group.exports_pipeline_t == pytest.approx(sum(row.exports_pipeline_t for row in members))

    assert water.production_per_day > machinery.demand_per_day
    assert machinery.local_production_gap_per_day > 0
    assert group.local_production_gap_per_day == pytest.approx(
        sum(row.local_production_gap_per_day for row in members)
    )
    assert group.local_coverage_ratio == pytest.approx(
        sum(
            max(0.0, row.demand_per_day - row.local_production_gap_per_day)
            for row in members
        ) / sum(row.demand_per_day for row in members)
    )

    invalid_group_id = DefinitionId("test.group.invalid")
    app._catalog.resource_groups[invalid_group_id] = ResourceGroupDef(
        invalid_group_id, "Invalid", (DefinitionId("missing.resource"),)
    )
    with pytest.raises(ConfigurationError, match="references missing resources"):
        validate_catalog_coverage(app._simulation, app._catalog)

def test_current_authorized_transport_projects_boundary_flow_consumption_and_partial_unmet():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update(
        sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    allocation_id = sim.transport.create_transport_allocation(
        ids.REUSABLE_LAUNCH_VEHICLE, EARTH, LEO,
        target_capacity=sim.transport.transport_capacity_for_units(
            ids.REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, 1, day=sim.day
        ),
        day=sim.day,
    )
    project_id = sim.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 3, "immediate", day=sim.day,
    )
    sim.logistics.set_supply_routing_constraint(
        SupplyRoutingConstraintScope(
            destination_id=LEO, owner_kind="project", owner_id=EntityId(str(project_id))
        ),
        source_node_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    demands = sim.projects.supplys(sim.day)
    for demand in demands:
        sim.inventory.stock[(EARTH, demand.resource_id)] = demand.amount_t + 5.0

    machinery = next(demand for demand in demands if demand.resource_id == ids.MACHINERY)
    sim.inventory.stock[(EARTH, machinery.resource_id)] = machinery.amount_t / 2.0
    partial = _resource(
        app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),))),
        ids.MACHINERY,
    )
    assert partial.imports_per_day > 0
    assert 0 < partial.unmet_demand_t < machinery.amount_t
    assert any(factor.code == "unmet_demand" for factor in partial.limiting_factors)
    assert partial.navigation is not None
    assert partial.navigation.decision_area == "logistics"
    assert partial.navigation.operational_node_id == str(LEO)
    assert partial.navigation.resource_id == str(ids.MACHINERY)
    assert partial.navigation.supply_requirement_ids
    assert str(allocation_id) in partial.navigation.transport_allocation_ids
    assert partial.navigation.movement_plan_ids

    sim.inventory.stock[(EARTH, machinery.resource_id)] = machinery.amount_t + 5.0
    leo = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(LEO),)))
    earth = app.query(GetDependencyAnalytics("operational_nodes", node_ids=(str(EARTH),)))
    combined = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(EARTH), str(LEO))
    ))

    incoming = [row for row in leo.current_resources if row.imports_per_day > 1e-9]
    assert incoming
    assert all(row.unmet_demand_t == pytest.approx(0.0) for row in incoming)
    assert sum(row.imports_per_day for row in leo.current_resources) == pytest.approx(
        sum(row.exports_per_day for row in earth.current_resources)
    )
    assert sum(row.imports_per_day for row in combined.current_resources) == pytest.approx(0.0)
    assert sum(row.exports_per_day for row in combined.current_resources) == pytest.approx(0.0)
    assert sum(row.internal_dispatch_per_day for row in combined.current_resources) == pytest.approx(
        sum(row.imports_per_day for row in leo.current_resources)
    )
    propellant = _resource(earth, ids.PROPELLANT)
    assert propellant.demand_per_day > 0
    assert propellant.consumption_per_day > 0


def test_current_and_forecast_use_distinct_contracts_and_forecast_reads_active_plan():
    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update(
        sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies
    )
    project_id = sim.projects.plan_build(
        ids.ORBITAL_LOGISTICS_NODE, LEO, 3, "standard_wait", day=sim.day,
    )
    sim.projects.advance_procurement(sim.day)

    current = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO),), time_basis="CURRENT"
    ))
    forecast = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO),), time_basis="FORECAST"
    ))

    assert current.time_basis == "CURRENT"
    assert current.current_resources
    assert not current.forecast_resources
    assert forecast.time_basis == "FORECAST"
    assert forecast.forecast_resources
    assert not forecast.current_resources

    recipe = sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE]
    for requirement in recipe.resources:
        row = next(row for row in forecast.forecast_resources if row.id == str(requirement.resource_id))
        assert row.planned_requirement_t >= requirement.amount_t
        assert row.earliest_requirement_day is not None
        assert row.earliest_requirement_day > sim.day
        assert row.navigation is not None
        assert row.navigation.decision_area == "logistics"
        assert row.navigation.operational_node_id == str(LEO)
        assert row.navigation.supply_requirement_ids

    assert all(
        row.id not in {str(requirement.resource_id) for requirement in recipe.resources}
        or row.demand_per_day < next(
            requirement.amount_t for requirement in recipe.resources
            if str(requirement.resource_id) == row.id
        )
        for row in current.current_resources
    )
    assert sim.projects.projects[project_id].status.value == "procuring"

    with pytest.raises(ApplicationError, match="time basis"):
        app.query(GetDependencyAnalytics(time_basis="historical"))


def test_service_dependency_projection_distinguishes_execution_blockers_and_forecast_scope():
    app = build_game_application()
    view = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(EARTH),), time_basis="CURRENT"
    ))

    row = _service(view, f"process:{ids.PROCESS_BASIC_MACHINERY}")
    assert row.scope == "OPERATIONAL_NODE"
    assert row.requested_rate > 0
    # Opening Machinery production is blocked by Resource constraints, but the
    # Process Service itself has enough local Capacity. Service dependency must
    # therefore not mirror generic execution under-allocation as a Service lack.
    assert row.allocated_rate == pytest.approx(0.0)
    assert row.local_enabled_rate >= row.requested_rate
    assert row.unmet_rate == pytest.approx(0.0)
    assert row.local_coverage_ratio == pytest.approx(1.0)

    sim = app._simulation
    project_id = sim.projects.plan_build(
        ids.CARGO_WAREHOUSE, LEO, 3, "standard_wait", day=sim.day
    )
    sim.projects.advance_procurement(sim.day)

    current = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO),), time_basis="CURRENT"
    ))
    forecast = app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=(str(LEO),), time_basis="FORECAST"
    ))

    assert not any(row.service_type == "construction_work" for row in current.current_services)
    row = next(row for row in forecast.forecast_services if row.service_type == "construction_work")
    recipe = sim.projects.recipe_for_project(sim.projects.projects[project_id])
    assert row.scope == "OPERATIONAL_NODE"
    assert row.planned_requirement == pytest.approx(recipe.construction_work)
    assert row.local_enabled_rate == pytest.approx(0.0)
    assert row.outside_scope_enabled_rate > 0
    assert any(factor.code == "no_local_service_capacity" for factor in row.limiting_factors)


def test_detailed_forecast_advances_isolated_snapshot_and_projects_future_inventory():
    app = build_game_application()
    sim = app._simulation
    base_day = sim.day
    base_stock = dict(sim.inventory.stock)

    view = app.query(GetDetailedForecast(
        "operational_nodes",
        node_ids=(str(ids.EARTH),),
        horizon="SHORT_TERM",
        period_days=5,
    ))

    assert view.base_day == base_day
    assert view.projected_day == base_day + 5
    assert view.period_days == 5
    assert view.horizon == "SHORT_TERM"
    assert view.node_ids == (str(ids.EARTH),)
    assert view.inventory
    assert sim.day == base_day
    assert sim.inventory.stock == base_stock
    assert all(isinstance(row.projected_net_per_day, float) for row in view.inventory)

    with pytest.raises(ApplicationError, match="unsupported detailed forecast horizon"):
        app.query(GetDetailedForecast(horizon="UNKNOWN", period_days=1))
    with pytest.raises(ApplicationError, match="period_days"):
        app.query(GetDetailedForecast(period_days=0))


def test_detailed_forecast_preserves_node_specific_inventory_extrema_across_the_horizon():
    app = build_game_application()
    sim = app._simulation
    base_day = sim.day
    base_stock = dict(sim.inventory.stock)
    selected_nodes = (EARTH, LEO)
    days = 6
    expected: dict[tuple[object, object], list[tuple[int, float]]] = {}
    for node_id, resource_id in sim.inventory.stock:
        if node_id in selected_nodes:
            expected[(node_id, resource_id)] = []
    # Observe an independent canonical replay rather than reproduce the
    # forecast's internal aggregation logic or rely on scenario balance values.
    from copy import deepcopy
    replay = deepcopy(sim)
    for _ in range(days + 1):
        for key in set(expected) | {
            key for key in replay.inventory.stock if key[0] in selected_nodes
        }:
            expected.setdefault(key, [])
            expected[key].append((replay.day, replay.inventory.available(*key)))
        if replay.day < base_day + days:
            replay.advance_days(1)

    view = app.query(GetDetailedForecast(
        "operational_nodes", node_ids=tuple(map(str, selected_nodes)), period_days=days,
    ))
    assert sim.day == base_day
    assert sim.inventory.stock == base_stock
    assert len(view.node_ids) == len(selected_nodes)
    assert view.inventory_ranges
    for row in view.inventory_ranges:
        key = (next(node for node in selected_nodes if str(node) == row.operational_node_id),
               DefinitionId(row.resource_id))
        timeline = {day: 0.0 for day in range(base_day, base_day + days + 1)}
        timeline.update(expected[key])
        minimum = min(timeline.values())
        assert row.base_available_amount == pytest.approx(timeline[base_day])
        assert row.projected_available_amount == pytest.approx(timeline[base_day + days])
        assert row.minimum_available_amount == pytest.approx(minimum)
        assert timeline[row.minimum_available_day] == pytest.approx(minimum)
        first_depleted = next((day for day in range(base_day + 1, base_day + days + 1)
                               if timeline.get(day - 1, 0) > 1e-9 and timeline.get(day, 0) <= 1e-9), None)
        assert row.first_depleted_day == first_depleted


def test_selected_scope_does_not_net_unshipped_remote_production_against_local_need():
    app = build_game_application()
    sim = app._simulation
    recipe = sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE]
    # An otherwise identical Project needing a Resource produced elsewhere.
    # Demand/production quantities are test inputs, not a gameplay balance contract.
    sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE] = replace(
        recipe, resources=(BuildResourceRequirement(ids.WATER, 0.2),)
    )
    sim.technology.completed.update(recipe.prerequisite_technologies)
    sim.projects.plan_build(ids.ORBITAL_LOGISTICS_NODE, LEO, 3, "immediate", day=sim.day)
    sim.projects.advance_procurement(sim.day)

    views = [app.query(GetDependencyAnalytics(
        "operational_nodes", node_ids=tuple(map(str, selected))
    )) for selected in ((EARTH,), (LEO,), (EARTH, LEO))]
    earth, leo, combined = (_resource(view, ids.WATER) for view in views)
    assert earth.production_per_day > leo.demand_per_day > 0
    assert leo.local_production_gap_per_day > 0
    assert combined.local_production_gap_per_day == pytest.approx(
        earth.local_production_gap_per_day + leo.local_production_gap_per_day
    )
    assert combined.local_production_gap_per_day > max(
        0.0, combined.demand_per_day - combined.production_per_day
    )
    assert combined.internal_dispatch_per_day == 0.0


def test_forecast_observes_real_allocations_and_unshipped_due_supply_without_mutating_live_state():
    app = build_game_application()
    sim = app._simulation
    baseline = sim.tick_decision_projection()
    expected_allocation_gap = sum(
        row.unmet_amount for row in baseline.allocations.resources.rows
        if row.operational_node_id == EARTH and row.resource_id == ids.METAL_ORE
    )
    assert expected_allocation_gap > 0
    projected_dispatch = sim.logistics.capacity_logistics_execution_projection(
        baseline.allocations.transport
    )
    due = sim.logistics.unshipped_due_supply(
        sim.day, baseline.intents.supplys, baseline.plan.external_requirements,
        ((row.requirement_id, row.amount_t) for row in projected_dispatch.dispatches),
    )
    expected_unshipped = sum(
        amount for requirement, amount in due
        if requirement.destination_id == EARTH and requirement.resource_id == ids.METAL_ORE
    )
    assert expected_unshipped > 0

    base_stock = dict(sim.inventory.stock)
    view = app.query(GetDetailedForecast(
        "operational_nodes", node_ids=(str(EARTH),), period_days=2,
    ))
    gaps = {(row.resource_id, row.kind): row for row in view.supply_gaps}
    execution = gaps[(str(ids.METAL_ORE), "execution_allocation")]
    procurement = gaps[(str(ids.METAL_ORE), "due_supply_unshipped")]
    assert execution.first_unmet_day == sim.day
    assert procurement.first_unmet_day == sim.day
    assert execution.first_unmet_t == pytest.approx(expected_allocation_gap)
    assert procurement.first_unmet_t == pytest.approx(expected_unshipped)
    assert sim.day == view.base_day
    assert sim.inventory.stock == base_stock

    # Observing a canonical allocation is read-only: the physical replay and
    # its serialized state remain unchanged compared with ordinary advancement.
    from copy import deepcopy
    observed, ordinary = deepcopy(sim), deepcopy(sim)
    seen = []
    observed.advance_days(2, observe_decision=lambda decision: seen.append(decision.snapshot.day))
    ordinary.advance_days(2)
    assert seen == [sim.day, sim.day + 1]
    assert observed.inventory.stock == ordinary.inventory.stock
    assert observed.logistics.cargo_flows == ordinary.logistics.cargo_flows
    assert observed.logistics.arrival_waiting == ordinary.logistics.arrival_waiting


def test_forecast_distinguishes_unadmitted_final_cargo_from_intermediate_handoff():
    app = build_game_application()
    sim = app._simulation
    from copy import deepcopy
    initial_day = sim.day
    for destination, identifier, remaining in (
        (LEO, "final", ()),
        (ids.LUNAR_ORBIT, "handoff", (
            CargoServiceLeg("test.next", LEO, ids.LUNAR_ORBIT, 7, 2.0,
                            EntityId("test.next.allocation"), "forward"),
        )),
    ):
        waiting_id = EntityId(f"test.wait.{identifier}")
        sim.logistics.arrival_waiting[waiting_id] = CargoArrivalWaiting(
            id=waiting_id, resource_id=ids.WATER, amount_t=0.5,
            node_id=LEO, final_destination_id=destination, requirement_id=None,
            owner_kind="test", owner_id=EntityId("test.owner"), priority=3,
            arrival_leg=CargoServiceLeg("test.first", EARTH, LEO, 2, 2.0,
                                       EntityId("test.first.allocation"), "forward"),
            remaining_legs=remaining, arrived_day=sim.day,
        )

    waiting_before = deepcopy(sim.logistics.arrival_waiting)
    view = app.query(GetDetailedForecast(
        "operational_nodes", node_ids=(str(LEO),), period_days=2,
    ))
    assert {(row.final_destination_id, row.first_waiting_day) for row in view.arrival_waiting} == {
        (str(LEO), sim.day), (str(ids.LUNAR_ORBIT), sim.day),
    }
    assert all(row.peak_waiting_t >= 0.5 for row in view.arrival_waiting)
    assert sim.day == initial_day
    assert sim.logistics.arrival_waiting == waiting_before


def test_flow_report_includes_current_facility_maintenance_consumption():
    app = build_game_application()
    sim = app._simulation
    before = {
        row.resource_id: row
        for row in app.query(GetFlowReport(str(ids.EARTH))).resources
    }

    definition_id = DefinitionId("test.facility.analytics_maintenance")
    sim.facilities.definitions[definition_id] = FacilityDef(
        definition_id,
        "Analytics maintenance fixture",
        maintenance_fraction_per_year=365.0,
    )
    sim.inventory.add(ids.EARTH, ids.WATER, 10.0)
    sim.facilities.install(
        definition_id,
        ids.EARTH,
        invested_resources={ids.WATER: 2.0},
    )

    after = {
        row.resource_id: row
        for row in app.query(GetFlowReport(str(ids.EARTH))).resources
    }
    water_before = before[str(ids.WATER)]
    water_after = after[str(ids.WATER)]
    assert (
        water_after.local_consumption_per_day - water_before.local_consumption_per_day
    ) == pytest.approx(2.0)
    assert water_after.local_net_per_day == pytest.approx(
        water_after.local_production_per_day - water_after.local_consumption_per_day
    )
