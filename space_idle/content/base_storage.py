from __future__ import annotations

from ..storage import StorageProviderSpec
from . import base_ids as ids


def build_storage_provider_specs() -> dict:
    return {
        ids.ORBITAL_PROPELLANT_DEPOT: StorageProviderSpec(
            ids.ORBITAL_PROPELLANT_DEPOT, {"cryogenic": 80.0}, frozenset({"cryogenic"}),
        ),
        ids.ORBITAL_LOGISTICS_NODE: StorageProviderSpec(
            ids.ORBITAL_LOGISTICS_NODE, {"cryogenic": 4.0}, frozenset({"cryogenic"}),
        ),
        ids.AUTONOMOUS_SURFACE_OUTPOST: StorageProviderSpec(
            ids.AUTONOMOUS_SURFACE_OUTPOST, {"cryogenic": 0.8}, frozenset({"cryogenic"}),
        ),
        ids.AUTONOMOUS_ORBITAL_OUTPOST: StorageProviderSpec(
            ids.AUTONOMOUS_ORBITAL_OUTPOST, {"cryogenic": 1.0}, frozenset({"cryogenic"}),
        ),
        ids.ROBOTIC_SURVEY_PACKAGE: StorageProviderSpec(
            ids.ROBOTIC_SURVEY_PACKAGE, {"cryogenic": 2.0}, frozenset({"cryogenic"}),
        ),
        ids.CRYOGENIC_STORAGE: StorageProviderSpec(ids.CRYOGENIC_STORAGE, {"cryogenic": 30.0}, frozenset({"cryogenic"})),
        ids.CRYOGENIC_PROPELLANT_TERMINAL: StorageProviderSpec(
            ids.CRYOGENIC_PROPELLANT_TERMINAL, {"cryogenic": 150.0}, frozenset({"cryogenic"}),
        ),
    }
