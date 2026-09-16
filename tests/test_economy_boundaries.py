from __future__ import annotations

from space_idle import (
    AdvanceTime, CreateExternalServicePolicy, GetWorld,
    build_game_application,
)
from space_idle.content.base_game import (
    EARTH,
    LEO,
    REUSABLE_LAUNCH_VEHICLE,
    WATER,
    EARTH_LEO_LAUNCH_SERVICE,
)


from space_idle.supply import SupplyRequirement
from space_idle.shared import EntityId
from tests._logistics_support import resolve_authorized_logistics

def test_time_progression_has_no_automatic_income():
    app = build_game_application()
    before = app.query(GetWorld())

    app.execute(AdvanceTime(1))
    after = app.query(GetWorld())

    assert after.funds_musd == before.funds_musd


def test_owned_transport_is_physical_while_external_transport_requires_policy_and_funds():
    def demand():
        return SupplyRequirement(
            EntityId("requirement.economy"), "test", EntityId("owner.economy"),
            LEO, WATER, 1.0, 5, EARTH,
        )

    def execute(sim):
        raw = sim.logistics.plan_capacity_logistics(sim.day, (demand(),))
        funds = sim.external_economy.allocate(raw.spending_requests, sim.day)
        plan = sim.logistics.authorize_capacity_logistics(raw, funds, sim.day)
        _shared, execution, _resources, _services = resolve_authorized_logistics(
            sim, sim.day, plan
        )
        sim.logistics.advance_capacity_logistics(
            sim.day, plan, funds, execution,
        )

    owned = build_game_application()
    owned_sim = owned._simulation
    owned_sim.transport.external_services.clear()
    owned_sim.transport.create_transport_allocation(
        REUSABLE_LAUNCH_VEHICLE, EARTH, LEO, target_units=1, day=owned_sim.day
    )
    owned_sim.inventory.add(EARTH, WATER, 1.0)
    owned_before = owned.query(GetWorld()).funds_musd
    execute(owned_sim)
    assert owned.query(GetWorld()).funds_musd == owned_before
    assert owned_sim.logistics.cargo_flows

    commercial = build_game_application()
    commercial_sim = commercial._simulation
    commercial_sim.transport.transport_allocations.clear()
    commercial_sim.inventory.add(EARTH, WATER, 2.0)
    commercial_before = commercial.query(GetWorld()).funds_musd

    execute(commercial_sim)
    assert commercial.query(GetWorld()).funds_musd == commercial_before
    assert not commercial_sim.logistics.cargo_flows

    commercial.execute(CreateExternalServicePolicy(
        enabled=True,
        allowed_service_ids=(str(EARTH_LEO_LAUNCH_SERVICE),),
    ))
    execute(commercial_sim)
    assert commercial.query(GetWorld()).funds_musd < commercial_before
    assert commercial_sim.logistics.cargo_flows


def test_extraction_stops_when_output_storage_service_is_full():
    app = build_game_application()
    sim = app._simulation
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[EARTH]
    execution = decision.allocations.execution
    initial = next(
        row
        for row in sim.extraction.snapshots(
            EARTH, sim.facilities, sim.inventory, power, sim.day, execution
        )
        if row.output_t_per_day > 0
    )
    spec = sim.extraction.specs[initial.facility_def_id]
    free = sim.inventory.free_capacity(EARTH, spec.output_resource_id)
    assert free is not None and free > 0

    sim.inventory.add(EARTH, spec.output_resource_id, free)
    before = sim.inventory.amount(EARTH, spec.output_resource_id)
    decision = sim.tick_decision_projection()
    power = decision.allocations.power_by_location[EARTH]
    execution = decision.allocations.execution
    blocked = next(
        row
        for row in sim.extraction.snapshots(
            EARTH, sim.facilities, sim.inventory, power, sim.day, execution
        )
        if row.facility_id == initial.facility_id
    )
    assert blocked.output_t_per_day == 0.0
    assert any(reason.startswith("storage:") for reason in blocked.limiting_factors)

    sim.extraction.advance_day(
        EARTH, sim.facilities, sim.inventory, power, sim.day, execution
    )
    assert sim.inventory.amount(EARTH, spec.output_resource_id) == before
