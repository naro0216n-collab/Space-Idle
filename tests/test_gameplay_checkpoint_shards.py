from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import test_gameplay_mechanics as gameplay


_CHECKPOINT_ENV = "SPACE_IDLE_GAMEPLAY_CHECKPOINT_DIR"
pytestmark = pytest.mark.skipif(
    _CHECKPOINT_ENV not in os.environ,
    reason="checkpoint-backed gameplay tests run in Full Validation",
)


def _state(name: str) -> dict:
    root = Path(os.environ[_CHECKPOINT_ENV])
    return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))


def test_storage_capacity_from_isru_checkpoint():
    gameplay.test_storage_capacity_stops_output_without_creating_or_destroying_capacity(
        _state("isru")
    )


def test_parallel_construction_from_isru_checkpoint():
    gameplay.test_construction_capacity_is_allocatable_between_parallel_projects(
        _state("isru")
    )


def test_vehicle_state_transitions_from_cislunar_checkpoint():
    gameplay.test_launch_vehicle_and_spacecraft_have_distinct_state_transitions(
        _state("cislunar")
    )


def test_lunar_propellant_export_from_isru_checkpoint():
    gameplay.test_lunar_propellant_changes_usable_export_logistics(_state("isru"))


def test_physical_bottleneck_projection_from_isru_checkpoint():
    gameplay.test_query_exposes_physical_bottleneck_without_prescribing_a_solution(
        _state("isru")
    )


def test_pause_resume_from_shared_checkpoints():
    gameplay.test_manual_pause_resume_controls_preserve_configuration_and_halt_autonomous_progress(
        _state("orbital_research"),
        _state("survey_ready"),
    )
