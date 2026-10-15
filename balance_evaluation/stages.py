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


def _research_inputs(sim, selection, previous=()):
    """Charge chosen typed stages and direct ancestors, without gifting unlocks."""
    selected = _technology_closure(sim, selection) - set(previous)
    return [
        {'kind': 'research_stage', 'node': EARTH, 'id': tid,
         'stage_id': stage.stage_id, 'count': 1}
        for tid in sorted(selected, key=str)
        for stage in sim.research.definitions[tid].stage_specs
    ]


def _earth_industry(sim, *, research_lab_count):
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
                                           facility_units=1, level=1)
        potential_rate = physical['physical_diminishing_response_t_per_day']
        # Explicit upper-envelope hypothesis, not an actual settled Source.
        proposed_rate = min(sim.extraction.nominal_capacity_for_level(fid, 1), potential_rate)
        activities.extend([
            {'kind': 'facility_operation', 'node': EARTH, 'id': fid,
             'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
             'selected_extraction_method_id': method},
            {'kind': 'extraction', 'node': EARTH, 'id': method, 'facility_id': fid,
             'facility_units': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
             'rate_t_per_day': proposed_rate},
        ])
    return activities


def _candidate_leg(sim, origin, destination, vehicle_id, cargo_t):
    evidence = movement_evidence(sim, origin, destination, vehicle_id, cargo_t=cargo_t)
    # A scenario must expose a missing physical leg, rather than invent one.
    if not evidence['forward']:
        raise ValueError(f'no physical leg for {vehicle_id} {origin} -> {destination}')
    return evidence['forward'][0]


def _stage_one(sim):
    chosen = ('PL-EARTH-PRECISION-PARTS', 'CO-RF-COMMUNICATIONS-01',
              'CR-CRYOGENIC-STORAGE-TRANSFER-02')
    acquired = _technology_closure(sim, chosen)
    archive = 'planned.facility.basic_data_archive'
    electronics_plant = 'planned.facility.earth_basic_electronics_shop'
    electronics_process = 'planned.process.earth_basic_electronics'
    founding = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
    leg = _candidate_leg(sim, ids.LUNAR_ORBIT, LUNAR_SITES[0],
                         ids.REUSABLE_SURFACE_CARGO_LANDER, founding.payload_t)
    launch = _candidate_leg(sim, ids.EARTH_CELL_INDUSTRIAL, ids.LEO,
                            ids.REUSABLE_LAUNCH_VEHICLE, founding.payload_t)
    transfer = _candidate_leg(sim, ids.LEO, ids.LUNAR_ORBIT,
                              ids.REUSABLE_ORBITAL_CARGO_TUG, founding.payload_t)
    activities = _earth_industry(sim, research_lab_count=2) + [
        {'kind': 'facility_construction', 'node': EARTH, 'id': ids.GENERAL_RESEARCH_LAB, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': archive, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': electronics_plant, 'count': 1},
        {'kind': 'facility_operation', 'node': EARTH, 'id': archive,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': electronics_plant,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': electronics_process},
        {'kind': 'process', 'node': EARTH, 'id': electronics_process, 'rate_per_day': 0.8},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.REUSABLE_LAUNCH_VEHICLE,
         'count': 1},
        {'kind': 'movement', 'node': EARTH, 'id': ids.REUSABLE_LAUNCH_VEHICLE,
         'origin_context_id': ids.EARTH_CELL_INDUSTRIAL, 'destination_context_id': ids.LEO,
         'movement_plan_id': launch['movement_plan_id'], 'cargo_t': founding.payload_t,
         'count': 1},
        {'kind': 'movement', 'node': str(ids.LEO), 'id': ids.REUSABLE_ORBITAL_CARGO_TUG,
         'origin_context_id': ids.LEO, 'destination_context_id': ids.LUNAR_ORBIT,
         'movement_plan_id': transfer['movement_plan_id'], 'cargo_t': founding.payload_t,
         'count': 1},
        {'kind': 'founding', 'node': LUNAR_ORBIT, 'id': ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE,
         'target_context_id': LUNAR_SITES[0], 'staging_context_id': ids.LUNAR_ORBIT, 'count': 1},
        {'kind': 'movement', 'node': LUNAR_ORBIT, 'id': ids.REUSABLE_SURFACE_CARGO_LANDER,
         'origin_context_id': ids.LUNAR_ORBIT, 'destination_context_id': LUNAR_SITES[0],
         'movement_plan_id': leg['movement_plan_id'], 'cargo_t': founding.payload_t, 'count': 1},
    ] + _research_inputs(sim, chosen)
    return {'stage': 1, 'period_days': EARTH_WINDOW_DAYS,
            'cumulative_target_hours': 4,
            'questions': ('Can finite Earth feedstocks sustain simultaneous parts, research and vehicle growth?',
                          'What remains to carry a real founding payload from Earth to lunar orbit?',
                          'Is RP generation, execution and admission adequate for the selected research branch?'),
            'selected_research': sorted(map(str, acquired)), 'activities': activities}


def _stage_two(sim):
    old = ('PL-EARTH-PRECISION-PARTS', 'CO-RF-COMMUNICATIONS-01',
           'CR-CRYOGENIC-STORAGE-TRANSFER-02')
    chosen = ('X2-REMOTE-OPERATIONS-LAB', 'X2-DATA-RETENTION',
              'BIO-HUMAN-BIOLOGY-MEDICINE-04', 'SS-SENSING-06')
    early = _technology_closure(sim, old)
    selected = _technology_closure(sim, chosen) - early
    remote_lab = 'planned.facility.remote_operations_lab'
    archive = 'planned.facility.robotic_data_archive'
    activities = _earth_industry(sim, research_lab_count=2) + [
        # Continuation from Stage 1: still using acquired electronics capacity,
        # not a free Stage 2 starting inventory or a second construction charge.
        {'kind': 'facility_operation', 'node': EARTH,
         'id': 'planned.facility.earth_basic_electronics_shop', 'count': 1,
         'context_id': ids.EARTH_CELL_INDUSTRIAL,
         'selected_process_id': 'planned.process.earth_basic_electronics'},
        {'kind': 'process', 'node': EARTH,
         'id': 'planned.process.earth_basic_electronics', 'rate_per_day': 0.8},
        {'kind': 'facility_operation', 'node': EARTH,
         'id': 'planned.facility.basic_data_archive', 'count': 1,
         'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_operation', 'node': EARTH, 'id': remote_lab,
         'count': 1, 'context_id': ids.EARTH_CELL_INDUSTRIAL},
        {'kind': 'facility_construction', 'node': EARTH, 'id': remote_lab, 'count': 1},
        {'kind': 'facility_construction', 'node': EARTH, 'id': archive, 'count': 1},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.CREW_TRANSFER_SPACECRAFT, 'count': 1},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.REUSABLE_SURFACE_CARGO_LANDER, 'count': 1},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.CREWED_LOW_GRAVITY_LANDER, 'count': 2},
        {'kind': 'vehicle_production', 'node': EARTH, 'id': ids.RADAR_MAPPING_ORBITER, 'count': 1},
    ]
    # Recurrent lunar-bound consumables compete with other deliveries on the
    # *preceding* leg too. Departure demand at LEO is not a delivered lunar stock.
    long_leg = sim.transport.movement_resolver()
    long_out = long_leg.physical_context_plans(ids.LEO, ids.LUNAR_ORBIT)
    long_back = long_leg.physical_context_plans(ids.LUNAR_ORBIT, ids.LEO)
    if not long_out or not long_back:
        raise ValueError('No usable physical LEO/lunar-orbit cycle for evaluation input')
    two_site_manifest = {
        str(rid): amount * 8 * len(LUNAR_SITES)
        for rid, amount in sim.facilities.definitions[ids.HABITAT].life_support.net_resources
    }
    activities.append({
        'kind': 'transport_cycle', 'node': str(ids.LEO), 'destination_node': LUNAR_ORBIT,
        'id': ids.REUSABLE_ORBITAL_CARGO_TUG, 'units': 1,
        'origin_context_id': ids.LEO, 'destination_context_id': ids.LUNAR_ORBIT,
        'forward_plan_id': str(long_out[0].id), 'reverse_plan_id': str(long_back[0].id),
        'forward_cargo_t_per_day': two_site_manifest,
    })
    for cell in LUNAR_SITES:
        node = str(cell)  # Prospective local accounting; NOT a founded Operational Node.
        founding = sim.founding.deployment_recipes[ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE]
        lander = _candidate_leg(sim, ids.LUNAR_ORBIT, cell,
                                ids.CREWED_LOW_GRAVITY_LANDER, cargo_t=0)
        # A source-side recurrent logistics load; cargo is not credited as
        # received at the unfounded destination. Two lanes require two units,
        # one existing lander and one separately acquired above.
        # Manifest demand at the dispatch node mirrors the separate local
        # consumption obligation; do not aggregate it as additional consumption.
        manifest = {
            str(rid): amount * 8
            for rid, amount in sim.facilities.definitions[ids.HABITAT].life_support.net_resources
        }
        resolver = sim.transport.movement_resolver()
        outbound = resolver.physical_context_plans(ids.LUNAR_ORBIT, cell)
        inbound = resolver.physical_context_plans(cell, ids.LUNAR_ORBIT)
        if not outbound or not inbound:
            raise ValueError(f'no return cycle for {cell}')
        activities.append({
            'kind': 'transport_cycle', 'node': LUNAR_ORBIT, 'destination_node': node,
            'id': ids.REUSABLE_SURFACE_CARGO_LANDER, 'units': 1,
            'origin_context_id': ids.LUNAR_ORBIT, 'destination_context_id': cell,
            'forward_plan_id': str(outbound[0].id), 'reverse_plan_id': str(inbound[0].id),
            'forward_cargo_t_per_day': manifest,
        })
        cargo_leg = _candidate_leg(sim, ids.LUNAR_ORBIT, cell,
                                   ids.REUSABLE_SURFACE_CARGO_LANDER, founding.payload_t)
        activities.extend([
            {'kind': 'founding', 'node': LUNAR_ORBIT, 'id': ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE,
             'target_context_id': cell, 'staging_context_id': ids.LUNAR_ORBIT, 'count': 1},
            {'kind': 'movement', 'node': LUNAR_ORBIT,
             'id': ids.REUSABLE_SURFACE_CARGO_LANDER, 'origin_context_id': ids.LUNAR_ORBIT,
             'destination_context_id': cell, 'movement_plan_id': cargo_leg['movement_plan_id'],
             'cargo_t': founding.payload_t, 'count': 1},
            {'kind': 'facility_construction', 'node': node, 'id': ids.HABITAT, 'count': 1},
            {'kind': 'facility_operation', 'node': node, 'id': ids.HABITAT,
             'context_id': cell, 'count': 1},
            {'kind': 'facility_construction', 'node': node, 'id': ids.SURFACE_POWER_GRID,
             'count': 1},
            {'kind': 'facility_operation', 'node': node, 'id': ids.SURFACE_POWER_GRID,
             'context_id': cell, 'count': 1},
            {'kind': 'life_support', 'node': node, 'id': ids.HABITAT, 'people': 8},
            {'kind': 'movement', 'node': LUNAR_ORBIT,
             'id': ids.CREWED_LOW_GRAVITY_LANDER, 'origin_context_id': ids.LUNAR_ORBIT,
             'destination_context_id': cell, 'movement_plan_id': lander['movement_plan_id'],
             'cargo_t': 0, 'count': math.ceil(8 / sim.transport.vehicle_defs[ids.CREWED_LOW_GRAVITY_LANDER].passengers.seats)},
        ])
    mars_leg = _candidate_leg(sim, ids.LEO, ids.MARS_ORBIT, ids.RADAR_MAPPING_ORBITER, cargo_t=0)
    activities.append({'kind': 'movement', 'node': str(ids.LEO),
                       'id': ids.RADAR_MAPPING_ORBITER,
                       'origin_context_id': ids.LEO, 'destination_context_id': ids.MARS_ORBIT,
                       'movement_plan_id': mars_leg['movement_plan_id'], 'cargo_t': 0, 'count': 1})
    activities += _research_inputs(sim, chosen, previous=early)
    return {'stage': 2, 'period_days': CISLUNAR_WINDOW_DAYS,
            'cumulative_target_hours': 12,
            'questions': ('Can stage-one industry acquire higher-tier research and transport assets concurrently?',
                          'Do two lunar habitation nodes have finite resources, return transport and power?',
                          'Does unmanned Mars survey compete with lunar fleet acquisition and research?'),
            'selected_research': sorted(map(str, selected)), 'activities': activities}


def _summarize_evidence(case, result):
    """Show decision-relevant rates, preserving the distinct units and owners."""
    summary = {
        'stage': case['stage'], 'design_target_hours_cumulative': case['cumulative_target_hours'],
        'sample_window_days': case['period_days'], 'technology_branch_size': len(case['selected_research']),
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
    return _summarize_evidence(case, report)


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
