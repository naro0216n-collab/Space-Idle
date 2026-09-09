from __future__ import annotations

from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "space_idle"


def test_application_logistics_projection_uses_public_transport_query_boundary():
    from space_idle.logistics import LogisticsService

    assert hasattr(LogisticsService, "transport_plan")
    for path in PACKAGE.glob("application_project_logistics*.py"):
        source = path.read_text(encoding="utf-8")
        for private_name in (
            "_automatic_mode_plan",
            "_mode_cost_musd_per_t",
            "_mode_propellant_t_per_cargo_t",
            "_demand_pipeline_remaining",
        ):
            assert private_name not in source, f"{path.name} reaches transport private API {private_name}"
