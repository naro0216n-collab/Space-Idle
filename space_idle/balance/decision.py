"""Whole-development decision evidence, derived from actual quantity transitions.

This is not a balance scorer, activity planner or Content edit recommender.  A
milestone's existence or a field's presence never establishes development.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor, isfinite, log10


COUPLED_QUESTIONS = (
    "Do research generations and the investment/industry supporting them develop together?",
    "Do the scale and location of industry, transport, and settlement remain compatible?",
    "Can investment and continuing operations coexist across the intended time horizon?",
)

DOMAIN_GROUPS = {
    "production_goal": "industry", "supply": "industry", "power": "industry",
    "construction": "capital", "capital": "capital", "research": "research",
    "logistics": "logistics", "transport": "logistics", "population": "population",
    "time": "time", "research_execution": "research", "content": "industry",
}


def _total(rows, key):
    return sum(row.get(key, 0) or 0 for row in rows)


def _scale_change(before, after):
    """Describe change, never whether that change is desirable."""
    if not isfinite(before) or not isfinite(after) or before < 0 or after < 0:
        raise ValueError("invalid whole-development quantity")
    if before == 0:
        return "newly_described" if after > 0 else "not_quantified"
    if after == 0:
        return "no_longer_quantified"
    ratio = after / before
    if ratio >= 10:
        return "order_of_magnitude_expansion"
    if ratio <= 0.1:
        return "order_of_magnitude_contraction"
    if ratio > 1.25:
        return "expansion"
    if ratio < 0.8:
        return "contraction"
    return "similar_scale"


def _magnitude(value):
    """Order-of-magnitude evidence, not a success band or an ideal target."""
    if not isfinite(value) or value < 0:
        raise ValueError("invalid whole-development magnitude")
    return "none_in_assumption" if value == 0 else f"order_10^{floor(log10(value))}"


def _snapshot(stage):
    """Use cumulative end-state and interval acquisition as different quantities."""
    research = stage["research"]
    return {
        "research_interval": research["required_average_rp_per_day_if_full_interval"],
        "capital_interval": _total(stage["capital_resources_t"], "quantity_t") / stage["interval_game_days_at_base_speed"],
        "construction_interval_per_day": sum(row["work_per_day_to_finish_in_interval"]
                                                 for row in stage["required_average_work_per_day_by_service"]
                                                 if row["service"] == "construction_work"),
        "industrial_end_operation": _total(stage["end_target_nominal_inputs_t_per_day"], "quantity_t"),
        "industry_authored_output": _total(stage["production_targets"], "target_t_per_day"),
        "logistics_end_flow": _total(stage["transport_targets"], "target_t_per_day"),
        "settlement_end_people": _total(stage["population_targets"], "target_people"),
        "power_end_load": _total(stage["end_target_reference_power"], "nominal_load_mw"),
    }


def _new_outcomes(stage, prev_stage, step):
    """Only measured new developments; inherited plans and repeated IDs aren't new."""
    outcome = []
    if stage["research"]["new_prerequisites_and_research"]:
        outcome.append("new_research_acquisition")
    if any(row["kind"] in {"facility_acquisition", "vehicle_acquisition",
                                   "facility_construction_work", "vehicle_production_work"}
           for row in stage["quantity_evidence"]):
        outcome.append("new_acquisition_or_build_work")
    if prev_stage is None:
        prior_prod, prior_supply, prior_routes, prior_pop = (), (), (), ()
    else:
        prior_prod = prev_stage["production_targets"]
        prior_supply = prev_stage["supply_choices"]
        prior_routes = prev_stage["transport_targets"]
        prior_pop = prev_stage["population_targets"]
    # Compare only the authored state (not option lists, Preview or conditional data).
    def pairs(rows, keys):
        return sorted(tuple(row.get(k) for k in keys) for row in rows)
    if pairs(stage["production_targets"], ("node", "resource", "target_t_per_day")) != pairs(prior_prod, ("node", "resource", "target_t_per_day")) or (
        pairs(stage["supply_choices"], ("node", "resource", "facility", "method")) !=
        pairs(prior_supply, ("node", "resource", "facility", "method"))):
        outcome.append("industry_plan_transition")
    if pairs(stage["transport_targets"], ("source", "destination", "resource", "target_t_per_day")) != pairs(
        prior_routes, ("source", "destination", "resource", "target_t_per_day")):
        outcome.append("logistics_plan_transition")
    if pairs(stage["population_targets"], ("node", "target_people")) != pairs(prior_pop, ("node", "target_people")):
        # In the first interval, initial population is not an authored expansion.
        if prev_stage is not None or step.get("population_targets"):
            outcome.append("settlement_plan_transition")
    return outcome


def whole_horizon_decision_view(stages: list[dict], authored_steps: list[dict]) -> dict:
    """One coupled KPI, with observed development transitions rather than coverage badges."""
    if len(stages) != len(authored_steps) or not stages:
        raise ValueError("development stages and authored assumptions must align")
    trajectory, unarticulated = [], []
    previous, previous_snapshot = None, None
    relations: dict[tuple[str, ...], set[str]] = defaultdict(set)
    unknown_dimensions: set[str] = set()
    for stage, step in zip(stages, authored_steps):
        name = stage["name"]
        outcomes = _new_outcomes(stage, previous, step)
        if not outcomes:
            unarticulated.append(name)
        current = _snapshot(stage)
        # These are *joint relationships*, not independent scores or recommended
        # correction directions. The technical magnitudes stay in evidence.
        if previous_snapshot is None:
            changes = {k: ("initial_reference" if value else "not_quantified")
                       for k, value in current.items()}
        else:
            changes = {k: _scale_change(previous_snapshot[k], value)
                       for k, value in current.items()}
        couples = [
            {"relation": "research_acquisition_industrial_investment_and_supply",
             "pattern": [changes[k] for k in ("research_interval", "capital_interval", "industrial_end_operation")]},
            {"relation": "industrial_output_logistics_and_settlement",
             "pattern": [changes[k] for k in ("industry_authored_output", "logistics_end_flow", "settlement_end_people")]},
            {"relation": "investment_work_and_power",
             "pattern": [changes[k] for k in ("capital_interval", "construction_interval_per_day", "power_end_load")]},
        ]
        # An inherited / initial-state limitation cannot by itself prove that
        # a milestone assessed new activity. Keep it as evidence, not coverage.
        for issue in stage["constraints"]:
            limits = issue.get("limits", ())
            unknown_dimensions.update(k for k in limits if k not in DOMAIN_GROUPS
                                      and k not in {"development_goal", "balance_judgment"})
            if outcomes:
                domains = tuple(sorted({DOMAIN_GROUPS[k] for k in limits if k in DOMAIN_GROUPS}))
                if len(domains) > 1:
                    relations[domains].add(name)
        trajectory.append({
            "milestone": name,
            "development_evidence": "new_outcomes_quantified_conditionally" if outcomes else "no_new_development_articulated",
            "new_development_connections": outcomes,
            "coupled_scale_transitions": couples,
            "whole_system_scale_evidence": {
                "relationship": "research_investment_industry_transport_settlement_and_time",
                "joint_dimensions_in_order": [
                    "research_rp_per_day", "capital_t_per_day", "construction_work_per_day",
                    "gross_operating_input_t_per_day", "authored_production_t_per_day",
                    "authored_transport_t_per_day", "planned_settlement_people", "nominal_power_mw"
                ],
                "joint_magnitude_profile": [_magnitude(current[k]) for k in current],
                "not_a_target_or_feasibility_proof": True,
            },
            "basis": "current_quantities_not_verified_gameplay",
        })
        previous, previous_snapshot = stage, current

    # Read the first/last conditional end-state together. This is a scale arc,
    # not a per-domain result or an independently passable set of KPIs.
    first = _snapshot(stages[0])
    last = _snapshot(stages[-1])
    entire_arc = {
        "reference_intervals": [stages[0]["name"], stages[-1]["name"]],
        "combined_scale_shifts": [
            {"relation": "research_investment_and_operating_industry",
             "shifts": [_scale_change(first[k], last[k]) for k in (
                 "research_interval", "capital_interval", "industrial_end_operation")]},
            {"relation": "production_transport_and_settlement",
             "shifts": [_scale_change(first[k], last[k]) for k in (
                 "industry_authored_output", "logistics_end_flow", "settlement_end_people")]},
            {"relation": "construction_and_power",
             "shifts": [_scale_change(first[k], last[k]) for k in (
                 "construction_interval_per_day", "power_end_load")]},
        ],
        "meaning": "conditional scale relations, not a demonstrated path or a desirable growth target",
    }
    return {
        "decision_unit": "entire_development_trajectory",
        "horizon": {
            "milestones": [stage["name"] for stage in stages],
            "assessment": "unarticulated_development_intervals" if unarticulated else "development_quantities_not_semantic_validation",
            "unarticulated_intervals": unarticulated,
            "not_a_required_gameplay_path": True,
        },
        "single_integrated_kpi": {
            "question": "Is the entire intended development coherent across research, investment, industry, logistics, settlement and time?",
            "joint_questions": list(COUPLED_QUESTIONS),
            "assessment": ("whole_trajectory_not_evaluable_from_these_assumptions" if unarticulated
                           else "development_quantities_available_not_verified_coherence"),
            "automatic_balance_verdict": None,
            "observed_whole_horizon": entire_arc,
        },
        "trajectory": trajectory,
        "cross_horizon_unverified_relations": [
            {"domains": list(domains), "evidence_intervals": sorted(names)}
            for domains, names in sorted(relations.items())
        ],
        "unclassified_condition_dimensions": sorted(unknown_dimensions),
        "interpretation": "These are coupled changes in the authored quantities, not targets or a proof of feasible progress. No new outcome in an interval means it was not articulated, not that no activity occurs. Inherited capacity, arbitrary field presence and milestone count cannot establish whole-game coherence. Technical details serve only as traceable evidence.",
    }
