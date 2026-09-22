from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import SiteRequirements


class KnowledgeLevel(IntEnum):
    UNKNOWN = 0
    PRESENCE_PROBABILITY = 1
    ESTIMATED_RESOURCE_POTENTIAL = 2
    MEASURED_RESOURCE_POTENTIAL = 3


@dataclass(frozen=True)
class KnowledgeRequirement:
    target_cell_id: SurfaceCellId
    subject_resource_id: DefinitionId
    minimum_level: KnowledgeLevel

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_level", KnowledgeLevel(self.minimum_level))
        if self.minimum_level is KnowledgeLevel.UNKNOWN:
            raise ValueError("knowledge requirement must require a positive knowledge level")


@dataclass(frozen=True)
class KnowledgeRequirementSpec:
    subject_resource_id: DefinitionId
    minimum_level: KnowledgeLevel

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_level", KnowledgeLevel(self.minimum_level))
        if self.minimum_level is KnowledgeLevel.UNKNOWN:
            raise ValueError("knowledge requirement spec must require a positive knowledge level")

    def bind(self, target_cell_id: SurfaceCellId) -> KnowledgeRequirement:
        return KnowledgeRequirement(target_cell_id, self.subject_resource_id, self.minimum_level)


class SurveyReachScope(str, Enum):
    SAME_BODY = "same_body"
    SAME_SYSTEM = "same_system"
    LOCATION_TERRITORY = "location_territory"


@dataclass(frozen=True)
class SurveyReachSpec:
    scope: SurveyReachScope
    max_characteristic_distance_km: float | None = None
    max_characteristic_delta_v_km_s: float | None = None
    required_operation_types: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.max_characteristic_distance_km is not None and self.max_characteristic_distance_km < 0:
            raise ValueError("survey reach distance must be non-negative")
        if self.max_characteristic_delta_v_km_s is not None and self.max_characteristic_delta_v_km_s < 0:
            raise ValueError("survey reach delta-v must be non-negative")
        if any(not operation_type for operation_type in self.required_operation_types):
            raise ValueError("survey reach operation type must not be empty")


class SurveyProviderSourceKind(str, Enum):
    FACILITY = "facility"
    FLEET = "fleet"


@dataclass(frozen=True)
class SurveyTarget:
    cell_id: SurfaceCellId
    resource_id: DefinitionId
    thresholds: tuple[float, float, float]
    prior_presence_probability: float = 0.5

    def __post_init__(self) -> None:
        if len(self.thresholds) != 3 or any(v < 0 for v in self.thresholds):
            raise ValueError("survey target requires three non-negative knowledge thresholds")
        if tuple(sorted(self.thresholds)) != self.thresholds:
            raise ValueError("survey knowledge thresholds must be sorted")
        if not 0.0 <= self.prior_presence_probability <= 1.0:
            raise ValueError("survey presence probability must be within 0..1")


@dataclass(frozen=True)
class SurveyObservationModeSpec:
    id: str
    survey_rate: float
    reach: SurveyReachSpec
    max_knowledge_level: KnowledgeLevel
    estimate_uncertainty_fraction: float
    measurement_precision_fraction: float
    site_requirements: SiteRequirements = SiteRequirements()
    required_source_capabilities: frozenset[str] = frozenset()
    minimum_source_units: int = 1
    display_name: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("survey observation mode id must not be empty")
        if self.display_name is not None and not self.display_name:
            raise ValueError("survey observation mode display name must not be empty")
        if self.survey_rate <= 0:
            raise ValueError("survey observation mode rate must be positive")
        object.__setattr__(self, "max_knowledge_level", KnowledgeLevel(self.max_knowledge_level))
        if self.max_knowledge_level is KnowledgeLevel.UNKNOWN:
            raise ValueError("survey observation mode max knowledge level must be positive")
        if not 0.0 <= self.estimate_uncertainty_fraction <= 1.0:
            raise ValueError("survey estimate uncertainty must be within 0..1")
        if not 0.0 <= self.measurement_precision_fraction <= 1.0:
            raise ValueError("survey measurement precision must be within 0..1")
        if self.minimum_source_units <= 0:
            raise ValueError("survey observation mode minimum source units must be positive")
        if any(not capability for capability in self.required_source_capabilities):
            raise ValueError("survey source capabilities must not be empty")

    def precision_for_level(self, level: KnowledgeLevel) -> float | None:
        level = KnowledgeLevel(level)
        if level < KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return None
        if level == KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            return self.estimate_uncertainty_fraction
        return self.measurement_precision_fraction


@dataclass(frozen=True)
class SurveyProviderSpec:
    id: DefinitionId
    source_kind: SurveyProviderSourceKind
    source_definition_id: DefinitionId
    observation_modes: tuple[SurveyObservationModeSpec, ...]
    capacity_units_per_source_per_day: float = 1.0

    def __post_init__(self) -> None:
        if not self.observation_modes:
            raise ValueError("survey provider must define at least one observation mode")
        if self.capacity_units_per_source_per_day <= 0:
            raise ValueError("survey provider source capacity must be positive")
        mode_ids = tuple(mode.id for mode in self.observation_modes)
        if len(set(mode_ids)) != len(mode_ids):
            raise ValueError("survey observation mode ids must be unique per provider")

    def observation_mode(self, mode_id: str) -> SurveyObservationModeSpec:
        for mode in self.observation_modes:
            if mode.id == mode_id:
                return mode
        raise KeyError(mode_id)


class SurveyCampaignControlState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(frozen=True)
class SurveyProviderConstraint:
    provider_definition_id: DefinitionId
    operational_node_id: SpatialNodeId


@dataclass
class SurveyCampaign:
    id: EntityId
    target_cell_ids: tuple[SurfaceCellId, ...]
    resource_ids: tuple[DefinitionId, ...]
    goal_knowledge_level: KnowledgeLevel
    provider_constraint: SurveyProviderConstraint | None = None
    observation_mode_constraint: str | None = None
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    control_state: SurveyCampaignControlState = SurveyCampaignControlState.ACTIVE

    def __post_init__(self) -> None:
        self.target_cell_ids = tuple(sorted(set(self.target_cell_ids), key=str))
        self.resource_ids = tuple(sorted(set(self.resource_ids), key=str))
        self.priority = ActivityPriority(self.priority)
        self.goal_knowledge_level = KnowledgeLevel(self.goal_knowledge_level)
        self.control_state = SurveyCampaignControlState(self.control_state)
        if not self.target_cell_ids:
            raise ValueError("survey campaign requires at least one target cell")
        if not self.resource_ids:
            raise ValueError("survey campaign requires at least one resource")
        if self.goal_knowledge_level is KnowledgeLevel.UNKNOWN:
            raise ValueError("survey goal knowledge level must be positive")
        if self.observation_mode_constraint is not None and not self.observation_mode_constraint:
            raise ValueError("survey observation mode constraint must not be empty")

    def target_pairs(self) -> tuple[tuple[SurfaceCellId, DefinitionId], ...]:
        return tuple(
            (cell_id, resource_id)
            for cell_id in self.target_cell_ids
            for resource_id in self.resource_ids
        )


@dataclass
class SurveyProviderAssignmentState:
    id: EntityId
    provider_definition_id: DefinitionId
    vehicle_definition_id: DefinitionId
    operational_node_id: SpatialNodeId
    fleet_commitment_ref: EntityId



@dataclass(frozen=True)
class ExtractionSpec:
    facility_def_id: DefinitionId
    resource_id: DefinitionId
    output_resource_id: DefinitionId
    nominal_capacity_t_per_day: float
    opportunity_requirements: SiteRequirements = SiteRequirements()
    geology_accessibility_key: str | None = None
    terrain_accessibility_attribute: str | None = None
    minimum_knowledge_level: KnowledgeLevel | None = None

    def __post_init__(self) -> None:
        if self.nominal_capacity_t_per_day < 0:
            raise ValueError("nominal extraction capacity must be non-negative")
        if self.geology_accessibility_key is not None and not self.geology_accessibility_key:
            raise ValueError("geology accessibility key must not be empty")
        if self.terrain_accessibility_attribute is not None and not self.terrain_accessibility_attribute:
            raise ValueError("terrain accessibility attribute must not be empty")
        if self.minimum_knowledge_level is not None:
            object.__setattr__(self, "minimum_knowledge_level", KnowledgeLevel(self.minimum_knowledge_level))
            if self.minimum_knowledge_level is KnowledgeLevel.UNKNOWN:
                raise ValueError("minimum extraction knowledge level must be positive")


@dataclass(frozen=True)
class ExtractionResourceSnapshot:
    resource_id: DefinitionId
    static_opportunity: float
    effective_opportunity: float
    knowledge_eligible_cell_count: int
    knowledge_blocked_cell_count: int
    installed_nominal_capacity_t_per_day: float
    operational_fulfillment: float
    diminishing_efficiency: float
    marginal_efficiency: float
    output_t_per_day: float


@dataclass(frozen=True)
class ExtractionSnapshot:
    facility_id: object
    facility_def_id: DefinitionId
    resource_id: DefinitionId
    output_resource_id: DefinitionId
    nominal_capacity_t_per_day: float
    effective_opportunity: float
    marginal_efficiency: float
    scale: float
    output_t_per_day: float
    limiting_factors: tuple[str, ...]
