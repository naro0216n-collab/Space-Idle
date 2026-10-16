"""One whole-development decision view over canonical pacing quantities.

The detailed numbers remain available as evidence, not improvement objectives.
No grades, priorities, inferred edits or gameplay simulation are produced here.
"""
from __future__ import annotations


# The questions jointly describe ONE system KPI, never independent targets.
COUPLED_DIMENSIONS = (
    "Research generations and the industrial investment that supports them",
    "Industrial expansion, geographic development and the supporting logistics",
    "Population and crew activity with continuing production and supply",
    "Concurrent investment, sustained operations and transitions over the whole time horizon",
)

AUTHOR_FIELDS = {
    "research": ("research_ids", "research_provider", "research_time_share"),
    "capital": ("facility_targets", "vehicle_targets"),
    "industry": ("production_targets", "supply_choices", "resource_supply_assumptions"),
    "logistics": ("transport_targets",),
    "population": ("population_targets",),
}

# The *meaning* of each condition is owned by the canonical quantitative
# evaluation. Here we only group its already-declared cross-domain limits.
DOMAIN_GROUPS = {
    "production_goal": "industry", "supply": "industry", "power": "industry",
    "construction": "capital", "capital": "capital", "research": "research",
    "logistics": "logistics", "transport": "logistics", "population": "population",
    "time": "time", "research_execution": "research", "content": "industry",
}


def whole_horizon_decision_view(stages: list[dict], authored_steps: list[dict]) -> dict:
    """Describe the whole horizon, not the best individual coefficient to edit."""
    if len(stages) != len(authored_steps) or not stages:
        raise ValueError("development stages and authored assumptions must align")
    covered = set()
    for step in authored_steps:
        covered.update(domain for domain, fields in AUTHOR_FIELDS.items()
                       if any(bool(step.get(field)) for field in fields))

    # Each relation refers to ALL occurrences across the horizon. Do not
    # publish per-Resource/Facility numbers or the most tempting issue code.
    relations: dict[tuple[str, ...], set[str]] = {}
    unclassified: set[str] = set()
    for stage in stages:
        for issue in stage["constraints"]:
            unclassified.update(set(issue["limits"]) - DOMAIN_GROUPS.keys())
            connected = tuple(sorted({DOMAIN_GROUPS[k] for k in issue["limits"]
                                      if k in DOMAIN_GROUPS}))
            if len(connected) >= 2:
                relations.setdefault(connected, set()).add(stage["name"])

    return {
        "decision_unit": "entire_development_trajectory",
        "horizon": {
            "milestones": [stage["name"] for stage in stages],
            "scope": "eight_stage_reference" if len(stages) >= 8 else "partial_horizon_not_whole_game",
            "not_a_required_gameplay_path": True,
        },
        "single_integrated_kpi": {
            "question": "Does the proposed whole-game development remain coherent across research, investment, industry, logistics, settlement and time?",
            "inseparable_dimensions": list(COUPLED_DIMENSIONS),
            "judgment": "requires_designer_evaluation_not_an_automatic_score",
        },
        "evaluation_conditions": {
            "authored_domains_somewhere_in_horizon": sorted(covered),
            "unarticulated_domains_not_assumed_zero": sorted(set(AUTHOR_FIELDS) - covered),
            "cross_domain_relations_with_unverified_conditions": [
                {"domains": list(domains), "technical_evidence_milestones": sorted(names)}
                for domains, names in sorted(relations.items())
            ],
            "unclassified_condition_dimensions": sorted(unclassified),
            "individual_conditions": "technical_evidence_only",
        },
        "decision_policy": {
            "technical_coefficients": "evidence_only_not_edit_objectives",
            "unknowns": "not_zero_and_not_failure",
            "implementation": "planned_quantities_are_not_achieved_game_state",
            "acceptance": "reassess_the_entire_trajectory_after_any_content_change",
        },
    }
