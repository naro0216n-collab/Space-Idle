"""Typed physical-asset Content registration for standard and analysis compositions.

One registered asset row projects into its existing Domain-owned Definition maps.
No runtime Asset State, experiment-only registry or parallel owner is created.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..facilities import FacilityDef
from ..power import PowerSpec
from ..projects import (ConstructionProviderSpec, ConstructionRecipe,
                        FacilityDecommissionRecipe, FacilityUpgradeRecipe)
from ..shared import DefinitionId
from ..storage import StorageProviderSpec
from ..transport import VehicleDef


@dataclass(frozen=True)
class FacilityAsset:
    """One authored Facility with its physical acquisition/operating contracts."""

    definition: FacilityDef
    construction: ConstructionRecipe
    power: PowerSpec
    storage: StorageProviderSpec | None = None
    construction_provider: ConstructionProviderSpec | None = None
    decommission: FacilityDecommissionRecipe | None = None
    upgrades: tuple[FacilityUpgradeRecipe, ...] = ()


@dataclass
class AssetDefinitions:
    facilities: dict[DefinitionId, FacilityDef] = field(default_factory=dict)
    construction: dict[DefinitionId, ConstructionRecipe] = field(default_factory=dict)
    power: dict[DefinitionId, PowerSpec] = field(default_factory=dict)
    storage: dict[DefinitionId, StorageProviderSpec] = field(default_factory=dict)
    construction_providers: dict[DefinitionId, ConstructionProviderSpec] = field(default_factory=dict)
    upgrades: dict[tuple[DefinitionId, int], FacilityUpgradeRecipe] = field(default_factory=dict)
    decommission: dict[DefinitionId, FacilityDecommissionRecipe] = field(default_factory=dict)
    vehicles: dict[DefinitionId, VehicleDef] = field(default_factory=dict)

    def add_facility(self, row: FacilityAsset) -> None:
        identity = row.definition.id
        if identity in self.facilities or identity in self.construction or identity in self.power:
            raise ValueError(f"duplicate Facility asset definition: {identity}")
        if row.construction.facility_def_id != identity:
            raise ValueError(f"construction owner differs from Facility: {identity}")
        if row.storage is not None and row.storage.facility_def_id != identity:
            raise ValueError(f"storage owner differs from Facility: {identity}")
        if row.construction_provider is not None and row.construction_provider.facility_def_id != identity:
            raise ValueError(f"construction provider differs from Facility: {identity}")
        upgrade_keys = [(item.facility_def_id, item.target_level) for item in row.upgrades]
        if (any(facility != identity for facility, _ in upgrade_keys) or
                len(upgrade_keys) != len(set(upgrade_keys)) or
                any(key in self.upgrades for key in upgrade_keys)):
            raise ValueError(f"invalid upgrade ownership for Facility: {identity}")
        if identity in self.storage or identity in self.construction_providers or identity in self.decommission:
            raise ValueError(f"duplicate Facility-owned definition: {identity}")
        recipe = row.decommission
        if recipe is None or recipe.facility_def_id != identity:
            raise ValueError(f"decommission owner differs from Facility: {identity}")
        self.facilities[identity] = row.definition
        self.construction[identity] = row.construction
        self.power[identity] = row.power
        self.decommission[identity] = recipe
        if row.storage is not None:
            self.storage[identity] = row.storage
        if row.construction_provider is not None:
            self.construction_providers[identity] = row.construction_provider
        for item in row.upgrades:
            self.upgrades[(identity, item.target_level)] = item

    def add_vehicle(self, definition: VehicleDef) -> None:
        if definition.id in self.vehicles:
            raise ValueError(f"duplicate Vehicle asset definition: {definition.id}")
        self.vehicles[definition.id] = definition

    def copy_facility(self, source: DefinitionId, target: DefinitionId) -> None:
        """New authored asset, using the exact same installation as base Content."""
        if source not in self.facilities or source not in self.construction or source not in self.power:
            raise ValueError(f"unknown complete Facility asset source: {source}")
        row = FacilityAsset(
            definition=replace(self.facilities[source], id=target),
            construction=replace(self.construction[source], facility_def_id=target),
            power=replace(self.power[source]),
            storage=(replace(self.storage[source], facility_def_id=target)
                     if source in self.storage else None),
            construction_provider=(replace(self.construction_providers[source], facility_def_id=target)
                                   if source in self.construction_providers else None),
            upgrades=tuple(replace(item, facility_def_id=target)
                           for (identity, _level), item in self.upgrades.items() if identity == source),
            decommission=(replace(self.decommission[source], facility_def_id=target)
                          if source in self.decommission else None),
        )
        self.add_facility(row)

    def copy_vehicle(self, source: DefinitionId, target: DefinitionId) -> None:
        if source not in self.vehicles:
            raise ValueError(f"unknown Vehicle asset source: {source}")
        self.add_vehicle(replace(self.vehicles[source], id=target))
