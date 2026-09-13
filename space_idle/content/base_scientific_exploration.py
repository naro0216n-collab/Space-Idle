from __future__ import annotations

from ..scientific_exploration import ScientificExplorationDefinition
from ..transport import SpaceflightCapability, TransportOperationKind, TransportOperationRequirement
from . import base_ids as ids
from . import base_requirements as req


def build_scientific_exploration_definitions() -> dict:
    """Finite science campaigns whose eligibility is based on real vehicle performance."""
    return {
        ids.CISLUNAR_SCIENCE_EXPLORATION: ScientificExplorationDefinition(
            id=ids.CISLUNAR_SCIENCE_EXPLORATION,
            display_name="地月空間航法・放射線環境観測",
            origin_id=ids.LEO,
            destination_id=ids.LUNAR_ORBIT,
            operations=(
                TransportOperationRequirement(TransportOperationKind.SPACEFLIGHT, 4.1),
            ),
            mission_duration_days=5,
            duration_days=8.0,
            research_points_total=45.0,
            consumable_resources=((ids.MACHINERY, 0.20), (ids.PRECISION_ELECTRONICS, 0.10)),
            origin_requirements=req.ORBIT_SITE,
            destination_requirements=req.ORBIT_SITE,
            return_to_origin=False,
        ),
    }
