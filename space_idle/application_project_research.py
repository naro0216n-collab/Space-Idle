from __future__ import annotations

from .application_views import ResearchProviderRow, ResearchRow, ResearchView
from .app_contracts.progression_views import ResearchSiteOptionRow


class ResearchProgressionProjectorMixin:
    def _research_site_options(
        self,
        definition,
        *,
        demonstration: bool,
    ) -> tuple[ResearchSiteOptionRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchSiteOptionRow] = []
        for node in sim.graph.operational_nodes():
            blockers = (
                sim.research.demonstration_site_blockers(definition.id, node.id, sim.day)
                if demonstration
                else sim.research.prototype_site_blockers(definition.id, node.id, sim.day)
            )
            rows.append(ResearchSiteOptionRow(
                str(node.id),
                blockers,
                (
                    sim.research.can_select_demonstration_site(definition.id, node.id, sim.day)
                    if demonstration
                    else sim.research.can_select_prototype_site(definition.id, node.id, sim.day)
                ),
            ))
        return tuple(rows)

    def _research_provider_rows(self, power_by_location) -> tuple[ResearchProviderRow, ...]:
        sim = self._simulation
        if sim.research is None:
            return ()
        rows: list[ResearchProviderRow] = []
        for facility in sorted(sim.facilities.facilities.values(), key=lambda row: str(row.id)):
            provider = sim.research.providers.get(facility.definition_id)
            if provider is None:
                continue
            blockers = list(sim.facilities.activation_failures(facility, sim.day))
            snapshot = power_by_location.get(facility.location_id)
            if snapshot is None:
                snapshot = sim.power.snapshot(facility.location_id, sim.facilities, sim.day)
            utilization = max(
                0.0,
                min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)),
            )
            if not blockers and utilization <= 1e-12:
                blockers.append(("power", "研究設備への電力供給なし"))
            rows.append(ResearchProviderRow(
                str(facility.id),
                str(facility.definition_id),
                str(facility.location_id),
                provider.tier,
                facility.level,
                sim.research.provider_generation(facility.id, power_by_location, sim.day),
                sim.research.provider_storage_capacity(facility.id, power_by_location, sim.day),
                tuple(blockers),
            ))
        return tuple(rows)

    def _research_view(self) -> ResearchView:
        sim = self._simulation
        if sim.research is None:
            return ResearchView(0.0, 0.0, 0.0, False, (), ())
        power_by_location = {
            node.id: sim.power.snapshot(node.id, sim.facilities, sim.day)
            for node in sim.graph.operational_nodes()
            if sim.facilities.all_at(node.id)
        }
        generation = sim.research.generation_rate(power_by_location, sim.day)
        capacity = sim.research.storage_capacity(power_by_location, sim.day)
        providers = self._research_provider_rows(power_by_location)
        rows: list[ResearchRow] = []
        for definition in sorted(sim.research.definitions.values(), key=lambda row: str(row.id)):
            state = sim.research.active.get(definition.id)
            complete = definition.id in sim.research.completed
            start_blockers = sim.research.start_blockers(
                definition.id,
                day=sim.day,
                power_by_location=power_by_location,
            )
            if complete:
                status = "complete"
            elif state is None:
                status = "available" if definition.prerequisites.issubset(sim.research.completed) else "locked"
            else:
                status = state.status.value

            prototype = definition.prototype
            demonstration = definition.demonstration
            demonstration_location_id = (
                None if state is None or state.demonstration_location_id is None
                else str(state.demonstration_location_id)
            )
            demonstration_blockers = (
                sim.research.demonstration_blockers(definition.id, sim.day)
                if state is not None and state.status.value == "demonstration"
                else ()
            )
            prototype_blockers = (
                sim.research.prototype_blockers(definition.id, sim.day)
                if state is not None and state.status.value == "prototype"
                else ()
            )
            current_blockers = sim.research.current_blockers(
                definition.id, day=sim.day, power_by_location=power_by_location
            )

            demonstration_required = 0 if demonstration is None else demonstration.days
            demonstration_done = (
                demonstration_required
                if complete
                else (0 if state is None else state.demonstration_done_days)
            )
            prototype_sites = (
                self._research_site_options(definition, demonstration=False)
                if status == "prototype" else ()
            )
            demonstration_sites = (
                self._research_site_options(definition, demonstration=True)
                if status == "demonstration" else ()
            )
            prototype_resources = () if prototype is None else tuple(
                (str(resource_id), amount)
                for resource_id, amount in sorted(prototype.resources.items(), key=lambda row: str(row[0]))
            )
            rows.append(ResearchRow(
                str(definition.id),
                definition.display_name,
                status,
                False if state is None else state.paused,
                not start_blockers,
                sim.research.can_pause(definition.id),
                sim.research.can_resume(definition.id),
                (
                    sim.research.can_fund_prototype(definition.id, sim.day)
                    if state is not None and state.status.value == "prototype"
                    else False
                ),
                definition.research_point_cost,
                current_blockers,
                start_blockers,
                prototype_resources,
                None if state is None or state.prototype_location_id is None
                else str(state.prototype_location_id),
                prototype_sites,
                demonstration_done,
                demonstration_required,
                demonstration_location_id,
                demonstration_sites,
                demonstration_blockers,
                prototype_blockers,
                tuple(sorted(str(item) for item in definition.prerequisites)),
            ))
        return ResearchView(
            sim.research.stored_points,
            capacity,
            generation,
            sim.research.stored_points > capacity + 1e-9,
            providers,
            tuple(rows),
        )
