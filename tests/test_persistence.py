from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from space_idle import (
    AdvanceTime,
    CreateTransportAllocation,
    DevelopSurfaceCell,
    GetDependencyAnalytics,
    GetOperationalNode,
    GetResearch,
    GetWorld,
    PauseBuild,
    PauseFacility,
    PauseResearch,
    PauseTransportAllocation,
    ResumeBuild,
    ResumeFacility,
    ResumeResearch,
    ResumeTransportAllocation,
    PlanBuild,
    ProduceVehicle,
    SetResearchPrototypeSite,
    StartResearch,
    StartSurvey,
    SetSupplyPolicy,
    SetTargetStock,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content.base_game import (
    EARTH,
    LEO,
    REUSABLE_LAUNCH_VEHICLE,
    REUSABLE_ORBITAL_CARGO_TUG,
)
from space_idle.content import base_ids as ids
from space_idle.persistence import SaveFormatError, capture_state, load_game, save_game
from space_idle.research import ResearchStage, ResearchState
from space_idle.shared import EntityId, CelestialBodyId, DefinitionId
from space_idle.simulation import OfflineProgressPolicy
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def _make_nontrivial_state():
    app = build_game_application()
    sim = app._simulation

    research = next(
        item for item in app.query(GetResearch()).items
        if item.id == str(ids.TECH_ORBITAL_OPERATIONS)
    )
    assert research.can_start
    app.execute(StartResearch(research.id, priority=4))

    surface_definition = ids.ROBOTIC_GEOLOGY_STATION
    surface_recipe = sim.projects.recipes[surface_definition]
    sim.technology.completed.update(surface_recipe.prerequisite_technologies)
    project_id = app.execute(
        PlanBuild(
            str(EARTH),
            str(surface_definition),
            sourcing_policy="local_priority",
            site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
        )
    ).created_id

    surface_facility_id = sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )

    survey_key = next(
        key
        for key in sim.survey.targets
        if sim.survey.can_start(ids.LUNAR_ORBIT, key[0], key[1], sim.day)
    )
    app.execute(
        StartSurvey(
            str(ids.LUNAR_ORBIT),
            str(survey_key[0]),
            str(survey_key[1]),
            priority=4,
        )
    )
    target = sim.survey.targets[survey_key]
    sim.survey.knowledge_progress[survey_key] = target.thresholds[0] / 2.0

    app.execute(
        SetSupplyPolicy(str(LEO), str(ids.MACHINERY), preferred_source_id=str(EARTH))
    )
    app.execute(SetTargetStock(str(LEO), str(ids.MACHINERY), 1.0, priority=4))
    allocation_id = app.execute(
        CreateTransportAllocation(
            str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO), target_units=1
        )
    ).created_id

    assert project_id is not None and allocation_id is not None
    app.execute(PauseBuild(project_id))
    app.execute(AdvanceTime(1))
    app.execute(PauseFacility(str(surface_facility_id)))
    app.execute(PauseResearch(research.id))
    app.execute(PauseTransportAllocation(allocation_id))
    sim.research.knowledge_state.add(ids.EXPERIENCE_TRANSPORT_OPERATIONS, 2.5)
    return app



def test_save_load_roundtrip_preserves_state_and_future_behavior(tmp_path):
    app = _make_nontrivial_state()
    path = tmp_path / "game.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)


def test_save_load_preserves_research_execution_site(tmp_path):
    app = build_game_application()
    sim = app._simulation
    research_id = ids.TECH_ORBITAL_OPERATIONS
    sim.research.active[research_id] = ResearchState(
        research_id,
        ResearchStage.PROTOTYPE,
        stage_started_day=sim.day,
    )
    app.execute(SetResearchPrototypeSite(str(research_id), str(EARTH)))

    before = sim.research.active[research_id].prototype_execution_site
    assert before is not None
    path = tmp_path / "research-execution-site.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)

    after = loaded._simulation.research.active[research_id].prototype_execution_site
    assert after == before
    assert capture_state(loaded._simulation)["research"] == capture_state(sim)["research"]
    assert loaded.query(GetResearch()) == app.query(GetResearch())

    # Future-behavior equality only needs one canonical tick here. Multi-day
    # composability is owned by the dedicated Offline Progress contract below.
    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)


def test_offline_progress_uses_the_same_active_simulation_path_as_normal_time(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elapsed_days = 3
    policy = OfflineProgressPolicy(real_seconds_per_game_day=1.0, max_game_days_per_resume=20)
    original = _make_nontrivial_state()
    sim = original._simulation

    # Exercise several active domains at once instead of preserving one offline
    # regression test per feature that happened to be added over time.
    for facility in sim.facilities.facilities.values():
        if facility.paused:
            original.execute(ResumeFacility(str(facility.id)))
    for research_id, project in tuple(sim.research.active.items()):
        if project.paused:
            original.execute(ResumeResearch(str(research_id)))
    for project in tuple(sim.projects.projects.values()):
        if project.paused:
            original.execute(ResumeBuild(str(project.id)))
    for allocation in tuple(sim.transport.transport_allocations.values()):
        if allocation.paused:
            original.execute(ResumeTransportAllocation(str(allocation.id)))
    original.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB, ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    original.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), sourcing_policy="import_now"
    ))

    path = tmp_path / "offline-active-domains.json"
    save_game(original, path, saved_at=saved_at)

    offline, result = load_game(
        path, build_game_application_for_load,
        now=saved_at + timedelta(seconds=elapsed_days),
        offline_policy=policy,
    )
    direct, _ = load_game(path, build_game_application_for_load)
    direct.execute(AdvanceTime(elapsed_days))

    assert result is not None and result.advanced_days == elapsed_days
    assert capture_state(offline._simulation) == capture_state(direct._simulation)
    assert offline.query(GetWorld()).day == direct.query(GetWorld()).day
    assert offline._simulation.boundary_settled_day == offline._simulation.day
    assert direct._simulation.boundary_settled_day == direct._simulation.day


def test_fractional_offline_time_is_composable():
    app_a = build_game_application()
    app_b = build_game_application()
    policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)
    app_a._simulation.advance_offline(6.0, policy)
    app_a._simulation.advance_offline(6.0, policy)
    app_b._simulation.advance_offline(12.0, policy)
    assert capture_state(app_a._simulation) == capture_state(app_b._simulation)


def test_save_load_preserves_in_flight_cargo_and_rederives_transport_projection(tmp_path):
    app = build_game_application()
    sim = app._simulation
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO), target_units=1
    )).created_id
    assert allocation_id is not None

    sim.inventory.stock[(ids.LEO, ids.MACHINERY)] = 0.0
    sim.inventory.add(ids.EARTH, ids.MACHINERY, 1.0)
    sim.logistics.set_supply_policy(
        ids.LEO, ids.MACHINERY, preferred_source_id=ids.EARTH
    )
    target_id = sim.logistics.set_target_stock(ids.LEO, ids.MACHINERY, 0.5, 5)
    sim.advance_days(1)
    assert any(
        row.owner_id == target_id for row in sim.logistics.cargo_flows.values()
    )

    allocation_entity_id = EntityId(allocation_id)
    before_capacity = sim.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=sim.day
    )
    before_flows = dict(sim.logistics.cargo_flows)

    path = tmp_path / "cargo-flow.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)

    assert loaded._simulation.logistics.cargo_flows == before_flows
    assert loaded._simulation.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=loaded._simulation.day
    ) == before_capacity

def test_save_load_preserves_vehicle_production_staging_and_future_completion(tmp_path):
    app = build_game_application()
    sim = app._simulation
    definition = sim.transport.vehicle_defs[REUSABLE_ORBITAL_CARGO_TUG]
    for resource_id, _required_t in definition.production.resources:
        sim.inventory.stock[(EARTH, resource_id)] = 0.0
    partial_resource, required_t = next(
        (resource_id, required_t)
        for resource_id, required_t in definition.production.resources
        if required_t > 0.0
    )
    partial_stock = required_t * 0.5
    sim.inventory.stock[(EARTH, partial_resource)] = partial_stock

    result = app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    assert result.created_id is not None
    production_id = EntityId(result.created_id)
    app.execute(AdvanceTime(1))
    original = sim.transport.vehicle_production_projects[production_id]
    remaining_on_hand = sim.inventory.amount(EARTH, partial_resource)
    assert original.phase.value == "awaiting_inputs"
    assert partial_stock - remaining_on_hand > 0.0

    before = capture_state(sim)
    path = tmp_path / "vehicle-production.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    loaded_state = capture_state(loaded._simulation)
    assert loaded_state["transport"] == before["transport"]
    assert loaded_state["inventory"] == before["inventory"]

    before_units = loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units
    for current in (app._simulation, loaded._simulation):
        for resource_id, resource_required_t in definition.production.resources:
            current.inventory.stock[(EARTH, resource_id)] = max(
                current.inventory.amount(EARTH, resource_id), resource_required_t * 2.0
            )

    production_days = int(definition.production.days)
    app.execute(AdvanceTime(production_days))
    loaded.execute(AdvanceTime(production_days))
    state = loaded._simulation.transport.vehicle_production_projects[production_id]
    assert state.phase.value == "complete"
    assert state.completed_units == 1
    assert loaded._simulation.transport.fleet_pool(
        REUSABLE_ORBITAL_CARGO_TUG, EARTH
    ).total_units == before_units + 1
    loaded_future = capture_state(loaded._simulation)
    original_future = capture_state(app._simulation)
    assert loaded_future["transport"] == original_future["transport"]
    assert loaded_future["inventory"] == original_future["inventory"]


def test_derived_projections_are_not_persisted_and_rederive_after_load(tmp_path):
    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    before = capture_state(sim)

    decision = sim.tick_decision_projection()
    assert decision.allocations.resources.allocations
    infrastructure_before = app.query(
        GetOperationalNode(str(ids.EARTH))
    ).surface_infrastructure
    analytics_before = app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(ids.EARTH),))
    )
    assert infrastructure_before is not None
    assert capture_state(sim) == before
    assert "surface_infrastructure" not in before
    assert "dependency_analytics" not in before
    assert "allocation_projection" not in before

    path = tmp_path / "derived-projections.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)
    assert capture_state(loaded._simulation) == before
    assert loaded.query(
        GetOperationalNode(str(ids.EARTH))
    ).surface_infrastructure == infrastructure_before
    assert loaded.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(ids.EARTH),))
    ) == analytics_before


def test_dynamic_environment_overlay_roundtrips_through_game_save(tmp_path):
    body_id = CelestialBodyId(str(ids.EARTH_BODY))
    species = DefinitionId("test.atmosphere.n2")

    def factory(*, for_load: bool = False):
        app = build_game_application_for_load() if for_load else build_game_application()
        service = TerraformingService({
            body_id: PlanetaryClimateState(body_id, 101325.0, 1.225, 288.0, {species: 1.0})
        })
        app._simulation.environment.overlays.append(TerraformingEnvironmentOverlay(service))
        return app

    app = factory()
    overlay = app._simulation.environment.overlays[-1]
    overlay.service.add_atmosphere(body_id, 250.0, 0.01, species, 0.0, 3.5)
    before = app._simulation.environment.capture_overlay_state()

    path = tmp_path / "dynamic-environment.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, lambda: factory(for_load=True))

    assert loaded._simulation.environment.capture_overlay_state() == before
    assert capture_state(loaded._simulation)["environment"] == capture_state(app._simulation)["environment"]


def test_load_rejects_cross_domain_runtime_invariant_violation(tmp_path):
    app = build_game_application()
    path = tmp_path / "invalid-runtime.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    payload = json.loads(path.read_text(encoding="utf-8"))
    provider = payload["state"]["market"]["provider_states"][0]
    resource_id = next(iter(provider["supply_available_t"]))
    provider["supply_available_t"][resource_id] = 1.0e12
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SaveFormatError, match="invalid saved runtime state"):
        load_game(path, build_game_application_for_load)
