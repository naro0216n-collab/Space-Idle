from __future__ import annotations

from space_idle import build_game_application
from space_idle.research import ResearchDefinition, ResearchPhase, ResearchPrototypeSpec
from space_idle.shared import DefinitionId
from space_idle.content.base_game import EARTH


def test_explicit_empty_prototype_spec_still_creates_prototype_phase():
    app = build_game_application()
    sim = app._simulation
    research_id = DefinitionId("test.research.explicit_empty_prototype")
    sim.research.definitions[research_id] = ResearchDefinition(
        research_id,
        "Explicit Prototype",
        research_point_cost=0.0,
        prototype=ResearchPrototypeSpec({}),
    )

    sim.research.start(research_id, day=sim.day)

    state = sim.research.active[research_id]
    assert state.status is ResearchPhase.PROTOTYPE
    sim.research.set_prototype_site(research_id, EARTH, sim.day)
    sim.research.fund_prototype(research_id, sim.day)
    assert research_id in sim.research.completed
    assert research_id not in sim.research.active
