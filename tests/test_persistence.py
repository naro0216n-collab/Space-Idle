from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from space_idle import (
    AdvanceTime,
    SetResearchProviderFleetQuantity,
    SetSurveyProviderFleetQuantity,
    CreateTransportAllocation,
    DevelopSurfaceCell,
    GetDependencyAnalytics,
    GetOperationalNode,
    GetResearch,
    GetSurveys,
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
    SetResearchProviderAssignmentPriority,
    SetFacilityProcess,
    StartResearch,
    StartSurvey,
    SetSupplyRoutingConstraint,
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
from space_idle.industry import ProcessSpec
from space_idle.research import (
    ResearchProviderLevelSpec, ResearchProviderSourceKind, ResearchProviderSpec,
    ResearchStage, ResearchState,
)
from space_idle.shared import EntityId, CelestialBodyId, DefinitionId
from space_idle.simulation import OfflineProgressPolicy
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService


def _capacity_command_kwargs(app, vehicle_definition_id, source_id, destination_id, units):
    capacity = app._simulation.transport.transport_capacity_for_units(
        vehicle_definition_id, source_id, destination_id, units, day=app._simulation.day
    )
    return {
        "target_forward_t_per_day": capacity.forward_t_per_day,
        "target_reverse_t_per_day": capacity.reverse_t_per_day,
    }


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
            procurement_policy="extended_wait",
            site_cell_id=str(ids.EARTH_CELL_INDUSTRIAL),
        )
    ).created_id

    surface_facility_id = sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )

    survey_provider_id = ids.LUNAR_RESOURCE_SURVEY_ORBITER
    survey_mode_id = "remote_orbital_spectrometry"
    survey_goal = 2
    survey_key = next(
        key
        for key in sim.survey.targets
        if sim.survey.can_start(
            ids.LUNAR_ORBIT, survey_provider_id, survey_mode_id,
            key[0], key[1], survey_goal, sim.day
        )
    )
    app.execute(
        StartSurvey(
            str(ids.LUNAR_ORBIT), str(survey_provider_id), survey_mode_id,
            str(survey_key[0]), str(survey_key[1]), survey_goal, priority=4,
        )
    )
    target = sim.survey.targets[survey_key]
    sim.survey.knowledge_progress[survey_key] = target.thresholds[0] / 2.0

    target_id = app.execute(SetTargetStock(str(LEO), str(ids.MACHINERY), 1.0, priority=4)).created_id
    assert target_id is not None
    app.execute(SetSupplyRoutingConstraint(
        destination_id=str(LEO), owner_kind="target_stock", owner_id=target_id,
        resource_id=str(ids.MACHINERY), source_node_id=str(EARTH),
    ))
    allocation_id = app.execute(
        CreateTransportAllocation(
            str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
            **_capacity_command_kwargs(app, REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, 1),
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

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)



def test_supply_routing_constraint_roundtrips_and_preserves_future_resolution(tmp_path):
    app = build_game_application()
    target_id = app.execute(
        SetTargetStock(str(LEO), str(ids.MACHINERY), 2.0, priority=4)
    ).created_id
    assert target_id is not None
    allocation_id = app.execute(
        CreateTransportAllocation(
            str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
            **_capacity_command_kwargs(app, REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, 1),
        )
    ).created_id
    assert allocation_id is not None
    app.execute(SetSupplyRoutingConstraint(
        destination_id=str(LEO),
        owner_kind="target_stock",
        owner_id=target_id,
        resource_id=str(ids.MACHINERY),
        source_node_id=str(EARTH),
        required_transport_allocation_ids=(allocation_id,),
    ))

    path = tmp_path / "supply-routing-constraint.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None

    from space_idle import GetLogistics
    view = loaded.query(GetLogistics())
    constraint = next(
        item for item in view.routing_constraints
        if item.owner_kind == "target_stock" and item.owner_id == target_id
    )
    assert constraint.destination_id == str(LEO)
    assert constraint.resource_id == str(ids.MACHINERY)
    assert constraint.source_node_id == str(EARTH)
    assert constraint.required_transport_allocation_ids == (allocation_id,)
    requirement = next(
        item for item in view.requirements
        if item.owner_kind == "target_stock" and item.owner_id == target_id
    )
    assert requirement.routing_constraint_source_id == str(EARTH)
    assert requirement.routing_constraint_transport_allocation_ids == (allocation_id,)

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)


def test_facility_owned_process_selection_roundtrips_in_facility_state(tmp_path):
    app = build_game_application()
    sim = app._simulation
    process = sim.industry.processes[ids.PROCESS_BASIC_STRUCTURAL_MATERIAL]
    facility = next(
        row for row in sim.facilities.facilities.values()
        if row.definition_id == process.facility_def_id
    )

    alternate_process_id = DefinitionId("test.process.alternate_structural_material")
    sim.industry.processes[alternate_process_id] = ProcessSpec(
        alternate_process_id,
        "Alternate structural material",
        process.facility_def_id,
        {},
        {ids.STRUCTURAL_COMPONENTS: 0.01},
    )
    unresolved = next(
        item for item in app.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if item.facility_id == str(facility.id)
    )
    assert unresolved.selection_required
    assert unresolved.process_id is None
    assert tuple(process_id for process_id, _name in unresolved.process_options) == tuple(sorted((
        str(process.id), str(alternate_process_id),
    )))

    app.execute(SetFacilityProcess(str(facility.id), str(process.id)))
    assert facility.selected_process_id == process.id
    selected = next(
        item for item in app.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if item.facility_id == str(facility.id)
    )
    assert not selected.selection_required
    assert selected.process_id == str(process.id)
    del sim.industry.processes[alternate_process_id]

    state = capture_state(sim)
    assert "industry" not in state
    saved_facility = next(
        row for row in state["facilities"]["items"]
        if row["id"] == str(facility.id)
    )
    assert saved_facility["selected_process_id"] == str(process.id)

    path = tmp_path / "facility-process.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    loaded_facility = loaded._simulation.facilities.facilities[facility.id]
    assert loaded_facility.selected_process_id == process.id
    row = next(
        item for item in loaded.query(GetOperationalNode(str(facility.operational_node_id))).industry
        if item.facility_id == str(facility.id)
    )
    assert row.process_id == str(process.id)
    assert not row.selection_required

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)




def test_offline_progress_matches_normal_time_and_is_fractionally_composable(tmp_path):
    saved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    elapsed_days = 3
    policy = OfflineProgressPolicy(real_seconds_per_game_day=1.0, max_game_days_per_resume=20)
    original = _make_nontrivial_state()
    sim = original._simulation

    # Offline equivalence is one simulation-boundary contract across active domains.
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
        str(ids.EARTH), str(ids.EARTH_CELL_COASTAL), procurement_policy="immediate"
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

    fractional_a = build_game_application()
    fractional_b = build_game_application()
    fractional_policy = OfflineProgressPolicy(real_seconds_per_game_day=10.0)
    fractional_a._simulation.advance_offline(6.0, fractional_policy)
    fractional_a._simulation.advance_offline(6.0, fractional_policy)
    fractional_b._simulation.advance_offline(12.0, fractional_policy)
    assert capture_state(fractional_a._simulation) == capture_state(fractional_b._simulation)


def test_save_load_preserves_in_flight_cargo_and_rederives_transport_projection(tmp_path):
    app = build_game_application()
    sim = app._simulation
    allocation_id = app.execute(CreateTransportAllocation(
        str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
        **_capacity_command_kwargs(
            app, ids.REUSABLE_LAUNCH_VEHICLE, ids.EARTH, ids.LEO, 1
        ),
    )).created_id
    assert allocation_id is not None

    sim.inventory.stock[(ids.LEO, ids.MACHINERY)] = 0.0
    sim.inventory.add(ids.EARTH, ids.MACHINERY, 1.0)
    target_id = sim.logistics.set_target_stock(ids.LEO, ids.MACHINERY, 0.5, 5)
    sim.advance_days(1)
    assert any(
        row.owner_id == target_id for row in sim.logistics.cargo_flows.values()
    )

    allocation_entity_id = EntityId(allocation_id)
    selected_plan = sim.transport.derive_transport_service_plan(
        allocation_entity_id, sim.day
    )
    sim.transport.set_transport_movement_constraint(
        allocation_entity_id, selected_plan.forward_path, day=sim.day
    )
    before_capacity = sim.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=sim.day
    )
    before_required_units = sim.transport.allocation_required_units(
        allocation_entity_id, sim.day
    )
    before_flows = dict(sim.logistics.cargo_flows)
    transport_state = capture_state(sim)["transport"]
    allocation_state = next(
        row for row in transport_state["transport_allocations"]
        if row["id"] == allocation_id
    )
    assert allocation_state["movement_hard_constraint"] == [
        str(value) for value in selected_plan.forward_path
    ]
    assert "required_units" not in allocation_state
    assert "selected_plan" not in allocation_state
    assert "nominal_capacity" not in allocation_state

    path = tmp_path / "cargo-flow.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application_for_load)

    assert loaded._simulation.logistics.cargo_flows == before_flows
    assert loaded._simulation.logistics.current_transport_capacity_snapshot(
        allocation_entity_id, day=loaded._simulation.day
    ) == before_capacity
    loaded_allocation = loaded._simulation.transport.transport_allocations[allocation_entity_id]
    assert loaded_allocation.movement_hard_constraint == selected_plan.forward_path
    assert loaded._simulation.transport.allocation_required_units(
        allocation_entity_id, loaded._simulation.day
    ) == before_required_units
    assert loaded._simulation.transport.derive_transport_service_plan(
        allocation_entity_id, loaded._simulation.day
    ).forward_path == selected_plan.forward_path


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
    assert decision.allocations.resources.rows
    infrastructure_before = app.query(
        GetOperationalNode(str(ids.EARTH))
    ).surface_infrastructure
    analytics_before = app.query(
        GetDependencyAnalytics("operational_nodes", node_ids=(str(ids.EARTH),))
    )
    movement_before = sim.transport.movement_plan_candidates(ids.EARTH, ids.LEO)
    assert len(movement_before) == 1
    movement_geometry_before = sim.transport.movement_geometry(movement_before[0].id)
    assert infrastructure_before is not None
    assert capture_state(sim) == before
    assert "surface_infrastructure" not in before
    assert "dependency_analytics" not in before
    assert "allocation_projection" not in before
    assert "movement_plans" not in before.get("transport", {})
    assert "extraction" not in before
    assert before["survey"]["knowledge_progress"]
    assert all(
        "cell_id" in row and "resource_id" in row and "location_id" not in row
        for row in before["survey"]["knowledge_progress"]
    )

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
    movement_after = loaded._simulation.transport.movement_plan_candidates(ids.EARTH, ids.LEO)
    assert tuple(plan.id for plan in movement_after) == tuple(plan.id for plan in movement_before)
    assert loaded._simulation.transport.movement_geometry(
        movement_after[0].id
    ) == movement_geometry_before


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


def test_research_authoritative_state_roundtrips_without_quantity_duplication(tmp_path):
    provider_id = DefinitionId("test.research_provider.persistence_fleet")

    def factory(*, for_load: bool):
        app = build_game_application_for_load() if for_load else build_game_application()
        app._simulation.research.providers[provider_id] = ResearchProviderSpec(
            provider_id,
            ResearchProviderSourceKind.FLEET,
            ids.REUSABLE_ORBITAL_CARGO_TUG,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 2.0, 25.0, 1.5),),
        )
        return app

    app = factory(for_load=False)
    sim = app._simulation
    research_id = ids.TECH_ORBITAL_OPERATIONS
    sim.research.active[research_id] = ResearchState(
        research_id,
        "prototype",
        stage_progress=0.0,
        stage_started_day=sim.day,
    )
    app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    execution_context = sim.research.active[research_id].execution_context
    assert execution_context is not None

    result = app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    ))
    assignment_id = result.created_id
    assert assignment_id is not None
    app.execute(SetResearchProviderAssignmentPriority(assignment_id, 4))
    assignment = next(iter(sim.research.provider_assignments.values()))
    before_commitment = sim.transport.fleet_commitment_snapshot(
        assignment.fleet_commitment_ref
    )
    assert before_commitment is not None and before_commitment.quantity == 1

    path = tmp_path / "research-authoritative-state.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    raw = json.loads(path.read_text(encoding="utf-8"))
    saved_assignment = raw["state"]["research"]["provider_assignments"][0]
    assert saved_assignment["fleet_commitment_ref"] == str(assignment.fleet_commitment_ref)
    assert "quantity" not in saved_assignment
    assert saved_assignment["vehicle_definition_id"] == str(ids.REUSABLE_ORBITAL_CARGO_TUG)

    loaded, offline = load_game(path, lambda: factory(for_load=True))
    assert offline is None
    loaded_sim = loaded._simulation
    assert loaded_sim.research.active[research_id].execution_context == execution_context
    assert capture_state(loaded_sim)["research"] == capture_state(sim)["research"]
    assert loaded.query(GetResearch()) == app.query(GetResearch())

    loaded_assignment = next(iter(loaded_sim.research.provider_assignments.values()))
    assert str(loaded_assignment.id) == assignment_id
    assert loaded_assignment.provider_definition_id == provider_id
    assert loaded_assignment.priority == 4
    loaded_commitment = loaded_sim.transport.fleet_commitment_snapshot(
        loaded_assignment.fleet_commitment_ref
    )
    assert loaded_commitment is not None
    assert loaded_commitment.quantity == 1
    assert loaded_commitment.owner_activity_ref.activity_id == loaded_assignment.id

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded_sim) == capture_state(sim)


def test_survey_provider_assignment_roundtrips_as_fleet_owned_capacity(tmp_path):
    app = build_game_application()
    sim = app._simulation
    sim.transport.add_fleet_units(
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, 1, ids.LUNAR_ORBIT, day=sim.day
    )
    assignment_id = app.execute(SetSurveyProviderFleetQuantity(
        str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 1
    )).created_id
    assert assignment_id is not None
    key = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.REGOLITH)
    app.execute(StartSurvey(
        str(ids.LUNAR_ORBIT), str(ids.LUNAR_FLEET_SURVEY_PROVIDER),
        "fleet_remote_mapping", str(key[0]), str(key[1]), 1,
    ))

    assignment = next(iter(sim.survey.provider_assignments.values()))
    commitment = sim.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref)
    assert commitment is not None and commitment.quantity == 1
    path = tmp_path / "survey-provider-assignment.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    raw = json.loads(path.read_text(encoding="utf-8"))
    saved_assignment = raw["state"]["survey"]["provider_assignments"][0]
    assert saved_assignment["fleet_commitment_ref"] == str(assignment.fleet_commitment_ref)
    assert "quantity" not in saved_assignment
    saved_campaign = raw["state"]["survey"]["campaigns"][0]
    assert "fleet_commitment_ref" not in saved_campaign

    loaded, offline = load_game(path, build_game_application_for_load)
    assert offline is None
    loaded_sim = loaded._simulation
    assert capture_state(loaded_sim)["survey"] == capture_state(sim)["survey"]
    loaded_assignment = next(iter(loaded_sim.survey.provider_assignments.values()))
    loaded_commitment = loaded_sim.transport.fleet_commitment_snapshot(
        loaded_assignment.fleet_commitment_ref
    )
    assert loaded_commitment is not None
    assert loaded_commitment.quantity == 1
    assert loaded_commitment.owner_activity_ref.activity_type == "survey_provider_assignment"
    assert loaded.query(GetSurveys(str(ids.LUNAR_ORBIT))) == app.query(GetSurveys(str(ids.LUNAR_ORBIT)))

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded_sim) == capture_state(sim)
