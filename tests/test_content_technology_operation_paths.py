"""Research unlocks real alternative operations on shared physical equipment."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from space_idle import (
    AdvanceTime, ApplicationError, GetOperationalNode, GetResearch, SetFacilityProcess,
)
from space_idle.bootstrap import (
    build_game_application_for_load, build_game_application_for_scenario,
)
from space_idle.content import base_ids as ids
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.scenario import ScenarioFacility, ScenarioInventoryStock


def _refinery_game():
    base = build_standard_scenario_definition()
    scenario = replace(base,
        facilities=base.facilities + (ScenarioFacility(
            ids.METALLURGY, ids.EARTH,
            invested_resources=((ids.STRUCTURAL_COMPONENTS, 12.0), (ids.MACHINERY, 8.0)),
        ),),
        inventory_stock=base.inventory_stock + (
            ScenarioInventoryStock(ids.EARTH, ids.METAL_FEEDSTOCK, 35.0),
            ScenarioInventoryStock(ids.EARTH, ids.MINERAL_FEEDSTOCK, 35.0),
        ),
    )
    return build_game_application_for_scenario(scenario)


def _refinery_row(app):
    return next(row for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
                if row.facility_definition_id == str(ids.METALLURGY))


def test_research_outlet_eligibility_and_real_alternative_resource_flow_roundtrip(tmp_path):
    app = _refinery_game()
    sim = app._simulation
    row = _refinery_row(app)
    options = {option.process_id: option for option in row.process_options}
    alternatives = {
        ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY: ids.RP_RESOURCE_CHAIN_14,
        ids.PROCESS_METALLURGY_VARIABLE_FEED: ids.RP_RESOURCE_CHAIN_15,
    }
    assert row.selection_required
    assert set(str(key) for key in alternatives) <= set(options)
    assert options[str(ids.PROCESS_METALLURGY)].can_select
    for method_id, technology_id in alternatives.items():
        option = options[str(method_id)]
        assert not option.can_select
        assert any(blocker.kind == 'technology' and blocker.subject_id == str(technology_id)
                   for blocker in option.blockers)
        with pytest.raises(ApplicationError, match='technology'):
            app.execute(SetFacilityProcess(row.facility_id, str(method_id)))
    unlocks = { (unlock.kind, unlock.id) for item in app.query(GetResearch()).items
                for unlock in item.unlocks }
    assert {('process', str(method)) for method in alternatives} <= unlocks

    # The same physical plant provides all three method choices. Research alone
    # changes eligibility, not selected Process or installed Equipment.
    app.execute(SetFacilityProcess(row.facility_id, str(ids.PROCESS_METALLURGY)))
    sim.technology.completed.update(alternatives.values())
    assert _refinery_row(app).process_id == str(ids.PROCESS_METALLURGY)
    method_id = ids.PROCESS_METALLURGY_BYPRODUCT_RECOVERY
    assert next(option for option in _refinery_row(app).process_options
                if option.process_id == str(method_id)).can_select
    app.execute(SetFacilityProcess(row.facility_id, str(method_id)))
    assert _refinery_row(app).process_id == str(method_id)
    resource_ids = (ids.METAL_FEEDSTOCK, ids.MINERAL_FEEDSTOCK, ids.WATER,
                    ids.BULK_STRUCTURE, ids.OXYGEN)
    before = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    app.execute(AdvanceTime(1))
    after = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    assert after[ids.METAL_FEEDSTOCK] < before[ids.METAL_FEEDSTOCK]
    assert after[ids.BULK_STRUCTURE] > before[ids.BULK_STRUCTURE]
    assert after[ids.OXYGEN] > before[ids.OXYGEN]

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    path = tmp_path / 'refinery.json'
    save_game(app, path, saved_at=now)
    loaded, offline = load_game(path, build_game_application_for_load, now=now)
    assert offline is None
    assert capture_state(loaded._simulation) == capture_state(sim)
    loaded.execute(SetFacilityProcess(row.facility_id, str(ids.PROCESS_METALLURGY_VARIABLE_FEED)))
    # Alternative method requires both physically available feedstocks, not
    # an invented substitution of Resource identity in generic Core.
    another = {rid: loaded._simulation.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    loaded.execute(AdvanceTime(1))
    app.execute(AdvanceTime(1))
    final = {rid: loaded._simulation.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    unchanged_method = {rid: sim.inventory.amount(ids.EARTH, rid) for rid in resource_ids}
    # The two instances have identical physical State before this tick; net
    # stock alone is not a reliable process measure when Extraction also adds
    # feedstock. Compare the alternative to the unchanged-process counterfactual.
    assert final[ids.MINERAL_FEEDSTOCK] < unchanged_method[ids.MINERAL_FEEDSTOCK]
    assert final[ids.METAL_FEEDSTOCK] > unchanged_method[ids.METAL_FEEDSTOCK]
    assert final[ids.BULK_STRUCTURE] < unchanged_method[ids.BULK_STRUCTURE]
    assert _refinery_row(loaded).process_id == str(ids.PROCESS_METALLURGY_VARIABLE_FEED)
