from __future__ import annotations

from dataclasses import dataclass, field

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
