from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import TYPE_CHECKING, Callable, Mapping

from .shared import DefinitionId, EntityId, SpatialNodeId, SurfaceCellId
from .site import EnvironmentCondition
from .spatial import EnvironmentResolver, SpatialContextId

if TYPE_CHECKING:
    from .power import PowerSnapshot


class FacilityPlacementScope(str, Enum):
    OPERATIONAL_NODE = "OPERATIONAL_NODE"
    SURFACE_CELL = "SURFACE_CELL"


@dataclass(frozen=True)
class CapabilitySupply:
    """Categorical function/interface supplied by a facility."""
    id: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("capability id must not be empty")


@dataclass(frozen=True)
class ServiceCapacitySupply:
    """Finite per-tick flow supplied by a facility before allocation."""
    service_type: str
    nominal_rate: float

    def __post_init__(self) -> None:
        if not self.service_type:
            raise ValueError("service type must not be empty")
        if self.nominal_rate <= 0:
            raise ValueError("service capacity nominal rate must be positive")


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
    placement_scope: FacilityPlacementScope = FacilityPlacementScope.OPERATIONAL_NODE
    service_capacity_supplies: tuple[ServiceCapacitySupply, ...] = ()

    def __post_init__(self) -> None:
        if self.maintenance_fraction_per_year < 0:
            raise ValueError("facility maintenance fraction must be non-negative")
        if not isinstance(self.placement_scope, FacilityPlacementScope):
            raise ValueError("facility placement scope must be a FacilityPlacementScope")


@dataclass
class FacilityState:
    id: EntityId
    definition_id: DefinitionId
    operational_node_id: SpatialNodeId
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
    service_availability_factor_provider: Callable[[SpatialNodeId, str, "PowerSnapshot", int], Mapping[EntityId, float]] | None = field(
        default=None, repr=False, compare=False
    )

    def placement_failures(
        self,
        definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        site_cell_id: SurfaceCellId | None = None,
    ) -> tuple[tuple[str, str], ...]:
        if definition_id not in self.definitions:
            return (("unknown_facility_definition", f"unknown facility definition: {definition_id}"),)
        if not self.environment.graph.has_operational_node(operational_node_id):
            return (("unknown_location", f"unknown operational node: {operational_node_id}"),)
        definition = self.definitions[definition_id]
        if definition.placement_scope is FacilityPlacementScope.OPERATIONAL_NODE:
            if site_cell_id is not None:
                return (("site_cell_not_allowed", "OPERATIONAL_NODE facility must not specify a surface cell"),)
            return ()
        if site_cell_id is None:
            return (("site_cell_required", "SURFACE_CELL facility requires a surface cell"),)
        location = self.environment.graph.locations.get(operational_node_id)
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
        operational_node_id: SpatialNodeId,
        site_cell_id: SurfaceCellId | None = None,
    ) -> SpatialContextId:
        failures = self.placement_failures(definition_id, operational_node_id, site_cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        definition = self.definitions[definition_id]
        if definition.placement_scope is FacilityPlacementScope.OPERATIONAL_NODE:
            return operational_node_id
        assert site_cell_id is not None
        return site_cell_id

    def facility_environment_context(self, facility: FacilityState) -> SpatialContextId:
        return self.placement_context(facility.definition_id, facility.operational_node_id, facility.site_cell_id)

    def install(
        self,
        definition_id: DefinitionId,
        operational_node_id: SpatialNodeId,
        *,
        site_cell_id: SurfaceCellId | None = None,
        power_priority: int | None = None,
        maintenance_priority: int = 50,
        level: int = 1,
        invested_resources: Mapping[DefinitionId, float] | None = None,
    ) -> EntityId:
        if definition_id not in self.definitions:
            raise KeyError(definition_id)
        if not self.environment.graph.has_operational_node(operational_node_id):
            raise KeyError(operational_node_id)
        placement_failures = self.placement_failures(definition_id, operational_node_id, site_cell_id)
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
            operational_node_id=operational_node_id,
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

    def all_at(self, operational_node_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.facilities.values() if f.operational_node_id == operational_node_id]

    def active_at(self, operational_node_id: SpatialNodeId) -> list[FacilityState]:
        return [f for f in self.all_at(operational_node_id) if not f.paused]

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

    def active_compatible_at(self, operational_node_id: SpatialNodeId, day: int) -> list[FacilityState]:
        return [f for f in self.all_at(operational_node_id) if self.is_active_and_compatible(f, day)]

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

    @staticmethod
    def _definition_has_capability(definition: FacilityDef, capability_id: str) -> bool:
        return any(supply.id == capability_id for supply in definition.capability_supplies)

    def installed_capability_at(self, operational_node_id: SpatialNodeId, capability_id: str) -> bool:
        """Whether the physical function/interface exists at the node.

        Installed capability is categorical and does not disappear because a
        facility is paused, unpowered, or temporarily environment-incompatible.
        """
        return any(
            self._definition_has_capability(self.definitions[facility.definition_id], capability_id)
            for facility in self.all_at(operational_node_id)
        )

    def active_capability_at(self, operational_node_id: SpatialNodeId, capability_id: str, day: int = 0) -> bool:
        """Whether an installed function is currently active as a category."""
        return any(
            self._definition_has_capability(self.definitions[facility.definition_id], capability_id)
            for facility in self.active_compatible_at(operational_node_id, day)
        )

    def nominal_service_capacity_at(
        self, operational_node_id: SpatialNodeId, service_type: str, day: int = 0
    ) -> float:
        contributions: list[float] = []
        for facility in sorted(
            self.active_compatible_at(operational_node_id, day), key=lambda row: str(row.id)
        ):
            definition = self.definitions[facility.definition_id]
            contributions.extend(
                supply.nominal_rate
                for supply in definition.service_capacity_supplies
                if supply.service_type == service_type
            )
        return math.fsum(contributions)

    def enabled_service_capacity_at(
        self,
        operational_node_id: SpatialNodeId,
        service_type: str,
        power: "PowerSnapshot",
        day: int = 0,
    ) -> float:
        """Provider flow enabled by already-resolved upstream dependencies.

        This adapter currently exposes power, maintenance and upstream surface
        infrastructure factors.  It is an allocation input; consumers must
        still submit ServiceCapacityRequest and cannot independently consume
        this value.
        """
        contributions: list[float] = []
        service_factors = (
            {}
            if self.service_availability_factor_provider is None
            else self.service_availability_factor_provider(
                operational_node_id, service_type, power, day
            )
        )
        for facility in sorted(
            self.active_compatible_at(operational_node_id, day), key=lambda row: str(row.id)
        ):
            definition = self.definitions[facility.definition_id]
            utilization = max(
                0.0, min(1.0, power.utilization_by_facility.get(facility.id, 1.0))
            )
            maintenance = max(
                0.0,
                min(
                    1.0,
                    power.maintenance_factor_by_facility.get(
                        facility.id, self.maintenance_factor(facility.id)
                    ),
                ),
            )
            upstream = max(0.0, min(1.0, service_factors.get(facility.id, 1.0)))
            for supply in definition.service_capacity_supplies:
                if supply.service_type == service_type:
                    contributions.append(
                        supply.nominal_rate * utilization * maintenance * upstream
                    )
        return math.fsum(contributions)

    def capability_ids(self) -> set[str]:
        return {
            supply.id
            for definition in self.definitions.values()
            for supply in definition.capability_supplies
        }

    def service_types(self) -> set[str]:
        return {
            supply.service_type
            for definition in self.definitions.values()
            for supply in definition.service_capacity_supplies
        }
