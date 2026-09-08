from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Mapping, Protocol, TypeVar, cast

from .shared import CelestialBodyId, DefinitionId, SpatialNodeId

FacetT = TypeVar("FacetT", bound="SpatialFacet")


class SpatialFacet:
    """Typed descriptive fact. Behavior belongs to consuming domains."""

    facet_key: ClassVar[str]


@dataclass(frozen=True)
class GravityField(SpatialFacet):
    facet_key: ClassVar[str] = "gravity"
    local_acceleration_m_s2: float
    escape_velocity_m_s: float | None = None

    def __post_init__(self) -> None:
        if self.local_acceleration_m_s2 < 0 or (self.escape_velocity_m_s is not None and self.escape_velocity_m_s < 0):
            raise ValueError("gravity values must be non-negative")


@dataclass(frozen=True)
class AtmosphereField(SpatialFacet):
    facet_key: ClassVar[str] = "atmosphere"
    pressure_pa: float
    density_kg_m3: float
    composition: Mapping[DefinitionId, float]

    def __post_init__(self) -> None:
        if self.pressure_pa < 0 or self.density_kg_m3 < 0 or any(v < 0 for v in self.composition.values()):
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
        if self.min_temperature_k is not None and self.max_temperature_k is not None and self.min_temperature_k > self.max_temperature_k:
            raise ValueError("minimum temperature cannot exceed maximum")


@dataclass(frozen=True)
class SurfaceField(SpatialFacet):
    facet_key: ClassVar[str] = "surface"
    terrain_factor: float = 1.0
    bearing_capacity_factor: float = 1.0
    dust_factor: float = 0.0
    slope_factor: float = 0.0

    def __post_init__(self) -> None:
        if min(self.terrain_factor, self.bearing_capacity_factor, self.dust_factor, self.slope_factor) < 0:
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
    SURFACE = "surface"
    ORBITAL = "orbital"


@dataclass(frozen=True)
class CelestialBodyDef:
    id: CelestialBodyId
    display_name: str


@dataclass(frozen=True)
class SpatialNodeDef:
    id: SpatialNodeId
    display_name: str
    parent_id: SpatialNodeId | None = None
    # Body membership is distinct from topology and environmental inheritance.
    # A body is not itself an inventory/facility location.
    body_id: CelestialBodyId | None = None
    kind: SpatialNodeKind = SpatialNodeKind.GENERIC
    # Containment and environmental inheritance are distinct. Orbital nodes,
    # sealed habitats, etc. can remain topologically related without inheriting
    # a surface atmosphere or climate.
    inherits_parent_environment: bool = True


@dataclass
class SpatialGraph:
    bodies: dict[CelestialBodyId, CelestialBodyDef] = field(default_factory=dict)
    nodes: dict[SpatialNodeId, SpatialNodeDef] = field(default_factory=dict)

    def add_body(self, body: CelestialBodyDef) -> None:
        if body.id in self.bodies:
            raise ValueError(f"duplicate celestial body: {body.id}")
        self.bodies[body.id] = body

    def add(self, node: SpatialNodeDef) -> None:
        if node.id in self.nodes:
            raise ValueError(f"duplicate spatial node: {node.id}")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise ValueError(f"unknown parent {node.parent_id} for {node.id}")
        if node.body_id is not None and node.body_id not in self.bodies:
            raise ValueError(f"unknown celestial body {node.body_id} for {node.id}")
        self.nodes[node.id] = node

    def nodes_for_body(self, body_id: CelestialBodyId) -> tuple[SpatialNodeId, ...]:
        if body_id not in self.bodies:
            raise KeyError(body_id)
        return tuple(sorted((node.id for node in self.nodes.values() if node.body_id == body_id), key=str))

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

    def environment_lineage(self, node_id: SpatialNodeId) -> tuple[SpatialNodeId, ...]:
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
            node = self.nodes[current]
            if not node.inherits_parent_environment:
                break
            current = node.parent_id
        return tuple(result)


@dataclass
class StaticFacetStore:
    facets: dict[tuple[SpatialNodeId, type[SpatialFacet]], SpatialFacet] = field(default_factory=dict)

    def set(self, node_id: SpatialNodeId, facet: FacetT) -> None:
        self.facets[(node_id, type(facet))] = facet

    def nearest(
        self,
        graph: SpatialGraph,
        node_id: SpatialNodeId,
        facet_type: type[FacetT],
    ) -> FacetT | None:
        for scope in graph.environment_lineage(node_id):
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
    """Explicit dynamic environment source.

    Overlays are ordered by explicit ``priority`` and ``overlay_key`` rather
    than registration order.  This keeps content composition deterministic as
    new domains (terraforming, habitats, weather, etc.) are added.
    """

    overlay_key: str
    priority: int

    def apply(
        self,
        graph: SpatialGraph,
        node_id: SpatialNodeId,
        facet_type: type[FacetT],
        current: FacetT | None,
        day: int,
    ) -> FacetT | None: ...


@dataclass
class EnvironmentResolver:
    graph: SpatialGraph
    static: StaticFacetStore
    overlays: list[EnvironmentOverlay] = field(default_factory=list)

    def _ordered_overlays(self) -> tuple[EnvironmentOverlay, ...]:
        keyed: list[tuple[int, str, EnvironmentOverlay]] = []
        seen: set[str] = set()
        for overlay in self.overlays:
            key = getattr(overlay, "overlay_key", None)
            if not isinstance(key, str) or not key:
                raise ValueError(f"environment overlay lacks a stable overlay_key: {type(overlay).__name__}")
            if key in seen:
                raise ValueError(f"duplicate environment overlay key: {key}")
            seen.add(key)
            priority = int(getattr(overlay, "priority", 0))
            keyed.append((priority, key, overlay))
        return tuple(overlay for _priority, _key, overlay in sorted(keyed, key=lambda row: (row[0], row[1])))

    def get(self, node_id: SpatialNodeId, facet_type: type[FacetT], day: int = 0) -> FacetT | None:
        value = self.static.nearest(self.graph, node_id, facet_type)
        for overlay in self._ordered_overlays():
            value = overlay.apply(self.graph, node_id, facet_type, value, day)
        return value

    def require(self, node_id: SpatialNodeId, facet_type: type[FacetT], day: int = 0) -> FacetT:
        value = self.get(node_id, facet_type, day)
        if value is None:
            raise LookupError(f"{node_id} has no {facet_type.__name__}")
        return value

    def capture_overlay_state(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for overlay in self._ordered_overlays():
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
        for overlay in self._ordered_overlays():
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
            raise ValueError(f"environment overlay state mismatch: expected {sorted(expected)}, got {sorted(supplied)}")
        for row in rows:
            getattr(overlays[row["key"]], "restore_state")(row["state"])
