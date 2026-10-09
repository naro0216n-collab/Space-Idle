from __future__ import annotations

from e2e_support import isolated_browser_context, monitored_page, wait_for_server

import os
from pathlib import Path
from threading import Thread
import tempfile

from space_idle import AdvanceTime, CreateTransportAllocation, GetFleet, GetTransportAllocations, PlanBuild, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy


EARTH = str(ids.EARTH)
LEO = str(ids.LEO)
PROPELLANT = str(ids.PROPELLANT)
OWNED_LAUNCH_VEHICLE = str(ids.REUSABLE_LAUNCH_VEHICLE)


def _choose_priority(root, holder_selector: str, level: int | str) -> None:
    value = str(level)
    holder = root.locator(holder_selector)
    group = holder.locator("xpath=ancestor::*[contains(@class,'priority-segment')][1]")
    group.locator(f'[data-priority-choice="{value}"]').click()
    assert holder.input_value() == value


def _build_logistics_test_application():
    app = build_game_application()
    app._simulation.technology.completed.update(  # noqa: SLF001 - deterministic E2E fixture setup
        {ids.LM_LOGISTICS_MAINTENANCE_01, ids.CR_CRYOGENIC_STORAGE_TRANSFER_03}
    )
    return app


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-logistics-ui-")
    runtime = GameRuntime(
        new_game_factory=_build_logistics_test_application,
        load_factory=build_game_application_for_load,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
    )
    runtime.set_time_control(paused=True)
    project_id = runtime.execute(
        PlanBuild(
            LEO,
            str(ids.ORBITAL_LOGISTICS_NODE),
            priority=5,
            procurement_policy="immediate",
        )
    ).data.created_id
    assert project_id is not None
    # Establish a real project-owned Supply Requirement so browser controls can
    # exercise sparse routing intent against an Application-projected decision row.
    runtime.execute(AdvanceTime(1))
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        wait_for_server(origin)
        with isolated_browser_context(
            browser_name,
            viewport={"width": 1194, "height": 834},
            has_touch=True,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        ) as context, monitored_page(context) as page:
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.locator('.primary-nav-button[data-section="logistics"]').click()

            fleet_pool = page.locator('#vehicleTable [data-fleet-pool-row]').first
            fleet_pool.wait_for(timeout=10000)
            assert fleet_pool.locator(".fleet-commitment-grid [data-fleet-usage]").count() > 0

            constraint_button = page.locator(
                f'#requirementTable [data-requirement-constraint][data-owner-id="{project_id}"]'
            ).first
            constraint_button.wait_for(timeout=10000)
            requirement_row = constraint_button.locator("xpath=ancestor::*[contains(@class,'supply-requirement-card')][1]")
            assert "輸送能力阻害" in requirement_row.inner_text(), (
                "Supply Requirement must remain visible while Transport Capacity is unavailable"
            )
            requirement_id = requirement_row.get_attribute("data-requirement-id")
            assert requirement_id
            decision_item = page.locator(
                f'#logisticsDecisionLane [data-logistics-decision-kind="supply_requirement"]'
                f'[data-logistics-decision-id="{requirement_id}"]'
            )
            decision_item.wait_for(timeout=10000)
            decision_text = decision_item.inner_text()
            assert "輸送能力阻害" in decision_text, (
                "Transport Decision Lane must preserve the Application supply-state classification"
            )
            assert "輸送能力不足" in decision_text, (
                "Transport Decision Lane must surface the concrete Application-projected blocker"
            )
            decision_item.click()
            page.locator("#networkDecisionContext").wait_for(state="visible", timeout=10000)
            assert "補給需要" in page.locator("#networkDecisionContext").inner_text()
            requirement_resource = constraint_button.get_attribute('data-resource-id')
            assert requirement_resource
            assert page.locator('#systemMapResourceFilter').input_value() == requirement_resource
            # A resource chosen at a location must resolve the same scoped
            # Demand/Allocation context in Transport, without a second search.
            page.locator('.primary-nav-button[data-section="location"]').click()
            page.locator(f'[data-location-id="{LEO}"]').click()
            page.locator('[data-section-tab="location"][data-tab="inventory"]').click()
            resource_card = page.locator(
                f'#operationsTabContent [data-inspect="resource"][data-id="{requirement_resource}"]'
            ).first
            resource_card.wait_for(timeout=10000)
            resource_card.click()
            resource_link = page.locator('#inspectorContent [data-issue-area="logistics"][data-issue-subject-kind="dependency_resource"]')
            resource_link.wait_for(timeout=10000)
            resource_link.click()
            assert page.locator('#logisticsView').is_visible()
            assert page.locator('#systemMapResourceFilter').input_value() == requirement_resource
            assert "関連する補給需要" in page.locator('#networkDecisionContext').inner_text()
            assert page.locator(f'#requirementTable [data-requirement-id="{requirement_id}"]').get_attribute('class').find('is-context-target') >= 0
            scoped_inspector = page.locator('#movementPlanInspectorContent')
            assert '現地Resource' in scoped_inspector.inner_text()
            assert '補給と輸送中貨物' in scoped_inspector.inner_text()
            scoped_inspector.locator(f'[data-open-location="{LEO}"]').click()
            assert page.locator('#operationsView').is_visible()
            assert page.locator('#inspectorTitle').inner_text() == page.evaluate('id => window.SpaceIdleApp.resourceName(id)', requirement_resource)
            # Project-owned supply uses the same decision identity even when
            # reached from the construction Inspector rather than Transport.
            page.locator('[data-section-tab="location"][data-tab="construction"]').click()
            page.locator(f'#operationsTabContent [data-inspect="project"][data-id="{project_id}"]').click()
            project_requirement = page.locator(
                f'#inspectorContent [data-issue-area="logistics"][data-issue-subject-id="{requirement_id}"]'
            )
            project_requirement.wait_for(timeout=10000)
            project_requirement.click()
            assert page.locator(f'#requirementTable [data-requirement-id="{requirement_id}"]').get_attribute('class').find('is-context-target') >= 0
            assert page.locator('#systemMapResourceFilter').input_value() == requirement_resource
            requirement_details = page.locator('#movementPlanInspectorContent').inner_text()
            assert all(label in requirement_details for label in ('未充足', '現地供給', '輸送系内'))
            # A supply shortfall is not evidence of an operating transport
            # connection. The spatial canvas must remain available even when
            # there is no allocated service for this requirement.
            assert page.locator("#systemMapStage [data-system-node-id]").count() > 0
            assert page.locator("#systemMapRelations [data-system-allocation-id]").count() == page.evaluate(
                "() => window.SpaceIdleApp.state.transportAllocations?.items?.length || 0"
            )
            # Create and later clear a project-scoped Routing Constraint through the UI.
            requirement_row.locator("[data-requirement-constraint]").click()
            page.locator("#routingConstraintDialog").wait_for(state="visible", timeout=10000)
            scope_text = page.locator("#routingConstraintScopeSummary").inner_text()
            assert project_id not in scope_text
            assert page.locator("#routingConstraintDialog").locator('input[type="text"]').count() == 0
            page.locator("#routingConstraintSource").select_option(EARTH)
            page.get_by_role("button", name="経路条件を保存").click()
            page.locator("#routingConstraintDialog").wait_for(state="hidden", timeout=10000)
            page.wait_for_function(
                """projectId => [...document.querySelectorAll('#requirementTable [data-requirement-constraint]')]
                  .some(button => button.dataset.ownerId === projectId && button.closest('.supply-requirement-card')?.innerText.includes('固定:'))""",
                arg=project_id,
                timeout=10000,
            )
            requirement_row = page.locator(
                f'#requirementTable [data-requirement-constraint][data-owner-id="{project_id}"]'
            ).first.locator("xpath=ancestor::*[contains(@class,'supply-requirement-card')][1]")
            assert project_id not in requirement_row.inner_text()
            constraint_clear = page.locator('[data-routing-constraint-clear]').first
            constraint_clear.wait_for(timeout=10000)

            # Create, edit, pause, resume, and delete Transport Allocation using only
            # browser controls. Domain allocation invariants are covered below E2E.
            page.get_by_role("button", name="輸送能力を設定").click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            page.locator("#allocationVehicle").select_option(OWNED_LAUNCH_VEHICLE)
            page.locator("#allocationSource").select_option(EARTH)
            page.locator("#allocationDestination").select_option(LEO)
            movement_card = page.locator("#allocationMovementChoices [data-allocation-movement-card]").first
            movement_card.wait_for(timeout=10000)
            movement_text = movement_card.inner_text()
            for label in ("所要時間", "必要Δv", "運行周期", "1機あたり往路能力", "満載時運用資源"):
                assert label in movement_text, f"Movement candidate must expose {label} before hard-constraint selection"
            movement_control = movement_card.locator("[data-allocation-movement]")
            assert movement_control.get_attribute("aria-pressed") == "false"
            page.locator('#allocationForwardPresets [data-allocation-capacity-preset="forward"]').nth(1).wait_for(timeout=10000)
            page.locator('#allocationForwardPresets [data-allocation-capacity-preset="forward"]').nth(1).click()
            assert float(page.locator("#allocationForward").input_value()) > 0
            assert page.locator("#allocationForward").evaluate("input => input.checkValidity()"), (
                "Application-derived capacity presets must remain valid precision inputs"
            )
            page.locator("#allocationPreview .kv-grid dt").first.wait_for(timeout=10000)
            assert page.locator("#allocationPreview .kv-grid dd").count() >= 4
            assert all(value.strip() for value in page.locator("#allocationPreview .kv-grid dd").all_inner_texts())
            page.locator('[data-allocation-priority="5"]').click()
            page.get_by_role("button", name="輸送設定を作成").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            allocation_row = page.locator("#allocationTable [data-allocation-row]").first
            allocation_row.wait_for(timeout=10000)
            allocation_id = allocation_row.get_attribute("data-allocation-row")
            assert allocation_id

            # Verify real Application-owned Fleet quantities in the browser.
            # Text labels alone could remain present while showing wrong numbers.
            pools = runtime.query(GetFleet()).data.pools
            pool = next(pool for pool in pools if pool.transport_units > 0)
            fleet_pool = page.locator(
                f'#vehicleTable [data-fleet-pool-row][data-fleet-node-id="{pool.operational_node_id}"]'
                f'[data-fleet-vehicle-id="{pool.vehicle_definition_id}"]'
            )
            fleet_pool.wait_for(timeout=10000)
            assert fleet_pool.locator(".decision-card-title strong").inner_text() == pool.display_name
            expected_usage = {
                key.removesuffix("_units"): value
                for key, value in vars(pool).items()
                if key.endswith("_units") and key not in {"total_units", "free_units"}
                and (key != "other_committed_units" or value > 0)
            }
            rendered_usage = {
                metric.get_attribute("data-fleet-usage"): int(metric.locator("strong").inner_text())
                for metric in fleet_pool.locator(".fleet-commitment-grid [data-fleet-usage]").all()
            }
            assert rendered_usage == expected_usage
            fleet_pool.locator('[data-fleet-map-node]').click()
            assert page.locator('#systemMapResourceFilter').input_value() == ''
            assert page.locator(f'#systemMapStage [data-system-node-id="{pool.operational_node_id}"]').get_attribute('aria-pressed') == 'true'
            assert page.locator('#movementPlanInspectorTitle').inner_text() == page.evaluate(
                'id => window.SpaceIdleApp.locationName(id)', pool.operational_node_id
            )
            # An explicit Resource choice is carried between entrances; the
            # earlier Fleet decision intentionally cleared the stale filter.
            page.locator('#systemMapResourceFilter').select_option(requirement_resource)
            assert all(
                metric.locator("small").inner_text().strip()
                for metric in fleet_pool.locator(".fleet-commitment-grid [data-fleet-usage]").all()
            )

            allocation_text = allocation_row.inner_text()
            for label in ("目標", "必要機体", "利用可能", "使用中", "余力", "周期"):
                assert label in allocation_text, f"Transport Allocation card must expose {label}"

            allocation_row.locator("[data-allocation-network]").click()
            page.locator("#networkDecisionContext").wait_for(state="visible", timeout=10000)
            assert "輸送能力設定" in page.locator("#networkDecisionContext").inner_text()
            allocation_map_entry = page.locator(
                f'#systemMapRelations [data-system-allocation-id="{allocation_id}"]'
            )
            allocation_map_entry.wait_for(state="visible", timeout=10000)
            assert allocation_map_entry.get_attribute("aria-pressed") == "true"
            # Comparing several allocations must not lose the keyboard target
            # merely because a new authoritative projection has been rendered.
            allocation_map_entry.focus()
            page.evaluate("() => window.SpaceIdleSystemMap.onSelect()")
            assert allocation_map_entry.evaluate("node => document.activeElement === node"), (
                "shared Map relation controls must retain focus across redraw"
            )
            assert page.locator("#systemMapStage .system-map-edge.is-context-related").count() > 0
            allocation_details = page.locator("#movementPlanInspectorContent").inner_text()
            assert all(label in allocation_details for label in (
                '目標', 'Nominal', '利用可能', '使用中', '余力', '必要Fleet', '運用Resource',
            ))
            # Shared Resource selection is UI context; it must survive a round trip
            # through the overview entrance without creating another spatial map.
            page.locator('.primary-nav-button[data-section="global"]').click()
            assert page.locator('#systemMapResourceFilter').input_value() == requirement_resource
            page.locator('.primary-nav-button[data-section="logistics"]').click()
            assert page.locator('#systemMapResourceFilter').input_value() == requirement_resource
            assert page.locator('#systemMapRelations [data-system-allocation-id]').count() > 0

            allocation_row = page.locator(f'[data-allocation-row="{allocation_id}"]')
            allocation_row.locator('[data-allocation-edit]').click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            page.locator('#allocationPreview .kv-grid dt').first.wait_for(timeout=10000)
            assert '現在のCapacity target' in page.locator('#allocationPreview').inner_text()
            assert '輸送能力目標' in page.locator('#allocationPreview').inner_text()
            page.locator('[data-allocation-priority="4"]').click()
            page.get_by_role("button", name="設定を更新").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)
            allocation_row = page.locator(f'[data-allocation-row="{allocation_id}"]')
            allocation_row.wait_for(timeout=10000)
            allocation_row.locator('[data-allocation-edit]').click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            assert page.locator("#allocationPriority").input_value() == "4"
            page.locator("#allocationCancelButton").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            allocation_toggle = allocation_row.locator('[data-allocation-toggle]')
            assert allocation_toggle.is_enabled()
            allocation_toggle.click()
            page.wait_for_function(
                "id => document.querySelector(`[data-allocation-row=\"${id}\"] [data-allocation-toggle]`)?.dataset.paused === '1'",
                arg=allocation_id,
                timeout=10000,
            )
            allocation_toggle = page.locator(f'[data-allocation-row="{allocation_id}"] [data-allocation-toggle]')
            assert allocation_toggle.is_enabled()
            allocation_toggle.click()
            page.wait_for_function(
                "id => document.querySelector(`[data-allocation-row=\"${id}\"] [data-allocation-toggle]`)?.dataset.paused === '0'",
                arg=allocation_id,
                timeout=10000,
            )

            # Cargo is not admitted Inventory; inspect the physical leg and final
            # destination separately when this state contains an in-flight parcel.
            cargo_card = page.locator('#cargoTable .cargo-flow-card').first
            if cargo_card.count():
                assert '最終目的地' in cargo_card.inner_text()
                assert '次のhandoff' in cargo_card.inner_text()
                cargo_card.locator('[data-cargo-inspect]').click()
                cargo_inspector = page.locator('#movementPlanInspectorContent').inner_text()
                assert all(label in cargo_inspector for label in (
                    '輸送中のResource', '最終目的地', '次の引継先', '輸送量',
                ))

            # Target Stock is a persistent Supply Planning intent with Activity Priority.
            page.get_by_role("button", name="追加備蓄を設定").click()
            page.locator("#targetStockDialog").wait_for(state="visible", timeout=10000)
            page.locator("#targetStockDestination").select_option(LEO)
            page.locator("#targetStockResource").select_option(PROPELLANT)
            page.wait_for_function(
                """() => ['current','inbound','demand'].every(
                  key => document.querySelector(`#targetStockOptionSummary [data-stock-summary="${key}"]`)
                )""",
                timeout=10000,
            )
            summary = page.locator("#targetStockOptionSummary")
            assert summary.locator('[data-stock-summary="current"]').count() == 1
            assert summary.locator('[data-stock-summary="inbound"]').count() == 1
            assert summary.locator('[data-stock-summary="demand"]').count() == 1
            page.locator("#targetStockQuantityRange").fill("1")
            page.locator('[data-target-stock-priority="4"]').click()
            page.get_by_role("button", name="追加備蓄を保存").click()
            page.locator("#targetStockDialog").wait_for(state="hidden", timeout=10000)
            target_delete = page.locator(
                f'[data-target-stock-delete="{LEO}"][data-resource-id="{PROPELLANT}"]'
            )
            target_delete.wait_for(timeout=10000)
            target_row = target_delete.locator("xpath=ancestor::*[@data-target-stock-row]")
            target_text = target_row.inner_text()
            assert "1" in target_text and "高" in target_text
            target_delete.click()
            target_delete.wait_for(state="detached", timeout=10000)

            constraint_clear = page.locator('[data-routing-constraint-clear]').first
            constraint_clear.click()
            constraint_clear.wait_for(state="detached", timeout=10000)

            allocation_delete = page.locator(
                f'[data-allocation-row="{allocation_id}"] [data-allocation-delete]'
            )
            allocation_delete.click()
            page.wait_for_function(
                "id => !document.querySelector(`[data-allocation-row=\"${id}\"]`)",
                arg=allocation_id,
                timeout=10000,
            )

            # Trade Order lifecycle belongs to the Economy decision canvas even
            # though it uses the same Application snapshot as logistics.
            page.locator('.primary-nav-button[data-section="economy"]').click()
            market_new = page.locator('[data-new-market-order]')
            market_new.wait_for(timeout=10000)
            market_create = market_new.locator('[data-market-create]')
            assert market_create.is_enabled()
            market_new.locator('[data-market-target]').fill('1')
            market_create.click()
            market_order = page.locator('[data-market-order-row]').first
            market_order.wait_for(timeout=10000)
            market_order_id = market_order.get_attribute('data-market-order-row')
            assert market_order_id
            market_order.locator('[data-market-target]').fill('2')
            _choose_priority(market_order, '[data-market-priority]', 4)
            market_order.locator('[data-market-save]').click()
            page.wait_for_function(
                "id => document.querySelector(`[data-market-order-row=\"${id}\"] [data-market-target]`)?.value === '2'",
                arg=market_order_id,
                timeout=10000,
            )
            page.locator(
                f'[data-market-order-row="{market_order_id}"] [data-market-cancel]'
            ).click()
            page.wait_for_function(
                "id => !document.querySelector(`[data-market-order-row=\"${id}\"]`)",
                arg=market_order_id,
                timeout=10000,
            )

            # The Map relation is a visual grouping, not a unique allocation.
            # Two independent settings on the same OD must remain individually
            # inspectable, even when their capacity targets differ sharply.
            first_parallel_id = runtime.execute(CreateTransportAllocation(
                OWNED_LAUNCH_VEHICLE, EARTH, LEO,
                target_forward_t_per_day=0.25, target_reverse_t_per_day=0.0,
            )).data.created_id
            second_parallel_id = runtime.execute(CreateTransportAllocation(
                OWNED_LAUNCH_VEHICLE, EARTH, LEO,
                target_forward_t_per_day=0.0, target_reverse_t_per_day=0.0,
            )).data.created_id
            assert first_parallel_id and second_parallel_id and first_parallel_id != second_parallel_id
            parallel_rows = runtime.query(GetTransportAllocations()).data.items
            parallel = {row.id: row for row in parallel_rows if row.id in (first_parallel_id, second_parallel_id)}
            assert len(parallel) == 2
            assert parallel[first_parallel_id].target_capacity.forward_t_per_day > 0
            assert parallel[second_parallel_id].target_capacity.forward_t_per_day == 0

            page.reload(wait_until='load')
            page.locator('#connectionState.is-ok').wait_for(timeout=10000)
            page.locator('.primary-nav-button[data-section="logistics"]').click()
            relation = page.locator('#systemMapRelations .system-map-relation').filter(
                has=page.locator(f'[data-system-allocation-id="{first_parallel_id}"]')
            )
            relation.wait_for(state='visible', timeout=10000)
            assert relation.locator('[data-system-allocation-id]').count() == 2
            assert '2 設定を比較' in relation.locator('[data-system-pair]').inner_text()
            first_button = relation.locator(f'[data-system-allocation-id="{first_parallel_id}"]')
            second_button = relation.locator(f'[data-system-allocation-id="{second_parallel_id}"]')
            first_button.click()
            assert first_button.get_attribute('aria-pressed') == 'true'
            second_button.click()
            assert first_button.get_attribute('aria-pressed') == 'false'
            assert second_button.get_attribute('aria-pressed') == 'true'
            relation.locator('[data-system-pair]').click()
            assert first_button.get_attribute('aria-pressed') == 'true'
            assert second_button.get_attribute('aria-pressed') == 'true'

            # A remote node selected on the shared Map is an inspection scope,
            # not a command to change the location running the simulation.
            remote_id = page.evaluate("""() => {
                const state = window.SpaceIdleApp.state;
                return state.world.operational_nodes.find(node => node.id !== state.operationalNodeId)?.id;
            }""")
            assert remote_id
            execution_id = page.evaluate('() => window.SpaceIdleApp.state.operationalNodeId')
            page.locator(f'#systemMapNodeIndex [data-system-node-jump="{remote_id}"]').click()
            page.wait_for_function(
                'id => window.SpaceIdleApp.state.inspectedNode?.id === id', arg=remote_id
            )
            assert page.evaluate('() => window.SpaceIdleApp.state.operationalNodeId') == execution_id
            remote_resource = page.evaluate(
                '() => window.SpaceIdleApp.state.inspectedNode.inventory?.[0]?.resource_id || null'
            )
            if remote_resource:
                page.locator('#systemMapResourceFilter').select_option(remote_resource)
                assert '現在在庫' in page.locator('#movementPlanInspectorContent').inner_text()
                assert '現地生産' in page.locator('#movementPlanInspectorContent').inner_text()

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
