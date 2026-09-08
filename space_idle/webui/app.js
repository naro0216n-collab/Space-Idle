(() => {
  'use strict';

  const state = {
    revision:null, session:null, world:null, catalog:null, locationId:null, location:null,
    flow:null, globalIssues:null, bottlenecks:null, projects:null, buildOptions:null,
    research:null, surveys:null, contracts:null, logisticsSummary:null, routes:null,
    vehicles:null, orders:null, missions:null, selectedRouteId:null,
    activeView:'operations', activeTab:'overview', inspector:null, busy:false,
    syncInFlight:null, cargoPlans:null, cargoContractId:null,
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]));
  const fmt = (v, digits = 1) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ja-JP', {maximumFractionDigits:digits}) : '—';
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
    base_construction:'基礎建設', basic_machine_shop:'基礎機械加工', bulk_storage:'バルク保管',
    cargo_storage:'一般貨物保管', cargo_transfer:'貨物移送', construction_yard:'建設ヤード',
    cryogenic_storage:'極低温保管', grid_power:'外部電力網', heavy_equipment_assembly:'重機組立',
    industrial_electrolysis:'工業電解', industrial_power:'産業電力', launch_operations:'打上げ運用',
    launch_vehicle_servicing:'打上げ機整備', metallurgy:'金属精錬', ore_processing:'鉱石処理',
    power_grid:'電力網', propellant_production:'推進剤製造', regolith_excavation:'レゴリス採掘',
    research_lab:'研究設備', robotic_operations:'ロボット運用', sintering:'焼結',
    spacecraft_servicing:'宇宙船整備', structural_fabrication:'構造材加工', surface_survey:'地表探査',
    vehicle_assembly:'輸送機組立', vehicle_refueling:'輸送機補給', water_extraction:'水抽出', water_storage:'水保管',
  };
  const operationLabels = {powered_ascent:'動力離昇', launch:'打上げ', spaceflight:'宇宙航行', landing:'着陸', atmospheric_entry:'大気圏突入'};
  const locationKindLabels = {surface:'地表', orbital:'軌道', orbit:'軌道'};
  const storageClassLabels = {bulk:'バルク', cryogenic:'極低温', general_cargo:'一般貨物', liquid:'液体'};
  const stateLabels = {
    available:'利用可能', active:'稼働', paused:'停止', locked:'未解禁', complete:'完了',
    offered:'提示中', accepted:'受諾済み', declined:'辞退', failed:'失敗', waiting:'待機',
    in_transit:'輸送中', arrival_waiting:'到着待機', prototype:'試作', demonstration:'実証',
    planned:'計画', procuring:'調達中', ready:'施工待ち', building:'施工中', cancelled:'取消済み',
  };
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
    const headers = {'Accept':'application/json', ...(options.headers || {})};
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, {...options, headers, cache:'no-store'});
    const text = response.status === 304 ? '' : await response.text();
    const payload = text ? JSON.parse(text) : null;
    const rev = response.headers.get('X-Space-Idle-Revision');
    if (rev !== null) state.revision = Math.max(state.revision ?? 0, Number(rev));
    if (!response.ok) {
      const err = new Error(payload?.error?.message || `${response.status} ${response.statusText}`);
      err.code = payload?.error?.code;
      err.status = response.status;
      err.details = payload?.error?.details;
      throw err;
    }
    if (payload?.revision !== undefined) state.revision = Math.max(state.revision ?? 0, Number(payload.revision));
    return payload?.data ?? payload;
  }

  function captureInteraction() {
    const active = document.activeElement;
    const control = active && /^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName) && active.id ? active : null;
    const scroll = document.scrollingElement;
    return {
      control:control ? {
        id:control.id, value:control.value,
        selectionStart:typeof control.selectionStart === 'number' ? control.selectionStart : null,
        selectionEnd:typeof control.selectionEnd === 'number' ? control.selectionEnd : null,
      } : null,
      scrollLeft:scroll?.scrollLeft || 0,
      scrollTop:scroll?.scrollTop || 0,
    };
  }

  function restoreInteraction(snapshot) {
    if (!snapshot) return;
    if (snapshot.control) {
      const control = document.getElementById(snapshot.control.id);
      if (control && /^(INPUT|SELECT|TEXTAREA)$/.test(control.tagName)) {
        control.value = snapshot.control.value;
        control.focus({preventScroll:true});
        if (snapshot.control.selectionStart !== null && typeof control.setSelectionRange === 'function') {
          try { control.setSelectionRange(snapshot.control.selectionStart, snapshot.control.selectionEnd); } catch {}
        }
      }
    }
    if (document.scrollingElement) {
      document.scrollingElement.scrollLeft = snapshot.scrollLeft;
      document.scrollingElement.scrollTop = snapshot.scrollTop;
    }
  }

  function applyUiSnapshot(data) {
    state.session=data.session; state.world=data.world; state.globalIssues=data.global_issues;
    state.research=data.research; state.contracts=data.contracts; state.logisticsSummary=data.logistics_summary;
    state.routes=data.routes; state.vehicles=data.vehicles; state.orders=data.orders; state.missions=data.missions;
    if (data.location !== undefined) state.location=data.location;
    if (data.flow !== undefined) state.flow=data.flow;
    if (data.projects !== undefined) state.projects=data.projects;
    if (data.build_options !== undefined) state.buildOptions=data.build_options;
    if (data.bottlenecks !== undefined) state.bottlenecks=data.bottlenecks;
    if (data.surveys !== undefined) state.surveys=data.surveys;
    if (state.selectedRouteId && !(state.routes?.items || []).some((r) => r.id === state.selectedRouteId)) state.selectedRouteId=null;
    if (state.inspector && !inspectorExists(state.inspector)) state.inspector=null;
  }

  function inspectorExists(inspector) {
    const {type,id}=inspector;
    if(type==='facility') return Boolean(state.location?.facilities?.some((x)=>x.id===id));
    if(type==='resource') return Boolean(state.location?.inventory?.some((x)=>x.resource_id===id));
    if(type==='project') return Boolean(state.projects?.items?.some((x)=>x.id===id));
    if(type==='build-option') return Boolean(state.buildOptions?.items?.some((x)=>x.facility_definition_id===id));
    if(type==='research') return Boolean(state.research?.items?.some((x)=>x.id===id));
    if(type==='survey') return Boolean(state.surveys?.items?.some((x)=>x.resource_id===id));
    if(type==='contract') return Boolean(state.contracts?.items?.some((x)=>x.id===id));
    return false;
  }

  async function loadUiSnapshot({preserveInteraction=true}={}) {
    if(state.syncInFlight) return state.syncInFlight;
    state.syncInFlight=(async()=>{
      const suffix=state.locationId?`?location_id=${encodeURIComponent(state.locationId)}`:'';
      const data=await api(`/api/v1/ui-state${suffix}`);
      applyUiSnapshot(data);
      if(!state.locationId || !(state.world?.locations||[]).some((x)=>x.id===state.locationId)) {
        state.locationId=state.world?.locations?.[0]?.id ?? null;
        if(state.locationId && data.location===undefined) {
          const nested=await api(`/api/v1/ui-state?location_id=${encodeURIComponent(state.locationId)}`);
          applyUiSnapshot(nested);
        }
      }
      const interaction=preserveInteraction?captureInteraction():null;
      renderAll(); restoreInteraction(interaction); setConnection('ok','PC Server');
      return data;
    })();
    try{return await state.syncInFlight;}finally{state.syncInFlight=null;}
  }

  async function beginMutation() {
    while(state.busy) await new Promise((resolve)=>setTimeout(resolve,20));
    state.busy=true; document.body.classList.add('is-busy');
    const pending=state.syncInFlight;
    if(pending){try{await pending;}catch{}}
    return true;
  }
  function endMutation(){state.busy=false;document.body.classList.remove('is-busy');}

  async function command(type,payload={}) {
    if(!await beginMutation())return;
    try{
      const headers={}; if(state.revision!==null)headers['If-Match']=`"rev-${state.revision}"`;
      const result=await api('/api/v1/commands',{method:'POST',headers,body:JSON.stringify({type,payload})});
      await loadUiSnapshot(); return result;
    }catch(err){
      if(err.code==='revision_conflict'){banner('別の操作で状態が更新されました。最新状態を再取得しました。','error');await loadUiSnapshot();}
      else banner(err.message||'操作に失敗しました','error',7000);
      throw err;
    }finally{endMutation();}
  }

  async function setTimeControl(payload){
    if(!await beginMutation())return;
    try{state.session=await api('/api/v1/time-control',{method:'POST',body:JSON.stringify(payload)});renderHeader();await loadUiSnapshot();}
    finally{endMutation();}
  }

  async function initialLoad(){
    setConnection('pending','接続中');
    const [catalog,world]=await Promise.all([api('/api/v1/catalog'),api('/api/v1/world')]);
    state.catalog=catalog;state.world=world;state.locationId=world.locations?.[0]?.id??null;
    populateStaticSelects();await loadUiSnapshot({preserveInteraction:false});$('#app').setAttribute('aria-busy','false');
  }
  async function loadLocation(locationId){if(!locationId)return;state.locationId=locationId;state.inspector=null;await loadUiSnapshot({preserveInteraction:false});}

  function renderHeader(){
    $('#dayValue').textContent=fmt(state.world?.day??state.session?.day,0);
    $('#fundsValue').textContent=`${fmt(state.world?.funds_musd,1)} M$`;
    $('#revisionValue').textContent=state.revision??state.session?.revision??'—';
    $('#appVersion').textContent=`v${state.session?.app_version||'0.4.5'}`;
    const paused=Boolean(state.session?.time_paused), speed=Number(state.session?.time_speed_multiplier||1), pause=$('#timePauseButton');
    pause.textContent=paused?'▶ 再開':'⏸ 一時停止';pause.setAttribute('aria-label',paused?'再開':'一時停止');pause.setAttribute('aria-pressed',paused?'true':'false');
    $$('[data-time-speed]').forEach((button)=>{const selected=Number(button.dataset.timeSpeed)===speed;button.setAttribute('aria-pressed',selected?'true':'false');button.disabled=selected;});
    const timeState=$('#timeState');if(timeState)timeState.textContent=state.session?.automatic_progress_enabled===false?'自動進行無効':paused?`停止中 · ${speed}×`:`自動進行 · ${speed}×`;
  }

  function renderLocations(){
    $('#locationList').innerHTML=(state.world?.locations||[]).map((loc)=>`<button type="button" class="location-button ${loc.id===state.locationId?'is-active':''}" data-location-id="${esc(loc.id)}"><span class="location-name">${esc(loc.display_name)}</span><span class="location-meta"><span>${esc(locationKindLabels[loc.kind]||loc.kind)}</span><span>設備 ${loc.facility_count}</span><span>建設 ${loc.active_project_count}</span></span></button>`).join('');
  }

  function issueHtml(issue){
    const rawMessage=Array.isArray(issue)?issue[1]:issue.message||issue.code||String(issue);
    const rawCategory=Array.isArray(issue)?issue[0]:issue.category||issue.source||'';
    let message=userFacingText(rawMessage);
    if(rawCategory==='technology'&&definitionName(rawMessage)!==rawMessage)message=`必要技術: ${definitionName(rawMessage)}`;
    if(rawCategory==='capability')message=`必要能力: ${capabilityName(rawMessage)}`;
    const categoryLabels={technology:'技術条件',capability:'能力条件',environment:'環境条件',contract:'契約',logistics:'物流',construction:'建設',research:'研究',survey:'探査',storage:'保管',power:'電力'};
    const category=categoryLabels[rawCategory]||userFacingText(rawCategory);
    const context=!Array.isArray(issue)&&issue.entity_id?definitionName(issue.entity_id):'';
    const meta=[category,context&&context!==issue.entity_id?context:''].filter(Boolean).join(' · ');
    return `<div class="issue"><div class="issue-title">${esc(message)}</div>${meta?`<div class="issue-meta">${esc(meta)}</div>`:''}</div>`;
  }
  function renderGlobalIssues(){const issues=state.globalIssues?.items||[];$('#globalIssues').innerHTML=issues.length?issues.slice(0,8).map(issueHtml).join('')+(issues.length>8?`<div class="cell-sub">ほか ${issues.length-8} 件</div>`:''):'<div class="empty-state">現在、全体blockerはありません。</div>';}
  function metricHtml([label,value]){return `<div class="metric-chip"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;}
  function statHtml(label,value){return `<div class="stat-box"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;}
  function signed(v){const n=Number(v||0);return `${n>0?'+':''}${fmt(n,2)}`;}

  function renderOperations(){
    const loc=state.location;if(!loc)return;
    $('#locationTitle').textContent=loc.display_name;
    $('#locationKind').textContent=`${locationKindLabels[locationMap()[loc.id]?.kind]||locationMap()[loc.id]?.kind||'拠点'}拠点`;
    $('#headlineMetrics').innerHTML=[['発電',`${fmt(loc.power_generation_mw)} MW`],['需要',`${fmt(loc.power_demand_mw)} MW`],['建設能力',`${fmt(loc.construction_capacity_per_day)} /日`],['設備',`${loc.facilities.length}`]].map(metricHtml).join('');
    $$('.tab-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.tab===state.activeTab));renderActiveTab();renderInspector();
  }
  function renderActiveTab(){const renderers={overview:renderOverviewTab,facilities:renderFacilitiesTab,inventory:renderInventoryTab,construction:renderConstructionTab,research:renderResearchTab,survey:renderSurveyTab,contracts:renderContractsTab};$('#operationsTabContent').innerHTML=renderers[state.activeTab]();}

  function renderOverviewTab(){
    const loc=state.location,flow=state.flow,issues=state.bottlenecks?.items||[];
    const storageRows=(loc.storage||[]).map((s)=>`<tr><td>${esc(storageClassLabels[s.storage_class]||s.storage_class)}</td><td>${fmt(s.stock_t)}</td><td>${fmt(s.service_capacity_t)}</td><td>${fmt(s.free_service_t)}</td><td>${fmt(s.unserviced_occupied_t)}</td></tr>`).join('');
    const capabilityRows=(loc.capabilities||[]).filter((c)=>c.infrastructure_capacity||c.active_capacity||c.available_capacity).map((c)=>`<tr><td>${esc(capabilityName(c.id))}</td><td>${fmt(c.infrastructure_capacity)}</td><td>${fmt(c.active_capacity)}</td><td>${fmt(c.available_capacity)}</td></tr>`).join('');
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>運用状態</h3></div><div class="card-body"><div class="stat-grid">${statHtml('電力利用率',pct(flow?.power_utilization))}${statHtml('利用可能電力',`${fmt(loc.power_allocated_mw)} MW`)}${statHtml('建設能力',`${fmt(loc.construction_capacity_per_day)} /日`)}${statHtml('進行中建設',`${loc.projects?.length||0}`)}</div></div></section><section class="card"><div class="card-heading"><h3>地点blocker</h3><span class="badge ${issues.length?'warn':'ok'}">${issues.length} 件</span></div><div class="card-body issue-stack">${issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state">現在のblockerはありません。</div>'}</div></section><section class="card"><div class="card-heading"><h3>保管サービス</h3></div><div class="table-wrap"><table><thead><tr><th>Class</th><th>在庫t</th><th>Service</th><th>空き</th><th>未service</th></tr></thead><tbody>${storageRows||'<tr><td colspan="5">保管設備なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>能力</h3></div><div class="table-wrap"><table><thead><tr><th>能力</th><th>インフラ</th><th>稼働</th><th>利用可能</th></tr></thead><tbody>${capabilityRows||'<tr><td colspan="4">Capabilityなし</td></tr>'}</tbody></table></div></section></div>`;
  }

  function renderFacilitiesTab(){
    const rows=(state.location?.facilities||[]).map((f)=>{const u=f.next_upgrade;const upgrade=u?(u.active_project_id?`案件 ${esc(u.active_project_id)}`:`→ Lv ${fmt(u.target_level,0)}`):'—';return `<tr class="selectable" data-inspect="facility" data-id="${esc(f.id)}"><td><div class="cell-main">${esc(f.display_name)}</div><div class="cell-sub">${esc(f.id)}</div></td><td>Lv ${fmt(f.level,0)}</td><td>${f.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">稼働</span>'}</td><td>${pct(f.power_utilization)}</td><td>${f.power_priority??'—'}</td><td>${upgrade}</td><td>${(f.activation_blockers||[]).length}</td></tr>`;}).join('');
    return `<section class="card"><div class="card-heading"><h3>設備一覧</h3><span class="badge">${state.location?.facilities.length||0}</span></div><div class="table-wrap"><table><thead><tr><th>設備</th><th>Level</th><th>状態</th><th>電力</th><th>優先度</th><th>Upgrade</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="7">設備なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderInventoryTab(){
    const flowMap=Object.fromEntries((state.flow?.resources||[]).map((r)=>[r.resource_id,r]));
    const rows=(state.location?.inventory||[]).filter((r)=>r.amount||r.reserved||flowMap[r.resource_id]?.local_production_per_day||flowMap[r.resource_id]?.local_consumption_per_day||flowMap[r.resource_id]?.inbound_in_transit_t||flowMap[r.resource_id]?.arrival_waiting_t).map((r)=>{const f=flowMap[r.resource_id]||{};return `<tr class="selectable" data-inspect="resource" data-id="${esc(r.resource_id)}"><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.storage_class)}</div></td><td>${fmt(r.amount)}</td><td>${fmt(r.available)}</td><td>${signed(f.local_net_per_day)}</td><td>${fmt(f.inbound_in_transit_t)}</td><td>${fmt(f.outbound_in_transit_t)}</td><td>${fmt(f.arrival_waiting_t)}</td><td>${fmt(r.free_capacity)}</td></tr>`;}).join('');
    return `<section class="card"><div class="card-heading"><h3>在庫・ローカルフロー・物流状態</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>在庫</th><th>利用可</th><th>Local net/日</th><th>入荷中</th><th>出荷中</th><th>到着待機</th><th>空容量</th></tr></thead><tbody>${rows||'<tr><td colspan="8">表示対象なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderConstructionTab(){
    const projects=state.projects?.items||[],options=state.buildOptions?.items||[];
    const pRows=projects.map((p)=>{const target=p.target_kind==='facility_upgrade'?`Upgrade → Lv ${fmt(p.target_level,0)}`:'新規建設';return `<tr class="selectable" data-inspect="project" data-id="${esc(p.id)}"><td><div class="cell-main">${esc(p.display_name||p.facility_display_name||p.id)}</div><div class="cell-sub">${esc(target)} · ${esc(p.id)}</div></td><td>${esc(stateLabels[p.status]||p.status||(p.paused?'paused':'active'))}</td><td>${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}</td><td>${p.priority??'—'}</td><td>${(p.blockers||[]).length}</td></tr>`;}).join('');
    const optionCards=options.map((o)=>{const blocked=(o.missing_technologies?.length||0)+(o.site_blockers?.length||0);return `<div class="route-mode-card"><div class="mode-title"><span>${esc(o.display_name)}</span><span class="badge ${blocked?'warn':'ok'}">${blocked?`${blocked} blocker`:'建設可'}</span></div><div class="cell-sub">工数 ${fmt(o.construction_required,0)} · 部材 ${o.components?.length||0}種</div><div class="action-row" style="margin-top:8px"><button type="button" data-build="${esc(o.facility_definition_id)}" ${blocked?'disabled':''}>建設計画</button><button type="button" data-inspect="build-option" data-id="${esc(o.facility_definition_id)}">詳細</button></div></div>`;}).join('');
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>建設案件</h3><span class="badge">${projects.length}</span></div><div class="table-wrap"><table><thead><tr><th>案件</th><th>状態</th><th>進捗</th><th>優先</th><th>blocker</th></tr></thead><tbody>${pRows||'<tr><td colspan="5">進行中案件なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>新規建設</h3><span class="badge">${options.length}</span></div><div class="card-body">${optionCards}</div></section></div>`;
  }

  function researchBlockers(r){if(r.status==='prototype')return r.prototype_blockers||[];if(r.status==='demonstration')return r.demonstration_blockers||[];return r.start_blockers||[];}
  function renderResearchTab(){if(!window.SpaceIdleResearchTree)return '<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="empty-state">技術ツリー描画機構を読み込めませんでした。</div></section>';return window.SpaceIdleResearchTree.render(state.research||{items:[],providers:[]});}

  function renderSurveyTab(){const rows=(state.surveys?.items||[]).map((s)=>`<tr class="selectable" data-inspect="survey" data-id="${esc(s.resource_id)}"><td><div class="cell-main">${esc(s.resource_name)}</div><div class="cell-sub">知識Lv ${s.knowledge_level}</div></td><td>${s.active?(s.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">探査中</span>'):'<span class="badge">未開始</span>'}</td><td>${pct(s.progress)}</td><td>${fmt(s.capacity_points_per_day,2)}</td><td>${s.presence_probability==null?'—':pct(s.presence_probability)}</td><td>${s.visible_reserve_t==null?'—':fmt(s.visible_reserve_t)}</td></tr>`).join('');return `<section class="card"><div class="card-heading"><h3>地点探査</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>状態</th><th>進捗</th><th>能力/日</th><th>存在確率</th><th>推定埋蔵量</th></tr></thead><tbody>${rows||'<tr><td colspan="6">この地点に探査対象なし</td></tr>'}</tbody></table></div></section>`;}
  function renderContractsTab(){const rows=(state.contracts?.items||[]).map((c)=>`<tr class="selectable" data-inspect="contract" data-id="${esc(c.id)}"><td><div class="cell-main">${esc(c.display_name)}</div><div class="cell-sub">${c.kind==='cargo'?'貨物契約':'能力契約'}</div></td><td>${esc(stateLabels[c.status]||c.status)}</td><td>Day ${c.deadline_day}</td><td>${fmt(c.reward_musd)} M$</td><td>${(c.blockers||[]).length}</td></tr>`).join('');return `<section class="card"><div class="card-heading"><h3>契約</h3></div><div class="table-wrap"><table><thead><tr><th>契約</th><th>状態</th><th>期限</th><th>報酬</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="5">契約なし</td></tr>'}</tbody></table></div></section>`;}

  function selectInspector(type,id){state.inspector={type,id};renderInspector();$$('#operationsTabContent tr').forEach((tr)=>tr.classList.toggle('is-selected',tr.dataset.id===id));}
  function renderInspector(){const title=$('#inspectorTitle'),content=$('#inspectorContent');if(!state.inspector){title.textContent='選択項目';content.innerHTML='<div class="empty-state">中央の項目を選択すると、状態・条件・操作をここに表示します。</div>';return;}const {type,id}=state.inspector;if(type==='facility')return renderFacilityInspector(id);if(type==='resource')return renderResourceInspector(id);if(type==='project')return renderProjectInspector(id);if(type==='build-option')return renderBuildOptionInspector(id);if(type==='research')return renderResearchInspector(id);if(type==='survey')return renderSurveyInspector(id);if(type==='contract')return renderContractInspector(id);}
  function setInspector(titleText,html){$('#inspectorTitle').textContent=titleText;$('#inspectorContent').innerHTML=html;}
  function section(title,body){return `<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;}
  function kv(rows){return `<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;}
  function componentCards(components){return (components||[]).map((c)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(c.component_id.replaceAll('_',' '))}</span><span>${fmt(c.required_t)} t</span></div><div class="cell-sub">標準材: ${esc(resourceName(c.import_resource_id))}${(c.local_substitutions||[]).length?` · 現地代替: ${(c.local_substitutions||[]).map(([r,f])=>`${esc(resourceName(r))} ${pct(f)}`).join(' / ')}`:''}</div></div>`).join('')||'<div class="empty-state">追加部材なし</div>';}

  function renderFacilityInspector(id){
    const f=state.location?.facilities.find((x)=>x.id===id);if(!f)return;
    const blockers=f.activation_blockers||[];
    const researchRows=f.research_tier==null?[]:[['Research Tier',fmt(f.research_tier,0)],['RP生成',`${fmt(f.research_generation_points_per_day,2)}/日`],['RP貯蔵',fmt(f.research_storage_capacity_points,1)]];
    const u=f.next_upgrade;
    let upgradeSection='';
    if(u){
      const upgradeBlockers=[...(u.missing_technologies||[]).map((x)=>['technology',x]),...(u.site_blockers||[])];
      const active=u.active_project_id?`<div class="issue"><div class="issue-title">Upgrade案件 ${esc(u.active_project_id)} が進行中</div></div>`:'';
      const blocked=upgradeBlockers.length||Boolean(u.active_project_id);
      upgradeSection=section(`次のUpgrade · Lv ${fmt(u.target_level,0)}`,kv([['必要工数',fmt(u.construction_required,0)],['既存案件',u.active_project_id?esc(u.active_project_id):'なし']])+componentCards(u.components)+`<div class="issue-stack">${active}${upgradeBlockers.map(issueHtml).join('')}</div>`+`<button type="button" class="primary" data-upgrade="${esc(f.id)}" ${blocked?'disabled':''}>Lv ${fmt(u.target_level,0)} Upgrade案件を作成</button>`);
    } else {
      upgradeSection=section('次のUpgrade','<div class="empty-state">現在定義されている次LevelのUpgradeはありません。</div>');
    }
    setInspector(f.display_name,section('状態',kv([['ID',esc(f.id)],['定義',esc(f.definition_id)],['Level',fmt(f.level,0)],['運転',f.paused?'手動停止':'稼働'],['電力利用率',pct(f.power_utilization)],['電力優先度',esc(f.power_priority??'—')],...researchRows]))+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<div class="badge ok">なし</div>')+upgradeSection+section('運用操作',`<div class="action-stack"><button type="button" data-command="${f.paused?'ResumeFacility':'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused?'設備を再開':'設備を停止'}</button><div class="form-row"><label>電力優先度<input id="facilityPriorityInput" type="number" step="1" value="${f.power_priority??50}"></label><button type="button" data-set-power-priority="${esc(f.id)}">優先度を適用</button></div></div>`));
  }
  function renderResourceInspector(id){const inv=state.location?.inventory.find((x)=>x.resource_id===id),f=state.flow?.resources.find((x)=>x.resource_id===id);if(!inv)return;setInspector(inv.display_name,section('在庫',kv([['在庫',fmt(inv.amount)],['予約',fmt(inv.reserved)],['利用可能',fmt(inv.available)],['空容量',fmt(inv.free_capacity)],['Storage',esc(inv.storage_class)]]))+section('フロー',kv([['生産/日',signed(f?.local_production_per_day)],['消費/日',signed(f?.local_consumption_per_day)],['Local net/日',signed(f?.local_net_per_day)],['入荷中',fmt(f?.inbound_in_transit_t)],['出荷中',fmt(f?.outbound_in_transit_t)],['到着待機',fmt(f?.arrival_waiting_t)]])));}
  function renderProjectInspector(id){
    const p=state.projects?.items.find((x)=>x.id===id);if(!p)return;
    const target=p.target_kind==='facility_upgrade'?`Facility Upgrade → Lv ${fmt(p.target_level,0)}`:'新規施設建設';
    const targetRows=[['ID',esc(p.id)],['種別',esc(target)],['状態',esc(stateLabels[p.status]||p.status||(p.paused?'paused':'active'))],['優先度',esc(p.priority??'—')],['工数',`${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}`]];
    if(p.target_facility_id)targetRows.push(['対象設備',esc(p.target_facility_id)]);
    if(p.completed_facility_id)targetRows.push(['反映設備',esc(p.completed_facility_id)]);
    const componentRows=(p.components||[]).map((c)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(c.component_id.replaceAll('_',' '))}</span><span>${fmt(c.required_t)} t</span></div><div class="cell-sub">現地予約 ${fmt(c.reserved_local_t)} t · 到着済予約 ${fmt(c.reserved_import_t)} t · 投入済 ${fmt((c.committed_local_t||0)+(c.committed_import_t||0))} t</div></div>`).join('');
    setInspector(p.display_name||p.facility_display_name||p.id,section('案件',kv(targetRows))+section('必要部材 / 調達',componentRows||'<div class="empty-state">追加部材なし</div>')+section('Blocker',(p.blockers||[]).length?`<div class="issue-stack">${p.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',`<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}" ${['complete','cancelled'].includes(p.status)?'disabled':''}>${p.paused?'建設再開':'建設停止'}</button><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}" ${['complete','cancelled'].includes(p.status)?'disabled':''}>案件取消</button></div>`));
  }
  function renderBuildOptionInspector(id){const o=state.buildOptions?.items.find((x)=>x.facility_definition_id===id);if(!o)return;const blockers=[...(o.missing_technologies||[]).map((x)=>['technology',x]),...(o.site_blockers||[])];setInspector(o.display_name,section('建設',kv([['必要工数',fmt(o.construction_required,0)],['自己展開',o.self_deploying?'はい':'いいえ']]))+section('必要部材',componentCards(o.components))+section('Blocker',blockers.length?blockers.map(issueHtml).join(''):'<span class="badge ok">なし</span>')+section('操作',`<button type="button" class="primary" data-build="${esc(o.facility_definition_id)}" ${blockers.length?'disabled':''}>この地点に建設</button>`));}

  function siteOptionsHtml(r,kind){const options=kind==='prototype'?(r.prototype_sites||[]):(r.demonstration_sites||[]);if(!options.length)return '<div class="empty-state">候補地点なし</div>';return options.map((site)=>{const blocked=(site.blockers||[]).length;const attr=kind==='prototype'?'data-research-prototype-site':'data-research-demo-site';return `<div class="route-mode-card"><div class="mode-title"><span>${esc(locationName(site.location_id))}</span><span class="badge ${blocked?'warn':'ok'}">${blocked?`${blocked} blocker`:'実行可'}</span></div>${blocked?`<div class="issue-stack">${site.blockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:''}<button type="button" ${attr}="${esc(site.location_id)}" data-id="${esc(r.id)}" ${blocked?'disabled':''}>${kind==='prototype'?'この地点で試作':'この地点で実証'}</button></div>`;}).join('');}

  function renderResearchInspector(id){
    const r=state.research?.items.find((x)=>x.id===id);if(!r)return;
    const canPause=!['available','locked','complete'].includes(r.status);let action='';
    if(r.status==='available'&&r.can_start)action=`<button type="button" class="primary" data-research-action="start" data-id="${esc(r.id)}">RP ${fmt(r.research_point_cost,1)} を支払い研究開始</button>`;
    else if(r.paused)action=`<button type="button" data-research-action="resume" data-id="${esc(r.id)}">研究再開</button>`;
    else if(canPause)action=`<button type="button" data-research-action="pause" data-id="${esc(r.id)}">研究停止</button>`;
    const phaseBlockers=researchBlockers(r);let phaseAction='';
    if(r.status==='prototype'){const resources=(r.prototype_resources||[]).map(([resource,amount])=>`${esc(resourceName(resource))} ${fmt(amount)}t`).join(' / ')||'追加資材なし';phaseAction=section('試作',`<div class="cell-sub">必要資材: ${resources}</div>${siteOptionsHtml(r,'prototype')}`);}
    else if(r.status==='demonstration')phaseAction=section('実証',`<div class="cell-sub">進捗 ${r.demonstration_done_days}/${r.demonstration_required_days}日</div>${siteOptionsHtml(r,'demonstration')}`);
    const startState=r.status==='available'||r.status==='locked'?section('開始条件',kv([['必要RP',fmt(r.research_point_cost,1)],['保有RP',fmt(state.research?.stored_points,1)],['RP容量',fmt(state.research?.storage_capacity_points,1)]])):'';
    setInspector(r.display_name,section('状態',kv([['段階',esc(stateLabels[r.status]||r.status)],['必要RP',fmt(r.research_point_cost,1)],['実証日数',`${r.demonstration_done_days}/${r.demonstration_required_days}`]]))+section('前提',(r.prerequisites||[]).length?(r.prerequisites||[]).map((x)=>`<span class="badge">${esc(definitionName(x))}</span>`).join(' '):'<span class="badge ok">なし</span>')+startState+section('現在のblocker',phaseBlockers.length?`<div class="issue-stack">${phaseBlockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:'<span class="badge ok">なし</span>')+phaseAction+section('操作',`<div class="action-stack">${action||'<span class="badge">現在可能な操作なし</span>'}</div>`));
  }

  function renderSurveyInspector(id){const s=state.surveys?.items.find((x)=>x.resource_id===id);if(!s)return;const action=s.active?(s.paused?`<button data-survey-action="resume" data-id="${esc(id)}">探査再開</button>`:`<button data-survey-action="pause" data-id="${esc(id)}">探査停止</button>`):`<button class="primary" data-survey-action="start" data-id="${esc(id)}">探査開始</button>`;setInspector(s.resource_name,section('探査状態',kv([['進捗',pct(s.progress)],['知識レベル',String(s.knowledge_level)],['能力/日',fmt(s.capacity_points_per_day,2)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['推定埋蔵量',s.visible_reserve_t==null?'—':`${fmt(s.visible_reserve_t)} t`]]))+section('操作',`<div class="action-stack">${action}<div class="form-row"><label>探査配分<input id="surveyWeightInput" type="number" min="0" step="0.1" value="${s.allocation_weight||1}"></label><button data-set-survey-weight="${esc(id)}">配分を適用</button></div></div>`));}
  function renderContractInspector(id){const c=state.contracts?.items.find((x)=>x.id===id);if(!c)return;const linked=c.cargo_order_id?(state.orders?.items||[]).find((o)=>o.id===c.cargo_order_id):null;let actions='<span class="badge">処理済み</span>';if(c.status==='offered')actions=`<div class="action-row"><button class="primary" data-contract-action="accept" data-id="${esc(c.id)}">受諾</button><button class="danger-button" data-contract-action="decline" data-id="${esc(c.id)}">辞退</button></div>`;else if(c.status==='accepted'&&c.kind==='cargo'&&!c.cargo_order_id)actions=`<button class="primary" data-contract-dispatch="${esc(c.id)}">契約貨物の輸送計画</button>`;const cargoState=c.kind==='cargo'?section('契約貨物',linked?kv([['輸送状態',esc(stateLabels[linked.status]||linked.status)],['配送済み',`${fmt(linked.delivered_t)}/${fmt(linked.amount_t)} t`],['輸送待ち',`${fmt(linked.waiting_t)} t`],['輸送中',`${fmt(linked.in_transit_t)} t`]]):'<div class="empty-state">輸送未設定</div>'):'';setInspector(c.display_name,section('契約',kv([['種別',c.kind==='cargo'?'貨物契約':'能力契約'],['状態',esc(stateLabels[c.status]||c.status)],['期限',`Day ${c.deadline_day}`],['報酬',`${fmt(c.reward_musd)} M$`],['出発地',esc(locationName(c.source_id))],['到着地',esc(locationName(c.destination_id))],['貨物',c.resource_id?`${esc(resourceName(c.resource_id))} ${fmt(c.cargo_t)}t`:'—']]))+cargoState+section('Blocker',(c.blockers||[]).length?`<div class="issue-stack">${c.blockers.map((x)=>issueHtml(['contract',x])).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',actions));}

  function renderLogistics(){if(!state.logisticsSummary||!state.routes)return;const s=state.logisticsSummary;$('#logisticsSummary').innerHTML=[['輸送路',`${s.usable_route_count}/${s.route_count}`],['輸送機',`${s.available_vehicle_count}/${s.vehicle_count}`],['輸送待ち',`${fmt(s.waiting_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');renderRouteFilters();renderRouteList();renderNetwork();renderVehicles();renderCargo();renderRouteInspector();}
  function renderRouteFilters(){const locs=state.world?.locations||[];for(const [selId,label] of [['#routeOriginFilter','全出発地'],['#routeDestinationFilter','全到着地']]){const sel=$(selId),current=sel.value;sel.innerHTML=`<option value="">${label}</option>`+locs.map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');if([...sel.options].some((o)=>o.value===current))sel.value=current;}}
  function filteredRoutes(){const origin=$('#routeOriginFilter')?.value||'',dest=$('#routeDestinationFilter')?.value||'';return (state.routes?.items||[]).filter((r)=>(!origin||r.origin_id===origin)&&(!dest||r.destination_id===dest));}
  function renderRouteList(){$('#routeList').innerHTML=filteredRoutes().map((r)=>`<button type="button" class="route-button ${r.id===state.selectedRouteId?'is-selected':''}" data-route-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="route-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.usable_now?'ok':r.available?'warn':''}">${r.usable_now?'利用可':r.available?'設備待ち':'利用不可'}</span></div></button>`).join('')||'<div class="empty-state">条件に一致するRouteなし</div>';}

  const nodePositions={'base.node.earth_surface':[12,50],'base.node.low_earth_orbit':[34,50],'base.node.lunar_orbit':[60,50],'base.node.south_polar_ridge':[84,22],'base.node.polar_cold_trap':[84,50],'base.node.nearside_mare':[84,78]};
  function renderNetwork(){const svg=$('#networkSvg'),nodes=$('#networkNodes'),routes=state.routes?.items||[];svg.innerHTML=routes.map((r)=>{const a=nodePositions[r.origin_id],b=nodePositions[r.destination_id];if(!a||!b)return'';return `<line x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}" class="network-line ${r.usable_now?'available':''} ${r.id===state.selectedRouteId?'selected':''}" data-route-line="${esc(r.id)}" />`;}).join('');nodes.innerHTML=(state.world?.locations||[]).map((loc)=>{const p=nodePositions[loc.id]||[50,50];return `<div class="network-node" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`;}).join('');}
  function renderVehicles(){const items=state.vehicles?.items||[];$('#vehicleCountBadge').textContent=`${items.length}機`;const rows=items.map((v)=>`<tr><td><div class="cell-main">${esc(v.display_name)}</div><div class="cell-sub">${esc(v.id)}</div></td><td>${esc(locationName(v.location_id))}</td><td>${esc(stateLabels[v.status]||v.status)}</td><td>${fmt(v.propellant_t)}/${fmt(v.propellant_capacity_t)}</td><td>${fmt(v.payload_t)}t</td><td>${(v.blockers||[]).length}</td></tr>`).join('');$('#vehicleTable').innerHTML=`<table><thead><tr><th>機体</th><th>現在地</th><th>状態</th><th>推進剤</th><th>Payload</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="6">輸送資産なし</td></tr>'}</tbody></table>`;}
  function renderCargo(){const items=(state.orders?.items||[]).filter((o)=>o.owner_kind!=='contract');$('#cargoCountBadge').textContent=`${items.length}件`;const rows=items.map((o)=>`<tr><td>${esc(resourceName(o.resource_id))}<div class="cell-sub">${o.owner_kind==='logistics_rule'?'定期物流':'手動輸送'} · ${esc(o.id)}</div></td><td>${esc(locationName(o.source_id))} → ${esc(locationName(o.destination_id))}</td><td>${fmt(o.delivered_t)}/${fmt(o.amount_t)}t</td><td>${esc(stateLabels[o.status]||o.status)}</td><td>${(o.blockers||[]).length}</td></tr>`).join('');$('#cargoTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newCargoButton">資源輸送を設定</button></div><table><thead><tr><th>資源</th><th>区間</th><th>配送済み/総量</th><th>状態</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="5">資源輸送なし</td></tr>'}</tbody></table>`;}
  function renderRouteInspector(){const title=$('#routeInspectorTitle'),content=$('#routeInspectorContent');if(!state.selectedRouteId){title.textContent='輸送路を選択';content.innerHTML='<div class="empty-state">左の輸送路またはネットワーク上の接続を選択してください。</div>';return;}const route=(state.routes?.items||[]).find((r)=>r.id===state.selectedRouteId);if(!route)return;title.textContent=route.display_name;const blockers=[...new Map([...(route.blockers||[]),...(route.operational_blockers||[])].map((x)=>[JSON.stringify(x),x])).values()];const modes=(route.modes||[]).map((m)=>`<div class="route-mode-card ${m.usable_now?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name)}</span><span class="badge ${m.usable_now?'ok':'warn'}">${m.usable_now?'利用可':'利用不可'}</span></div><div class="cell-sub">${m.kind==='external_service'?'外部サービス':`ヴィークル · ${m.available_vehicle_count}機利用可`} · ${fmt(m.transit_days)}日 · ${fmt(m.dispatch_capacity_t)}t</div>${(m.blockers||[]).length?`<div class="issue-stack" style="margin-top:7px">${m.blockers.map(issueHtml).join('')}</div>`:''}</div>`).join('');content.innerHTML=section('区間',kv([['出発',esc(locationName(route.origin_id))],['到着',esc(locationName(route.destination_id))],['物理条件',route.available?'成立':'不成立'],['現在利用',route.usable_now?'はい':'いいえ'],['基準日数',fmt(route.transit_days)],['Δv',`${fmt(route.delta_v_km_s,2)} km/s`],['Dispatch能力',`${fmt(route.dispatch_capacity_t)} t`]]))+section('Operation',(route.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o)?o[0]:o))}</span>`).join(' ')||'—')+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('輸送方式 / ヴィークル',modes||'<div class="empty-state">方式情報なし</div>')+section('操作','<button type="button" class="primary" id="routeCargoButton">この区間を基準に資源輸送</button>');}

  function populateStaticSelects(){const locOpts=(state.world?.locations||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');$('#cargoSource').innerHTML=locOpts;$('#cargoDestination').innerHTML=locOpts;$('#cargoResource').innerHTML=(state.catalog?.resources||[]).map((r)=>`<option value="${esc(r.id)}">${esc(r.display_name)}</option>`).join('');}
  function modeLabel(mode){return mode.kind==='external_service'?`外部サービス: ${mode.display_name}`:`ヴィークル: ${mode.display_name} (${mode.available_vehicle_count}機利用可)`;}
  async function loadCargoPlans(){const source=$('#cargoSource').value,destination=$('#cargoDestination').value,planSelect=$('#cargoPlan'),legs=$('#cargoLegChoices');if(!source||!destination||source===destination){state.cargoPlans=null;planSelect.innerHTML='<option value="">出発地と到着地を指定</option>';legs.innerHTML='';return;}const plans=await api(`/api/v1/transport-plans?source_id=${encodeURIComponent(source)}&destination_id=${encodeURIComponent(destination)}`);state.cargoPlans=plans;const options=plans?.options||[];planSelect.innerHTML=options.map((p,i)=>`<option value="${i}">${esc((p.path||[]).map((routeId)=>definitionName(routeId)).join(' → '))} · ${fmt(p.transit_days)}日 · ${fmt(p.estimated_cost_musd_per_t,2)} M$/t</option>`).join('')||'<option value="">現在実行可能な輸送計画なし</option>';const policy=$('#cargoPolicy').value,preferred=options.findIndex((p)=>p.policy===policy);if(preferred>=0)planSelect.value=String(preferred);renderCargoLegChoices();}
  function renderCargoLegChoices(){const options=state.cargoPlans?.options||[],plan=options[Number($('#cargoPlan').value||0)];if(!plan){$('#cargoLegChoices').innerHTML='<div class="empty-state">実行可能な輸送計画がありません。</div>';return;}const defaults=Object.fromEntries(plan.route_modes||[]);$('#cargoLegChoices').innerHTML=(plan.path||[]).map((routeId,index)=>{const route=(state.routes?.items||[]).find((r)=>r.id===routeId);if(!route)return'';const modes=route.modes||[],opts=modes.map((m)=>`<option value="${esc(m.id)}" ${m.id===defaults[routeId]?'selected':''} ${!m.usable_now?'disabled':''}>${esc(modeLabel(m))}${m.usable_now?'':' — 利用不可'}</option>`).join('');return `<div class="route-mode-card"><div class="mode-title"><span>Leg ${index+1}: ${esc(route.display_name)}</span></div><label>輸送方式 / ヴィークル<select data-cargo-route-mode="${esc(routeId)}">${opts}</select></label></div>`;}).join('');}
  async function openCargoDialog(route=null,contract=null){state.cargoContractId=contract?.id||null;$('#cargoDialogTitle').textContent=contract?'契約貨物の輸送計画':'資源輸送を設定';$('#cargoSubmitButton').textContent=contract?'契約輸送を開始':'輸送登録';for(const id of ['cargoSource','cargoDestination','cargoResource','cargoAmount'])$('#'+id).disabled=Boolean(contract);if(contract){$('#cargoSource').value=contract.source_id;$('#cargoDestination').value=contract.destination_id;$('#cargoResource').value=contract.resource_id;$('#cargoAmount').value=contract.cargo_t;}else if(route){$('#cargoSource').value=route.origin_id;$('#cargoDestination').value=route.destination_id;}$('#cargoDialog').showModal();try{await loadCargoPlans();}catch(e){banner(e.message,'error');}}
  function renderAll(){renderHeader();renderLocations();renderGlobalIssues();if(state.activeView==='operations')renderOperations();else renderLogistics();}

  document.addEventListener('click',async(event)=>{
    const viewBtn=event.target.closest('[data-view]');if(viewBtn){state.activeView=viewBtn.dataset.view;$$('.view-button').forEach((b)=>b.classList.toggle('is-active',b===viewBtn));$('#operationsView').hidden=state.activeView!=='operations';$('#logisticsView').hidden=state.activeView!=='logistics';renderAll();return;}
    const locBtn=event.target.closest('[data-location-id]');if(locBtn){await loadLocation(locBtn.dataset.locationId);return;}
    const tab=event.target.closest('[data-tab]');if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;renderOperations();return;}
    const inspect=event.target.closest('[data-inspect]');if(inspect){selectInspector(inspect.dataset.inspect,inspect.dataset.id);return;}
    const pause=event.target.closest('#timePauseButton');if(pause){try{await setTimeControl({paused:!Boolean(state.session?.time_paused)});}catch(e){banner(e.message,'error');}return;}
    const speed=event.target.closest('[data-time-speed]');if(speed){try{await setTimeControl({speed_multiplier:Number(speed.dataset.timeSpeed)});}catch(e){banner(e.message,'error');}return;}
    const build=event.target.closest('[data-build]');if(build){try{await command('PlanBuild',{location_id:state.locationId,facility_id:build.dataset.build,priority:50,sourcing_policy:'mixed',import_source_id:null});banner('建設計画を作成しました');}catch{}return;}
    const upgrade=event.target.closest('[data-upgrade]');if(upgrade){try{const result=await command('PlanFacilityUpgrade',{facility_id:upgrade.dataset.upgrade,priority:50,sourcing_policy:'mixed',import_source_id:null});banner(`Upgrade案件 ${result?.created_id||''} を作成しました`);}catch{}return;}
    const routeBtn=event.target.closest('[data-route-id]');if(routeBtn){state.selectedRouteId=routeBtn.dataset.routeId;renderLogistics();return;}
    const routeLine=event.target.closest('[data-route-line]');if(routeLine){state.selectedRouteId=routeLine.dataset.routeLine;renderLogistics();return;}
    if(event.target.closest('#newCargoButton')){await openCargoDialog();return;}
    if(event.target.closest('#routeCargoButton')){await openCargoDialog((state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId));return;}
    const contractDispatch=event.target.closest('[data-contract-dispatch]');if(contractDispatch){const c=(state.contracts?.items||[]).find((x)=>x.id===contractDispatch.dataset.contractDispatch);if(c)await openCargoDialog(null,c);return;}
    const cmd=event.target.closest('[data-command]');if(cmd){let payload={};if(cmd.dataset.facilityId)payload.facility_id=cmd.dataset.facilityId;if(cmd.dataset.projectId)payload.project_id=cmd.dataset.projectId;try{await command(cmd.dataset.command,payload);}catch{}return;}
    const pp=event.target.closest('[data-set-power-priority]');if(pp){try{await command('SetPowerPriority',{facility_id:pp.dataset.setPowerPriority,priority:Number($('#facilityPriorityInput').value)});}catch{}return;}
    const ra=event.target.closest('[data-research-action]');if(ra){const map={start:'StartResearch',pause:'PauseResearch',resume:'ResumeResearch'};try{await command(map[ra.dataset.researchAction],{research_id:ra.dataset.id});}catch{}return;}
    const proto=event.target.closest('[data-research-prototype-site]');if(proto){try{await command('FundResearchPrototype',{research_id:proto.dataset.id,location_id:proto.dataset.researchPrototypeSite});}catch{}return;}
    const demo=event.target.closest('[data-research-demo-site]');if(demo){try{await command('SetResearchDemonstrationSite',{research_id:demo.dataset.id,location_id:demo.dataset.researchDemoSite});}catch{}return;}
    const sa=event.target.closest('[data-survey-action]');if(sa){const map={start:'StartSurvey',pause:'PauseSurvey',resume:'ResumeSurvey'},payload={location_id:state.locationId,resource_id:sa.dataset.id};if(sa.dataset.surveyAction==='start')payload.allocation_weight=1;try{await command(map[sa.dataset.surveyAction],payload);}catch{}return;}
    const sw=event.target.closest('[data-set-survey-weight]');if(sw){try{await command('SetSurveyAllocation',{location_id:state.locationId,resource_id:sw.dataset.setSurveyWeight,weight:Number($('#surveyWeightInput').value)});}catch{}return;}
    const ca=event.target.closest('[data-contract-action]');if(ca){try{await command(ca.dataset.contractAction==='accept'?'AcceptContract':'DeclineContract',{contract_id:ca.dataset.id});}catch{}return;}
    if(event.target.closest('#refreshButton')){try{await loadUiSnapshot();banner('最新状態を取得しました');}catch(e){banner(e.message,'error');}return;}
  });

  $('#routeOriginFilter').addEventListener('change',renderRouteList);$('#routeDestinationFilter').addEventListener('change',renderRouteList);
  $('#cargoSource').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoDestination').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoPolicy').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoPlan').addEventListener('change',renderCargoLegChoices);
  $('#saveButton').addEventListener('click',async()=>{if(!await beginMutation())return;try{await api('/api/v1/session/save',{method:'POST',body:JSON.stringify({slot:'manual'})});banner('manual スロットへ保存しました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
  $('#loadButton').addEventListener('click',async()=>{if(!await beginMutation())return;try{await api('/api/v1/session/load',{method:'POST',body:JSON.stringify({slot:'manual',apply_offline:true})});await loadUiSnapshot({preserveInteraction:false});banner('manual スロットを読み込みました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
  $('#cargoCloseButton').addEventListener('click',()=>$('#cargoDialog').close());$('#cargoCancelButton').addEventListener('click',()=>$('#cargoDialog').close());
  $('#cargoForm').addEventListener('submit',async(event)=>{event.preventDefault();const options=state.cargoPlans?.options||[],plan=options[Number($('#cargoPlan').value||0)];if(!plan){banner('実行可能な輸送計画を選択してください','error');return;}const routeModes=$$('[data-cargo-route-mode]').map((sel)=>[sel.dataset.cargoRouteMode,sel.value]);try{if(state.cargoContractId)await command('DispatchContractCargo',{contract_id:state.cargoContractId,path:plan.path,route_modes:routeModes});else await command('SubmitCargo',{source_id:$('#cargoSource').value,destination_id:$('#cargoDestination').value,resource_id:$('#cargoResource').value,amount_t:Number($('#cargoAmount').value),priority:Number($('#cargoPriority').value),path:plan.path,route_modes:routeModes,path_policy:$('#cargoPolicy').value});$('#cargoDialog').close();state.cargoContractId=null;banner('輸送を登録しました');}catch{}});

  window.addEventListener('online',()=>setConnection('ok','PC Server'));window.addEventListener('offline',()=>setConnection('error','オフライン'));
  window.setInterval(()=>{if(document.hidden||state.busy||$('#app')?.getAttribute('aria-busy')!=='false')return;loadUiSnapshot().catch((err)=>{setConnection('error','同期失敗');console.error(err);});},1000);
  initialLoad().catch((err)=>{setConnection('error','接続失敗');banner(`Serverへ接続できません: ${err.message}`,'error',0);$('#app').setAttribute('aria-busy','false');});
})();
