from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from enum import Enum

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .research import ResearchService
from .resource_claim import ResourceAllocationPlan, ResourceClaim
from .resource_demand import ResourceDemand
from .shared import DefinitionId, EntityId, RouteId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements
from .transport.models import FleetReservationKind, RouteDef, RouteEndpoint, TransportOperationRequirement

if TYPE_CHECKING:
    from .transport.service import TransportService


@dataclass(frozen=True)
class ScientificExplorationDefinition:
    id: DefinitionId
    display_name: str
    origin: RouteEndpoint
    destination: RouteEndpoint
    operations: tuple[TransportOperationRequirement, ...]
    mission_duration_days: int
    duration_days: float
    research_points_total: float
    consumable_resources: tuple[tuple[DefinitionId, float], ...] = ()
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()
    return_to_origin: bool = False
    required_units: int = 1
    minimum_payload_t: float = 0.0
    required_vehicle_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mission_duration_days <= 0:
            raise ValueError("scientific exploration mission duration must be positive")
        if self.duration_days <= 0:
            raise ValueError("scientific exploration campaign duration must be positive")
        if self.research_points_total <= 0:
            raise ValueError("scientific exploration reward must be positive")
        if any(amount < 0 for _resource, amount in self.consumable_resources):
            raise ValueError("scientific exploration consumables must be non-negative")
        if self.required_units <= 0:
            raise ValueError("scientific exploration required units must be positive")
        if self.minimum_payload_t < 0:
            raise ValueError("scientific exploration minimum payload must be non-negative")

    @property
    def origin_id(self) -> SpatialNodeId:
        return self.origin.node_id

    @property
    def destination_id(self) -> SpatialNodeId:
        return self.destination.node_id

    @property
    def points_per_day(self) -> float:
        return self.research_points_total / self.duration_days

    def compatibility_route(self) -> RouteDef:
        return RouteDef(
            RouteId(f"exploration.route:{self.id}"),
            self.origin,
            self.destination,
            self.mission_duration_days,
            self.operations,
            display_name=self.display_name,
            origin_requirements=self.origin_requirements,
            destination_requirements=self.destination_requirements,
        )


class ScientificExplorationPhase(str, Enum):
    AWAITING_FLEET = "awaiting_fleet"
    ACTIVE = "active"
    COMPLETE = "complete"


@dataclass
class ScientificExplorationState:
    definition_id: DefinitionId
    phase: ScientificExplorationPhase = ScientificExplorationPhase.AWAITING_FLEET
    vehicle_definition_id: DefinitionId | None = None
    reserved_units: int = 0
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
    transport: "TransportService"
    research: ResearchService
    campaigns: dict[DefinitionId, ScientificExplorationState] = field(default_factory=dict)

    def start(self, definition_id: DefinitionId, *, day: int = 0) -> None:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if not self.can_start(definition_id):
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

    def _route_failures_for_fleet(
        self,
        definition: ScientificExplorationDefinition,
        vehicle_definition_id: DefinitionId,
        day: int,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        route = definition.compatibility_route()
        failures = list(
            self.transport.fleet_campaign_failures(
                vehicle_definition_id,
                route,
                activity_days=definition.duration_days,
                return_to_origin=definition.return_to_origin,
                minimum_payload_t=definition.minimum_payload_t,
                required_vehicle_capabilities=definition.required_vehicle_capabilities,
                day=day,
            )
        )
        for prefix, location_id, requirements in (
            ("origin", definition.origin_id, definition.origin_requirements),
            ("destination", definition.destination_id, definition.destination_requirements),
        ):
            snapshot = (
                None if power_by_location is None else power_by_location.get(location_id)
            )
            for failure in evaluate_site_requirements(
                requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
                snapshot,
            ):
                failures.append(f"{prefix}:{failure.code}:{failure.detail}")
        return tuple(dict.fromkeys(failures))

    def fleet_failures(
        self,
        definition_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        definition = self.definitions[definition_id]
        if self.transport.vehicle_definition(vehicle_definition_id) is None:
            return ("unknown_vehicle_definition",)
        failures = list(
            self._route_failures_for_fleet(
                definition,
                vehicle_definition_id,
                day,
                power_by_location,
            )
        )
        free = self.transport.fleet_free_units(
            vehicle_definition_id, definition.origin_id
        )
        if free < definition.required_units:
            failures.append(f"fleet_units:{free}/{definition.required_units}")
        return tuple(dict.fromkeys(failures))

    def can_start(self, definition_id: DefinitionId) -> bool:
        return definition_id in self.definitions and definition_id not in self.campaigns

    def can_pause(self, definition_id: DefinitionId) -> bool:
        state = self.campaigns.get(definition_id)
        return (
            state is not None
            and state.phase is not ScientificExplorationPhase.COMPLETE
            and not state.paused
        )

    def can_resume(self, definition_id: DefinitionId) -> bool:
        state = self.campaigns.get(definition_id)
        return (
            state is not None
            and state.phase is not ScientificExplorationPhase.COMPLETE
            and state.paused
        )

    def can_assign_fleet(
        self,
        definition_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> bool:
        state = self.campaigns.get(definition_id)
        if (
            state is None
            or state.phase is ScientificExplorationPhase.COMPLETE
            or state.vehicle_definition_id is not None
        ):
            return False
        return not self.fleet_failures(
            definition_id,
            vehicle_definition_id,
            day=day,
            power_by_location=power_by_location,
        )

    def can_unassign_fleet(self, definition_id: DefinitionId) -> bool:
        state = self.campaigns.get(definition_id)
        return (
            state is not None
            and state.phase is not ScientificExplorationPhase.COMPLETE
            and state.vehicle_definition_id is not None
            and state.progress_days <= 1e-9
            and not state.inputs_consumed
        )

    def assign_fleet(
        self,
        definition_id: DefinitionId,
        vehicle_definition_id: DefinitionId,
        *,
        day: int = 0,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("scientific exploration is complete")
        if state.vehicle_definition_id is not None:
            raise ValueError("scientific exploration already has Fleet assigned")
        failures = self.fleet_failures(
            definition_id,
            vehicle_definition_id,
            day=day,
            power_by_location=power_by_location,
        )
        if failures:
            raise ValueError(
                "Fleet is not compatible with scientific exploration: "
                + "; ".join(failures)
            )
        definition = self.definitions[definition_id]
        reservation_id = EntityId(f"scientific_exploration:{definition_id}")
        self.transport.reserve_fleet_units(
            reservation_id,
            reservation_id,
            FleetReservationKind.SCIENTIFIC_EXPLORATION,
            vehicle_definition_id,
            definition.origin_id,
            definition.required_units,
        )
        state.vehicle_definition_id = vehicle_definition_id
        state.reserved_units = definition.required_units
        state.phase = ScientificExplorationPhase.ACTIVE

    def unassign_fleet(self, definition_id: DefinitionId, *, day: int = 0) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("scientific exploration is complete")
        if state.vehicle_definition_id is None:
            return
        if not self.can_unassign_fleet(definition_id):
            raise ValueError("started scientific exploration cannot release its Fleet")
        definition = self.definitions[definition_id]
        self._restore_staged_inputs(definition)
        reservation_id = EntityId(f"scientific_exploration:{definition_id}")
        self.transport.release_fleet_reservation(reservation_id, day=day)
        state.vehicle_definition_id = None
        state.reserved_units = 0
        state.phase = ScientificExplorationPhase.AWAITING_FLEET

    @staticmethod
    def _resource_demand_id(definition_id: DefinitionId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.scientific_exploration:{definition_id}:{resource_id}")

    @staticmethod
    def _resource_claim_id(definition_id: DefinitionId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"claim.scientific_exploration:{definition_id}:{resource_id}")

    @staticmethod
    def _input_staging_owner_id(definition_id: DefinitionId) -> EntityId:
        return EntityId(f"scientific_exploration.inputs:{definition_id}")

    def _staged_input_t(
        self, definition_id: DefinitionId, resource_id: DefinitionId
    ) -> float:
        definition = self.definitions[definition_id]
        return self.inventory.staged_for(
            self._input_staging_owner_id(definition_id),
            definition.origin_id,
            resource_id,
        )

    def _stage_input_allocations(
        self,
        definition: ScientificExplorationDefinition,
        allocations: ResourceAllocationPlan,
    ) -> None:
        staging_owner = self._input_staging_owner_id(definition.id)
        for resource_id, amount_t in definition.consumable_resources:
            if amount_t <= 1e-12:
                continue
            staged = self._staged_input_t(definition.id, resource_id)
            missing = max(0.0, amount_t - staged)
            if missing <= 1e-12:
                continue
            try:
                allocated = allocations.allocated(
                    self._resource_claim_id(definition.id, resource_id)
                )
            except KeyError:
                allocated = 0.0
            amount = min(missing, max(0.0, allocated))
            if amount > 1e-12:
                self.inventory.stage_allocated(
                    staging_owner, definition.origin_id, resource_id, amount
                )

    def _restore_staged_inputs(
        self, definition: ScientificExplorationDefinition
    ) -> None:
        staging_owner = self._input_staging_owner_id(definition.id)
        for resource_id, _amount_t in definition.consumable_resources:
            staged = self._staged_input_t(definition.id, resource_id)
            if staged > 1e-12:
                self.inventory.unstage_to_stock(
                    staging_owner, definition.origin_id, resource_id, staged
                )

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        demands: list[ResourceDemand] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.inputs_consumed
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            for resource_id, amount_t in sorted(definition.consumable_resources, key=lambda row: str(row[0])):
                remaining = max(
                    0.0, amount_t - self._staged_input_t(definition_id, resource_id)
                )
                if remaining <= 1e-12:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(definition_id, resource_id),
                    "scientific_exploration",
                    EntityId(f"scientific_exploration:{definition_id}"),
                    definition.origin_id,
                    resource_id,
                    remaining,
                    70,
                    None,
                ))
        return tuple(demands)

    def resource_claims(self, day: int = 0) -> tuple[ResourceClaim, ...]:
        claims: list[ResourceClaim] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.inputs_consumed
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            for resource_id, amount_t in sorted(
                definition.consumable_resources, key=lambda row: str(row[0])
            ):
                staged = self._staged_input_t(definition_id, resource_id)
                remaining = max(0.0, amount_t - staged)
                if remaining <= 1e-12:
                    continue
                claims.append(ResourceClaim(
                    self._resource_claim_id(definition_id, resource_id),
                    definition.origin_id,
                    resource_id,
                    remaining,
                    70,
                    "scientific_exploration",
                    EntityId(f"scientific_exploration:{definition_id}"),
                    "campaign_consumables",
                    demand_id=self._resource_demand_id(definition_id, resource_id),
                ))
        return tuple(claims)

    def _consume_inputs_if_ready(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
    ) -> bool:
        if state.inputs_consumed:
            return True
        resources = tuple((rid, amount) for rid, amount in definition.consumable_resources if amount > 1e-12)
        if not all(
            self._staged_input_t(definition.id, rid) + 1e-9 >= amount
            for rid, amount in resources
        ):
            return False
        staging_owner = self._input_staging_owner_id(definition.id)
        for resource_id, _amount_t in resources:
            staged = self._staged_input_t(definition.id, resource_id)
            if staged > 1e-12:
                self.inventory.release_storage_occupancy(
                    staging_owner, definition.origin_id, resource_id, staged
                )
        state.inputs_consumed = True
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
        if state.vehicle_definition_id is None:
            blockers.append("fleet_unassigned")
            return tuple(blockers)
        if not state.inputs_consumed:
            for resource_id, amount_t in definition.consumable_resources:
                allocated = self._staged_input_t(definition_id, resource_id)
                if allocated + 1e-9 < amount_t:
                    blockers.append(f"resource:{resource_id}:{allocated:g}/{amount_t:g}")
        blockers.extend(
            self._route_failures_for_fleet(
                definition,
                state.vehicle_definition_id,
                day,
                power_by_location,
            )
        )
        return tuple(blockers)

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        resource_allocations: ResourceAllocationPlan,
        day: int,
    ) -> None:
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if state.phase is not ScientificExplorationPhase.ACTIVE or state.paused or state.vehicle_definition_id is None:
                continue
            definition = self.definitions[definition_id]
            self._stage_input_allocations(definition, resource_allocations)
            if self.blockers(
                definition_id,
                day=day,
                power_by_location=power_by_location,
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
            self.research.store_generated_points(
                requested_points,
                power_by_location=power_by_location,
                day=day,
            )
            # Campaign work is physical/scientific activity, not RP storage.
            # A full RP pool constrains how much reward can be retained, but it
            # must not freeze a finite campaign or hold its Fleet indefinitely.
            state.progress_days += intended_day_fraction
            state.research_points_awarded += requested_points
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
        if state.vehicle_definition_id is not None:
            reservation_id = EntityId(f"scientific_exploration:{definition.id}")
            final_location_id = (
                definition.origin_id
                if definition.return_to_origin
                else definition.destination_id
            )
            self.transport.complete_fleet_reservation(
                reservation_id,
                final_location_id=final_location_id,
                day=day,
            )
        state.phase = ScientificExplorationPhase.COMPLETE
