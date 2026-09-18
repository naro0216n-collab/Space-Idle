from __future__ import annotations

from e2e_support import isolated_browser_context, monitored_page, wait_for_server

import json
import os
from pathlib import Path
from threading import Thread
import tempfile

from space_idle import GetSurfaceMap, build_game_application
from space_idle.bootstrap import build_game_application_for_load
from space_idle.api import ApiServerConfig, GameRuntime, create_server
from space_idle.content import base_ids as ids
from space_idle.simulation import OfflineProgressPolicy


SUPPORTED_BROWSERS = {"chromium", "webkit"}

def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _visible_button_min_height(page) -> float:
    return page.evaluate(
        """() => Math.min(...Array.from(document.querySelectorAll('button'))
          .filter(b => { const r=b.getBoundingClientRect(); const s=getComputedStyle(b); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; })
          .map(b => b.getBoundingClientRect().height))"""
    )


def run() -> dict[str, object]:
    browser_name = os.environ.get("SPACE_IDLE_BROWSER", "chromium").strip().lower()
    if browser_name not in SUPPORTED_BROWSERS:
        raise ValueError(f"unsupported browser {browser_name!r}; expected one of {sorted(SUPPORTED_BROWSERS)}")

    temp_dir = tempfile.TemporaryDirectory(prefix="space-idle-e2e-")
    runtime = GameRuntime(
        new_game_factory=build_game_application,
        load_factory=build_game_application_for_load,
        save_dir=Path(temp_dir.name) / "saves",
        offline_policy=OfflineProgressPolicy(real_seconds_per_game_day=0.5),
    )
    # The browser test is about the upgrade decision surface and command path,
    # not about replaying the research progression. Prepare whichever initial
    # facility currently has a content-defined next upgrade by satisfying that
    # recipe's prerequisite technologies. No balance value or technology ID is
    # hard-coded into the acceptance fixture.
    fixture_sim = runtime._app._simulation
    upgrade_fixture = next(
        (
            (facility, recipe)
            for facility in sorted(fixture_sim.facilities.facilities.values(), key=lambda row: str(row.id))
            if (recipe := fixture_sim.projects.next_upgrade_recipe(facility.id)) is not None
        ),
        None,
    )
    if upgrade_fixture is None:
        raise AssertionError("base game must expose at least one facility upgrade for browser acceptance")
    _fixture_facility, fixture_recipe = upgrade_fixture
    fixture_sim.technology.completed.update(fixture_recipe.prerequisite_technologies)

    # Keep the browser smoke focused on the player-facing site-selection and
    # Founding command path rather than encoding Survey balance timing. Satisfy
    # the current recipe's knowledge contract, then select the option projected
    # by the Application instead of preserving a historical UI selector tuple.
    founding_fixture_cell = ids.MOON_CELL_FARSIDE_HIGHLANDS
    founding_recipe = fixture_sim.founding.deployment_recipes[
        ids.ROBOTIC_LUNAR_OUTPOST_FOUNDING_PACKAGE
    ]
    for requirement in founding_recipe.knowledge_requirements:
        target = fixture_sim.survey.targets[(
            founding_fixture_cell, requirement.subject_resource_id
        )]
        fixture_sim.survey.knowledge_progress[(target.cell_id, target.resource_id)] = (
            target.thresholds[int(requirement.minimum_level) - 1]
        )
    founding_cell_projection = next(
        cell
        for cell in runtime._app.query(GetSurfaceMap(str(ids.MOON))).cells
        if cell.id == str(founding_fixture_cell)
    )
    founding_fixture_option = next(
        option
        for option in sorted(
            founding_cell_projection.foundation_options,
            key=lambda row: (
                row.staging_node_id, row.deployment_recipe_id, row.vehicle_definition_id
            ),
        )
        if option.can_plan
    )

    server = create_server(
        runtime,
        ApiServerConfig(host="127.0.0.1", port=0),
    )
    port = int(server.server_address[1])
    server_origin = f"http://127.0.0.1:{port}"
    server_thread = Thread(target=server.serve_forever, name="space-idle-e2e-http", daemon=True)
    server_thread.start()

    results: dict[str, object] = {}
    try:
        wait_for_server(server_origin)
        with isolated_browser_context(
            browser_name,
                viewport={"width": 1194, "height": 834},
                screen={"width": 1194, "height": 834},
                has_touch=True,
                device_scale_factor=2,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                user_agent=(
                    "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            ) as context, monitored_page(context) as page:
            page.goto(server_origin + "/", wait_until="load", timeout=30000)
            page.locator("#connectionState.is-ok").wait_for(timeout=10000)

            _assert(page.locator("#operationsView").is_visible(), "operations view should be visible by default")
            _assert(not page.locator("#logisticsView").is_visible(), "logistics view must not coexist with operations")
            _assert(page.locator(".location-button").count() > 0, "at least one spatial node must be rendered")
            viewport_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(viewport_metrics["scroll"] <= viewport_metrics["w"], "1194px landscape must not horizontally overflow")
            _assert(_visible_button_min_height(page) >= 44, "visible touch controls must be at least 44 CSS px high")

            _assert(page.locator("#timePauseButton").is_visible(), "automatic clock must expose pause control")
            _assert(page.locator('[data-time-speed="1"]').is_visible(), "1x speed control must be visible")
            _assert(page.locator('[data-time-speed="4"]').is_visible(), "4x speed control must be visible")
            _assert(page.locator('[data-time-speed="16"]').is_visible(), "16x speed control must be visible")
            _assert(page.get_by_role("button", name="+1日").count() == 0, "manual day-jump control must be removed")

            day_before = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) > d",
                arg=day_before,
                timeout=10000,
            )
            running_day = int(page.locator("#dayValue").inner_text().replace(",", ""))

            page.locator("#timePauseButton").tap()
            page.wait_for_function(
                "() => document.querySelector('#timeState').textContent.includes('停止中')",
                timeout=10000,
            )
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            paused_day = int(page.locator("#dayValue").inner_text().replace(",", ""))
            page.wait_for_timeout(1200)
            _assert(
                int(page.locator("#dayValue").inner_text().replace(",", "")) == paused_day,
                "paused automatic clock must not advance",
            )

            # Facility upgrades are ordinary construction projects. Verify the
            # decision surface and command path while the clock is paused so the
            # project cannot consume materials before we inspect it.
            page.locator('[data-tab="facilities"]').click()
            upgrade_row = page.locator(
                f'tr[data-inspect="facility"][data-id="{_fixture_facility.id}"]'
            )
            upgrade_row.wait_for(timeout=10000)
            upgrade_row.click()
            upgrade_button = page.locator('#inspectorContent [data-upgrade]').first
            _assert(upgrade_button.count() == 1, "fixture facility must expose its Application-projected upgrade action")
            _assert(upgrade_button.is_visible(), "facility inspector must show the upgrade action")
            _assert(upgrade_button.is_enabled(), "unblocked facility upgrade action must be enabled")
            _assert("必要工数" in page.locator("#inspectorContent").inner_text(), "upgrade inspector must expose construction work")
            _assert("必要資源" in page.locator("#inspectorContent").inner_text(), "upgrade inspector must expose physical resource requirements")
            _assert(page.locator("#upgradePlanPriorityInput").is_visible(), "upgrade planning must expose priority before project creation")
            _assert(page.locator("#upgradePlanProcurementTimingPolicy").is_visible(), "upgrade planning must expose procurement timing policy before project creation")
            page.locator("#upgradePlanPriorityInput").select_option("4")
            # The form is a multi-field draft. Moving focus to another control
            # must not let periodic synchronization overwrite the first edit.
            page.locator("#upgradePlanProcurementTimingPolicy").focus()
            page.wait_for_timeout(1200)
            _assert(
                page.locator("#upgradePlanPriorityInput").input_value() == "4",
                "non-focused construction planning drafts must survive periodic refresh",
            )
            page.locator("#upgradePlanProcurementTimingPolicy").select_option("immediate")
            # Unsaved planning values are client-owned drafts. A refresh with no
            # authoritative change must not silently reset them before submission.
            page.locator("#refreshButton").click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            _assert(page.locator("#upgradePlanPriorityInput").input_value() == "4", "upgrade planning priority must survive refresh")
            _assert(page.locator("#upgradePlanProcurementTimingPolicy").input_value() == "immediate", "upgrade procurement timing policy must survive refresh")
            upgrade_button = page.locator('#inspectorContent [data-upgrade]').first
            upgrade_button.click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator('[data-tab="construction"]').click()
            upgrade_rows = page.locator('tr[data-inspect="project"]', has_text="Upgrade")
            _assert(upgrade_rows.count() > 0, "upgrade command must create a construction project visible in the project list")
            upgrade_rows.first.click()
            inspector_text = page.locator("#inspectorContent").inner_text()
            _assert("Facility Upgrade" in inspector_text, "project inspector must retain typed upgrade target information")
            _assert(page.locator("#projectPriorityInput").input_value() == "4", "project inspector must retain the planned priority")
            _assert(page.locator("#projectProcurementTimingPolicy").input_value() == "immediate", "project inspector must retain the planned procurement timing policy")
            _assert(
                page.locator('#inspectorContent [data-project-routing-constraint]').count() > 0,
                "project Supply Requirements must expose Routing Constraint actions at the decision point",
            )
            _assert(page.locator("#projectPriorityInput").is_enabled(), "mutable project priority must stay visible and enabled")
            _assert(page.locator("#projectProcurementTimingPolicy").is_enabled(), "mutable procurement timing policy must stay visible and enabled")
            page.locator("#projectPriorityInput").select_option("5")
            page.locator('[data-set-project-priority]').click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            _assert(page.locator("#projectPriorityInput").input_value() == "5", "project priority command must round-trip through the UI")
            cancel_upgrade = page.locator('#inspectorContent [data-command="CancelBuild"]')
            _assert(cancel_upgrade.is_enabled(), "planned upgrade project must use ordinary construction cancellation")
            cancel_upgrade.click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-tab="research"]').click()
            research_rows = page.locator('#researchTree [data-inspect="research"]')
            _assert(research_rows.count() > 0, "research tree must expose research decisions")
            startable_research = None
            for index in range(research_rows.count()):
                research_rows.nth(index).click()
                control = page.locator('#inspectorContent [data-lifecycle-control="research"]')
                if (
                    control.count() == 1
                    and control.get_attribute('data-research-action') == 'start'
                    and control.is_enabled()
                ):
                    startable_research = control
                    break
            _assert(startable_research is not None, "at least one projected Research decision must be startable")
            page.locator('#researchPriorityInput').select_option('4')
            startable_research.click()
            research_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="research"]')
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=research]')?.dataset.researchAction === 'pause'",
                timeout=10000,
            )
            research_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=research]')?.dataset.researchAction === 'resume'",
                timeout=10000,
            )
            research_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=research]')?.dataset.researchAction === 'pause'",
                timeout=10000,
            )
            research_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=research]')?.dataset.researchAction === 'resume'",
                timeout=10000,
            )
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-tab="scientific-exploration"]').click()
            exploration_rows = page.locator('tr[data-inspect="scientific-exploration"]')
            _assert(exploration_rows.count() > 0, "scientific exploration campaign must be visible")
            exploration_rows.first.click()
            exploration_text = page.locator("#inspectorContent").inner_text()
            _assert("Campaign所要期間" in exploration_text, "exploration inspector must expose activity duration separately from Movement latency")
            _assert("Minimum Payload" in exploration_text, "exploration inspector must expose minimum payload requirement")
            _assert("Vehicle Capability" in exploration_text, "exploration inspector must expose generic vehicle capability requirements")
            _assert("RP/日" in exploration_text, "exploration inspector must expose application-projected RP rate")
            _assert("空間条件: 軌道地点が必要" in exploration_text, "exploration inspector must expose spatial classification requirements")
            _assert("Operation:" in exploration_text, "exploration inspector must expose required operations")
            _assert("消耗資源:" in exploration_text, "exploration inspector must expose consumable resources")
            exploration_assign_buttons = page.locator('#inspectorContent [data-exploration-assign]')
            _assert(exploration_assign_buttons.count() > 0, "exploration inspector must keep vehicle assignment controls visible before campaign start")
            _assert(all(not exploration_assign_buttons.nth(i).is_enabled() for i in range(exploration_assign_buttons.count())), "vehicle assignment must remain disabled until the campaign exists")
            exploration_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="exploration"]')
            _assert(exploration_lifecycle.count() == 1, "exploration must expose one lifecycle control")
            _assert(exploration_lifecycle.get_attribute('data-exploration-action') == 'start' and exploration_lifecycle.is_enabled(), "campaign lifecycle control must expose start when startable")
            page.locator('#explorationPriorityInput').select_option('4')
            exploration_lifecycle.click()
            assignable_fleet = page.locator('#inspectorContent [data-exploration-assign]:not([disabled])').first
            assignable_fleet.wait_for(timeout=10000)
            _assert(assignable_fleet.count() == 1, "started exploration must expose an assignable Fleet option when projected")
            assignable_fleet.click()
            page.locator('#inspectorContent [data-exploration-unassign]').wait_for(timeout=10000)
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=exploration]')?.dataset.explorationAction === 'pause'",
                timeout=10000,
            )
            exploration_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="exploration"]')
            exploration_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=exploration]')?.dataset.explorationAction === 'resume'",
                timeout=10000,
            )
            exploration_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=exploration]')?.dataset.explorationAction === 'pause'",
                timeout=10000,
            )
            exploration_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=exploration]')?.dataset.explorationAction === 'resume'",
                timeout=10000,
            )
            page.locator('[data-tab="overview"]').click()

            page.locator(f'[data-location-id="{ids.EARTH}"]').click()
            page.locator('[data-tab="survey"]').click()
            known_survey = page.locator('tr[data-inspect="survey"]').first
            known_survey.wait_for(timeout=10000)
            _assert("Knowledge" in known_survey.inner_text(), "raw Survey Knowledge must be presented independently from Campaign lifecycle")
            known_survey.click()
            _assert("Knowledge State" in page.locator("#inspectorContent").inner_text(), "Survey target inspector must expose raw Knowledge state")
            _assert(page.locator('#inspectorContent [data-lifecycle-control="survey"]').count() == 0, "fine-grained Knowledge must not expose a per-target Campaign lifecycle")

            page.locator('[data-tab="surface"]').click()
            surface_cells = page.locator('.surface-cell-button')
            surface_cells.first.wait_for(timeout=10000)
            _assert(surface_cells.count() > 0, "surface map must render Application-projected body cells")
            _assert("base.cell." not in surface_cells.first.inner_text(), "surface map must present labels rather than internal cell ids")
            surface_decision_found = False
            for index in range(surface_cells.count()):
                surface_cells.nth(index).click()
                if (
                    page.locator('#inspectorContent [data-surface-develop]').count() > 0
                    and "Location設立" in page.locator("#inspectorContent").inner_text()
                ):
                    surface_decision_found = True
                    break
            _assert(surface_decision_found, "surface map must expose a projected development/founding decision")
            surface_inspector = page.locator("#inspectorContent").inner_text()
            _assert("Cell状態" in surface_inspector, "surface cell inspector must expose physical cell state")
            _assert("Current Environment" in surface_inspector, "surface cell inspector must expose application-projected current environment")
            _assert("Resource Knowledge" in surface_inspector, "surface cell inspector must expose survey-derived resource knowledge")
            _assert(page.locator('#inspectorContent [data-inspect="survey"]').count() > 0, "surface map resource decisions must link directly to survey controls")
            _assert("既存Locationから開発" in surface_inspector, "undeveloped cell must expose location development options in-place")
            _assert("Location設立" in surface_inspector, "unowned cell must expose founding options in-place")
            _assert(page.locator('#inspectorContent [data-surface-develop]').count() > 0, "surface cell inspector must expose application-projected development commands")
            page.locator('[data-tab="overview"]').click()
            overview_text = page.locator('#operationsTabContent').inner_text()
            _assert("Surface Infrastructure" in overview_text, "location overview must expose aggregate surface infrastructure state")
            _assert("Resource Opportunity / Extraction" in overview_text, "location overview must expose aggregate extraction decision state")
            _assert("Current Environment" in overview_text, "location overview must expose current environment state")

            page.locator(f'[data-location-id="{ids.LUNAR_ORBIT}"]').click()
            page.locator('[data-tab="survey"]').click()
            survey_rows = page.locator('tr[data-inspect="survey"]')
            _assert(survey_rows.count() > 0, "Survey UI must expose at least one Application-projected target")
            campaign_cell_id = campaign_resource_id = None
            for row_index in range(survey_rows.count()):
                survey_pair_id = survey_rows.nth(row_index).get_attribute("data-id")
                if survey_pair_id is None or "::" not in survey_pair_id:
                    continue
                candidate_cell_id, candidate_resource_id = survey_pair_id.split("::", 1)
                cell_checkbox = page.locator(
                    f'[data-survey-draft-cell][value="{candidate_cell_id}"]'
                )
                resource_checkbox = page.locator(
                    f'[data-survey-draft-resource][value="{candidate_resource_id}"]'
                )
                if cell_checkbox.count() == 0 or resource_checkbox.count() == 0:
                    continue
                cell_checkbox.check()
                resource_checkbox.check()
                for goal in ("1", "2", "3"):
                    page.locator('#surveyDraftGoal').select_option(goal)
                    page.wait_for_function(
                        "() => !document.querySelector('[data-survey-start-intent-status]')?.textContent?.includes('可否確認中')",
                        timeout=10000,
                    )
                    if page.locator('[data-start-survey-campaign]').is_enabled():
                        campaign_cell_id = candidate_cell_id
                        campaign_resource_id = candidate_resource_id
                        break
                if campaign_cell_id is not None:
                    break
                cell_checkbox.uncheck()
                resource_checkbox.uncheck()
            _assert(
                campaign_cell_id is not None and campaign_resource_id is not None,
                "Survey Campaign UI must expose at least one Application-approved scope / goal intent",
            )
            _assert(
                page.locator('[data-survey-start-intent-status]').inner_text().strip() == "適用可能",
                "Survey Campaign creation availability must come from Application preview",
            )
            page.locator('#surveyDraftPriority').select_option("4")
            page.locator('[data-start-survey-campaign]').click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            campaign_row = page.locator('tr[data-inspect="survey-campaign"]').first
            campaign_row.wait_for(timeout=10000)
            _assert("1 Cell × 1 Resource" in campaign_row.inner_text(), "Survey Campaign creation must round-trip the selected UI scope")
            _assert("base." not in campaign_row.inner_text(), "Survey Campaign row must use presentation labels rather than raw definition ids")
            campaign_row.click()
            campaign_text = page.locator('#inspectorContent').inner_text()
            _assert("Scope / Goal編集" in campaign_text, "Survey Campaign inspector must expose the selected scope and goal")
            _assert("Provider / Mode候補差" in campaign_text, "Survey Campaign inspector must expose candidate differences at the decision point")
            _assert("Projected Provider / Mode" in campaign_text, "Survey Campaign inspector must expose the auto-resolved operational choice")
            _assert(page.locator('#inspectorContent [data-set-survey-priority]').is_enabled(), "active Survey Campaign must expose priority control")
            page.wait_for_function(
                "() => !document.querySelector('[data-survey-update-intent-status]')?.textContent?.includes('可否確認中')",
                timeout=10000,
            )
            _assert(
                page.locator('[data-update-survey-campaign]').is_enabled(),
                "Survey Campaign edit availability must come from Application preview",
            )
            _assert(int(page.locator('#surveyPriorityInput').input_value()) == 4, "Survey Campaign start priority must round-trip through the UI")
            survey_lifecycle = page.locator('#inspectorContent [data-lifecycle-control="survey-campaign"]')
            _assert(survey_lifecycle.get_attribute('data-survey-campaign-action') == 'pause' and survey_lifecycle.is_enabled(), "active Survey Campaign must expose pause on the stable lifecycle control")
            page.locator('#surveyPriorityInput').select_option('5')
            page.locator('#inspectorContent [data-set-survey-priority]').click()
            page.wait_for_function(
                "() => document.querySelector('#surveyPriorityInput')?.value === '5'", timeout=10000
            )
            survey_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=survey-campaign]')?.dataset.surveyCampaignAction === 'resume'",
                timeout=10000,
            )
            survey_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=survey-campaign]')?.dataset.surveyCampaignAction === 'pause'",
                timeout=10000,
            )
            survey_lifecycle.click()
            page.wait_for_function(
                "() => document.querySelector('[data-lifecycle-control=survey-campaign]')?.dataset.surveyCampaignAction === 'resume'",
                timeout=10000,
            )

            # A surveyed Cell must become a player-selectable founding site; the
            # UI must use the Application-projected option rather than inventing
            # a fixed pre-existing lunar Location.
            page.locator('[data-tab="surface"]').click()
            founding_cell = page.locator(f'.surface-cell-button[data-id="{founding_fixture_cell}"]')
            founding_cell.wait_for(timeout=10000)
            founding_cell.click()
            founding_button = page.locator(
                '#inspectorContent [data-surface-found]'
                f'[data-staging-node-id="{founding_fixture_option.staging_node_id}"]'
                f'[data-recipe-id="{founding_fixture_option.deployment_recipe_id}"]'
                f'[data-vehicle-id="{founding_fixture_option.vehicle_definition_id}"]'
            )
            _assert(founding_button.count() == 1, "surveyed lunar cell must expose the canonical Founding option")
            _assert(founding_button.is_enabled(), "surveyed lunar cell must allow player-selected Founding when planning requirements are met")
            founding_card = founding_button.locator('xpath=ancestor::*[contains(@class,"surface-action-card")][1]')
            _assert("Staging必要Resource" in founding_card.inner_text(), "Founding decision surface must expose staging resources before commitment")
            _assert(
                founding_card.locator('.surface-resource-list .cell-sub').count() > 0,
                "Founding decision surface must present its Application-projected staging resources",
            )
            founding_card.locator('[data-new-location-name]').fill("Browser Lunar Outpost")
            founding_button.click()
            page.wait_for_function("() => !document.body.classList.contains('is-busy')", timeout=10000)
            _assert("案件進行中" in page.locator('#inspectorContent').inner_text(), "Founding command must round-trip to an active project on the selected cell")
            _assert(founding_button.count() == 1, "Founding control must remain in the same place after project start")
            _assert(not founding_button.is_enabled(), "active Founding must keep the same action visible but unavailable")
            page.locator('[data-tab="overview"]').click()

            page.locator('[data-time-speed="4"]').click()
            page.wait_for_function(
                "() => !document.body.classList.contains('is-busy')",
                timeout=10000,
            )
            page.locator("#timePauseButton").click()
            page.wait_for_function(
                "d => Number(document.querySelector('#dayValue').textContent.replaceAll(',','')) > d",
                arg=paused_day,
                timeout=10000,
            )
            rev_after = int(page.locator("#revisionValue").inner_text())

            page.set_viewport_size({"width": 1180, "height": 820})
            page.wait_for_timeout(100)
            standard_ipad_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(
                standard_ipad_metrics["scroll"] <= standard_ipad_metrics["w"],
                "1180px full-size iPad landscape must not horizontally overflow",
            )

            page.get_by_role("button", name="物流ネットワーク").click()
            standard_logistics_metrics = page.evaluate("() => ({w: innerWidth, scroll: document.documentElement.scrollWidth})")
            _assert(
                standard_logistics_metrics["scroll"] <= standard_logistics_metrics["w"],
                "1180px full-size iPad logistics must not horizontally overflow",
            )
            page.set_viewport_size({"width": 1194, "height": 834})
            page.wait_for_timeout(100)
            _assert(page.locator("#logisticsView").is_visible(), "logistics view should be visible after switch")
            _assert(not page.locator("#operationsView").is_visible(), "operations view must be hidden after switch")
            movement_plan_buttons = page.locator(".movement-plan-button")
            _assert(movement_plan_buttons.count() > 0, "at least one movement plan must be rendered")
            blocked = page.locator(".movement-plan-button", has=page.locator(".badge", has_text="未解禁"))
            (blocked.first if blocked.count() else movement_plan_buttons.first).click()
            page.locator("#movementPlanInspectorContent .detail-card").first.wait_for(timeout=10000)
            _assert(
                page.locator("#movementPlanInspectorTitle").inner_text() != "Movement Planを選択",
                "movement plan inspector should show selected plan",
            )
            _assert(
                page.locator("#movementPlanInspectorContent .detail-card").count() > 0,
                "selected movement plan should expose transport modes",
            )
            issue_titles = page.locator("#movementPlanInspectorContent .issue-title").all_inner_texts()
            _assert(all("base.tech." not in text for text in issue_titles), "technology IDs must not leak into blocker titles")
            _assert(all("technology:" not in text for text in issue_titles), "raw blocker prefixes must not leak into blocker titles")

            page.get_by_role("button", name="拠点運用").click()
            page.set_viewport_size({"width": 834, "height": 1194})
            page.wait_for_timeout(100)
            portrait = page.evaluate(
                """() => {
                  const view=document.querySelector('#operationsView');
                  const children=Array.from(view.children).map(x=>x.getBoundingClientRect());
                  return {
                    innerWidth,
                    scrollWidth: document.documentElement.scrollWidth,
                    display: getComputedStyle(view).display,
                    left0: children[0]?.left,
                    left1: children[1]?.left,
                    left2: children[2]?.left,
                    bodyText: document.body.innerText,
                  };
                }"""
            )
            _assert(portrait["scrollWidth"] >= 1180, "portrait must retain the landscape design width")
            _assert(portrait["display"] == "grid", "portrait must not switch to a stacked alternate layout")
            _assert(
                portrait["left0"] < portrait["left1"] < portrait["left2"],
                "portrait must preserve left/workspace/inspector order",
            )
            _assert("非対応" not in portrait["bodyText"], "portrait must not replace the UI with an unsupported notice")

            page.get_by_role("button", name="物流ネットワーク").click()
            portrait_logistics = page.evaluate(
                """() => {
                  const view=document.querySelector('#logisticsView');
                  const children=Array.from(view.children).map(x=>x.getBoundingClientRect());
                  return {
                    scrollWidth: document.documentElement.scrollWidth,
                    display: getComputedStyle(view).display,
                    left0: children[0]?.left, left1: children[1]?.left, left2: children[2]?.left
                  };
                }"""
            )
            _assert(
                portrait_logistics["scrollWidth"] >= 1180,
                "portrait logistics must retain the landscape design width",
            )
            _assert(
                portrait_logistics["display"] == "grid",
                "portrait logistics must not switch to a stacked layout",
            )
            _assert(
                portrait_logistics["left0"] < portrait_logistics["left1"] < portrait_logistics["left2"],
                "portrait logistics must preserve movement-plan/network/inspector order",
            )
            network_locations = page.locator("#networkNodes [data-network-location]")
            expected_network_locations = page.locator("#movementPlanOriginFilter option").count() - 1
            _assert(
                network_locations.count() == expected_network_locations,
                "network must render every location exposed by the Application view",
            )
            network_positions = network_locations.evaluate_all(
                "rows => rows.map(row => { const node=row.closest('.network-node'); return `${node.style.left}:${node.style.top}`; })"
            )
            _assert(
                len(set(network_positions)) == len(network_positions),
                "network layout must give each rendered location a distinct position",
            )

            results = {
                "browser": browser_name,
                "server": "in_process_http",
                "device_scale_factor": 2,
                "facility_upgrade_ui": True,
                "landscape_viewport": viewport_metrics,
                "standard_ipad_landscape": standard_ipad_metrics,
                "standard_ipad_logistics": standard_logistics_metrics,
                "portrait_scroll_width": portrait["scrollWidth"],
                "portrait_logistics_scroll_width": portrait_logistics["scrollWidth"],
                "movement_plan_count": movement_plan_buttons.count(),
                "issue_titles_checked": len(issue_titles),
                "day_before": day_before,
                "day_running": running_day,
                "day_after": int(page.locator("#dayValue").inner_text().replace(",", "")),
                "revision_after": rev_after,
            }

        return results
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        temp_dir.cleanup()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
