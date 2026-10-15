"""Physical bodies remain distinct from player-operated sites and logistics."""

from __future__ import annotations

from dataclasses import replace

import pytest

from space_idle import GetCatalog, GetSurfaceMap, GetWorld, GetNonSurfaceFoundingOptions, build_game_application
from space_idle.content import base_ids as ids
from space_idle.shared import CelestialBodyId, SpatialNodeId, SurfaceCellId, StarSystemId
from space_idle.spatial import (
    CelestialBodyDef, CharacteristicTransportGeometry, PhysicalSurface,
    SpatialGraph, StarSystemDef, SurfaceCellDef, SurfacePoint,
)


def test_registered_physical_bodies_project_without_creating_player_owned_nodes():
    app = build_game_application()
    graph = app._simulation.graph
    bodies = tuple(graph.bodies.values())
    assert bodies
    assert all(
        body.parent_body_id is None
        or body.star_system_id == graph.bodies[body.parent_body_id].star_system_id
        for body in bodies
    )

    catalog = app.query(GetCatalog())
    assert {row.id for row in catalog.celestial_bodies} == {str(body.id) for body in bodies}
    catalog_by_id = {row.id: row for row in catalog.celestial_bodies}
    for body in bodies:
        entry = catalog_by_id[str(body.id)]
        assert entry.parent_body_id == (str(body.parent_body_id) if body.parent_body_id else None)
        if body.physical_surface is PhysicalSurface.NO_SOLID_SURFACE:
            assert entry.surface_cell_count == 0
    # Public projection of each physical class needs one representative; the
    # Catalog-to-registration correspondence above already covers all bodies.
    for physical_surface in {body.physical_surface for body in bodies}:
        representative = min(
            (body for body in bodies if body.physical_surface is physical_surface),
            key=lambda body: catalog_by_id[str(body.id)].surface_cell_count,
        )
        entry = catalog_by_id[str(representative.id)]
        surface_map = app.query(GetSurfaceMap(entry.id))
        assert surface_map.physical_surface == entry.physical_surface
        assert len(surface_map.cells) == entry.surface_cell_count

    world = app.query(GetWorld())
    assert {row.id for row in world.operational_nodes} == {str(id_) for id_ in graph.operational_node_ids()}
    assert not {row.id for row in world.operational_nodes} & {str(body.id) for body in bodies}


def test_body_parent_validation_and_surface_capability_have_distinct_semantics():
    graph = SpatialGraph()
    one, two = StarSystemId("one"), StarSystemId("two")
    zero = CharacteristicTransportGeometry((0.0,))
    graph.add_star_system(StarSystemDef(one, "one", zero))
    graph.add_star_system(StarSystemDef(two, "two", zero))
    giant_id, moon_id = CelestialBodyId("giant"), CelestialBodyId("moon")
    giant = CelestialBodyDef(giant_id, "giant", 1000, one, None,
                            physical_surface=PhysicalSurface.NO_SOLID_SURFACE)
    moon = CelestialBodyDef(moon_id, "moon", 100, one, None, parent_body_id=giant_id)
    with pytest.raises(ValueError, match="unknown celestial parent"):
        graph.add_body(moon)
    graph.add_body(giant)
    graph.add_body(moon)
    assert graph.body_lineage(moon_id) == (moon_id, giant_id)
    assert graph.cells_for_body(moon_id) == ()  # no registered Cells != no surface
    with pytest.raises(ValueError, match="no solid surface"):
        graph.add_surface_cell(SurfaceCellDef(
            SurfaceCellId("giant.cell"), giant_id, 1, SurfacePoint(0, 0), display_name="bad"))
    assert graph.location_foundation_failures(giant_id, SurfaceCellId("missing"))[0][0] == "no_solid_surface"
    graph.add_surface_cell(SurfaceCellDef(
        SurfaceCellId("moon.cell"), moon_id, 1, SurfacePoint(0, 0), display_name="valid"))
    graph.found_location(SpatialNodeId("moon.outpost"), "Outpost", moon_id, SurfaceCellId("moon.cell"))
    assert graph.has_operational_node(SpatialNodeId("moon.outpost"))
    with pytest.raises(ValueError, match="another star system"):
        graph.add_body(replace(moon, id=CelestialBodyId("wrong.system"), star_system_id=two))
    with pytest.raises(ValueError, match="hierarchy cycle"):
        graph.bodies[giant_id] = replace(giant, parent_body_id=moon_id)
        graph.body_lineage(giant_id)



def test_representative_climate_is_day_stable_and_solar_uses_local_flux():
    """Local solar generation consumes physical Environment, not World-wide defaults."""
    from space_idle.spatial import (
        GravityField, IlluminationField, ThermalField,
    )
    from space_idle.facilities import FacilityBook, FacilityDef, FacilityPlacementScope
    from space_idle.power import PowerSpec, SolarGeneration
    from space_idle.shared import DefinitionId

    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    env = sim.environment
    # The geographic registration and its per-body coverage have their own
    # contract. A daily-environment test only needs physically contrasting
    # sites, rather than repeating an every-body climate enumeration.
    first_cell_by_body = {}
    for cell in graph.surface_cells.values():
        first_cell_by_body.setdefault(cell.body_id, cell.id)
    flux_bodies = sorted(
        (body_id for body_id in first_cell_by_body
         if graph.representative_solar_flux_w_m2(body_id) is not None),
        key=graph.representative_solar_flux_w_m2,
    )
    representative_bodies = tuple(dict.fromkeys((
        flux_bodies[0], flux_bodies[-1], flux_bodies[len(flux_bodies) // 2],
    )))
    candidate_cells = tuple(first_cell_by_body[body_id] for body_id in representative_bodies)
    baseline_climate = {
        cell_id: (env.require(cell_id, IlluminationField), env.get(cell_id, ThermalField))
        for cell_id in candidate_cells
    }
    for cell_id in candidate_cells:
        body_id = graph.surface_cells[cell_id].body_id
        assert env.require(cell_id, GravityField).local_acceleration_m_s2 > 0
        assert env.require(cell_id, IlluminationField).solar_flux_w_m2 == pytest.approx(
            graph.representative_solar_flux_w_m2(body_id)
        )
    sim.advance_days(1)
    assert all((env.require(cell_id, IlluminationField), env.get(cell_id, ThermalField)) == climate
               for cell_id, climate in baseline_climate.items())

    # Same solar Facility at contrasting heliocentric distances receives
    # precisely the local registered flux, without another AU attenuation.
    # Exhaustive body input validation belongs to registration, not this
    # behavior test's repeated per-body facility installation.
    assert candidate_cells
    # Use a purpose-built solar Definition rather than requiring any named
    # Content Facility to remain in the catalogue.
    generator_id = DefinitionId("test.facility.solar_probe")
    solar = SolarGeneration(2.5, 1361.0)
    sim.power.specs[generator_id] = PowerSpec(solar, 0.0)
    facilities = FacilityBook({generator_id: FacilityDef(
        generator_id, "Solar probe", placement_scope=FacilityPlacementScope.SURFACE_CELL,
    )}, env)
    for cell_id in candidate_cells:
        node_id = graph.owner_of_cell(cell_id)
        if node_id is None:
            node_id = SpatialNodeId(f"test.power.{cell_id}")
            graph.found_location(node_id, "Power test", graph.surface_cells[cell_id].body_id, cell_id)
        facility_id = facilities.install(generator_id, node_id, site_cell_id=cell_id)
        generation = sim.power.physical_snapshot(node_id, facilities, sim.day).generation_mw_by_facility[facility_id]
        illum = env.require(cell_id, IlluminationField)
        assert generation == pytest.approx(
            solar.rated_mw_at_reference_flux * illum.solar_flux_w_m2 / solar.reference_flux_w_m2
            * illum.availability
        )


def test_surface_access_rules_follow_body_identity_and_physical_surface():
    """World Content can add landings without creating an OD table or player nodes."""
    app = build_game_application()
    sim = app._simulation
    graph = sim.graph
    resolver = sim.transport.movement_resolver()
    # Solid surfaces can be inaccessible; merely being a solid body does not
    # require authored descent/launch operations for every possible target.
    eligible = [rule.body_id for rule in resolver.surface_access_rules]
    # A body may admit multiple authored access methods with different operating
    # requirements; the physical-surface rule applies to each method independently.
    assert all(graph.bodies[body_id].physical_surface is PhysicalSurface.SOLID
               for body_id in eligible)

    # Synthetic bodies avoid making the continued existence of a particular
    # authored atmospheric planet a prerequisite for testing the generic rule.
    # Equal terminal names remain distinct physical contexts; atmosphere and
    # gravity, not names, determine the movement requirements.
    from space_idle.content.base_transport import build_surface_access_movement_rules
    from space_idle.spatial import AtmosphereField, EnvironmentResolver, StaticFacetStore
    from space_idle.transport import TransportOperationKind

    world = SpatialGraph()
    system = StarSystemId("test.system.access")
    geometry = CharacteristicTransportGeometry((0.0,))
    world.add_star_system(StarSystemDef(system, "Test access system", geometry))
    facets = StaticFacetStore()
    for name, pressure in (("test.outer.same", 100_000.0),
                           ("test.inner.same", 100_000.0),
                           ("test.vacuum.same", 0.0),
                           ("test.unknown.same", None)):
        body_id = CelestialBodyId(name)
        world.add_body(CelestialBodyDef(
            body_id, name, 2_000.0, system, geometry, reference_gravity_m_s2=4.0,
        ))
        if pressure is not None:
            facets.set_body(body_id, AtmosphereField(pressure, 0.0, {}))
    generated = build_surface_access_movement_rules(world, EnvironmentResolver(world, facets))
    by_body = {str(rule.body_id): rule for rule in generated}
    assert set(by_body) == {"test.outer.same", "test.inner.same", "test.vacuum.same"}
    outer, inner = by_body["test.outer.same"], by_body["test.inner.same"]
    assert outer.id != inner.id
    assert outer.gateway_capability_id == inner.gateway_capability_id == "launch_operations"
    assert outer.descent_operations == inner.descent_operations
    assert outer.descent_operations[0].operation_type == TransportOperationKind.ATMOSPHERIC_ENTRY
    vacuum = by_body["test.vacuum.same"]
    assert vacuum.gateway_capability_id == "surface_distribution"
    assert vacuum.descent_operations[0].operation_type == TransportOperationKind.LANDING


def test_founding_projections_are_scoped_to_explicit_targets_without_losing_other_cell_geography(monkeypatch):
    app = build_game_application()
    sim = app._simulation
    assert sim.founding is not None
    original = sim.founding.planning_failures
    visited = []

    def tracked(staging_id, target, recipe_id, vehicle_id, day=0, power=None):
        visited.append(sim.founding.target_context_id(target))
        return original(staging_id, target, recipe_id, vehicle_id, day, power)

    monkeypatch.setattr(sim.founding, "planning_failures", tracked)
    # Test multi-target query scoping against an available physical body,
    # rather than fixing the number or names of Moon Surface Cells.
    counts = {}
    for cell in sim.graph.surface_cells.values():
        counts[cell.body_id] = counts.get(cell.body_id, 0) + 1
    body_id = min((body for body, count in counts.items() if count >= 2),
                  key=counts.get)
    physical_cells = sim.graph.cells_for_body(body_id)
    body = str(body_id)
    unselected = app.query(GetSurfaceMap(body, ()))
    assert len(unselected.cells) == len(physical_cells)
    assert not visited
    assert all(not row.foundation_options for row in unselected.cells)
    cells = [str(row.id) for row in physical_cells]
    pinned = app.query(GetSurfaceMap(body, (cells[0], cells[1])))
    assert {str(value) for value in visited} == set(cells[:2])
    assert all(next(row for row in pinned.cells if row.id == cell).foundation_options for cell in cells[:2])
    assert all(not row.foundation_options for row in pinned.cells if row.id not in cells[:2])
    from space_idle.app_contracts.common import ApplicationError
    foreign_cell = next(
        cell.id for cell in sim.graph.surface_cells.values() if cell.body_id != body_id
    )
    with pytest.raises(ApplicationError, match="selected body"):
        app.query(GetSurfaceMap(body, (str(foreign_cell),)))

    visited.clear()
    # Context presence and the set of admissible Deployment recipes are
    # Content decisions. Verify projection and ownership for every registered
    # non-surface target without requiring a specific body, number of contexts,
    # or named founding package.
    owned = set(sim.graph.operational_node_ids())
    fleet = dict(sim.transport.fleet_pools)
    stock = dict(sim.inventory.stock)
    # The registration layer validates every physical context. Querying every
    # giant-world context with every recipe/vehicle/staging combination here
    # would repeat the same Application contract without new coverage.
    target = next(
        node for node in sim.graph.nodes.values()
        if (node.body_id is not None
            and sim.graph.bodies[node.body_id].physical_surface is PhysicalSurface.NO_SOLID_SURFACE
            and not sim.graph.has_operational_node(node.id))
    )
    context_id = str(target.id)
    listing = app.query(GetNonSurfaceFoundingOptions(str(target.body_id), ""))
    assert not visited  # Listing must not run detailed founding planning.
    assert any(row.spatial_node_id == context_id for row in listing.contexts)
    detailed = app.query(GetNonSurfaceFoundingOptions(str(target.body_id), context_id))
    projected = next(row for row in detailed.contexts if row.spatial_node_id == context_id)
    assert projected.spatial_node_id not in {str(node) for node in owned}
    assert not projected.operational
    assert all(option.blockers or option.can_plan for option in projected.foundation_options)
    assert {str(value) for value in visited} == {context_id}
    other_body = next(body.id for body in sim.graph.bodies.values() if body.id != target.body_id)
    from space_idle.app_contracts.common import ApplicationError
    with pytest.raises(ApplicationError, match="selected body"):
        app.query(GetNonSurfaceFoundingOptions(str(other_body), context_id))
    assert set(sim.graph.operational_node_ids()) == owned
    assert sim.transport.fleet_pools == fleet
    assert sim.inventory.stock == stock


def test_registered_world_inputs_and_representative_realization_preserve_global_geometry():
    """Product Content coverage is checked before expansion; generator rules
    are exercised on diverse real bodies, not two fully generated Solar Systems.
    """
    from math import pi
    from space_idle.content.base_spatial import build_world_registration
    from space_idle.content.surface_world import register_complete_surface_world
    from space_idle.surface_partition import validate_surface_partitions

    registered, environment = build_world_registration()
    # Realization itself validates the registered inputs; separate invalid
    # inputs are exercised at the registration boundary below.
    original_ids = set(registered.surface_cells)
    originals = tuple(registered.surface_cells.values())
    solid = [body for body in registered.bodies.values()
             if body.physical_surface is PhysicalSurface.SOLID]
    # register_complete_surface_world validates *every* registered body,
    # including reference presence and solid/non-solid consistency. Avoid
    # replicating its input-validation loop as a second test oracle.
    references_by_body = {body_id: [] for body_id in registered.bodies}
    for cell in originals:
        references_by_body[cell.body_id].append(cell)
    # Pick physically different inputs; do not make specific body names or
    # hard-coded Cell counts an architectural contract.
    by_radius = sorted(solid, key=lambda body: body.mean_radius_km)
    # The generator is generic: verify extremes and one intermediate size.
    # Geographic variation is a Content property, not a fixed per-body score.
    middle = by_radius[len(by_radius) // 2]
    selected = frozenset({by_radius[0].id, by_radius[-1].id, middle.id})
    budgets = {}
    for body_id in selected:
        sample = references_by_body[body_id]
        radius = registered.bodies[body_id].mean_radius_km
        for resource in {rid for cell in sample for rid in cell.resource_potential_by_resource}:
            budgets[(body_id, resource)] = (4 * pi * radius**2 / sum(c.area_km2 for c in sample)) * sum(
                c.resource_potential_by_resource.get(resource, 0.0) for c in sample
            )
    register_complete_surface_world(registered, environment.static, body_ids=selected)
    validate_surface_partitions(registered)
    assert original_ids <= set(registered.surface_cells)  # Named reference sites survive.
    assert len(registered.surface_cells) > len(original_ids)
    # Coverage, equal area and complete physical adjacency belong to the
    # partition validator above. A second graph walk of those same edges is
    # redundant in the representative Content test.
    for (body_id, resource), expected in budgets.items():
        actual = sum(cell.resource_potential_by_resource.get(resource, 0.0)
                     for cell in registered.cells_for_body(body_id))
        assert actual == pytest.approx(expected, rel=1e-10, abs=1e-10)
    # Authored geographical information must survive realization. Test the
    # mapping directly rather than prescribing a diversity score per planet.
    reference = references_by_body[middle.id][0]
    generated = registered.surface_cells[reference.id]
    assert generated.terrain == reference.terrain
    assert {rid for rid, value in generated.resource_potential_by_resource.items() if value > 0} == {
        rid for rid, value in reference.resource_potential_by_resource.items() if value > 0
    }
    # Regional differences arise from the generic physical generator, even
    # when new Content uses different reference placements or geology.
    generated_cells = [cell for cell in registered.cells_for_body(middle.id)
                       if cell.id not in original_ids]
    assert len({cell.terrain for cell in generated_cells}) > 1
    # Non-selected references remain exactly as authored, not regenerated.
    assert all(registered.surface_cells[cell.id] is cell for cell in originals
               if cell.body_id not in selected)



def test_registration_rejects_invalid_product_inputs_before_surface_expansion():
    from space_idle.content.base_spatial import build_world_registration
    from space_idle.content.surface_world import validate_surface_registration

    graph, _environment = build_world_registration()
    reference = next(iter(graph.surface_cells.values()))
    graph.surface_cells[reference.id] = replace(
        reference, resource_potential_by_resource={
            resource: float('nan') for resource in reference.resource_potential_by_resource
        },
    )
    with pytest.raises(ValueError, match='reference Resource potential'):
        validate_surface_registration(graph)
    graph.surface_cells[reference.id] = reference
    # Unregistered solid bodies and broken cross-body links are not repaired
    # by the regular generator or concealed by representative sampling.
    body_references = [cell for cell in graph.surface_cells.values()
                       if cell.body_id == reference.body_id]
    for cell in body_references:
        del graph.surface_cells[cell.id]
    with pytest.raises(ValueError, match='lacks geologic reference'):
        validate_surface_registration(graph)

    # A positive Resource reference that is numerically too small to survive
    # the generator's minimum deposit resolution must fail closed. Otherwise
    # budget normalization silently loses the entire resource on that body.
    from space_idle.content.surface_world import register_complete_surface_world
    small, environment = build_world_registration()
    body_id = reference.body_id
    ref_cells = [cell for cell in small.surface_cells.values() if cell.body_id == body_id]
    resource = next(iter(reference.resource_potential_by_resource))
    for cell in ref_cells:
        if resource in cell.resource_potential_by_resource:
            potential = dict(cell.resource_potential_by_resource)
            potential[resource] = 1e-300
            small.surface_cells[cell.id] = replace(cell, resource_potential_by_resource=potential)
    with pytest.raises(ValueError, match='invalid surface Resource distribution'):
        register_complete_surface_world(small, environment.static, body_ids=frozenset({body_id}))


def test_standard_partition_registration_conserves_resources_across_resolution():
    """Resolution independence belongs to the shared generator, not 29 copies."""
    from collections import defaultdict
    from space_idle.content.base_spatial import build_world_registration
    from space_idle.content import surface_world

    def realize(*, finer):
        graph, environment = build_world_registration()
        body = max((body for body in graph.bodies.values()
                    if body.physical_surface is PhysicalSurface.SOLID),
                   key=lambda b: b.mean_radius_km)
        if finer:
            original = surface_world._ring_count
            surface_world._ring_count = lambda radius: original(radius) + 2
        try:
            surface_world.register_complete_surface_world(
                graph, environment.static, body_ids=frozenset({body.id}),
            )
        finally:
            if finer:
                surface_world._ring_count = original
        # Geometry/adjacency is verified by the representative generator test;
        # this independent resolution comparison only needs the Resource totals.
        quantities = defaultdict(float)
        cells = graph.cells_for_body(body.id)
        for cell in cells:
            for rid, potential in cell.resource_potential_by_resource.items():
                quantities[rid] += potential
        return cells, quantities

    normal_cells, normal = realize(finer=False)
    finer_cells, finer = realize(finer=True)
    assert len(finer_cells) > len(normal_cells)
    assert normal.keys() == finer.keys()
    for resource, total in normal.items():
        assert finer[resource] == pytest.approx(total, rel=1e-10, abs=1e-10)


def test_standard_world_instances_do_not_share_mutable_static_mappings():
    from space_idle.content.base_spatial import instantiate_standard_world
    from space_idle.spatial import ThermalField

    left, left_env = instantiate_standard_world()
    right, right_env = instantiate_standard_world()
    cell_id = next(iter(left.surface_cells))
    assert left is not right
    assert left.surface_cells[cell_id] is not right.surface_cells[cell_id]
    assert left.surface_cells[cell_id].static_geology is not right.surface_cells[cell_id].static_geology
    left.surface_cells[cell_id].static_geology['test_mutation'] = 99.0
    assert 'test_mutation' not in right.surface_cells[cell_id].static_geology
    body = left.surface_cells[cell_id].body_id
    left.bodies.pop(body)
    assert body in right.bodies
    left_env.static.facets[(cell_id, ThermalField)] = ThermalField(500)
    assert left_env.static.facets != right_env.static.facets

def test_survey_product_registration_and_spatial_ids_reject_invalid_inputs():
    """Exercise registration at the boundary, not the entire product in every test."""
    from space_idle.content.base_spatial import build_world_registration
    from space_idle.content.base_progression import build_survey_targets, build_extraction_specs
    from space_idle.content.surface_world import validate_surface_registration
    from space_idle.shared import CelestialBodyId, DefinitionId
    from space_idle.survey_service import ValidatedSurveyRegistration

    graph, _ = build_world_registration()
    resources = frozenset(spec.resource_id for spec in build_extraction_specs().values())
    targets = build_survey_targets(graph)
    cells = frozenset(graph.surface_cells)
    # The certificate constructor is the structural invariant, not a separate
    # test loop which happens to repeat its implementation.
    verified = ValidatedSurveyRegistration(targets, resources, cells)
    assert verified.targets == targets
    bad = dict(targets)
    key, target = next(iter(targets.items()))
    bad[key] = replace(target, resource_id=DefinitionId('test.unregistered.resource'))
    with pytest.raises(ValueError, match='invalid Survey registration target'):
        ValidatedSurveyRegistration(bad, resources, cells)
    bad.pop(key)
    with pytest.raises(ValueError, match='does not cover the Cell/Resource product'):
        ValidatedSurveyRegistration(bad, resources, cells)

    sample = next(iter(graph.surface_cells.values()))
    with pytest.raises(ValueError, match="duplicate surface cell"):
        graph.add_surface_cell(sample)
    with pytest.raises(ValueError, match="unknown celestial body"):
        graph.add_surface_cell(replace(
            sample, id=SurfaceCellId("test.invalid.reference"),
            body_id=CelestialBodyId("test.unknown.body"),
        ))

    # Two authored bodies with different IDs but the same generated suffix
    # would otherwise overwrite a Cell in the completed World dict.
    body = graph.bodies[sample.body_id]
    collision = CelestialBodyId("test.validation." + str(sample.body_id).rsplit(".", 1)[-1])
    graph.add_body(replace(body, id=collision, parent_body_id=None))
    graph.add_surface_cell(replace(sample, id=SurfaceCellId("test.collision.reference"),
                                   body_id=collision, neighbor_ids=frozenset()))
    with pytest.raises(ValueError, match="generated surface Cell IDs collide"):
        validate_surface_registration(graph)


def test_unknown_surface_map_does_not_reveal_actual_resource_presence():
    """An unknown deposit and a barren site have the same public uncertainty.

    Cell × Resource target completeness and physical diversity are verified
    by the registration/generation contracts, not by this Map query.
    """
    app = build_game_application()
    sim = app._simulation
    moon = sim.graph.cells_for_body(ids.MOON)
    resource = ids.VOLATILE_BEARING_MATERIAL
    bearing = next(cell for cell in moon if cell.resource_potential_by_resource.get(resource, 0) > 0)
    barren = next(cell for cell in moon if cell.resource_potential_by_resource.get(resource, 0) == 0)
    view = app.query(GetSurfaceMap(str(ids.MOON), (str(bearing.id), str(barren.id))))
    for cell in (bearing, barren):
        exposed = next(row for row in view.cells if row.id == str(cell.id))
        assert exposed.display_name
        assert exposed.environment_knowledge_level == 0
        assert not exposed.environment
        evidence = next(row for row in exposed.resources if row.resource_id == str(resource))
        assert evidence.knowledge_level == 0
        assert evidence.presence_probability is None
        assert evidence.visible_potential is None


def test_verified_static_world_rechecks_modified_geography_and_facets():
    """Provenance reuses a proof only for unchanged records, not future edits."""
    from space_idle.validation import validate_simulation_configuration
    from space_idle.shared import DefinitionId
    from space_idle.spatial import IlluminationField, ThermalField
    from space_idle.validation_support import ConfigurationError

    app = build_game_application()
    sim = app._simulation
    # Initial product validation has already happened at composition.
    # Exercise invalidation only when authoritative static inputs change.
    cell_id, original = next(iter(sim.graph.surface_cells.items()))
    # A mutation made after the standard World's initial validation cannot
    # borrow that earlier geometric proof.
    sim.graph.surface_cells[cell_id] = replace(original, area_km2=original.area_km2 * 1.01)
    with pytest.raises(ValueError, match="surface cell physical area"):
        validate_simulation_configuration(sim)
    sim.graph.surface_cells[cell_id] = original

    # In-place changes to mutable per-Cell Content also invalidate the proof.
    resource = next(iter(original.resource_potential_by_resource))
    valid_potential = original.resource_potential_by_resource[resource]
    sim.graph.surface_cells[cell_id].resource_potential_by_resource[resource] = -1.0
    with pytest.raises(ConfigurationError, match="negative resource potential"):
        validate_simulation_configuration(sim)
    sim.graph.surface_cells[cell_id].resource_potential_by_resource[resource] = valid_potential
    # A separately materialized static registry is enough to verify
    # target-dictionary ownership; a second complete Application provides
    # no additional evidence for this static registry contract.
    from space_idle.content.base_progression import instantiate_standard_survey_targets
    other_targets = instantiate_standard_survey_targets()

    facet_id = next(key for key in sim.environment.static.facets if key[1] is IlluminationField)
    saved_facet = sim.environment.static.facets[facet_id]
    sim.environment.static.facets[facet_id] = ThermalField(300.0)
    with pytest.raises(ConfigurationError, match="environment facet type mismatch"):
        validate_simulation_configuration(sim)
    sim.environment.static.facets[facet_id] = saved_facet

    # Target registry is also independent across composed games even when
    # immutable SurveyTarget Definitions come from the same Content template.
    target_id = next(iter(sim.survey.targets))
    removed = sim.survey.targets.pop(target_id)
    assert target_id in other_targets
    # Static geometry verification never substitutes for Survey's own
    # registration checks when targets have been changed independently.
    sim.survey.targets[target_id] = replace(removed, resource_id=DefinitionId("test.invalid.survey_resource"))
    with pytest.raises(ConfigurationError, match="survey target key mismatch"):
        validate_simulation_configuration(sim)
    sim.survey.targets[target_id] = removed
