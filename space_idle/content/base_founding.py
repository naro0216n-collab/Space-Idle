from __future__ import annotations

from ..founding import (
    FoundingFacilityDeployment,
    FoundingPackageDefinition,
    FoundingStagingRelation,
)
from ..site import SiteRequirements
from ..transport.models import TransportOperationKind, TransportOperationRequirement
from . import base_ids as ids
from . import base_requirements as req


def build_founding_packages() -> dict:
    """Integrated opening packages for creating a Location where none exists.

    These investments describe pre-integrated deployment hardware, not normal
    on-site construction recipes.  Their mass is the payload that must be
    delivered in the one-time Founding Deployment.
    """
    package = FoundingPackageDefinition(
        id=ids.LUNAR_ROBOTIC_FOUNDING_PACKAGE,
        display_name="ロボット月面初期拠点パッケージ",
        facilities=(
            FoundingFacilityDeployment(
                ids.ROBOTIC_SURVEY_PACKAGE,
                (
                    (ids.STRUCTURAL_COMPONENTS, 1.0),
                    (ids.MACHINERY, 1.0),
                    (ids.PRECISION_ELECTRONICS, 0.5),
                ),
            ),
            FoundingFacilityDeployment(
                ids.CARGO_WAREHOUSE,
                (
                    (ids.STRUCTURAL_COMPONENTS, 0.75),
                    (ids.MACHINERY, 0.25),
                    (ids.PRECISION_ELECTRONICS, 0.1),
                ),
            ),
            FoundingFacilityDeployment(
                ids.SURFACE_DISTRIBUTION_HUB,
                (
                    (ids.STRUCTURAL_COMPONENTS, 0.6),
                    (ids.MACHINERY, 0.55),
                    (ids.PRECISION_ELECTRONICS, 0.25),
                ),
            ),
            FoundingFacilityDeployment(
                ids.CRYOGENIC_STORAGE,
                (
                    (ids.STRUCTURAL_COMPONENTS, 0.2),
                    (ids.MACHINERY, 0.2),
                    (ids.PRECISION_ELECTRONICS, 0.1),
                ),
            ),
        ),
        initial_inventory=((ids.PROPELLANT, 0.3),),
        operations=(
            TransportOperationRequirement(TransportOperationKind.LANDING, 1.9),
        ),
        transit_days=3,
        preparation_work=2.0,
        required_units=1,
        minimum_survey_knowledge_level=1,
        staging_requirements=SiteRequirements(
            req.ORBIT_ENV, req._infrastructure_requirements("cargo_transfer")
        ),
        target_requirements=req.VACUUM_SURFACE_SITE,
        staging_relation=FoundingStagingRelation.SAME_BODY,
    )
    return {package.id: package}
