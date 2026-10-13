"""Selected Technology prerequisites and Stage time constraints for the shared quantity ledger.

This module supplies no independent RP/industry calculator or catalog-wide
Research economy report. Activity choices and quantities belong to the single
phase projection in analysis_balance.py.
"""
from __future__ import annotations

from space_idle.shared import DefinitionId
from space_idle.research_models import site_stage_daily_progress_request_limit



def selected_research_time_structure(definitions, stages, services, *,
                                     organization_execution_per_day,
                                     rp_generation_lower_bound_days,
                                     total_execution_lower_bound_days):
    """Conditional, non-scheduling lower bounds for a selected Research workload.

    An actual Research Project executes its registered Stages in order, and a
    prerequisite Technology precedes its dependent Technology. Independent
    projects can overlap. Only Service work that can be quantified from the
    same selected-activity ledger participates in the serial path; RP can be
    banked before a Stage and its aggregate generation floor is separate.
    Missing Service capacity and experience are gates, never zero-day unlocks.
    """
    chosen = {row['research'] for row in stages}
    stage_by_id = {(row['research'], row['stage']): row for row in stages}
    service_capacity = {(scope, kind): capacity for scope, kind, capacity in services}
    stage_bounds = []
    serial_by_tech = {}
    missing_capacity = set()
    experience = []
    missing_stages = []
    for tech_id in sorted(chosen):
        definition = definitions[DefinitionId(tech_id)]
        serial = 0.0
        for spec in definition.stage_specs:
            stage = stage_by_id.get((tech_id, spec.stage_id))
            if stage is None:
                missing_stages.append(f'{tech_id}/{spec.stage_id}')
                continue
            requirements = []
            daily_request_limit = site_stage_daily_progress_request_limit(spec)
            progress_floor = (getattr(spec, 'required_work', 0.0) / daily_request_limit
                              if daily_request_limit else 0.0)
            duration_floor = progress_floor
            for requirement in stage['execution_requirements']:
                if requirement['kind'] != 'service':
                    continue
                scope = ('organization' if requirement['scope'] == 'ORGANIZATION'
                         else f"node:{requirement.get('node', stage['node'])}")
                amount = requirement['total_required']
                rate = (organization_execution_per_day
                        if (scope, requirement['name']) == ('organization', 'research_execution')
                        else service_capacity.get((scope, requirement['name']), 0.0))
                floor = amount / rate if rate > 0 else 0.0 if amount == 0 else None
                if floor is None:
                    missing_capacity.add((scope, requirement['name']))
                else:
                    duration_floor = max(duration_floor, floor)
                requirements.append({'scope': scope, 'service': requirement['name'],
                                     'required_work': amount, 'capacity_per_day': rate,
                                     'lower_bound_days': floor})
            if stage['stage_type'] == 'operational_experience':
                experience.append(f'{tech_id}/{spec.stage_id}')
            serial += duration_floor
            stage_bounds.append({'research': tech_id, 'stage': spec.stage_id,
                                 'stage_type': stage['stage_type'],
                                 'required_service_bounds': requirements,
                                 'site_progress_request_limit_per_day': daily_request_limit,
                                 'site_progress_lower_bound_days': progress_floor,
                                 'serial_service_lower_bound_days': duration_floor,
                                 'unresolved_stage_gate': (
                                     stage['stage_type'] == 'operational_experience'
                                     or any(v['lower_bound_days'] is None for v in requirements)),
                                 'status': 'lower_bound_not_a_stage_completion_schedule'})
        serial_by_tech[tech_id] = serial
    memo = {}
    def critical(tech_id):
        if tech_id not in memo:
            prerequisites = [critical(str(p)) for p in definitions[DefinitionId(tech_id)].prerequisites
                             if str(p) in chosen]
            memo[tech_id] = serial_by_tech[tech_id] + max(prerequisites, default=0.0)
        return memo[tech_id]
    critical_floor = max((critical(k) for k in chosen), default=0.0)
    numeric_floors = [critical_floor]
    numeric_floors.extend(v for v in (rp_generation_lower_bound_days,
                                      total_execution_lower_bound_days) if v is not None)
    return {
        'selected_stage_service_bounds': stage_bounds,
        'serial_prerequisite_stage_service_lower_bound_days': critical_floor,
        'shared_rp_generation_lower_bound_days': rp_generation_lower_bound_days,
        'shared_research_execution_lower_bound_days': total_execution_lower_bound_days,
        'conditional_known_capacity_lower_bound_days': max(numeric_floors),
        'missing_stage_service_capacity': [
            {'scope': scope, 'service': name} for scope, name in sorted(missing_capacity)],
        'operational_experience_gates_not_elapsed_time': experience,
        'unselected_stages_in_technology': sorted(missing_stages),
        'external_prerequisites': sorted({str(pre) for key in chosen
            for pre in definitions[DefinitionId(key)].prerequisites if str(pre) not in chosen}),
        'status': 'conditional_lower_bound_not_a_completion_date',
    }


def research_goal_closure(definitions, research_ids, *, include_prerequisites=False):
    """Resolve the registered Technology DAG once for both goal and quantity views.

    The closure is a set of *requirements*, not a scheduled Research Project
    sequence or a claim of unlocked Technologies.
    """
    chosen = set(research_ids)
    if not chosen or len(chosen) != len(research_ids):
        raise ValueError('research IDs must be nonempty and unique')
    if not chosen <= {str(identifier) for identifier in definitions}:
        raise ValueError('unknown research ID')
    if include_prerequisites:
        todo = list(chosen)
        while todo:
            definition = definitions[DefinitionId(todo.pop())]
            for prerequisite in definition.prerequisites:
                if str(prerequisite) not in chosen:
                    chosen.add(str(prerequisite))
                    todo.append(str(prerequisite))
    return tuple(sorted(chosen))
