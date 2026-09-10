from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from enum import Enum

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .research import ResearchService
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements
from .transport.models import RouteDef, TransportOperationRequirement

if TYPE_CHECKING:
    from .logistics import LogisticsService


@dataclass(frozen=True)
class ScientificExplorationDefinition:
    id: DefinitionId
    display_name: str
    origin_id: SpatialNodeId
    destination_id: SpatialNodeId
    operations: tuple[TransportOperationRequirement, ...]
    mission_duration_days: int
    duration_days: float
    research_points_total: float
    consumable_resources: tuple[tuple[DefinitionId, float], ...] = ()
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()
    return_to_origin: bool = False

    def __post_init__(self) -> None:
        if self.mission_duration_days <= 0:
            raise ValueError("scientific exploration mission duration must be positive")
        if self.duration_days <= 0:
            raise ValueError("scientific exploration campaign duration must be positive")
        if self.research_points_total <= 0:
            raise ValueError("scientific exploration reward must be positive")
        if any(amount < 0 for _resource, amount in self.consumable_resources):
            raise ValueError("scientific exploration consumables must be non-negative")

    @property
    def points_per_day(self) -> float:
        return self.research_points_total / self.duration_days

    def compatibility_route(self) -> RouteDef:
        return RouteDef(
            RouteId(f"exploration.route:{self.id}"),
            self.origin_id,
            self.destination_id,
            self.mission_duration_days,
            self.operations,
            display_name=self.display_name,
            origin_requirements=self.origin_requirements,
            destination_requirements=self.destination_requirements,
        )


class ScientificExplorationPhase(str, Enum):
    AWAITING_VEHICLE = "awaiting_vehicle"
    ACTIVE = "active"
    COMPLETE = "complete"


@dataclass
class ScientificExplorationState:
    definition_id: DefinitionId
    phase: ScientificExplorationPhase = ScientificExplorationPhase.AWAITING_VEHICLE
    vehicle_id: EntityId | None = None
    progress_days: float = 0.0
    research_points_awarded: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    created_day: int = 0


@dataclass
class ScientificExplorationService:
    definitions: dict[DefinitionId, ScientificExplorationDefinition]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    logistics: "LogisticsService"
    research: ResearchService
    campaigns: dict[DefinitionId, ScientificExplorationState] = field(default_factory=dict)

    def start(self, definition_id: DefinitionId, *, day: int = 0) -> None:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if definition_id in self.campaigns:
            raise ValueError("scientific exploration campaign already started")
        self.campaigns[definition_id] = ScientificExplorationState(
            definition_id=definition_id,
            created_day=day,
        )

    def pause(self, definition_id: DefinitionId) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("completed scientific exploration cannot be paused")
        state.paused = True

    def resume(self, definition_id: DefinitionId) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("completed scientific exploration cannot be resumed")
        state.paused = False

    def _route_failures_for_vehicle(
        self,
        definition: ScientificExplorationDefinition,
        vehicle_id: EntityId,
        day: int,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        vehicle = self.logistics.vehicles[vehicle_id]
        vehicle_def = self.logistics.vehicle_defs[vehicle.definition_id]
        route = definition.compatibility_route()
        failures = list(
            self.logistics.performance_route_failures(
                route,
                vehicle_def.performance,
                day,
                power_by_location=power_by_location,
            )
        )
        for prefix, location_id, requirements in (
            ("origin", definition.origin_id, definition.origin_requirements),
            ("destination", definition.destination_id, definition.destination_requirements),
        ):
            snapshot = (
                None if power_by_location is None else power_by_location.get(location_id)
            ) or self.power.snapshot(location_id, self.facilities, day)
            for failure in evaluate_site_requirements(
                requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
                snapshot,
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(failures)

    def vehicle_failures(
        self,
        definition_id: DefinitionId,
        vehicle_id: EntityId,
        *,
        day: int = 0,
    ) -> tuple[str, ...]:
        definition = self.definitions[definition_id]
        if vehicle_id not in self.logistics.vehicles:
            return ("unknown_vehicle",)
        failures = list(
            self.logistics.exclusive_assignment_failures(
                vehicle_id, definition.origin_id, day
            )
        )
        failures.extend(self._route_failures_for_vehicle(definition, vehicle_id, day))
        return tuple(failures)

    def assign_vehicle(
        self,
        definition_id: DefinitionId,
        vehicle_id: EntityId,
        *,
        day: int = 0,
    ) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("scientific exploration is complete")
        if state.vehicle_id is not None:
            raise ValueError("scientific exploration already has a vehicle")
        failures = self.vehicle_failures(definition_id, vehicle_id, day=day)
        if failures:
            raise ValueError("vehicle is not compatible with scientific exploration: " + "; ".join(failures))
        assignment_id = EntityId(f"scientific_exploration:{definition_id}")
        self.logistics.assign_vehicle_exclusively(
            vehicle_id,
            assignment_id,
            "scientific_exploration",
            self.definitions[definition_id].origin_id,
            day,
        )
        state.vehicle_id = vehicle_id
        state.phase = ScientificExplorationPhase.ACTIVE

    def unassign_vehicle(self, definition_id: DefinitionId) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("scientific exploration is complete")
        if state.progress_days > 1e-9 or state.inputs_consumed:
            raise ValueError("started scientific exploration cannot release its vehicle")
        if state.vehicle_id is None:
            return
        assignment_id = EntityId(f"scientific_exploration:{definition_id}")
        self.logistics.release_vehicle_assignment(
            state.vehicle_id,
            assignment_id,
            self.definitions[definition_id].origin_id,
        )
        state.vehicle_id = None
        state.phase = ScientificExplorationPhase.AWAITING_VEHICLE

    @staticmethod
    def _resource_demand_id(definition_id: DefinitionId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.scientific_exploration:{definition_id}:{resource_id}")

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.inputs_consumed
                or state.vehicle_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            for resource_id, amount_t in sorted(definition.consumable_resources, key=lambda row: str(row[0])):
                if amount_t <= 1e-12:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(definition_id, resource_id),
                    "scientific_exploration",
                    EntityId(f"scientific_exploration:{definition_id}"),
                    definition.origin_id,
                    resource_id,
                    amount_t,
                    70,
                    None,
                ))
        return tuple(demands)

    def _consume_inputs_if_ready(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
    ) -> bool:
        if state.inputs_consumed:
            return True
        resources = tuple((rid, amount) for rid, amount in definition.consumable_resources if amount > 1e-12)
        if not all(
            self.inventory.reserved_for(
                self._resource_demand_id(definition.id, rid),
                definition.origin_id,
                rid,
            ) + 1e-9 >= amount
            for rid, amount in resources
        ):
            return False
        for resource_id, amount_t in resources:
            self.inventory.consume_reserved(
                self._resource_demand_id(definition.id, resource_id),
                definition.origin_id,
                resource_id,
                amount_t,
            )
        state.inputs_consumed = True
        if state.vehicle_id is not None and definition.destination_id != definition.origin_id:
            self.logistics.move_assigned_vehicle(
                state.vehicle_id,
                EntityId(f"scientific_exploration:{definition.id}"),
                definition.destination_id,
            )
        return True

    def blockers(
        self,
        definition_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        definition = self.definitions[definition_id]
        state = self.campaigns.get(definition_id)
        if state is None:
            return ()
        if state.phase is ScientificExplorationPhase.COMPLETE:
            return ()
        blockers: list[str] = []
        if state.paused:
            blockers.append("manual_pause")
        if state.vehicle_id is None:
            blockers.append("vehicle_unassigned")
            return tuple(blockers)
        if not state.inputs_consumed:
            for resource_id, amount_t in definition.consumable_resources:
                allocated = self.inventory.reserved_for(
                    self._resource_demand_id(definition_id, resource_id),
                    definition.origin_id,
                    resource_id,
                )
                if allocated + 1e-9 < amount_t:
                    blockers.append(f"resource:{resource_id}:{allocated:g}/{amount_t:g}")
        blockers.extend(
            self._route_failures_for_vehicle(
                definition,
                state.vehicle_id,
                day,
                power_by_location,
            )
        )
        snapshots = power_by_location or {}
        capacity = self.research.storage_capacity(snapshots if snapshots else None, day)
        if self.research.stored_points >= capacity - 1e-9:
            blockers.append("rp_storage_full")
        return tuple(blockers)

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> None:
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if state.phase is not ScientificExplorationPhase.ACTIVE or state.paused or state.vehicle_id is None:
                continue
            definition = self.definitions[definition_id]
            if self._route_failures_for_vehicle(
                definition,
                state.vehicle_id,
                day,
                power_by_location,
            ):
                continue
            if not self._consume_inputs_if_ready(definition, state):
                continue

            remaining_days = max(0.0, definition.duration_days - state.progress_days)
            remaining_points = max(0.0, definition.research_points_total - state.research_points_awarded)
            if remaining_days <= 1e-9 or remaining_points <= 1e-9:
                self._complete(definition, state, day)
                continue
            intended_day_fraction = min(1.0, remaining_days)
            requested_points = min(remaining_points, definition.points_per_day * intended_day_fraction)
            stored = self.research.store_generated_points(
                requested_points,
                power_by_location=power_by_location,
                day=day,
            )
            if stored <= 1e-12:
                continue
            fraction = stored / definition.points_per_day
            state.progress_days += fraction
            state.research_points_awarded += stored
            if (
                state.progress_days + 1e-9 >= definition.duration_days
                and state.research_points_awarded + 1e-9 >= definition.research_points_total
            ):
                self._complete(definition, state, day)

    def _complete(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
    ) -> None:
        if state.vehicle_id is not None:
            self.logistics.release_vehicle_assignment(
                state.vehicle_id,
                EntityId(f"scientific_exploration:{definition.id}"),
                definition.origin_id if definition.return_to_origin else definition.destination_id,
                available_day=day + 1,
            )
        state.phase = ScientificExplorationPhase.COMPLETE