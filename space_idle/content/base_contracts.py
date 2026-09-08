from __future__ import annotations

from ..contracts import CapabilityContractTemplate
from ..shared import DefinitionId
from ..site import SiteRequirements
from . import base_ids as ids
from . import base_requirements as req

SURFACE_POWER_CONTRACT = DefinitionId("base.contract.surface_power")


def build_contract_templates() -> dict:
    """Optional scenario/event contracts retained outside the core growth loop."""
    return {
        SURFACE_POWER_CONTRACT: CapabilityContractTemplate(
            SURFACE_POWER_CONTRACT, "南極観測網向け電力供給",
            SiteRequirements(req.SURFACE_ENV, req._available_requirements("power_grid")),
            260, 260.0, ids.SOUTH_POLAR_RIDGE,
        ),
    }
