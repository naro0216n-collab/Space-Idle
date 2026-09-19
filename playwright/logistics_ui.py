from __future__ import annotations

from e2e_support import isolated_browser_context, monitored_page, wait_for_server

import os
from pathlib import Path
from threading import Thread
import tempfile

from space_idle import AdvanceTime, PlanBuild, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy


EARTH = str(ids.EARTH)
LEO = str(ids.LEO)
PROPELLANT = str(ids.PROPELLANT)
OWNED_LAUNCH_VEHICLE = str(ids.REUSABLE_LAUNCH_VEHICLE)


def _build_logistics_test_application():
    app = build_game_application()
    app._simulation.technology.completed.update(  # noqa: SLF001 - deterministic E2E fixture setup
        {ids.TECH_ORBITAL_OPERATIONS, ids.TECH_CISLUNAR_LOGISTICS}
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

            constraint_button = page.locator(
                f'#requirementTable [data-requirement-constraint][data-owner-id="{project_id}"]'
            ).first
            constraint_button.wait_for(timeout=10000)
            requirement_row = constraint_button.locator("xpath=ancestor::tr")
            assert "輸送能力阻害" in requirement_row.inner_text(), (
                "Supply Requirement must remain visible while Transport Capacity is unavailable"
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
                  .some(button => button.dataset.ownerId === projectId && button.closest('tr')?.innerText.includes('固定条件'))""",
                arg=project_id,
                timeout=10000,
            )
            requirement_row = page.locator(
                f'#requirementTable [data-requirement-constraint][data-owner-id="{project_id}"]'
            ).first.locator("xpath=ancestor::tr")
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
            page.locator('#allocationForwardPresets [data-allocation-capacity-preset="forward"]').nth(1).wait_for(timeout=10000)
            page.locator('#allocationForwardPresets [data-allocation-capacity-preset="forward"]').nth(1).click()
            assert float(page.locator("#allocationForward").input_value()) > 0
            assert page.locator("#allocationForward").evaluate("input => input.checkValidity()"), (
                "Application-derived capacity presets must remain valid precision inputs"
            )
            page.locator("#allocationPreview").get_by_text("必要Fleet", exact=True).wait_for(timeout=10000)
            assert "unit" in page.locator("#allocationPreview").inner_text()
            page.locator('[data-allocation-priority="5"]').click()
            page.get_by_role("button", name="輸送設定を作成").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            allocation_row = page.locator("#allocationTable [data-allocation-row]").first
            allocation_row.wait_for(timeout=10000)
            allocation_id = allocation_row.get_attribute("data-allocation-row")
            assert allocation_id
            assert "方向別Capacity target" in allocation_row.inner_text()

            allocation_row.locator('[data-allocation-edit]').click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
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
            assert allocation_toggle.inner_text() == "停止"
            allocation_toggle.click()
            page.wait_for_function(
                "id => document.querySelector(`[data-allocation-row=\"${id}\"] [data-allocation-toggle]`)?.dataset.paused === '1'",
                arg=allocation_id,
                timeout=10000,
            )
            allocation_toggle = page.locator(f'[data-allocation-row="{allocation_id}"] [data-allocation-toggle]')
            assert allocation_toggle.inner_text() == "再開"
            allocation_toggle.click()
            page.wait_for_function(
                "id => document.querySelector(`[data-allocation-row=\"${id}\"] [data-allocation-toggle]`)?.dataset.paused === '0'",
                arg=allocation_id,
                timeout=10000,
            )

            # Target Stock is a persistent Supply Planning intent with Activity Priority.
            page.get_by_role("button", name="追加備蓄を設定").click()
            page.locator("#targetStockDialog").wait_for(state="visible", timeout=10000)
            page.locator("#targetStockDestination").select_option(LEO)
            page.locator("#targetStockResource").select_option(PROPELLANT)
            summary_primary = page.locator("#targetStockOptionSummary .cell-sub").first
            summary_primary.wait_for(timeout=10000)
            assert "通常需要" in summary_primary.inner_text()
            page.locator("#targetStockQuantityRange").fill("1")
            page.locator('[data-target-stock-priority="4"]').click()
            page.get_by_role("button", name="追加備蓄を保存").click()
            page.locator("#targetStockDialog").wait_for(state="hidden", timeout=10000)
            target_delete = page.locator(
                f'[data-target-stock-delete="{LEO}"][data-resource-id="{PROPELLANT}"]'
            )
            target_delete.wait_for(timeout=10000)
            target_row = target_delete.locator("xpath=ancestor::tr")
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
            market_order.locator('[data-market-priority]').select_option('4')
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

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run()
