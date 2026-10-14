from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from hashlib import sha256

from .exploration_models import KnowledgeLevel, KnowledgeRequirement, SurveyTarget, SurveyObservationModeSpec
from .shared import CelestialBodyId, DefinitionId, SurfaceCellId
from .spatial import SpatialGraph

from .shared import EntityId, SpatialNodeId


@dataclass(frozen=True)
class DomainActivity:
    activity_kind: str
    amount: float
    owner_kind: str
    owner_id: EntityId
    operational_node_id: SpatialNodeId | None = None

    def __post_init__(self) -> None:
        if not self.activity_kind:
            raise ValueError("activity kind must not be empty")
        if self.amount < -1e-9:
            raise ValueError("activity amount must be non-negative")


@dataclass(frozen=True)
class ExperienceContributionRule:
    activity_kind: str
    category_id: str
    points_per_unit: float

    def __post_init__(self) -> None:
        if not self.activity_kind or not self.category_id:
            raise ValueError("experience contribution rule ids must not be empty")
        if self.points_per_unit < 0:
            raise ValueError("experience contribution rate must be non-negative")


@dataclass
class KnowledgeState:
    experience_by_category: dict[str, float] = field(default_factory=dict)

    def value(self, category_id: str) -> float:
        return max(0.0, self.experience_by_category.get(category_id, 0.0))

    def add(self, category_id: str, amount: float) -> None:
        if amount < -1e-9:
            raise ValueError("knowledge contribution must be non-negative")
        if amount > 1e-12:
            self.experience_by_category[category_id] = self.value(category_id) + amount

    def record(
        self,
        activities: tuple[DomainActivity, ...],
        rules: tuple[ExperienceContributionRule, ...],
    ) -> None:
        rates: dict[str, list[ExperienceContributionRule]] = {}
        for rule in rules:
            rates.setdefault(rule.activity_kind, []).append(rule)
        for activity in activities:
            if activity.amount <= 1e-12:
                continue
            for rule in rates.get(activity.activity_kind, ()): 
                self.add(rule.category_id, activity.amount * rule.points_per_unit)


@dataclass
class SurfaceKnowledgeState:
    """Player observations; World is the sole owner of physical values.

    This state is shared by Survey and Scientific Exploration, never copied
    into an activity campaign. Progress and quality are monotonic.
    """
    targets: dict[tuple[SurfaceCellId, DefinitionId], SurveyTarget]
    graph: SpatialGraph
    knowledge_progress: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    knowledge_precision_fraction: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    estimated_potential: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    observed_presence_probability: dict[tuple[SurfaceCellId, DefinitionId], float] = field(default_factory=dict)
    # Cell-local attributes are independently observed; known Resource does not
    # silently reveal weather, slope, geology or Power conditions.
    cell_attribute_levels: dict[tuple[SurfaceCellId, str], int] = field(default_factory=dict)
    terrain_overview_resolution: float = 0.5

    def attribute_level(self, cell_id: SurfaceCellId, attribute: str) -> int:
        if cell_id not in self.graph.surface_cells or attribute not in ("terrain", "environment", "geology"):
            raise KeyError((cell_id, attribute))
        return self.cell_attribute_levels.get((cell_id, attribute), 0)

    def unpublished_site_condition_codes(self, cell_id: SurfaceCellId, *requirements: object) -> frozenset[str]:
        """Which authored Environment requirements cannot be explained publicly.

        This only classifies metadata for projection; execution continues to
        evaluate true World conditions through the owning Site service.
        """
        if self.attribute_level(cell_id, "environment") >= 2:
            return frozenset()
        return frozenset(
            condition.code
            for requirement in requirements
            for condition in requirement.environment
        )

    def terrain_overview(self, cell_id: SurfaceCellId) -> tuple[tuple[str, float], ...]:
        """Content-granularity intervals, never a midpoint that reveals true value."""
        if self.attribute_level(cell_id, "terrain") < 1:
            return ()
        terrain = self.graph.surface_cells[cell_id].terrain
        result: list[tuple[str, float]] = []
        for attr in ("terrain_factor", "bearing_capacity_factor", "dust_factor", "slope_factor"):
            value = float(getattr(terrain, attr))
            lower = floor(value / self.terrain_overview_resolution) * self.terrain_overview_resolution
            result.extend(((attr + "_min", lower), (attr + "_max", lower + self.terrain_overview_resolution)))
        return tuple(result)

    def observe_attribute(self, cell_id: SurfaceCellId, attribute: str, level: int) -> None:
        self.attribute_level(cell_id, attribute)
        if isinstance(level, bool) or not isinstance(level, int) or level not in (1, 2):
            raise ValueError("attribute observation quality must be overview=1 or measured=2")
        key = (cell_id, attribute)
        self.cell_attribute_levels[key] = max(level, self.cell_attribute_levels.get(key, 0))

    def observe_body(self, body_id: CelestialBodyId, *, resource_level: KnowledgeLevel,
                     attribute_level: int = 0) -> None:
        """A finite orbital campaign settles one consistent regional observation.

        The truth is still owned by World; settlement only improves what the
        player knows. This never creates Survey Intent or RP.
        """
        resources_by_cell = self.resource_ids_by_cell
        for cell in self.graph.cells_for_body(body_id):
            if attribute_level:
                for attribute in ("terrain", "environment"):
                    self.observe_attribute(cell.id, attribute, attribute_level)
            if resource_level is not KnowledgeLevel.UNKNOWN:
                for resource_id in resources_by_cell.get(cell.id, ()):
                    self.observe_resource(cell.id, resource_id, resource_level, precision=0.0)

    @property
    def resource_ids_by_cell(self) -> dict[SurfaceCellId, tuple[DefinitionId, ...]]:
        # Only used at settlement, not during each UI Cell iteration.
        result: dict[SurfaceCellId, list[DefinitionId]] = {}
        for cell_id, resource_id in self.targets:
            result.setdefault(cell_id, []).append(resource_id)
        return {key: tuple(values) for key, values in result.items()}

    def observe_resource(self, cell_id: SurfaceCellId, resource_id: DefinitionId,
                         level: KnowledgeLevel, *, precision: float = 0.0,
                         estimate: float | None = None) -> None:
        """Settle an actual observation without resetting a stronger result."""
        key = (cell_id, resource_id)
        target = self.targets[key]
        level = KnowledgeLevel(level)
        current_level = self.knowledge_level(*key)
        if level is KnowledgeLevel.UNKNOWN or current_level is KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            return
        if (level is KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL
                and key not in self.estimated_potential and estimate is None):
            raise ValueError("estimated observation requires an uncertainty-bearing result")
        self.knowledge_progress[key] = max(self.progress(*key), target.thresholds[int(level) - 1])
        if level < KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            # Evidence is settled once; reading it must not re-sample World truth.
            self.observed_presence_probability.setdefault(key, self._presence_observation(*key))
        else:
            self.observed_presence_probability.pop(key, None)
        if level >= KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL:
            old_precision = self.knowledge_precision_fraction.get(key)
            self.knowledge_precision_fraction[key] = precision if old_precision is None else min(old_precision, precision)
            if level is KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL and key not in self.estimated_potential:
                self.estimated_potential[key] = max(0.0, estimate)
            if self.knowledge_level(*key) is KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
                self.estimated_potential.pop(key, None)

    def settle_survey_work(self, cell_id: SurfaceCellId, resource_id: DefinitionId,
                           work: float, max_level: KnowledgeLevel, provider_id: DefinitionId,
                           mode: SurveyObservationModeSpec) -> None:
        key = (cell_id, resource_id)
        target = self.targets[key]
        threshold = target.thresholds[int(max_level) - 1]
        if work <= 0:
            return
        before_level = self.knowledge_level(*key)
        self.knowledge_progress[key] = max(self.progress(*key), min(threshold, self.progress(*key) + work))
        after_level = self.knowledge_level(*key)
        if after_level > before_level:
            estimate = (self._estimated_potential_for_mode(cell_id, resource_id, provider_id, mode)
                        if after_level is KnowledgeLevel.ESTIMATED_RESOURCE_POTENTIAL else None)
            self.observe_resource(cell_id, resource_id, after_level,
                                  precision=mode.precision_for_level(after_level) or 0.0, estimate=estimate)
        # Finite regional observation provides physical context as a separate
        # quality-graded attribute, without unlocking unrelated Resource truths.
        if after_level >= KnowledgeLevel.PRESENCE_PROBABILITY:
            self.observe_attribute(cell_id, "terrain", 1)
            self.observe_attribute(cell_id, "environment", 1)
        if after_level >= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            self.observe_attribute(cell_id, "terrain", 2)
            self.observe_attribute(cell_id, "environment", 2)
            self.observe_attribute(cell_id, "geology", 2)

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
        self.observe_resource(cell_id, resource_id, KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL)

    def is_complete(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> bool:
        return self.knowledge_level(cell_id, resource_id) >= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL

    def actual_potential(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        if (cell_id, resource_id) not in self.targets:
            raise KeyError((cell_id, resource_id))
        return float(self.graph.surface_cells[cell_id].resource_potential_by_resource.get(resource_id, 0.0))

    def visible_presence_probability(
        self, cell_id: SurfaceCellId, resource_id: DefinitionId
    ) -> float | None:
        level = self.knowledge_level(cell_id, resource_id)
        if level < KnowledgeLevel.PRESENCE_PROBABILITY:
            return None
        if level >= KnowledgeLevel.MEASURED_RESOURCE_POTENTIAL:
            return 1.0 if self.actual_potential(cell_id, resource_id) > 0.0 else 0.0
        return self.observed_presence_probability[(cell_id, resource_id)]

    def _presence_observation(self, cell_id: SurfaceCellId, resource_id: DefinitionId) -> float:
        # Settled evidence, unlike a Query, is allowed to inspect physical truth.
        actual_present = self.actual_potential(cell_id, resource_id) > 0.0
        target = self.targets[(cell_id, resource_id)]
        prior = target.prior_presence_probability
        reliability = target.presence_detection_reliability
        # Real observations can return a false positive or a false negative.
        # Physical truth does not become public through a probability of 1/0.
        digest = sha256(f"{cell_id}\0{resource_id}\0detection".encode()).digest()
        detection_error = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        observed_positive = (actual_present == (detection_error < reliability))
        if observed_positive:
            observed_true = reliability * prior
            observed_false = (1.0 - reliability) * (1.0 - prior)
        else:
            observed_true = (1.0 - reliability) * prior
            observed_false = reliability * (1.0 - prior)
        return observed_true / (observed_true + observed_false)

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
