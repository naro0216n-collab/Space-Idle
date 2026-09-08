from __future__ import annotations

from ..storage import StorageProviderSpec
from . import base_ids as ids


def build_storage_provider_specs() -> dict:
    return {
        ids.ROBOTIC_SURVEY_PACKAGE: StorageProviderSpec(ids.ROBOTIC_SURVEY_PACKAGE, {"liquid": 5.0, "cryogenic": 2.0}),
        ids.WATER_STORAGE: StorageProviderSpec(ids.WATER_STORAGE, {"liquid": 40.0}),
        ids.CRYOGENIC_STORAGE: StorageProviderSpec(ids.CRYOGENIC_STORAGE, {"cryogenic": 30.0}, frozenset({"cryogenic"})),
        ids.BULK_STORAGE: StorageProviderSpec(ids.BULK_STORAGE, {"bulk": 200.0}),
        ids.CARGO_WAREHOUSE: StorageProviderSpec(ids.CARGO_WAREHOUSE, {"general_cargo": 120.0}),
    }
