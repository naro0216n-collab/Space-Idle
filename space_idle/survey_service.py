from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from .facilities import FacilityBook
from .power import PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .service_capacity import ServiceCapacityScope
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .spatial import SpatialGraph
from .site import evaluate_site_requirements
from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    ServiceCapacityRequirement,
)
from .exploration_models import (
    KnowledgeLevel,
    KnowledgeRequirement,
    SurveyCoverage,
    SurveyProviderSourceKind,
    SurveyTarget,
    SurveyProviderSpec,
    SurveyObservationModeSpec,
    SurveyCampaign,
)
from .transport.models import FleetActivityRef

if TYPE_CHECKING:
    from .transport.service import TransportService


@dataclass
class SurveyService:
    DEFAULT_PRIORITY = DEFAULT_ACTIVITY_PRIORITY

    targets: dict[tuple[SurfaceCellId, DefinitionId], SurveyTarget]
    providers: dict[DefinitionId, SurveyProviderSpec]
    facilities: FacilityBook
    graph: SpatialGraph
    transport: "TransportService"
    knowledge_progress: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    knowledge_precision_fraction: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    campaigns: dict[tuple[SurfaceCellId, DefinitionId], SurveyCampaign] = field(default_factory=dict)

    @staticmethod
    def service_type_for_provider(provider_id: DefinitionId) -> str:
        return f"survey_observation:{provider_id}"

    @staticmethod
    def campaign_owner_id(cell_id: SurfaceCellId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"survey:{cell_id}:{resource_id}")

    @classmethod
    def fleet_commitment_id(cls, cell_id: SurfaceCellId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"fleet.commitment.{cls.campaign_owner_id(cell_id, resource_id)}")

    @staticmethod
    def execution_bundle_id(cell_id: SurfaceCellId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"execution.survey:{cell_id}:{resource_id}")

    def provider(self, provider_id: DefinitionId) -> SurveyProviderSpec:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown survey provider: {provider_id}") from exc

    def observation_mode(
        self, provider_id: DefinitionId, observation_mode_id: str
    ) -> SurveyObservationModeSpec:
        return self.provider(provider_id).observation_mode(observation_mode_id)

    def _mode_covers_target(
        self,
        provider_operational_node_id: SpatialNodeId,
        mode: SurveyObservationModeSpec,
        cell_id: SurfaceCellId,
    ) -> bool:
        if not self.graph.has_operational_node(provider_operational_node_id):
            return False
        target = self.graph.surface_cells.get(cell_id)
        if target is None:
            return False
        provider_node = self.graph.operational_node(provider_operational_node_id)
        if provider_node.body_id != target.body_id:
            return False
        if mode.coverage is SurveyCoverage.BODY_REMOTE:
            return True
        if mode.coverage is SurveyCoverage.LOCATION_TERRITORY:
            location = self.graph.locations.get(provider_operational_node_id)
            return location is not None and cell_id in location.developed_cell_ids
        return False

    def _mode_site_failures(
        self,
        provider_operational_node_id: SpatialNodeId,
        mode: SurveyObservationModeSpec,
        day: int,
    ) -> tuple[str, ...]:
        return tuple(
            f"site:{failure.code}:{failure.detail}"
            for failure in evaluate_site_requirements(
                mode.site_requirements,
                provider_operational_node_id,
                day,
                self.facilities.environment,
                self.facilities,
            )
        )

    def _source_capability_failures(
        self,
        provider: SurveyProviderSpec,
        mode: SurveyObservationModeSpec,
    ) -> tuple[str, ...]:
        required = set(mode.required_source_capabilities)
        if not required:
            return ()
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            definition = self.facilities.definitions.get(provider.source_definition_id)
            if definition is None:
                return ("unknown_provider_source",)
            available = {row.id for row in definition.capability_supplies}
        else:
            definition = self.transport.vehicle_definition(provider.source_definition_id)
            if definition is None:
                return ("unknown_provider_source",)
            available = set(definition.generic_capabilities)
        return tuple(f"source_capability:{item}" for item in sorted(required - available))

    def _facility_source_rows(
        self,
        provider: SurveyProviderSpec,
        operational_node_id: SpatialNodeId,
        *,
        active_only: bool,
        day: int,
    ):
        rows = (
            self.facilities.active_compatible_at(operational_node_id, day)
            if active_only
            else self.facilities.all_at(operational_node_id)
        )
        return tuple(row for row in rows if row.definition_id == provider.source_definition_id)

    def _facility_capacity(
        self,
        facility,
        provider: SurveyProviderSpec,
        power: PowerSnapshot | None,
        provider_factors: Mapping[EntityId, float] | None = None,
    ) -> float:
        utilization = 1.0 if power is None else power.utilization_by_facility.get(facility.id, 1.0)
        maintenance = 1.0 if power is None else power.maintenance_factor_by_facility.get(facility.id, 1.0)
        infrastructure = 1.0 if provider_factors is None else provider_factors.get(facility.id, 1.0)
        return provider.capacity_units_per_source_per_day * utilization * maintenance * infrastructure

    def _fleet_campaign_capacity(
        self,
        provider: SurveyProviderSpec,
        campaign: SurveyCampaign,
    ) -> float:
        if campaign.paused or campaign.fleet_commitment_ref is None:
            return 0.0
        commitment = self.transport.fleet_commitment(campaign.fleet_commitment_ref)
        if commitment is None or commitment.operational_node_id != campaign.provider_operational_node_id:
            return 0.0
        if commitment.vehicle_definition_id != provider.source_definition_id:
            return 0.0
        return commitment.quantity * provider.capacity_units_per_source_per_day

    def provider_capacity_at(
        self,
        provider_id: DefinitionId,
        provider_operational_node_id: SpatialNodeId,
        power: PowerSnapshot | None = None,
        day: int = 0,
        *,
        provider_factors: Mapping[EntityId, float] | None = None,
    ) -> float:
        provider = self.provider(provider_id)
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            return sum(
                self._facility_capacity(row, provider, power, provider_factors)
                for row in self._facility_source_rows(
                    provider, provider_operational_node_id, active_only=True, day=day
                )
            )
        return sum(
            self._fleet_campaign_capacity(provider, campaign)
            for campaign in self.campaigns.values()
            if campaign.provider_definition_id == provider_id
            and campaign.provider_operational_node_id == provider_operational_node_id
        )

    def reachable_knowledge_level(
        self,
        provider_operational_node_id: SpatialNodeId,
        provider_id: DefinitionId,
        observation_mode_id: str,
        cell_id: SurfaceCellId,
        *,
        day: int = 0,
    ) -> KnowledgeLevel:
        try:
            provider = self.provider(provider_id)
            mode = provider.observation_mode(observation_mode_id)
        except KeyError:
            return KnowledgeLevel.UNKNOWN
        if not self._mode_covers_target(provider_operational_node_id, mode, cell_id):
            return KnowledgeLevel.UNKNOWN
        if self._mode_site_failures(provider_operational_node_id, mode, day):
            return KnowledgeLevel.UNKNOWN
        if self._source_capability_failures(provider, mode):
            return KnowledgeLevel.UNKNOWN
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            if not self._facility_source_rows(
                provider, provider_operational_node_id, active_only=False, day=day
            ):
                return KnowledgeLevel.UNKNOWN
        else:
            definition = self.transport.vehicle_definition(provider.source_definition_id)
            if definition is None:
                return KnowledgeLevel.UNKNOWN
        return mode.max_knowledge_level

    def start_blockers(
        self,
        provider_operational_node_id: SpatialNodeId,
        provider_id: DefinitionId,
        observation_mode_id: str,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        target_knowledge_level: KnowledgeLevel,
        day: int = 0,
    ) -> tuple[str, ...]:
        key = (cell_id, resource_id)
        if key not in self.targets:
            return ("unknown_target",)
        if key in self.campaigns:
            return ("already_active",)
        if not self.graph.has_operational_node(provider_operational_node_id):
            return ("unknown_provider_location",)
        try:
            provider = self.provider(provider_id)
            mode = provider.observation_mode(observation_mode_id)
        except KeyError:
            return ("unknown_provider_or_mode",)
        try:
            target_level = KnowledgeLevel(target_knowledge_level)
        except ValueError:
            return ("invalid_target_knowledge_level",)
        if target_level is KnowledgeLevel.UNKNOWN:
            return ("invalid_target_knowledge_level",)
        provider_body = self.graph.operational_node(provider_operational_node_id).body_id
        target_body = self.graph.surface_cells[cell_id].body_id
        if provider_body != target_body:
            return ("different_body",)
        failures: list[str] = []
        if not self._mode_covers_target(provider_operational_node_id, mode, cell_id):
            failures.append("survey_coverage")
        failures.extend(self._mode_site_failures(provider_operational_node_id, mode, day))
        failures.extend(self._source_capability_failures(provider, mode))
        current = self.knowledge_level(cell_id, resource_id)
        if current >= target_level:
            failures.append("knowledge_goal_reached")
        if target_level > mode.max_knowledge_level:
            failures.append("survey_provider_limit")
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            if not self._facility_source_rows(
                provider, provider_operational_node_id, active_only=False, day=day
            ):
                failures.append("survey_provider")
        else:
            if self.transport.vehicle_definition(provider.source_definition_id) is None:
                failures.append("unknown_provider_source")
            elif self.transport.fleet_free_units(
                provider.source_definition_id, provider_operational_node_id
            ) < mode.required_fleet_units:
                failures.append("fleet_units")
        return tuple(dict.fromkeys(failures))

    def can_start(self, *args, **kwargs) -> bool:
        return not self.start_blockers(*args, **kwargs)

    def start(
        self,
        provider_operational_node_id: SpatialNodeId,
        provider_id: DefinitionId,
        observation_mode_id: str,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        target_knowledge_level: KnowledgeLevel,
        *,
        priority: ActivityPriority = DEFAULT_PRIORITY,
        day: int = 0,
    ) -> None:
        blockers = self.start_blockers(
            provider_operational_node_id,
            provider_id,
            observation_mode_id,
            cell_id,
            resource_id,
            target_knowledge_level,
            day,
        )
        if blockers:
            raise ValueError("; ".join(blockers))
        provider = self.provider(provider_id)
        mode = provider.observation_mode(observation_mode_id)
        commitment_id: EntityId | None = None
        if provider.source_kind is SurveyProviderSourceKind.FLEET:
            commitment_id = self.fleet_commitment_id(cell_id, resource_id)
            self.transport.commit_fleet_units(
                commitment_id,
                FleetActivityRef("survey", self.campaign_owner_id(cell_id, resource_id)),
                provider.source_definition_id,
                provider_operational_node_id,
                mode.required_fleet_units,
            )
        self.campaigns[(cell_id, resource_id)] = SurveyCampaign(
            provider_id,
            observation_mode_id,
            provider_operational_node_id,
            cell_id,
            resource_id,
            target_knowledge_level,
            priority,
            False,
            commitment_id,
        )

    def pause_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        campaign = self.campaigns.get((cell_id, resource_id))
        if campaign is None:
            return ("not_active",)
        if campaign.paused:
            return ("already_paused",)
        return ()

    def can_pause(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.pause_blockers(cell_id, resource_id)

    def pause(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        blockers = self.pause_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(cell_id, resource_id)].paused = True

    def resume_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        campaign = self.campaigns.get((cell_id, resource_id))
        if campaign is None:
            return ("not_active",)
        if not campaign.paused:
            return ("not_paused",)
        provider = self.provider(campaign.provider_definition_id)
        mode = provider.observation_mode(campaign.observation_mode_id)
        if provider.source_kind is SurveyProviderSourceKind.FLEET and campaign.fleet_commitment_ref is None:
            if self.transport.fleet_free_units(
                provider.source_definition_id, campaign.provider_operational_node_id
            ) < mode.required_fleet_units:
                return ("fleet_units",)
        return ()

    def can_resume(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.resume_blockers(cell_id, resource_id)

    def resume(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        blockers = self.resume_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        campaign = self.campaigns[(cell_id, resource_id)]
        provider = self.provider(campaign.provider_definition_id)
        mode = provider.observation_mode(campaign.observation_mode_id)
        if provider.source_kind is SurveyProviderSourceKind.FLEET and campaign.fleet_commitment_ref is None:
            commitment_id = self.fleet_commitment_id(cell_id, resource_id)
            self.transport.commit_fleet_units(
                commitment_id,
                FleetActivityRef("survey", self.campaign_owner_id(cell_id, resource_id)),
                provider.source_definition_id,
                campaign.provider_operational_node_id,
                mode.required_fleet_units,
            )
            campaign.fleet_commitment_ref = commitment_id
        campaign.paused = False

    def settle_boundary(self, day: int = 0) -> None:
        for campaign in self.campaigns.values():
            if not campaign.paused or campaign.fleet_commitment_ref is None:
                continue
            commitment = self.transport.fleet_commitment(campaign.fleet_commitment_ref)
            if commitment is None:
                campaign.fleet_commitment_ref = None
                continue
            if commitment.operational_node_id is None:
                continue
            self.transport.release_fleet_commitment(campaign.fleet_commitment_ref, day=day)
            campaign.fleet_commitment_ref = None

    def priority_blockers(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> tuple[str, ...]:
        return () if (cell_id, resource_id) in self.campaigns else ("not_active",)

    def can_set_priority(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return not self.priority_blockers(cell_id, resource_id)

    def set_priority(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId, priority: ActivityPriority
    ) -> None:
        blockers = self.priority_blockers(cell_id, resource_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[(cell_id, resource_id)].priority = ActivityPriority(priority)

    def progress(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        key = (cell_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        return self.knowledge_progress.get(key, 0.0)

    def knowledge_level(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> KnowledgeLevel:
        key = (cell_id, resource_id)
        target = self.targets[key]
        progress = self.knowledge_progress.get(key, 0.0)
        level = KnowledgeLevel.UNKNOWN
        for index, threshold in enumerate(target.thresholds, start=1):
            if progress + 1e-9 >= threshold:
                level = KnowledgeLevel(index)
        return level

    def knowledge_requirement_failures(self, requirement: KnowledgeRequirement) -> tuple[str, ...]:
        key = (requirement.target_cell_id, requirement.subject_resource_id)
        if key not in self.targets:
            return ("knowledge_target_unknown",)
        actual = self.knowledge_level(*key)
        if actual < requirement.minimum_level:
            return (
                f"knowledge:{requirement.target_cell_id}:{requirement.subject_resource_id}:"
                f"{int(actual)}/{int(requirement.minimum_level)}",
            )
        return ()

    def initialize_known(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> None:
        key = (cell_id, resource_id)
        if key not in self.targets:
            raise KeyError(key)
        self.knowledge_progress[key] = max(
            self.knowledge_progress.get(key, 0.0), self.targets[key].thresholds[-1]
        )
        self.knowledge_precision_fraction[key] = 0.0
        self.campaigns.pop(key, None)

    def is_complete(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return self.knowledge_level(cell_id, resource_id) >= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL

    def actual_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        if (cell_id, resource_id) not in self.targets:
            raise KeyError((cell_id, resource_id))
        return float(self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0))

    def visible_presence_probability(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> float | None:
        if self.knowledge_level(cell_id, resource_id) < KnowledgeLevel.PRESENCE_PROBABILITY:
            return None
        return self.targets[(cell_id, resource_id)].prior_presence_probability

    def visible_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float | None:
        if self.knowledge_level(cell_id, resource_id) < KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return None
        return self.actual_potential(cell_id, resource_id)

    def visible_potential_precision_fraction(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> float | None:
        if self.knowledge_level(cell_id, resource_id) < KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return None
        return self.knowledge_precision_fraction.get((cell_id, resource_id))

    def capacity_for_campaign(
        self,
        campaign: SurveyCampaign,
        power: PowerSnapshot | None = None,
        day: int = 0,
    ) -> float:
        mode = self.observation_mode(campaign.provider_definition_id, campaign.observation_mode_id)
        if not self._mode_covers_target(campaign.provider_operational_node_id, mode, campaign.cell_id):
            return 0.0
        return self.provider_capacity_at(
            campaign.provider_definition_id,
            campaign.provider_operational_node_id,
            power,
            day,
        ) * mode.survey_rate

    def blockers(
        self,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        power: PowerSnapshot | None = None,
        day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[str, ...]:
        campaign = self.campaigns.get((cell_id, resource_id))
        if campaign is None:
            return ()
        blockers: list[str] = []
        if campaign.paused:
            blockers.append("manual_pause")
        provider = self.provider(campaign.provider_definition_id)
        mode = provider.observation_mode(campaign.observation_mode_id)
        if self._mode_site_failures(campaign.provider_operational_node_id, mode, day):
            blockers.append("survey_site")
        if self.capacity_for_campaign(campaign, power, day) <= 1e-12 and not campaign.paused:
            blockers.append("survey_capacity")
        if execution_allocations is not None and not campaign.paused:
            try:
                allocated = execution_allocations.allocated(self.execution_bundle_id(cell_id, resource_id))
            except KeyError:
                allocated = 0.0
            if allocated <= 1e-12:
                blockers.append("service_capacity")
        return tuple(dict.fromkeys(blockers))

    def execution_requirement_bundles(self, day: int = 0) -> tuple[ExecutionRequirementBundle, ...]:
        bundles: list[ExecutionRequirementBundle] = []
        for key, campaign in sorted(
            self.campaigns.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
        ):
            if campaign.paused:
                continue
            mode = self.observation_mode(campaign.provider_definition_id, campaign.observation_mode_id)
            if self.knowledge_level(*key) >= campaign.target_knowledge_level:
                continue
            threshold = self.targets[key].thresholds[int(campaign.target_knowledge_level) - 1]
            remaining_progress = max(0.0, threshold - self.knowledge_progress.get(key, 0.0))
            requested_capacity = remaining_progress / mode.survey_rate
            if requested_capacity <= 1e-12:
                continue
            bundles.append(
                ExecutionRequirementBundle(
                    self.execution_bundle_id(*key),
                    "survey",
                    self.campaign_owner_id(*key),
                    "survey_observation",
                    campaign.provider_operational_node_id,
                    requested_capacity,
                    campaign.priority,
                    (
                        ServiceCapacityRequirement(
                            self.service_type_for_provider(campaign.provider_definition_id), 1.0
                        ),
                    ),
                )
            )
        return tuple(bundles)

    def service_capacity_types(self) -> tuple[str, ...]:
        return tuple(self.service_type_for_provider(provider_id) for provider_id in sorted(self.providers, key=str))

    def _provider_id_for_service_type(self, service_type: str) -> DefinitionId:
        prefix = "survey_observation:"
        if not service_type.startswith(prefix):
            raise KeyError(service_type)
        provider_id = DefinitionId(service_type[len(prefix):])
        if provider_id not in self.providers:
            raise KeyError(service_type)
        return provider_id

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        self._provider_id_for_service_type(service_type)
        return ServiceCapacityScope.OPERATIONAL_NODE

    def service_capacity_provider_definition_ids(self, service_type: str) -> frozenset[DefinitionId]:
        provider = self.provider(self._provider_id_for_service_type(service_type))
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            return frozenset((provider.source_definition_id,))
        return frozenset()

    def service_capacity_upstream_services(self, service_type: str) -> frozenset[str]:
        self._provider_id_for_service_type(service_type)
        return frozenset()

    def service_capacity_supply_at(
        self,
        operational_node_id: SpatialNodeId,
        service_type: str,
        facilities: FacilityBook,
        power: PowerSnapshot | None,
        day: int = 0,
        *,
        provider_factors: Mapping[EntityId, float] | None = None,
    ) -> tuple[float, float]:
        if facilities is not self.facilities:
            raise ValueError("survey service provider requires its owning FacilityBook")
        provider_id = self._provider_id_for_service_type(service_type)
        provider = self.provider(provider_id)
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            nominal = sum(
                provider.capacity_units_per_source_per_day
                for _ in self._facility_source_rows(provider, operational_node_id, active_only=False, day=day)
            )
            enabled = sum(
                self._facility_capacity(row, provider, power, provider_factors)
                for row in self._facility_source_rows(provider, operational_node_id, active_only=True, day=day)
            )
            return (nominal, enabled)
        enabled = sum(
            self._fleet_campaign_capacity(provider, campaign)
            for campaign in self.campaigns.values()
            if campaign.provider_definition_id == provider_id
            and campaign.provider_operational_node_id == operational_node_id
        )
        return (enabled, enabled)

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan,
        day: int = 0,
    ) -> None:
        completed: list[tuple[SurfaceCellId, DefinitionId]] = []
        for key, campaign in sorted(
            self.campaigns.items(), key=lambda row: (-int(row[1].priority), str(row[0][0]), str(row[0][1]))
        ):
            if campaign.paused:
                continue
            if self.knowledge_level(*key) >= campaign.target_knowledge_level:
                completed.append(key)
                continue
            try:
                allocated_capacity = execution_allocations.allocated(self.execution_bundle_id(*key))
            except KeyError:
                allocated_capacity = 0.0
            if allocated_capacity <= 1e-12:
                continue
            mode = self.observation_mode(campaign.provider_definition_id, campaign.observation_mode_id)
            threshold = self.targets[key].thresholds[int(campaign.target_knowledge_level) - 1]
            before_level = self.knowledge_level(*key)
            current = self.knowledge_progress.get(key, 0.0)
            gain = min(allocated_capacity * mode.survey_rate, max(0.0, threshold - current))
            if gain <= 1e-12:
                continue
            self.knowledge_progress[key] = min(threshold, current + gain)
            after_level = self.knowledge_level(*key)
            if after_level >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL and after_level > before_level:
                precision = mode.precision_for_level(after_level)
                if precision is not None:
                    prior = self.knowledge_precision_fraction.get(key)
                    self.knowledge_precision_fraction[key] = precision if prior is None else min(prior, precision)
            if after_level >= campaign.target_knowledge_level:
                completed.append(key)
        for key in completed:
            campaign = self.campaigns.get(key)
            if campaign is None:
                continue
            if campaign.fleet_commitment_ref is not None:
                commitment = self.transport.fleet_commitment(campaign.fleet_commitment_ref)
                if commitment is not None and commitment.operational_node_id is not None:
                    self.transport.release_fleet_commitment(campaign.fleet_commitment_ref, day=day)
            self.campaigns.pop(key, None)
