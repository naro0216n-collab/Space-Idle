from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from enum import Enum

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .research import ResearchService
from .execution_requirements import (
    ExecutionAllocationPlan, ExecutionRequirementBundle, ReservationAcquisitionRequirement,
)
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
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY

    def __post_init__(self) -> None:
        self.priority = ActivityPriority(self.priority)


@dataclass
class ScientificExplorationService:
    definitions: dict[DefinitionId, ScientificExplorationDefinition]
    facilities: FacilityBook
    inventory: InventoryBook
    power: PowerService
    transport: "TransportService"
    research: ResearchService
    campaigns: dict[DefinitionId, ScientificExplorationState] = field(default_factory=dict)

    def start(
        self, definition_id: DefinitionId, *, day: int = 0,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
    ) -> None:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if not self.can_start(definition_id):
            raise ValueError("scientific exploration campaign already started")
        self.campaigns[definition_id] = ScientificExplorationState(
            definition_id=definition_id,
            created_day=day,
            priority=priority,
        )

    def set_priority(self, definition_id: DefinitionId, priority: ActivityPriority) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("completed scientific exploration priority cannot change")
        state.priority = ActivityPriority(priority)

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
        self.inventory.release_reservation(self._input_reservation_owner_id(definition_id))
        reservation_id = EntityId(f"scientific_exploration:{definition_id}")
        self.transport.release_fleet_reservation(reservation_id, day=day)
        state.vehicle_definition_id = None
        state.reserved_units = 0
        state.phase = ScientificExplorationPhase.AWAITING_FLEET

    @staticmethod
    def _resource_demand_id(definition_id: DefinitionId, resource_id: DefinitionId) -> EntityId:
        return EntityId(f"demand.scientific_exploration:{definition_id}:{resource_id}")

    @staticmethod
    def _input_reservation_owner_id(definition_id: DefinitionId) -> EntityId:
        return EntityId(f"scientific_exploration.inputs:{definition_id}")

    @staticmethod
    def _reservation_acquisition_id(
        definition_id: DefinitionId, resource_id: DefinitionId
    ) -> EntityId:
        return EntityId(f"reservation.scientific_exploration:{definition_id}:{resource_id}")

    @staticmethod
    def execution_bundle_id(definition_id: DefinitionId) -> EntityId:
        return EntityId(f"execution.scientific_exploration:{definition_id}")

    def _reserved_input_t(
        self, definition_id: DefinitionId, resource_id: DefinitionId
    ) -> float:
        definition = self.definitions[definition_id]
        return self.inventory.reserved_for(
            self._input_reservation_owner_id(definition_id),
            definition.origin_id,
            resource_id,
        )

    def _inputs_ready(self, definition_id: DefinitionId) -> bool:
        definition = self.definitions[definition_id]
        return all(
            self._reserved_input_t(definition_id, resource_id) + 1e-9 >= amount_t
            for resource_id, amount_t in definition.consumable_resources
            if amount_t > 1e-12
        )

    def resource_demands(self, day: int = 0) -> tuple[ResourceDemand, ...]:
        del day
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
                remaining = max(0.0, amount_t - self._reserved_input_t(definition_id, resource_id))
                if remaining <= 1e-12:
                    continue
                demands.append(ResourceDemand(
                    self._resource_demand_id(definition_id, resource_id),
                    "scientific_exploration",
                    EntityId(f"scientific_exploration:{definition_id}"),
                    definition.origin_id,
                    resource_id,
                    remaining,
                    state.priority,
                    None,
                ))
        return tuple(demands)

    def reservation_acquisition_requirements(
        self, day: int = 0
    ) -> tuple[ReservationAcquisitionRequirement, ...]:
        del day
        rows: list[ReservationAcquisitionRequirement] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.inputs_consumed
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            owner_id = self._input_reservation_owner_id(definition_id)
            for resource_id, amount_t in sorted(definition.consumable_resources, key=lambda row: str(row[0])):
                missing = max(0.0, amount_t - self._reserved_input_t(definition_id, resource_id))
                if missing <= 1e-12:
                    continue
                rows.append(ReservationAcquisitionRequirement(
                    id=self._reservation_acquisition_id(definition_id, resource_id),
                    owner_id=owner_id,
                    operational_node_id=definition.origin_id,
                    resource_id=resource_id,
                    requested_amount=missing,
                    priority=state.priority,
                    purpose="campaign_consumables",
                ))
        return tuple(rows)

    def execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        del day
        rows: list[ExecutionRequirementBundle] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.vehicle_definition_id is None
                or (not state.inputs_consumed and not self._inputs_ready(definition_id))
            ):
                continue
            definition = self.definitions[definition_id]
            remaining = max(0.0, definition.duration_days - state.progress_days)
            requested = min(1.0, remaining)
            if requested <= 1e-12:
                continue
            rows.append(ExecutionRequirementBundle(
                id=self.execution_bundle_id(definition_id),
                owner_kind="scientific_exploration",
                owner_id=EntityId(f"scientific_exploration:{definition_id}"),
                purpose="campaign_execution",
                operational_node_id=definition.origin_id,
                requested_execution=requested,
                priority=state.priority,
            ))
        return tuple(rows)

    def _finalize_reservation_acquisition(
        self, execution_allocations: ExecutionAllocationPlan
    ) -> None:
        for requirement in self.reservation_acquisition_requirements():
            try:
                allocated = execution_allocations.allocated(requirement.id)
            except KeyError:
                allocated = 0.0
            amount = min(requirement.requested_amount, max(0.0, allocated))
            if amount <= 1e-12:
                continue
            taken = self.inventory.reserve(
                requirement.owner_id,
                requirement.operational_node_id,
                requirement.resource_id,
                amount,
            )
            if taken + 1e-9 < amount:
                raise RuntimeError("allocated exploration reservation stock changed before execution")

    def _consume_inputs_if_ready(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
    ) -> bool:
        if state.inputs_consumed:
            return True
        if not self._inputs_ready(definition.id):
            return False
        owner_id = self._input_reservation_owner_id(definition.id)
        for resource_id, amount_t in definition.consumable_resources:
            if amount_t > 1e-12:
                self.inventory.consume_reserved(
                    owner_id, definition.origin_id, resource_id, amount_t
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
                allocated = self._reserved_input_t(definition_id, resource_id)
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
        execution_allocations: ExecutionAllocationPlan,
        day: int,
    ) -> None:
        # Newly acquired reservations do not make the campaign executable
        # retroactively: execution bundles were generated from the tick-start snapshot.
        self._finalize_reservation_acquisition(execution_allocations)
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if state.phase is not ScientificExplorationPhase.ACTIVE or state.paused or state.vehicle_definition_id is None:
                continue
            definition = self.definitions[definition_id]
            if self.blockers(
                definition_id,
                day=day,
                power_by_location=power_by_location,
            ):
                continue
            try:
                allocated_execution = execution_allocations.allocated(
                    self.execution_bundle_id(definition_id)
                )
            except KeyError:
                allocated_execution = 0.0
            if allocated_execution <= 1e-12:
                continue
            if not self._consume_inputs_if_ready(definition, state):
                continue

            remaining_days = max(0.0, definition.duration_days - state.progress_days)
            remaining_points = max(0.0, definition.research_points_total - state.research_points_awarded)
            if remaining_days <= 1e-9 or remaining_points <= 1e-9:
                self._complete(definition, state, day)
                continue
            intended_day_fraction = min(allocated_execution, remaining_days)
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
