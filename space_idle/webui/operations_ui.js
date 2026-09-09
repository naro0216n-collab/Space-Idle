(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before operations_ui.js');
  const {state,$,$$,esc,fmt,pct,resourceName,locationName,definitionName,capabilityName,storageClassLabels,stateLabels,issueHtml,statHtml,signed,command,banner}=A;

  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const setInspector=(title,html)=>{$('#inspectorTitle').textContent=title;$('#inspectorContent').innerHTML=html;};
  const componentCards=(components)=>(components||[]).map((c)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(c.component_id.replaceAll('_',' '))}</span><span>${fmt(c.required_t)} t</span></div><div class="cell-sub">標準材: ${esc(resourceName(c.import_resource_id))}${(c.local_substitutions||[]).length?` · 現地代替: ${(c.local_substitutions||[]).map(([r,f])=>`${esc(resourceName(r))} ${pct(f)}`).join(' / ')}`:''}</div></div>`).join('')||'<div class="empty-state">追加部材なし</div>';

  function renderOverviewTab(){
    const loc=state.location,flow=state.flow,issues=state.bottlenecks?.items||[];
    const storageRows=(loc.storage||[]).map((s)=>`<tr><td>${esc(storageClassLabels[s.storage_class]||s.storage_class)}</td><td>${fmt(s.stock_t)}</td><td>${fmt(s.service_capacity_t)}</td><td>${fmt(s.free_service_t)}</td><td>${fmt(s.unserviced_occupied_t)}</td></tr>`).join('');
    const capabilityRows=(loc.capabilities||[]).filter((c)=>c.infrastructure_capacity||c.active_capacity||c.available_capacity).map((c)=>`<tr><td>${esc(capabilityName(c.id))}</td><td>${fmt(c.infrastructure_capacity)}</td><td>${fmt(c.active_capacity)}</td><td>${fmt(c.available_capacity)}</td></tr>`).join('');
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>運用状態</h3></div><div class="card-body"><div class="stat-grid">${statHtml('電力利用率',pct(flow?.power_utilization))}${statHtml('利用可能電力',`${fmt(loc.power_allocated_mw)} MW`)}${statHtml('建設能力',`${fmt(loc.construction_capacity_per_day)} /日`)}${statHtml('進行中建設',`${loc.projects?.length||0}`)}</div></div></section><section class="card"><div class="card-heading"><h3>地点blocker</h3><span class="badge ${issues.length?'warn':'ok'}">${issues.length} 件</span></div><div class="card-body issue-stack">${issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state">現在のblockerはありません。</div>'}</div></section><section class="card"><div class="card-heading"><h3>保管サービス</h3></div><div class="table-wrap"><table><thead><tr><th>Class</th><th>在庫t</th><th>Service</th><th>空き</th><th>未service</th></tr></thead><tbody>${storageRows||'<tr><td colspan="5">保管設備なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>能力</h3></div><div class="table-wrap"><table><thead><tr><th>能力</th><th>インフラ</th><th>稼働</th><th>利用可能</th></tr></thead><tbody>${capabilityRows||'<tr><td colspan="4">Capabilityなし</td></tr>'}</tbody></table></div></section></div>`;
  }

  function renderFacilitiesTab(){
    const rows=(state.location?.facilities||[]).map((f)=>{const u=f.next_upgrade;const upgrade=u?(u.active_project_id?`案件 ${esc(u.active_project_id)}`:`→ Lv ${fmt(u.target_level,0)}`):'—';return `<tr class="selectable" data-inspect="facility" data-id="${esc(f.id)}"><td><div class="cell-main">${esc(f.display_name)}</div><div class="cell-sub">${esc(f.id)}</div></td><td>Lv ${fmt(f.level,0)}</td><td>${f.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">稼働</span>'}</td><td>${pct(f.power_utilization)}</td><td>${f.power_priority??'—'}</td><td>${upgrade}</td><td>${(f.activation_blockers||[]).length}</td></tr>`;}).join('');
    return `<section class="card"><div class="card-heading"><h3>設備一覧</h3><span class="badge">${state.location?.facilities?.length||0}</span></div><div class="table-wrap"><table><thead><tr><th>設備</th><th>Level</th><th>状態</th><th>電力</th><th>優先度</th><th>Upgrade</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="7">設備なし</td></tr>'}</tbody></table></div></section>`;
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
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>建設案件</h3><span class="badge">${projects.length}</span></div><div class="table-wrap"><table><thead><tr><th>案件</th><th>状態</th><th>進捗</th><th>優先</th><th>blocker</th></tr></thead><tbody>${pRows||'<tr><td colspan="5">進行中案件なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>新規建設</h3><span class="badge">${options.length}</span></div><div class="card-body">${optionCards||'<div class="empty-state">建設候補なし</div>'}</div></section></div>`;
  }

  function renderResearchTab(){
    if(!window.SpaceIdleResearchTree)return '<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="empty-state">技術ツリー描画機構を読み込めませんでした。</div></section>';
    return window.SpaceIdleResearchTree.render(state.research||{items:[],providers:[]});
  }
  function renderSurveyTab(){
    const rows=(state.surveys?.items||[]).map((s)=>`<tr class="selectable" data-inspect="survey" data-id="${esc(s.resource_id)}"><td><div class="cell-main">${esc(s.resource_name)}</div><div class="cell-sub">知識Lv ${s.knowledge_level}</div></td><td>${s.active?(s.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">探査中</span>'):'<span class="badge">未開始</span>'}</td><td>${pct(s.progress)}</td><td>${fmt(s.capacity_points_per_day,2)}</td><td>${s.presence_probability==null?'—':pct(s.presence_probability)}</td><td>${s.visible_reserve_t==null?'—':fmt(s.visible_reserve_t)}</td></tr>`).join('');
    return `<section class="card"><div class="card-heading"><h3>地点探査</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>状態</th><th>進捗</th><th>能力/日</th><th>存在確率</th><th>推定埋蔵量</th></tr></thead><tbody>${rows||'<tr><td colspan="6">この地点に探査対象なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderActiveTab(){
    const renderers={overview:renderOverviewTab,facilities:renderFacilitiesTab,inventory:renderInventoryTab,construction:renderConstructionTab,research:renderResearchTab,survey:renderSurveyTab};
    $('#operationsTabContent').innerHTML=(renderers[state.activeTab]||renderOverviewTab)();
  }

  function renderFacilityInspector(id){
    const f=state.location?.facilities?.find((x)=>x.id===id);if(!f)return false;
    const blockers=f.activation_blockers||[],u=f.next_upgrade;
    const researchRows=f.research_tier==null?[]:[['Research Tier',fmt(f.research_tier,0)],['RP生成',`${fmt(f.research_generation_points_per_day,2)}/日`],['RP貯蔵',fmt(f.research_storage_capacity_points,1)]];
    let upgradeSection='';
    if(u){
      const upgradeBlockers=[...(u.missing_technologies||[]).map((x)=>['technology',x]),...(u.site_blockers||[])];
      const active=u.active_project_id?`<div class="issue"><div class="issue-title">Upgrade案件 ${esc(u.active_project_id)} が進行中</div></div>`:'';
      const blocked=upgradeBlockers.length||Boolean(u.active_project_id);
      upgradeSection=section(`次のUpgrade · Lv ${fmt(u.target_level,0)}`,kv([['必要工数',fmt(u.construction_required,0)],['既存案件',u.active_project_id?esc(u.active_project_id):'なし']])+componentCards(u.components)+`<div class="issue-stack">${active}${upgradeBlockers.map(issueHtml).join('')}</div><button type="button" class="primary" data-upgrade="${esc(f.id)}" ${blocked?'disabled':''}>Lv ${fmt(u.target_level,0)} Upgrade案件を作成</button>`);
    }else upgradeSection=section('次のUpgrade','<div class="empty-state">現在定義されている次LevelのUpgradeはありません。</div>');
    setInspector(f.display_name,section('状態',kv([['ID',esc(f.id)],['定義',esc(f.definition_id)],['Level',fmt(f.level,0)],['運転',f.paused?'手動停止':'稼働'],['電力利用率',pct(f.power_utilization)],['電力優先度',esc(f.power_priority??'—')],...researchRows]))+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<div class="badge ok">なし</div>')+upgradeSection+section('運用操作',`<div class="action-stack"><button type="button" data-command="${f.paused?'ResumeFacility':'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused?'設備を再開':'設備を停止'}</button><div class="form-row"><label>電力優先度<input id="facilityPriorityInput" type="number" step="1" value="${f.power_priority??50}"></label><button type="button" data-set-power-priority="${esc(f.id)}">優先度を適用</button></div></div>`));
    return true;
  }
  function renderResourceInspector(id){
    const inv=state.location?.inventory?.find((x)=>x.resource_id===id),f=state.flow?.resources?.find((x)=>x.resource_id===id);if(!inv)return false;
    setInspector(inv.display_name,section('在庫',kv([['在庫',fmt(inv.amount)],['予約',fmt(inv.reserved)],['利用可能',fmt(inv.available)],['空容量',fmt(inv.free_capacity)],['Storage',esc(inv.storage_class)]]))+section('フロー',kv([['生産/日',signed(f?.local_production_per_day)],['消費/日',signed(f?.local_consumption_per_day)],['Local net/日',signed(f?.local_net_per_day)],['入荷中',fmt(f?.inbound_in_transit_t)],['出荷中',fmt(f?.outbound_in_transit_t)],['到着待機',fmt(f?.arrival_waiting_t)]])));
    return true;
  }
  function renderProjectInspector(id){
    const p=state.projects?.items?.find((x)=>x.id===id);if(!p)return false;
    const target=p.target_kind==='facility_upgrade'?`Facility Upgrade → Lv ${fmt(p.target_level,0)}`:'新規施設建設';
    const targetRows=[['ID',esc(p.id)],['種別',esc(target)],['状態',esc(stateLabels[p.status]||p.status||(p.paused?'paused':'active'))],['優先度',esc(p.priority??'—')],['工数',`${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}`]];
    if(p.target_facility_id)targetRows.push(['対象設備',esc(p.target_facility_id)]);if(p.completed_facility_id)targetRows.push(['反映設備',esc(p.completed_facility_id)]);
    const componentRows=(p.components||[]).map((c)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(c.component_id.replaceAll('_',' '))}</span><span>${fmt(c.required_t)} t</span></div><div class="cell-sub">現地予約 ${fmt(c.reserved_local_t)} t · 到着済予約 ${fmt(c.reserved_import_t)} t · 投入済 ${fmt((c.committed_local_t||0)+(c.committed_import_t||0))} t</div></div>`).join('');
    const demands=(state.demands||[]).filter((d)=>d.owner_kind==='project'&&d.owner_id===p.id);
    const demandHtml=demands.length?demands.map((d)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(resourceName(d.resource_id))}</span><span>${fmt(d.remaining_t)} t 待ち</span></div><div class="cell-sub">${d.source_id?esc(locationName(d.source_id)):'Laneが供給元を選択'} → ${esc(locationName(d.destination_id))} · 輸送系内 ${fmt(d.pipeline_t)} t</div></div>`).join(''):'<div class="empty-state">現在の物流Demandなし</div>';
    setInspector(p.display_name||p.facility_display_name||p.id,section('案件',kv(targetRows))+section('必要部材 / 調達',componentRows||'<div class="empty-state">追加部材なし</div>')+section('物流Demand',demandHtml)+section('Blocker',(p.blockers||[]).length?`<div class="issue-stack">${p.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',`<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}" ${['complete','cancelled'].includes(p.status)?'disabled':''}>${p.paused?'建設再開':'建設停止'}</button><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}" ${['complete','cancelled'].includes(p.status)?'disabled':''}>案件取消</button></div>`));
    return true;
  }
  function renderBuildOptionInspector(id){
    const o=state.buildOptions?.items?.find((x)=>x.facility_definition_id===id);if(!o)return false;
    const blockers=[...(o.missing_technologies||[]).map((x)=>['technology',x]),...(o.site_blockers||[])];
    setInspector(o.display_name,section('建設',kv([['必要工数',fmt(o.construction_required,0)],['自己展開',o.self_deploying?'はい':'いいえ']]))+section('必要部材',componentCards(o.components))+section('Blocker',blockers.length?blockers.map(issueHtml).join(''):'<span class="badge ok">なし</span>')+section('操作',`<button type="button" class="primary" data-build="${esc(o.facility_definition_id)}" ${blockers.length?'disabled':''}>この地点に建設</button>`));
    return true;
  }

  function researchBlockers(r){if(r.status==='prototype')return r.prototype_blockers||[];if(r.status==='demonstration')return r.demonstration_blockers||[];return r.start_blockers||[];}
  function siteOptionsHtml(r,kind){
    const options=kind==='prototype'?(r.prototype_sites||[]):(r.demonstration_sites||[]),selected=kind==='prototype'?r.prototype_location_id:r.demonstration_location_id;
    if(!options.length)return '<div class="empty-state">候補地点なし</div>';
    return options.map((site)=>{const blocked=(site.blockers||[]).length,isSelected=site.location_id===selected,attr=kind==='prototype'?'data-research-prototype-site':'data-research-demo-site';return `<div class="route-mode-card ${isSelected?'is-usable':''}"><div class="mode-title"><span>${esc(locationName(site.location_id))}</span><span class="badge ${blocked?'warn':isSelected?'ok':''}">${blocked?`${blocked} blocker`:isSelected?'選択中':'実行可'}</span></div>${blocked?`<div class="issue-stack">${site.blockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:''}<button type="button" ${attr}="${esc(site.location_id)}" data-id="${esc(r.id)}" ${blocked||isSelected?'disabled':''}>${kind==='prototype'?'試作地点に設定':'実証地点に設定'}</button></div>`;}).join('');
  }
  function prototypeDemandHtml(r){
    const owner=`research:${r.id}`;
    const rows=(state.demands||[]).filter((d)=>d.owner_kind==='research'&&d.owner_id===owner);
    if(!rows.length)return '<div class="empty-state">現在の試作資材Demandなし</div>';
    return rows.map((d)=>`<div class="route-mode-card"><div class="mode-title"><span>${esc(resourceName(d.resource_id))}</span><span>${fmt(d.remaining_t)} t 未充足</span></div><div class="cell-sub">要求 ${fmt(d.requested_t)} t · 輸送系内 ${fmt(d.pipeline_t)} t · ${d.source_id?esc(locationName(d.source_id)):'供給元はLaneが選択'}</div></div>`).join('');
  }
  function renderResearchInspector(id){
    const r=state.research?.items?.find((x)=>x.id===id);if(!r)return false;
    const canPause=!['available','locked','complete'].includes(r.status);let action='';
    if(r.status==='available'&&r.can_start)action=`<button type="button" class="primary" data-research-action="start" data-id="${esc(r.id)}">RP ${fmt(r.research_point_cost,1)} を支払い研究開始</button>`;
    else if(r.paused)action=`<button type="button" data-research-action="resume" data-id="${esc(r.id)}">研究再開</button>`;
    else if(canPause)action=`<button type="button" data-research-action="pause" data-id="${esc(r.id)}">研究停止</button>`;
    const phaseBlockers=researchBlockers(r);let phase='';
    if(r.status==='prototype'){
      const resources=(r.prototype_resources||[]).map(([resource,amount])=>`${esc(resourceName(resource))} ${fmt(amount)}t`).join(' / ')||'追加資材なし';
      const funding=r.prototype_location_id?`<button type="button" class="primary" data-research-prototype-fund="${esc(r.id)}" ${phaseBlockers.length?'disabled':''}>試作資材を投入して完了</button>`:'';
      phase=section('試作',`<div class="cell-sub">必要資材: ${resources}</div><div class="cell-sub">試作地点: ${r.prototype_location_id?esc(locationName(r.prototype_location_id)):'未選択'}</div>${siteOptionsHtml(r,'prototype')}<h3>資材Demand</h3>${prototypeDemandHtml(r)}${funding}`);
    }else if(r.status==='demonstration')phase=section('実証',`<div class="cell-sub">進捗 ${r.demonstration_done_days}/${r.demonstration_required_days}日 · 地点 ${r.demonstration_location_id?esc(locationName(r.demonstration_location_id)):'未選択'}</div>${siteOptionsHtml(r,'demonstration')}`);
    const startState=['available','locked'].includes(r.status)?section('開始条件',kv([['必要RP',fmt(r.research_point_cost,1)],['保有RP',fmt(state.research?.stored_points,1)],['RP容量',fmt(state.research?.storage_capacity_points,1)]])):'';
    setInspector(r.display_name,section('状態',kv([['段階',esc(stateLabels[r.status]||r.status)],['必要RP',fmt(r.research_point_cost,1)],['実証日数',`${r.demonstration_done_days}/${r.demonstration_required_days}`]]))+section('前提',(r.prerequisites||[]).length?(r.prerequisites||[]).map((x)=>`<span class="badge">${esc(definitionName(x))}</span>`).join(' '):'<span class="badge ok">なし</span>')+startState+section('現在のblocker',phaseBlockers.length?`<div class="issue-stack">${phaseBlockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:'<span class="badge ok">なし</span>')+phase+section('研究操作',`<div class="action-stack">${action||'<span class="badge">現在可能な研究操作なし</span>'}</div>`));
    return true;
  }
  function renderSurveyInspector(id){
    const s=state.surveys?.items?.find((x)=>x.resource_id===id);if(!s)return false;
    const action=s.active?(s.paused?`<button data-survey-action="resume" data-id="${esc(id)}">探査再開</button>`:`<button data-survey-action="pause" data-id="${esc(id)}">探査停止</button>`):`<button class="primary" data-survey-action="start" data-id="${esc(id)}">探査開始</button>`;
    setInspector(s.resource_name,section('探査状態',kv([['進捗',pct(s.progress)],['知識レベル',String(s.knowledge_level)],['能力/日',fmt(s.capacity_points_per_day,2)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['推定埋蔵量',s.visible_reserve_t==null?'—':`${fmt(s.visible_reserve_t)} t`]]))+section('操作',`<div class="action-stack">${action}<div class="form-row"><label>探査配分<input id="surveyWeightInput" type="number" min="0" step="0.1" value="${s.allocation_weight||1}"></label><button data-set-survey-weight="${esc(id)}">配分を適用</button></div></div>`));return true;
  }

  function renderInspector(){
    if(!state.inspector){setInspector('選択項目','<div class="empty-state">中央の項目を選択すると、状態・条件・操作をここに表示します。</div>');return;}
    const {type,id}=state.inspector;
    const handlers={facility:renderFacilityInspector,resource:renderResourceInspector,project:renderProjectInspector,'build-option':renderBuildOptionInspector,research:renderResearchInspector,survey:renderSurveyInspector};
    if(!handlers[type]?.(id)){state.inspector=null;setInspector('選択項目','<div class="empty-state">項目の状態が変化しました。再選択してください。</div>');}
  }

  function render(){
    const loc=state.location;if(!loc)return;
    $('#locationTitle').textContent=loc.display_name;
    const kind=(state.world?.locations||[]).find((x)=>x.id===loc.id)?.kind;
    $('#locationKind').textContent=`${A.locationKindLabels[kind]||kind||'拠点'}拠点`;
    $('#headlineMetrics').innerHTML=[['発電',`${fmt(loc.power_generation_mw)} MW`],['需要',`${fmt(loc.power_demand_mw)} MW`],['建設能力',`${fmt(loc.construction_capacity_per_day)} /日`],['設備',`${loc.facilities.length}`]].map(A.metricHtml).join('');
    $$('.tab-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.tab===state.activeTab));
    renderActiveTab();renderInspector();
  }

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='operations')return;
    const tab=event.target.closest('[data-tab]');if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;render();return;}
    const inspect=event.target.closest('[data-inspect]');if(inspect){state.inspector={type:inspect.dataset.inspect,id:inspect.dataset.id};renderInspector();$$('#operationsTabContent tr').forEach((tr)=>tr.classList.toggle('is-selected',tr.dataset.id===inspect.dataset.id));return;}
    const build=event.target.closest('[data-build]');if(build){try{await command('PlanBuild',{location_id:state.locationId,facility_id:build.dataset.build,priority:50,sourcing_policy:'mixed',import_source_id:null});banner('建設計画を作成しました');}catch{}return;}
    const upgrade=event.target.closest('[data-upgrade]');if(upgrade){try{const result=await command('PlanFacilityUpgrade',{facility_id:upgrade.dataset.upgrade,priority:50,sourcing_policy:'mixed',import_source_id:null});banner(`Upgrade案件 ${result?.created_id||''} を作成しました`);}catch{}return;}
    const cmd=event.target.closest('[data-command]');if(cmd){const payload={};if(cmd.dataset.facilityId)payload.facility_id=cmd.dataset.facilityId;if(cmd.dataset.projectId)payload.project_id=cmd.dataset.projectId;try{await command(cmd.dataset.command,payload);}catch{}return;}
    const pp=event.target.closest('[data-set-power-priority]');if(pp){try{await command('SetPowerPriority',{facility_id:pp.dataset.setPowerPriority,priority:Number($('#facilityPriorityInput').value)});}catch{}return;}
    const ra=event.target.closest('[data-research-action]');if(ra){const map={start:'StartResearch',pause:'PauseResearch',resume:'ResumeResearch'};try{await command(map[ra.dataset.researchAction],{research_id:ra.dataset.id});}catch{}return;}
    const protoSite=event.target.closest('[data-research-prototype-site]');if(protoSite){try{await command('SetResearchPrototypeSite',{research_id:protoSite.dataset.id,location_id:protoSite.dataset.researchPrototypeSite});}catch{}return;}
    const protoFund=event.target.closest('[data-research-prototype-fund]');if(protoFund){try{await command('FundResearchPrototype',{research_id:protoFund.dataset.researchPrototypeFund});}catch{}return;}
    const demo=event.target.closest('[data-research-demo-site]');if(demo){try{await command('SetResearchDemonstrationSite',{research_id:demo.dataset.id,location_id:demo.dataset.researchDemoSite});}catch{}return;}
    const sa=event.target.closest('[data-survey-action]');if(sa){const map={start:'StartSurvey',pause:'PauseSurvey',resume:'ResumeSurvey'},payload={location_id:state.locationId,resource_id:sa.dataset.id};if(sa.dataset.surveyAction==='start')payload.allocation_weight=1;try{await command(map[sa.dataset.surveyAction],payload);}catch{}return;}
    const sw=event.target.closest('[data-set-survey-weight]');if(sw){try{await command('SetSurveyAllocation',{location_id:state.locationId,resource_id:sw.dataset.setSurveyWeight,weight:Number($('#surveyWeightInput').value)});}catch{}return;}
  });

  window.SpaceIdleOperations={render};
})();
