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
    SurveyProviderConstraintInput,
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
from space_idle.persistence import (
    SAVE_SCHEMA_VERSION, SaveFormatError, capture_state, load_game, save_game,
)
from space_idle.research import (
    ResearchDefinition, ResearchPrototypeStageSpec,
    ResearchProviderLevelSpec, ResearchProviderSourceKind, ResearchProviderSpec,
    ResearchState,
)
from space_idle.shared import EntityId, DefinitionId, SpatialNodeId
from space_idle.site import SiteRequirements
from space_idle.simulation import OfflineProgressPolicy
from space_idle.spatial import SpatialNodeDef, SpatialNodeKind
from space_idle.terraforming import PlanetaryClimateState, TerraformingEnvironmentOverlay, TerraformingService
from space_idle.validation_support import ConfigurationError


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
        if item.id == str(ids.RP_RESOURCE_CHAIN_01)
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
    selected_process = sim.industry.processes[ids.PROCESS_BASIC_STRUCTURAL_MATERIAL]
    process_facility = next(
        row for row in sim.facilities.facilities.values()
        if row.definition_id == selected_process.facility_def_id
    )
    app.execute(SetFacilityProcess(str(process_facility.id), str(selected_process.id)))

    survey_provider_id = ids.LUNAR_RESOURCE_SURVEY_ORBITER
    survey_mode_id = "remote_orbital_spectrometry"
    survey_goal = 2
    survey_cells = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE)
    survey_resources = (ids.MINERAL_FEEDSTOCK, ids.VOLATILE_BEARING_MATERIAL)
    survey_key = (survey_cells[0], survey_resources[0])
    app.execute(
        StartSurvey(
            target_cell_ids=tuple(map(str, survey_cells)),
            resource_ids=tuple(map(str, survey_resources)),
            goal_knowledge_level=survey_goal,
            provider_constraint=SurveyProviderConstraintInput(
                str(survey_provider_id), str(ids.LUNAR_ORBIT)
            ),
            observation_mode_constraint=survey_mode_id,
            priority=4,
        )
    )
    target = sim.survey.targets[survey_key]
    sim.survey.knowledge_progress[survey_key] = target.thresholds[0] / 2.0

    target_id = app.execute(SetTargetStock(str(LEO), str(ids.MACHINERY), 1.0, priority=4)).created_id
    assert target_id is not None
    allocation_id = app.execute(
        CreateTransportAllocation(
            str(REUSABLE_LAUNCH_VEHICLE), str(EARTH), str(LEO),
            **_capacity_command_kwargs(app, REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, 1),
        )
    ).created_id
    assert project_id is not None and allocation_id is not None
    app.execute(SetSupplyRoutingConstraint(
        destination_id=str(LEO), owner_kind="target_stock", owner_id=target_id,
        resource_id=str(ids.MACHINERY), source_node_id=str(EARTH),
        required_transport_allocation_ids=(allocation_id,),
    ))
    app.execute(PauseBuild(project_id))
    app.execute(AdvanceTime(1))
    app.execute(PauseFacility(str(surface_facility_id)))
    app.execute(PauseResearch(research.id))
    app.execute(PauseTransportAllocation(allocation_id))
    sim.research.knowledge_state.add(ids.EXPERIENCE_TRANSPORT_OPERATIONS, 2.5)
    return app



def test_authoritative_snapshot_roundtrip_preserves_domain_ownership_and_future_behavior(tmp_path):
    app = _make_nontrivial_state()
    body_id = ids.EARTH_BODY
    species = DefinitionId("test.atmosphere.n2")
    climate = PlanetaryClimateState(body_id, 101325.0, 1.225, 288.0, {species: 1.0})
    app._simulation.environment.overlays.append(
        TerraformingEnvironmentOverlay(TerraformingService({body_id: climate}))
    )
    overlay = app._simulation.environment.overlays[-1]
    overlay.service.add_atmosphere(body_id, 250.0, 0.01, species, 0.0, 3.5)

    def load_factory():
        loaded_app = build_game_application_for_load()
        loaded_climate = PlanetaryClimateState(
            body_id, 101325.0, 1.225, 288.0, {species: 1.0}
        )
        loaded_app._simulation.environment.overlays.append(
            TerraformingEnvironmentOverlay(TerraformingService({body_id: loaded_climate}))
        )
        return loaded_app

    path = tmp_path / "game.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    payload = json.loads(path.read_text(encoding="utf-8"))
    state = payload["state"]
    assert "industry" not in state
    assert "day" not in state
    assert "pending_offline_game_days" not in state
    assert "boundary_used_by_constraint" not in state
    assert set(state["core"]) == {
        "day", "pending_offline_game_days", "boundary_service_usage",
    }
    assert any(
        row["selected_process_id"] == str(ids.PROCESS_BASIC_STRUCTURAL_MATERIAL)
        for row in state["facilities"]["items"]
    )

    loaded, offline = load_game(path, load_factory)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

    app.execute(AdvanceTime(1))
    loaded.execute(AdvanceTime(1))
    assert capture_state(loaded._simulation) == capture_state(app._simulation)

def test_offline_load_matches_direct_progress_for_active_domain_state(tmp_path):
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



def test_derived_projections_are_not_persisted_and_rederive_after_load(tmp_path):
    app = build_game_application()
    app.execute(ProduceVehicle(str(REUSABLE_ORBITAL_CARGO_TUG), str(EARTH)))
    sim = app._simulation
    sim.graph.develop_surface_cell(ids.EARTH, ids.EARTH_CELL_COASTAL)
    dormant = SpatialNodeId("test.node.context_only")
    sim.graph.add(
        SpatialNodeDef(
            dormant,
            "Context only",
            ids.SOL_SYSTEM,
            sim.graph.bodies[ids.MOON].system_local_transport_geometry,
            body_id=ids.MOON,
            kind=SpatialNodeKind.ORBITAL,
            inherits_parent_environment=False,
        )
    )
    before_operational = set(sim.graph.operational_node_ids())
    before_locations = set(sim.graph.locations)
    assert dormant not in before_operational
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    survey_campaign_id = app.execute(StartSurvey(
        target_cell_ids=(str(ids.MOON_CELL_FARSIDE_HIGHLANDS),),
        resource_ids=(str(ids.MINERAL_FEEDSTOCK),),
        goal_knowledge_level=1,
        provider_constraint=SurveyProviderConstraintInput(
            str(ids.LUNAR_RESOURCE_SURVEY_ORBITER), str(ids.LUNAR_ORBIT)
        ),
        observation_mode_constraint="remote_orbital_spectrometry",
    )).created_id
    assert survey_campaign_id is not None
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
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "developed_cell_ids" in raw["state"]["environment"]["locations"][0]
    assert "owner_location_id" not in json.dumps(raw["state"]["environment"])
    saved_campaign = next(
        row
        for row in raw["state"]["survey"]["campaigns"]
        if row["id"] == survey_campaign_id
    )
    assert "fleet_commitment_ref" not in saved_campaign
    assert "resolved_provider_definition_id" not in saved_campaign
    assert "resolved_observation_mode_id" not in saved_campaign
    assert "unfinished_targets" not in saved_campaign

    loaded, _ = load_game(path, build_game_application_for_load)
    assert capture_state(loaded._simulation) == before
    loaded_graph = loaded._simulation.graph
    assert loaded_graph.owner_of_cell(ids.EARTH_CELL_COASTAL) == ids.EARTH
    assert set(loaded_graph.operational_node_ids()) == before_operational
    assert set(loaded_graph.locations) == before_locations
    assert dormant not in loaded_graph.nodes
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



def _roundtrip_fleet_backed_assignment(
    tmp_path,
    *,
    name: str,
    app,
    domain_key: str,
    assignment,
    load_factory,
):
    sim = app._simulation
    commitment = sim.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref)
    assert commitment is not None and commitment.quantity == 1

    path = tmp_path / f"{name}-fleet-backed-provider.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    raw = json.loads(path.read_text(encoding="utf-8"))
    saved_assignment = raw["state"][domain_key]["provider_assignments"][0]
    assert saved_assignment["fleet_commitment_ref"] == str(assignment.fleet_commitment_ref)
    assert "quantity" not in saved_assignment

    loaded, offline = load_game(path, load_factory)
    assert offline is None
    loaded_sim = loaded._simulation
    loaded_domain = getattr(loaded_sim, domain_key)
    loaded_assignment = next(iter(loaded_domain.provider_assignments.values()))
    loaded_commitment = loaded_sim.transport.fleet_commitment_snapshot(
        loaded_assignment.fleet_commitment_ref
    )
    assert loaded_commitment is not None and loaded_commitment.quantity == 1
    return raw, loaded, loaded_assignment, loaded_commitment


def test_fleet_backed_provider_state_roundtrips_with_quantity_owned_only_by_fleet_commitment(tmp_path):
    provider_id = DefinitionId("test.research_provider.persistence_fleet")
    research_id = DefinitionId("test.research.persistence_prototype")

    def research_factory(*, for_load: bool):
        app = build_game_application_for_load() if for_load else build_game_application()
        app._simulation.research.providers[provider_id] = ResearchProviderSpec(
            provider_id,
            ResearchProviderSourceKind.FLEET,
            ids.REUSABLE_ORBITAL_CARGO_TUG,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 2.0, 25.0, 1.5),),
        )
        app._simulation.research.definitions[research_id] = ResearchDefinition(
            research_id,
            "Persistence Prototype Research",
            (ResearchPrototypeStageSpec("prototype", {}, SiteRequirements()),),
        )
        return app

    research_app = research_factory(for_load=False)
    research_sim = research_app._simulation
    research_sim.research.active[research_id] = ResearchState(
        research_id,
        "prototype",
        stage_progress=0.0,
        stage_started_day=research_sim.day,
    )
    research_app.execute(SetResearchPrototypeSite(str(research_id), "prototype", str(EARTH)))
    execution_context = research_sim.research.active[research_id].execution_context
    assert execution_context is not None

    result = research_app.execute(SetResearchProviderFleetQuantity(
        str(provider_id), str(ids.LEO), str(ids.REUSABLE_ORBITAL_CARGO_TUG), 1
    ))
    research_assignment_id = result.created_id
    assert research_assignment_id is not None
    research_app.execute(SetResearchProviderAssignmentPriority(research_assignment_id, 4))
    research_assignment = next(iter(research_sim.research.provider_assignments.values()))
    research_raw, loaded_research, loaded_research_assignment, loaded_research_commitment = (
        _roundtrip_fleet_backed_assignment(
            tmp_path,
            name="research",
            app=research_app,
            domain_key="research",
            assignment=research_assignment,
            load_factory=lambda: research_factory(for_load=True),
        )
    )
    saved_research_assignment = research_raw["state"]["research"]["provider_assignments"][0]
    assert saved_research_assignment["vehicle_definition_id"] == str(
        ids.REUSABLE_ORBITAL_CARGO_TUG
    )
    loaded_research_sim = loaded_research._simulation
    assert loaded_research_sim.research.active[research_id].execution_context == execution_context
    assert capture_state(loaded_research_sim)["research"] == capture_state(research_sim)["research"]
    assert loaded_research.query(GetResearch()) == research_app.query(GetResearch())
    assert str(loaded_research_assignment.id) == research_assignment_id
    assert loaded_research_assignment.provider_definition_id == provider_id
    assert loaded_research_assignment.priority == 4
    assert loaded_research_commitment.owner_activity_ref.activity_id == loaded_research_assignment.id

    survey_app = build_game_application()
    survey_sim = survey_app._simulation
    survey_sim.transport.add_fleet_units(
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, 1, ids.LUNAR_ORBIT, day=survey_sim.day
    )
    survey_assignment_id = survey_app.execute(SetSurveyProviderFleetQuantity(
        str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 1
    )).created_id
    assert survey_assignment_id is not None
    survey_assignment = next(iter(survey_sim.survey.provider_assignments.values()))
    survey_raw, loaded_survey, loaded_survey_assignment, loaded_survey_commitment = (
        _roundtrip_fleet_backed_assignment(
            tmp_path,
            name="survey",
            app=survey_app,
            domain_key="survey",
            assignment=survey_assignment,
            load_factory=build_game_application_for_load,
        )
    )

    loaded_survey_sim = loaded_survey._simulation
    assert capture_state(loaded_survey_sim)["survey"] == capture_state(survey_sim)["survey"]
    assert loaded_survey_assignment.id == survey_assignment.id
    assert loaded_survey_commitment.owner_activity_ref.activity_type == "survey_provider_assignment"

    # Future behavior must remain equivalent after restoring either domain-owned
    # assignment while the physical Fleet quantity continues to be owned only by
    # the Transport Fleet Commitment.
    research_app.execute(AdvanceTime(1))
    loaded_research.execute(AdvanceTime(1))
    assert capture_state(loaded_research_sim) == capture_state(research_sim)
    survey_app.execute(AdvanceTime(1))
    loaded_survey.execute(AdvanceTime(1))
    assert capture_state(loaded_survey_sim) == capture_state(survey_sim)


def _corrupt_saved_snapshot(path, case: str) -> None:
    if case == "invalid_utf8":
        path.write_bytes(b"\xff\xfe\x00not-json")
        return
    if case == "duplicate_json_key":
        text = path.read_text(encoding="utf-8")
        marker = f'"schema_version": {SAVE_SCHEMA_VERSION},'
        path.write_text(
            text.replace(marker, f'{marker}\n  {marker}', 1),
            encoding="utf-8",
        )
        return

    payload = json.loads(path.read_text(encoding="utf-8"))
    state = payload["state"]
    if case == "missing_domain_field":
        del state["storage"]["infrastructure_capacity"]
    elif case == "unexpected_envelope_field":
        payload["unexpected_field"] = None
    elif case == "unexpected_nested_field":
        state["transport"]["transport_allocations"][0]["unexpected_field"] = None
    elif case == "identity_mismatch":
        payload["world_definition_id"] = "test.mismatched.definition"
    elif case == "invalid_timestamp":
        payload["saved_at"] = "not-a-date"
    elif case == "wrong_boolean_type":
        state["facilities"]["items"][0]["paused"] = "false"
    elif case == "wrong_integer_type":
        state["facilities"]["items"][0]["level"] = "1"
    elif case == "wrong_identifier_type":
        state["projects"]["items"][0]["operational_node_id"] = 1
    elif case == "duplicate_entity_id":
        state["facilities"]["items"].append(dict(state["facilities"]["items"][0]))
    elif case == "stale_generated_id_counter":
        state["facilities"]["counter"] = 0
    elif case == "missing_provider_fleet_commitment":
        state["survey"]["provider_assignments"][0][
            "fleet_commitment_ref"
        ] = "missing.commitment"
    elif case == "invalid_nested_collection_type":
        state["transport"]["transport_allocations"][0][
            "movement_hard_constraint"
        ] = "movement.plan.not-a-list"
    elif case == "noncanonical_domain_order":
        state["facilities"]["items"].reverse()
    elif case == "cross_domain_runtime_violation":
        provider = state["market"]["provider_states"][0]
        resource_id = next(iter(provider["supply_available_t"]))
        provider["supply_available_t"][resource_id] = 1.0e12
    elif case == "post_rebuild_capacity_violation":
        state["inventory"]["stock"][0]["amount"] = 1.0e12
    elif case == "non_finite_number":
        state["core"]["pending_offline_game_days"] = float("nan")
    else:
        raise AssertionError(f"unknown corruption case: {case}")
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_boundary_rejects_noncanonical_or_invalid_snapshots(tmp_path):
    app = _make_nontrivial_state()
    sim = app._simulation
    sim.transport.add_fleet_units(
        ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT, 1, ids.LUNAR_ORBIT, day=sim.day
    )
    app.execute(SetSurveyProviderFleetQuantity(
        str(ids.LUNAR_FLEET_SURVEY_PROVIDER), str(ids.LUNAR_ORBIT),
        str(ids.LUNAR_ORBITAL_SURVEY_SPACECRAFT), 1,
    ))
    baseline_path = tmp_path / "baseline.json"
    save_game(app, baseline_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    baseline = baseline_path.read_bytes()

    cases = (
        "missing_domain_field",
        "unexpected_envelope_field",
        "unexpected_nested_field",
        "identity_mismatch",
        "invalid_timestamp",
        "wrong_boolean_type",
        "wrong_integer_type",
        "wrong_identifier_type",
        "duplicate_entity_id",
        "stale_generated_id_counter",
        "missing_provider_fleet_commitment",
        "invalid_nested_collection_type",
        "noncanonical_domain_order",
        "cross_domain_runtime_violation",
        "post_rebuild_capacity_violation",
        "duplicate_json_key",
        "invalid_utf8",
        "non_finite_number",
    )
    for case in cases:
        path = tmp_path / f"invalid-{case}.json"
        path.write_bytes(baseline)
        _corrupt_saved_snapshot(path, case)
        try:
            load_game(path, build_game_application_for_load)
        except SaveFormatError:
            continue
        pytest.fail(f"load accepted invalid persisted snapshot: {case}")


def test_save_commit_preserves_existing_snapshot_across_validation_and_write_failures(
    tmp_path, monkeypatch
):
    path = tmp_path / "protected.json"
    app = build_game_application()
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    original = path.read_bytes()

    provider = next(iter(app._simulation.market.provider_states.values()))
    resource_id = next(iter(provider.supply_available_t))
    provider.supply_available_t[resource_id] = 1.0e12
    with pytest.raises(ConfigurationError):
        save_game(app, path, saved_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert path.read_bytes() == original

    fresh_app = build_game_application()
    with monkeypatch.context() as patch:
        patch.setattr(
            "space_idle.persistence.os.replace",
            lambda _source, _target: (_ for _ in ()).throw(OSError("replace failed")),
        )
        with pytest.raises(OSError, match="replace failed"):
            save_game(
                fresh_app, path, saved_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
            )
    assert path.read_bytes() == original
