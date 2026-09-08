from __future__ import annotations

from .application_views import ContractRow, ContractsView
from .contracts import CargoContractTemplate
from .site import evaluate_site_requirements


class ContractProgressionProjectorMixin:
    def _contracts_view(self) -> ContractsView:
        sim = self._simulation
        if sim.contracts is None:
            return ContractsView(())
        rows = []
        for state in sorted(sim.contracts.contracts.values(), key=lambda row: str(row.id)):
            template = sim.contracts.templates[state.template_id]
            if isinstance(template, CargoContractTemplate):
                kind = "cargo"
                source_id = str(template.source_id)
                destination_id = str(template.destination_id)
                resource_id = str(template.resource_id)
                cargo_t = template.cargo_t
                target_location_id = None
                if state.cargo_order_id is not None:
                    blockers = sim.logistics.order_blockers(state.cargo_order_id, sim.day)
                elif state.status == "accepted":
                    blockers = ("dispatch_required",)
                else:
                    blockers = ()
            else:
                kind = "capability"
                source_id = destination_id = resource_id = None
                cargo_t = None
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
                            template.target_location_id,
                            sim.facilities,
                            sim.day,
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
                    kind,
                    state.status,
                    state.deadline_day,
                    template.reward_musd,
                    source_id,
                    destination_id,
                    resource_id,
                    cargo_t,
                    None if state.cargo_order_id is None else str(state.cargo_order_id),
                    target_location_id,
                    blockers,
                )
            )
        return ContractsView(tuple(rows))
