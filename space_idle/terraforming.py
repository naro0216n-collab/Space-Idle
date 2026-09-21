from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast

from .domain import decode_dict, decode_float, decode_list, decode_str, require_fields
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
    reference_temperature_k: float | None = None

    def __post_init__(self) -> None:
        if self.pressure_pa < 0 or self.density_kg_m3 < 0 or self.mean_temperature_k < 0:
            raise ValueError("planetary climate values must be non-negative")
        if self.reference_temperature_k is None:
            self.reference_temperature_k = self.mean_temperature_k
        elif self.reference_temperature_k < 0:
            raise ValueError("planetary climate reference temperature must be non-negative")
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
                "reference_temperature_k": climate.reference_temperature_k,
                "composition": {str(k): v for k, v in sorted(climate.composition.items(), key=lambda x: str(x[0]))},
            }
            for body_id, climate in sorted(self.service.climates.items(), key=lambda x: str(x[0]))
        ]

    def restore_state(self, state: object) -> None:
        restored: dict[CelestialBodyId, PlanetaryClimateState] = {}
        fields = {
            "body_id", "pressure_pa", "density_kg_m3", "mean_temperature_k",
            "reference_temperature_k", "composition",
        }
        for index, raw in enumerate(decode_list(state, "terraforming state")):
            row = require_fields(raw, fields, f"terraforming climate[{index}]")
            body_id = CelestialBodyId(decode_str(row["body_id"], "terraforming body_id"))
            if body_id in restored:
                raise ValueError(f"duplicate terraforming climate: {body_id}")
            composition_raw = decode_dict(row["composition"], "terraforming composition")
            restored[body_id] = PlanetaryClimateState(
                body_id,
                decode_float(row["pressure_pa"], "terraforming pressure_pa"),
                decode_float(row["density_kg_m3"], "terraforming density_kg_m3"),
                decode_float(row["mean_temperature_k"], "terraforming mean_temperature_k"),
                {
                    DefinitionId(key): decode_float(value, "terraforming composition value")
                    for key, value in composition_raw.items()
                },
                decode_float(
                    row["reference_temperature_k"],
                    "terraforming reference_temperature_k",
                ),
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
            reference = climate.reference_temperature_k
            if reference is None:
                raise ValueError("planetary climate lacks reference temperature")
            delta = climate.mean_temperature_k - reference
            if current is None:
                return cast(FacetT, ThermalField(climate.mean_temperature_k))
            if not isinstance(current, ThermalField):
                raise TypeError("thermal environment overlay received incompatible field")
            return cast(
                FacetT,
                ThermalField(
                    current.nominal_temperature_k + delta,
                    None if current.min_temperature_k is None else current.min_temperature_k + delta,
                    None if current.max_temperature_k is None else current.max_temperature_k + delta,
                ),
            )
        return current
