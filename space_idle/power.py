from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from .facilities import FacilityBook, FacilityState
from .service_capacity import ServiceCapacityRequest, allocate_service_capacity
from .shared import DefinitionId, EntityId, SpatialNodeId
from .spatial import EnvironmentResolver, IlluminationField


@dataclass(frozen=True)
class FixedGeneration:
    mw: float


@dataclass(frozen=True)
class SolarGeneration:
    rated_mw_at_reference_flux: float
    reference_flux_w_m2: float


GenerationModel: TypeAlias = FixedGeneration | SolarGeneration


@dataclass(frozen=True)
class PowerSpec:
    generation: GenerationModel | None = None
    load_mw: float = 0.0
    default_priority: int = 50
    # Load required even while the facility is manually paused (e.g.
    # cryogenic hold, containment, safe-state control). It never produces
    # active domain output or capability while paused.
    standby_load_mw: float = 0.0


@dataclass(frozen=True)
class PowerPhysicalSnapshot:
    operational_node_id: SpatialNodeId
    generation_mw_by_facility: dict[EntityId, float]
    requests: tuple[ServiceCapacityRequest, ...]
    demand_mw: float

    @property
    def nominal_generation_mw(self) -> float:
        return sum(self.generation_mw_by_facility.values())


@dataclass(frozen=True)
class PowerSnapshot:
    generation_mw: float
    demand_mw: float
    allocated_mw: float
    utilization_by_facility: dict[EntityId, float]
    maintenance_factor_by_facility: dict[EntityId, float]

    @property
    def site_utilization(self) -> float:
        if self.demand_mw <= 1e-9:
            return 1.0
        return min(1.0, self.allocated_mw / self.demand_mw)


@dataclass
class PowerService:
    SERVICE_TYPE = "power"

    @staticmethod
    def _request_id(facility_id: EntityId) -> EntityId:
        return EntityId(f"service.power:{facility_id}")

    specs: dict[DefinitionId, PowerSpec]
    environment: EnvironmentResolver

    def _generation(self, spec: PowerSpec, facility: FacilityState, facilities: FacilityBook, day: int) -> float:
        model = spec.generation
        if model is None:
            return 0.0
        if isinstance(model, FixedGeneration):
            return model.mw
        context_id = facilities.facility_environment_context(facility)
        illumination = self.environment.get(context_id, IlluminationField, day)
        if illumination is None:
            return 0.0
        return (
            model.rated_mw_at_reference_flux
            * illumination.solar_flux_w_m2
            / model.reference_flux_w_m2
            * illumination.availability
        )

    def physical_snapshot(
        self, operational_node_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> PowerPhysicalSnapshot:
        """Capture nominal power supply and load intent before allocation."""
        requests: list[ServiceCapacityRequest] = []
        generation_by_facility: dict[EntityId, float] = {}
        demand = 0.0
        for facility in facilities.all_at(operational_node_id):
            if not facilities.is_environmentally_compatible(facility, day):
                continue
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            if not facility.paused:
                generation_by_facility[facility.id] = self._generation(
                    spec, facility, facilities, day
                )
            load = spec.standby_load_mw if facility.paused else spec.load_mw
            if load > 0:
                priority = (
                    facility.power_priority
                    if facility.power_priority is not None
                    else spec.default_priority
                )
                requests.append(ServiceCapacityRequest(
                    self._request_id(facility.id),
                    operational_node_id,
                    self.SERVICE_TYPE,
                    load,
                    priority,
                    "facility",
                    facility.id,
                    "power_load",
                ))
                demand += load
        return PowerPhysicalSnapshot(
            operational_node_id,
            generation_by_facility,
            tuple(requests),
            demand,
        )

    def resolve_snapshot(
        self,
        physical: PowerPhysicalSnapshot,
        maintenance_factors: dict[EntityId, float] | None = None,
    ) -> PowerSnapshot:
        """Resolve current-tick power from physical state and upstream allocation."""
        factors = maintenance_factors or {}
        facility_ids = (
            set(factors)
            | set(physical.generation_mw_by_facility)
            | {request.owner_id for request in physical.requests}
        )
        resolved_factors = {
            facility_id: max(0.0, min(1.0, factors.get(facility_id, 1.0)))
            for facility_id in facility_ids
        }
        generation = sum(
            amount * resolved_factors.get(facility_id, 1.0)
            for facility_id, amount in physical.generation_mw_by_facility.items()
        )
        plan = allocate_service_capacity(
            physical.requests,
            nominal_supply={(physical.operational_node_id, self.SERVICE_TYPE): generation},
        )
        utilization: dict[EntityId, float] = {}
        allocated = 0.0
        for request in physical.requests:
            amount = plan.allocated(request.id)
            allocated += amount
            utilization[request.owner_id] = (
                1.0
                if request.requested_rate <= 1e-12
                else max(0.0, min(1.0, amount / request.requested_rate))
            )
        return PowerSnapshot(
            generation,
            physical.demand_mw,
            allocated,
            utilization,
            resolved_factors,
        )

    def snapshot(
        self, operational_node_id: SpatialNodeId, facilities: FacilityBook, day: int
    ) -> PowerSnapshot:
        """Resolve a nominal standalone snapshot without transient maintenance state.

        Simulation execution supplies current-tick maintenance fulfillment through
        ``resolve_snapshot``. Direct callers receive a dependency-neutral snapshot
        and therefore cannot accidentally reuse a previous tick's allocation.
        """
        return self.resolve_snapshot(
            self.physical_snapshot(operational_node_id, facilities, day)
        )
