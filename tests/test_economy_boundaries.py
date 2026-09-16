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
    CONSTRUCTION_EQUIPMENT,
    EARTH_LEO_LAUNCH_SERVICE,
)



def test_time_progression_has_no_automatic_income():
    app = build_game_application()
    before = app.query(GetWorld())

    app.execute(AdvanceTime(1))
    after = app.query(GetWorld())

    assert after.funds_musd == before.funds_musd


def test_owned_transport_is_physical_while_external_transport_requires_policy_and_funds():
    def configure_target(app, *, owned: bool):
        sim = app._simulation
        sim.inventory.stock[(LEO, CONSTRUCTION_EQUIPMENT)] = 0.0
        sim.inventory.add(EARTH, CONSTRUCTION_EQUIPMENT, 2.0)
        sim.logistics.set_supply_policy(
            LEO, CONSTRUCTION_EQUIPMENT, preferred_source_id=EARTH
        )
        target_id = sim.logistics.set_target_stock(
            LEO, CONSTRUCTION_EQUIPMENT, 1.0, 5
        )
        if owned:
            sim.transport.external_services.clear()
            sim.transport.create_transport_allocation(
                REUSABLE_LAUNCH_VEHICLE,
                EARTH,
                LEO,
                target_units=1,
                day=sim.day,
            )
        else:
            sim.transport.transport_allocations.clear()
        return sim, target_id

    owned = build_game_application()
    owned_sim, owned_target = configure_target(owned, owned=True)
    owned_before = owned.query(GetWorld()).funds_musd
    owned_sim.advance_days(1)
    assert owned.query(GetWorld()).funds_musd == owned_before
    assert any(
        row.owner_id == owned_target
        for row in owned_sim.logistics.cargo_flows.values()
    )

    commercial = build_game_application()
    commercial_sim, commercial_target = configure_target(commercial, owned=False)
    commercial_before = commercial.query(GetWorld()).funds_musd

    commercial_sim.advance_days(1)
    assert commercial.query(GetWorld()).funds_musd == commercial_before
    assert not [
        row for row in commercial_sim.logistics.cargo_flows.values()
        if row.owner_id == commercial_target
    ]

    commercial.execute(CreateExternalServicePolicy(
        enabled=True,
        allowed_service_ids=(str(EARTH_LEO_LAUNCH_SERVICE),),
    ))
    assert any(
        row.requirement.owner_id == commercial_target and amount > 0.0
        for row, amount in commercial_sim.tick_decision_projection().allocations.transport.executable_dispatches
    )
    commercial_sim.advance_days(1)
    assert commercial.query(GetWorld()).funds_musd < commercial_before
    assert any(
        row.owner_id == commercial_target
        for row in commercial_sim.logistics.cargo_flows.values()
    )

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
