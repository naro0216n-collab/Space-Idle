(() => {
  'use strict';

  const state = {
    revision: null,
    session: null,
    world: null,
    catalog: null,
    locationId: null,
    location: null,
    flow: null,
    bottlenecks: null,
    projects: null,
    buildOptions: null,
    research: null,
    surveys: null,
    contracts: null,
    logisticsSummary: null,
    routes: null,
    routeDetail: null,
    vehicles: null,
    orders: null,
    missions: null,
    selectedRouteId: null,
    activeView: 'operations',
    activeTab: 'overview',
    inspector: null,
    busy: false,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const fmt = (v, digits = 1) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ja-JP', {maximumFractionDigits: digits}) : '—';
  const pct = (v) => Number.isFinite(Number(v)) ? `${Math.round(Number(v) * 100)}%` : '—';
  const byId = (items = []) => Object.fromEntries(items.map((x) => [x.id, x]));
  const resourceMap = () => byId(state.catalog?.resources || []);
  const locationMap = () => byId(state.world?.locations || []);
  const definitionMaps = () => [
    state.catalog?.resources, state.catalog?.facilities, state.catalog?.vehicles,
    state.catalog?.locations, state.catalog?.processes, state.catalog?.research,
    state.catalog?.routes, state.catalog?.transport_services,
  ].filter(Boolean).map(byId);
  const locationName = (id) => locationMap()[id]?.display_name || definitionName(id);
  const resourceName = (id) => resourceMap()[id]?.display_name || definitionName(id);
  const definitionName = (id) => {
    if (!id) return '—';
    for (const map of definitionMaps()) {
      const item = map[id];
      if (item?.display_name) return item.display_name;
    }
    return id;
  };
  const capabilityLabels = {
    base_construction: '基礎建設', basic_machine_shop: '基礎機械加工', bulk_storage: 'バルク保管',
    cargo_storage: '一般貨物保管', cargo_transfer: '貨物移送', construction_yard: '建設ヤード',
    cryogenic_storage: '極低温保管', grid_power: '外部電力網', heavy_equipment_assembly: '重機組立',
    industrial_electrolysis: '工業電解', industrial_power: '産業電力', launch_operations: '打上げ運用',
    launch_vehicle_servicing: '打上げ機整備', metallurgy: '金属精錬', ore_processing: '鉱石処理',
    power_grid: '電力網', propellant_production: '推進剤製造', regolith_excavation: 'レゴリス採掘',
    research_lab: '研究設備', robotic_operations: 'ロボット運用', sintering: '焼結',
    spacecraft_servicing: '宇宙船整備', structural_fabrication: '構造材加工', surface_survey: '地表探査',
    vehicle_assembly: '輸送機組立', vehicle_refueling: '輸送機補給', water_extraction: '水抽出', water_storage: '水保管',
  };
  const operationLabels = {powered_ascent:'動力離昇', launch:'打上げ', spaceflight:'宇宙航行', landing:'着陸', atmospheric_entry:'大気圏突入'};
  const locationKindLabels = {surface:'地表', orbital:'軌道', orbit:'軌道'};
  const storageClassLabels = {bulk:'バルク', cryogenic:'極低温', general_cargo:'一般貨物', liquid:'液体'};
  const stateLabels = {available:'利用可能', active:'稼働', paused:'停止', locked:'未解禁', complete:'完了', offered:'提示中', accepted:'受諾済み', declined:'辞退', waiting:'待機', in_transit:'輸送中', arrival_waiting:'到着待機'};
  const capabilityName = (id) => capabilityLabels[id] || id || '—';
  const operationName = (id) => operationLabels[id] || id || '—';
  function userFacingText(value) {
    let text = String(value ?? '');
    for (const map of definitionMaps()) {
      for (const [id, item] of Object.entries(map)) {
        if (text.includes(id) && item?.display_name) text = text.split(id).join(item.display_name);
      }
    }
    text = text.replace(/technology:([^;]+)/g, (_, ids) => `技術不足: ${ids.split(',').map((x) => definitionName(x.trim())).join('、')}`);
    text = text.replace(/capability:([a-zA-Z0-9_.-]+)/g, (_, id) => `能力不足: ${capabilityName(id)}`);
    text = text.replace(/(available|active|infrastructure):([a-zA-Z0-9_.-]+):([0-9.+-]+)\/([0-9.+-]+)/g, (_, kind, id, current, required) => {
      const label = kind === 'available' ? '利用可能能力' : kind === 'active' ? '稼働能力' : 'インフラ能力';
      return `${label}不足: ${capabilityName(id)} ${current} / ${required}`;
    });
    return text;
  }

  function banner(message, kind = 'info', timeout = 4200) {
    const el = $('#statusBanner');
    el.textContent = message;
    el.className = `status-banner${kind === 'error' ? ' error' : ''}`;
    el.hidden = false;
    clearTimeout(banner.timer);
    if (timeout) banner.timer = setTimeout(() => { el.hidden = true; }, timeout);
  }

  function setConnection(kind, text) {
    const el = $('#connectionState');
    el.className = `connection-state ${kind === 'ok' ? 'is-ok' : kind === 'error' ? 'is-error' : ''}`;
    el.lastElementChild.textContent = text;
  }

  async function api(path, options = {}) {
    const headers = {'Accept': 'application/json', ...(options.headers || {})};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, {...options, headers, cache: 'no-store'});
    let payload = null;
    if (response.status !== 304) {
      const text = await response.text();
      payload = text ? JSON.parse(text) : null;
    }
    const rev = response.headers.get('X-Space-Idle-Revision');
    if (rev !== null) state.revision = Number(rev);
    if (!response.ok) {
      const err = new Error(payload?.error?.message || `${response.status} ${response.statusText}`);
      err.code = payload?.error?.code;
      err.status = response.status;
      err.details = payload?.error?.details;
      throw err;
    }
    if (payload?.revision !== undefined) state.revision = payload.revision;
    return payload?.data ?? payload;
  }

  async function command(type, payload = {}) {
    if (state.busy) return;
    state.busy = true;
    document.body.classList.add('is-busy');
    try {
      const headers = {};
      if (state.revision !== null) headers['If-Match'] = `"rev-${state.revision}"`;
      const result = await api('/api/v1/commands', {method: 'POST', headers, body: JSON.stringify({type, payload})});
      await refreshCurrentContext();
      return result;
    } catch (err) {
      if (err.code === 'revision_conflict') {
        banner('別の操作で状態が更新されました。最新状態を再取得しました。', 'error');
        await loadSessionAndWorld();
        await refreshCurrentContext();
      } else {
        banner(err.message || '操作に失敗しました', 'error', 7000);
      }
      throw err;
    } finally {
      state.busy = false;
      document.body.classList.remove('is-busy');
    }
  }

  async function loadSessionAndWorld() {
    const [session, world] = await Promise.all([api('/api/v1/session'), api('/api/v1/world')]);
    state.session = session;
    state.world = world;
    state.revision = session.revision ?? state.revision;
    if (!state.locationId || !world.locations.some((x) => x.id === state.locationId)) {
      state.locationId = world.locations[0]?.id ?? null;
    }
    renderHeader();
    renderLocations();
  }

  async function initialLoad() {
    setConnection('pending', '接続中');
    const [catalog] = await Promise.all([api('/api/v1/catalog'), loadSessionAndWorld()]);
    state.catalog = catalog;
    populateStaticSelects();
    await Promise.all([loadGlobalIssues(), loadResearch(), loadContracts(), loadLogisticsData()]);
    await loadLocation(state.locationId);
    setConnection('ok', 'PC Server');
    $('#app').setAttribute('aria-busy', 'false');
    renderAll();
  }

  async function loadLocation(locationId) {
    if (!locationId) return;
    state.locationId = locationId;
    const q = encodeURIComponent(locationId);
    const [location, flow, projects, buildOptions, bottlenecks, surveys] = await Promise.all([
      api(`/api/v1/locations/${q}`), api(`/api/v1/locations/${q}/flow`), api(`/api/v1/projects?location_id=${q}`),
      api(`/api/v1/locations/${q}/build-options`), api(`/api/v1/bottlenecks?location_id=${q}`), api(`/api/v1/surveys?location_id=${q}`),
    ]);
    Object.assign(state, {location, flow, projects, buildOptions, bottlenecks, surveys});
    state.inspector = null;
    renderLocations();
    renderOperations();
  }

  async function loadGlobalIssues() {
    state.globalIssues = await api('/api/v1/bottlenecks');
    renderGlobalIssues();
  }

  async function loadResearch() { state.research = await api('/api/v1/research'); }
  async function loadContracts() { state.contracts = await api('/api/v1/contracts'); }

  async function loadLogisticsData() {
    const [summary, routes, vehicles, orders, missions] = await Promise.all([
      api('/api/v1/logistics/summary'), api('/api/v1/logistics/routes'), api('/api/v1/logistics/vehicles'),
      api('/api/v1/logistics/orders'), api('/api/v1/logistics/missions'),
    ]);
    Object.assign(state, {logisticsSummary: summary, routes, vehicles, orders, missions});
    if (state.selectedRouteId && !routes.items.some((r) => r.id === state.selectedRouteId)) state.selectedRouteId = null;
    renderLogistics();
  }

  async function loadRouteDetail(routeId) {
    state.selectedRouteId = routeId;
    state.routeDetail = await api(`/api/v1/logistics/routes/${encodeURIComponent(routeId)}`);
    renderLogistics();
  }

  async function refreshCurrentContext() {
    await loadSessionAndWorld();
    await Promise.all([loadGlobalIssues(), loadResearch(), loadContracts(), loadLogisticsData()]);
    await loadLocation(state.locationId);
  }

  function renderHeader() {
    $('#dayValue').textContent = fmt(state.world?.day, 0);
    $('#fundsValue').textContent = `${fmt(state.world?.funds_musd, 1)} M$`;
    $('#revisionValue').textContent = state.revision ?? '—';
    $('#appVersion').textContent = `v${state.session?.app_version || '0.4.4'}`;
  }

  function renderLocations() {
    const items = state.world?.locations || [];
    $('#locationList').innerHTML = items.map((loc) => `
      <button type="button" class="location-button ${loc.id === state.locationId ? 'is-active' : ''}" data-location-id="${esc(loc.id)}">
        <span class="location-name">${esc(loc.display_name)}</span>
        <span class="location-meta"><span>${esc(locationKindLabels[loc.kind] || loc.kind)}</span><span>設備 ${loc.facility_count}</span><span>建設 ${loc.active_project_count}</span></span>
      </button>`).join('');
  }

  function renderGlobalIssues() {
    const issues = state.globalIssues?.items || [];
    const target = $('#globalIssues');
    if (!issues.length) { target.innerHTML = '<div class="empty-state">現在、全体blockerはありません。</div>'; return; }
    target.innerHTML = issues.slice(0, 8).map(issueHtml).join('') + (issues.length > 8 ? `<div class="cell-sub">ほか ${issues.length - 8} 件</div>` : '');
  }

  function issueHtml(issue) {
    const rawMessage = Array.isArray(issue) ? issue[1] : issue.message || issue.code || String(issue);
    const rawCategory = Array.isArray(issue) ? issue[0] : issue.category || issue.source || '';
    let message = userFacingText(rawMessage);
    if (rawCategory === 'technology' && definitionName(rawMessage) !== rawMessage) message = `必要技術: ${definitionName(rawMessage)}`;
    if (rawCategory === 'capability') message = `必要能力: ${capabilityName(rawMessage)}`;
    const categoryLabels = {technology:'技術条件', capability:'能力条件', environment:'環境条件', contract:'契約', logistics:'物流', construction:'建設', research:'研究', survey:'探査', storage:'保管', power:'電力'};
    const category = categoryLabels[rawCategory] || userFacingText(rawCategory);
    const context = !Array.isArray(issue) && issue.entity_id ? definitionName(issue.entity_id) : '';
    const meta = [category, context && context !== issue.entity_id ? context : ''].filter(Boolean).join(' · ');
    return `<div class="issue"><div class="issue-title">${esc(message)}</div>${meta ? `<div class="issue-meta">${esc(meta)}</div>` : ''}</div>`;
  }

  function renderOperations() {
    const loc = state.location;
    if (!loc) return;
    $('#locationTitle').textContent = loc.display_name;
    $('#locationKind').textContent = `${locationKindLabels[locationMap()[loc.id]?.kind] || locationMap()[loc.id]?.kind || '拠点'}拠点`;
    $('#headlineMetrics').innerHTML = [
      ['発電', `${fmt(loc.power_generation_mw)} MW`], ['需要', `${fmt(loc.power_demand_mw)} MW`],
      ['建設能力', `${fmt(loc.construction_capacity_per_day)} /日`], ['設備', `${loc.facilities.length}`],
    ].map(metricHtml).join('');
    $$('.tab-button').forEach((b) => b.classList.toggle('is-active', b.dataset.tab === state.activeTab));
    renderActiveTab();
    renderInspector();
  }

  function metricHtml([label, value]) { return `<div class="metric-chip"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`; }

  function renderActiveTab() {
    const renderers = {overview: renderOverviewTab, facilities: renderFacilitiesTab, inventory: renderInventoryTab, construction: renderConstructionTab, research: renderResearchTab, survey: renderSurveyTab, contracts: renderContractsTab};
    $('#operationsTabContent').innerHTML = renderers[state.activeTab]();
  }

  function renderOverviewTab() {
    const loc = state.location, flow = state.flow;
    const issues = state.bottlenecks?.items || [];
    const storageRows = (loc.storage || []).map((s) => `<tr><td>${esc(storageClassLabels[s.storage_class] || s.storage_class)}</td><td>${fmt(s.stock_t)}</td><td>${fmt(s.service_capacity_t)}</td><td>${fmt(s.free_service_t)}</td><td>${fmt(s.unserviced_occupied_t)}</td></tr>`).join('');
    const capabilityRows = (loc.capabilities || []).filter((c) => c.infrastructure_capacity || c.active_capacity || c.available_capacity).map((c) => `<tr><td>${esc(capabilityName(c.id))}</td><td>${fmt(c.infrastructure_capacity)}</td><td>${fmt(c.active_capacity)}</td><td>${fmt(c.available_capacity)}</td></tr>`).join('');
    return `<div class="card-grid">
      <section class="card"><div class="card-heading"><h3>運用状態</h3></div><div class="card-body"><div class="stat-grid">
        ${statHtml('電力利用率', pct(flow?.power_utilization))}${statHtml('利用可能電力', `${fmt(loc.power_allocated_mw)} MW`)}${statHtml('建設能力', `${fmt(loc.construction_capacity_per_day)} /日`)}${statHtml('進行中建設', `${loc.projects?.length || 0}`)}
      </div></div></section>
      <section class="card"><div class="card-heading"><h3>地点blocker</h3><span class="badge ${issues.length ? 'warn' : 'ok'}">${issues.length} 件</span></div><div class="card-body issue-stack">${issues.length ? issues.slice(0, 8).map(issueHtml).join('') : '<div class="empty-state">現在のblockerはありません。</div>'}</div></section>
      <section class="card"><div class="card-heading"><h3>保管サービス</h3></div><div class="table-wrap"><table><thead><tr><th>Class</th><th>在庫t</th><th>Service</th><th>空き</th><th>未service</th></tr></thead><tbody>${storageRows || '<tr><td colspan="5">保管設備なし</td></tr>'}</tbody></table></div></section>
      <section class="card"><div class="card-heading"><h3>能力</h3></div><div class="table-wrap"><table><thead><tr><th>能力</th><th>インフラ</th><th>稼働</th><th>利用可能</th></tr></thead><tbody>${capabilityRows || '<tr><td colspan="4">Capabilityなし</td></tr>'}</tbody></table></div></section>
    </div>`;
  }

  function statHtml(label, value) { return `<div class="stat-box"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`; }

  function renderFacilitiesTab() {
    const rows = (state.location?.facilities || []).map((f) => `<tr class="selectable" data-inspect="facility" data-id="${esc(f.id)}"><td><div class="cell-main">${esc(f.display_name)}</div><div class="cell-sub">${esc(f.id)}</div></td><td>${f.paused ? '<span class="badge warn">停止</span>' : '<span class="badge ok">稼働</span>'}</td><td>${pct(f.power_utilization)}</td><td>${f.power_priority ?? '—'}</td><td>${(f.activation_blockers || []).length}</td></tr>`).join('');
    return `<section class="card"><div class="card-heading"><h3>設備一覧</h3><span class="badge">${state.location?.facilities.length || 0}</span></div><div class="table-wrap"><table><thead><tr><th>設備</th><th>状態</th><th>電力</th><th>優先度</th><th>blocker</th></tr></thead><tbody>${rows || '<tr><td colspan="5">設備なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderInventoryTab() {
    const flowMap = Object.fromEntries((state.flow?.resources || []).map((r) => [r.resource_id, r]));
    const rows = (state.location?.inventory || []).filter((r) => r.amount || r.reserved || flowMap[r.resource_id]?.local_production_per_day || flowMap[r.resource_id]?.local_consumption_per_day || flowMap[r.resource_id]?.inbound_in_transit_t || flowMap[r.resource_id]?.arrival_waiting_t).map((r) => {
      const f = flowMap[r.resource_id] || {};
      return `<tr class="selectable" data-inspect="resource" data-id="${esc(r.resource_id)}"><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.storage_class)}</div></td><td>${fmt(r.amount)}</td><td>${fmt(r.available)}</td><td>${signed(f.local_net_per_day)}</td><td>${fmt(f.inbound_in_transit_t)}</td><td>${fmt(f.outbound_in_transit_t)}</td><td>${fmt(f.arrival_waiting_t)}</td><td>${fmt(r.free_capacity)}</td></tr>`;
    }).join('');
    return `<section class="card"><div class="card-heading"><h3>在庫・ローカルフロー・物流状態</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>在庫</th><th>利用可</th><th>Local net/日</th><th>入荷中</th><th>出荷中</th><th>到着待機</th><th>空容量</th></tr></thead><tbody>${rows || '<tr><td colspan="8">表示対象なし</td></tr>'}</tbody></table></div></section>`;
  }
  function signed(v) { const n = Number(v || 0); return `${n > 0 ? '+' : ''}${fmt(n, 2)}`; }

  function renderConstructionTab() {
    const projects = state.projects?.items || [];
    const options = state.buildOptions?.items || [];
    const pRows = projects.map((p) => `<tr class="selectable" data-inspect="project" data-id="${esc(p.id)}"><td><div class="cell-main">${esc(p.display_name || p.facility_display_name || p.id)}</div><div class="cell-sub">${esc(p.id)}</div></td><td>${esc(p.status || (p.paused ? 'paused' : 'active'))}</td><td>${fmt(p.progress ?? p.construction_done ?? 0)}/${fmt(p.construction_required ?? 0)}</td><td>${p.priority ?? '—'}</td><td>${(p.blockers || []).length}</td></tr>`).join('');
    const optionCards = options.map((o) => {
      const blocked = (o.missing_technologies?.length || 0) + (o.site_blockers?.length || 0);
      return `<div class="route-mode-card"><div class="mode-title"><span>${esc(o.display_name)}</span><span class="badge ${blocked ? 'warn' : 'ok'}">${blocked ? `${blocked} blocker` : '建設可'}</span></div><div class="cell-sub">工数 ${fmt(o.construction_required, 0)} · 部材 ${o.components?.length || 0}種</div><div class="action-row" style="margin-top:8px"><button type="button" data-build="${esc(o.facility_definition_id)}" ${blocked ? 'disabled' : ''}>建設計画</button><button type="button" data-inspect="build-option" data-id="${esc(o.facility_definition_id)}">詳細</button></div></div>`;
    }).join('');
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>建設案件</h3><span class="badge">${projects.length}</span></div><div class="table-wrap"><table><thead><tr><th>案件</th><th>状態</th><th>進捗</th><th>優先</th><th>blocker</th></tr></thead><tbody>${pRows || '<tr><td colspan="5">進行中案件なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>新規建設</h3><span class="badge">${options.length}</span></div><div class="card-body">${optionCards}</div></section></div>`;
  }

  function renderResearchTab() {
    const rows = (state.research?.items || []).map((r) => {
      const progress = r.theory_required ? r.theory_done / r.theory_required : 0;
      return `<tr class="selectable" data-inspect="research" data-id="${esc(r.id)}"><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.status)}</div></td><td><div>${fmt(r.theory_done)}/${fmt(r.theory_required)}</div><div class="progress-track"><div class="progress-bar" style="width:${Math.max(0, Math.min(100, progress * 100))}%"></div></div></td><td>${fmt(r.allocation_weight,2)}</td><td>${fmt(r.eligible_capacity_points_per_day,2)}</td><td>${(r.theory_blockers || []).length}</td></tr>`;
    }).join('');
    return `<section class="card"><div class="card-heading"><h3>研究</h3><span class="badge">研究能力 ${fmt(state.research?.capacity_points_per_day,2)}/日</span></div><div class="table-wrap"><table><thead><tr><th>研究</th><th>Theory</th><th>配分</th><th>適格能力</th><th>blocker</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }

  function renderSurveyTab() {
    const rows = (state.surveys?.items || []).map((s) => `<tr class="selectable" data-inspect="survey" data-id="${esc(s.resource_id)}"><td><div class="cell-main">${esc(s.resource_name)}</div><div class="cell-sub">知識Lv ${s.knowledge_level}</div></td><td>${s.active ? (s.paused ? '<span class="badge warn">停止</span>' : '<span class="badge ok">探査中</span>') : '<span class="badge">未開始</span>'}</td><td>${pct(s.progress)}</td><td>${fmt(s.capacity_points_per_day,2)}</td><td>${s.presence_probability == null ? '—' : pct(s.presence_probability)}</td><td>${s.visible_reserve_t == null ? '—' : fmt(s.visible_reserve_t)}</td></tr>`).join('');
    return `<section class="card"><div class="card-heading"><h3>地点探査</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>状態</th><th>進捗</th><th>能力/日</th><th>存在確率</th><th>推定埋蔵量</th></tr></thead><tbody>${rows || '<tr><td colspan="6">この地点に探査対象なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderContractsTab() {
    const rows = (state.contracts?.items || []).map((c) => `<tr class="selectable" data-inspect="contract" data-id="${esc(c.id)}"><td><div class="cell-main">${esc(c.display_name)}</div><div class="cell-sub">${esc(c.kind)} · ${esc(c.id)}</div></td><td>${esc(c.status)}</td><td>Day ${c.deadline_day}</td><td>${fmt(c.reward_musd)} M$</td><td>${(c.blockers || []).length}</td></tr>`).join('');
    return `<section class="card"><div class="card-heading"><h3>契約</h3></div><div class="table-wrap"><table><thead><tr><th>契約</th><th>状態</th><th>期限</th><th>報酬</th><th>blocker</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }

  function selectInspector(type, id) {
    state.inspector = {type, id};
    renderInspector();
    if (type === 'facility') {
      $$('#operationsTabContent tr').forEach((tr) => tr.classList.toggle('is-selected', tr.dataset.id === id));
    }
  }

  function renderInspector() {
    const title = $('#inspectorTitle'), content = $('#inspectorContent');
    if (!state.inspector) { title.textContent = '選択項目'; content.innerHTML = '<div class="empty-state">中央の項目を選択すると、状態・条件・操作をここに表示します。</div>'; return; }
    const {type, id} = state.inspector;
    if (type === 'facility') return renderFacilityInspector(id);
    if (type === 'resource') return renderResourceInspector(id);
    if (type === 'project') return renderProjectInspector(id);
    if (type === 'build-option') return renderBuildOptionInspector(id);
    if (type === 'research') return renderResearchInspector(id);
    if (type === 'survey') return renderSurveyInspector(id);
    if (type === 'contract') return renderContractInspector(id);
  }

  function setInspector(titleText, html) { $('#inspectorTitle').textContent = titleText; $('#inspectorContent').innerHTML = html; }
  function section(title, body) { return `<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`; }
  function kv(rows) { return `<dl class="kv-grid">${rows.map(([k,v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`; }

  function renderFacilityInspector(id) {
    const f = state.location?.facilities.find((x) => x.id === id); if (!f) return;
    const blockers = f.activation_blockers || [];
    setInspector(f.display_name, section('状態', kv([['ID', esc(f.id)], ['定義', esc(f.definition_id)], ['運転', f.paused ? '手動停止' : '稼働'], ['電力利用率', pct(f.power_utilization)], ['電力優先度', esc(f.power_priority ?? '—')]])) + section('Blocker', blockers.length ? `<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>` : '<div class="badge ok">なし</div>') + section('操作', `<div class="action-stack"><button type="button" data-command="${f.paused ? 'ResumeFacility' : 'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused ? '設備を再開' : '設備を停止'}</button><div class="form-row"><label>電力優先度<input id="facilityPriorityInput" type="number" step="1" value="${f.power_priority ?? 50}"></label><button type="button" data-set-power-priority="${esc(f.id)}">優先度を適用</button></div></div>`));
  }

  function renderResourceInspector(id) {
    const inv = state.location?.inventory.find((x) => x.resource_id === id); const f = state.flow?.resources.find((x) => x.resource_id === id); if (!inv) return;
    setInspector(inv.display_name, section('在庫', kv([['在庫', fmt(inv.amount)], ['予約', fmt(inv.reserved)], ['利用可能', fmt(inv.available)], ['空容量', fmt(inv.free_capacity)], ['Storage', esc(inv.storage_class)]])) + section('フロー', kv([['生産/日', signed(f?.local_production_per_day)], ['消費/日', signed(f?.local_consumption_per_day)], ['Local net/日', signed(f?.local_net_per_day)], ['入荷中', fmt(f?.inbound_in_transit_t)], ['出荷中', fmt(f?.outbound_in_transit_t)], ['到着待機', fmt(f?.arrival_waiting_t)]])));
  }

  function renderProjectInspector(id) {
    const p = state.projects?.items.find((x) => x.id === id); if (!p) return;
    setInspector(p.display_name || p.facility_display_name || p.id, section('案件', kv([['ID',esc(p.id)],['状態',esc(p.status || (p.paused?'paused':'active'))],['優先度',esc(p.priority ?? '—')],['工数',`${fmt(p.progress ?? p.construction_done ?? 0)}/${fmt(p.construction_required ?? 0)}`]])) + section('操作', `<div class="action-stack"><button type="button" data-command="${p.paused ? 'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}">${p.paused ? '建設再開':'建設停止'}</button><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}">案件取消</button></div>`));
  }

  function renderBuildOptionInspector(id) {
    const o = state.buildOptions?.items.find((x) => x.facility_definition_id === id); if (!o) return;
    const components = (o.components || []).map((c) => `<div class="route-mode-card"><div class="mode-title"><span>${esc(c.component_id.replaceAll('_',' '))}</span><span>${fmt(c.required_t)}t</span></div><div class="cell-sub">輸入材: ${esc(resourceName(c.import_resource_id))}</div></div>`).join('');
    const blockers = [...(o.missing_technologies || []).map((x) => ['technology', x]), ...(o.site_blockers || [])];
    setInspector(o.display_name, section('建設', kv([['必要工数',fmt(o.construction_required,0)],['自己展開',o.self_deploying?'はい':'いいえ']])) + section('必要部材', components) + section('Blocker', blockers.length ? blockers.map(issueHtml).join('') : '<span class="badge ok">なし</span>') + section('操作', `<button type="button" class="primary" data-build="${esc(o.facility_definition_id)}" ${blockers.length ? 'disabled':''}>この地点に建設</button>`));
  }

  function renderResearchInspector(id) {
    const r = state.research?.items.find((x) => x.id === id); if (!r) return;
    const canPause = !['available','locked','complete'].includes(r.status);
    let action = '';
    if (r.status === 'available' && r.can_start) action = `<button type="button" class="primary" data-research-action="start" data-id="${esc(r.id)}">研究開始</button>`;
    else if (r.paused) action = `<button type="button" data-research-action="resume" data-id="${esc(r.id)}">研究再開</button>`;
    else if (canPause) action = `<button type="button" data-research-action="pause" data-id="${esc(r.id)}">研究停止</button>`;
    setInspector(r.display_name, section('状態', kv([['Status',esc(r.status)],['Theory',`${fmt(r.theory_done)}/${fmt(r.theory_required)}`],['配分',fmt(r.allocation_weight,2)],['適格能力/日',fmt(r.eligible_capacity_points_per_day,2)],['実証日数',`${r.demonstration_done_days}/${r.demonstration_required_days}`]])) + section('前提', (r.prerequisites || []).length ? (r.prerequisites || []).map((x)=>`<div class="badge">${esc(definitionName(x))}</div>`).join(' ') : '<span class="badge ok">なし</span>') + section('操作', `<div class="action-stack">${action}<div class="form-row"><label>研究配分<input id="researchWeightInput" type="number" min="0" step="0.1" value="${r.allocation_weight || 1}"></label><button type="button" data-set-research-weight="${esc(r.id)}">配分を適用</button></div></div>`));
  }

  function renderSurveyInspector(id) {
    const s = state.surveys?.items.find((x) => x.resource_id === id); if (!s) return;
    let action = s.active ? (s.paused ? `<button data-survey-action="resume" data-id="${esc(id)}">探査再開</button>` : `<button data-survey-action="pause" data-id="${esc(id)}">探査停止</button>`) : `<button class="primary" data-survey-action="start" data-id="${esc(id)}">探査開始</button>`;
    setInspector(s.resource_name, section('探査状態', kv([['進捗',pct(s.progress)],['知識レベル',String(s.knowledge_level)],['能力/日',fmt(s.capacity_points_per_day,2)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['推定埋蔵量',s.visible_reserve_t==null?'—':`${fmt(s.visible_reserve_t)} t`]])) + section('操作', `<div class="action-stack">${action}<div class="form-row"><label>探査配分<input id="surveyWeightInput" type="number" min="0" step="0.1" value="${s.allocation_weight || 1}"></label><button data-set-survey-weight="${esc(id)}">配分を適用</button></div></div>`));
  }

  function renderContractInspector(id) {
    const c = state.contracts?.items.find((x) => x.id === id); if (!c) return;
    const offered = c.status === 'offered';
    setInspector(c.display_name, section('契約', kv([['種別',esc(c.kind)],['状態',esc(c.status)],['期限',`Day ${c.deadline_day}`],['報酬',`${fmt(c.reward_musd)} M$`],['出発地',esc(locationName(c.source_id))],['到着地',esc(locationName(c.destination_id))],['貨物',c.resource_id?`${esc(resourceName(c.resource_id))} ${fmt(c.cargo_t)}t`:'—']])) + section('Blocker',(c.blockers||[]).length?`<div class="issue-stack">${c.blockers.map((x)=>issueHtml(['contract',x])).join('')}</div>`:'<span class="badge ok">なし</span>') + section('操作', offered ? `<div class="action-row"><button class="primary" data-contract-action="accept" data-id="${esc(c.id)}">受諾</button><button class="danger-button" data-contract-action="decline" data-id="${esc(c.id)}">辞退</button></div>` : '<span class="badge">受諾済み/処理済み</span>'));
  }

  function renderLogistics() {
    if (!state.logisticsSummary || !state.routes) return;
    const s = state.logisticsSummary;
    $('#logisticsSummary').innerHTML = [['輸送路',`${s.usable_route_count}/${s.route_count}`],['輸送機',`${s.available_vehicle_count}/${s.vehicle_count}`],['輸送待ち',`${fmt(s.waiting_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');
    renderRouteFilters(); renderRouteList(); renderNetwork(); renderVehicles(); renderCargo(); renderRouteInspector();
  }

  function renderRouteFilters() {
    const locs = state.world?.locations || [];
    for (const [selId,label] of [['#routeOriginFilter','全出発地'],['#routeDestinationFilter','全到着地']]) {
      const sel = $(selId); const current = sel.value;
      sel.innerHTML = `<option value="">${label}</option>` + locs.map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
      if ([...sel.options].some((o)=>o.value===current)) sel.value=current;
    }
  }

  function filteredRoutes() {
    const origin = $('#routeOriginFilter')?.value || '', dest = $('#routeDestinationFilter')?.value || '';
    return (state.routes?.items || []).filter((r)=>(!origin||r.origin_id===origin)&&(!dest||r.destination_id===dest));
  }

  function renderRouteList() {
    $('#routeList').innerHTML = filteredRoutes().map((r)=>`<button type="button" class="route-button ${r.id===state.selectedRouteId?'is-selected':''}" data-route-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="route-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.usable_now?'ok':r.available?'warn':''}">${r.usable_now?'利用可':r.available?'設備待ち':'未解禁'}</span></div></button>`).join('') || '<div class="empty-state">条件に一致するRouteなし</div>';
  }

  const nodePositions = {
    'base.node.earth_surface':[12,50], 'base.node.low_earth_orbit':[34,50], 'base.node.lunar_orbit':[60,50],
    'base.node.south_polar_ridge':[84,22], 'base.node.polar_cold_trap':[84,50], 'base.node.nearside_mare':[84,78]
  };

  function renderNetwork() {
    const svg = $('#networkSvg'), nodes = $('#networkNodes'); const routes = state.routes?.items || [];
    svg.innerHTML = routes.map((r)=>{
      const a=nodePositions[r.origin_id], b=nodePositions[r.destination_id]; if(!a||!b)return '';
      return `<line x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}" class="network-line ${r.usable_now?'available':''} ${r.id===state.selectedRouteId?'selected':''}" data-route-line="${esc(r.id)}" />`;
    }).join('');
    nodes.innerHTML = (state.world?.locations || []).map((loc)=>{ const p=nodePositions[loc.id]||[50,50]; return `<div class="network-node" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`; }).join('');
  }

  function renderVehicles() {
    const items=state.vehicles?.items||[]; $('#vehicleCountBadge').textContent=`${items.length}機`;
    const rows=items.map((v)=>`<tr><td><div class="cell-main">${esc(v.display_name)}</div><div class="cell-sub">${esc(v.id)}</div></td><td>${esc(locationName(v.location_id))}</td><td>${esc(stateLabels[v.status] || v.status)}</td><td>${fmt(v.propellant_t)}/${fmt(v.propellant_capacity_t)}</td><td>${fmt(v.payload_t)}t</td><td>${(v.blockers||[]).length}</td></tr>`).join('');
    $('#vehicleTable').innerHTML=`<table><thead><tr><th>機体</th><th>現在地</th><th>状態</th><th>推進剤</th><th>Payload</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="6">輸送資産なし</td></tr>'}</tbody></table>`;
  }

  function renderCargo() {
    const items=state.orders?.items||[]; $('#cargoCountBadge').textContent=`${items.length}件`;
    const rows=items.map((o)=>`<tr><td>${esc(resourceName(o.resource_id))}<div class="cell-sub">${esc(o.id)}</div></td><td>${esc(locationName(o.source_id))} → ${esc(locationName(o.destination_id))}</td><td>${fmt(o.amount_t ?? o.requested_t)}t</td><td>${esc(stateLabels[o.status] || o.status)}</td><td>${(o.blockers||[]).length}</td></tr>`).join('');
    $('#cargoTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newCargoButton">貨物輸送を設定</button></div><table><thead><tr><th>貨物</th><th>区間</th><th>数量</th><th>状態</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="5">貨物注文なし</td></tr>'}</tbody></table>`;
  }

  function renderRouteInspector() {
    const title=$('#routeInspectorTitle'), content=$('#routeInspectorContent');
    if(!state.selectedRouteId){title.textContent='輸送路を選択';content.innerHTML='<div class="empty-state">左の輸送路またはネットワーク上の接続を選択してください。</div>';return;}
    const route=(state.routeDetail?.items||[]).find((r)=>r.id===state.selectedRouteId)||(state.routes?.items||[]).find((r)=>r.id===state.selectedRouteId);
    if(!route)return;
    title.textContent=route.display_name;
    const blockers=[...new Map([...(route.blockers||[]),...(route.operational_blockers||[])].map((x)=>[JSON.stringify(x),x])).values()];
    const modes=(route.modes||[]).map((m)=>`<div class="route-mode-card ${m.usable_now?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name||m.mode_id||m.kind||'輸送方式')}</span><span class="badge ${m.usable_now?'ok':'warn'}">${m.usable_now?'利用可':'利用不可'}</span></div>${m.transit_days!=null?`<div class="cell-sub">${fmt(m.transit_days)}日 · ${fmt(m.dispatch_capacity_t)}t</div>`:''}${(m.blockers||[]).length?`<div class="issue-stack" style="margin-top:7px">${m.blockers.map(issueHtml).join('')}</div>`:''}</div>`).join('');
    content.innerHTML=section('区間',kv([['出発',esc(locationName(route.origin_id))],['到着',esc(locationName(route.destination_id))],['解禁',route.available?'はい':'いいえ'],['現在利用',route.usable_now?'はい':'いいえ'],['基準日数',fmt(route.transit_days)],['Δv',`${fmt(route.delta_v_km_s,2)} km/s`],['Dispatch能力',`${fmt(route.dispatch_capacity_t)} t`]]))+section('Operation',(route.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o) ? o[0] : o))}</span>`).join(' ')||'—')+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('輸送方式',modes||'<div class="empty-state">方式情報なし</div>')+section('操作','<button type="button" class="primary" id="routeCargoButton">この区間を基準に貨物輸送</button>');
  }

  function populateStaticSelects() {
    const locOpts=(state.world?.locations||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
    $('#cargoSource').innerHTML=locOpts; $('#cargoDestination').innerHTML=locOpts;
    $('#cargoResource').innerHTML=(state.catalog?.resources||[]).map((r)=>`<option value="${esc(r.id)}">${esc(r.display_name)}</option>`).join('');
  }

  function openCargoDialog(route=null) {
    if(route){$('#cargoSource').value=route.origin_id;$('#cargoDestination').value=route.destination_id;}
    $('#cargoDialog').showModal();
  }

  function renderAll(){ renderHeader(); renderLocations(); renderGlobalIssues(); renderOperations(); renderLogistics(); }

  document.addEventListener('click', async (event) => {
    const viewBtn=event.target.closest('[data-view]'); if(viewBtn){ state.activeView=viewBtn.dataset.view; $$('.view-button').forEach((b)=>b.classList.toggle('is-active',b===viewBtn)); $('#operationsView').hidden=state.activeView!=='operations'; $('#logisticsView').hidden=state.activeView!=='logistics'; if(state.activeView==='logistics') renderLogistics(); return; }
    const locBtn=event.target.closest('[data-location-id]'); if(locBtn){ await loadLocation(locBtn.dataset.locationId); return; }
    const tab=event.target.closest('[data-tab]'); if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;renderOperations();return;}
    const inspect=event.target.closest('[data-inspect]'); if(inspect){selectInspector(inspect.dataset.inspect,inspect.dataset.id);return;}
    const advance=event.target.closest('[data-advance]'); if(advance){try{await command('AdvanceTime',{days:Number(advance.dataset.advance)});banner(`${advance.dataset.advance}日進行しました`);}catch{}return;}
    const build=event.target.closest('[data-build]'); if(build){try{await command('PlanBuild',{location_id:state.locationId,facility_id:build.dataset.build,priority:50,sourcing_policy:'mixed',import_source_id:null});banner('建設計画を作成しました');}catch{}return;}
    const routeBtn=event.target.closest('[data-route-id]'); if(routeBtn){await loadRouteDetail(routeBtn.dataset.routeId);return;}
    const routeLine=event.target.closest('[data-route-line]'); if(routeLine){await loadRouteDetail(routeLine.dataset.routeLine);return;}
    if(event.target.closest('#newCargoButton')){openCargoDialog();return;}
    if(event.target.closest('#routeCargoButton')){const r=(state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId);openCargoDialog(r);return;}
    const cmd=event.target.closest('[data-command]'); if(cmd){let payload={};if(cmd.dataset.facilityId)payload.facility_id=cmd.dataset.facilityId;if(cmd.dataset.projectId)payload.project_id=cmd.dataset.projectId;try{await command(cmd.dataset.command,payload);}catch{}return;}
    const pp=event.target.closest('[data-set-power-priority]'); if(pp){try{await command('SetPowerPriority',{facility_id:pp.dataset.setPowerPriority,priority:Number($('#facilityPriorityInput').value)});}catch{}return;}
    const ra=event.target.closest('[data-research-action]'); if(ra){const map={start:'StartResearch',pause:'PauseResearch',resume:'ResumeResearch'};const payload={research_id:ra.dataset.id};if(ra.dataset.researchAction==='start')payload.allocation_weight=1;try{await command(map[ra.dataset.researchAction],payload);}catch{}return;}
    const rw=event.target.closest('[data-set-research-weight]'); if(rw){try{await command('SetResearchAllocation',{research_id:rw.dataset.setResearchWeight,weight:Number($('#researchWeightInput').value)});}catch{}return;}
    const sa=event.target.closest('[data-survey-action]'); if(sa){const map={start:'StartSurvey',pause:'PauseSurvey',resume:'ResumeSurvey'};const payload={location_id:state.locationId,resource_id:sa.dataset.id};if(sa.dataset.surveyAction==='start')payload.allocation_weight=1;try{await command(map[sa.dataset.surveyAction],payload);}catch{}return;}
    const sw=event.target.closest('[data-set-survey-weight]'); if(sw){try{await command('SetSurveyAllocation',{location_id:state.locationId,resource_id:sw.dataset.setSurveyWeight,weight:Number($('#surveyWeightInput').value)});}catch{}return;}
    const ca=event.target.closest('[data-contract-action]'); if(ca){try{await command(ca.dataset.contractAction==='accept'?'AcceptContract':'DeclineContract',{contract_id:ca.dataset.id});}catch{}return;}
    if(event.target.closest('#refreshButton')){try{await refreshCurrentContext();banner('最新状態を取得しました');}catch(e){banner(e.message,'error');}return;}
  });

  $('#routeOriginFilter').addEventListener('change',()=>{renderRouteList();});
  $('#routeDestinationFilter').addEventListener('change',()=>{renderRouteList();});
  $('#saveButton').addEventListener('click', async()=>{try{await api('/api/v1/session/save',{method:'POST',body:JSON.stringify({slot:'manual'})});banner('manual スロットへ保存しました');}catch(e){banner(e.message,'error');}});
  $('#loadButton').addEventListener('click', async()=>{try{await api('/api/v1/session/load',{method:'POST',body:JSON.stringify({slot:'manual',apply_offline:true})});await refreshCurrentContext();banner('manual スロットを読み込みました');}catch(e){banner(e.message,'error');}});
  $('#cargoCloseButton').addEventListener('click',()=>$('#cargoDialog').close());
  $('#cargoCancelButton').addEventListener('click',()=>$('#cargoDialog').close());
  $('#cargoForm').addEventListener('submit',async(event)=>{event.preventDefault();try{await command('SubmitCargo',{source_id:$('#cargoSource').value,destination_id:$('#cargoDestination').value,resource_id:$('#cargoResource').value,amount_t:Number($('#cargoAmount').value),priority:Number($('#cargoPriority').value),path:null,route_modes:[],path_policy:$('#cargoPolicy').value});$('#cargoDialog').close();banner('貨物輸送を登録しました');}catch{}});

  window.addEventListener('online',()=>setConnection('ok','PC Server'));
  window.addEventListener('offline',()=>setConnection('error','オフライン'));

  initialLoad().catch((err)=>{setConnection('error','接続失敗');banner(`Serverへ接続できません: ${err.message}`,'error',0);$('#app').setAttribute('aria-busy','false');});
})();
