"""Physical implementation contracts for research-driven industrial concepts.

These tests enforce ownership and finite flows, not one preferred game build or
any particular stage-wide throughput balance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from space_idle import AdvanceTime, SetFacilityProcess, GetOperationalNode, GetLogistics, ProduceVehicle
from space_idle.bootstrap import build_game_application, build_game_application_for_load
from space_idle.content.base_concept_assets import build_concept_facility_assets
from space_idle.content.base_concept_industry import build_concept_process_specs
from space_idle.content import base_ids as ids
from space_idle.persistence import capture_state, load_game, save_game
from space_idle.shared import DefinitionId


def test_concept_assets_use_physical_construction_and_power_without_generic_unlock_bonuses():
    sim = build_game_application()._simulation
    assets = build_concept_facility_assets()
    process_defs = build_concept_process_specs()
    technologies = sim.research.definitions
    resources = sim.inventory.resource_definitions
    assert len({row.definition.id for row in assets}) == len(assets)
    assert len(process_defs) == len(set(process_defs))
    capabilities = {
        capability.id for facility in sim.facilities.definitions.values()
        for capability in facility.capability_supplies
    }
    for asset in assets:
        identity = asset.definition.id
        assert sim.facilities.definitions[identity].capability_supplies == asset.definition.capability_supplies
        assert sim.facilities.definitions[identity].installation_requirements == asset.definition.installation_requirements
        assert sim.projects.recipes[identity] == asset.construction
        assert sim.power.specs[identity] == asset.power
        assert asset.construction.resources
        assert len(asset.construction.resources) <= 3
        assert all(req.amount_t > 0 and req.resource_id in resources for req in asset.construction.resources)
        assert asset.construction.prerequisite_technologies <= technologies.keys()
        assert asset.definition.maintenance_fraction_per_year > 0
        assert asset.power.load_mw > 0
    for definition in process_defs.values():
        assert sim.industry.processes[definition.id] == definition
        assert len(definition.inputs_per_day) <= 3
        assert definition.required_capabilities <= capabilities
        assert definition.prerequisite_technologies <= technologies.keys()
        assert set(definition.inputs_per_day) | set(definition.outputs_per_day) <= resources.keys()
        assert all(rate > 0 for rate in definition.inputs_per_day.values())
        assert all(rate > 0 for rate in definition.outputs_per_day.values())
        assert sum(definition.outputs_per_day.values()) <= sum(definition.inputs_per_day.values()) + 1e-9
    # Neither Fusion studies nor the isotope separator mint Power from Fuel.
    assert ids.FUSION_FUEL_ISOTOPES in resources
    assert ids.HELIUM4_COOLANT in resources
    assert not any(asset.definition.id == DefinitionId('planned.facility.fusion_power_station') for asset in assets)


def test_concept_recovery_is_technology_gated_and_physically_consumes_stock(tmp_path):
    app = build_game_application()
    sim = app._simulation
    facility_id = DefinitionId('planned.facility.recovery_microelectronics_fab')
    process_id = DefinitionId('planned.process.laser_film_rework')
    technology = DefinitionId('VR-6-MICROELECTRONICS-01')
    facility = sim.facilities.install(facility_id, ids.EARTH)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, ids.EARTH, level=3)
    sim.inventory.add(ids.EARTH, ids.RECOVERY_SCRAP, 9)
    sim.inventory.add(ids.EARTH, ids.PRECISION_COMPONENTS, 7)
    options = {item.process_id: item for row in app.query(GetOperationalNode(str(ids.EARTH))).industry
        if row.facility_id == str(facility) for item in row.process_options}
    assert str(process_id) in options
    assert not options[str(process_id)].can_select
    sim.technology.completed.add(technology)
    app.execute(SetFacilityProcess(str(facility), str(process_id)))
    before = (sim.inventory.amount(ids.EARTH, ids.RECOVERY_SCRAP),
              sim.inventory.amount(ids.EARTH, ids.PRECISION_ELECTRONICS))
    app.execute(AdvanceTime(1))
    after = (sim.inventory.amount(ids.EARTH, ids.RECOVERY_SCRAP),
             sim.inventory.amount(ids.EARTH, ids.PRECISION_ELECTRONICS))
    assert after[0] < before[0]
    assert after[1] > before[1]
    path = tmp_path / 'concept-rework.json'
    save_game(app, path, saved_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
    loaded, result = load_game(path, build_game_application_for_load)
    assert result is None
    assert capture_state(sim) == capture_state(loaded._simulation)
    app.execute(AdvanceTime(2))
    loaded.execute(AdvanceTime(2))
    assert capture_state(sim) == capture_state(loaded._simulation)


def test_isotope_supply_and_fusion_fleet_acquisition_require_real_resources():
    app = build_game_application()
    sim = app._simulation
    ship_id = DefinitionId('planned.vehicle.fusion_freighter')
    ship = sim.transport.vehicle_defs[ship_id]
    assert ship.performance.propellant_resource_id == ids.FUSION_FUEL_ISOTOPES
    assert ship.production.prerequisite_technologies == {DefinitionId('SF-FUSION-03')}
    assert ship.performance.propellant_capacity_t > 0
    assert ship.performance.propellant_t_per_total_t_per_km_s > 0
    assert ship.retirement.enabled
    assert ship.maintenance.resources
    assert ship.performance.resource_support_requirements[0].resource_id == ids.FUSION_FUEL_ISOTOPES
    unavailable = next(row for row in app.query(GetLogistics()).vehicle_production_options
                       if row.vehicle_definition_id == str(ship_id) and row.operational_node_id == str(ids.EARTH))
    assert not unavailable.can_plan
    assert any(blocker.kind == 'technology' for blocker in unavailable.blockers)
    sim.technology.completed.add(DefinitionId('SF-FUSION-03'))
    available = next(row for row in app.query(GetLogistics()).vehicle_production_options
                     if row.vehicle_definition_id == str(ship_id) and row.operational_node_id == str(ids.EARTH))
    assert available.can_plan
    assert app.execute(ProduceVehicle(str(ship_id), str(ids.EARTH))).created_id
    # Production is a project that reserves material, not a free ship unlock.
    assert sim.transport.fleet_free_units(ship_id, ids.EARTH) == 0


def test_helium_and_fusion_isotope_manufacturing_have_finite_feed():
    app = build_game_application()
    sim = app._simulation
    refinery = DefinitionId('planned.facility.integrated_propellant_refinery')
    facility = sim.facilities.install(refinery, ids.EARTH)
    sim.facilities.install(ids.INDUSTRIAL_POWER_BLOCK, ids.EARTH, level=5)
    sim.facilities.install(ids.CRYOGENIC_STORAGE, ids.EARTH)
    sim.technology.completed.add(DefinitionId('VR-7-THERMAL-TRANSPORT-01'))
    sim.inventory.add(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL, 12.)
    process = DefinitionId('planned.process.helium4_volatile_recovery')
    app.execute(SetFacilityProcess(str(facility), str(process)))
    before_feed = sim.inventory.amount(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL)
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(ids.EARTH, ids.VOLATILE_BEARING_MATERIAL) < before_feed
    assert sim.inventory.amount(ids.EARTH, ids.HELIUM4_COOLANT) > 0
    # The isotope feed and product are separate Resources, so Research does
    # not spontaneously fill Vehicle tanks or generate electricity.
    sim.technology.completed.add(DefinitionId('SF-FUSION-04'))
    sim.inventory.add(ids.EARTH, ids.HYDROGEN, 20.)
    app.execute(SetFacilityProcess(str(facility), str(DefinitionId('planned.process.fusion_isotope_separation'))))
    before_hydrogen = sim.inventory.amount(ids.EARTH, ids.HYDROGEN)
    app.execute(AdvanceTime(1))
    assert sim.inventory.amount(ids.EARTH, ids.HYDROGEN) < before_hydrogen
    assert sim.inventory.amount(ids.EARTH, ids.FUSION_FUEL_ISOTOPES) > 0
