from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime,
    ApplicationError,
    CancelBuild,
    CancelFounding,
    DevelopSurfaceCell,
    PlanOperationalNodeFounding,
    NonSurfaceOperationalNodeFoundingTarget,
    SurfaceLocationFoundingTarget,
    GetProjects,
    GetSurfaceMap,
    build_game_application,
)
from space_idle.bootstrap import build_game_application_for_load
from space_idle.content import base_ids as ids
from space_idle.content import base_requirements as req
from space_idle.persistence import load_game, save_game
from space_idle.founding import (
    DeploymentRecipe, FoundingFacilityDeployment, FoundingResourceRequirement,
    NonSurfaceOperationalNodeTargetSpec,
)
from space_idle.facilities import FacilityDef
from space_idle.power import FixedGeneration, PowerSpec
from space_idle.storage import StorageProviderSpec
from space_idle.shared import DefinitionId, EntityId, SpatialNodeId
from space_idle.spatial import CharacteristicTransportGeometry, SpatialNodeDef, SpatialNodeKind
from space_idle.spatial_claims import SurfaceCellClaim


def _survey_cell_to_l2(sim, cell_id):
    target = sim.survey.targets[(cell_id, ids.REGOLITH)]
    key = (target.cell_id, target.resource_id)
    sim.survey.knowledge_progress[key] = target.thresholds[1]
    sim.survey.estimated_potential[key] = sim.survey.actual_potential(*key) * 0.9
    sim.survey.knowledge_precision_fraction[key] = 0.35
    assert sim.survey.knowledge_level(cell_id, ids.REGOLITH) >= 2


def _surface_target(sim, body_id, cell_id):
    return sim.founding.surface_target_spec(body_id, cell_id)


def _advance_founding_to_deployment(app, project):
    sim = app._simulation
    while project.status.value == "preparing":
        before = project.preparation_done
        app.execute(AdvanceTime(1))
        assert (
            project.status.value != "preparing"
            or project.preparation_done > before + 1e-12
        ), "ready founding preparation made no canonical-tick progress"
    assert project.status.value == "deploying"
    assert project.movement_execution_id is not None
    return sim.transport.movement_executions[project.movement_execution_id]


def _advance_founding_to_completion(app, project):
    sim = app._simulation
    execution = (
        _advance_founding_to_deployment(app, project)
        if project.status.value == "preparing"
        else sim.transport.movement_executions[project.movement_execution_id]
    )
    remaining_days = execution.completion_day - sim.day
    assert remaining_days > 0
    app.execute(AdvanceTime(remaining_days))
    assert project.status.value == "complete"
    return execution


def _stage_founding_resources(sim):
    recipe = sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    for req in recipe.payload_resources:
        sim.inventory.add(ids.LUNAR_ORBIT, req.resource_id, req.amount_t + 1.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 10.0)
    return recipe


def _found_command(name: str, cell_id):
    return PlanOperationalNodeFounding(
        staging_node_id=str(ids.LUNAR_ORBIT),
        display_name=name,
        target_spec=SurfaceLocationFoundingTarget(
            "surface_location", str(ids.MOON), str(cell_id)
        ),
        deployment_recipe_id=str(ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE),
        vehicle_definition_id=str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )


def test_knowledge_requirements_are_subject_specific_and_gate_founding_without_early_materialization():
    app = build_game_application()
    sim = app._simulation

    earth_cell = ids.EARTH_CELL_COASTAL
    water_key = (earth_cell, ids.WATER)
    unrelated_key = (earth_cell, ids.METAL_ORE)
    sim.survey.knowledge_progress[water_key] = 0.0
    sim.survey.knowledge_progress[unrelated_key] = sim.survey.targets[unrelated_key].thresholds[-1]
    development_failures = sim.projects.surface_cell_development_failures(
        ids.EARTH, earth_cell, sim.day
    )
    assert any(
        failure.code == "knowledge" and str(ids.WATER) in failure.detail
        for failure in development_failures
    )

    lunar_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    recipe = sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    water_target = sim.survey.targets[(lunar_cell, ids.WATER)]
    sim.survey.knowledge_progress[(lunar_cell, ids.WATER)] = water_target.thresholds[-1]
    sim.survey.knowledge_progress[(lunar_cell, ids.REGOLITH)] = 0.0
    founding_failures = sim.founding.planning_failures(
        ids.LUNAR_ORBIT,
        _surface_target(sim, ids.MOON, lunar_cell),
        recipe.id,
        ids.REUSABLE_SURFACE_CARGO_LANDER,
        sim.day,
    )
    assert any(
        failure.code == "knowledge_requirement" and str(ids.REGOLITH) in failure.detail
        for failure in founding_failures
    )
    with pytest.raises(ApplicationError, match="knowledge_requirement"):
        app.execute(_found_command("Farside", lunar_cell))

    _survey_cell_to_l2(sim, lunar_cell)
    _stage_founding_resources(sim)
    result = app.execute(_found_command("Farside", lunar_cell))
    assert result.created_id is not None
    project = next(
        row for row in sim.founding.projects.values()
        if str(row.id) == result.created_id
    )
    target_id = sim.founding.target_operational_node_id(project.target_spec)
    assert target_id not in sim.graph.locations
    assert not sim.graph.has_operational_node(target_id)
    assert all(location_id != target_id for location_id, _resource in sim.inventory.stock)
    assert not sim.transport.movement_plan_candidates(ids.LUNAR_ORBIT, target_id)


def test_non_surface_operational_node_founding_uses_common_lifecycle_without_early_node_creation():
    app = build_game_application()
    sim = app._simulation
    target_id = SpatialNodeId("test.node.non_surface_founding")
    sim.graph.add(SpatialNodeDef(
        target_id,
        "Test orbital founding target",
        ids.SOL_SYSTEM,
        CharacteristicTransportGeometry((12000.0, 0.0, 0.0), (0.2, 0.0, 0.0)),
        body_id=ids.EARTH_BODY,
        kind=SpatialNodeKind.ORBITAL,
        inherits_parent_environment=False,
    ))
    recipe_id = DefinitionId("test.deployment_recipe.non_surface")
    sim.founding.deployment_recipes[recipe_id] = DeploymentRecipe(
        recipe_id, "Test orbital deployment", (), 0.0, "construction"
    )
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 2.0)
    sim.transport.add_fleet_units(ids.REUSABLE_ORBITAL_CARGO_TUG, 1, ids.LEO, day=sim.day)

    result = app.execute(PlanOperationalNodeFounding(
        staging_node_id=str(ids.LEO),
        display_name="Test orbital outpost",
        target_spec=NonSurfaceOperationalNodeFoundingTarget(
            "non_surface_operational_node", str(target_id)
        ),
        deployment_recipe_id=str(recipe_id),
        vehicle_definition_id=str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    ))
    assert result.created_id is not None
    project = next(
        row for row in sim.founding.projects.values() if str(row.id) == result.created_id
    )
    assert target_id in sim.graph.nodes
    assert not sim.graph.has_operational_node(target_id)
    assert target_id not in sim.graph.locations

    with pytest.raises(ApplicationError, match="target_claimed"):
        app.execute(PlanOperationalNodeFounding(
            staging_node_id=str(ids.LEO),
            display_name="Duplicate orbital outpost",
            target_spec=NonSurfaceOperationalNodeFoundingTarget(
                "non_surface_operational_node", str(target_id)
            ),
            deployment_recipe_id=str(recipe_id),
            vehicle_definition_id=str(ids.REUSABLE_ORBITAL_CARGO_TUG),
        ))
    assert len([p for p in sim.founding.projects.values() if p.status.value == "preparing"]) == 1

    app.execute(AdvanceTime(1))
    assert project.status.value == "complete"
    assert sim.graph.has_operational_node(target_id)
    assert target_id not in sim.graph.locations

    row = next(
        item for item in app.query(GetProjects(str(ids.LEO))).items
        if item.id == result.created_id
    )
    assert row.founding_target_type == "non_surface_operational_node"
    assert row.deployment_phase == "complete"



def test_founding_transport_path_and_site_requirements_follow_staging_and_target_contexts():
    app = build_game_application()
    sim = app._simulation
    recipe = sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)

    same_body = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, _surface_target(sim, ids.MOON, cell), recipe.id,
        ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    assert not any(row.code.startswith("deployment_vehicle") and "deployment_path:" in row.detail for row in same_body)
    assert not any(row.code.startswith("staging:") for row in same_body)
    assert not any(row.code.startswith("target:") for row in same_body)

    cross_body = sim.founding.planning_failures(
        ids.LEO, _surface_target(sim, ids.MOON, cell), recipe.id,
        ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    # Movement capability determines whether the cross-body deployment is
    # physically possible. Finite preparation service is not an Eligibility gate;
    # it is allocated after the project exists.
    assert not any(row.code == "deployment_vehicle" for row in cross_body)
    assert not any(row.code == "staging_service" for row in cross_body)

    earth_target = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, _surface_target(sim, ids.EARTH_BODY, ids.EARTH_CELL_COASTAL), recipe.id,
        ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day
    )
    assert any(row.code == "target:environment:low_pressure" for row in earth_target)






class _ExternalSurfaceCellClaimProvider:
    def __init__(self, cell_id):
        self.cell_id = cell_id

    def surface_cell_claims(self):
        return (
            SurfaceCellClaim(
                self.cell_id,
                "external_operation",
                EntityId("external.operation.1"),
                "test_exclusive_operation",
            ),
        )


def test_surface_cell_claim_registry_enforces_exclusivity_across_builtin_and_extension_owners():
    app = build_game_application()
    sim = app._simulation
    cell = ids.EARTH_CELL_COASTAL
    registry = sim.projects.surface_cell_claim_registry
    assert registry is sim.founding.surface_cell_claim_registry

    development_id = app.execute(DevelopSurfaceCell(
        str(ids.EARTH), str(cell), procurement_policy="immediate"
    )).created_id
    assert development_id is not None
    recipe = sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    builtin_failures = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, _surface_target(sim, ids.EARTH_BODY, cell),
        recipe.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day,
    )
    assert any(row.code == "cell_claimed" for row in builtin_failures)

    # Remove the built-in project claim so the same registry can prove that a
    # new owner integrates without pairwise Project/Founding wiring.
    app.execute(CancelBuild(development_id))
    registry.register(_ExternalSurfaceCellClaimProvider(cell))

    development_failures = sim.projects.surface_cell_development_failures(
        ids.EARTH, cell, sim.day
    )
    assert any(
        row.code == "cell_claimed" and row.detail == "external.operation.1"
        for row in development_failures
    )

    recipe = sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
    founding_failures = sim.founding.planning_failures(
        ids.LUNAR_ORBIT, _surface_target(sim, ids.EARTH_BODY, cell),
        recipe.id, ids.REUSABLE_SURFACE_CARGO_LANDER, sim.day,
    )
    assert any(
        row.code == "cell_claimed" and row.detail == "external.operation.1"
        for row in founding_failures
    )

def test_partial_founding_procurement_becomes_durable_staged_payload_and_cancel_restores_it():
    app = build_game_application()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    available = sim.inventory.available(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT)
    if available > 1e-12:
        sim.inventory.consume_allocated(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT, available)
    partial = 0.25
    sim.inventory.add(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT, partial)

    project_id = app.execute(_found_command("Partial Procurement", cell)).created_id
    assert project_id is not None
    planned = next(
        row for row in app.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if row.id == project_id
    )
    assert any(
        code in {"import_source", "import_transport_blocked"}
        for code, _detail in planned.blockers
    )
    assert any(code == "resource_shortage" for code, _detail in planned.blockers)

    app.execute(AdvanceTime(1))
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    staged = sim.founding.staged_payload_t(project.id, ids.CONSTRUCTION_EQUIPMENT)
    assert staged == pytest.approx(partial)
    assert not project.inputs_consumed

    project_row = next(
        row for row in app.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if row.id == project_id
    )
    resource_row = next(
        row for row in project_row.resources
        if row.resource_id == str(ids.CONSTRUCTION_EQUIPMENT)
    )
    requirement = next(
        row for row in sim.founding.project_resource_requirements(project.id)
        if row.resource_id == ids.CONSTRUCTION_EQUIPMENT
    )
    assert resource_row.committed_t == pytest.approx(partial)
    assert resource_row.shortage_t == pytest.approx(requirement.amount_t - partial)

    app.execute(AdvanceTime(1))
    assert sim.founding.staged_payload_t(project.id, ids.CONSTRUCTION_EQUIPMENT) == pytest.approx(staged)
    stock_before_cancel = sim.inventory.amount(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT)
    app.execute(CancelFounding(project_id))
    assert sim.inventory.amount(ids.LUNAR_ORBIT, ids.CONSTRUCTION_EQUIPMENT) == pytest.approx(
        stock_before_cancel + staged
    )

def test_founding_target_preflight_uses_facility_site_and_powered_inventory_contracts_atomically():
    app = build_game_application()
    sim = app._simulation

    def orbital_target(name: str, offset: float) -> SpatialNodeId:
        target_id = SpatialNodeId(name)
        sim.graph.add(SpatialNodeDef(
            target_id, name, ids.SOL_SYSTEM,
            CharacteristicTransportGeometry((9000.0 + offset, 0.0, 0.0), (0.1, 0.0, 0.0)),
            body_id=ids.EARTH_BODY, kind=SpatialNodeKind.ORBITAL, inherits_parent_environment=False,
        ))
        return target_id

    bad_site_facility = DefinitionId("test.facility.founding_bad_site")
    sim.facilities.definitions[bad_site_facility] = FacilityDef(
        bad_site_facility, "Bad-site founding fixture",
        installation_requirements=req.SURFACE_SITE, operating_requirements=req.SURFACE_SITE,
    )
    bad_site_recipe = DefinitionId("test.deployment_recipe.bad_site")
    sim.founding.deployment_recipes[bad_site_recipe] = DeploymentRecipe(
        bad_site_recipe, "Bad-site deployment",
        (FoundingFacilityDeployment(bad_site_facility),), 0.0, "construction",
    )
    bad_site_target = orbital_target("test.node.founding_bad_site", 0.0)
    failures = sim.founding.planning_failures(
        ids.LEO,
        NonSurfaceOperationalNodeTargetSpec(bad_site_target),
        bad_site_recipe, ids.REUSABLE_ORBITAL_CARGO_TUG, sim.day,
    )
    assert any(row.code == "facility_installation" for row in failures)
    assert not sim.graph.has_operational_node(bad_site_target)

    storage_facility = DefinitionId("test.facility.founding_powered_storage")
    sim.facilities.definitions[storage_facility] = FacilityDef(
        storage_facility, "Powered founding storage fixture",
        installation_requirements=req.ORBIT_SITE, operating_requirements=req.ORBIT_SITE,
    )
    sim.storage.providers[storage_facility] = StorageProviderSpec(
        storage_facility, {"cryogenic": 10.0}, frozenset(("cryogenic",))
    )
    sim.power.specs[storage_facility] = PowerSpec(load_mw=1.0)
    storage_recipe = DefinitionId("test.deployment_recipe.powered_storage")
    sim.founding.deployment_recipes[storage_recipe] = DeploymentRecipe(
        storage_recipe, "Powered-storage deployment",
        (FoundingFacilityDeployment(storage_facility),), 0.0, "construction",
        initial_inventory=(FoundingResourceRequirement(ids.PROPELLANT, 1.0),),
    )
    blocked_target = orbital_target("test.node.founding_unpowered_storage", 100.0)
    blocked_failures = sim.founding.planning_failures(
        ids.LEO,
        NonSurfaceOperationalNodeTargetSpec(blocked_target),
        storage_recipe, ids.REUSABLE_ORBITAL_CARGO_TUG, sim.day,
    )
    assert any(row.code == "initial_inventory_admission" for row in blocked_failures)
    assert not sim.graph.has_operational_node(blocked_target)

    # A valid plan can still lose eligibility while in transit. Arrival must fail
    # before any target-side State is materialized.
    sim.power.specs[storage_facility] = PowerSpec(FixedGeneration(2.0), load_mw=1.0)
    target_id = orbital_target("test.node.founding_atomic_preflight", 991000.0)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 5.0)
    project_id = app.execute(PlanOperationalNodeFounding(
        staging_node_id=str(ids.LEO),
        display_name="Atomic preflight outpost",
        target_spec=NonSurfaceOperationalNodeFoundingTarget(
            "non_surface_operational_node", str(target_id)
        ),
        deployment_recipe_id=str(storage_recipe),
        vehicle_definition_id=str(ids.REUSABLE_ORBITAL_CARGO_TUG),
    )).created_id
    project = next(row for row in sim.founding.projects.values() if str(row.id) == project_id)
    execution = _advance_founding_to_deployment(app, project)
    sim.power.specs[storage_facility] = PowerSpec(load_mw=1.0)
    remaining = execution.completion_day - sim.day
    assert remaining > 0
    with pytest.raises(ApplicationError, match="founding settlement preflight failed"):
        app.execute(AdvanceTime(remaining))
    assert not sim.graph.has_operational_node(target_id)
    assert not sim.facilities.all_at(target_id)
    assert sim.inventory.amount(target_id, ids.PROPELLANT) == pytest.approx(0.0)


def test_surface_map_exposes_founding_recipe_vehicle_and_blockers():
    app = build_game_application()
    cell_id = ids.MOON_CELL_FARSIDE_HIGHLANDS
    cell = next(row for row in app.query(GetSurfaceMap(str(ids.MOON))).cells if row.id == str(cell_id))
    option = next(
        row for row in cell.foundation_options
        if row.staging_node_id == str(ids.LUNAR_ORBIT)
        and row.deployment_recipe_id == str(ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE)
        and row.vehicle_definition_id == str(ids.REUSABLE_SURFACE_CARGO_LANDER)
    )
    assert option.payload_t > 0
    assert 0 < option.payload_t_per_unit <= option.payload_t
    assert option.required_units > 0
    displayed_resources = dict(option.resources)
    expected_resources = {
        str(row.resource_id): row.amount_t
        for row in app._simulation.founding.resource_requirements_for(
            ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE,
            ids.REUSABLE_SURFACE_CARGO_LANDER,
                ids.LUNAR_ORBIT,
                _surface_target(app._simulation, ids.MOON, cell_id),
        )
    }
    assert displayed_resources == expected_resources
    assert str(ids.PROPELLANT) in displayed_resources
    assert any(code == "knowledge_requirement" for code, _detail in option.blockers)


def test_founding_persistence_preserves_payload_ownership_and_materializes_location_once(tmp_path):
    recipe_id = DefinitionId("test.founding.persisted_payload")

    def factory(*, for_load: bool = False):
        current = build_game_application_for_load() if for_load else build_game_application()
        current_sim = current._simulation
        base = current_sim.founding.deployment_recipes[ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE]
        first_deployment = base.deployed_facilities[0]
        duplicated_investment = replace(
            first_deployment,
            invested_resources=(
                FoundingResourceRequirement(ids.STRUCTURAL_COMPONENTS, 0.4),
                FoundingResourceRequirement(ids.STRUCTURAL_COMPONENTS, 1.0),
                *tuple(
                    row for row in first_deployment.invested_resources
                    if row.resource_id != ids.STRUCTURAL_COMPONENTS
                ),
            ),
        )
        current_sim.founding.deployment_recipes[recipe_id] = replace(
            base,
            id=recipe_id,
            deployed_facilities=(duplicated_investment, *base.deployed_facilities[1:]),
            initial_inventory=(
                FoundingResourceRequirement(ids.STRUCTURAL_COMPONENTS, 0.4),
            ),
            required_units=2,
        )
        return current

    app = factory()
    sim = app._simulation
    cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    _survey_cell_to_l2(sim, cell)
    recipe = sim.founding.deployment_recipes[recipe_id]
    sim.transport.add_fleet_units(
        ids.REUSABLE_SURFACE_CARGO_LANDER, 1, ids.LUNAR_ORBIT, day=sim.day
    )
    expected_payload: dict[DefinitionId, float] = {}
    for deployment in recipe.deployed_facilities:
        for requirement in deployment.invested_resources:
            expected_payload[requirement.resource_id] = (
                expected_payload.get(requirement.resource_id, 0.0) + requirement.amount_t
            )
    for requirement in recipe.initial_inventory:
        expected_payload[requirement.resource_id] = (
            expected_payload.get(requirement.resource_id, 0.0) + requirement.amount_t
        )
    for resource_id, amount_t in expected_payload.items():
        sim.inventory.add(ids.LUNAR_ORBIT, resource_id, amount_t + 1.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 10.0)

    project_id = app.execute(PlanOperationalNodeFounding(
        staging_node_id=str(ids.LUNAR_ORBIT),
        display_name="Persisted Deployment",
        target_spec=SurfaceLocationFoundingTarget("surface_location", str(ids.MOON), str(cell)),
        deployment_recipe_id=str(recipe_id),
        vehicle_definition_id=str(ids.REUSABLE_SURFACE_CARGO_LANDER),
    )).created_id
    assert project_id is not None

    project = next(p for p in sim.founding.projects.values() if str(p.id) == project_id)
    preparing_path = tmp_path / "preparing-founding.json"
    save_game(app, preparing_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(preparing_path, lambda: factory(for_load=True))
    loaded_sim = loaded._simulation
    loaded_project = loaded_sim.founding.projects[project.id]
    assert loaded_project == project

    execution = _advance_founding_to_deployment(loaded, loaded_project)
    assert {
        row.resource_id: row.amount_t for row in execution.payload_resources
    } == pytest.approx(expected_payload)
    assert sum(row.amount_t for row in execution.payload_resources) == pytest.approx(
        sum(expected_payload.values())
    )
    for row in recipe.payload_resources:
        assert loaded_sim.founding.staged_payload_t(loaded_project.id, row.resource_id) == pytest.approx(0.0)
    project_row = next(
        row for row in loaded.query(GetProjects(str(ids.LUNAR_ORBIT))).items
        if row.id == project_id
    )
    assert project_row.resources
    assert all(row.shortage_t == pytest.approx(0.0) for row in project_row.resources)
    assert all(row.committed_t == pytest.approx(row.required_t) for row in project_row.resources)

    deploying_path = tmp_path / "deploying-founding.json"
    save_game(loaded, deploying_path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reloaded, _ = load_game(deploying_path, lambda: factory(for_load=True))
    reloaded_sim = reloaded._simulation
    reloaded_project = reloaded_sim.founding.projects[project.id]
    assert reloaded_project.status.value == "deploying"
    assert reloaded_sim.founding.target_operational_node_id(reloaded_project.target_spec) not in reloaded_sim.graph.locations
    assert reloaded_project.movement_execution_id is not None
    loaded_execution = reloaded_sim.transport.movement_executions[
        reloaded_project.movement_execution_id
    ]
    assert {
        row.resource_id: row.amount_t for row in loaded_execution.payload_resources
    } == expected_payload

    assert reloaded_sim.inventory.amount(
        reloaded_sim.founding.target_operational_node_id(reloaded_project.target_spec), ids.STRUCTURAL_COMPONENTS
    ) == pytest.approx(0.0)

    _advance_founding_to_completion(reloaded, reloaded_project)
    assert reloaded_project.movement_execution_id is None
    location_id = reloaded_sim.founding.target_operational_node_id(reloaded_project.target_spec)
    assert location_id in reloaded_sim.graph.locations
    assert reloaded_sim.inventory.amount(
        location_id, ids.STRUCTURAL_COMPONENTS
    ) == pytest.approx(0.4)
    facilities = reloaded_sim.facilities.all_at(location_id)
    assert len(facilities) == len(recipe.deployed_facilities)
    assert {row.definition_id for row in facilities} == {
        row.facility_def_id for row in recipe.deployed_facilities
    }
    for resource_id, expected_t in expected_payload.items():
        invested_t = sum(
            facility.invested_resources.get(resource_id, 0.0)
            for facility in facilities
        )
        initial_inventory_t = reloaded_sim.inventory.amount(location_id, resource_id)
        assert invested_t + initial_inventory_t == pytest.approx(expected_t)
    assert (
        reloaded_sim.transport.fleet_pool(
            ids.REUSABLE_SURFACE_CARGO_LANDER, location_id
        ).total_units
        == recipe.required_units
    )
    assert {
        anchor.cell_id
        for anchor in reloaded_sim.surface_infrastructure.active_access_anchors(
            location_id, reloaded_sim.day
        )
    } == {cell}
    orbit_plans = (
        reloaded_sim.transport.movement_plan_candidates(location_id, ids.LUNAR_ORBIT)
        + reloaded_sim.transport.movement_plan_candidates(ids.LUNAR_ORBIT, location_id)
    )
    assert orbit_plans
    assert all(
        (
            plan.origin.surface_interface_id is not None
            and reloaded_sim.facilities.facilities[plan.origin.surface_interface_id].site_cell_id == cell
        )
        or (
            plan.destination.surface_interface_id is not None
            and reloaded_sim.facilities.facilities[plan.destination.surface_interface_id].site_cell_id == cell
        )
        for plan in orbit_plans
    )
    plan_ids = {plan.id for plan in orbit_plans}

    reloaded.execute(AdvanceTime(1))
    assert reloaded_project.status.value == "complete"
    assert len(reloaded_sim.facilities.all_at(location_id)) == len(recipe.deployed_facilities)
    assert {
        plan.id for plan in (
            reloaded_sim.transport.movement_plan_candidates(location_id, ids.LUNAR_ORBIT)
            + reloaded_sim.transport.movement_plan_candidates(ids.LUNAR_ORBIT, location_id)
        )
    } == plan_ids
