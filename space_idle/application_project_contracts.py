from __future__ import annotations

from .application_constraints import constraints_from_codes, constraints_from_pairs
from .application_views import ContractRow, ContractsView
from .site import evaluate_site_requirements


class ContractProgressionProjectorMixin:
    def _contracts_view(self) -> ContractsView:
        sim = self._simulation
        if sim.contracts is None:
            return ContractsView(())
        rows: list[ContractRow] = []
        for state in sorted(
            sim.contracts.contracts.values(), key=lambda row: str(row.id)
        ):
            template = sim.contracts.templates[state.template_id]
            target_operational_node_id = (
                None
                if template.target_operational_node_id is None
                else str(template.target_operational_node_id)
            )
            if template.target_operational_node_id is not None:
                failures = evaluate_site_requirements(
                    template.site_requirements,
                    template.target_operational_node_id,
                    sim.day,
                    sim.environment,
                    sim.facilities,
                )
                blockers = constraints_from_pairs(
                    tuple((failure.code, failure.detail) for failure in failures),
                    affected_action="accept_contract",
                    related_entity_kind="contract",
                    related_entity_id=str(state.id),
                )
            else:
                blocker_codes = (
                    ()
                    if any(
                        not evaluate_site_requirements(
                            template.site_requirements,
                            node.id,
                            sim.day,
                            sim.environment,
                            sim.facilities,
                        )
                        for node in sim.graph.operational_nodes()
                    )
                    else ("site_requirements",)
                )
                blockers = constraints_from_codes(
                    blocker_codes,
                    affected_action="accept_contract",
                    related_entity_kind="contract",
                    related_entity_id=str(state.id),
                )
            rows.append(
                ContractRow(
                    str(state.id),
                    str(template.id),
                    template.display_name,
                    state.status.value,
                    state.deadline_day,
                    target_operational_node_id,
                    blockers,
                )
            )
        return ContractsView(tuple(rows))
