from __future__ import annotations

from space_idle import (
    AdvanceTime,
    AssignExplorationFleet,
    CreateLogisticsLane,
    CreateTransportAllocation,
    FundResearchPrototype,
    GetLocation,
    GetLogistics,
    GetProjects,
    GetResearch,
    GetScientificExplorations,
    GetFleet,
    PlanBuild,
    ProduceVehicle,
    SetResearchPrototypeSite,
    StartResearch,
    StartScientificExploration,
    build_game_application,
)
from space_idle.content import base_ids as ids


def _research_row(app, research_id):
    return next(row for row in app.query(GetResearch()).items if row.id == str(research_id))


def _advance_until(app, predicate, *, max_days: int = 240) -> None:
    for _ in range(max_days + 1):
        if predicate():
            return
        app.execute(AdvanceTime(1))
    raise AssertionError("condition was not reached through normal simulation")


def _complete_prototype_research(app, research_id) -> None:
    _advance_until(app, lambda: _research_row(app, research_id).can_start)
    app.execute(StartResearch(str(research_id)))
    row = _research_row(app, research_id)
    if row.status == "prototype":
        site = next((candidate for candidate in row.prototype_sites if not candidate.blockers), None)
        assert site is not None
        app.execute(SetResearchPrototypeSite(str(research_id), site.location_id))
        _advance_until(app, lambda: not _research_row(app, research_id).prototype_blockers)
        app.execute(FundResearchPrototype(str(research_id)))
    assert _research_row(app, research_id).status == "complete"


def test_research_point_growth_loop_is_reachable_through_application_api():
    app = build_game_application()

    # Opening industry is ordinary finite extraction + production, not a market shortcut.
    app.execute(AdvanceTime(2))
    earth = app.query(GetLocation(str(ids.EARTH)))
    assert any(row.output_t_per_day > 0 for row in earth.extraction)
    assert any(row.output_rates_per_day for row in earth.industry)

    # Physical construction creates investment history and therefore maintenance demand.
    project_id = app.execute(PlanBuild(
        str(ids.EARTH),
        str(ids.WATER_STORAGE),
        priority=50,
        sourcing_policy="mixed",
        import_source_id=None,
    )).created_id
    assert project_id is not None
    _advance_until(
        app,
        lambda: next(row for row in app.query(GetProjects()).items if row.id == project_id).status == "complete",
    )
    storage = next(
        row for row in app.query(GetLocation(str(ids.EARTH))).facilities
        if row.definition_id == str(ids.WATER_STORAGE)
    )
    assert storage.invested_resources
    assert storage.maintenance_demand_per_day

    # Unlock the initial orbital operating method using the normal RP/prototype path.
    _complete_prototype_research(app, ids.TECH_ORBITAL_OPERATIONS)

    # Vehicle production increases the authoritative Fleet Pool rather than creating an individual ID.
    before_pool = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and row.location_id == str(ids.EARTH)
    ) if any(
        row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG) and row.location_id == str(ids.EARTH)
        for row in app.query(GetFleet()).pools
    ) else None
    before_units = 0 if before_pool is None else before_pool.total_units
    production_id = app.execute(ProduceVehicle(
        str(ids.REUSABLE_ORBITAL_CARGO_TUG), str(ids.EARTH),
    )).created_id
    assert production_id is not None

    def production_complete():
        row = next(item for item in app.query(GetLogistics()).vehicle_production if item.id == production_id)
        return row.phase == "complete"

    _advance_until(app, production_complete)
    produced_pool = next(
        row for row in app.query(GetFleet()).pools
        if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
        and row.location_id == str(ids.EARTH)
    )
    assert produced_pool.total_units == before_units + 1

    # Scientific Exploration reserves units from an existing Fleet Pool by vehicle definition.
    exploration_id = ids.CISLUNAR_SCIENCE_EXPLORATION
    app.execute(StartScientificExploration(str(exploration_id)))
    exploration_before = next(
        row for row in app.query(GetScientificExplorations()).items
        if row.id == str(exploration_id)
    )
    option = next(
        row for row in exploration_before.fleet_options
        if row.vehicle_definition_id == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
    )
    assert option.can_assign
    app.execute(AssignExplorationFleet(str(exploration_id), option.vehicle_definition_id))
    research_points_before = app.query(GetResearch()).stored_points
    _advance_until(
        app,
        lambda: next(
            row for row in app.query(GetScientificExplorations()).items
            if row.id == str(exploration_id)
        ).status == "complete",
    )
    exploration = next(
        row for row in app.query(GetScientificExplorations()).items
        if row.id == str(exploration_id)
    )
    assert exploration.research_points_awarded > 0
    assert app.query(GetResearch()).stored_points > research_points_before

    # RP enables a higher-generation research method, which must still be physically built.
    _complete_prototype_research(app, ids.TECH_MICROGRAVITY_EXPERIMENT_SYSTEMS)
    if not any(
        row.anchor_location_id == str(ids.EARTH) and row.destination_id == str(ids.LEO)
        for row in app.query(GetLogistics()).allocations
    ):
        app.execute(CreateTransportAllocation(
            str(ids.REUSABLE_LAUNCH_VEHICLE), str(ids.EARTH), str(ids.LEO),
            control_mode="units", target_units=1, priority=70,
        ))
    if not any(
        row.source_id == str(ids.EARTH) and row.destination_id == str(ids.LEO)
        for row in app.query(GetLogistics()).lanes
    ):
        app.execute(CreateLogisticsLane(
            str(ids.EARTH), str(ids.LEO), requested_capacity_t_per_day=10.0, priority=70
        ))
    provider_project = app.execute(PlanBuild(
        str(ids.LEO),
        str(ids.MICROGRAVITY_EXPERIMENT_PLATFORM),
        priority=70,
        sourcing_policy="import_now",
        import_source_id=str(ids.EARTH),
    )).created_id
    assert provider_project is not None
    _advance_until(
        app,
        lambda: next(
            row for row in app.query(GetProjects()).items if row.id == provider_project
        ).status == "complete",
    )
    provider = next(
        row for row in app.query(GetLocation(str(ids.LEO))).facilities
        if row.definition_id == str(ids.MICROGRAVITY_EXPERIMENT_PLATFORM)
    )
    assert provider.research_tier is not None and provider.research_tier > 1
    assert provider.research_generation_points_per_day > 0
    assert provider.research_storage_capacity_points > 0
