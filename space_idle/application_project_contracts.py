from __future__ import annotations

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
            target_location_id = (
                None
                if template.target_location_id is None
                else str(template.target_location_id)
            )
            if template.target_location_id is not None:
                failures = evaluate_site_requirements(
                    template.site_requirements,
                    template.target_location_id,
                    sim.day,
                    sim.environment,
                    sim.facilities,
                    sim.power.snapshot(
                        template.target_location_id, sim.facilities, sim.day
                    ),
                )
                blockers = tuple(
                    f"{failure.code}:{failure.detail}" for failure in failures
                )
            else:
                blockers = (
                    ()
                    if any(
                        not evaluate_site_requirements(
                            template.site_requirements,
                            node.id,
                            sim.day,
                            sim.environment,
                            sim.facilities,
                            sim.power.snapshot(node.id, sim.facilities, sim.day),
                        )
                        for node in sim.graph.nodes.values()
                    )
                    else ("site_requirements",)
                )
            rows.append(
                ContractRow(
                    str(state.id),
                    str(template.id),
                    template.display_name,
                    state.status.value,
                    state.deadline_day,
                    template.reward_musd,
                    target_location_id,
                    blockers,
                )
            )
        return ContractsView(tuple(rows))
