from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ResearchRow:
    id: str
    display_name: str
    status: str
    paused: bool
    can_start: bool
    theory_done: float
    theory_required: float
    eligible_capacity_points_per_day: float
    allocation_weight: float
    prototype_resources: tuple[tuple[str, float], ...]
    prototype_location_id: str | None
    demonstration_done_days: int
    demonstration_required_days: int
    demonstration_location_id: str | None
    demonstration_blockers: tuple[tuple[str, str], ...]
    prototype_blockers: tuple[tuple[str, str], ...]
    theory_blockers: tuple[tuple[str, str], ...]
    prerequisites: tuple[str, ...]

@dataclass(frozen=True)
class ResearchView:
    capacity_points_per_day: float
    items: tuple[ResearchRow, ...]

@dataclass(frozen=True)
class SurveyRow:
    location_id: str
    resource_id: str
    resource_name: str
    active: bool
    complete: bool
    paused: bool
    progress: float
    allocation_weight: float
    knowledge_level: int
    presence_probability: float | None
    visible_concentration: float | None
    visible_reserve_t: float | None
    capacity_points_per_day: float
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class SurveysView:
    items: tuple[SurveyRow, ...]

@dataclass(frozen=True)
class ContractRow:
    id: str
    template_id: str
    display_name: str
    kind: str
    status: str
    deadline_day: int
    reward_musd: float
    source_id: str | None
    destination_id: str | None
    resource_id: str | None
    cargo_t: float | None
    cargo_order_id: str | None
    target_location_id: str | None
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class ContractsView:
    items: tuple[ContractRow, ...]
