from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import ContractService
from .domain import DomainExtension
from .facilities import FacilityBook
from .industry import IndustryService
from .inventory import InventoryBook
from .logistics import LogisticsService
from .power import PowerService, PowerSnapshot
from .projects import ProjectService
from .research import ResearchService
from .resource_demand import ResourceDemand
from .shared import AccountState, SpatialNodeId
from .spatial import EnvironmentResolver, SpatialGraph
from .storage import StorageService
from .technology import TechnologyState
from .survey import ExtractionService, SurveyService


@dataclass(frozen=True)
class OfflineProgressPolicy:
    """Maps elapsed real time to normal simulation days."""

    real_seconds_per_game_day: float
    max_game_days_per_resume: int | None = None

    def __post_init__(self) -> None:
        if self.real_seconds_per_game_day <= 0:
            raise ValueError("real_seconds_per_game_day must be positive")
        if self.max_game_days_per_resume is not None and self.max_game_days_per_resume < 0:
            raise ValueError("max_game_days_per_resume must be non-negative")


@dataclass(frozen=True)
class OfflineProgressResult:
    elapsed_real_seconds: float
    credited_game_days: float
    advanced_days: int
    pending_fractional_day: float
    capped: bool


@dataclass
class Simulation:
    day: int
    account: AccountState
    graph: SpatialGraph
    environment: EnvironmentResolver
    inventory: InventoryBook
    facilities: FacilityBook
    power: PowerService
    storage: StorageService
    industry: IndustryService
    logistics: LogisticsService
    projects: ProjectService
    technology: TechnologyState
    contracts: ContractService | None = None
    research: ResearchService | None = None
    survey: SurveyService | None = None
    extraction: ExtractionService | None = None
    content_id: str = "unconfigured"
    pending_offline_game_days: float = 0.0
    domain_extensions: tuple[DomainExtension, ...] = ()

    def _active_locations(self) -> set[SpatialNodeId]:
        locations = {facility.location_id for facility in self.facilities.facilities.values()}
        locations.update(project.location_id for project in self.projects.projects.values())
        if self.survey is not None:
            locations.update(campaign.location_id for campaign in self.survey.campaigns.values())
        return locations

    def refresh_storage(self) -> None:
        locations = set(self.graph.nodes) | {
            facility.location_id for facility in self.facilities.facilities.values()
        }
        power_by_location = {
            loc: self.power.snapshot(loc, self.facilities, self.day)
            for loc in sorted(locations, key=str)
        }
        self.storage.refresh(self.day, power_by_location)

    def resource_demands(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[ResourceDemand, ...]:
        """Collect material needs declared by domains without coupling logistics to them."""
        locations = self._active_locations()
        powers = power_by_location or {
            loc: self.power.snapshot(loc, self.facilities, self.day)
            for loc in sorted(locations, key=str)
        }
        demands: list[ResourceDemand] = list(self.projects.resource_demands(self.day))
        for location_id in sorted(locations, key=str):
            power = powers.get(location_id)
            if power is None:
                power = self.power.snapshot(location_id, self.facilities, self.day)
            demands.extend(
                self.industry.resource_demands(
                    location_id, self.facilities, self.inventory, power, self.day
                )
            )
        if self.research is not None:
            demands.extend(self.research.resource_demands(self.day))
        seen: set[object] = set()
        for demand in demands:
            if demand.id in seen:
                raise RuntimeError(f"duplicate resource demand id: {demand.id}")
            seen.add(demand.id)
        return tuple(sorted(demands, key=lambda row: (-row.priority, str(row.id))))

    def advance_to_day(self, target_day: int) -> None:
        if target_day < self.day:
            raise ValueError("target day is in the past")
        self.advance_days(target_day - self.day)

    def advance_offline(
        self, elapsed_real_seconds: float, policy: OfflineProgressPolicy
    ) -> OfflineProgressResult:
        if elapsed_real_seconds < 0:
            raise ValueError("elapsed_real_seconds must be non-negative")
        raw_game_days = elapsed_real_seconds / policy.real_seconds_per_game_day
        capped = False
        if (
            policy.max_game_days_per_resume is not None
            and raw_game_days > policy.max_game_days_per_resume
        ):
            raw_game_days = float(policy.max_game_days_per_resume)
            capped = True
        credited = raw_game_days + self.pending_offline_game_days
        whole_days = math.floor(credited + 1e-12)
        self.pending_offline_game_days = max(0.0, credited - whole_days)
        if whole_days:
            self.advance_days(whole_days)
        return OfflineProgressResult(
            elapsed_real_seconds=elapsed_real_seconds,
            credited_game_days=credited,
            advanced_days=whole_days,
            pending_fractional_day=self.pending_offline_game_days,
            capped=capped,
        )

    def advance_days(self, days: int) -> None:
        if days < 0:
            raise ValueError("days must be non-negative")
        for _ in range(days):
            locations = self._active_locations()
            ordered_locations = sorted(locations, key=str)
            power_before = {
                loc: self.power.snapshot(loc, self.facilities, self.day)
                for loc in ordered_locations
            }
            self.storage.refresh(self.day, power_before)
            for loc in ordered_locations:
                self.industry.advance_day(
                    loc, self.facilities, self.inventory, power_before[loc], self.day
                )
                if self.extraction is not None:
                    self.extraction.advance_day(
                        loc, self.facilities, self.inventory, power_before[loc], self.day
                    )

            if self.research is not None:
                self.research.advance_day(power_before, self.day)
            if self.survey is not None:
                self.survey.advance_day(power_before, self.day)

            # Procurement determines domain need; logistics then allocates that
            # need across player-configured lanes and creates physical orders.
            self.projects.advance_procurement(self.day)
            demands = self.resource_demands(power_before)
            self.logistics.advance_automation(self.day, demands)
            self.logistics.advance_day(self.day)
            # Arrivals can satisfy construction reservations on the same tick.
            self.projects.advance_procurement(self.day)

            power_after = {
                loc: self.power.snapshot(loc, self.facilities, self.day)
                for loc in ordered_locations
            }
            self.projects.advance_construction(power_after, self.day)
            self.refresh_storage()
            next_day = self.day + 1
            if self.contracts is not None:
                self.contracts.advance_day(next_day)
            self.day = next_day
