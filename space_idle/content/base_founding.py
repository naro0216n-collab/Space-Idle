from __future__ import annotations

from ..founding import FoundingFacilityDeployment, FoundingPackageDefinition, FoundingResourceRequirement
from ..site import CapabilityRequirement, SiteRequirements
from ..spatial import SurfaceField
from ..site import RequiresFacet
from ..transport.models import TransportOperationKind, TransportOperationRequirement
from . import base_ids as ids


def _r(resource_id, amount):
    return FoundingResourceRequirement(resource_id, amount)


def build_founding_packages() -> dict:
    package = FoundingPackageDefinition(
        id=ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE,
        display_name="Robotic Lunar Outpost Founding Package",
        resources=(
            _r(ids.STRUCTURAL_COMPONENTS, 3.4),
            _r(ids.MACHINERY, 1.3),
            _r(ids.PRECISION_ELECTRONICS, 0.8),
            _r(ids.CONSTRUCTION_EQUIPMENT, 0.5),
        ),
        deployed_facilities=(
            FoundingFacilityDeployment(
                ids.ROBOTIC_SURVEY_PACKAGE,
                (_r(ids.STRUCTURAL_COMPONENTS, 1.4), _r(ids.MACHINERY, 0.5), _r(ids.PRECISION_ELECTRONICS, 0.3), _r(ids.CONSTRUCTION_EQUIPMENT, 0.2)),
            ),
            FoundingFacilityDeployment(
                ids.CARGO_WAREHOUSE,
                (_r(ids.STRUCTURAL_COMPONENTS, 0.8), _r(ids.MACHINERY, 0.2), _r(ids.PRECISION_ELECTRONICS, 0.1), _r(ids.CONSTRUCTION_EQUIPMENT, 0.1)),
            ),
            FoundingFacilityDeployment(
                ids.SURFACE_DISTRIBUTION_HUB,
                (_r(ids.STRUCTURAL_COMPONENTS, 0.9), _r(ids.MACHINERY, 0.4), _r(ids.PRECISION_ELECTRONICS, 0.2), _r(ids.CONSTRUCTION_EQUIPMENT, 0.1)),
                place_at_core_cell=True,
            ),
            FoundingFacilityDeployment(
                ids.CRYOGENIC_STORAGE,
                (_r(ids.STRUCTURAL_COMPONENTS, 0.3), _r(ids.MACHINERY, 0.2), _r(ids.PRECISION_ELECTRONICS, 0.2), _r(ids.CONSTRUCTION_EQUIPMENT, 0.1)),
            ),
        ),
        preparation_work=3.0,
        preparation_capability_id="cargo_transfer",
        operations=(TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),),
        transit_days=3,
        site_requirements=SiteRequirements(environment=(RequiresFacet(SurfaceField, "surface", "surface terrain data is required"),)),
        minimum_survey_knowledge_level=2,
        required_units=1,
    )
    return {package.id: package}
