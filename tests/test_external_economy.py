from __future__ import annotations

from datetime import datetime, timezone

import pytest

from space_idle import (
    CreateExternalServicePolicy,
    GetExternalEconomy,
    build_game_application,
)
from space_idle.external_economy import ExternalEconomyState, FundsRequest
from space_idle.persistence import load_game, save_game
from space_idle.shared import AccountState, DefinitionId, EntityId
from space_idle.content import base_ids as ids


def _economy(funds: float = 100.0) -> tuple[ExternalEconomyState, DefinitionId, EntityId]:
    service = DefinitionId("test.external.service")
    state = ExternalEconomyState(AccountState(funds))
    state.register_service(service)
    policy_id = state.create_policy(
        enabled=True,
        allowed_service_ids=(service,),
        period_budget_musd=100.0,
        minimum_reserve_musd=0.0,
    )
    return state, service, policy_id


def _request(
    request_id: str,
    policy_id: EntityId,
    service_id: DefinitionId,
    amount: float,
    priority: int,
) -> FundsRequest:
    return FundsRequest(
        EntityId(request_id),
        policy_id,
        service_id,
        amount,
        priority,
        "lane",
        EntityId("lane.test"),
        "transport",
    )



def _transport_service_allocations(sim, day, plan):
    requests = sim.logistics.transport_service_capacity_requests(day, plan.planned_usage)
    locations = sim._active_locations() | set(sim.graph.operational_node_ids())
    powers = {
        location_id: sim.power.snapshot(location_id, sim.facilities, day)
        for location_id in locations
    }
    return sim._allocate_tick_services(powers, requests)

def test_funds_allocation_is_same_priority_registration_order_independent():
    def run(order: tuple[str, ...]):
        state, service, policy = _economy(10.0)
        rows = {
            "a": _request("funds.a", policy, service, 8.0, 50),
            "b": _request("funds.b", policy, service, 12.0, 50),
        }
        plan = state.allocate(tuple(rows[key] for key in order), 0)
        return {str(row.request_id): row.authorized_musd for row in plan.rows}

    assert run(("a", "b")) == pytest.approx(run(("b", "a")))
    result = run(("a", "b"))
    assert result["funds.a"] == pytest.approx(4.0)
    assert result["funds.b"] == pytest.approx(6.0)


def test_higher_priority_authorization_reserves_period_budget_within_tick():
    state, service, policy = _economy(100.0)
    state.policies[policy].period_budget_musd = 10.0
    plan = state.allocate(
        (
            _request("funds.high", policy, service, 8.0, 100),
            _request("funds.low", policy, service, 8.0, 10),
        ),
        0,
    )
    assert plan.authorized(EntityId("funds.high")) == pytest.approx(8.0)
    assert plan.authorized(EntityId("funds.low")) == pytest.approx(2.0)
    assert "period_budget" in plan.authorization(EntityId("funds.low")).limiting_factors


def test_minimum_reserve_and_spending_cap_limit_authorization():
    state, service, policy = _economy(20.0)
    state.policies[policy].minimum_reserve_musd = 7.0
    state.policies[policy].spending_cap_musd = 15.0
    plan = state.allocate((_request("funds.one", policy, service, 30.0, 50),), 0)
    row = plan.authorization(EntityId("funds.one"))
    assert row.authorized_musd == pytest.approx(13.0)
    assert set(row.limiting_factors) == {"funds", "minimum_reserve", "spending_cap"}


def test_application_policy_defaults_to_deny_and_roundtrips_with_funds(tmp_path):
    app = build_game_application()
    sim = app._simulation
    assert app.query(GetExternalEconomy()).policies == ()
    assert not sim.external_economy.service_allowed(
        ids.EARTH_LEO_LAUNCH_SERVICE, "lane", EntityId("lane.any")
    )

    policy_id = app.execute(
        CreateExternalServicePolicy(
            enabled=True,
            allowed_service_ids=(str(ids.EARTH_LEO_LAUNCH_SERVICE),),
            spending_cap_musd=12.0,
            period_budget_musd=40.0,
            minimum_reserve_musd=250.0,
        )
    ).created_id
    assert policy_id is not None
    sim.external_economy.account.funds_musd = 777.0

    path = tmp_path / "external-economy.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    view = loaded.query(GetExternalEconomy())
    assert view.funds_musd == pytest.approx(777.0)
    assert len(view.policies) == 1
    row = view.policies[0]
    assert row.id == policy_id
    assert row.spending_cap_musd == pytest.approx(12.0)
    assert row.period_budget_musd == pytest.approx(40.0)
    assert row.minimum_reserve_musd == pytest.approx(250.0)


def test_duplicate_same_scope_policy_for_same_service_fails_closed():
    state, service, _policy = _economy(100.0)
    with pytest.raises(ValueError, match="ambiguous external service policy"):
        state.create_policy(enabled=True, allowed_service_ids=(service,))


def test_lane_projection_exposes_policy_denial_until_authorized():
    app = build_game_application()
    sim = app._simulation
    sim.logistics.transport_allocations.clear()
    lane_id = sim.logistics.create_lane(ids.EARTH, ids.LEO, 1.0, 50)
    demand = __import__('space_idle.resource_demand', fromlist=['ResourceDemand']).ResourceDemand(
        EntityId("demand.policy-blocker"), "test", EntityId("owner.policy-blocker"),
        ids.LEO, ids.MACHINERY, 1.0, 50, ids.EARTH,
    )
    metric = next(row for row in sim.logistics.lane_snapshot((demand,), sim.day).lanes if row.lane_id == lane_id)
    assert metric.effective_capacity_t_per_day == 0.0
    assert any(value.startswith("external_policy_denied:") for value in metric.blockers)

    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(ids.EARTH_LEO_LAUNCH_SERVICE,),
        day=sim.day,
    )
    metric = next(row for row in sim.logistics.lane_snapshot((demand,), sim.day).lanes if row.lane_id == lane_id)
    assert metric.effective_capacity_t_per_day > 0.0
    assert not any(value.startswith("external_policy_denied:") for value in metric.blockers)


def test_load_rederives_same_external_spending_authorization(tmp_path):
    from space_idle.content.base_game import (
        EARTH, LEO, ORBITAL_LOGISTICS_NODE,
        TECH_CISLUNAR_LOGISTICS, TECH_ORBITAL_OPERATIONS,
    )

    app = build_game_application()
    sim = app._simulation
    sim.technology.completed.update({TECH_ORBITAL_OPERATIONS, TECH_CISLUNAR_LOGISTICS})
    sim.projects.plan_build(
        ORBITAL_LOGISTICS_NODE,
        LEO,
        50,
        "import_now",
        day=sim.day,
        import_source_id=EARTH,
    )
    sim.projects.advance_procurement(sim.day)
    sim.logistics.create_lane(EARTH, LEO, 1.0, 50)
    app.execute(CreateExternalServicePolicy(
        enabled=True,
        allowed_service_ids=(str(ids.EARTH_LEO_LAUNCH_SERVICE),),
        period_budget_musd=20.0,
        minimum_reserve_musd=100.0,
    ))
    before = app.query(GetExternalEconomy()).authorizations
    assert before

    path = tmp_path / "external-auth.json"
    save_game(app, path, saved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    loaded, _ = load_game(path, build_game_application)
    after = loaded.query(GetExternalEconomy()).authorizations
    assert after == before


def test_multiedge_external_transport_spends_only_cost_of_executed_tonnage():
    from space_idle.content.base_game import EARTH, LUNAR_ORBIT, MACHINERY
    from space_idle.resource_claim import allocate_resource_claims
    from space_idle.resource_demand import ResourceDemand

    app = build_game_application()
    sim = app._simulation
    sim.logistics.transport_allocations.clear()
    sim.external_economy.create_policy(
        enabled=True,
        allowed_service_ids=(ids.EARTH_LEO_LAUNCH_SERVICE, ids.LEO_LUNAR_SERVICE),
        spending_cap_musd=0.5,
        day=sim.day,
    )
    lane_id = sim.logistics.create_lane(EARTH, LUNAR_ORBIT, 1.0, 50)
    sim.inventory.add(EARTH, MACHINERY, 1.0)
    demand = ResourceDemand(
        EntityId("demand.multiedge-spend"), "test", EntityId("owner.multiedge-spend"),
        LUNAR_ORBIT, MACHINERY, 1.0, 50, EARTH,
    )
    raw = sim.logistics.plan_capacity_logistics(sim.day, (demand,))
    assert len(raw.spending_requests) == 2
    funds = sim.external_economy.allocate(raw.spending_requests, sim.day)
    plan = sim.logistics.authorize_capacity_logistics(raw, funds, sim.day)
    row = next(item for item in plan.dispatches if item.lane_id == lane_id)
    assert row.amount_t == pytest.approx(0.1)
    resources = allocate_resource_claims(plan.claims, sim.inventory)
    services = _transport_service_allocations(sim, sim.day, plan)
    execution = sim.logistics.allocate_capacity_logistics_execution(
        sim.day, plan, resources, services
    )
    before = sim.external_economy.account.funds_musd
    sim.logistics.advance_capacity_logistics(
            sim.day, plan, funds, execution,
        )
    assert before - sim.external_economy.account.funds_musd == pytest.approx(0.9)
