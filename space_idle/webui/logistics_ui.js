(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before logistics_ui.js');
  const {state,$,esc,fmt,locationName,resourceName,definitionName,capabilityName,operationName,issueHtml,metricHtml,command,banner}=A;
  let editingLaneId=null;
  let editingAllocationId=null;
  let relocationContext=null;

  const ownerLabels={project:'建設',research:'研究',industry:'産業',facility_maintenance:'設備維持',vehicle_production:'機体建造',scientific_exploration:'科学探査',contract:'契約'};
  const ownerLabel=(kind)=>ownerLabels[kind]||kind;
  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const capText=(c)=>c?`${fmt(c.forward_t_per_day,2)} / ${fmt(c.reverse_t_per_day,2)} t/日`:'—';
  const infrastructureText=(rows)=>{const items=rows||[];return items.length?items.map((r)=>`${locationName(r.location_id)}: ${capabilityName(r.capability_id)}${Number(r.minimum_capacity||0)>0?` ≥ ${fmt(r.minimum_capacity,2)}`:''} (${r.mode==='available'?'利用可能':'インフラ'})`).join(' / '):'追加Infrastructure要件なし';};

  function logistics(){return state.logistics||{};}

  function renderRouteFilters(){
    const locs=state.world?.locations||[];
    for(const [selId,label] of [['#routeOriginFilter','全出発地'],['#routeDestinationFilter','全到着地']]){
      const sel=$(selId); if(!sel)continue; const current=sel.value;
      sel.innerHTML=`<option value="">${label}</option>`+locs.map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
      if([...sel.options].some((o)=>o.value===current))sel.value=current;
    }
  }
  function filteredRoutes(){
    const origin=$('#routeOriginFilter')?.value||'',dest=$('#routeDestinationFilter')?.value||'';
    return (state.routes?.items||[]).filter((r)=>(!origin||r.origin_id===origin)&&(!dest||r.destination_id===dest));
  }
  function renderRouteList(){
    $('#routeList').innerHTML=filteredRoutes().map((r)=>`<button type="button" class="route-button ${r.id===state.selectedRouteId?'is-selected':''}" data-route-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="route-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.service_feasible_now?'ok':r.available?'warn':''}">${r.service_feasible_now?'Service可':r.available?'運用条件待ち':'Route不成立'}</span></div></button>`).join('')||'<div class="empty-state">条件に一致するRouteなし</div>';
  }

  const nodePositions={'base.node.earth_surface':[12,50],'base.node.low_earth_orbit':[34,50],'base.node.lunar_orbit':[60,50],'base.node.south_polar_ridge':[84,22],'base.node.polar_cold_trap':[84,50],'base.node.nearside_mare':[84,78]};
  function renderNetwork(){
    const svg=$('#networkSvg'),nodes=$('#networkNodes'),routes=state.routes?.items||[];
    svg.innerHTML=routes.map((r)=>{const a=nodePositions[r.origin_id],b=nodePositions[r.destination_id];if(!a||!b)return'';return `<line x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}" class="network-line ${r.service_feasible_now?'available':''} ${r.id===state.selectedRouteId?'selected':''}" data-route-line="${esc(r.id)}" />`;}).join('');
    nodes.innerHTML=(state.world?.locations||[]).map((loc)=>{const p=nodePositions[loc.id]||[50,50];return `<div class="network-node" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`;}).join('');
  }

  function renderLanes(){
    const items=state.lanes?.items||[];$('#laneCountBadge').textContent=`${items.length}本`;
    const rows=items.map((lane)=>{const blocked=(lane.blockers||[]).length,stateText=lane.paused?'停止':blocked?'阻害':'稼働',stateClass=lane.paused||blocked?'warn':'ok';return `<tr><td><div class="cell-main">${esc(locationName(lane.source_id))} → ${esc(locationName(lane.destination_id))}</div><div class="cell-sub">${esc(lane.id)} · ${esc(lane.path_policy)}</div></td><td>${fmt(lane.requested_capacity_t_per_day)} t/日</td><td>${lane.priority}</td><td>${fmt(lane.effective_capacity_t_per_day)} t/日</td><td>${fmt(lane.used_t)} t</td><td>${fmt(lane.queued_t)} t</td><td><span class="badge ${stateClass}">${stateText}</span><div class="cell-sub">${blocked?esc((lane.blockers||[]).map(A.userFacingText).join(' / ')):'blockerなし'}</div></td><td><div class="action-row"><button type="button" data-lane-edit="${esc(lane.id)}">設定</button><button type="button" data-lane-toggle="${esc(lane.id)}" data-paused="${lane.paused?'1':'0'}">${lane.paused?'再開':'停止'}</button><button type="button" class="danger-button" data-lane-delete="${esc(lane.id)}">削除</button></div></td></tr>`;}).join('');
    $('#laneTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newLaneButton">Laneを作成</button></div><table><thead><tr><th>Lane</th><th>要求容量</th><th>優先度</th><th>実効容量</th><th>使用</th><th>待ち需要</th><th>状態</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="8">Laneなし。需要は保持され、輸送能力の利用先が未設定として表示されます。</td></tr>'}</tbody></table>`;
  }

  function demandStateLabel(d){return {local_covered:'現地充足',pipeline_covered:'輸送中で充足',no_lane:'Lane未設定',lane_blocked:'Lane阻害',source_shortage:'供給元不足',coverage_gap:'供給空白',low_runway:'猶予小',uncovered:'未充足'}[d.supply_state]||d.supply_state;}
  function renderDemands(){
    const items=state.demands||[];$('#demandCountBadge').textContent=`${items.length}件`;
    const rows=items.map((d)=>{const runway=d.local_runway_days==null?'—':`${fmt(d.local_runway_days,1)}日`,arrival=d.earliest_confirmed_arrival_day==null?'—':`Day ${fmt(d.earliest_confirmed_arrival_day,0)}`,stateClass=['local_covered','pipeline_covered'].includes(d.supply_state)?'ok':'warn';return `<tr><td><div class="cell-main">${esc(ownerLabel(d.owner_kind))}</div><div class="cell-sub">${esc(d.owner_id)}</div></td><td>${esc(resourceName(d.resource_id))}</td><td>${d.source_id?esc(locationName(d.source_id)):'Lane選択'} → ${esc(locationName(d.destination_id))}</td><td>${fmt(d.requested_t)} t<div class="cell-sub">現地 ${fmt(d.local_supply_t)} / 外部 ${fmt(d.external_required_t)} t</div></td><td>${fmt(d.pipeline_t)} t<div class="cell-sub">最短確定到着 ${esc(arrival)}</div></td><td>${fmt(d.remaining_t)} t<div class="cell-sub">猶予 ${esc(runway)}</div></td><td><span class="badge ${stateClass}">${esc(demandStateLabel(d))}</span><div class="cell-sub">Lane ${d.operational_lane_count}/${d.eligible_lane_count} · 在庫源 ${d.stocked_source_count}</div></td><td>${d.priority}</td></tr>`;}).join('');
    $('#demandTable').innerHTML=`<table><thead><tr><th>発生元</th><th>資源</th><th>供給→需要地</th><th>要求/現地</th><th>輸送系内</th><th>未充足/猶予</th><th>供給状態</th><th>優先</th></tr></thead><tbody>${rows||'<tr><td colspan="8">現在のResource Demandなし</td></tr>'}</tbody></table>`;
  }

  function renderFleet(){
    const pools=state.fleet?.pools||logistics().fleet_pools||[]; const relocations=state.fleet?.relocations||logistics().relocations||[]; const releases=state.fleet?.releases||logistics().releases||[];
    $('#vehicleCountBadge').textContent=`${pools.reduce((n,p)=>n+Number(p.total_units||0),0)} unit`;
    const rows=pools.map((p)=>`<tr><td><div class="cell-main">${esc(p.display_name)}</div><div class="cell-sub">${esc(p.vehicle_definition_id)}</div></td><td>${esc(locationName(p.location_id))}</td><td>${fmt(p.total_units,0)}</td><td>${fmt(p.free_units,0)}</td><td>${fmt(p.transport_units,0)}</td><td>${fmt(p.exploration_units,0)}</td><td>${fmt(p.relocating_units,0)}</td><td>${fmt(p.releasing_units,0)}</td><td><button type="button" data-fleet-relocate="${esc(p.vehicle_definition_id)}" data-fleet-source="${esc(p.location_id)}" data-fleet-free="${fmt(p.free_units,0)}" ${Number(p.free_units||0)<=0?'disabled title="free Fleetなし"':''}>移動</button></td></tr>`).join('');
    const relocationRows=relocations.map((r)=>`<div class="cell-sub">${esc(r.display_name)} ${fmt(r.units,0)} unit · ${esc(locationName(r.source_id))} → ${esc(locationName(r.destination_id))} · Day ${fmt(r.arrival_day,0)} 到着</div>`).join('');
    const releaseRows=releases.map((r)=>`<div class="cell-sub">${esc(r.display_name)} ${fmt(r.units,0)} unit · ${esc(locationName(r.location_id))} · ${esc(r.allocation_id)} から回収中 · Day ${fmt(r.release_day,0)} 解放（残り ${fmt(r.remaining_days,0)}日）</div>`).join('');
    $('#vehicleTable').innerHTML=`<table><thead><tr><th>Vehicle type</th><th>所在地</th><th>総数</th><th>free</th><th>Transport</th><th>Exploration</th><th>relocating</th><th>releasing</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="9">Fleetなし</td></tr>'}</tbody></table>${relocationRows?`<div style="padding:8px"><strong>移動中</strong>${relocationRows}</div>`:''}${releaseRows?`<div style="padding:8px"><strong>回収中</strong>${releaseRows}</div>`:''}`;
  }

  function allocationTarget(a){return a.control_mode==='units'?`${fmt(a.target_units,0)} unit`:`F ${fmt(a.target_capacity?.forward_t_per_day,2)} / R ${fmt(a.target_capacity?.reverse_t_per_day,2)} t/日`;}
  function renderAllocations(){
    const items=state.transportAllocations?.items||logistics().allocations||[]; $('#allocationCountBadge').textContent=`${items.length}件`;
    const rows=items.map((a)=>{const blocked=(a.blockers||[]).length+(a.limiting_factors||[]).length;return `<tr data-allocation-row="${esc(a.id)}"><td><div class="cell-main">${esc(a.display_name)}</div><div class="cell-sub">${esc(locationName(a.anchor_location_id))} → ${esc(locationName(a.destination_id))} · ${esc(a.id)}</div><div class="cell-sub">Infrastructure: ${esc(infrastructureText(a.infrastructure_requirements))}</div><div class="cell-sub">Resource: ${(a.operational_resource_demand||[]).map(([loc,rid,amount])=>`${esc(locationName(loc))} ${esc(resourceName(rid))} ${fmt(amount,2)} t/日`).join(' / ')||'追加運用Resourceなし'}</div></td><td><span class="badge">${esc(a.control_mode.toUpperCase())}</span><div class="cell-sub">正本: ${esc(allocationTarget(a))}</div></td><td>${fmt(a.active_units,0)} / ${fmt(a.required_units,0)}<div class="cell-sub">unfilled ${fmt(a.unfilled_units,0)}</div></td><td>${capText(a.nominal)}</td><td>${capText(a.available)}</td><td>${capText(a.used)}</td><td>${capText(a.spare)}</td><td>${fmt(a.cycle_days,1)}日<div class="cell-sub">latency ${fmt(a.forward_latency_days,0)}日</div></td><td>${blocked}<div class="cell-sub">${esc([...(a.blockers||[]),...(a.limiting_factors||[])].slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><div class="action-row"><button type="button" data-allocation-edit="${esc(a.id)}">設定</button><button type="button" data-allocation-mode="${esc(a.id)}" data-mode="${esc(a.control_mode)}">${a.control_mode==='units'?'CAPACITYへ':'UNITSへ'}</button><button type="button" data-allocation-toggle="${esc(a.id)}" data-paused="${a.paused?'1':'0'}">${a.paused?'再開':'停止'}</button><button type="button" class="danger-button" data-allocation-delete="${esc(a.id)}">削除</button></div></td></tr>`;}).join('');
    $('#allocationTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newAllocationButton">Transport Allocationを作成</button></div><table><thead><tr><th>Service</th><th>control / target</th><th>active / required</th><th>Nominal F/R</th><th>Available F/R</th><th>Used F/R</th><th>Spare F/R</th><th>cycle</th><th>blocker</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="10">Transport Allocationなし。Fleetはfreeのままです。</td></tr>'}</tbody></table>`;
  }

  function renderVehicleProduction(){
    const projects=logistics().vehicle_production||[],options=logistics().vehicle_production_options||[]; $('#vehicleProductionCountBadge').textContent=`${projects.length}件`;
    const projectRows=projects.map((p)=>{const blockers=p.blockers||[],toggle=p.phase==='complete'?'<span class="badge ok">完成</span>':`<button type="button" data-production-toggle="${esc(p.id)}" data-paused="${p.paused?'1':'0'}">${p.paused?'再開':'停止'}</button>`;return `<tr data-production-project-row="${esc(p.id)}"><td><div class="cell-main">${esc(p.display_name)}</div><div class="cell-sub">${esc(locationName(p.location_id))}</div></td><td>${esc(p.phase)}</td><td>${fmt(p.progress_days,1)}/${fmt(p.required_days,1)}日</td><td><input type="number" step="1" value="${fmt(p.priority,0)}" data-production-priority-value data-draft-key="production:${esc(p.id)}:priority" ${p.priority_editable?'':'disabled'}></td><td><input type="number" min="0.01" step="0.1" value="${fmt(p.allocation_weight,2)}" data-production-allocation-value data-draft-key="production:${esc(p.id)}:allocation" ${p.allocation_editable?'':'disabled'}></td><td>${blockers.length}<div class="cell-sub">${esc(blockers.slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><div class="action-row">${toggle}${p.phase==='complete'?'':`<button type="button" data-production-settings="${esc(p.id)}">設定適用</button>`}</div></td></tr>`;}).join('');
    const optionRows=options.map((o)=>`<tr data-production-option-row><td><div class="cell-main">${esc(o.display_name)}</div><div class="cell-sub">${esc(locationName(o.location_id))}</div></td><td>${fmt(o.production_days,1)}日</td><td>${(o.resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)}t`).join(' / ')}</td><td><input type="number" step="1" value="50" data-production-priority-value data-draft-key="production-option:${esc(o.vehicle_definition_id)}:${esc(o.location_id)}:priority"></td><td><input type="number" min="0.01" step="0.1" value="1" data-production-allocation-value data-draft-key="production-option:${esc(o.vehicle_definition_id)}:${esc(o.location_id)}:allocation"></td><td>${(o.blockers||[]).length}<div class="cell-sub">${esc((o.blockers||[]).slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><button type="button" data-produce-vehicle="${esc(o.vehicle_definition_id)}" data-production-location="${esc(o.location_id)}" ${(o.blockers||[]).length?'disabled':''}>建造</button></td></tr>`).join('');
    $('#vehicleProductionTable').innerHTML=`<table><thead><tr><th>建造中</th><th>進捗</th><th>状態</th><th>資材優先</th><th>能力配分</th><th>blocker</th><th>操作</th></tr></thead><tbody>${projectRows||'<tr><td colspan="7">建造中Vehicleなし</td></tr>'}</tbody></table><table><thead><tr><th>建造候補</th><th>期間</th><th>必要資源</th><th>資材優先</th><th>能力配分</th><th>blocker</th><th>操作</th></tr></thead><tbody>${optionRows||'<tr><td colspan="7">建造候補なし</td></tr>'}</tbody></table>`;
  }

  function renderCargoFlows(){
    const items=state.cargoFlows?.items||logistics().cargo_flows||[]; $('#cargoCountBadge').textContent=`${items.length}件`;
    const rows=items.map((f)=>`<tr><td><div class="cell-main">${esc(resourceName(f.resource_id))}</div><div class="cell-sub">${esc(ownerLabel(f.owner_kind))} · ${esc(f.owner_id)}</div></td><td>${esc(locationName(f.source_id))} → ${esc(locationName(f.destination_id))}</td><td>${fmt(f.amount_t)} t</td><td>${esc(f.status)}</td><td>Day ${fmt(f.departure_day,0)} → ${fmt(f.ready_day,0)}</td><td>${esc((f.service_ids||[]).map(definitionName).join(' → '))}</td></tr>`).join('');
    $('#cargoTable').innerHTML=`<table><thead><tr><th>資源 / 発生元</th><th>区間</th><th>量</th><th>状態</th><th>dispatch / arrival</th><th>Service path</th></tr></thead><tbody>${rows||'<tr><td colspan="6">輸送中・到着待機Cargo Flowなし</td></tr>'}</tbody></table>`;
  }

  function renderRouteInspector(){
    const title=$('#routeInspectorTitle'),content=$('#routeInspectorContent');
    if(!state.selectedRouteId){title.textContent='輸送路を選択';content.innerHTML='<div class="empty-state">左の輸送路またはネットワーク上の接続を選択してください。</div>';return;}
    const route=(state.routes?.items||[]).find((r)=>r.id===state.selectedRouteId);if(!route)return;
    title.textContent=route.display_name;
    const modes=(route.modes||[]).map((m)=>`<div class="route-mode-card ${m.service_feasible?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name)}</span><span class="badge ${m.service_feasible?'ok':'warn'}">${m.service_feasible?'Service可':'阻害'}</span></div><div class="cell-sub">${m.kind==='external_service'?'外部Service':`Fleet total ${fmt(m.fleet_total_units,0)} / free ${fmt(m.fleet_free_units,0)}`} · nominal ${capText(m.nominal_capacity)} · cycle ${m.cycle_days==null?'—':fmt(m.cycle_days,1)+'日'}</div>${m.kind==='external_service'?'':`<div class="cell-sub">Infrastructure: ${esc(infrastructureText(m.infrastructure_requirements))}</div>`}${(m.blockers||[]).length?`<div class="issue-stack">${m.blockers.map((b)=>issueHtml(['transport',b])).join('')}</div>`:''}</div>`).join('');
    content.innerHTML=section('区間',kv([['出発',esc(locationName(route.origin_id))],['到着',esc(locationName(route.destination_id))],['Route条件',route.available?'成立':'不成立'],['Service成立',route.service_feasible_now?'はい':'いいえ'],['基準日数',fmt(route.transit_days)],['Δv',`${fmt(route.delta_v_km_s,2)} km/s`]]))+section('Operation',(route.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o)?o[0]:o))}</span>`).join(' ')||'—')+section('Blocker',(route.blockers||[]).length?`<div class="issue-stack">${route.blockers.map((b)=>issueHtml(['transport',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+section('Service候補',modes||'<div class="empty-state">候補なし</div>')+section('操作','<div class="action-stack"><button type="button" class="primary" id="routeAllocationButton">この関係へFleetを配分</button><button type="button" id="routeLaneButton">この関係のLaneを作成</button></div>');
  }

  function populateLocationSelects(){
    const opts=(state.world?.locations||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
    for(const id of ['laneSource','laneDestination','allocationSource','allocationDestination','relocationDestination']){const el=$('#'+id);if(el){const current=el.value;el.innerHTML=opts;if([...el.options].some((o)=>o.value===current))el.value=current;}}
    const vehicle=$('#allocationVehicle'); if(vehicle){const current=vehicle.value;vehicle.innerHTML=(state.catalog?.vehicles||[]).map((v)=>`<option value="${esc(v.id)}">${esc(v.display_name)}</option>`).join('');if([...vehicle.options].some((o)=>o.value===current))vehicle.value=current;}
  }
  function openLaneDialog(route=null,lane=null){
    editingLaneId=lane?.id||null;populateLocationSelects();const editing=Boolean(lane);
    $('#laneDialog h2').textContent=editing?'物流Laneを編集':'物流Laneを作成';$('#laneForm button[type="submit"]').textContent=editing?'設定を更新':'Lane作成';
    for(const id of ['laneSource','laneDestination','lanePolicy'])$('#'+id).disabled=editing;
    if(lane){$('#laneSource').value=lane.source_id;$('#laneDestination').value=lane.destination_id;$('#laneCapacity').value=String(lane.requested_capacity_t_per_day);$('#lanePriority').value=String(lane.priority);$('#lanePolicy').value=lane.path_policy;}else if(route){$('#laneSource').value=route.origin_id;$('#laneDestination').value=route.destination_id;}
    $('#laneDialog').showModal();
  }
  function updateAllocationModeFields(){const capacity=$('#allocationMode').value==='capacity';$('#allocationUnitsGroup').hidden=capacity;$('#allocationCapacityGroup').hidden=!capacity;}
  function openAllocationDialog(route=null,allocation=null){
    editingAllocationId=allocation?.id||null;populateLocationSelects();const editing=Boolean(allocation);
    $('#allocationDialog h2').textContent=editing?'Transport Allocationを編集':'Fleetを輸送へ配分';
    $('#allocationForm button[type="submit"]').textContent=editing?'設定を更新':'Allocation作成';
    for(const id of ['allocationVehicle','allocationSource','allocationDestination','allocationMode'])$('#'+id).disabled=editing;
    if(allocation){
      $('#allocationVehicle').value=allocation.vehicle_definition_id;$('#allocationSource').value=allocation.anchor_location_id;$('#allocationDestination').value=allocation.destination_id;$('#allocationMode').value=allocation.control_mode;$('#allocationPriority').value=String(allocation.priority);$('#allocationPolicy').value=allocation.path_policy;
      if(allocation.control_mode==='units')$('#allocationUnits').value=String(allocation.target_units??0);else{$('#allocationForward').value=String(allocation.target_capacity?.forward_t_per_day??0);$('#allocationReverse').value=String(allocation.target_capacity?.reverse_t_per_day??0);}
    }else if(route){$('#allocationSource').value=route.origin_id;$('#allocationDestination').value=route.destination_id;}
    updateAllocationModeFields();$('#allocationDialog').showModal();
  }
  function openRelocationDialog(vehicleDefinitionId,sourceId,freeUnits){
    relocationContext={vehicle_definition_id:vehicleDefinitionId,source_id:sourceId};populateLocationSelects();
    $('#relocationVehicle').textContent=definitionName(vehicleDefinitionId);$('#relocationSource').textContent=locationName(sourceId);$('#relocationFree').textContent=String(freeUnits);$('#relocationUnits').max=String(freeUnits);$('#relocationUnits').value=String(Math.min(1,Number(freeUnits)));
    const destination=$('#relocationDestination');if(destination.value===sourceId){const other=[...destination.options].find((o)=>o.value!==sourceId);if(other)destination.value=other.value;}
    $('#relocationDialog').showModal();
  }

  function render(){
    if(!state.logisticsSummary||!state.routes)return;const s=state.logisticsSummary;
    $('#logisticsSummary').innerHTML=[['Fleet',`${s.free_fleet_units}/${s.fleet_units} free`],['Allocation',`${s.allocation_count} · 未充足 ${s.unfilled_allocation_units}`],['Lane',`${s.lane_count}`],['Demand',`${s.demand_count}`],['待ち需要',`${fmt(s.queued_demand_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');
    populateLocationSelects();renderRouteFilters();renderRouteList();renderNetwork();renderLanes();renderDemands();renderFleet();renderAllocations();renderVehicleProduction();renderCargoFlows();renderRouteInspector();
  }

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='logistics')return;
    const routeBtn=event.target.closest('[data-route-id]');if(routeBtn){state.selectedRouteId=routeBtn.dataset.routeId;render();return;}
    const routeLine=event.target.closest('[data-route-line]');if(routeLine){state.selectedRouteId=routeLine.dataset.routeLine;render();return;}
    const network=event.target.closest('[data-network-location]');if(network){$('#routeOriginFilter').value=network.dataset.networkLocation;renderRouteList();return;}
    if(event.target.closest('#newLaneButton')){openLaneDialog();return;} if(event.target.closest('#routeLaneButton')){openLaneDialog((state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId));return;}
    if(event.target.closest('#newAllocationButton')){openAllocationDialog();return;} if(event.target.closest('#routeAllocationButton')){openAllocationDialog((state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId));return;}
    const allocationEdit=event.target.closest('[data-allocation-edit]');if(allocationEdit){const a=(state.transportAllocations?.items||[]).find((x)=>x.id===allocationEdit.dataset.allocationEdit);if(a)openAllocationDialog(null,a);return;}
    const relocate=event.target.closest('[data-fleet-relocate]');if(relocate){openRelocationDialog(relocate.dataset.fleetRelocate,relocate.dataset.fleetSource,Number(relocate.dataset.fleetFree));return;}
    const allocationMode=event.target.closest('[data-allocation-mode]');if(allocationMode){try{await command('ChangeTransportAllocationMode',{allocation_id:allocationMode.dataset.allocationMode,control_mode:allocationMode.dataset.mode==='units'?'capacity':'units'});}catch{}return;}
    const allocationToggle=event.target.closest('[data-allocation-toggle]');if(allocationToggle){try{await command(allocationToggle.dataset.paused==='1'?'ResumeTransportAllocation':'PauseTransportAllocation',{allocation_id:allocationToggle.dataset.allocationToggle});}catch{}return;}
    const allocationDelete=event.target.closest('[data-allocation-delete]');if(allocationDelete){try{await command('DeleteTransportAllocation',{allocation_id:allocationDelete.dataset.allocationDelete});}catch{}return;}
    const produce=event.target.closest('[data-produce-vehicle]');if(produce){const row=produce.closest('[data-production-option-row]');try{await command('ProduceVehicle',{vehicle_definition_id:produce.dataset.produceVehicle,location_id:produce.dataset.productionLocation,priority:Number(row.querySelector('[data-production-priority-value]').value),allocation_weight:Number(row.querySelector('[data-production-allocation-value]').value)});}catch{}return;}
    const productionToggle=event.target.closest('[data-production-toggle]');if(productionToggle){try{await command(productionToggle.dataset.paused==='1'?'ResumeVehicleProduction':'PauseVehicleProduction',{production_id:productionToggle.dataset.productionToggle});}catch{}return;}
    const productionSettings=event.target.closest('[data-production-settings]');if(productionSettings){const row=productionSettings.closest('[data-production-project-row]');try{await command('SetVehicleProductionSettings',{production_id:productionSettings.dataset.productionSettings,priority:Number(row.querySelector('[data-production-priority-value]').value),allocation_weight:Number(row.querySelector('[data-production-allocation-value]').value)});}catch{}return;}
    const edit=event.target.closest('[data-lane-edit]');if(edit){const lane=(state.lanes?.items||[]).find((x)=>x.id===edit.dataset.laneEdit);if(lane)openLaneDialog(null,lane);return;}
    const toggle=event.target.closest('[data-lane-toggle]');if(toggle){try{await command(toggle.dataset.paused==='1'?'ResumeLogisticsLane':'PauseLogisticsLane',{lane_id:toggle.dataset.laneToggle});}catch{}return;}
    const del=event.target.closest('[data-lane-delete]');if(del){try{await command('DeleteLogisticsLane',{lane_id:del.dataset.laneDelete});}catch{}return;}
  });

  document.addEventListener('DOMContentLoaded',()=>{
    $('#routeOriginFilter').addEventListener('change',renderRouteList);$('#routeDestinationFilter').addEventListener('change',renderRouteList);
    $('#laneCloseButton').addEventListener('click',()=>{editingLaneId=null;$('#laneDialog').close();});$('#laneCancelButton').addEventListener('click',()=>{editingLaneId=null;$('#laneDialog').close();});
    $('#laneForm').addEventListener('submit',async(event)=>{event.preventDefault();const capacity=Number($('#laneCapacity').value),priority=Number($('#lanePriority').value);try{if(editingLaneId){await command('UpdateLogisticsLane',{lane_id:editingLaneId,requested_capacity_t_per_day:capacity,priority});editingLaneId=null;}else{const source=$('#laneSource').value,destination=$('#laneDestination').value;if(source===destination){banner('Laneの出発地と到着地は異なる必要があります','error');return;}await command('CreateLogisticsLane',{source_id:source,destination_id:destination,requested_capacity_t_per_day:capacity,priority,path:null,path_policy:$('#lanePolicy').value});}$('#laneDialog').close();}catch{}});
    $('#allocationMode').addEventListener('change',updateAllocationModeFields);$('#allocationCloseButton').addEventListener('click',()=>{editingAllocationId=null;$('#allocationDialog').close();});$('#allocationCancelButton').addEventListener('click',()=>{editingAllocationId=null;$('#allocationDialog').close();});
    $('#allocationForm').addEventListener('submit',async(event)=>{event.preventDefault();const mode=$('#allocationMode').value;try{if(editingAllocationId){const payload={allocation_id:editingAllocationId,priority:Number($('#allocationPriority').value),path_policy:$('#allocationPolicy').value};if(mode==='units')payload.target_units=Number($('#allocationUnits').value);else{payload.target_forward_t_per_day=Number($('#allocationForward').value);payload.target_reverse_t_per_day=Number($('#allocationReverse').value);}await command('UpdateTransportAllocation',payload);editingAllocationId=null;}else{const payload={vehicle_definition_id:$('#allocationVehicle').value,anchor_location_id:$('#allocationSource').value,destination_id:$('#allocationDestination').value,priority:Number($('#allocationPriority').value),control_mode:mode,path:null,path_policy:$('#allocationPolicy').value};if(mode==='units')payload.target_units=Number($('#allocationUnits').value);else{payload.target_forward_t_per_day=Number($('#allocationForward').value);payload.target_reverse_t_per_day=Number($('#allocationReverse').value);}await command('CreateTransportAllocation',payload);}$('#allocationDialog').close();}catch{}});
    $('#relocationCloseButton').addEventListener('click',()=>{relocationContext=null;$('#relocationDialog').close();});$('#relocationCancelButton').addEventListener('click',()=>{relocationContext=null;$('#relocationDialog').close();});
    $('#relocationForm').addEventListener('submit',async(event)=>{event.preventDefault();if(!relocationContext)return;const destination=$('#relocationDestination').value;if(destination===relocationContext.source_id){banner('Fleet移動の出発地と到着地は異なる必要があります','error');return;}try{await command('RelocateFleet',{vehicle_definition_id:relocationContext.vehicle_definition_id,units:Number($('#relocationUnits').value),source_id:relocationContext.source_id,destination_id:destination,path:null,path_policy:$('#relocationPolicy').value});relocationContext=null;$('#relocationDialog').close();}catch{}});
  });

  window.SpaceIdleLogistics={render,openLaneDialog,openAllocationDialog};
})();
