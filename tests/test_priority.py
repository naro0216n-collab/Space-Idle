from __future__ import annotations

import pytest

from space_idle import PauseFacility, ResumeFacility, SetFacilityActivityPriority, build_game_application
from space_idle.content import base_ids as ids
from space_idle.facilities import FacilityDef
from space_idle.shared import DefinitionId
from space_idle.priority import (
    ActivityPriority, DEFAULT_ACTIVITY_PRIORITY, DEFAULT_PRIORITY_LEVEL,
    DEFAULT_PROVISIONING_PRIORITY, PriorityLevel, ProvisioningPriority,
)


def test_priority_contract_has_five_distinct_ordinal_roles_and_pause_is_orthogonal_state():
    assert tuple(int(level) for level in PriorityLevel) == (1, 2, 3, 4, 5)
    assert DEFAULT_PRIORITY_LEVEL is PriorityLevel.NORMAL
    assert int(DEFAULT_ACTIVITY_PRIORITY) == 3
    assert int(DEFAULT_PROVISIONING_PRIORITY) == 3

    for value in (0, 6, -1, True, 1.5):
        with pytest.raises(ValueError):
            ActivityPriority(value)
        with pytest.raises(ValueError):
            ProvisioningPriority(value)

    activity = ActivityPriority(4)
    provisioning = ProvisioningPriority(4)
    assert type(activity) is ActivityPriority
    assert type(provisioning) is ProvisioningPriority
    with pytest.raises(ValueError, match="different priority role"):
        ProvisioningPriority(activity)
    with pytest.raises(ValueError, match="different priority role"):
        ActivityPriority(provisioning)

    app = build_game_application()
    sim = app._simulation
    definition_id = DefinitionId("test.facility.priority_pause")
    sim.facilities.definitions[definition_id] = FacilityDef(
        definition_id, "Priority/pause fixture"
    )
    facility_id = sim.facilities.install(definition_id, ids.EARTH)
    facility = sim.facilities.facilities[facility_id]
    app.execute(SetFacilityActivityPriority(str(facility.id), 5))
    app.execute(PauseFacility(str(facility.id)))
    assert facility.paused is True
    assert facility.activity_priority == 5
    app.execute(ResumeFacility(str(facility.id)))
    assert facility.paused is False
    assert facility.activity_priority == 5
