from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .shared import DefinitionId, EntityId, SpatialNodeId
from .site import EnvironmentCondition
from .spatial import EnvironmentResolver

if TYPE_CHECKING:
    from .power import PowerSnapshot


@dataclass(frozen=True)
class CapabilitySupply:
    """A facility-provided qualitative service with a rated capacity.

    The rating is intentionally unitless at this layer. Domain systems such as
    survey, construction and manufacturing retain their own physical rates.
    This supply only expresses whether enough infrastructure/service capacity
    exists to satisfy generic prerequisites.
    """
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


@dataclass
class FacilityState:
    id: EntityId
    definition_id: DefinitionId
    location_id: SpatialNodeId
    paused: bool = False
    power_priority: int | None = None
    level: int = 1

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError("facility level must be positive")


@dataclass
class FacilityBook:
    definitions: dict[DefinitionId, FacilityDef]
    environment: EnvironmentResolver
    facilities: dict[EntityId, FacilityState] = field(default_factory=dict)
    _counter: int = 0

    def install(
        self,
        definition_id: DefinitionId,
        location_id: SpatialNodeId,
        *,
        power_priority: int | None = None,
        level: int = 1,
    ) -> EntityId:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if location_id not in self.environment.graph.nodes:
            raise KeyError(location_id)
        if level < 1:
            raise ValueError("facility level must be positive")
        self._counter += 1
        entity_id = EntityId(f"facility.{self._counter}")
        self.facilities[entity_id] = FacilityState(
            entity_id, definition_id, location_id, False, power_priority, level
        )
        return entity_id

    def upgrade_to(self, facility_id: EntityId, target_level: int) -> None:
        """Apply one completed level transition without assigning generic level effects."""
        facility = self.facilities[facility_id]
        if target_level != facility.level + 1:
            raise ValueError(
                f"facility level transition must be sequential: {facility.level} -> {target_level}"
            )
        facility.level = target_level

    def pause(self, facility_id: EntityId) -> None:
        self.facilities[facility_id].paused = True

    def resume(self, facility_id: EntityId) -> None:
        self.facilities[facility_id].paused = False

    def set_power_priority(self, facility_id: EntityId, priority: int | None) -> None:
        self.facilities[facility_id].power_priority = priority

    def all_at(self, location_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.facilities.values() if f.location_id == location_id]

    def active_at(self, location_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.all_at(location_id) if not f.paused]

    def environment_failures(self, facility: FacilityState, day: int) -> tuple[tuple[str, str], ...]:
        definition = self.definitions[facility.definition_id]
        failures: list[tuple[str, str]] = []
        for condition in definition.operating_environment:
            if not condition.matches(self.environment, facility.location_id, day):
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

    def _capacity_from_facilities(self, facilities: list[FacilityState], capability_id: str) -> float:
        total = 0.0
        for facility in facilities:
            definition = self.definitions[facility.definition_id]
            total += sum(supply.rated_capacity for supply in definition.capability_supplies if supply.id == capability_id)
        return total

    def infrastructure_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, day: int = 0) -> float:
        facilities = [f for f in self.all_at(location_id) if self.is_environmentally_compatible(f, day)]
        return self._capacity_from_facilities(facilities, capability_id)

    def active_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, day: int = 0) -> float:
        return self._capacity_from_facilities(self.active_compatible_at(location_id, day), capability_id)

    def available_capability_capacity_at(self, location_id: SpatialNodeId, capability_id: str, power: PowerSnapshot, day: int = 0) -> float:
        total = 0.0
        for facility in self.active_compatible_at(location_id, day):
            definition = self.definitions[facility.definition_id]
            utilization = max(0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0)))
            for supply in definition.capability_supplies:
                if supply.id == capability_id:
                    total += supply.rated_capacity * utilization
        return total

    def capability_ids(self) -> set[str]:
        return {supply.id for definition in self.definitions.values() for supply in definition.capability_supplies}
