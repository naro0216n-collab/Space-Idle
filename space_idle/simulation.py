from __future__ import annotations

from dataclasses import dataclass
import math

from .contracts import ContractService
from .domain import DomainExtension
from .facilities import FacilityBook
from .industry import IndustryService
from .inventory import InventoryBook
from .logistics import LogisticsService
from .maintenance import FacilityMaintenanceService
from .power import PowerService, PowerSnapshot
from .projects import ProjectService
from .research import ResearchService
from .resource_demand import (
    ResourceDemand,
    external_resource_demands,
    reconcile_local_resource_claims,
    resolve_local_resource_supply,
    ResourceDemandResolution,
)
from .shared import AccountState, SpatialNodeId
from .spatial import EnvironmentResolver, SpatialGraph
from .storage import StorageService
from .technology import TechnologyState
from .survey import ExtractionService, SurveyService
from .scientific_exploration import ScientificExplorationService


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
    scientific_exploration: ScientificExplorationService | None = None
    maintenance: FacilityMaintenanceService | None = None
    content_id: str = "unconfigured"
    pending_offline_game_days: float = 0.0
    domain_extensions: tuple[DomainExtension, ...] = ()

    def _active_locations(self) -> set[SpatialNodeId]:
        locations = {facility.location_id for facility in self.facilities.facilities.values()}
        locations.update(project.location_id for project in self.projects.projects.values())
        if self.survey is not None:
            locations.update(campaign.provider_location_id for campaign in self.survey.campaigns.values())
        locations.update(
            project.location_id
            for project in self.logistics.vehicle_production_projects.values()
        )
        if self.scientific_exploration is not None:
            for definition_id in self.scientific_exploration.campaigns:
                definition = self.scientific_exploration.definitions[definition_id]
                locations.add(definition.origin_id)
                locations.add(definition.destination_id)
        return locations

    def refresh_storage(self) -> None:
        locations = set(self.graph.operational_node_ids()) | {
            facility.location_id for facility in self.facilities.facilities.values()
        }
        power_by_location = {
            loc: self.power.snapshot(loc, self.facilities, self.day)
            for loc in sorted(locations, key=str)
        }
        self.storage.refresh(self.day, power_by_location)

    def _gross_resource_demands(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[ResourceDemand, ...]:
        """Collect domain need before local supply and transport are resolved."""
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
        if self.maintenance is not None:
            demands.extend(self.maintenance.resource_demands(self.day))
        demands.extend(self.logistics.vehicle_production_resource_demands(self.day))
        if self.scientific_exploration is not None:
            demands.extend(self.scientific_exploration.resource_demands(self.day))
        seen: set[object] = set()
        for demand in demands:
            if demand.id in seen:
                raise RuntimeError(f"duplicate resource demand id: {demand.id}")
            seen.add(demand.id)
        return tuple(demands)

    def resource_demand_resolutions(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[ResourceDemandResolution, ...]:
        """Expose gross need and deterministic on-site allocation for queries.

        This is observational. It does not reserve resources or alter priorities,
        and therefore does not remove a supply bottleneck on the player's behalf.
        """
        return resolve_local_resource_supply(
            self._gross_resource_demands(power_by_location), self.inventory
        )

    def resource_demands(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[ResourceDemand, ...]:
        """Return only the true off-site shortage after shared local netting."""
        rows: list[ResourceDemand] = []
        for resolution in self.resource_demand_resolutions(power_by_location):
            demand = resolution.external_demand()
            if demand is not None:
                rows.append(demand)
        return tuple(rows)

    def refresh_resource_claims(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[ResourceDemandResolution, ...]:
        """Recompute present-time local allocations without advancing the clock.

        Commands that commit a discrete demand may call this after changing the
        demand set. It applies the same Location × Resource priority allocator as
        the daily orchestrator; it does not create supply, choose a route, or
        advance logistics.
        """
        powers = power_by_location or {
            loc: self.power.snapshot(loc, self.facilities, self.day)
            for loc in sorted(self._active_locations(), key=str)
        }
        return reconcile_local_resource_claims(
            self._gross_resource_demands(powers), self.inventory
        )

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

            # Determine all current need and Transport availability before any
            # same-tick production or arrivals can alter the resource snapshot.
            gross_demands = self._gross_resource_demands(power_before)
            reconcile_local_resource_claims(gross_demands, self.inventory)
            external_demands = external_resource_demands(gross_demands, self.inventory)
            self.logistics.advance_capacity_logistics(self.day, external_demands)

            # Arrivals may serve later Domain work in this tick, but cannot feed
            # back into the already fixed Transport capacity above.
            reconcile_local_resource_claims(gross_demands, self.inventory)

            for loc in ordered_locations:
                self.industry.advance_day(
                    loc, self.facilities, self.inventory, power_before[loc], self.day
                )
                if self.extraction is not None:
                    self.extraction.advance_day(
                        loc, self.facilities, self.inventory, power_before[loc], self.day
                    )

            reconcile_local_resource_claims(
                self._gross_resource_demands(power_before), self.inventory
            )

            if self.research is not None:
                self.research.advance_day(power_before, self.day)
            if self.scientific_exploration is not None:
                self.scientific_exploration.advance_day(power_before, self.day)
            if self.survey is not None:
                self.survey.advance_day(power_before, self.day)
            if self.maintenance is not None:
                self.maintenance.advance_day(self.day)

            self.projects.advance_procurement(self.day)

            self.logistics.advance_vehicle_production_day(power_before, self.day)
            self.projects.finalize_procurement(self.day)
            self.projects.advance_construction(power_before, self.day)
            self.refresh_storage()
            next_day = self.day + 1
            if self.contracts is not None:
                self.contracts.advance_day(next_day)
            self.day = next_day
            self.refresh_resource_claims()
