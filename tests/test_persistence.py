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
from space_idle.persistence import SaveFormatError, capture_state, load_game, save_game
from space_idle.industry import ProcessSpec
from space_idle.research import (
    ResearchProviderLevelSpec, ResearchProviderSourceKind, ResearchProviderSpec,
    ResearchState,
)
from space_idle.shared import EntityId, DefinitionId
from space_idle.simulation import OfflineProgressPolicy


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
    survey_cells = (ids.MOON_CELL_FARSIDE_HIGHLANDS, ids.MOON_CELL_NEARSIDE_MARE)
    survey_resources = (ids.REGOLITH, ids.WATER)
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
    assert tuple(option.process_id for option in unresolved.process_options) == tuple(sorted((
        str(process.id), str(alternate_process_id),
    )))
    assert unresolved.process_comparison_axes
    assert any(axis.differs for axis in unresolved.process_comparison_axes)
    primary_option = next(
        option for option in unresolved.process_options if option.process_id == str(process.id)
    )
    assert primary_option.input_rates_per_day == tuple(
        (str(resource_id), amount)
        for resource_id, amount in sorted(process.inputs_per_day.items(), key=lambda row: str(row[0]))
    )
    assert primary_option.output_rates_per_day == tuple(
        (str(resource_id), amount)
        for resource_id, amount in sorted(process.outputs_per_day.items(), key=lambda row: str(row[0]))
    )
    assert primary_option.service_requirements == ((f"process:{process.id}", 1.0),)
    assert {value.axis_key for value in primary_option.comparison_values} == {
        axis.key for axis in unresolved.process_comparison_axes
    }

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
    sim.facilities.install(
        ids.SURFACE_DISTRIBUTION_HUB,
        ids.EARTH,
        site_cell_id=ids.EARTH_CELL_INDUSTRIAL,
    )
    survey_campaign_id = app.execute(StartSurvey(
        target_cell_ids=(str(ids.MOON_CELL_FARSIDE_HIGHLANDS),),
        resource_ids=(str(ids.REGOLITH),),
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

    def research_factory(*, for_load: bool):
        app = build_game_application_for_load() if for_load else build_game_application()
        app._simulation.research.providers[provider_id] = ResearchProviderSpec(
            provider_id,
            ResearchProviderSourceKind.FLEET,
            ids.REUSABLE_ORBITAL_CARGO_TUG,
            tier=2,
            levels=(ResearchProviderLevelSpec(1, 2.0, 25.0, 1.5),),
        )
        return app

    research_app = research_factory(for_load=False)
    research_sim = research_app._simulation
    research_id = ids.TECH_ORBITAL_OPERATIONS
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


@pytest.mark.parametrize(
    ("case", "error_pattern"),
    (
        (("missing", "storage", "infrastructure_capacity"), "save domain section has invalid fields"),
        (("missing", "logistics", "routing_constraints"), "save domain section has invalid fields"),
        (("missing", "survey", "campaigns"), "save domain section has invalid fields"),
        (("unexpected", "envelope"), "save file has invalid fields"),
        (("unexpected", "transport_allocation"), "transport allocation has invalid fields"),
        (("unexpected", "survey_campaign"), "survey campaign has invalid fields"),
        (("unexpected", "construction_project"), "construction project has invalid fields"),
        (("identity", "world_definition_id"), "save world definition mismatch"),
        (("identity", "scenario_id"), "save scenario mismatch"),
    ),
)
def test_save_envelope_and_persisted_boundaries_reject_invalid_contracts(tmp_path, case, error_pattern):
    app = _make_nontrivial_state()
    path = tmp_path / ("schema-" + "-".join(case) + ".json")
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    payload = json.loads(path.read_text(encoding="utf-8"))

    if case[0] == "missing":
        _kind, domain_key, field = case
        del payload["state"][domain_key][field]
    elif case[0] == "unexpected":
        _kind, boundary = case
        targets = {
            "envelope": payload,
            "transport_allocation": payload["state"]["transport"]["transport_allocations"][0],
            "survey_campaign": payload["state"]["survey"]["campaigns"][0],
            "construction_project": payload["state"]["projects"]["items"][0],
        }
        targets[boundary]["unexpected_field"] = None
    else:
        _kind, field = case
        payload[field] = "test.mismatched.definition"

    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SaveFormatError, match=error_pattern):
        load_game(path, build_game_application_for_load)
