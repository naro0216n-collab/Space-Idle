from __future__ import annotations

from space_idle import GetResearch, GetWorld, build_game_application
from space_idle.api import GameRuntime
from space_idle.content import base_ids as ids
from space_idle.logistics import PathPolicy
from space_idle.research import ResearchPhase
from space_idle.shared import EntityId, RouteId
from space_idle.simulation import OfflineProgressPolicy


def test_full_research_point_payment_transitions_directly_to_visible_prototype_and_can_complete():
    app = build_game_application()
    sim = app._simulation
    assert sim.research is not None

    for _ in range(2000):
        if sim.research.can_start(ids.TECH_ORBITAL_OPERATIONS, day=sim.day):
            break
        sim.advance_days(1)
    else:
        raise AssertionError("research never became startable")

    definition = sim.research.definitions[ids.TECH_ORBITAL_OPERATIONS]
    points_before = sim.research.stored_points
    sim.research.start(ids.TECH_ORBITAL_OPERATIONS, day=sim.day)

    state = sim.research.active[ids.TECH_ORBITAL_OPERATIONS]
    assert state.status is ResearchPhase.PROTOTYPE
    assert sim.research.stored_points == points_before - definition.research_point_cost
    assert ids.TECH_ORBITAL_OPERATIONS not in sim.research.completed

    view = app.query(GetResearch())
    row = next(item for item in view.items if item.id == str(ids.TECH_ORBITAL_OPERATIONS))
    assert row.status == "prototype"
    earth = next(site for site in row.prototype_sites if site.location_id == str(ids.EARTH))
    assert not earth.blockers

    sim.research.set_prototype_site(ids.TECH_ORBITAL_OPERATIONS, ids.EARTH, sim.day)
    sim.refresh_resource_claims()
    sim.research.fund_prototype(ids.TECH_ORBITAL_OPERATIONS, sim.day)
    assert ids.TECH_ORBITAL_OPERATIONS in sim.research.completed
    assert ids.TECH_ORBITAL_OPERATIONS not in sim.research.active

    completed_row = next(item for item in app.query(GetResearch()).items if item.id == str(ids.TECH_ORBITAL_OPERATIONS))
    assert completed_row.status == "complete"


def test_research_definitions_have_granular_engineering_outcomes():
    app = build_game_application()
    sim = app._simulation
    assert sim.research is not None
    assert len(sim.research.definitions) >= 13

    single_outcomes = {
        ids.REGOLITH_HARVESTER: ids.TECH_REGOLITH_EXCAVATION,
        ids.REGOLITH_SINTERING: ids.TECH_LUNAR_MATERIALS,
        ids.ORE_PROCESSING: ids.TECH_ORE_BENEFICIATION,
        ids.METALLURGY: ids.TECH_HIGH_TEMPERATURE_METALLURGY,
        ids.FABRICATION_WORKSHOP: ids.TECH_STRUCTURAL_FABRICATION,
        ids.MACHINE_SHOP: ids.TECH_PRECISION_MACHINING,
        ids.HEAVY_EQUIPMENT_ASSEMBLY: ids.TECH_HEAVY_EQUIPMENT_ASSEMBLY,
        ids.ELECTROLYSIS_PLANT: ids.TECH_INDUSTRIAL_ELECTROLYSIS,
        ids.PROPELLANT_PLANT: ids.TECH_PROPELLANT_HANDLING,
    }
    for facility_id, technology_id in single_outcomes.items():
        assert sim.projects.recipes[facility_id].prerequisite_technologies == frozenset({technology_id})

    assert sim.projects.recipes[ids.ORBITAL_LOGISTICS_NODE].prerequisite_technologies == frozenset({
        ids.TECH_ORBITAL_OPERATIONS,
        ids.TECH_CISLUNAR_LOGISTICS,
    })


def test_direct_earth_to_south_pole_cargo_actually_dispatches_and_arrives():
    app = build_game_application()
    sim = app._simulation
    route_id = RouteId("base.route.earth_ridge_direct")
    service_mode = str(ids.DIRECT_LUNAR_SERVICE)

    order_id = sim.logistics.submit_order(
        ids.EARTH,
        ids.SOUTH_POLAR_RIDGE,
        ids.STRUCTURAL_COMPONENTS,
        1.0,
        50,
        "player",
        EntityId("player"),
        day=sim.day,
        path=(route_id,),
        mode_by_route={route_id: service_mode},
        path_policy=PathPolicy.FASTEST,
    )
    assert sim.logistics.waiting[(order_id, 0)] == 1.0

    sim.advance_days(1)
    assert any(mission.order_id == order_id for mission in sim.logistics.missions.values())
    assert sim.logistics.waiting.get((order_id, 0), 0.0) < 1.0

    sim.advance_days(20)
    assert sim.logistics.order_complete(order_id)
    assert sim.inventory.amount(ids.SOUTH_POLAR_RIDGE, ids.STRUCTURAL_COMPONENTS) >= 1.0 - 1e-9


def test_runtime_snapshot_reads_all_projections_at_one_clock_sync(tmp_path):
    now = [0.0]
    runtime = GameRuntime(
        factory=build_game_application,
        save_dir=tmp_path,
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
        clock=lambda: now[0],
    )
    now[0] = 3.2
    result = runtime.snapshot({"world": GetWorld(), "research": GetResearch()})
    assert result.data["session"]["day"] == 3
    assert result.data["world"].day == 3
    assert result.revision == 1
