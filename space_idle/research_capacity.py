from __future__ import annotations

from .execution_requirements import (
    ExecutionAllocationPlan,
    ExecutionRequirementBundle,
    PoolAdmissionRequirement,
    pool_admission_constraint,
    pool_constraint,
)
from .power import PowerSnapshot
from .priority import ActivityPriority, DEFAULT_ACTIVITY_PRIORITY
from .service_capacity import ServiceCapacityScope
from .site import evaluate_site_requirements
from .shared import DefinitionId, EntityId, SpatialNodeId
from .transport.models import FleetActivityRef
from .research_models import ResearchProviderSourceKind


class ResearchCapacityMixin:
    RESEARCH_POINT_POOL = "research_points"

    def _facility_provider(self, facility_id):
        facility = self.facilities.facilities[facility_id]
        matches = tuple(
            provider
            for provider in self.providers.values()
            if provider.source_kind is ResearchProviderSourceKind.FACILITY
            and provider.source_definition_id == facility.definition_id
        )
        if len(matches) > 1:
            raise RuntimeError(
                f"multiple Research Providers reference facility definition: {facility.definition_id}"
            )
        return matches[0] if matches else None

    def facility_provider_spec(self, facility_id: EntityId):
        """Return the Research Provider represented by a Facility State, if any."""
        return self._facility_provider(facility_id)

    def _provider_factor(
        self,
        facility_id,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> float:
        facility = self.facilities.facilities[facility_id]
        if not self.facilities.is_active_and_compatible(facility, day):
            return 0.0
        provider = self._facility_provider(facility_id)
        if provider is None:
            return 0.0
        if evaluate_site_requirements(
            provider.site_requirements,
            facility.operational_node_id,
            day,
            self.facilities.environment,
            self.facilities,
            environment_context_id=self.facilities.facility_environment_context(facility),
        ):
            return 0.0
        snapshot = power_by_location.get(facility.operational_node_id)
        if snapshot is None:
            # Missing allocation data means a nominal query, not permission to
            # run a private Power allocation outside the tick DAG.
            return 1.0
        return max(
            0.0,
            min(
                1.0,
                snapshot.utilization_by_facility.get(facility.id, 1.0)
                * snapshot.maintenance_factor_by_facility.get(facility.id, 1.0),
            ),
        )

    def _provider_level_spec(self, facility_id):
        facility = self.facilities.facilities[facility_id]
        provider = self._facility_provider(facility_id)
        return None if provider is None else provider.level_spec(facility.level)

    def facility_provider_blockers(
        self,
        facility_id: EntityId,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> tuple[tuple[str, str], ...]:
        facility = self.facilities.facilities[facility_id]
        provider = self._facility_provider(facility_id)
        if provider is None:
            raise ValueError(f"facility is not a Research Provider: {facility_id}")
        blockers = list(self.facilities.activation_failures(facility, day))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in evaluate_site_requirements(
                provider.site_requirements,
                facility.operational_node_id,
                day,
                self.facilities.environment,
                self.facilities,
                environment_context_id=self.facilities.facility_environment_context(facility),
            )
        )
        snapshot = power_by_location.get(facility.operational_node_id)
        if not blockers and snapshot is not None:
            utilization = max(
                0.0,
                min(1.0, snapshot.utilization_by_facility.get(facility.id, 1.0)),
            )
            maintenance = max(
                0.0,
                min(1.0, snapshot.maintenance_factor_by_facility.get(facility.id, 1.0)),
            )
            if utilization < 1.0 - 1e-9:
                blockers.append(("power", "研究設備への電力配分不足"))
            if maintenance < 1.0 - 1e-9:
                blockers.append(("maintenance", "研究設備の維持資源充足率不足"))
        return tuple(blockers)

    def provider_generation(
        self,
        facility_id,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> float:
        spec = self._provider_level_spec(facility_id)
        if spec is None:
            return 0.0
        return spec.generation_points_per_day * self._provider_factor(
            facility_id, power_by_location, day
        )

    def provider_storage_capacity(
        self,
        facility_id,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> float:
        spec = self._provider_level_spec(facility_id)
        if spec is None:
            return 0.0
        return spec.storage_capacity_points * self._provider_factor(
            facility_id, power_by_location, day
        )

    @staticmethod
    def provider_assignment_commitment_id(assignment_id: EntityId) -> EntityId:
        return EntityId(f"fleet.commitment.research_provider:{assignment_id}")

    def provider_assignment_site_failures(
        self,
        provider_definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        *,
        day: int = 0,
    ):
        provider = self.providers.get(provider_definition_id)
        if provider is None:
            raise KeyError(provider_definition_id)
        if provider.source_kind is not ResearchProviderSourceKind.FLEET:
            raise ValueError("Research Provider assignment requires a Fleet-backed provider")
        if not self.facilities.environment.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        return evaluate_site_requirements(
            provider.site_requirements,
            operational_node_id,
            day,
            self.facilities.environment,
            self.facilities,
        )

    def create_provider_assignment(
        self,
        provider_definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        quantity: int,
        *,
        priority: ActivityPriority = DEFAULT_ACTIVITY_PRIORITY,
        day: int = 0,
    ) -> EntityId:
        provider = self.providers.get(provider_definition_id)
        if provider is None:
            raise KeyError(provider_definition_id)
        if provider.source_kind is not ResearchProviderSourceKind.FLEET:
            raise ValueError("Research Provider assignment requires a Fleet-backed provider")
        if not self.facilities.environment.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        if quantity <= 0:
            raise ValueError("Research Provider assignment quantity must be positive")
        site_failures = self.provider_assignment_site_failures(
            provider_definition_id, operational_node_id, day=day
        )
        if site_failures:
            raise ValueError("; ".join(f"{row.code}: {row.detail}" for row in site_failures))
        next_counter = self._provider_assignment_counter + 1
        assignment_id = EntityId(f"research.provider_assignment.{next_counter}")
        commitment_id = self.provider_assignment_commitment_id(assignment_id)
        # Fleet owns quantity. This call is atomic and fails before Research State
        # is created if there are insufficient free units.
        self.transport.commit_fleet_units(
            commitment_id,
            FleetActivityRef("research_provider_assignment", assignment_id),
            provider.source_definition_id,
            operational_node_id,
            quantity,
        )
        self._provider_assignment_counter = next_counter
        from .research import ResearchProviderAssignmentState
        self.provider_assignments[assignment_id] = ResearchProviderAssignmentState(
            id=assignment_id,
            provider_definition_id=provider_definition_id,
            vehicle_definition_id=provider.source_definition_id,
            operational_node_id=operational_node_id,
            priority=priority,
            paused=False,
            fleet_commitment_ref=commitment_id,
        )
        return assignment_id

    def resize_provider_assignment(self, assignment_id: EntityId, quantity: int) -> None:
        assignment = self.provider_assignments[assignment_id]
        if quantity <= 0:
            raise ValueError("Research Provider assignment quantity must be positive")
        self.transport.resize_fleet_commitment(assignment.fleet_commitment_ref, quantity)

    def set_provider_assignment_priority(
        self, assignment_id: EntityId, priority: ActivityPriority
    ) -> None:
        self.provider_assignments[assignment_id].priority = ActivityPriority(priority)

    def pause_provider_assignment(self, assignment_id: EntityId) -> None:
        self.provider_assignments[assignment_id].paused = True

    def resume_provider_assignment(self, assignment_id: EntityId) -> None:
        self.provider_assignments[assignment_id].paused = False

    def release_provider_assignment(self, assignment_id: EntityId, *, day: int = 0) -> None:
        assignment = self.provider_assignments[assignment_id]
        self.transport.release_fleet_commitment(assignment.fleet_commitment_ref, day=day)
        del self.provider_assignments[assignment_id]

    def provider_assignment_quantity(self, assignment_id: EntityId) -> int:
        assignment = self.provider_assignments[assignment_id]
        snapshot = self.transport.fleet_commitment_snapshot(assignment.fleet_commitment_ref)
        if snapshot is None:
            raise RuntimeError(f"Research Provider assignment lost Fleet commitment: {assignment_id}")
        return snapshot.quantity

    def provider_assignment_research_execution(
        self, assignment_id: EntityId, *, day: int = 0
    ) -> float:
        if self.provider_assignment_blockers(assignment_id, day=day):
            return 0.0
        assignment = self.provider_assignments[assignment_id]
        provider = self.providers[assignment.provider_definition_id]
        if assignment.vehicle_definition_id != provider.source_definition_id:
            raise RuntimeError(f"Research Provider assignment vehicle mismatch: {assignment_id}")
        return (
            provider.level_spec(1).research_execution_per_day
            * self.provider_assignment_quantity(assignment_id)
        )

    def provider_assignment_blockers(
        self, assignment_id: EntityId, *, day: int = 0
    ) -> tuple[tuple[str, str], ...]:
        assignment = self.provider_assignments[assignment_id]
        provider = self.providers[assignment.provider_definition_id]
        blockers: list[tuple[str, str]] = []
        if assignment.paused:
            blockers.append(("manual_pause", "Research Provider assignment is paused"))
        blockers.extend(
            (failure.code, failure.detail)
            for failure in evaluate_site_requirements(
                provider.site_requirements,
                assignment.operational_node_id,
                day,
                self.facilities.environment,
                self.facilities,
            )
        )
        return tuple(blockers)

    def _fleet_assignment_rates(
        self, assignment_id: EntityId, *, day: int = 0
    ) -> tuple[float, float]:
        assignment = self.provider_assignments[assignment_id]
        provider = self.providers[assignment.provider_definition_id]
        if provider.source_kind is not ResearchProviderSourceKind.FLEET:
            raise RuntimeError("Research Provider assignment references non-Fleet provider")
        if assignment.vehicle_definition_id != provider.source_definition_id:
            raise RuntimeError(f"Research Provider assignment vehicle mismatch: {assignment_id}")
        site_failures = self.provider_assignment_site_failures(
            assignment.provider_definition_id, assignment.operational_node_id, day=day
        )
        if site_failures:
            return (0.0, 0.0)
        quantity = self.provider_assignment_quantity(assignment_id)
        # Fleet-backed definitions use level 1 as the per-unit contribution.
        spec = provider.level_spec(1)
        return (
            0.0 if assignment.paused else spec.generation_points_per_day * quantity,
            spec.storage_capacity_points * quantity,
        )

    def service_capacity_types(self) -> tuple[str, ...]:
        return ("research_execution",)

    def service_capacity_scope(self, service_type: str) -> ServiceCapacityScope:
        if service_type != "research_execution":
            raise KeyError(service_type)
        return ServiceCapacityScope.ORGANIZATION

    def service_capacity_provider_definition_ids(
        self, service_type: str
    ) -> frozenset[DefinitionId]:
        if service_type != "research_execution":
            raise KeyError(service_type)
        return frozenset(
            provider.source_definition_id
            for provider in self.providers.values()
            if provider.source_kind is ResearchProviderSourceKind.FACILITY
        )

    def service_capacity_upstream_services(self, service_type: str) -> frozenset[str]:
        if service_type != "research_execution":
            raise KeyError(service_type)
        return frozenset()

    def service_capacity_supply_at(
        self, operational_node_id: SpatialNodeId, service_type: str, facilities, power,
        day: int = 0, *, provider_factors=None,
    ) -> tuple[float, float]:
        if service_type != "research_execution":
            return (0.0, 0.0)
        nominal = 0.0
        enabled = 0.0
        for facility in sorted(
            self.facilities.active_compatible_at(operational_node_id, day),
            key=lambda row: str(row.id),
        ):
            provider = self._facility_provider(facility.id)
            if provider is None:
                continue
            if evaluate_site_requirements(
                provider.site_requirements,
                facility.operational_node_id,
                day,
                self.facilities.environment,
                self.facilities,
                environment_context_id=self.facilities.facility_environment_context(facility),
            ):
                continue
            level = provider.level_spec(facility.level)
            nominal += level.research_execution_per_day
            factor = 1.0 if power is None else self._provider_factor(
                facility.id, {operational_node_id: power}, day
            )
            enabled += level.research_execution_per_day * factor
        for assignment_id, assignment in sorted(
            self.provider_assignments.items(), key=lambda row: str(row[0])
        ):
            if assignment.operational_node_id != operational_node_id:
                continue
            if self.provider_assignment_blockers(assignment_id, day=day):
                continue
            provider = self.providers[assignment.provider_definition_id]
            quantity = self.provider_assignment_quantity(assignment_id)
            rate = provider.level_spec(1).research_execution_per_day * quantity
            nominal += rate
            enabled += rate
        return (nominal, nominal if power is None else enabled)

    def generation_rate(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
        day: int = 0,
    ) -> float:
        snapshots = {} if power_by_location is None else power_by_location
        facility_generation = sum(
            self.provider_generation(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if self._facility_provider(facility.id) is not None
        )
        fleet_generation = sum(
            self._fleet_assignment_rates(assignment_id, day=day)[0]
            for assignment_id in self.provider_assignments
        )
        return facility_generation + fleet_generation

    def storage_capacity(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
        day: int = 0,
    ) -> float:
        snapshots = {} if power_by_location is None else power_by_location
        facility_capacity = sum(
            self.provider_storage_capacity(facility.id, snapshots, day)
            for facility in self.facilities.facilities.values()
            if self._facility_provider(facility.id) is not None
        )
        fleet_capacity = sum(
            self._fleet_assignment_rates(assignment_id, day=day)[1]
            for assignment_id in self.provider_assignments
        )
        return facility_capacity + fleet_capacity

    def allocation_pool_capacities(self, day: int):
        """Expose authoritative RP stock and nominal admission headroom."""
        return {
            pool_constraint(self.RESEARCH_POINT_POOL, scope_id="organization"): self.stored_points,
            pool_admission_constraint(self.RESEARCH_POINT_POOL, scope_id="organization"): max(
                0.0, self.storage_capacity(None, day) - self.stored_points
            ),
        }

    def allocation_pool_capacity_overrides(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int,
    ) -> dict:
        return {
            pool_admission_constraint(self.RESEARCH_POINT_POOL, scope_id="organization"): max(
                0.0, self.storage_capacity(power_by_location, day) - self.stored_points
            )
        }

    @staticmethod
    def _facility_generation_bundle_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"execution.research_provider:facility:{facility_id}")

    @staticmethod
    def _assignment_generation_bundle_id(assignment_id: EntityId) -> EntityId:
        return EntityId(f"execution.research_provider:fleet:{assignment_id}")

    def generation_execution_bundles(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot],
        day: int = 0,
    ) -> tuple[ExecutionRequirementBundle, ...]:
        rows: list[ExecutionRequirementBundle] = []
        for facility in sorted(self.facilities.facilities.values(), key=lambda row: str(row.id)):
            provider = self._facility_provider(facility.id)
            if provider is None:
                continue
            requested = self.provider_generation(facility.id, power_by_location, day)
            if requested <= 1e-12:
                continue
            rows.append(ExecutionRequirementBundle(
                id=self._facility_generation_bundle_id(facility.id),
                owner_kind="research_provider",
                owner_id=facility.id,
                purpose="research_point_generation",
                operational_node_id=None,
                requested_execution=requested,
                priority=facility.activity_priority,
                requirements=(PoolAdmissionRequirement(self.RESEARCH_POINT_POOL, 1.0),),
            ))
        for assignment_id, assignment in sorted(
            self.provider_assignments.items(), key=lambda row: str(row[0])
        ):
            requested, _capacity = self._fleet_assignment_rates(assignment_id, day=day)
            if requested <= 1e-12:
                continue
            rows.append(ExecutionRequirementBundle(
                id=self._assignment_generation_bundle_id(assignment_id),
                owner_kind="research_provider",
                owner_id=assignment_id,
                purpose="research_point_generation",
                operational_node_id=None,
                requested_execution=requested,
                priority=assignment.priority,
                requirements=(PoolAdmissionRequirement(self.RESEARCH_POINT_POOL, 1.0),),
            ))
        return tuple(rows)

    def settle_generated_points(self, execution: ExecutionAllocationPlan) -> float:
        generated = 0.0
        for bundle in execution.bundles:
            if bundle.owner_kind != "research_provider" or bundle.purpose != "research_point_generation":
                continue
            generated += execution.allocated(bundle.id)
        self.stored_points += generated
        return generated

    def store_generated_points(
        self,
        points: float,
        *,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
        day: int = 0,
    ) -> float:
        """Store external RP producers not yet migrated to common admission.

        Scientific Exploration remains on this boundary until its dedicated
        canonical migration. Normal Research Providers settle through the
        common PoolAdmission allocation above.
        """
        if points < -1e-9:
            raise ValueError("generated research points must be non-negative")
        capacity = self.storage_capacity(power_by_location, day)
        free = max(0.0, capacity - self.stored_points)
        accepted = min(max(0.0, points), free)
        self.stored_points += accepted
        return accepted

    def is_over_capacity(
        self,
        power_by_location: dict[SpatialNodeId, PowerSnapshot] | None = None,
        day: int = 0,
    ) -> bool:
        return self.stored_points > self.storage_capacity(power_by_location, day) + 1e-9
