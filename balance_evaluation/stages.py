"""Stage 1–2 Content balance evaluation scenarios, not pass/fail tests.

Run ``python -m balance_evaluation --stage 1`` or ``--stage 2``.
Selected scales and windows are revisable design inputs, not acceptance
thresholds, constructed locations, player plans, or simulated trajectories.
"""
import argparse
import json
import math

from content_balance.ledger import quantity_ledger
from content_balance.physical import movement_evidence, surface_region_evidence
from space_idle.composition.base_simulation import build_base_simulation
from space_idle.content.base_catalog import build_base_catalog
from space_idle.content.base_scenario import build_standard_scenario_definition
from space_idle.content import base_ids as ids


# Independent, revisable samples of acquisition intensity and operation. They
# are NOT the 4/12-hour cumulative pacing targets or presumed game completion.
EARTH_WINDOW_DAYS = 14_400
CISLUNAR_WINDOW_DAYS = 28_800
EARTH = str(ids.EARTH)
LUNAR_ORBIT = str(ids.LUNAR_ORBIT)
LUNAR_SITES = (ids.MOON_CELL_SOUTH_POLAR_RIDGE, ids.MOON_CELL_NEARSIDE_MARE)


def _setup():
    scenario = build_standard_scenario_definition()
    sim = build_base_simulation(build_base_catalog(),
        population_rules=scenario.population_rules,
        external_population_sources=scenario.external_population_sources)
    return sim, scenario


def _technology_closure(sim, endpoints):
    """Direct prerequisites of a *chosen* set, never all members of a stage."""
    result = set()

    def include(tid):
        if tid not in sim.research.definitions:
            raise ValueError(f'unregistered research in evaluation input: {tid}')
        if tid in result:
            return
        result.add(tid)
        for parent in sim.research.definitions[tid].prerequisites:
            include(parent)

    for tid in endpoints:
        include(tid)
    return result


def _research_inputs(sim, selection, previous=(), *, portfolio="activity"):
    """Charge chosen typed stages and direct ancestors, without gifting unlocks."""
    selected = _technology_closure(sim, selection) - set(previous)
    return [
        {'kind': 'research_stage', 'node': EARTH, 'id': tid,
         'stage_id': stage.stage_id, 'count': 1, 'portfolio': portfolio}
        for tid in sorted(selected, key=str)
        for stage in sim.research.definitions[tid].stage_specs
    ]


def _earth_industry(sim, *, research_lab_count, propellant_process_rate, electrolysis_rate, fuel_plants=1, water_intakes=1):
    """Baseline factories remain operating while new assets are acquired."""
    activities = [
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.GENERAL_RESEARCH_LAB,
         'count': research_lab_count, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'research_fleet_provider', 'node': str(ids.LEO),
         'id': ids.ORBITAL_OBSERVATION_RESEARCH_PROVIDER,
         'vehicle_id': ids.ORBITAL_OBSERVATION_SPACECRAFT, 'units': 1,
         'context_id': ids.LEO},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.GRID_POWER_SUPPLY,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        # Already installed in the standard Scenario: these supply actual
        # construction/assembly/launch capacity and finite orbital handoff.
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.SURFACE_LAUNCH_SUPPORT,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.VEHICLE_ASSEMBLY_FACILITY,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'construction_resource', 'node': EARTH, 'id': ids.CONSTRUCTION_EQUIPMENT,
         'available_stock_t': 60.0},
        {'kind': 'facility_operation', 'node': str(ids.LEO), 'id': ids.AUTONOMOUS_ORBITAL_OUTPOST,
         'count': 1, 'context_id': ids.LEO},
        {'kind': 'facility_operation', 'node': LUNAR_ORBIT, 'id': ids.ORBITAL_LOGISTICS_NODE,
         'count': 1, 'context_id': ids.LUNAR_ORBIT},
        # Acquired from initial finite construction stocks and stage-one
        # research; stage two inherits the same physical assets.
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.ELECTROLYSIS_PLANT,
         'count': fuel_plants, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': 'planned.process.earth_electrolysis_basic'},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.PROPELLANT_PLANT,
         'count': fuel_plants, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': ids.PROCESS_PROPELLANT_BLEND},
        {'kind': 'process', 'node': EARTH, 'id': 'planned.process.earth_electrolysis_basic',
         'rate_per_day': electrolysis_rate},
        {'kind': 'process', 'node': EARTH, 'id': ids.PROCESS_PROPELLANT_BLEND,
         'rate_per_day': propellant_process_rate},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.BASIC_STRUCTURAL_MATERIAL_PLANT,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': ids.PROCESS_BASIC_STRUCTURAL_MATERIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.BASIC_MACHINERY_WORKS,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': ids.PROCESS_BASIC_MACHINERY},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.FOOD_FARM,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': ids.PROCESS_FOOD_PRODUCTION},
        {'kind': 'process', 'node': EARTH, 'id': ids.PROCESS_BASIC_STRUCTURAL_MATERIAL,
         'rate_per_day': 1.0},
        {'kind': 'process', 'node': EARTH, 'id': ids.PROCESS_BASIC_MACHINERY,
         'rate_per_day': 1.0},
        {'kind': 'process', 'node': EARTH, 'id': ids.PROCESS_FOOD_PRODUCTION,
         'rate_per_day': 1.0},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.BREATHABLE_SURFACE_LIFE_SUPPORT,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'life_support', 'node': EARTH, 'id': ids.BREATHABLE_SURFACE_LIFE_SUPPORT,
         'people': 30},
    ]
    # Hypothetical local collection is a separate, physical-input assumption;
    # the ledger shows the geological response, not guaranteed extraction.
    for fid, method in (
        (ids.METAL_ORE_MINE, ids.EXTRACTION_CRUST_ORE),
        (ids.MINERAL_QUARRY, ids.EXTRACTION_CRUST_MINERAL),
        (ids.INDUSTRIAL_WATER_INTAKE, ids.EXTRACTION_WATER_INTAKE),
        ('planned.facility.earth_biomass_feedstock_collector', ids.EXTRACTION_BIOMASS_FEEDSTOCK),
    ):
        context = ids.EARTH_CELL_INDUSTRIAL
        physical = surface_region_evidence(sim, [context], method, fid,
                                           facility_units=water_intakes if fid == ids.INDUSTRIAL_WATER_INTAKE else 1, level=1)
        potential_rate = physical['physical_diminishing_response_t_per_day']
        # Explicit upper-envelope hypothesis, not an actual settled Source.
        units = water_intakes if fid == ids.INDUSTRIAL_WATER_INTAKE else 1
        proposed_rate = min(sim.extraction.nominal_capacity_for_level(fid, 1) * units, potential_rate)
        activities.extend([
            {'kind': 'facility_operation', 'node': EARTH, 'id': fid,
             'count': units, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
             'selected_extraction_method_id': method},
            {'kind': 'extraction', 'node': EARTH, 'id': method, 'facility_id': fid,
             'facility_units': units, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
             'rate_t_per_day': proposed_rate},
        ])
    return activities


def _candidate_leg(sim, origin, destination, vehicle_id, cargo_t):
    evidence = movement_evidence(sim, origin, destination, vehicle_id, cargo_t=cargo_t)
    # A scenario must expose a missing physical leg, rather than invent one.
    if not evidence['forward']:
        raise ValueError(f'no physical leg for {vehicle_id} {origin} -> {destination}')
    return evidence['forward'][0]


def _candidate_cycle(sim, origin, destination, vehicle_id, source_node, destination_node, manifest, units=1):
    resolver = sim.transport.movement_resolver()
    forward = resolver.physical_context_plans(origin, destination)
    reverse = resolver.physical_context_plans(destination, origin)
    if not forward:
        raise ValueError(f'no physical cycle leg: {origin} -> {destination}')
    disposition = sim.transport.vehicle_defs[vehicle_id].movement_asset_disposition(forward[0]).value
    if disposition == 'destination' and not reverse:
        raise ValueError(f'no physical return: {destination} -> {origin}')
    result = {'kind': 'transport_cycle', 'node': source_node,
              'destination_node': destination_node, 'id': vehicle_id,
              'units': units, 'origin_context_id': origin,
              'destination_context_id': destination,
              'forward_plan_id': str(forward[0].id),
              'forward_cargo_t_per_day': manifest}
    if disposition == 'destination':
        result['reverse_plan_id'] = str(reverse[0].id)
    return result


def _stage_one(sim):
    # Chosen equipment technologies and their direct prerequisite closure;
    # other optional scientific branches still compete for finite RP.
    chosen = ('PL-EARTH-PRECISION-PARTS', 'CO-RF-COMMUNICATIONS-01',
              'CR-CRYOGENIC-STORAGE-TRANSFER-02', 'GN-NAVIGATION-01',
              'CH-COMBUSTION-01', 'CH-COMBUSTION-06', 'GN-NAVIGATION-04',
              'EDL-EDL-06')
    acquired = _technology_closure(sim, chosen)
    archive = 'planned.facility.basic_data_archive'
    electronics_plant = 'planned.facility.earth_basic_electronics_shop'
    electronics_process = 'planned.process.earth_basic_electronics'
    founding = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
    activities = _earth_industry(sim, research_lab_count=6,
                                 propellant_process_rate=.25, electrolysis_rate=.25) + [
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.GENERAL_RESEARCH_LAB, 'count': 5},
        {'kind': 'facility_construction', 'node': EARTH, 'id': archive, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': electronics_plant, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.ELECTROLYSIS_PLANT, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.PROPELLANT_PLANT, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.PROPULSION_TEST_FACILITY, 'count': 1},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.PROPULSION_TEST_FACILITY,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': archive,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': electronics_plant,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': electronics_process},
        {'kind': 'process', 'node': EARTH, 'id': electronics_process, 'rate_per_day': .8},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.REUSABLE_LAUNCH_VEHICLE, 'count': 1},
        # Source-side Cargo obligations at Earth and LEO represent the same
        # physical founding manifest through two transfer legs, not gifts.
        _candidate_cycle(sim, ids.EARTH_CELL_INDUSTRIAL, ids.LEO,
                         ids.REUSABLE_LAUNCH_VEHICLE, EARTH, str(ids.LEO),
                         {str(r.resource_id): r.amount_t / EARTH_WINDOW_DAYS
                          for r in founding.payload_resources}),
        _candidate_cycle(sim, ids.LEO, ids.LUNAR_ORBIT,
                         ids.REUSABLE_ORBITAL_CARGO_TUG, str(ids.LEO), LUNAR_ORBIT,
                         {str(r.resource_id): r.amount_t / EARTH_WINDOW_DAYS
                          for r in founding.payload_resources}),
        {'kind': 'founding', 'node': LUNAR_ORBIT, 'id': ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE,
         'target_context_id': LUNAR_SITES[0], 'staging_context_id': ids.LUNAR_ORBIT, 'count': 1},
        {'kind': 'movement', 'node': LUNAR_ORBIT, 'id': ids.REUSABLE_SURFACE_CARGO_LANDER,
         'origin_context_id': ids.LUNAR_ORBIT, 'destination_context_id': LUNAR_SITES[0],
         'movement_plan_id': _candidate_leg(sim, ids.LUNAR_ORBIT, LUNAR_SITES[0],
                         ids.REUSABLE_SURFACE_CARGO_LANDER, founding.payload_t)['movement_plan_id'],
         'cargo_t': founding.payload_t, 'count': 1},
    ] + _research_inputs(sim, chosen)
    return {'stage': 1, 'period_days': EARTH_WINDOW_DAYS, 'cumulative_target_hours': 4,
            'questions': ('Can initial mining, process, electronics and propellant chains sustain parallel research and asset growth?',
                          'Do finite construction/vehicle services and initial stocks support the first lunar founding?',
                          'Does the selected research branch fit RP generation, execution and Pool capacities?'),
            'selected_research': sorted(map(str, acquired)), 'activities': activities}


def _stage_two(sim):
    early_endpoints = ('PL-EARTH-PRECISION-PARTS', 'CO-RF-COMMUNICATIONS-01',
                       'CR-CRYOGENIC-STORAGE-TRANSFER-02', 'GN-NAVIGATION-01',
                       'CH-COMBUSTION-01', 'CH-COMBUSTION-06', 'GN-NAVIGATION-04',
                       'EDL-EDL-06')
    chosen = ('X2-REMOTE-OPERATIONS-LAB', 'X2-DATA-RETENTION',
              'BIO-HUMAN-BIOLOGY-MEDICINE-04', 'SS-SENSING-06',
              'LS-ATMOSPHERE-WATER-WASTE-01', 'PG-SOLAR-POWER-02',
              'LM-LOGISTICS-MAINTENANCE-01', 'GN-NAVIGATION-03',
              'MC-MANUFACTURING-CONSTRUCTION-02', 'RP-RESOURCE-CHAIN-01')
    # A separate, revisable concurrent science portfolio represents the RP
    # opportunity cost of continuing autonomy, habitat, sensing, logistics,
    # industrial-material and propulsion work while the featured physical
    # expansion occurs. This is neither a requirement to complete the display
    # stage nor a preferred research order.
    concurrent = (
        'AR-AUTONOMY-ROBOTICS-04', 'LS-ATMOSPHERE-WATER-WASTE-05',
        'HB-HABITATION-PROTECTION-04', 'CO-RF-COMMUNICATIONS-04',
        'LM-LOGISTICS-MAINTENANCE-05', 'MC-MANUFACTURING-CONSTRUCTION-03',
        'RP-RESOURCE-CHAIN-03', 'SM-SURFACE-MOBILITY-04',
        'CR-CRYOGENIC-STORAGE-TRANSFER-04', 'PG-SOLAR-POWER-04',
        'BIO-HUMAN-BIOLOGY-MEDICINE-05', 'SS-SENSING-05',
        'TH-THERMAL-TRANSPORT-03', 'PL-PLANT-FOOD-02',
    )
    early = _technology_closure(sim, early_endpoints)
    selected = _technology_closure(sim, chosen) - early
    concurrent_selected = _technology_closure(sim, concurrent) - early - selected
    remote_lab = 'planned.facility.remote_operations_lab'
    archive = 'planned.facility.robotic_data_archive'
    pad = 'planned.facility.surface_lander_service_pad'
    orbital_assembly = 'planned.facility.orbital_light_assembly_cell'
    # Reusable prior-stage assets plus distinct second-stage scientific equipment.
    remote_lab_units = 2
    microgravity_units = 3
    activities = _earth_industry(sim, research_lab_count=6,
                                 propellant_process_rate=1.75, electrolysis_rate=1.85,
                                 fuel_plants=2, water_intakes=2) + [
        {'kind': 'facility_operation', 'node': EARTH, 'id': 'planned.facility.earth_basic_electronics_shop',
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': 'planned.process.earth_basic_electronics'},
        {'kind': 'process', 'node': EARTH, 'id': 'planned.process.earth_basic_electronics', 'rate_per_day': .8},
        {'kind': 'facility_operation', 'node': EARTH, 'id': 'planned.facility.basic_data_archive',
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': ids.PROPULSION_TEST_FACILITY,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': remote_lab,
         'count': remote_lab_units, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_construction', 'node': EARTH, 'id': remote_lab,
         'count': remote_lab_units},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.ELECTROLYSIS_PLANT, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.PROPELLANT_PLANT, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.INDUSTRIAL_WATER_INTAKE, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': archive, 'count': 1},
        {'kind': 'facility_operation', 'node': EARTH, 'id': archive,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        # Light orbital assembly requires its own vacuum-capable equipment,
        # local power, construction work and inbound materials. Surface
        # vehicle assembly facilities cannot simply operate in LEO.
        {'kind': 'facility_construction', 'node': str(ids.LEO),
         'id': orbital_assembly, 'count': 1},
        {'kind': 'facility_operation', 'node': str(ids.LEO),
         'id': orbital_assembly, 'count': 1, 'context_id': ids.LEO},
        {'kind': 'facility_construction', 'node': str(ids.LEO),
         'id': ids.MICROGRAVITY_EXPERIMENT_PLATFORM, 'count': microgravity_units},
        {'kind': 'facility_operation', 'node': str(ids.LEO),
         'id': ids.MICROGRAVITY_EXPERIMENT_PLATFORM, 'count': microgravity_units,
         'context_id': ids.LEO},
        {'kind': 'facility_construction', 'node': str(ids.LEO),
         'id': ids.ORBITAL_SOLAR_ARRAY, 'count': 1},
        {'kind': 'facility_operation', 'node': str(ids.LEO),
         'id': ids.ORBITAL_SOLAR_ARRAY, 'count': 1, 'context_id': ids.LEO},
        {'kind': 'construction_resource', 'node': str(ids.LEO),
         'id': ids.CONSTRUCTION_EQUIPMENT, 'available_stock_t': .5},
        {'kind': 'vehicle_production', 'node': str(ids.LEO), 'id': ids.CREW_TRANSFER_SPACECRAFT, 'count': 1},
        {'kind': 'vehicle_production', 'node': str(ids.LEO), 'id': ids.REUSABLE_SURFACE_CARGO_LANDER, 'count': 2},
        {'kind': 'vehicle_production', 'node': str(ids.LEO), 'id': ids.CREWED_LOW_GRAVITY_LANDER, 'count': 2},
        {'kind': 'vehicle_production', 'node': str(ids.LEO), 'id': ids.RADAR_MAPPING_ORBITER, 'count': 1},
    ]
    founding = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
    local_manifests = []
    for cell in LUNAR_SITES:
        node = str(cell)  # Location construction is hypothetical, not assumed completed.
        # The first outpost was acquired in stage one; only the second site
        # requires a new founding package and staging payload.
        if cell != LUNAR_SITES[0]:
            activities.append({'kind': 'founding', 'node': LUNAR_ORBIT,
                'id': ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE, 'target_context_id': cell,
                'staging_context_id': ids.LUNAR_ORBIT, 'count': 1})
        # Geological science supplies a local second-tier research method at
        # each developed surface site, rather than a free global stage buff.
        site_assets = (ids.HABITAT, ids.SURFACE_POWER_GRID, pad,
                       ids.ROBOTIC_GEOLOGY_STATION)
        manifest = {str(r): per_person * 8 for r, per_person
                    in sim.facilities.definitions[ids.HABITAT].life_support.net_resources}
        # Conservative replenishment envelope for low-duty-cycle landers,
        # plus a bounded amount of extra construction equipment.
        manifest[str(ids.PROPELLANT)] = .012
        manifest[str(ids.CONSTRUCTION_EQUIPMENT)] = .05 / CISLUNAR_WINDOW_DAYS
        for fid in site_assets:
            for part in sim.projects.recipes[fid].resources:
                key = str(part.resource_id)
                manifest[key] = manifest.get(key, 0) + part.amount_t / CISLUNAR_WINDOW_DAYS
        if cell != LUNAR_SITES[0]:
            for part in founding.payload_resources:
                key = str(part.resource_id)
                manifest[key] = manifest.get(key, 0) + part.amount_t / CISLUNAR_WINDOW_DAYS
        local_manifests.append(manifest)
        activities.extend([
            {'kind': 'facility_construction', 'node': node, 'id': fid, 'count': 1}
            for fid in site_assets
        ])
        activities.extend([
            {'kind': 'facility_operation', 'node': node, 'id': fid,
             'context_id': cell, 'count': 1}
            for fid in site_assets
        ])
        # Initial founding provides .05t construction equipment. Additional
        # .05t is an explicit inbound sourcing requirement, not a free grant.
        activities.extend([
            {'kind': 'construction_resource', 'node': node, 'id': ids.CONSTRUCTION_EQUIPMENT,
             'available_stock_t': .10},
            {'kind': 'life_support', 'node': node, 'id': ids.HABITAT, 'people': 8},
            _candidate_cycle(sim, ids.LUNAR_ORBIT, cell, ids.REUSABLE_SURFACE_CARGO_LANDER,
                             LUNAR_ORBIT, node, manifest),
            {'kind': 'movement', 'node': LUNAR_ORBIT,
             'id': ids.CREWED_LOW_GRAVITY_LANDER,
             'origin_context_id': ids.LUNAR_ORBIT, 'destination_context_id': cell,
             'movement_plan_id': _candidate_leg(sim, ids.LUNAR_ORBIT, cell,
                 ids.CREWED_LOW_GRAVITY_LANDER, 0)['movement_plan_id'],
             'cargo_t': 0, 'count': math.ceil(8 / sim.transport.vehicle_defs[
                 ids.CREWED_LOW_GRAVITY_LANDER].passengers.seats)},
        ])
    # Forward flow through each transit leg is a *source-side obligation*.
    # Including propulsion, construction mass and consumables at every tier
    # reveals the genuine Earth-to-LEO launch cost instead of materializing
    # cargo at LEO or lunar orbit for free.
    moon_manifest = {}
    for manifest in local_manifests:
        for key, rate in manifest.items():
            moon_manifest[key] = moon_manifest.get(key, 0) + rate
    moon_manifest[str(ids.PROPELLANT)] += .055
    moon_manifest[str(ids.CONSTRUCTION_EQUIPMENT)] += .0
    # Explicit fuel delivery to LEO serves the tug's own outbound duty cycle.
    leo_manifest = dict(moon_manifest)
    leo_manifest[str(ids.PROPELLANT)] += .12
    # LEO's orbital assembly cell must itself be built and supplied from
    # Earth. Lunar craft are then physically repositioned to lunar orbit.
    for fid, count in ((orbital_assembly, 1), (ids.ORBITAL_SOLAR_ARRAY, 1),
                       (ids.MICROGRAVITY_EXPERIMENT_PLATFORM, microgravity_units)):
        for req in sim.projects.recipes[fid].resources:
            key = str(req.resource_id)
            leo_manifest[key] = leo_manifest.get(key, 0) + req.amount_t * count / CISLUNAR_WINDOW_DAYS
    for fid, count in ((ids.CREW_TRANSFER_SPACECRAFT, 1),
                       (ids.REUSABLE_SURFACE_CARGO_LANDER, 2),
                       (ids.CREWED_LOW_GRAVITY_LANDER, 2),
                       (ids.RADAR_MAPPING_ORBITER, 1)):
        for rid, amount in sim.transport.vehicle_defs[fid].production.resources:
            key = str(rid)
            leo_manifest[key] = leo_manifest.get(key, 0) + amount * count / CISLUNAR_WINDOW_DAYS
    leo_manifest[str(ids.CONSTRUCTION_EQUIPMENT)] = (
        leo_manifest.get(str(ids.CONSTRUCTION_EQUIPMENT), 0) + .5 / CISLUNAR_WINDOW_DAYS)
    activities.extend([
        _candidate_cycle(sim, ids.LEO, ids.LUNAR_ORBIT,
                         ids.REUSABLE_ORBITAL_CARGO_TUG, str(ids.LEO), LUNAR_ORBIT,
                         moon_manifest),
        _candidate_cycle(sim, ids.EARTH_CELL_INDUSTRIAL, ids.LEO,
                         ids.REUSABLE_LAUNCH_VEHICLE, EARTH, str(ids.LEO),
                         leo_manifest),
        # Population relocation is not a recurrent transport supply rate.
        {'kind': 'movement', 'node': EARTH, 'id': ids.REUSABLE_LAUNCH_VEHICLE,
         'origin_context_id': ids.EARTH_CELL_INDUSTRIAL, 'destination_context_id': ids.LEO,
         'movement_plan_id': _candidate_leg(sim, ids.EARTH_CELL_INDUSTRIAL, ids.LEO,
                 ids.REUSABLE_LAUNCH_VEHICLE, 0)['movement_plan_id'],
         'cargo_t': 0, 'count': 2},
        # Freshly assembled landers reposition from LEO. The first-stage
        # lander remains at the lunar surface until a real return operation.
        *[{'kind': 'movement', 'node': str(ids.LEO), 'id': vid,
           'origin_context_id': ids.LEO, 'destination_context_id': ids.LUNAR_ORBIT,
           'movement_plan_id': _candidate_leg(sim, ids.LEO, ids.LUNAR_ORBIT,
               vid, 0)['movement_plan_id'], 'cargo_t': 0, 'count': count}
          for vid, count in ((ids.REUSABLE_SURFACE_CARGO_LANDER, 2),
                             (ids.CREWED_LOW_GRAVITY_LANDER, 2))],
        {'kind': 'movement', 'node': str(ids.LEO), 'id': ids.CREW_TRANSFER_SPACECRAFT,
         'origin_context_id': ids.LEO, 'destination_context_id': ids.LUNAR_ORBIT,
         'movement_plan_id': _candidate_leg(sim, ids.LEO, ids.LUNAR_ORBIT,
                 ids.CREW_TRANSFER_SPACECRAFT, 0)['movement_plan_id'],
         'cargo_t': 0, 'count': 2},
        {'kind': 'movement', 'node': str(ids.LEO), 'id': ids.RADAR_MAPPING_ORBITER,
         'origin_context_id': ids.LEO, 'destination_context_id': ids.MARS_ORBIT,
         'movement_plan_id': _candidate_leg(sim, ids.LEO, ids.MARS_ORBIT,
                 ids.RADAR_MAPPING_ORBITER, 0)['movement_plan_id'],
         'cargo_t': 0, 'count': 1},
    ])
    activities += _research_inputs(sim, chosen, previous=early)
    activities += _research_inputs(sim, concurrent, previous=early | selected,
                                   portfolio='parallel')
    return {'stage': 2, 'period_days': CISLUNAR_WINDOW_DAYS,
            'cumulative_target_hours': 12,
            'questions': ('Can first-stage Earth industry sustain stage-two propellant, research, construction and spacecraft acquisition?',
                          'Are the two moon sites supported by finite transferred cargo, equipment and landing services?',
                          'Do Earth-to-LEO, LEO-to-lunar-orbit, and surface cycles share the same sourced consumables?',
                          'Does the inherited and expanded Tier 1–2 research infrastructure yield materially greater executable RP throughput, not just generation?',
                          'How much of the research progression is still gated by physical Prototype/Demonstration/Knowledge?'),
            'selected_research': sorted(map(str, selected)),
            'parallel_research': sorted(map(str, concurrent_selected)),
            'activities': activities}


def _summarize_evidence(sim, case, result):
    """Show decision-relevant rates, preserving the distinct units and owners."""
    # Show stage-wide cost context *separately* from the deliberately selected
    # technical branch. A branch average divided by differing period lengths
    # is not a valid cross-stage comparison of the whole research system.
    reference = [definition for definition in sim.research.definitions.values()
                 if definition.progression_stage == case['stage']]
    reference_theory_rp = sum(stage.research_point_cost
        for definition in reference for stage in definition.stage_specs
        if hasattr(stage, 'research_point_cost'))
    theory_by_portfolio = {'activity': 0.0, 'parallel': 0.0}
    for activity in case['activities']:
        if activity['kind'] != 'research_stage':
            continue
        stage = sim.research.definitions[activity['id']].stage_spec(activity['stage_id'])
        if hasattr(stage, 'research_point_cost'):
            theory_by_portfolio[activity.get('portfolio', 'activity')] += (
                stage.research_point_cost * activity['count'])
    total_theory_rp = sum(theory_by_portfolio.values())
    nominal = result['research_by_scope'][0]
    summary = {
        'research_scale': {
            'display_stage_research_count': len(reference),
            'display_stage_theory_rp_total_reference_only': reference_theory_rp,
            'display_stage_mean_theory_rp_per_research': (reference_theory_rp / len(reference)
                if reference else 0),
            'activity_branch_theory_rp_total': theory_by_portfolio['activity'],
            'parallel_science_theory_rp_total': theory_by_portfolio['parallel'],
            'activity_and_parallel_theory_rp_total': total_theory_rp,
            'sampled_branch_mean_theory_rp_per_day': total_theory_rp / case['period_days'],
            'nominal_sustained_theory_processing_bound_rp_per_day': min(
                nominal['rp_nominal_per_day'], nominal['execution_nominal_per_day']),
            'interpretation': 'all-stage sum is optional research, not required completion; '
                'sampled activity plus optional parallel science rate depends on the chosen window; '
                'sustained bound excludes stored RP drawdown, acquisition, allocation, power, RP admission and typed stages',
        },
        'stage': case['stage'], 'design_target_hours_cumulative': case['cumulative_target_hours'],
        'sample_window_days': case['period_days'], 'technology_branch_size': len(case['selected_research']),
        'concurrent_science_branch_size': len(case.get('parallel_research', ())),
        'research': result['research_by_scope'],
        'resources': result['resource_by_node'], 'service': result['service_by_scope'],
        'power': result['power_by_node'], 'habitation': result['habitation_by_node'],
        'extraction_opportunity': [
            {'source': row['source'], 'declared_rate_t_per_day': next(
                (e['mean_t_per_day'] for e in row['evidence']
                 if e.get('measure') == 'resource' and e['direction'] == 'supply'), 0),
             'physical_response_t_per_day': next(
                (e['combined_physical_response_t_per_day'] for e in row['evidence']
                 if e.get('measure') == 'extraction_physical_opportunity'), 0)}
            for row in result['activity_evidence'] if row['source'].startswith('extraction:')
        ],
        'transport_requirements': [
            {'source': row['source'], 'evidence': entry}
            for row in result['activity_evidence'] for entry in row['evidence']
            if entry.get('measure') == 'transport_od_demand'
        ],
        'unresolved_physics': [
            {'source': row['source'], 'details': entry}
            for row in result['activity_evidence'] for entry in row['evidence']
            if entry.get('measure') == 'one_way_movement' and
            (entry['vehicle_physical_failures'] or entry['origin_environment_failures'] or
             entry['destination_environment_failures'])
        ],
        'questions': case['questions'], 'limits': result['limits'],
    }
    return summary



def evaluate_stage(stage: int) -> dict:
    """Return conditional evidence, not a verdict on stage feasibility.

    No gameplay State is advanced, and quoted capacities are not effective
    allocations, fulfilled cargo, or guaranteed technology unlocks.
    """
    scenarios = {1: _stage_one, 2: _stage_two}
    if stage not in scenarios:
        raise ValueError(f'No authored evaluation scenario for stage {stage}')
    sim, _ = _setup()
    case = scenarios[stage](sim)
    report = quantity_ledger(sim, period_days=case['period_days'], activities=case['activities'])
    return _summarize_evidence(sim, case, report)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description='Inspect revisable stage balance assumptions and quantity evidence; not a test suite.')
    parser.add_argument('--stage', type=int, choices=(1, 2), action='append',
                        help='Stage to evaluate (repeatable). Default: both authored stages.')
    args = parser.parse_args(argv)
    stages = sorted(set(args.stage or (1, 2)))
    for stage in stages:
        print(json.dumps(evaluate_stage(stage), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
