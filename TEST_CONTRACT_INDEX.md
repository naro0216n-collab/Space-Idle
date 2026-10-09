# Test contract ownership index

This is a navigation index for the **current** test suite, not a game specification or
an independent testing policy. `docs/design.md`, `docs/architecture.md`, and
`docs/development-principles.md` §6 remain authoritative. The detailed execution
and publish procedure is in `DEVELOPMENT.md`.

Before adding a regression test, find the owning contract in this table. Extend its
existing invariant/transition scenario where possible; add a distinct test only
when a separately falsifiable *current* contract has no suitable owner. An
individual defect, Content ID, migration step, or UI implementation detail does
not by itself create a new contract. Review adjacent layers for duplicate
assertions: Domain owns rules, Application owns their projection, HTTP owns the
boundary, and browser acceptance owns actual interaction continuity.

| Owning contract | Test modules / acceptance entrypoint | Boundary verified |
| --- | --- | --- |
| Domain ownership, registration and dependency order | `tests/test_modularity.py`, `tests/test_execution_requirements.py` | Dependency direction, deterministic allocation, extensible contracts |
| Time and normal/offline Simulation | `tests/test_time_progression.py` | Clock control, invalid elapsed time, canonical day transitions |
| Authoritative state and derived-state restoration | `tests/test_persistence.py` | Whole-snapshot roundtrip, Offline equivalence, validation/atomic save, cache rederivation |
| Resource accounting and market | `tests/test_inventory_admission.py`, `tests/test_market.py`, `tests/test_maintenance.py` | Pool admission, funds and stock conservation, ongoing operating allocation |
| Local resource production and external dependency | `tests/test_resource_potential_extraction.py`, `tests/test_dependency_analytics.py`, `tests/test_supply_planning.py` | Knowledge-limited extraction, flow accounting, resource reservations and cargo transit |
| Building, assets, facilities and infrastructure | `tests/test_construction_state_transitions.py`, `tests/test_facility_lifecycle.py`, `tests/test_facility_surface_placement.py`, `tests/test_surface_infrastructure.py` | Project ownership, build/decommission, Site eligibility and services |
| World, environment and operational-node founding | `tests/test_surface_spatial_model.py`, `tests/test_dynamic_environment.py`, `tests/test_surface_location_projects.py` | Graph/Cell invariants, overlays, node creation and founding-owned payload |
| Movement, vehicles and Fleet | `tests/test_movement_planning.py`, `tests/test_vehicle_configuration.py`, `tests/test_vehicle_production.py`, `tests/test_fleet_allocations.py`, `tests/test_fleet_retirement.py` | Physical operation requirements, Fleet ownership/commitment, production/retirement |
| Research and scientific operations | `tests/test_research_phase_model.py`, `tests/test_research_execution.py`, `tests/test_scientific_exploration.py`, `tests/test_survey_progression.py` | Research DAG and stage execution, experiment, survey, provider commitments |
| Base Content integration | `tests/test_base_content_research_resource_integration.py`, `tests/test_solar_system_world.py` | Definition connectivity and physical world examples without fixing balancing figures or generic rules |
| Application decision state | `tests/test_application_decision_projection.py` | Player-facing blockers, options, projections, scope and read-only behavior |
| HTTP and packaged WebUI boundary | `tests/test_api_server.py` | Command/revision/query routing, persistence endpoints, resource serving |
| Publish Gateway transport | `development_tests/test_publish_request.py` | Snapshot restore, fixed-slot packets, transaction safety and gateway contract |
| Workflow and control-plane maintenance | `development_tests/test_workflow_maintenance.py`, `development_tests/test_publish_control_maintenance.py` | Workflow-only/control-only transactions and rehydration |
| Test and browser runners | `development_tests/test_local_test_run.py`, `development_tests/test_browser_e2e_harness.py` | Real pytest exit versus external tool timeout, scenario discovery and browser isolation |
| Interactive browser acceptance | `playwright/acceptance.py`, `playwright/interaction_continuity.py`, `playwright/logistics_ui.py` | Direct browser-to-server decisions, persisted drafts and navigation, logistics controls |

`tests/conftest.py`, `development_tests/script_harness.py`, and
`playwright/e2e_support.py` supply test inputs and orchestration, not a separate
set of business rules. New fixtures and helpers should be shared only for a
common contract, not introduced to hide unrelated per-scenario behavior.
