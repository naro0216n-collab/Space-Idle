from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from .facilities import FacilityBook
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
    specs: dict[DefinitionId, PowerSpec]
    environment: EnvironmentResolver

    def _generation(self, spec: PowerSpec, location_id: SpatialNodeId, day: int) -> float:
        model = spec.generation
        if model is None:
            return 0.0
        if isinstance(model, FixedGeneration):
            return model.mw
        illumination = self.environment.get(location_id, IlluminationField, day)
        if illumination is None:
            return 0.0
        return (
            model.rated_mw_at_reference_flux
            * illumination.solar_flux_w_m2
            / model.reference_flux_w_m2
            * illumination.availability
        )

    def snapshot(self, location_id: SpatialNodeId, facilities: FacilityBook, day: int) -> PowerSnapshot:
        rows: list[tuple[int, EntityId, float]] = []
        generation = 0.0
        demand = 0.0
        maintenance_factors: dict[EntityId, float] = {}
        for facility in facilities.all_at(location_id):
            if not facilities.is_environmentally_compatible(facility, day):
                continue
            spec = self.specs.get(facility.definition_id)
            if spec is None:
                continue
            maintenance = facilities.maintenance_factor(facility.id)
            maintenance_factors[facility.id] = maintenance
            if not facility.paused:
                generation += self._generation(spec, location_id, day) * maintenance
            load = spec.standby_load_mw if facility.paused else spec.load_mw
            if load > 0:
                priority = facility.power_priority if facility.power_priority is not None else spec.default_priority
                rows.append((priority, facility.id, load))
                demand += load

        remaining = generation
        utilization: dict[EntityId, float] = {}
        allocated = 0.0
        # Priority is a player decision; entity installation order is not. All
        # loads in the same priority band therefore share any shortfall
        # proportionally.
        priorities = sorted({priority for priority, _facility_id, _load in rows}, reverse=True)
        for priority in priorities:
            group = [(facility_id, load) for p, facility_id, load in rows if p == priority]
            group_demand = sum(load for _facility_id, load in group)
            if group_demand <= 1e-12:
                continue
            factor = min(1.0, max(0.0, remaining) / group_demand)
            for facility_id, load in sorted(group, key=lambda x: str(x[0])):
                use = load * factor
                allocated += use
                utilization[facility_id] = factor
            remaining = max(0.0, remaining - group_demand * factor)
        return PowerSnapshot(generation, demand, allocated, utilization, maintenance_factors)
