from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from enum import Enum

from .facilities import FacilityBook
from .inventory import InventoryBook
from .power import PowerService, PowerSnapshot
from .service_capacity import ServiceCapacityRegistry
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .research import ResearchService
from .execution_requirements import (
    ExecutionAllocationPlan, ExecutionRequirementBundle, PoolAdmissionRequirement,
    ReservationAcquisitionRequirement,
)
from .supply import SupplyRequirement
from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import SiteRequirements, evaluate_site_requirements
from .transport.models import FleetActivityRef, MovementExecutionKind, PathPolicy

if TYPE_CHECKING:
    from .transport.service import TransportService


@dataclass(frozen=True)
class ScientificExplorationDefinition:
    id: DefinitionId
    display_name: str
    origin_id: SpatialNodeId
    destination_id: SpatialNodeId
    duration_days: float
    research_points_total: float
    consumable_resources: tuple[tuple[DefinitionId, float], ...] = ()
    origin_requirements: SiteRequirements = SiteRequirements()
    destination_requirements: SiteRequirements = SiteRequirements()
    return_to_origin: bool = False
    required_units: int = 1
    minimum_payload_t: float = 0.0
    required_vehicle_capabilities: tuple[str, ...] = ()
    path_policy: PathPolicy = PathPolicy.BALANCED

    def __post_init__(self) -> None:
        if self.origin_id == self.destination_id:
            raise ValueError("scientific exploration endpoints must differ")
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
        object.__setattr__(self, "path_policy", PathPolicy(self.path_policy))

    @property
    def points_per_day(self) -> float:
        return self.research_points_total / self.duration_days


class ScientificExplorationPhase(str, Enum):
    AWAITING_FLEET = "awaiting_fleet"
    PREPARING = "preparing"
    OUTBOUND = "outbound"
    ACTIVE = "active"
    RETURN_PREPARING = "return_preparing"
    RETURNING = "returning"
    COMPLETE = "complete"


@dataclass
class ScientificExplorationState:
    definition_id: DefinitionId
    phase: ScientificExplorationPhase = ScientificExplorationPhase.AWAITING_FLEET
    vehicle_definition_id: DefinitionId | None = None
    fleet_commitment_id: EntityId | None = None
    progress_days: float = 0.0
    research_points_awarded: float = 0.0
    inputs_consumed: bool = False
    paused: bool = False
    created_day: int = 0
    priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY
    movement_execution_id: EntityId | None = None

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
    service_capacity_registry: ServiceCapacityRegistry
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
        if not self.can_pause(definition_id):
            raise ValueError("scientific exploration cannot be paused in its current phase")
        state = self.campaigns[definition_id]
        state.paused = True

    def resume(self, definition_id: DefinitionId) -> None:
        if not self.can_resume(definition_id):
            raise ValueError("scientific exploration cannot be resumed in its current phase")
        state = self.campaigns[definition_id]
        state.paused = False

    def movement_path(
        self,
        definition: ScientificExplorationDefinition,
        vehicle_definition_id: DefinitionId,
        day: int,
        *,
        reverse: bool = False,
    ):
        origin_id = definition.destination_id if reverse else definition.origin_id
        destination_id = definition.origin_id if reverse else definition.destination_id
        return self.transport.movement_path_for_vehicle(
            origin_id,
            destination_id,
            vehicle_definition_id,
            day=day,
            path_policy=definition.path_policy,
            require_destination_disposition=True,
        )

    def _movement_failures_for_fleet(
        self,
        definition: ScientificExplorationDefinition,
        vehicle_definition_id: DefinitionId,
        day: int,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
    ) -> tuple[str, ...]:
        if self.transport.vehicle_definition(vehicle_definition_id) is None:
            return ("unknown_vehicle_definition",)
        vehicle = self.transport.vehicle_definition(vehicle_definition_id)
        assert vehicle is not None
        failures: list[str] = []
        try:
            outbound = self.movement_path(definition, vehicle_definition_id, day)
        except ValueError as exc:
            return (f"movement_path:{exc}",)

        all_plans = list(outbound)
        return_plans = ()
        if definition.return_to_origin:
            try:
                return_plans = self.movement_path(
                    definition, vehicle_definition_id, day, reverse=True
                )
            except ValueError as exc:
                failures.append(f"return_path:{exc}")
            all_plans.extend(return_plans)

        for plan in all_plans:
            failures.extend(self.transport.movement_plan_failures(plan.id, day))
            failures.extend(
                self.transport.vehicle_movement_failures(
                    plan.id, vehicle_definition_id, day
                )
            )
        usable_payload_t = min(
            (vehicle.max_cargo_for_movement(plan) for plan in all_plans),
            default=0.0,
        )
        if usable_payload_t + 1e-9 < definition.minimum_payload_t:
            failures.append(
                f"payload_capacity:{usable_payload_t:g}/{definition.minimum_payload_t:g}"
            )
        vehicle_capabilities = set(vehicle.generic_capabilities)
        failures.extend(
            f"vehicle_capability:{capability}"
            for capability in sorted(
                set(definition.required_vehicle_capabilities) - vehicle_capabilities
            )
        )
        movement_days = sum(
            self.transport.performance_movement_transit_days(plan, vehicle.performance)
            for plan in all_plans
        )
        failures.extend(
            vehicle.endurance_failures(float(movement_days) + definition.duration_days)
        )
        for prefix, location_id, requirements in (
            ("origin", definition.origin_id, definition.origin_requirements),
            ("destination", definition.destination_id, definition.destination_requirements),
        ):
            for failure in evaluate_site_requirements(
                requirements,
                location_id,
                day,
                self.facilities.environment,
                self.facilities,
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
            self._movement_failures_for_fleet(
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

    def completion_disposition(self, definition_id: DefinitionId) -> str:
        definition = self.definitions[definition_id]
        return (
            "return_to_origin_then_release"
            if definition.return_to_origin
            else "release_at_destination"
        )

    def transition_options(self, definition_id: DefinitionId) -> tuple[str, ...]:
        state = self.campaigns.get(definition_id)
        if state is None:
            return ("start",)
        if state.phase is ScientificExplorationPhase.COMPLETE:
            return ()
        if state.phase is ScientificExplorationPhase.AWAITING_FLEET:
            return ("assign_fleet",)
        if state.phase in {
            ScientificExplorationPhase.OUTBOUND,
            ScientificExplorationPhase.RETURNING,
        }:
            return ("continue",)
        options: list[str] = []
        if state.paused:
            options.append("resume")
        else:
            options.extend(("continue", "pause"))
        if self.can_unassign_fleet(definition_id):
            options.append("unassign_fleet")
        return tuple(options)

    def can_pause(self, definition_id: DefinitionId) -> bool:
        state = self.campaigns.get(definition_id)
        return (
            state is not None
            and state.phase in {ScientificExplorationPhase.PREPARING, ScientificExplorationPhase.ACTIVE, ScientificExplorationPhase.RETURN_PREPARING}
            and not state.paused
        )

    def can_resume(self, definition_id: DefinitionId) -> bool:
        state = self.campaigns.get(definition_id)
        return (
            state is not None
            and state.phase in {ScientificExplorationPhase.PREPARING, ScientificExplorationPhase.ACTIVE, ScientificExplorationPhase.RETURN_PREPARING}
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
            or state.phase is not ScientificExplorationPhase.AWAITING_FLEET
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
            and state.phase is ScientificExplorationPhase.PREPARING
            and state.vehicle_definition_id is not None
            and state.progress_days <= 1e-9
            and not state.inputs_consumed
            and state.movement_execution_id is None
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
        commitment_id = EntityId(f"fleet.commitment.scientific_exploration:{definition_id}")
        self.transport.commit_fleet_units(
            commitment_id,
            FleetActivityRef("scientific_exploration", EntityId(str(definition_id))),
            vehicle_definition_id,
            definition.origin_id,
            definition.required_units,
        )
        state.vehicle_definition_id = vehicle_definition_id
        state.fleet_commitment_id = commitment_id
        state.phase = ScientificExplorationPhase.PREPARING

    def unassign_fleet(self, definition_id: DefinitionId, *, day: int = 0) -> None:
        state = self.campaigns[definition_id]
        if state.phase is ScientificExplorationPhase.COMPLETE:
            raise ValueError("scientific exploration is complete")
        if state.vehicle_definition_id is None:
            return
        if not self.can_unassign_fleet(definition_id):
            raise ValueError("started scientific exploration cannot release its Fleet")
        self.inventory.release_reservation(self._input_reservation_owner_id(definition_id))
        commitment_id = state.fleet_commitment_id
        if commitment_id is None:
            raise RuntimeError("scientific exploration Fleet assignment lacks commitment")
        self.transport.release_fleet_commitment(commitment_id, day=day)
        state.vehicle_definition_id = None
        state.fleet_commitment_id = None
        state.phase = ScientificExplorationPhase.AWAITING_FLEET

    @staticmethod
    def _supply_id(
        definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        resource_id: DefinitionId,
        *,
        returning: bool = False,
    ) -> EntityId:
        leg = "return" if returning else "outbound"
        return EntityId(
            f"requirement.scientific_exploration:{definition_id}:{leg}:"
            f"{operational_node_id}:{resource_id}"
        )

    @staticmethod
    def _input_reservation_owner_id(
        definition_id: DefinitionId, *, returning: bool = False
    ) -> EntityId:
        leg = "return" if returning else "outbound"
        return EntityId(f"scientific_exploration.inputs:{definition_id}:{leg}")

    @staticmethod
    def _reservation_acquisition_id(
        definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        resource_id: DefinitionId,
        *,
        returning: bool = False,
    ) -> EntityId:
        leg = "return" if returning else "outbound"
        return EntityId(
            f"reservation.scientific_exploration:{definition_id}:{leg}:"
            f"{operational_node_id}:{resource_id}"
        )

    @staticmethod
    def execution_bundle_id(definition_id: DefinitionId) -> EntityId:
        return EntityId(f"execution.scientific_exploration:{definition_id}")

    def _preparation_requirements(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
        *,
        returning: bool = False,
    ) -> tuple[tuple[SpatialNodeId, DefinitionId, float, str], ...]:
        if state.vehicle_definition_id is None:
            return ()
        totals: dict[tuple[SpatialNodeId, DefinitionId], tuple[float, str]] = {}
        if not returning:
            for resource_id, amount_t in definition.consumable_resources:
                if amount_t <= 1e-12:
                    continue
                totals[(definition.origin_id, resource_id)] = (
                    totals.get((definition.origin_id, resource_id), (0.0, "campaign_consumables"))[0]
                    + amount_t,
                    "campaign_consumables",
                )
        try:
            plans = self.movement_path(
                definition,
                state.vehicle_definition_id,
                day,
                reverse=returning,
            )
        except ValueError:
            # Route feasibility is reported separately as a blocker. Do not invent
            # operation-resource requirements without a current Movement Plan.
            plans = ()
        if plans:
            for requirement in self.transport.movement_resource_requirements_for_plans(
                state.vehicle_definition_id,
                definition.required_units,
                plans,
                payload_t_per_unit=definition.minimum_payload_t,
            ):
                key = (requirement.operational_node_id, requirement.resource_id)
                current, current_purpose = totals.get(key, (0.0, "movement_resource"))
                purpose = (
                    "campaign_and_movement_resource"
                    if current > 1e-12 and current_purpose != "movement_resource"
                    else "movement_resource"
                )
                totals[key] = (current + requirement.required_t, purpose)
        return tuple(
            (node_id, resource_id, amount_t, purpose)
            for (node_id, resource_id), (amount_t, purpose) in sorted(
                totals.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))
            )
            if amount_t > 1e-12
        )

    def _reserved_preparation_t(
        self,
        definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        resource_id: DefinitionId,
        *,
        returning: bool = False,
    ) -> float:
        return self.inventory.reserved_for(
            self._input_reservation_owner_id(definition_id, returning=returning),
            operational_node_id,
            resource_id,
        )

    def _reserved_input_t(
        self, definition_id: DefinitionId, resource_id: DefinitionId
    ) -> float:
        definition = self.definitions[definition_id]
        return self._reserved_preparation_t(
            definition_id, definition.origin_id, resource_id
        )

    def _preparation_ready(
        self,
        definition_id: DefinitionId,
        day: int,
        *,
        returning: bool = False,
    ) -> bool:
        definition = self.definitions[definition_id]
        state = self.campaigns[definition_id]
        return all(
            self._reserved_preparation_t(
                definition_id, node_id, resource_id, returning=returning
            )
            + 1e-9
            >= amount_t
            for node_id, resource_id, amount_t, _purpose in self._preparation_requirements(
                definition, state, day, returning=returning
            )
        )

    def _inputs_ready(self, definition_id: DefinitionId, day: int = 0) -> bool:
        return self._preparation_ready(definition_id, day)

    def supplys(self, day: int = 0) -> tuple[SupplyRequirement, ...]:
        requirements: list[SupplyRequirement] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            returning = state.phase is ScientificExplorationPhase.RETURN_PREPARING
            if (
                state.phase not in {
                    ScientificExplorationPhase.PREPARING,
                    ScientificExplorationPhase.RETURN_PREPARING,
                }
                or state.paused
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            for node_id, resource_id, amount_t, _purpose in self._preparation_requirements(
                definition, state, day, returning=returning
            ):
                remaining = max(
                    0.0,
                    amount_t
                    - self._reserved_preparation_t(
                        definition_id, node_id, resource_id, returning=returning
                    ),
                )
                if remaining <= 1e-12:
                    continue
                requirements.append(SupplyRequirement(
                    id=self._supply_id(
                        definition_id, node_id, resource_id, returning=returning
                    ),
                    owner_kind="scientific_exploration",
                    owner_id=EntityId(f"scientific_exploration:{definition_id}"),
                    destination_id=node_id,
                    resource_id=resource_id,
                    amount_t=remaining,
                    priority=state.priority,
                ))
        return tuple(requirements)

    def reservation_acquisition_requirements(
        self, day: int = 0
    ) -> tuple[ReservationAcquisitionRequirement, ...]:
        rows: list[ReservationAcquisitionRequirement] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            returning = state.phase is ScientificExplorationPhase.RETURN_PREPARING
            if (
                state.phase not in {
                    ScientificExplorationPhase.PREPARING,
                    ScientificExplorationPhase.RETURN_PREPARING,
                }
                or state.paused
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            owner_id = self._input_reservation_owner_id(
                definition_id, returning=returning
            )
            for node_id, resource_id, amount_t, purpose in self._preparation_requirements(
                definition, state, day, returning=returning
            ):
                missing = max(
                    0.0,
                    amount_t
                    - self._reserved_preparation_t(
                        definition_id, node_id, resource_id, returning=returning
                    ),
                )
                if missing <= 1e-12:
                    continue
                rows.append(ReservationAcquisitionRequirement(
                    id=self._reservation_acquisition_id(
                        definition_id, node_id, resource_id, returning=returning
                    ),
                    owner_id=owner_id,
                    operational_node_id=node_id,
                    resource_id=resource_id,
                    requested_amount=missing,
                    priority=state.priority,
                    purpose=purpose,
                ))
        return tuple(rows)

    def execution_requirement_bundles(
        self, day: int = 0
    ) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if (
                state.phase is not ScientificExplorationPhase.ACTIVE
                or state.paused
                or state.vehicle_definition_id is None
            ):
                continue
            definition = self.definitions[definition_id]
            if self.blockers(definition_id, day=day):
                continue
            remaining = max(0.0, definition.duration_days - state.progress_days)
            requested = min(1.0, remaining)
            if requested <= 1e-12:
                continue
            rows.append(ExecutionRequirementBundle(
                id=self.execution_bundle_id(definition_id),
                owner_kind="scientific_exploration",
                owner_id=EntityId(f"scientific_exploration:{definition_id}"),
                purpose="campaign_execution",
                operational_node_id=definition.destination_id,
                requested_execution=requested,
                priority=state.priority,
                requirements=(
                    PoolAdmissionRequirement(
                        self.research.RESEARCH_POINT_POOL,
                        definition.points_per_day,
                    ),
                ),
            ))
        return tuple(rows)

    def _finalize_reservation_acquisition(
        self, execution_allocations: ExecutionAllocationPlan, day: int
    ) -> None:
        for requirement in self.reservation_acquisition_requirements(day):
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

    def _consume_preparation_if_ready(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
        *,
        returning: bool = False,
    ) -> bool:
        if not returning and state.inputs_consumed:
            return True
        if not self._preparation_ready(definition.id, day, returning=returning):
            return False
        owner_id = self._input_reservation_owner_id(
            definition.id, returning=returning
        )
        for node_id, resource_id, amount_t, _purpose in self._preparation_requirements(
            definition, state, day, returning=returning
        ):
            if amount_t > 1e-12:
                self.inventory.consume_reserved(
                    owner_id, node_id, resource_id, amount_t
                )
        if not returning:
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
        if state is None or state.phase is ScientificExplorationPhase.COMPLETE:
            return ()
        blockers: list[str] = []
        if state.paused and state.phase in {
            ScientificExplorationPhase.PREPARING,
            ScientificExplorationPhase.ACTIVE,
            ScientificExplorationPhase.RETURN_PREPARING,
        }:
            blockers.append("manual_pause")
        if state.vehicle_definition_id is None:
            blockers.append("fleet_unassigned")
            return tuple(blockers)
        if state.phase is ScientificExplorationPhase.PREPARING:
            for node_id, resource_id, amount_t, _purpose in self._preparation_requirements(
                definition, state, day
            ):
                allocated = self._reserved_preparation_t(
                    definition_id, node_id, resource_id
                )
                if allocated + 1e-9 < amount_t:
                    blockers.append(
                        f"resource:{node_id}:{resource_id}:{allocated:g}/{amount_t:g}"
                    )
            blockers.extend(
                self._movement_failures_for_fleet(
                    definition, state.vehicle_definition_id, day, power_by_location
                )
            )
        elif state.phase is ScientificExplorationPhase.RETURN_PREPARING:
            for node_id, resource_id, amount_t, _purpose in self._preparation_requirements(
                definition, state, day, returning=True
            ):
                allocated = self._reserved_preparation_t(
                    definition_id, node_id, resource_id, returning=True
                )
                if allocated + 1e-9 < amount_t:
                    blockers.append(
                        f"resource:{node_id}:{resource_id}:{allocated:g}/{amount_t:g}"
                    )
            try:
                plans = self.movement_path(
                    definition, state.vehicle_definition_id, day, reverse=True
                )
            except ValueError as exc:
                blockers.append(f"return_path:{exc}")
            else:
                for plan in plans:
                    blockers.extend(self.transport.movement_plan_failures(plan.id, day))
                    blockers.extend(
                        self.transport.vehicle_movement_failures(
                            plan.id, state.vehicle_definition_id, day
                        )
                    )
        elif state.phase is ScientificExplorationPhase.ACTIVE:
            snapshot = (
                None
                if power_by_location is None
                else power_by_location.get(definition.destination_id)
            )
            for failure in evaluate_site_requirements(
                definition.destination_requirements,
                definition.destination_id,
                day,
                self.facilities.environment,
                self.facilities,
            ):
                blockers.append(f"destination:{failure.code}:{failure.detail}")
        return tuple(dict.fromkeys(blockers))

    @staticmethod
    def _movement_execution_id(
        definition_id: DefinitionId, *, returning: bool = False
    ) -> EntityId:
        suffix = "return" if returning else "outbound"
        return EntityId(f"movement.scientific_exploration:{definition_id}:{suffix}")

    def _start_outbound(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
    ) -> None:
        assert state.vehicle_definition_id is not None
        plans = self.movement_path(definition, state.vehicle_definition_id, day)
        commitment_id = state.fleet_commitment_id
        if commitment_id is None:
            raise RuntimeError("scientific exploration Fleet assignment lacks commitment")
        execution = self.transport.start_movement_execution_for_path(
            self._movement_execution_id(definition.id),
            EntityId(str(definition.id)),
            MovementExecutionKind.SCIENTIFIC_EXPLORATION,
            commitment_id,
            tuple(plan.id for plan in plans),
            payload_t_per_unit=definition.minimum_payload_t,
            day=day,
        )
        try:
            dispatched = self.transport.dispatch_fleet_commitment(
                commitment_id, execution.id, day=day
            )
        except Exception:
            self.transport.finish_movement_execution(execution.id)
            raise
        if (
            dispatched.vehicle_definition_id != state.vehicle_definition_id
            or dispatched.quantity != definition.required_units
            or dispatched.operational_node_id != definition.origin_id
        ):
            self.transport.finish_movement_execution(execution.id)
            raise RuntimeError("scientific exploration Fleet dispatch mismatch")
        state.movement_execution_id = execution.id
        state.phase = ScientificExplorationPhase.OUTBOUND

    def _start_return(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
    ) -> None:
        assert state.vehicle_definition_id is not None
        plans = self.movement_path(
            definition, state.vehicle_definition_id, day, reverse=True
        )
        commitment_id = state.fleet_commitment_id
        if commitment_id is None:
            raise RuntimeError("scientific exploration Fleet assignment lacks commitment")
        execution = self.transport.start_movement_execution_for_path(
            self._movement_execution_id(definition.id, returning=True),
            EntityId(str(definition.id)),
            MovementExecutionKind.SCIENTIFIC_EXPLORATION,
            commitment_id,
            tuple(plan.id for plan in plans),
            payload_t_per_unit=definition.minimum_payload_t,
            day=day,
        )
        try:
            dispatched = self.transport.dispatch_fleet_commitment(
                commitment_id, execution.id, day=day
            )
        except Exception:
            self.transport.finish_movement_execution(execution.id)
            raise
        if (
            dispatched.vehicle_definition_id != state.vehicle_definition_id
            or dispatched.quantity != definition.required_units
            or dispatched.operational_node_id != definition.destination_id
        ):
            self.transport.finish_movement_execution(execution.id)
            raise RuntimeError("scientific exploration return Fleet dispatch mismatch")
        state.movement_execution_id = execution.id
        state.phase = ScientificExplorationPhase.RETURNING

    def settle_movement_arrivals(self, day: int) -> None:
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if state.phase not in {
                ScientificExplorationPhase.OUTBOUND,
                ScientificExplorationPhase.RETURNING,
            }:
                continue
            execution_id = state.movement_execution_id
            if execution_id is None:
                raise RuntimeError(f"scientific exploration movement state lacks execution: {definition_id}")
            execution = self.transport.movement_execution_snapshot(execution_id)
            if execution is None:
                raise RuntimeError(f"scientific exploration MovementExecution missing: {definition_id}")
            if execution.completion_day > day:
                continue
            definition = self.definitions[definition_id]
            commitment_id = state.fleet_commitment_id
            if commitment_id is None:
                raise RuntimeError("scientific exploration Movement lacks Fleet commitment")
            if state.phase is ScientificExplorationPhase.OUTBOUND:
                self.transport.receive_fleet_commitment(
                    commitment_id,
                    definition.destination_id,
                    execution_id=execution_id,
                    day=day,
                )
                self.transport.finish_movement_execution(execution_id)
                state.movement_execution_id = None
                state.phase = ScientificExplorationPhase.ACTIVE
            else:
                self.transport.receive_fleet_commitment(
                    commitment_id,
                    definition.origin_id,
                    execution_id=execution_id,
                    day=day,
                )
                self.transport.finish_movement_execution(execution_id)
                state.movement_execution_id = None
                self.transport.release_fleet_commitment(commitment_id, day=day)
                state.fleet_commitment_id = None
                state.phase = ScientificExplorationPhase.COMPLETE

    def advance_day(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        execution_allocations: ExecutionAllocationPlan,
        day: int,
    ) -> None:
        ready_at_snapshot = {
            definition_id: self._preparation_ready(
                definition_id,
                day,
                returning=(state.phase is ScientificExplorationPhase.RETURN_PREPARING),
            )
            for definition_id, state in self.campaigns.items()
            if state.phase in {
                ScientificExplorationPhase.PREPARING,
                ScientificExplorationPhase.RETURN_PREPARING,
            }
        }
        # Newly acquired reservations do not make a departure executable
        # retroactively: start eligibility is taken from the tick-start snapshot.
        self._finalize_reservation_acquisition(execution_allocations, day)
        for definition_id, state in sorted(self.campaigns.items(), key=lambda row: str(row[0])):
            if state.vehicle_definition_id is None:
                continue
            definition = self.definitions[definition_id]
            if state.phase is ScientificExplorationPhase.PREPARING:
                if state.paused or not ready_at_snapshot.get(definition_id, False):
                    continue
                if self.blockers(
                    definition_id, day=day, power_by_location=power_by_location
                ):
                    continue
                if not self._consume_preparation_if_ready(definition, state, day):
                    continue
                self._start_outbound(definition, state, day)
                continue
            if state.phase is ScientificExplorationPhase.RETURN_PREPARING:
                if state.paused or not ready_at_snapshot.get(definition_id, False):
                    continue
                if self.blockers(
                    definition_id, day=day, power_by_location=power_by_location
                ):
                    continue
                if not self._consume_preparation_if_ready(
                    definition, state, day, returning=True
                ):
                    continue
                self._start_return(definition, state, day)
                continue
            if state.phase is not ScientificExplorationPhase.ACTIVE or state.paused:
                continue
            if state.progress_days + 1e-9 >= definition.duration_days:
                if definition.return_to_origin:
                    state.phase = ScientificExplorationPhase.RETURN_PREPARING
                else:
                    self._complete_at_destination(definition, state, day)
                continue
            if self.blockers(
                definition_id, day=day, power_by_location=power_by_location
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
            remaining_days = max(0.0, definition.duration_days - state.progress_days)
            remaining_points = max(
                0.0, definition.research_points_total - state.research_points_awarded
            )
            admitted_day_fraction = min(allocated_execution, remaining_days)
            admitted_points = min(
                remaining_points, definition.points_per_day * admitted_day_fraction
            )
            self.research.settle_admitted_points(admitted_points)
            state.progress_days += admitted_day_fraction
            state.research_points_awarded += admitted_points
            if state.progress_days + 1e-9 >= definition.duration_days:
                state.progress_days = definition.duration_days
                if definition.return_to_origin:
                    state.phase = ScientificExplorationPhase.RETURN_PREPARING
                else:
                    self._complete_at_destination(definition, state, day)

    def _complete_at_destination(
        self,
        definition: ScientificExplorationDefinition,
        state: ScientificExplorationState,
        day: int,
    ) -> None:
        commitment_id = state.fleet_commitment_id
        if commitment_id is None:
            raise RuntimeError("scientific exploration completion lacks Fleet commitment")
        self.transport.release_fleet_commitment(commitment_id, day=day)
        state.fleet_commitment_id = None
        state.phase = ScientificExplorationPhase.COMPLETE
