from __future__ import annotations

from ..founding import DeploymentRecipe, FoundingFacilityDeployment, FoundingResourceRequirement
from . import base_requirements as req
from . import base_ids as ids


def _r(resource_id, amount):
    return FoundingResourceRequirement(resource_id, amount)


def build_deployment_recipes() -> dict:
    # Founding carries fully paid physical hardware, not a discounted bundle
    # of operational warehouses, power plants and cargo terminals. Each
    # compact outpost provides just enough service for regular follow-up
    # construction and inbound supply. It supplies no unearned resource stock.
    surface = DeploymentRecipe(
        id=ids.ROBOTIC_SURFACE_OUTPOST_PACKAGE,
        display_name="自律地表初期拠点展開",
        deployed_facilities=(FoundingFacilityDeployment(
            ids.AUTONOMOUS_SURFACE_OUTPOST,
            (_r(ids.STRUCTURAL_COMPONENTS, 2.7),
             _r(ids.MACHINERY, 1.5),
             _r(ids.CONSTRUCTION_EQUIPMENT, 0.5)),
        ),),
        preparation_work=12.0,
        preparation_service_type="cargo_transfer",
        initial_inventory=(_r(ids.STRUCTURAL_COMPONENTS, 0.25),
                           _r(ids.MACHINERY, 0.20),
                           _r(ids.CONSTRUCTION_EQUIPMENT, 0.05)),
        staging_requirements=req.ORBIT_SITE,
        target_requirements=req.ROBOTIC_OUTPOST_SURFACE_SITE,
        required_units=1,
    )
    orbital = DeploymentRecipe(
        id=ids.ORBITAL_OUTPOST_FOUNDING_PACKAGE,
        display_name="自律軌道初期拠点展開",
        deployed_facilities=(FoundingFacilityDeployment(
            ids.AUTONOMOUS_ORBITAL_OUTPOST,
            (_r(ids.STRUCTURAL_COMPONENTS, 3.4),
             _r(ids.MACHINERY, 1.9)),
        ),),
        preparation_work=10.0,
        preparation_service_type="cargo_transfer",
        staging_requirements=req.ORBIT_SITE,
        target_requirements=req.ORBIT_SITE,
        initial_inventory=(_r(ids.PROPELLANT, 0.8),
                           _r(ids.STRUCTURAL_COMPONENTS, 0.4),
                           _r(ids.MACHINERY, 0.5)),
        required_units=1,
    )
    return {row.id: row for row in (surface, orbital)}
