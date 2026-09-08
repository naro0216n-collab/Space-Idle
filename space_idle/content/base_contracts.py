from __future__ import annotations

from ..contracts import CapabilityContractTemplate, CargoContractTemplate
from ..shared import DefinitionId
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req

SURFACE_POWER_CONTRACT = DefinitionId("base.contract.surface_power")
OBSERVATORY_CARGO_CONTRACT = DefinitionId("base.contract.observatory_cargo")


def build_contract_templates() -> dict:
    return {
        SURFACE_POWER_CONTRACT: CapabilityContractTemplate(
            SURFACE_POWER_CONTRACT, "南極観測網向け電力供給",
            SiteRequirements(req.SURFACE_ENV, req._available_requirements("power_grid")),
            260, 260.0, ids.SOUTH_POLAR_RIDGE,
        ),
        OBSERVATORY_CARGO_CONTRACT: CargoContractTemplate(
            OBSERVATORY_CARGO_CONTRACT, "観測機材緊急輸送",
            ids.EARTH, ids.SOUTH_POLAR_RIDGE, ids.CONTRACT_PAYLOAD,
            18.0, 220, 380.0, 100,
        ),
    }


def initial_contract_offers() -> tuple[DefinitionId, ...]:
    return (SURFACE_POWER_CONTRACT, OBSERVATORY_CARGO_CONTRACT)
