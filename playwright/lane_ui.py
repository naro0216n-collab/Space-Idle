from __future__ import annotations

from e2e_support import (
    guard_ci_secondary_entrypoint,
    isolated_browser_context,
    run_ci_suite_or_standalone,
)

if __name__ == "__main__" and guard_ci_secondary_entrypoint(__file__):
    raise SystemExit(0)

import os
from pathlib import Path
from threading import Thread
import tempfile
import time
import urllib.request

from space_idle import build_game_application
from space_idle.content import base_ids as ids
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.simulation import OfflineProgressPolicy



def _build_lane_test_application():
    app = build_game_application()
    sim = app._simulation  # noqa: SLF001 - deterministic browser fixture setup
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LEO)
    sim.facilities.install(ids.ORBITAL_LOGISTICS_NODE, ids.LUNAR_ORBIT)
    sim.inventory.add(ids.LEO, ids.PROPELLANT, 100.0)
    sim.inventory.add(ids.LUNAR_ORBIT, ids.PROPELLANT, 100.0)
    return app


def _wait_for_server(origin: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{origin}/api/v1/health", timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"server did not become ready: {last_error}")


def run() -> None:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in {"chromium", "webkit"}:
        raise ValueError(f"unsupported browser: {browser_name}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-lane-ui-")
    runtime = GameRuntime(
        factory=_build_lane_test_application,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=1.0),
    )
    server = create_server(runtime, ApiServerConfig(host="127.0.0.1", port=0))
    origin = f"http://127.0.0.1:{int(server.server_address[1])}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_server(origin)
        with isolated_browser_context(
            browser_name,
            viewport={"width": 1194, "height": 834},
        ) as context:
            page = context.new_page()
            page.goto(origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)
            page.locator("#timePauseButton").click()
            page.wait_for_function(
                "() => document.querySelector('#timePauseButton')?.getAttribute('aria-pressed') === 'true'",
                timeout=10000,
            )
            page.get_by_role("button", name="物流ネットワーク").click()

            production_option = page.locator(
                "#vehicleProductionTable [data-production-option-row]"
            ).filter(has=page.locator("button[data-produce-vehicle]:not([disabled])")).first
            production_option.wait_for(timeout=10000)
            production_option.locator("[data-production-priority-value]").fill("37")
            page.wait_for_timeout(1200)
            assert production_option.locator("[data-production-priority-value]").input_value() == "37"
            production_option.locator("button[data-produce-vehicle]").click()
            project_row = page.locator(
                "#vehicleProductionTable [data-production-project-row]"
            ).first
            project_row.wait_for(timeout=10000)
            assert project_row.locator("[data-production-priority-value]").input_value() == "37"
            project_row.locator("[data-production-priority-value]").fill("81")
            project_row.get_by_role("button", name="設定適用").click()
            page.wait_for_function(
                """() => {
                  const row = document.querySelector('#vehicleProductionTable [data-production-project-row]');
                  return row?.querySelector('[data-production-priority-value]')?.value === '81';
                }""",
                timeout=10000,
            )

            assert page.locator("#laneTable").is_visible()
            lane_headers = page.locator("#laneTable th").all_inner_texts()
            for required in ("要求容量", "優先度", "実効容量", "使用", "待ち需要", "状態"):
                assert required in lane_headers, f"lane decision surface lacks {required}"
            demand_headers = page.locator("#demandTable th").all_inner_texts()
            for required in ("発生元", "資源", "要求", "輸送系内", "未充足"):
                assert any(required in header for header in demand_headers), (
                    f"demand decision surface lacks {required}"
                )
            fleet_headers = page.locator("#vehicleTable th").all_inner_texts()
            for required in ("所在地", "総数", "free", "Transport", "Exploration", "relocating", "releasing"):
                assert required in fleet_headers, f"fleet decision surface lacks {required}"
            allocation_headers = page.locator("#allocationTable th").all_inner_texts()
            for required in (
                "control / target",
                "active / required",
                "Nominal F/R",
                "Available F/R",
                "Used F/R",
                "Spare F/R",
                "blocker",
            ):
                assert required in allocation_headers, f"transport allocation decision surface lacks {required}"

            page.get_by_role("button", name="Allocationを作成").click()
            page.locator("#allocationDialog").wait_for(state="visible", timeout=10000)
            page.locator("#allocationSource").select_option(str(ids.LEO))
            page.locator("#allocationDestination").select_option(str(ids.LUNAR_ORBIT))
            page.wait_for_function(
                f"""() => [...document.querySelectorAll('[data-allocation-option]')]
                    .some((button) => button.dataset.allocationOption === '{ids.REUSABLE_ORBITAL_CARGO_TUG}'
                        && button.dataset.allocationOptionPolicy === 'fastest')""",
                timeout=10000,
            )
            option_surface = page.locator("#allocationServiceOptions").inner_text()
            for required in ("Transport Service候補", "往路", "復路 / 回収", "Nominal F/R", "Cycle / latency", "Fleet", "Infrastructure", "Full-use Resource"):
                assert required in option_surface, f"allocation candidate surface lacks {required}"
            page.locator(
                f'[data-allocation-option="{ids.REUSABLE_ORBITAL_CARGO_TUG}"]'
                '[data-allocation-option-policy="fastest"]'
            ).click()
            assert page.locator("#allocationVehicle").input_value() == str(ids.REUSABLE_ORBITAL_CARGO_TUG)
            assert page.locator("#allocationPolicy").input_value() == "fastest"
            # Candidate selection itself is the UI contract under test. Do not create an
            # allocation here: later relocation checks intentionally exercise the same
            # free Fleet pool, so mutating it would make these scenarios order-dependent.
            page.locator("#allocationCancelButton").click()
            page.locator("#allocationDialog").wait_for(state="hidden", timeout=10000)

            tug_relocate = page.locator(
                f'button[data-fleet-relocate="{ids.REUSABLE_ORBITAL_CARGO_TUG}"]'
                f'[data-fleet-source="{ids.LEO}"]'
            )
            tug_relocate.wait_for(timeout=10000)
            tug_relocate.click()
            page.locator("#relocationDialog").wait_for(state="visible", timeout=10000)
            with page.expect_response(
                lambda response: (
                    "/api/v1/logistics/fleet-relocation-preview?" in response.url
                    and f"destination_id={ids.LUNAR_ORBIT}" in response.url
                ),
                timeout=10000,
            ) as relocation_response:
                page.locator("#relocationDestination").select_option(str(ids.LUNAR_ORBIT))
            assert relocation_response.value.ok, "relocation preview request failed"
            page.wait_for_function(
                """() => {
                    const root = document.querySelector('#relocationPreview');
                    const text = root?.innerText || '';
                    return root?.querySelector('.badge.ok')?.textContent === '実行可能'
                        && ['経路', '所要', 'Infrastructure', '必要Resource'].every((row) => text.includes(row));
                }""",
                timeout=10000,
            )
            relocation_text = page.locator("#relocationPreview").inner_text()
            for required in ("経路", "所要", "Infrastructure", "必要Resource"):
                assert required in relocation_text, f"relocation decision surface lacks {required}"
            assert page.locator("#relocationSubmitButton").is_enabled()
            refresh_state = page.evaluate(
                """() => {
                    document.dispatchEvent(new CustomEvent('spaceidle:snapshot'));
                    return {
                        text: document.querySelector('#relocationPreview')?.innerText || '',
                        disabled: Boolean(document.querySelector('#relocationSubmitButton')?.disabled),
                    };
                }"""
            )
            assert not refresh_state["disabled"], "background snapshot disabled a valid relocation action"
            for required in ("経路", "所要", "Infrastructure", "必要Resource"):
                assert required in refresh_state["text"], f"background snapshot hid relocation {required}"
            page.locator("#relocationCancelButton").click()
            page.locator("#relocationDialog").wait_for(state="hidden", timeout=10000)

            page.get_by_role("button", name="Laneを作成").click()
            page.locator("#laneDialog").wait_for(state="visible", timeout=10000)
            assert page.locator("#laneDialog #cargoResource").count() == 0
            options = page.locator("#laneSource option").evaluate_all("rows => rows.map(x => x.value)")
            assert len(options) >= 2
            page.locator("#laneSource").select_option(options[0])
            page.locator("#laneDestination").select_option(options[1])
            page.locator("#laneCapacity").fill("2")
            page.locator("#lanePriority").fill("70")
            page.get_by_role("button", name="Lane作成").click()
            page.locator("#laneDialog").wait_for(state="hidden", timeout=10000)
            lane_rows = page.locator("#laneTable tbody tr").filter(
                has=page.locator("button[data-lane-edit]")
            )
            lane_rows.first.wait_for(timeout=10000)
            row = lane_rows.first
            assert "2 t/日" in row.inner_text()
            assert "70" in row.inner_text()

            row.get_by_role("button", name="設定").click()
            page.locator("#laneDialog").wait_for(state="visible", timeout=10000)
            assert page.locator("#laneSource").is_disabled()
            assert page.locator("#laneDestination").is_disabled()
            assert page.locator("#lanePolicy").is_enabled()
            page.locator("#laneCapacity").fill("3")
            page.locator("#lanePriority").fill("85")
            page.locator("#lanePolicy").select_option("lowest_propellant")
            page.get_by_role("button", name="設定を更新").click()
            page.locator("#laneDialog").wait_for(state="hidden", timeout=10000)
            page.wait_for_function(
                "() => document.querySelector('#laneTable tbody button[data-lane-edit]')?.closest('tr')?.innerText.includes('3 t/日')",
                timeout=10000,
            )
            row = lane_rows.first
            text = row.inner_text()
            assert "3 t/日" in text
            assert "85" in text
            assert "lowest_propellant" in text

            row.get_by_role("button", name="停止").click()
            page.wait_for_function(
                "() => document.querySelector('#laneTable tbody button[data-lane-edit]')?.closest('tr')?.innerText.includes('停止')",
                timeout=10000,
            )
            row = lane_rows.first
            row.get_by_role("button", name="再開").click()
            page.wait_for_function(
                "() => document.querySelector('#laneTable tbody button[data-lane-toggle]')?.textContent === '停止'",
                timeout=10000,
            )
            row = lane_rows.first
            assert row.locator(".badge").inner_text() == "阻害"
            assert "External Service Policy未許可" in row.inner_text()

            lane_rows.first.get_by_role("button", name="削除").click()
            page.wait_for_function(
                "() => document.querySelectorAll('#laneTable tbody button[data-lane-edit]').length === 0",
                timeout=10000,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    run_ci_suite_or_standalone(__file__, run)
