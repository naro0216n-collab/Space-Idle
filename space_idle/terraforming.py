from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from .shared import CelestialBodyId, DefinitionId
from .spatial import AtmosphereField, EnvironmentOverlay, SpatialContextId, SpatialFacet, SpatialGraph, ThermalField

FacetT = TypeVar("FacetT", bound=SpatialFacet)


@dataclass
class PlanetaryClimateState:
    body_id: CelestialBodyId
    pressure_pa: float
    density_kg_m3: float
    mean_temperature_k: float
    composition: dict[DefinitionId, float]

    def __post_init__(self) -> None:
        if self.pressure_pa < 0 or self.density_kg_m3 < 0 or self.mean_temperature_k < 0:
            raise ValueError("planetary climate values must be non-negative")
        if any(value < 0 for value in self.composition.values()):
            raise ValueError("planetary atmosphere composition must be non-negative")
        total = sum(self.composition.values())
        if total > 0:
            self.composition = {key: value / total for key, value in self.composition.items()}


@dataclass
class TerraformingService:
    climates: dict[CelestialBodyId, PlanetaryClimateState]

    def add_atmosphere(
        self,
        body_id: CelestialBodyId,
        pressure_delta_pa: float,
        density_delta_kg_m3: float,
        species: DefinitionId,
        composition_delta: float,
        warming_delta_k: float,
    ) -> None:
        climate = self.climates[body_id]
        pressure = climate.pressure_pa + pressure_delta_pa
        density = climate.density_kg_m3 + density_delta_kg_m3
        temperature = climate.mean_temperature_k + warming_delta_k
        if pressure < -1e-9 or density < -1e-12 or temperature < -1e-9:
            raise ValueError("terraforming update would create a non-physical climate state")
        climate.pressure_pa = max(0.0, pressure)
        climate.density_kg_m3 = max(0.0, density)
        climate.mean_temperature_k = max(0.0, temperature)
        climate.composition[species] = max(0.0, climate.composition.get(species, 0.0) + composition_delta)
        total = sum(climate.composition.values())
        if total > 0:
            for key in list(climate.composition):
                climate.composition[key] /= total


@dataclass
class TerraformingEnvironmentOverlay(EnvironmentOverlay):
    service: TerraformingService
    overlay_key: str = "terraforming.climate"
    priority: int = 100
    state_key: str = "terraforming.climates"

    def capture_state(self) -> list[dict[str, object]]:
        return [
            {
                "body_id": str(body_id),
                "pressure_pa": climate.pressure_pa,
                "density_kg_m3": climate.density_kg_m3,
                "mean_temperature_k": climate.mean_temperature_k,
                "composition": {str(k): v for k, v in sorted(climate.composition.items(), key=lambda x: str(x[0]))},
            }
            for body_id, climate in sorted(self.service.climates.items(), key=lambda x: str(x[0]))
        ]

    def restore_state(self, state: object) -> None:
        if not isinstance(state, list):
            raise ValueError("terraforming state must be a list")
        restored: dict[CelestialBodyId, PlanetaryClimateState] = {}
        for raw in state:
            if not isinstance(raw, dict):
                raise ValueError("terraforming climate row must be an object")
            body_id = CelestialBodyId(str(raw["body_id"]))
            composition_raw = raw["composition"]
            if not isinstance(composition_raw, dict):
                raise ValueError("terraforming composition must be an object")
            restored[body_id] = PlanetaryClimateState(
                body_id,
                float(raw["pressure_pa"]),
                float(raw["density_kg_m3"]),
                float(raw["mean_temperature_k"]),
                {DefinitionId(str(k)): float(v) for k, v in composition_raw.items()},
            )
        self.service.climates = restored

    def apply(
        self,
        graph: SpatialGraph,
        context_id: SpatialContextId,
        facet_type: type[FacetT],
        current: FacetT | None,
        day: int,
    ) -> FacetT | None:
        body_id = graph.context_body_id(context_id)
        climate = (
            self.service.climates.get(body_id)
            if body_id is not None and graph.is_surface_context(context_id)
            else None
        )
        if climate is None:
            return current
        if facet_type is AtmosphereField:
            return cast(FacetT, AtmosphereField(climate.pressure_pa, climate.density_kg_m3, dict(climate.composition)))
        if facet_type is ThermalField:
            return cast(FacetT, ThermalField(climate.mean_temperature_k))
        return current
