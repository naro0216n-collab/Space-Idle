from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Mapping

from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import EnvironmentCondition
from .spatial import EnvironmentResolver, SpatialContextId

if TYPE_CHECKING:
    from .power import PowerSnapshot


class FacilityPlacementScope(str, Enum):
    LOCATION = "LOCATION"
    SURFACE_CELL = "SURFACE_CELL"


@dataclass(frozen=True)
class CapabilitySupply:
    """A facility-provided qualitative service with a rated capacity."""
    id: str
    rated_capacity: float = 1.0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("capability id must not be empty")
        if self.rated_capacity <= 0:
            raise ValueError("capability rated capacity must be positive")


@dataclass(frozen=True)
class FacilityDef:
    id: DefinitionId
    display_name: str
    capability_supplies: tuple[CapabilitySupply, ...] = ()
    installation_environment: tuple[EnvironmentCondition, ...] = ()
    operating_environment: tuple[EnvironmentCondition, ...] = ()
    # Fraction of cumulative construction/upgrade resource investment required
    # per game year. The value is content balance; Core only supplies the rule.
    maintenance_fraction_per_year: float = 0.0
    placement_scope: FacilityPlacementScope = FacilityPlacementScope.LOCATION

    def __post_init__(self) -> None:
        if self.maintenance_fraction_per_year < 0:
            raise ValueError("facility maintenance fraction must be non-negative")
        if not isinstance(self.placement_scope, FacilityPlacementScope):
            raise ValueError("facility placement scope must be a FacilityPlacementScope")


@dataclass
class FacilityState:
    id: EntityId
    definition_id: DefinitionId
    location_id: SpatialNodeId
    paused: bool = False
    power_priority: int | None = None
    maintenance_priority: int = 50
    level: int = 1
    invested_resources: dict[DefinitionId, float] = field(default_factory=dict)
    maintenance_satisfaction: float = 1.0
    site_cell_id: SurfaceCellId | None = None

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError("facility level must be positive")
        if any(amount < 0 for amount in self.invested_resources.values()):
            raise ValueError("facility invested resources must be non-negative")
        if not 0.0 <= self.maintenance_satisfaction <= 1.0:
            raise ValueError("facility maintenance satisfaction must be in 0..1")


@dataclass
class FacilityBook:
    definitions: dict[DefinitionId, FacilityDef]
    environment: EnvironmentResolver
    facilities: dict[EntityId, FacilityState] = field(default_factory=dict)
    _counter: int = 0

    def placement_failures(
        self,
        definition_id: DefinitionId,
        location_id: SpatialNodeId,
        site_cell_id: SurfaceCellId | None = None,
    ) -> tuple[tuple[str, str], ...]:
        if definition_id not in self.definitions:
            return (("unknown_facility_definition", f"unknown facility definition: {definition_id}"),)
        if not self.environment.graph.has_operational_node(location_id):
            return (("unknown_location", f"unknown facility location: {location_id}"),)
        definition = self.definitions[definition_id]
        if definition.placement_scope is FacilityPlacementScope.LOCATION:
            if site_cell_id is not None:
                return (("site_cell_not_allowed", "LOCATION facility must not specify a surface cell"),)
            return ()
        if site_cell_id is None:
            return (("site_cell_required", "SURFACE_CELL facility requires a surface cell"),)
        location = self.environment.graph.locations.get(location_id)
        if location is None:
            return (("surface_location_required", "SURFACE_CELL facility requires a surface Location"),)
        cell = self.environment.graph.surface_cells.get(site_cell_id)
        if cell is None:
            return (("unknown_site_cell", f"unknown surface cell: {site_cell_id}"),)
        if cell.body_id != location.body_id:
            return (("site_cell_body_mismatch", "surface cell belongs to another celestial body"),)
        if site_cell_id not in location.developed_cell_ids:
            return (("site_cell_not_developed", "surface cell is not developed by the facility Location"),)
        return ()

    def placement_context(
        self,
        definition_id: DefinitionId,
        location_id: SpatialNodeId,
        site_cell_id: SurfaceCellId | None = None,
    ) -> SpatialContextId:
        failures = self.placement_failures(definition_id, location_id, site_cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        definition = self.definitions[definition_id]
        if definition.placement_scope is FacilityPlacementScope.LOCATION:
            return location_id
        assert site_cell_id is not None
        return site_cell_id

    def facility_environment_context(self, facility: FacilityState) -> SpatialContextId:
        return self.placement_context(facility.definition_id, facility.location_id, facility.site_cell_id)

    def install(
        self,
        definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        site_cell_id: SurfaceCellId | None = None,
        power_priority: int | None = None,
        maintenance_priority: int = 50,
        level: int = 1,
        invested_resources: Mapping[DefinitionId, float] | None = None,
    ) -> EntityId:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if not self.environment.graph.has_operational_node(location_id):
            raise KeyError(location_id)
        placement_failures = self.placement_failures(definition_id, location_id, site_cell_id)
        if placement_failures:
            if placement_failures[0][0] == "unknown_site_cell":
                raise KeyError(site_cell_id)
            raise ValueError("; ".join(detail for _code, detail in placement_failures))
        if level < 1:
            raise ValueError("facility level must be positive")
        investment = dict(invested_resources or {})
        if any(amount < 0 for amount in investment.values()):
            raise ValueError("facility invested resources must be non-negative")
        self._counter += 1
        entity_id = EntityId(f"facility.{self._counter}")
        self.facilities[entity_id] = FacilityState(
            id=entity_id,
            definition_id=definition_id,
            location_id=location_id,
            paused=False,
            power_priority=power_priority,
            maintenance_priority=maintenance_priority,
            level=level,
            invested_resources=investment,
            maintenance_satisfaction=1.0,
            site_cell_id=site_cell_id,
        )
        return entity_id

    def upgrade_to(
        self,
        facility_id: EntityId,
        target_level: int,
        *,
        invested_resources: Mapping[DefinitionId, float] | None = None,
    ) -> None:
        """Apply one completed level transition and retain physical investment history."""
        facility = self.facilities[facility_id]
        if target_level != facility.level + 1:
            raise ValueError(
                f"facility level transition must be sequential: {facility.level} -> {target_level}"
            )
        for resource_id, amount in (invested_resources or {}).items():
            if amount < 0:
                raise ValueError("facility invested resources must be non-negative")
            facility.invested_resources[resource_id] = facility.invested_resources.get(resource_id, 0.0) + amount
        facility.level = target_level

    def pause(self, facility_id: EntityId) -> None:
        self.facilities[facility_id].paused = True

    def resume(self, facility_id: EntityId) -> None:
        self.facilities[facility_id].paused = False

    def set_power_priority(self, facility_id: EntityId, priority: int | None) -> None:
        self.facilities[facility_id].power_priority = priority

    def set_maintenance_priority(self, facility_id: EntityId, priority: int) -> None:
        self.facilities[facility_id].maintenance_priority = priority

    def all_at(self, location_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.facilities.values() if f.location_id == location_id]

    def active_at(self, location_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.all_at(location_id) if not f.paused]

    def environment_failures(self, facility: FacilityState, day: int) -> tuple[tuple[str, str], ...]:
        definition = self.definitions[facility.definition_id]
        failures: list[tuple[str, str]] = []
        context_id = self.facility_environment_context(facility)
        for condition in definition.operating_environment:
            if not condition.matches(self.environment, context_id, day):
                failures.append((condition.code, condition.description))
        return tuple(failures)

    def is_environmentally_compatible(self, facility: FacilityState, day: int) -> bool:
        return not self.environment_failures(facility, day)

    def activation_failures(self, facility: FacilityState, day: int) -> tuple[tuple[str, str], ...]:
        failures: list[tuple[str, str]] = []
        if facility.paused:
            failures.append(("manual_pause", "設備が手動停止中"))
        failures.extend(self.environment_failures(facility, day))
        return tuple(failures)

    def is_active_and_compatible(self, facility: FacilityState, day: int) -> bool:
        return not self.activation_failures(facility, day)

    def active_compatible_at(self, location_id: SpatialNodeId, day: int) -> list[FacilityState]:
        return [f for f in self.all_at(location_id) if self.is_active_and_compatible(f, day)]

    def maintenance_requirements_per_day(self, facility_id: EntityId) -> dict[DefinitionId, float]:
        facility = self.facilities[facility_id]
        fraction = self.definitions[facility.definition_id].maintenance_fraction_per_year
        if fraction <= 1e-12:
            return {}
        return {
            resource_id: amount * fraction / 365.0
            for resource_id, amount in facility.invested_resources.items()
            if amount > 1e-12
        }

    def maintenance_factor(self, facility_id: EntityId) -> float:
        return max(0.0, min(1.0, self.facilities[facility_id].maintenance_satisfaction))

    def _capacity_from_facilities(self, facilities: list[FacilityState], capability_id: str, *, maintenance: bool = False) -> float:
        total = 0.0
        for facility in facilities:
            definition = self.definitions[facility.definition_id]
            factor = self.maintenance_factor(facility.id) if maintenance else 1.0
            total += sum(supply.rated_capacity * factor for supply in definition.capability_supplies if supply.id == capability_id)
        return total

    def infrastructure_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, day: int = 0) -> float:
        facilities = [f for f in self.all_at(location_id) if self.is_environmentally_compatible(f, day)]
        return self._capacity_from_facilities(facilities, capability_id)

    def active_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, day: int = 0) -> float:
        # Active is rated capacity before transient power/maintenance allocation.
        return self._capacity_from_facilities(self.active_compatible_at(location_id, day), capability_id)

    def available_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, power: PowerSnapshot, day: int = 0) -> float:
        total = 0.0
        for facility in self.active_compatible_at(location_id, day):
            definition = self.definitions[facility.definition_id]
            utilization = max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            factor = utilization * power.maintenance_factor_by_facility.get(
                facility.id, self.maintenance_factor(facility.id)
            )
            for supply in definition.capability_supplies:
                if supply.id == capability_id:
                    total += supply.rated_capacity * factor
        return total

    def capability_ids(self) -> set[str]:
        return {supply.id for definition in self.definitions.values() for supply in definition.capability_supplies}
