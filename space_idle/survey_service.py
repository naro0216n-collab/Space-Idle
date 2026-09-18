from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
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
    SurveyReachScope,
    SurveyProviderSourceKind,
    SurveyTarget,
    SurveyProviderSpec,
    SurveyObservationModeSpec,
    SurveyCampaign,
    SurveyCampaignControlState,
    SurveyProviderConstraint,
    SurveyProviderAssignmentState,
)
from .transport.models import FleetActivityRef

if TYPE_CHECKING:
    from .transport.service import TransportService


@dataclass(frozen=True)
class SurveyProviderModeCandidate:
    provider_definition_id: DefinitionId
    provider_operational_node_id: SpatialNodeId
    observation_mode_id: str
    source_kind: SurveyProviderSourceKind
    source_definition_id: DefinitionId
    survey_rate: float
    max_knowledge_level: KnowledgeLevel
    estimate_uncertainty_fraction: float
    measurement_precision_fraction: float
    minimum_source_units: int
    assigned_source_units: int
    capacity_units_per_day: float
    blockers: tuple[str, ...]

    @property
    def viable(self) -> bool:
        return not self.blockers


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
    estimated_potential: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    campaigns: dict[EntityId, SurveyCampaign] = field(default_factory=dict)
    provider_assignments: dict[EntityId, SurveyProviderAssignmentState] = field(default_factory=dict)
    _campaign_counter: int = 0
    _provider_assignment_counter: int = 0

    @staticmethod
    def service_type_for_provider(provider_id: DefinitionId) -> str:
        return f"survey_observation:{provider_id}"

    @staticmethod
    def campaign_owner_id(campaign_id: EntityId) -> EntityId:
        return campaign_id

    @staticmethod
    def provider_assignment_commitment_id(assignment_id: EntityId) -> EntityId:
        return EntityId(f"fleet.commitment.survey_provider:{assignment_id}")

    @staticmethod
    def execution_bundle_id(
        campaign_id: EntityId, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"execution.survey:{campaign_id}:{cell_id}:{resource_id}")

    def provider(self, provider_id: DefinitionId) -> SurveyProviderSpec:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown survey provider: {provider_id}") from exc

    def observation_mode(
        self, provider_id: DefinitionId, observation_mode_id: str
    ) -> SurveyObservationModeSpec:
        return self.provider(provider_id).observation_mode(observation_mode_id)

    def _mode_reach_failures(
        self,
        provider: SurveyProviderSpec,
        provider_operational_node_id: SpatialNodeId,
        mode: SurveyObservationModeSpec,
        cell_id: SurfaceCellId,
        day: int,
    ) -> tuple[str, ...]:
        if not self.graph.has_operational_node(provider_operational_node_id):
            return ("unknown_provider_location",)
        if cell_id not in self.graph.surface_cells:
            return ("unknown_target",)
        reach = mode.reach
        failures: list[str] = []
        provider_body = self.graph.context_body_id(provider_operational_node_id)
        target_body = self.graph.context_body_id(cell_id)
        if reach.scope is SurveyReachScope.SAME_BODY and provider_body != target_body:
            failures.append("reach:body")
        elif reach.scope is SurveyReachScope.SAME_SYSTEM:
            if self.graph.context_star_system_id(provider_operational_node_id) != self.graph.context_star_system_id(cell_id):
                failures.append("reach:star_system")
        elif reach.scope is SurveyReachScope.LOCATION_TERRITORY:
            location = self.graph.locations.get(provider_operational_node_id)
            if location is None or cell_id not in location.developed_cell_ids:
                failures.append("reach:location_territory")
        separation = self.graph.characteristic_transport_separation(
            provider_operational_node_id, cell_id
        )
        if (
            reach.max_characteristic_distance_km is not None
            and separation.distance_km > reach.max_characteristic_distance_km + 1e-9
        ):
            failures.append("reach:distance")
        if (
            reach.max_characteristic_delta_v_km_s is not None
            and separation.delta_v_km_s > reach.max_characteristic_delta_v_km_s + 1e-9
        ):
            failures.append("reach:delta_v")
        if reach.required_operation_types:
            if provider.source_kind is not SurveyProviderSourceKind.FLEET:
                failures.append("reach:movement_source")
            else:
                try:
                    plan = self.transport.movement_plan_to_physical_target_for_vehicle(
                        provider_operational_node_id, cell_id, provider.source_definition_id,
                        payload_t_per_unit=0.0, day=day,
                    )
                except (KeyError, ValueError):
                    failures.append("reach:movement_plan")
                else:
                    present = {operation.operation_type for operation in plan.operations}
                    failures.extend(
                        f"reach:operation:{operation_type}"
                        for operation_type in sorted(reach.required_operation_types - present)
                    )
        return tuple(failures)

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

    def provider_assignment_quantity(self, assignment_id: EntityId) -> int:
        assignment = self.provider_assignments[assignment_id]
        commitment = self.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref)
        if commitment is None:
            raise RuntimeError(f"Survey Provider assignment lost Fleet commitment: {assignment_id}")
        return commitment.quantity

    def provider_assignment_for(
        self,
        provider_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId | None = None,
    ) -> SurveyProviderAssignmentState | None:
        rows = [
            row for row in self.provider_assignments.values()
            if row.provider_definition_id == provider_id
            and row.operational_node_id == operational_node_id
            and (vehicle_definition_id is None or row.vehicle_definition_id == vehicle_definition_id)
        ]
        if len(rows) > 1:
            raise RuntimeError(f"duplicate Survey Provider assignment: {provider_id}@{operational_node_id}")
        return rows[0] if rows else None

    def set_provider_fleet_quantity(
        self,
        provider_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        vehicle_definition_id: DefinitionId,
        quantity: int,
        *,
        day: int = 0,
    ) -> EntityId | None:
        provider = self.provider(provider_id)
        if provider.source_kind is not SurveyProviderSourceKind.FLEET:
            raise ValueError("Survey Provider fleet quantity requires a Fleet-backed provider")
        if provider.source_definition_id != vehicle_definition_id:
            raise ValueError("Survey Provider vehicle does not match provider definition")
        if not self.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        if quantity < 0:
            raise ValueError("Survey Provider fleet quantity must be non-negative")
        assignment = self.provider_assignment_for(
            provider_id, operational_node_id, vehicle_definition_id
        )
        if quantity == 0:
            if assignment is not None:
                self.release_provider_assignment(assignment.id, day=day)
            return None
        if assignment is not None:
            self.resize_provider_assignment(assignment.id, quantity)
            return assignment.id
        return self.create_provider_assignment(provider_id, operational_node_id, quantity)

    def create_provider_assignment(
        self, provider_id: DefinitionId, operational_node_id: SpatialNodeId, quantity: int
    ) -> EntityId:
        provider = self.provider(provider_id)
        if provider.source_kind is not SurveyProviderSourceKind.FLEET:
            raise ValueError("Survey Provider assignment requires a Fleet-backed provider")
        if not self.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        if quantity <= 0:
            raise ValueError("Survey Provider assignment quantity must be positive")
        if self.provider_assignment_for(provider_id, operational_node_id) is not None:
            raise ValueError("Survey Provider assignment already exists at operational node")
        next_counter = self._provider_assignment_counter + 1
        assignment_id = EntityId(f"survey.provider_assignment.{next_counter}")
        commitment_id = self.provider_assignment_commitment_id(assignment_id)
        self.transport.commit_fleet_units(
            commitment_id,
            FleetActivityRef("survey_provider_assignment", assignment_id),
            provider.source_definition_id, operational_node_id, quantity,
        )
        self.provider_assignments[assignment_id] = SurveyProviderAssignmentState(
            assignment_id, provider_id, provider.source_definition_id,
            operational_node_id, commitment_id,
        )
        self._provider_assignment_counter = next_counter
        return assignment_id

    def resize_provider_assignment(self, assignment_id: EntityId, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Survey Provider assignment quantity must be positive")
        assignment = self.provider_assignments[assignment_id]
        self.transport.resize_fleet_commitment(assignment.fleet_commitment_ref, quantity)

    def release_provider_assignment(self, assignment_id: EntityId, *, day: int = 0) -> None:
        assignment = self.provider_assignments[assignment_id]
        self.transport.release_fleet_commitment(assignment.fleet_commitment_ref, day=day)
        del self.provider_assignments[assignment_id]

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
        assignment = self.provider_assignment_for(provider_id, provider_operational_node_id)
        if assignment is None:
            return 0.0
        return self.provider_assignment_quantity(assignment.id) * provider.capacity_units_per_source_per_day

    def _provider_mode_eligibility_failures(
        self, provider_operational_node_id: SpatialNodeId, provider: SurveyProviderSpec,
        mode: SurveyObservationModeSpec, cell_id: SurfaceCellId, day: int,
    ) -> tuple[str, ...]:
        failures: list[str] = []
        failures.extend(self._mode_reach_failures(
            provider, provider_operational_node_id, mode, cell_id, day
        ))
        failures.extend(self._mode_site_failures(provider_operational_node_id, mode, day))
        failures.extend(self._source_capability_failures(provider, mode))
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            source_count = len(self._facility_source_rows(
                provider, provider_operational_node_id, active_only=True, day=day
            ))
        else:
            assignment = self.provider_assignment_for(provider.id, provider_operational_node_id)
            source_count = 0 if assignment is None else self.provider_assignment_quantity(assignment.id)
        if source_count < mode.minimum_source_units:
            failures.append(f"source_units:{source_count}/{mode.minimum_source_units}")
        return tuple(dict.fromkeys(failures))

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
        if self._provider_mode_eligibility_failures(
            provider_operational_node_id, provider, mode, cell_id, day
        ):
            return KnowledgeLevel.UNKNOWN
        return mode.max_knowledge_level

    def _provider_context_ids(self, provider: SurveyProviderSpec) -> tuple[SpatialNodeId, ...]:
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            return tuple(sorted((
                node_id for node_id in self.graph.operational_node_states
                if any(row.definition_id == provider.source_definition_id for row in self.facilities.all_at(node_id))
            ), key=str))
        return tuple(sorted({
            row.operational_node_id for row in self.provider_assignments.values()
            if row.provider_definition_id == provider.id
        }, key=str))

    def unfinished_targets(self, campaign: SurveyCampaign) -> tuple[tuple[SurfaceCellId, DefinitionId], ...]:
        return tuple(
            key for key in campaign.target_pairs()
            if key in self.targets and self.knowledge_level(*key) < campaign.goal_knowledge_level
        )

    def _candidate_source_units(self, provider: SurveyProviderSpec, operational_node_id: SpatialNodeId, day: int) -> int:
        if provider.source_kind is SurveyProviderSourceKind.FACILITY:
            return len(self._facility_source_rows(provider, operational_node_id, active_only=True, day=day))
        assignment = self.provider_assignment_for(provider.id, operational_node_id)
        return 0 if assignment is None else self.provider_assignment_quantity(assignment.id)

    def campaign_candidates(self, campaign: SurveyCampaign, *, day: int = 0) -> tuple[SurveyProviderModeCandidate, ...]:
        unfinished = self.unfinished_targets(campaign)
        rows: list[SurveyProviderModeCandidate] = []
        for provider in sorted(self.providers.values(), key=lambda row: str(row.id)):
            for node_id in self._provider_context_ids(provider):
                for mode in sorted(provider.observation_modes, key=lambda row: row.id):
                    blockers: list[str] = []
                    if campaign.goal_knowledge_level > mode.max_knowledge_level:
                        blockers.append("survey_provider_limit")
                    for cell_id, _resource_id in unfinished:
                        blockers.extend(self._provider_mode_eligibility_failures(node_id, provider, mode, cell_id, day))
                    source_units = self._candidate_source_units(provider, node_id, day)
                    capacity_units = self.provider_capacity_at(provider.id, node_id, None, day)
                    rows.append(SurveyProviderModeCandidate(
                        provider.id, node_id, mode.id, provider.source_kind, provider.source_definition_id,
                        mode.survey_rate, mode.max_knowledge_level, mode.estimate_uncertainty_fraction,
                        mode.measurement_precision_fraction, mode.minimum_source_units, source_units,
                        capacity_units, tuple(dict.fromkeys(blockers)),
                    ))
        return tuple(rows)

    @staticmethod
    def _candidate_stable_key(candidate: SurveyProviderModeCandidate) -> tuple[str, str, str]:
        return (str(candidate.provider_definition_id), str(candidate.provider_operational_node_id), candidate.observation_mode_id)

    def _candidate_strategic_signature(self, candidate: SurveyProviderModeCandidate) -> tuple[object, ...]:
        provider = self.provider(candidate.provider_definition_id)
        mode = provider.observation_mode(candidate.observation_mode_id)
        return (
            candidate.source_kind.value, str(candidate.source_definition_id),
            str(candidate.provider_operational_node_id), candidate.survey_rate,
            int(candidate.max_knowledge_level), candidate.estimate_uncertainty_fraction,
            candidate.measurement_precision_fraction, candidate.minimum_source_units,
            candidate.assigned_source_units, candidate.capacity_units_per_day,
            mode.reach, mode.site_requirements, tuple(sorted(mode.required_source_capabilities)),
        )

    def candidate_matches_constraints(self, campaign: SurveyCampaign, candidate: SurveyProviderModeCandidate) -> bool:
        if campaign.provider_constraint is not None:
            constraint = campaign.provider_constraint
            if (candidate.provider_definition_id != constraint.provider_definition_id
                    or candidate.provider_operational_node_id != constraint.operational_node_id):
                return False
        if campaign.observation_mode_constraint is not None and candidate.observation_mode_id != campaign.observation_mode_constraint:
            return False
        return True

    def resolve_campaign_candidate(self, campaign: SurveyCampaign, *, day: int = 0) -> tuple[SurveyProviderModeCandidate | None, tuple[str, ...]]:
        if not self.unfinished_targets(campaign):
            return None, ()
        matching = tuple(candidate for candidate in self.campaign_candidates(campaign, day=day) if self.candidate_matches_constraints(campaign, candidate))
        if not matching:
            if campaign.provider_constraint is not None or campaign.observation_mode_constraint is not None:
                return None, ("survey_constraint_unavailable",)
            return None, ("survey_candidate_unavailable",)
        viable = tuple(candidate for candidate in matching if candidate.viable)
        if not viable:
            blockers = ["survey_candidate_unavailable"]
            for candidate in matching:
                blockers.extend(f"survey_eligibility:{item}" for item in candidate.blockers)
            return None, tuple(dict.fromkeys(blockers))
        if len(viable) == 1:
            return viable[0], ()
        signatures = {self._candidate_strategic_signature(candidate) for candidate in viable}
        if len(signatures) == 1:
            return min(viable, key=self._candidate_stable_key), ()
        return None, ("survey_decision_required",)

    def _campaign_intent_blockers(
        self, target_cell_ids: tuple[SurfaceCellId, ...], resource_ids: tuple[DefinitionId, ...],
        goal_knowledge_level: KnowledgeLevel, provider_constraint: SurveyProviderConstraint | None,
        observation_mode_constraint: str | None, *, exclude_campaign_id: EntityId | None = None,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        try:
            goal = KnowledgeLevel(goal_knowledge_level)
        except ValueError:
            return ("invalid_target_knowledge_level",)
        if goal is KnowledgeLevel.UNKNOWN:
            blockers.append("invalid_target_knowledge_level")
        cells = tuple(sorted(set(target_cell_ids), key=str))
        resources = tuple(sorted(set(resource_ids), key=str))
        if not cells:
            blockers.append("survey_scope_empty")
        if not resources:
            blockers.append("survey_resource_scope_empty")
        for cell_id in cells:
            if cell_id not in self.graph.surface_cells:
                blockers.append(f"unknown_target:{cell_id}")
        pairs = tuple((cell_id, resource_id) for cell_id in cells for resource_id in resources)
        for key in pairs:
            if key not in self.targets:
                blockers.append(f"unknown_target:{key[0]}:{key[1]}")
        if pairs and all(key in self.targets and self.knowledge_level(*key) >= goal for key in pairs):
            blockers.append("knowledge_goal_reached")
        for campaign_id, campaign in self.campaigns.items():
            if campaign_id == exclude_campaign_id or campaign.control_state is SurveyCampaignControlState.COMPLETED:
                continue
            if set(pairs) & set(campaign.target_pairs()):
                blockers.append(f"campaign_scope_conflict:{campaign_id}")
        if provider_constraint is not None:
            try:
                self.provider(provider_constraint.provider_definition_id)
            except KeyError:
                blockers.append("unknown_provider")
            if not self.graph.has_operational_node(provider_constraint.operational_node_id):
                blockers.append("unknown_provider_location")
        if observation_mode_constraint is not None:
            if not observation_mode_constraint or not any(
                any(mode.id == observation_mode_constraint for mode in provider.observation_modes)
                for provider in self.providers.values()
            ):
                blockers.append("unknown_provider_or_mode")
        return tuple(dict.fromkeys(blockers))

    def start_blockers(
        self, target_cell_ids: tuple[SurfaceCellId, ...], resource_ids: tuple[DefinitionId, ...],
        goal_knowledge_level: KnowledgeLevel, provider_constraint: SurveyProviderConstraint | None = None,
        observation_mode_constraint: str | None = None,
    ) -> tuple[str, ...]:
        return self._campaign_intent_blockers(
            target_cell_ids, resource_ids, goal_knowledge_level, provider_constraint, observation_mode_constraint
        )

    def start(
        self, target_cell_ids: tuple[SurfaceCellId, ...], resource_ids: tuple[DefinitionId, ...],
        goal_knowledge_level: KnowledgeLevel, *, provider_constraint: SurveyProviderConstraint | None = None,
        observation_mode_constraint: str | None = None, priority: ActivityPriority = DEFAULT_PRIORITY, day: int = 0,
    ) -> EntityId:
        del day
        blockers = self.start_blockers(target_cell_ids, resource_ids, goal_knowledge_level, provider_constraint, observation_mode_constraint)
        if blockers:
            raise ValueError("; ".join(blockers))
        self._campaign_counter += 1
        campaign_id = EntityId(f"survey.campaign.{self._campaign_counter}")
        self.campaigns[campaign_id] = SurveyCampaign(
            campaign_id, target_cell_ids, resource_ids, goal_knowledge_level, provider_constraint,
            observation_mode_constraint, priority, SurveyCampaignControlState.ACTIVE,
        )
        return campaign_id

    def update(
        self, campaign_id: EntityId, target_cell_ids: tuple[SurfaceCellId, ...],
        resource_ids: tuple[DefinitionId, ...], goal_knowledge_level: KnowledgeLevel, *,
        provider_constraint: SurveyProviderConstraint | None = None, observation_mode_constraint: str | None = None,
    ) -> None:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            raise KeyError(campaign_id)
        blockers = self._campaign_intent_blockers(
            target_cell_ids, resource_ids, goal_knowledge_level, provider_constraint, observation_mode_constraint,
            exclude_campaign_id=campaign_id,
        )
        if blockers:
            raise ValueError("; ".join(blockers))
        campaign.target_cell_ids = tuple(sorted(set(target_cell_ids), key=str))
        campaign.resource_ids = tuple(sorted(set(resource_ids), key=str))
        campaign.goal_knowledge_level = KnowledgeLevel(goal_knowledge_level)
        campaign.provider_constraint = provider_constraint
        campaign.observation_mode_constraint = observation_mode_constraint
        if campaign.control_state is SurveyCampaignControlState.COMPLETED:
            campaign.control_state = SurveyCampaignControlState.ACTIVE
        self._settle_campaign_completion(campaign)

    def pause_blockers(self, campaign_id: EntityId) -> tuple[str, ...]:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return ("not_active",)
        if campaign.control_state is SurveyCampaignControlState.PAUSED:
            return ("already_paused",)
        if campaign.control_state is SurveyCampaignControlState.COMPLETED:
            return ("already_complete",)
        return ()

    def can_pause(self, campaign_id: EntityId) -> bool:
        return not self.pause_blockers(campaign_id)

    def pause(self, campaign_id: EntityId) -> None:
        blockers = self.pause_blockers(campaign_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[campaign_id].control_state = SurveyCampaignControlState.PAUSED

    def resume_blockers(self, campaign_id: EntityId) -> tuple[str, ...]:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return ("not_active",)
        if campaign.control_state is SurveyCampaignControlState.COMPLETED:
            return ("already_complete",)
        if campaign.control_state is not SurveyCampaignControlState.PAUSED:
            return ("not_paused",)
        return ()

    def can_resume(self, campaign_id: EntityId) -> bool:
        return not self.resume_blockers(campaign_id)

    def resume(self, campaign_id: EntityId) -> None:
        blockers = self.resume_blockers(campaign_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[campaign_id].control_state = SurveyCampaignControlState.ACTIVE

    def priority_blockers(self, campaign_id: EntityId) -> tuple[str, ...]:
        return () if campaign_id in self.campaigns else ("not_active",)

    def can_set_priority(self, campaign_id: EntityId) -> bool:
        return not self.priority_blockers(campaign_id)

    def set_priority(self, campaign_id: EntityId, priority: ActivityPriority) -> None:
        blockers = self.priority_blockers(campaign_id)
        if blockers:
            raise ValueError("; ".join(blockers))
        self.campaigns[campaign_id].priority = ActivityPriority(priority)

    def _settle_campaign_completion(self, campaign: SurveyCampaign) -> None:
        if not self.unfinished_targets(campaign):
            campaign.control_state = SurveyCampaignControlState.COMPLETED

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
        self.estimated_potential.pop(key, None)
        for campaign in self.campaigns.values():
            if key in campaign.target_pairs():
                self._settle_campaign_completion(campaign)

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

    def _estimated_potential_for_mode(
        self,
        cell_id: SurfaceCellId,
        resource_id: DefinitionId,
        provider_id: DefinitionId,
        mode: SurveyObservationModeSpec,
    ) -> float:
        """Create a stable observation result without exposing static ground truth.

        The uncertainty width is Content-owned. Core only derives a stable signed
        observation error from the observation identity so results are independent
        of registration order and survive Save / Load exactly once stored.
        """

        actual = self.actual_potential(cell_id, resource_id)
        uncertainty = mode.estimate_uncertainty_fraction
        if actual <= 0.0 or uncertainty <= 1e-12:
            return actual
        digest = sha256(
            f"{cell_id}\0{resource_id}\0{provider_id}\0{mode.id}".encode("utf-8")
        ).digest()
        unit = int.from_bytes(digest[:8], "big") / float((1 << 64) - 1)
        signed_error = (unit * 2.0) - 1.0
        return max(0.0, actual * (1.0 + signed_error * uncertainty))

    def visible_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float | None:
        level = self.knowledge_level(cell_id, resource_id)
        if level < KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return None
        if level >= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            return self.actual_potential(cell_id, resource_id)
        return self.estimated_potential.get((cell_id, resource_id))

    def visible_potential_precision_fraction(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> float | None:
        if self.knowledge_level(cell_id, resource_id) < KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return None
        return self.knowledge_precision_fraction.get((cell_id, resource_id))

    def capacity_for_campaign(
        self, campaign: SurveyCampaign, power: PowerSnapshot | None = None, day: int = 0,
    ) -> float:
        candidate, blockers = self.resolve_campaign_candidate(campaign, day=day)
        if candidate is None or blockers:
            return 0.0
        mode = self.observation_mode(candidate.provider_definition_id, candidate.observation_mode_id)
        return self.provider_capacity_at(
            candidate.provider_definition_id, candidate.provider_operational_node_id, power, day
        ) * mode.survey_rate

    def campaign_blockers(
        self, campaign_id: EntityId, *, day: int = 0,
        execution_allocations: ExecutionAllocationPlan | None = None,
    ) -> tuple[str, ...]:
        campaign = self.campaigns[campaign_id]
        if campaign.control_state is SurveyCampaignControlState.PAUSED:
            return ("manual_pause",)
        if campaign.control_state is SurveyCampaignControlState.COMPLETED:
            return ()
        candidate, blockers = self.resolve_campaign_candidate(campaign, day=day)
        result = list(blockers)
        if candidate is not None and execution_allocations is not None:
            unfinished = self.unfinished_targets(campaign)
            allocation_by_id = {row.bundle_id: row.allocated_execution for row in execution_allocations.allocations}
            if unfinished and all(
                allocation_by_id.get(self.execution_bundle_id(campaign.id, *key), 0.0) <= 1e-12
                for key in unfinished
            ):
                result.append("service_capacity")
        return tuple(dict.fromkeys(result))

    def execution_requirement_bundles(self, day: int = 0) -> tuple[ExecutionRequirementBundle, ...]:
        bundles: list[ExecutionRequirementBundle] = []
        for campaign in sorted(self.campaigns.values(), key=lambda row: (-int(row.priority), str(row.id))):
            if campaign.control_state is not SurveyCampaignControlState.ACTIVE:
                continue
            candidate, blockers = self.resolve_campaign_candidate(campaign, day=day)
            if candidate is None or blockers:
                continue
            mode = self.observation_mode(candidate.provider_definition_id, candidate.observation_mode_id)
            for key in self.unfinished_targets(campaign):
                threshold = self.targets[key].thresholds[int(campaign.goal_knowledge_level) - 1]
                remaining_progress = max(0.0, threshold - self.knowledge_progress.get(key, 0.0))
                requested_capacity = remaining_progress / mode.survey_rate
                if requested_capacity <= 1e-12:
                    continue
                bundles.append(ExecutionRequirementBundle(
                    self.execution_bundle_id(campaign.id, *key), "survey",
                    self.campaign_owner_id(campaign.id), "survey_observation",
                    candidate.provider_operational_node_id, requested_capacity, campaign.priority,
                    (ServiceCapacityRequirement(self.service_type_for_provider(candidate.provider_definition_id), 1.0),),
                ))
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
        assignment = self.provider_assignment_for(provider_id, operational_node_id)
        enabled = (
            0.0 if assignment is None
            else self.provider_assignment_quantity(assignment.id) * provider.capacity_units_per_source_per_day
        )
        return (enabled, enabled)

    def advance_day(
        self, power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan, day: int = 0,
    ) -> None:
        del power_by_location
        for campaign in sorted(self.campaigns.values(), key=lambda row: (-int(row.priority), str(row.id))):
            if campaign.control_state is not SurveyCampaignControlState.ACTIVE:
                continue
            candidate, blockers = self.resolve_campaign_candidate(campaign, day=day)
            if candidate is None or blockers:
                continue
            mode = self.observation_mode(candidate.provider_definition_id, candidate.observation_mode_id)
            for key in self.unfinished_targets(campaign):
                try:
                    allocated_capacity = execution_allocations.allocated(self.execution_bundle_id(campaign.id, *key))
                except KeyError:
                    allocated_capacity = 0.0
                if allocated_capacity <= 1e-12:
                    continue
                threshold = self.targets[key].thresholds[int(campaign.goal_knowledge_level) - 1]
                before_level = self.knowledge_level(*key)
                current = self.knowledge_progress.get(key, 0.0)
                gain = min(allocated_capacity * mode.survey_rate, max(0.0, threshold - current))
                if gain <= 1e-12:
                    continue
                self.knowledge_progress[key] = min(threshold, current + gain)
                after_level = self.knowledge_level(*key)
                if after_level >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL and after_level > before_level:
                    if key not in self.estimated_potential:
                        self.estimated_potential[key] = self._estimated_potential_for_mode(
                            key[0], key[1], candidate.provider_definition_id, mode
                        )
                    precision = mode.precision_for_level(after_level)
                    if precision is not None:
                        prior = self.knowledge_precision_fraction.get(key)
                        self.knowledge_precision_fraction[key] = precision if prior is None else min(prior, precision)
            self._settle_campaign_completion(campaign)
