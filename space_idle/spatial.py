from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping, Protocol, TypeAlias, TypeVar, cast

from .shared import CelestialBodyId, DefinitionId, SpatialNodeId, SurfaceCellId

FacetT = TypeVar("FacetT", bound="SpatialFacet")
SpatialContextId: TypeAlias = SpatialNodeId | SurfaceCellId


class SpatialFacet:
    """Typed descriptive fact. Behavior belongs to consuming domains."""

    facet_key: ClassVar[str]


@dataclass(frozen=True)
class GravityField(SpatialFacet):
    facet_key: ClassVar[str] = "gravity"
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
    solar_flux_w_m2: float
    availability: float = 1.0

    def __post_init__(self) -> None:
        if self.solar_flux_w_m2 < 0 or not 0 <= self.availability <= 1:
            raise ValueError("invalid illumination values")


@dataclass(frozen=True)
class ThermalField(SpatialFacet):
    facet_key: ClassVar[str] = "thermal"
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
class SurfaceField(SpatialFacet):
    facet_key: ClassVar[str] = "surface"
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
    orbital_period_s: float | None = None

    def __post_init__(self) -> None:
        if self.orbital_period_s is not None and self.orbital_period_s <= 0:
            raise ValueError("orbital period must be positive")


@dataclass(frozen=True)
class CommunicationField(SpatialFacet):
    facet_key: ClassVar[str] = "communication"
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
class CelestialBodyDef:
    id: CelestialBodyId
    display_name: str


@dataclass(frozen=True)
class SurfacePoint:
    latitude_deg: float
    longitude_deg: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("surface latitude must be within -90..90 degrees")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("surface longitude must be within -180..180 degrees")


@dataclass(frozen=True)
class SurfaceCellDef:
    """Static physical geography for one cell on a celestial body."""

    id: SurfaceCellId
    body_id: CelestialBodyId
    area_km2: float
    centroid: SurfacePoint
    neighbor_ids: frozenset[SurfaceCellId] = frozenset()
    terrain: SurfaceField = SurfaceField()
    static_geology: Mapping[str, float] = field(default_factory=dict)
    resource_potential_by_resource: Mapping[DefinitionId, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.area_km2 <= 0:
            raise ValueError("surface cell area must be positive")
        if self.id in self.neighbor_ids:
            raise ValueError("surface cell cannot be adjacent to itself")
        if any(not key for key in self.static_geology):
            raise ValueError("static geology keys must not be empty")
        if any(value < 0 for value in self.resource_potential_by_resource.values()):
            raise ValueError("resource potential must be non-negative")


@dataclass
class LocationState:
    """Player-operated economic/industrial/logistics node on a surface."""

    id: SpatialNodeId
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
    parent_id: SpatialNodeId | None = None
    body_id: CelestialBodyId | None = None
    kind: SpatialNodeKind = SpatialNodeKind.GENERIC
    inherits_parent_environment: bool = True

    def __post_init__(self) -> None:
        if self.kind is SpatialNodeKind.SURFACE:
            raise ValueError("surface geography must use SurfaceCellDef and LocationState")


@dataclass(frozen=True)
class OperationalNodeView:
    id: SpatialNodeId
    display_name: str
    parent_id: SpatialNodeId | None
    body_id: CelestialBodyId | None
    kind: SpatialNodeKind


@dataclass
class SpatialGraph:
    bodies: dict[CelestialBodyId, CelestialBodyDef] = field(default_factory=dict)
    # Non-surface nodes only. Surface economic nodes live in locations.
    nodes: dict[SpatialNodeId, SpatialNodeDef] = field(default_factory=dict)
    surface_cells: dict[SurfaceCellId, SurfaceCellDef] = field(default_factory=dict)
    locations: dict[SpatialNodeId, LocationState] = field(default_factory=dict)

    def add_body(self, body: CelestialBodyDef) -> None:
        if body.id in self.bodies:
            raise ValueError(f"duplicate celestial body: {body.id}")
        self.bodies[body.id] = body

    def add(self, node: SpatialNodeDef) -> None:
        if node.id in self.nodes or node.id in self.locations:
            raise ValueError(f"duplicate operational node: {node.id}")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise ValueError(f"unknown non-surface parent {node.parent_id} for {node.id}")
        if node.body_id is not None and node.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {node.body_id} for {node.id}")
        self.nodes[node.id] = node

    def add_surface_cell(self, cell: SurfaceCellDef) -> None:
        if cell.id in self.surface_cells:
            raise ValueError(f"duplicate surface cell: {cell.id}")
        if cell.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {cell.body_id} for {cell.id}")
        self.surface_cells[cell.id] = cell

    def add_location(self, location: LocationState) -> None:
        if location.id in self.locations or location.id in self.nodes:
            raise ValueError(f"duplicate operational node: {location.id}")
        self._validate_location_shape(location, allow_unknown_neighbors=False)
        overlapping = set(location.developed_cell_ids) & set(self.cell_owners())
        if overlapping:
            raise ValueError(
                "surface cell already belongs to another location: "
                + ",".join(sorted(map(str, overlapping)))
            )
        self.locations[location.id] = location

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
    ) -> LocationState:
        failures = self.location_foundation_failures(body_id, core_cell_id)
        if failures:
            raise ValueError("; ".join(detail for _code, detail in failures))
        location = LocationState(location_id, display_name, body_id, core_cell_id, {core_cell_id})
        self.add_location(location)
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
        rows = [
            OperationalNodeView(node.id, node.display_name, node.parent_id, node.body_id, node.kind)
            for node in self.nodes.values()
        ]
        rows.extend(
            OperationalNodeView(
                location.id,
                location.display_name,
                None,
                location.body_id,
                SpatialNodeKind.SURFACE,
            )
            for location in self.locations.values()
        )
        return tuple(sorted(rows, key=lambda row: str(row.id)))

    def operational_node_map(self) -> dict[SpatialNodeId, OperationalNodeView]:
        return {row.id: row for row in self.operational_nodes()}

    def operational_node(self, node_id: SpatialNodeId) -> OperationalNodeView:
        node = self.nodes.get(node_id)
        if node is not None:
            return OperationalNodeView(node.id, node.display_name, node.parent_id, node.body_id, node.kind)
        location = self.locations.get(node_id)
        if location is not None:
            return OperationalNodeView(
                location.id,
                location.display_name,
                None,
                location.body_id,
                SpatialNodeKind.SURFACE,
            )
        raise KeyError(node_id)

    def has_operational_node(self, node_id: SpatialNodeId) -> bool:
        return node_id in self.nodes or node_id in self.locations

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
        if context_id in self.locations:
            return (self.locations[cast(SpatialNodeId, context_id)].core_cell_id,)
        if context_id in self.surface_cells:
            return (cast(SurfaceCellId, context_id),)
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

    def surface_cell_for_context(self, context_id: SpatialContextId) -> SurfaceCellId | None:
        if context_id in self.locations:
            return self.locations[cast(SpatialNodeId, context_id)].core_cell_id
        if context_id in self.surface_cells:
            return cast(SurfaceCellId, context_id)
        if context_id in self.nodes:
            return None
        raise KeyError(context_id)

    def is_surface_context(self, context_id: SpatialContextId) -> bool:
        return self.surface_cell_for_context(context_id) is not None

    def _validate_location_shape(self, location: LocationState, *, allow_unknown_neighbors: bool) -> None:
        if location.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {location.body_id} for {location.id}")
        if location.core_cell_id not in self.surface_cells:
            raise ValueError(f"unknown core surface cell {location.core_cell_id} for {location.id}")
        if location.core_cell_id not in location.developed_cell_ids:
            raise ValueError("location core cell must be in developed territory")
        for cell_id in location.developed_cell_ids:
            cell = self.surface_cells.get(cell_id)
            if cell is None:
                raise ValueError(f"unknown developed surface cell {cell_id} for {location.id}")
            if cell.body_id != location.body_id:
                raise ValueError(f"location developed cell belongs to another body: {location.id}/{cell_id}")
        if not self._cells_connected(location.developed_cell_ids, allow_unknown_neighbors=allow_unknown_neighbors):
            raise ValueError(f"location developed territory is not connected: {location.id}")

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
    facets: dict[tuple[SpatialContextId, type[SpatialFacet]], SpatialFacet] = field(default_factory=dict)

    def set(self, context_id: SpatialContextId, facet: FacetT) -> None:
        self.facets[(context_id, type(facet))] = facet

    def nearest(
        self,
        graph: SpatialGraph,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
    ) -> FacetT | None:
        for scope in graph.environment_lineage(context_id):
            if facet_type is SurfaceField and scope in graph.surface_cells:
                return cast(FacetT, graph.surface_cells[cast(SurfaceCellId, scope)].terrain)
            value = self.facets.get((scope, facet_type))
            if value is not None:
                return cast(FacetT, value)
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
        value = self.static.nearest(self.graph, context_id, facet_type)
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
