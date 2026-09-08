from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Mapping

from .application_views import ContractRow, ContractsView, ResearchRow, ResearchView, SurveyRow, SurveysView
from .contracts import CapabilityContractTemplate, CargoContractTemplate
from .shared import ContractId, DefinitionId, EntityId, ProjectId, RouteId, SpatialNodeId
from .site import evaluate_site_requirements


class ProgressionProjectorMixin:
    def _research_view(self) -> ResearchView:
        sim = self._simulation
        if sim.research is None:
            return ResearchView(0.0, ())
        power_by_location = {
            node.id: sim.power.snapshot(node.id, sim.facilities, sim.day)
            for node in sim.graph.nodes.values()
            if sim.facilities.all_at(node.id)
        }
        capacity = sim.research.research_capacity(power_by_location, sim.day)
        rows = []
        for definition in sorted(sim.research.definitions.values(), key=lambda d: str(d.id)):
            state = sim.research.active.get(definition.id)
            if definition.id in sim.research.completed:
                status = "complete"
            elif state is None:
                status = "available" if sim.research.can_start(definition.id) else "locked"
            else:
                status = state.status
            demonstration_location_id = None if state is None or state.demonstration_location_id is None else str(state.demonstration_location_id)
            demonstration_blockers: tuple[tuple[str, str], ...] = ()
            if state is not None and state.status == "demonstration":
                if state.paused:
                    demonstration_blockers = (("manual_pause", "研究が手動停止中"),)
                if state.demonstration_location_id is None:
                    demonstration_blockers = demonstration_blockers + (("demonstration_site", "実証地点が未選択"),)
                else:
                    demonstration_blockers = demonstration_blockers + tuple(
                        (f.code, f.detail)
                        for f in sim.research.demonstration_failures(definition.id, state.demonstration_location_id, sim.day)
                    )
            prototype_blockers: tuple[tuple[str, str], ...] = ()
            if state is not None and state.status == "prototype":
                if state.paused:
                    prototype_blockers = (("manual_pause", "研究が手動停止中"),)
                if state.prototype_location_id is None:
                    prototype_blockers = prototype_blockers + (("prototype_site", "試作地点が未選択"),)
                else:
                    prototype_blockers = prototype_blockers + tuple(
                        (f.code, f.detail)
                        for f in sim.research.prototype_failures(definition.id, state.prototype_location_id, sim.day)
                    )
            theory_blockers: tuple[tuple[str, str], ...] = ()
            if state is not None and state.paused:
                theory_blockers = (("manual_pause", "研究が手動停止中"),)
            if status == "theory" and sim.research.theory_capacity_for(definition.id, power_by_location, sim.day) <= 1e-12:
                theory_blockers = theory_blockers + ((
                    "research_site",
                    "研究設備と必要な環境・能力条件を同一地点で満たせない",
                ),)
            eligible_capacity = sim.research.theory_capacity_for(definition.id, power_by_location, sim.day)
            rows.append(ResearchRow(
                str(definition.id), definition.display_name, status, False if state is None else state.paused, sim.research.can_start(definition.id),
                0.0 if state is None else state.theory_done, definition.theory_points, eligible_capacity,
                0.0 if state is None else state.allocation_weight,
                tuple((str(k), v) for k, v in sorted(definition.prototype_resources.items(), key=lambda x: str(x[0]))),
                None if state is None or state.prototype_location_id is None else str(state.prototype_location_id),
                0 if state is None else state.demonstration_done_days, definition.demonstration_days,
                demonstration_location_id, demonstration_blockers, prototype_blockers, theory_blockers,
                tuple(sorted(str(x) for x in definition.prerequisites)),
            ))
        return ResearchView(capacity, tuple(rows))

    def _surveys_view(self, location_id: SpatialNodeId | None) -> SurveysView:
        sim = self._simulation
        if sim.survey is None:
            return SurveysView(())
        rows = []
        for (loc, resource_id), _target in sorted(sim.survey.targets.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
            if location_id is not None and loc != location_id:
                continue
            campaign = sim.survey.campaigns.get((loc, resource_id))
            power = sim.power.snapshot(loc, sim.facilities, sim.day)
            capacity = sim.survey.capacity_at(loc, power, sim.day)
            blockers: list[str] = []
            if campaign is not None:
                if campaign.paused:
                    blockers.append("manual_pause")
                if campaign.allocation_weight <= 1e-12:
                    blockers.append("allocation")
                if capacity <= 1e-12:
                    blockers.append("survey_capacity")
            visible_reserve = sim.survey.visible_reserve(loc, resource_id)
            if visible_reserve is not None and sim.extraction is not None:
                visible_reserve = sim.extraction.remaining_reserve_t.get((loc, resource_id), visible_reserve)
            rows.append(SurveyRow(
                str(loc), str(resource_id), self._resource_name(resource_id), campaign is not None,
                sim.survey.is_complete(loc, resource_id), False if campaign is None else campaign.paused,
                0.0 if campaign is None else campaign.progress, 0.0 if campaign is None else campaign.allocation_weight,
                sim.survey.knowledge_level(loc, resource_id), sim.survey.visible_presence_probability(loc, resource_id),
                sim.survey.visible_concentration(loc, resource_id), visible_reserve, capacity, tuple(blockers),
            ))
        return SurveysView(tuple(rows))

    def _contracts_view(self) -> ContractsView:
        sim = self._simulation
        if sim.contracts is None:
            return ContractsView(())
        rows = []
        for state in sorted(sim.contracts.contracts.values(), key=lambda c: str(c.id)):
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
                target_location_id = None if template.target_location_id is None else str(template.target_location_id)
                if template.target_location_id is not None:
                    failures = evaluate_site_requirements(
                        template.site_requirements, template.target_location_id, sim.day, sim.environment, sim.facilities,
                        sim.power.snapshot(template.target_location_id, sim.facilities, sim.day),
                    )
                    blockers = tuple(f"{f.code}:{f.detail}" for f in failures)
                else:
                    blockers = () if any(
                        not evaluate_site_requirements(
                            template.site_requirements, node.id, sim.day, sim.environment, sim.facilities,
                            sim.power.snapshot(node.id, sim.facilities, sim.day),
                        )
                        for node in sim.graph.nodes.values()
                    ) else ("site_requirements",)
            rows.append(ContractRow(
                str(state.id), str(template.id), template.display_name, kind, state.status, state.deadline_day,
                template.reward_musd, source_id, destination_id, resource_id, cargo_t,
                None if state.cargo_order_id is None else str(state.cargo_order_id), target_location_id, blockers,
            ))
        return ContractsView(tuple(rows))
