from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, dist, isfinite, radians, sin, sqrt
from enum import Enum
from typing import Any, ClassVar, Mapping, Protocol, TypeAlias, TypeVar, cast

from .shared import CelestialBodyId, DefinitionId, SpatialNodeId, StarSystemId, SurfaceCellId

FacetT = TypeVar("FacetT", bound="SpatialFacet")
SpatialContextId: TypeAlias = SpatialNodeId | SurfaceCellId


class EnvironmentFieldScope(str, Enum):
    """Where a Physical Environment field is authoritative."""

    BODY_GLOBAL = "BODY_GLOBAL"
    SURFACE_CELL_LOCAL = "SURFACE_CELL_LOCAL"
    BODY_WITH_CELL_OVERLAY = "BODY_WITH_CELL_OVERLAY"
    CONTEXT_LOCAL = "CONTEXT_LOCAL"


class SpatialFacet:
    """Typed Physical Environment field definition.

    Each concrete field owns its scope/composition contract.  The resolver uses
    that contract generically instead of maintaining a facet-name allowlist.
    """

    facet_key: ClassVar[str]
    environment_scope: ClassVar[EnvironmentFieldScope]


@dataclass(frozen=True)
class GravityField(SpatialFacet):
    facet_key: ClassVar[str] = "gravity"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.BODY_GLOBAL
    local_acceleration_m_s2: float
    escape_velocity_m_s: float | None = None

    def __post_init__(self) -> None:
        if self.local_acceleration_m_s2 < 0 or (
            self.escape_velocity_m_s is not None and self.escape_velocity_m_s < 0
        ):
            raise ValueError("gravity values must be non-negative")


@dataclass(frozen=True)
class AtmosphereField(SpatialFacet):
    facet_key: ClassVar[str] = "atmosphere"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.BODY_GLOBAL
    pressure_pa: float
    density_kg_m3: float
    composition: Mapping[DefinitionId, float]

    def __post_init__(self) -> None:
        if self.pressure_pa < 0 or self.density_kg_m3 < 0 or any(
            v < 0 for v in self.composition.values()
        ):
            raise ValueError("atmosphere values must be non-negative")


@dataclass(frozen=True)
class IlluminationField(SpatialFacet):
    facet_key: ClassVar[str] = "illumination"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.SURFACE_CELL_LOCAL
    solar_flux_w_m2: float
    availability: float = 1.0

    def __post_init__(self) -> None:
        if self.solar_flux_w_m2 < 0 or not 0 <= self.availability <= 1:
            raise ValueError("invalid illumination values")


@dataclass(frozen=True)
class ThermalField(SpatialFacet):
    facet_key: ClassVar[str] = "thermal"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY
    nominal_temperature_k: float
    min_temperature_k: float | None = None
    max_temperature_k: float | None = None

    def __post_init__(self) -> None:
        values = [self.nominal_temperature_k]
        if self.min_temperature_k is not None:
            values.append(self.min_temperature_k)
        if self.max_temperature_k is not None:
            values.append(self.max_temperature_k)
        if any(v < 0 for v in values):
            raise ValueError("temperatures must be non-negative")
        if (
            self.min_temperature_k is not None
            and self.max_temperature_k is not None
            and self.min_temperature_k > self.max_temperature_k
        ):
            raise ValueError("minimum temperature cannot exceed maximum")


@dataclass(frozen=True)
class SurfaceTerrain:
    """Static terrain/geology descriptors owned by SurfaceCellDef."""
    terrain_factor: float = 1.0
    bearing_capacity_factor: float = 1.0
    dust_factor: float = 0.0
    slope_factor: float = 0.0

    def __post_init__(self) -> None:
        if min(
            self.terrain_factor,
            self.bearing_capacity_factor,
            self.dust_factor,
            self.slope_factor,
        ) < 0:
            raise ValueError("surface factors must be non-negative")


@dataclass(frozen=True)
class OrbitalField(SpatialFacet):
    facet_key: ClassVar[str] = "orbit"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.CONTEXT_LOCAL
    orbital_period_s: float | None = None

    def __post_init__(self) -> None:
        if self.orbital_period_s is not None and self.orbital_period_s <= 0:
            raise ValueError("orbital period must be positive")


@dataclass(frozen=True)
class CommunicationField(SpatialFacet):
    facet_key: ClassVar[str] = "communication"
    environment_scope: ClassVar[EnvironmentFieldScope] = EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY
    baseline_latency_s: float
    availability: float = 1.0

    def __post_init__(self) -> None:
        if self.baseline_latency_s < 0 or not 0 <= self.availability <= 1:
            raise ValueError("invalid communication values")


class SpatialNodeKind(str, Enum):
    GENERIC = "generic"
    # Kept as a projection value for player-operated surface Locations. Static
    # surface geography itself is represented by SurfaceCellDef, not a node.
    SURFACE = "surface"
    ORBITAL = "orbital"


@dataclass(frozen=True)
class CharacteristicTransportGeometry:
    """Stable transport coordinates used to derive characteristic separation.

    These coordinates are deliberately not instantaneous ephemeris state.  They
    provide a deterministic spatial anchor from which Movement can derive a
    characteristic relation for arbitrary endpoint pairs.  Concrete latency,
    payload and resource use remain Movement/Vehicle responsibilities.
    """

    position_km: tuple[float, ...]
    delta_v_coordinate_km_s: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.position_km:
            raise ValueError("transport geometry requires at least one position coordinate")
        if any(not isfinite(value) for value in self.position_km):
            raise ValueError("transport position coordinates must be finite")
        if any(not isfinite(value) for value in self.delta_v_coordinate_km_s):
            raise ValueError("transport delta-v coordinates must be finite")

    def separation_to(self, other: "CharacteristicTransportGeometry") -> tuple[float, float]:
        if len(self.position_km) != len(other.position_km):
            raise ValueError("transport position coordinate dimensions must match")
        distance_km = dist(self.position_km, other.position_km)
        if not self.delta_v_coordinate_km_s and not other.delta_v_coordinate_km_s:
            delta_v_km_s = 0.0
        else:
            if len(self.delta_v_coordinate_km_s) != len(other.delta_v_coordinate_km_s):
                raise ValueError("transport delta-v coordinate dimensions must match")
            delta_v_km_s = dist(self.delta_v_coordinate_km_s, other.delta_v_coordinate_km_s)
        return distance_km, delta_v_km_s


@dataclass(frozen=True)
class CharacteristicTransportSeparation:
    scope: str
    distance_km: float
    delta_v_km_s: float


@dataclass(frozen=True)
class StarSystemDef:
    id: StarSystemId
    display_name: str
    interstellar_transport_geometry: CharacteristicTransportGeometry

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("star system display name must not be empty")


@dataclass(frozen=True)
class CelestialBodyDef:
    id: CelestialBodyId
    display_name: str
    mean_radius_km: float
    star_system_id: StarSystemId
    system_local_transport_geometry: CharacteristicTransportGeometry

    def __post_init__(self) -> None:
        if self.mean_radius_km <= 0:
            raise ValueError("celestial body mean radius must be positive")
        if not self.display_name.strip():
            raise ValueError("celestial body display name must not be empty")


@dataclass(frozen=True)
class SurfacePoint:
    latitude_deg: float
    longitude_deg: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("surface latitude must be within -90..90 degrees")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("surface longitude must be within -180..180 degrees")




def great_circle_distance_km(a: SurfacePoint, b: SurfacePoint, radius_km: float) -> float:
    """Spatial-owned great-circle separation for two points on one body."""
    lat1, lon1 = radians(a.latitude_deg), radians(a.longitude_deg)
    lat2, lon2 = radians(b.latitude_deg), radians(b.longitude_deg)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2.0) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2.0) ** 2
    return 2.0 * radius_km * asin(min(1.0, sqrt(max(0.0, h))))

@dataclass(frozen=True)
class SurfaceCellDef:
    """Static physical geography for one cell on a celestial body."""

    id: SurfaceCellId
    body_id: CelestialBodyId
    area_km2: float
    centroid: SurfacePoint
    neighbor_ids: frozenset[SurfaceCellId] = frozenset()
    terrain: SurfaceTerrain = SurfaceTerrain()
    static_geology: Mapping[str, float] = field(default_factory=dict)
    resource_potential_by_resource: Mapping[DefinitionId, float] = field(default_factory=dict)
    display_name: str = ""

    def __post_init__(self) -> None:
        if self.area_km2 <= 0:
            raise ValueError("surface cell area must be positive")
        if not self.display_name.strip():
            raise ValueError("surface cell display name must not be empty")
        if self.id in self.neighbor_ids:
            raise ValueError("surface cell cannot be adjacent to itself")
        if any(not key for key in self.static_geology):
            raise ValueError("static geology keys must not be empty")
        if any(value < 0 for value in self.resource_potential_by_resource.values()):
            raise ValueError("resource potential must be non-negative")


@dataclass
class SurfaceLocationState:
    """Player-operated economic/industrial/logistics node on a surface."""

    operational_node_id: SpatialNodeId
    display_name: str
    body_id: CelestialBodyId
    core_cell_id: SurfaceCellId
    developed_cell_ids: set[SurfaceCellId] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.developed_cell_ids:
            self.developed_cell_ids.add(self.core_cell_id)
        if self.core_cell_id not in self.developed_cell_ids:
            raise ValueError("location core cell must be developed")


@dataclass(frozen=True)
class SpatialNodeDef:
    """Non-surface spatial node such as an orbit or free-space staging point."""

    id: SpatialNodeId
    display_name: str
    star_system_id: StarSystemId
    system_local_transport_geometry: CharacteristicTransportGeometry
    parent_id: SpatialNodeId | None = None
    body_id: CelestialBodyId | None = None
    kind: SpatialNodeKind = SpatialNodeKind.GENERIC
    inherits_parent_environment: bool = True

    def __post_init__(self) -> None:
        if self.kind is SpatialNodeKind.SURFACE:
            raise ValueError("surface geography must use SurfaceCellDef and SurfaceLocationState")
        if not self.display_name.strip():
            raise ValueError("spatial node display name must not be empty")


@dataclass(frozen=True)
class OperationalNodeState:
    """Existence marker for a player-operable economic/logistics node."""

    id: SpatialNodeId


@dataclass(frozen=True)
class OperationalNodeView:
    id: SpatialNodeId
    display_name: str
    parent_id: SpatialNodeId | None
    body_id: CelestialBodyId | None
    kind: SpatialNodeKind


@dataclass
class SpatialGraph:
    star_systems: dict[StarSystemId, StarSystemDef] = field(default_factory=dict)
    bodies: dict[CelestialBodyId, CelestialBodyDef] = field(default_factory=dict)
    # Non-surface nodes only. Surface economic nodes live in locations.
    nodes: dict[SpatialNodeId, SpatialNodeDef] = field(default_factory=dict)
    surface_cells: dict[SurfaceCellId, SurfaceCellDef] = field(default_factory=dict)
    locations: dict[SpatialNodeId, SurfaceLocationState] = field(default_factory=dict)
    operational_node_states: dict[SpatialNodeId, OperationalNodeState] = field(default_factory=dict)

    def add_star_system(self, system: StarSystemDef) -> None:
        if system.id in self.star_systems:
            raise ValueError(f"duplicate star system: {system.id}")
        self.star_systems[system.id] = system

    def add_body(self, body: CelestialBodyDef) -> None:
        if body.id in self.bodies:
            raise ValueError(f"duplicate celestial body: {body.id}")
        if body.star_system_id not in self.star_systems:
            raise ValueError(f"unknown star system {body.star_system_id} for {body.id}")
        self.bodies[body.id] = body

    def add(self, node: SpatialNodeDef) -> None:
        if node.id in self.nodes or node.id in self.locations:
            raise ValueError(f"duplicate spatial context: {node.id}")
        if node.star_system_id not in self.star_systems:
            raise ValueError(f"unknown star system {node.star_system_id} for {node.id}")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise ValueError(f"unknown non-surface parent {node.parent_id} for {node.id}")
        if node.parent_id is not None and self.nodes[node.parent_id].star_system_id != node.star_system_id:
            raise ValueError(f"non-surface parent belongs to another star system: {node.id}")
        if node.body_id is not None and node.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {node.body_id} for {node.id}")
        if node.body_id is not None and self.bodies[node.body_id].star_system_id != node.star_system_id:
            raise ValueError(f"spatial node body belongs to another star system: {node.id}")
        self.nodes[node.id] = node

    def add_surface_cell(self, cell: SurfaceCellDef) -> None:
        if cell.id in self.surface_cells:
            raise ValueError(f"duplicate surface cell: {cell.id}")
        if cell.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {cell.body_id} for {cell.id}")
        self.surface_cells[cell.id] = cell

    def _add_location_state(self, location: SurfaceLocationState) -> None:
        node_id = location.operational_node_id
        if node_id in self.locations or node_id in self.nodes:
            raise ValueError(f"duplicate spatial context: {node_id}")
        self._validate_location_shape(location, allow_unknown_neighbors=False)
        overlapping = set(location.developed_cell_ids) & set(self.cell_owners())
        if overlapping:
            raise ValueError(
                "surface cell already belongs to another location: "
                + ",".join(sorted(map(str, overlapping)))
            )
        self.locations[node_id] = location

    def add_operational_node(self, state: OperationalNodeState) -> None:
        if state.id in self.operational_node_states:
            raise ValueError(f"duplicate operational node: {state.id}")
        context_count = int(state.id in self.nodes) + int(state.id in self.locations)
        if context_count != 1:
            raise ValueError(
                f"operational node must reference exactly one spatial context: {state.id}"
            )
        self.operational_node_states[state.id] = state

    def replace_dynamic_state(
        self,
        locations: tuple[SurfaceLocationState, ...],
        operational_nodes: tuple[OperationalNodeState, ...],
    ) -> None:
        """Atomically replace persisted surface geography and Operational Node existence."""
        old_locations = self.locations
        old_operational_nodes = self.operational_node_states
        self.locations = {}
        self.operational_node_states = {}
        try:
            for location in locations:
                self._add_location_state(location)
            for state in operational_nodes:
                self.add_operational_node(state)
            missing = set(self.locations) - set(self.operational_node_states)
            if missing:
                raise ValueError(
                    "surface locations lack operational node state: "
                    + ",".join(sorted(map(str, missing)))
                )
        except Exception:
            self.locations = old_locations
            self.operational_node_states = old_operational_nodes
            raise

    def location_foundation_failures(
        self, body_id: CelestialBodyId, core_cell_id: SurfaceCellId
    ) -> tuple[tuple[str, str], ...]:
        failures: list[tuple[str, str]] = []
        if body_id not in self.bodies:
            return (("unknown_body", f"unknown celestial body: {body_id}"),)
        cell = self.surface_cells.get(core_cell_id)
        if cell is None:
            return (("unknown_cell", f"unknown surface cell: {core_cell_id}"),)
        if cell.body_id != body_id:
            failures.append(("body_mismatch", "surface cell belongs to a different celestial body"))
        if self.owner_of_cell(core_cell_id) is not None:
            failures.append(("cell_owned", "surface cell already belongs to a location"))
        return tuple(failures)

    def found_location(
        self,
        location_id: SpatialNodeId,
        display_name: str,
        body_id: CelestialBodyId,
        core_cell_id: SurfaceCellId,
    ) -> SurfaceLocationState:
        failures = self.location_foundation_failures(body_id, core_cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        if location_id in self.nodes or location_id in self.locations or location_id in self.operational_node_states:
            raise ValueError(f"duplicate spatial or operational node: {location_id}")
        location = SurfaceLocationState(
            location_id, display_name, body_id, core_cell_id, {core_cell_id}
        )
        self._add_location_state(location)
        try:
            self.add_operational_node(OperationalNodeState(location_id))
        except Exception:
            self.locations.pop(location_id, None)
            raise
        return location

    def surface_cell_development_failures(
        self, location_id: SpatialNodeId, cell_id: SurfaceCellId
    ) -> tuple[tuple[str, str], ...]:
        if location_id not in self.locations:
            return (("unknown_location", f"unknown surface location: {location_id}"),)
        if cell_id not in self.surface_cells:
            return (("unknown_cell", f"unknown surface cell: {cell_id}"),)
        location = self.locations[location_id]
        cell = self.surface_cells[cell_id]
        failures: list[tuple[str, str]] = []
        if cell.body_id != location.body_id:
            failures.append(("body_mismatch", "surface cell belongs to a different celestial body"))
        owner = self.owner_of_cell(cell_id)
        if owner is not None:
            failures.append((
                "already_developed" if owner == location_id else "cell_owned",
                "surface cell is already developed by this location"
                if owner == location_id
                else "surface cell is already developed by another location",
            ))
        if owner is None and not any(
            cell_id in self.surface_cells[developed].neighbor_ids
            for developed in location.developed_cell_ids
        ):
            failures.append(("not_adjacent", "surface cell must be adjacent to the developed territory"))
        return tuple(failures)

    def develop_surface_cell(self, location_id: SpatialNodeId, cell_id: SurfaceCellId) -> None:
        failures = self.surface_cell_development_failures(location_id, cell_id)
        if failures:
            if failures[0][0] in {"unknown_location", "unknown_cell"}:
                raise KeyError(location_id if failures[0][0] == "unknown_location" else cell_id)
            raise ValueError("; ".join(detail for _code, detail in failures))
        self.locations[location_id].developed_cell_ids.add(cell_id)

    def owner_of_cell(self, cell_id: SurfaceCellId) -> SpatialNodeId | None:
        if cell_id not in self.surface_cells:
            raise KeyError(cell_id)
        for location_id, location in self.locations.items():
            if cell_id in location.developed_cell_ids:
                return location_id
        return None

    def cell_owners(self) -> dict[SurfaceCellId, SpatialNodeId]:
        result: dict[SurfaceCellId, SpatialNodeId] = {}
        for location_id, location in self.locations.items():
            for cell_id in location.developed_cell_ids:
                if cell_id in result:
                    raise ValueError(f"surface cell has multiple location owners: {cell_id}")
                result[cell_id] = location_id
        return result

    def cells_for_body(self, body_id: CelestialBodyId) -> tuple[SurfaceCellDef, ...]:
        if body_id not in self.bodies:
            raise KeyError(body_id)
        return tuple(
            sorted(
                (cell for cell in self.surface_cells.values() if cell.body_id == body_id),
                key=lambda cell: str(cell.id),
            )
        )

    def nodes_for_body(self, body_id: CelestialBodyId) -> tuple[SpatialNodeId, ...]:
        if body_id not in self.bodies:
            raise KeyError(body_id)
        return tuple(
            sorted(
                (
                    node.id
                    for node in self.operational_nodes()
                    if node.body_id == body_id
                ),
                key=str,
            )
        )

    def operational_nodes(self) -> tuple[OperationalNodeView, ...]:
        return tuple(
            sorted(
                (self._operational_node_view(state.id) for state in self.operational_node_states.values()),
                key=lambda row: str(row.id),
            )
        )

    def _operational_node_view(self, node_id: SpatialNodeId) -> OperationalNodeView:
        node = self.nodes.get(node_id)
        if node is not None:
            return OperationalNodeView(
                node.id, node.display_name, node.parent_id, node.body_id, node.kind
            )
        location = self.locations.get(node_id)
        if location is not None:
            return OperationalNodeView(
                location.operational_node_id,
                location.display_name,
                None,
                location.body_id,
                SpatialNodeKind.SURFACE,
            )
        raise ValueError(f"operational node has no spatial context: {node_id}")

    def operational_node_map(self) -> dict[SpatialNodeId, OperationalNodeView]:
        return {row.id: row for row in self.operational_nodes()}

    def operational_node(self, node_id: SpatialNodeId) -> OperationalNodeView:
        if node_id not in self.operational_node_states:
            raise KeyError(node_id)
        return self._operational_node_view(node_id)

    def has_operational_node(self, node_id: SpatialNodeId) -> bool:
        return node_id in self.operational_node_states

    def operational_node_ids(self) -> tuple[SpatialNodeId, ...]:
        return tuple(row.id for row in self.operational_nodes())

    def lineage(self, node_id: SpatialNodeId) -> tuple[SpatialNodeId, ...]:
        if node_id not in self.nodes:
            raise KeyError(node_id)
        result: list[SpatialNodeId] = []
        current: SpatialNodeId | None = node_id
        seen: set[SpatialNodeId] = set()
        while current is not None:
            if current in seen:
                raise ValueError("spatial hierarchy cycle")
            seen.add(current)
            result.append(current)
            current = self.nodes[current].parent_id
        return tuple(result)

    def is_descendant(self, node_id: SpatialNodeId, ancestor_id: SpatialNodeId) -> bool:
        return ancestor_id in self.lineage(node_id)

    def environment_lineage(self, context_id: SpatialContextId) -> tuple[SpatialContextId, ...]:
        """Return explicit context-local inheritance only.

        Surface Locations deliberately do not inherit from ``core_cell_id``.
        Body/global and Surface Cell composition is resolved by the field scope
        contract in ``StaticFacetStore.resolve``.
        """
        if context_id in self.locations or context_id in self.surface_cells:
            return (context_id,)
        if context_id not in self.nodes:
            raise KeyError(context_id)
        result: list[SpatialContextId] = []
        current: SpatialNodeId | None = cast(SpatialNodeId, context_id)
        seen: set[SpatialNodeId] = set()
        while current is not None:
            if current in seen:
                raise ValueError("spatial hierarchy cycle")
            seen.add(current)
            result.append(current)
            node = self.nodes[current]
            if not node.inherits_parent_environment:
                break
            current = node.parent_id
        return tuple(result)

    def context_body_id(self, context_id: SpatialContextId) -> CelestialBodyId | None:
        if context_id in self.locations:
            return self.locations[cast(SpatialNodeId, context_id)].body_id
        if context_id in self.surface_cells:
            return self.surface_cells[cast(SurfaceCellId, context_id)].body_id
        if context_id in self.nodes:
            return self.nodes[cast(SpatialNodeId, context_id)].body_id
        raise KeyError(context_id)

    def context_star_system_id(self, context_id: SpatialContextId) -> StarSystemId:
        if context_id in self.locations:
            body_id = self.locations[cast(SpatialNodeId, context_id)].body_id
            return self.bodies[body_id].star_system_id
        if context_id in self.surface_cells:
            body_id = self.surface_cells[cast(SurfaceCellId, context_id)].body_id
            return self.bodies[body_id].star_system_id
        if context_id in self.nodes:
            return self.nodes[cast(SpatialNodeId, context_id)].star_system_id
        raise KeyError(context_id)

    def transport_geometry_for_context(
        self, context_id: SpatialContextId
    ) -> CharacteristicTransportGeometry:
        if context_id in self.locations:
            body_id = self.locations[cast(SpatialNodeId, context_id)].body_id
            return self.bodies[body_id].system_local_transport_geometry
        if context_id in self.surface_cells:
            body_id = self.surface_cells[cast(SurfaceCellId, context_id)].body_id
            return self.bodies[body_id].system_local_transport_geometry
        if context_id in self.nodes:
            return self.nodes[cast(SpatialNodeId, context_id)].system_local_transport_geometry
        raise KeyError(context_id)

    def characteristic_transport_separation(
        self, origin_context_id: SpatialContextId, destination_context_id: SpatialContextId
    ) -> CharacteristicTransportSeparation:
        origin_system = self.context_star_system_id(origin_context_id)
        destination_system = self.context_star_system_id(destination_context_id)
        if origin_system == destination_system:
            origin_geometry = self.transport_geometry_for_context(origin_context_id)
            destination_geometry = self.transport_geometry_for_context(destination_context_id)
            distance_km, delta_v_km_s = origin_geometry.separation_to(destination_geometry)
            return CharacteristicTransportSeparation(
                "system_local", distance_km, delta_v_km_s
            )
        origin_geometry = self.star_systems[origin_system].interstellar_transport_geometry
        destination_geometry = self.star_systems[destination_system].interstellar_transport_geometry
        distance_km, delta_v_km_s = origin_geometry.separation_to(destination_geometry)
        return CharacteristicTransportSeparation(
            "interstellar", distance_km, delta_v_km_s
        )

    def is_surface_context(self, context_id: SpatialContextId) -> bool:
        if context_id in self.locations or context_id in self.surface_cells:
            return True
        if context_id in self.nodes:
            return False
        raise KeyError(context_id)

    def _validate_location_shape(self, location: SurfaceLocationState, *, allow_unknown_neighbors: bool) -> None:
        if location.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {location.body_id} for {location.operational_node_id}")
        if location.core_cell_id not in self.surface_cells:
            raise ValueError(f"unknown core surface cell {location.core_cell_id} for {location.operational_node_id}")
        if location.core_cell_id not in location.developed_cell_ids:
            raise ValueError("location core cell must be in developed territory")
        for cell_id in location.developed_cell_ids:
            cell = self.surface_cells.get(cell_id)
            if cell is None:
                raise ValueError(f"unknown developed surface cell {cell_id} for {location.operational_node_id}")
            if cell.body_id != location.body_id:
                raise ValueError(f"location developed cell belongs to another body: {location.operational_node_id}/{cell_id}")
        if not self._cells_connected(location.developed_cell_ids, allow_unknown_neighbors=allow_unknown_neighbors):
            raise ValueError(f"location developed territory is not connected: {location.operational_node_id}")

    def _cells_connected(
        self,
        cell_ids: set[SurfaceCellId],
        *,
        allow_unknown_neighbors: bool = False,
    ) -> bool:
        if not cell_ids:
            return False
        start = next(iter(cell_ids))
        seen = {start}
        pending = [start]
        while pending:
            current = pending.pop()
            cell = self.surface_cells.get(current)
            if cell is None:
                return False
            for neighbor in cell.neighbor_ids:
                if neighbor not in self.surface_cells:
                    if allow_unknown_neighbors:
                        continue
                    return False
                if neighbor in cell_ids and neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        return seen == cell_ids


@dataclass
class StaticFacetStore:
    """Static Physical Environment definitions separated by authoritative scope."""

    facets: dict[tuple[SpatialContextId, type[SpatialFacet]], SpatialFacet] = field(default_factory=dict)
    body_facets: dict[tuple[CelestialBodyId, type[SpatialFacet]], SpatialFacet] = field(default_factory=dict)

    @staticmethod
    def _field_scope(facet_type: type[FacetT]) -> EnvironmentFieldScope:
        scope = getattr(facet_type, "environment_scope", None)
        if not isinstance(scope, EnvironmentFieldScope):
            raise ValueError(
                f"physical environment field lacks explicit scope: {facet_type.__name__}"
            )
        return scope

    def set(self, context_id: SpatialContextId, facet: FacetT) -> None:
        self._field_scope(type(facet))
        self.facets[(context_id, type(facet))] = facet

    def set_body(self, body_id: CelestialBodyId, facet: FacetT) -> None:
        scope = self._field_scope(type(facet))
        if scope not in {
            EnvironmentFieldScope.BODY_GLOBAL,
            EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY,
        }:
            raise ValueError(
                f"{type(facet).__name__} cannot be defined at body scope ({scope.value})"
            )
        self.body_facets[(body_id, type(facet))] = facet

    def facet_types(self) -> set[type[SpatialFacet]]:
        return {facet_type for (_context_id, facet_type) in self.facets} | {
            facet_type for (_body_id, facet_type) in self.body_facets
        }

    def field_applies_to_context(
        self, graph: SpatialGraph, context_id: SpatialContextId, facet_type: type[FacetT]
    ) -> bool:
        scope = self._field_scope(facet_type)
        if context_id in graph.locations:
            return scope in {
                EnvironmentFieldScope.BODY_GLOBAL,
                EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY,
            }
        if context_id in graph.surface_cells or context_id in graph.nodes:
            return True
        raise KeyError(context_id)

    def _nearest_context_value(
        self,
        graph: SpatialGraph,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
    ) -> FacetT | None:
        for context in graph.environment_lineage(context_id):
            value = self.facets.get((context, facet_type))
            if value is not None:
                return cast(FacetT, value)
        return None

    def resolve(
        self,
        graph: SpatialGraph,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
    ) -> FacetT | None:
        scope = self._field_scope(facet_type)

        if context_id in graph.locations:
            # A Surface Location is an Operational Node spanning many Cells.  It
            # may evaluate only body-global fields without an explicit Cell.
            if scope not in {
                EnvironmentFieldScope.BODY_GLOBAL,
                EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY,
            }:
                return None
            body_id = graph.locations[cast(SpatialNodeId, context_id)].body_id
            value = self.body_facets.get((body_id, facet_type))
            return None if value is None else cast(FacetT, value)

        if context_id in graph.surface_cells:
            cell_id = cast(SurfaceCellId, context_id)
            cell = graph.surface_cells[cell_id]
            body_value = self.body_facets.get((cell.body_id, facet_type))
            cell_value = self.facets.get((cell_id, facet_type))
            if scope is EnvironmentFieldScope.BODY_GLOBAL:
                return None if body_value is None else cast(FacetT, body_value)
            if scope in {EnvironmentFieldScope.SURFACE_CELL_LOCAL, EnvironmentFieldScope.CONTEXT_LOCAL}:
                return None if cell_value is None else cast(FacetT, cell_value)
            # BODY_WITH_CELL_OVERLAY: a Cell-local value replaces the body base
            # for that field; absent an overlay the body value is inherited.
            value = cell_value if cell_value is not None else body_value
            return None if value is None else cast(FacetT, value)

        if context_id not in graph.nodes:
            raise KeyError(context_id)

        # Non-surface contexts may provide explicit local values.  If a field
        # also has a body-global component, that body value is only a fallback
        # after the explicit non-surface lineage has been checked.
        local_value = self._nearest_context_value(graph, context_id, facet_type)
        if local_value is not None:
            return local_value
        if scope in {EnvironmentFieldScope.BODY_GLOBAL, EnvironmentFieldScope.BODY_WITH_CELL_OVERLAY}:
            body_id = graph.context_body_id(context_id)
            if body_id is not None:
                body_value = self.body_facets.get((body_id, facet_type))
                if body_value is not None:
                    return cast(FacetT, body_value)
        return None


class StatefulEnvironmentOverlay(Protocol):
    """Optional persistence contract for mutable environment overlays."""

    state_key: str

    def capture_state(self) -> Any: ...

    def restore_state(self, state: Any) -> None: ...


class EnvironmentOverlay(Protocol):
    """Explicit dynamic environment source."""

    overlay_key: str
    priority: int

    def apply(
        self,
        graph: SpatialGraph,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
        current: FacetT | None,
        day: int,
    ) -> FacetT | None: ...


@dataclass
class EnvironmentResolver:
    graph: SpatialGraph
    static: StaticFacetStore
    overlays: list[EnvironmentOverlay] = field(default_factory=list)

    def ordered_overlays(self) -> tuple[EnvironmentOverlay, ...]:
        keyed: list[tuple[int, str, EnvironmentOverlay]] = []
        seen: set[str] = set()
        for overlay in self.overlays:
            key = getattr(overlay, "overlay_key", None)
            if not isinstance(key, str) or not key:
                raise ValueError(
                    f"environment overlay lacks a stable overlay_key: {type(overlay).__name__}"
                )
            if key in seen:
                raise ValueError(f"duplicate environment overlay key: {key}")
            seen.add(key)
            priority = int(getattr(overlay, "priority", 0))
            keyed.append((priority, key, overlay))
        return tuple(
            overlay
            for _priority, _key, overlay in sorted(keyed, key=lambda row: (row[0], row[1]))
        )

    def get(
        self,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
        day: int = 0,
    ) -> FacetT | None:
        if not self.static.field_applies_to_context(self.graph, context_id, facet_type):
            return None
        value = self.static.resolve(self.graph, context_id, facet_type)
        for overlay in self.ordered_overlays():
            value = overlay.apply(self.graph, context_id, facet_type, value, day)
        return value

    def require(
        self,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
        day: int = 0,
    ) -> FacetT:
        value = self.get(context_id, facet_type, day)
        if value is None:
            raise LookupError(f"{context_id} has no {facet_type.__name__}")
        return value

    def capture_overlay_state(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for overlay in self.ordered_overlays():
            key = getattr(overlay, "state_key", None)
            capture = getattr(overlay, "capture_state", None)
            if key is None or capture is None:
                continue
            if key in seen:
                raise ValueError(f"duplicate environment overlay state key: {key}")
            seen.add(key)
            rows.append({"key": key, "state": capture()})
        return rows

    def restore_overlay_state(self, rows: list[dict[str, Any]]) -> None:
        overlays: dict[str, object] = {}
        for overlay in self.ordered_overlays():
            key = getattr(overlay, "state_key", None)
            restore = getattr(overlay, "restore_state", None)
            if key is None or restore is None:
                continue
            if key in overlays:
                raise ValueError(f"duplicate environment overlay state key: {key}")
            overlays[key] = overlay
        supplied = {row["key"] for row in rows}
        if len(supplied) != len(rows):
            raise ValueError("duplicate environment overlay state row")
        expected = set(overlays)
        if supplied != expected:
            raise ValueError(
                f"environment overlay state mismatch: expected {sorted(expected)}, got {sorted(supplied)}"
            )
        for row in rows:
            getattr(overlays[row["key"]], "restore_state")(row["state"])
