from __future__ import annotations

from ..scientific_exploration import ScientificExplorationDefinition
from ..transport.models import MovementEndpoint
from . import base_ids as ids
from . import base_requirements as req
from ..shared import DefinitionId


def build_scientific_exploration_definitions() -> dict:
    """Finite science campaigns whose eligibility is based on real vehicle performance."""
    return {
        ids.CISLUNAR_SCIENCE_EXPLORATION: ScientificExplorationDefinition(
            id=ids.CISLUNAR_SCIENCE_EXPLORATION,
            display_name="地月空間航法・放射線環境観測",
            origin_id=ids.LEO,
            destination=ids.LUNAR_ORBIT,
            duration_days=8.0,
            research_points_total=45.0,
            consumable_resources=((ids.MACHINERY, 0.20), (ids.PRECISION_ELECTRONICS, 0.10)),
            origin_requirements=req.ORBIT_SITE,
            destination_requirements=req.ORBIT_SITE,
            return_to_origin=False,
        ),
        ids.CREWED_CISLUNAR_EXPEDITION: ScientificExplorationDefinition(
            id=ids.CREWED_CISLUNAR_EXPEDITION,
            display_name="地月有人科学探査",
            origin_id=ids.LEO,
            destination=ids.LUNAR_ORBIT,
            duration_days=5.0,
            research_points_total=75.0,
            consumable_resources=((ids.MACHINERY, 0.1),),
            origin_requirements=req.ORBIT_SITE,
            destination_requirements=req.ORBIT_SITE,
            required_crew=2,
            return_to_origin=True,
        ),
        ids.MARS_ORBIT_SCIENCE_EXPLORATION: ScientificExplorationDefinition(
            id=ids.MARS_ORBIT_SCIENCE_EXPLORATION,
            display_name="火星周回・環境観測遠征",
            origin_id=ids.LEO,
            destination=MovementEndpoint(physical_target_node_id=ids.MARS_ORBIT),
            duration_days=12.0,
            research_points_total=180.0,
            prerequisite_technologies=frozenset({DefinitionId("SS-SENSING-02")}),
            consumable_resources=((ids.MACHINERY, 0.10), (ids.PRECISION_ELECTRONICS, 0.20)),
            origin_requirements=req.ORBIT_SITE,
            destination_requirements=req.ORBIT_SITE,
            return_to_origin=True,
        ),
    }
