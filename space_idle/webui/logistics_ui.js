(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before logistics_ui.js');
  const {state,$,$$,esc,fmt,locationName,resourceName,definitionName,operationName,stateLabels,issueHtml,metricHtml,api,command,banner}=A;
  let cargoPlans=null;
  let cargoContractId=null;

  const ownerLabels={project:'建設',research:'研究',industry:'産業',player:'手動',contract:'契約'};
  const ownerLabel=(kind)=>ownerLabels[kind]||kind;
  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;

  function renderRouteFilters(){
    const locs=state.world?.locations||[];
    for(const [selId,label] of [['#routeOriginFilter','全出発地'],['#routeDestinationFilter','全到着地']]){
      const sel=$(selId);if(!sel)continue;const current=sel.value;
      sel.innerHTML=`<option value="">${label}</option>`+locs.map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
      if([...sel.options].some((o)=>o.value===current))sel.value=current;
    }
  }
  function filteredRoutes(){
    const origin=$('#routeOriginFilter')?.value||'',dest=$('#routeDestinationFilter')?.value||'';
    return (state.routes?.items||[]).filter((r)=>(!origin||r.origin_id===origin)&&(!dest||r.destination_id===dest));
  }
  function renderRouteList(){
    $('#routeList').innerHTML=filteredRoutes().map((r)=>`<button type="button" class="route-button ${r.id===state.selectedRouteId?'is-selected':''}" data-route-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="route-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.usable_now?'ok':r.available?'warn':''}">${r.usable_now?'利用可':r.available?'設備待ち':'利用不可'}</span></div></button>`).join('')||'<div class="empty-state">条件に一致するRouteなし</div>';
  }

  const nodePositions={'base.node.earth_surface':[12,50],'base.node.low_earth_orbit':[34,50],'base.node.lunar_orbit':[60,50],'base.node.south_polar_ridge':[84,22],'base.node.polar_cold_trap':[84,50],'base.node.nearside_mare':[84,78]};
  function renderNetwork(){
    const svg=$('#networkSvg'),nodes=$('#networkNodes'),routes=state.routes?.items||[];
    svg.innerHTML=routes.map((r)=>{const a=nodePositions[r.origin_id],b=nodePositions[r.destination_id];if(!a||!b)return'';return `<line x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}" class="network-line ${r.usable_now?'available':''} ${r.id===state.selectedRouteId?'selected':''}" data-route-line="${esc(r.id)}" />`;}).join('');
    nodes.innerHTML=(state.world?.locations||[]).map((loc)=>{const p=nodePositions[loc.id]||[50,50];return `<div class="network-node" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`;}).join('');
  }

  function renderLanes(){
    const items=state.lanes?.items||[];$('#laneCountBadge').textContent=`${items.length}本`;
    const rows=items.map((lane)=>{
      const blocked=(lane.blockers||[]).length;
      const stateText=lane.paused?'停止':blocked?'阻害':'稼働';
      const stateClass=lane.paused||blocked?'warn':'ok';
      return `<tr data-lane-row="${esc(lane.id)}"><td><div class="cell-main">${esc(locationName(lane.source_id))} → ${esc(locationName(lane.destination_id))}</div><div class="cell-sub">${esc(lane.id)} · ${esc(lane.path_policy)}</div></td><td>${fmt(lane.requested_capacity_t_per_day)} t/日</td><td>${fmt(lane.effective_capacity_t_per_day)} t/日</td><td>${fmt(lane.used_t)} t</td><td>${fmt(lane.queued_t)} t</td><td><span class="badge ${stateClass}">${stateText}</span><div class="cell-sub">${blocked?esc((lane.blockers||[]).map(A.userFacingText).join(' / ')):'blockerなし'}</div></td><td><div class="action-row"><button type="button" data-lane-toggle="${esc(lane.id)}" data-paused="${lane.paused?'1':'0'}">${lane.paused?'再開':'停止'}</button><button type="button" class="danger-button" data-lane-delete="${esc(lane.id)}">削除</button></div></td></tr>`;
    }).join('');
    $('#laneTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newLaneButton">Laneを作成</button></div><table><thead><tr><th>Lane</th><th>要求容量</th><th>実効容量</th><th>本日使用</th><th>待ち需要</th><th>状態</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="7">Laneなし。Domain DemandはLaneが作成されるまで輸送Order化されません。</td></tr>'}</tbody></table>`;
  }

  function renderDemands(){
    const items=state.demands||[];$('#demandCountBadge').textContent=`${items.length}件`;
    const rows=items.map((d)=>`<tr><td><div class="cell-main">${esc(ownerLabel(d.owner_kind))}</div><div class="cell-sub">${esc(d.owner_id)}</div></td><td>${esc(resourceName(d.resource_id))}</td><td>${d.source_id?esc(locationName(d.source_id)):'Lane選択'} → ${esc(locationName(d.destination_id))}</td><td>${fmt(d.requested_t)} t</td><td>${fmt(d.pipeline_t)} t</td><td>${fmt(d.remaining_t)} t</td><td>${d.priority}</td></tr>`).join('');
    $('#demandTable').innerHTML=`<table><thead><tr><th>発生元</th><th>資源</th><th>供給→需要地</th><th>要求</th><th>輸送系内</th><th>未充足</th><th>優先</th></tr></thead><tbody>${rows||'<tr><td colspan="7">現在のResource Demandなし</td></tr>'}</tbody></table>`;
  }

  function renderVehicles(){
    const items=state.vehicles?.items||[];$('#vehicleCountBadge').textContent=`${items.length}機`;
    const rows=items.map((v)=>`<tr><td><div class="cell-main">${esc(v.display_name)}</div><div class="cell-sub">${esc(v.id)}</div></td><td>${esc(locationName(v.location_id))}</td><td>${esc(stateLabels[v.status]||v.status)}</td><td>${fmt(v.propellant_t)}/${fmt(v.propellant_capacity_t)}</td><td>${fmt(v.payload_t)}t</td><td>${(v.blockers||[]).length}</td></tr>`).join('');
    $('#vehicleTable').innerHTML=`<table><thead><tr><th>機体</th><th>現在地</th><th>状態</th><th>推進剤</th><th>Payload</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="6">輸送資産なし</td></tr>'}</tbody></table>`;
  }
  function renderCargo(){
    const items=(state.orders?.items||[]).filter((o)=>o.owner_kind!=='contract');$('#cargoCountBadge').textContent=`${items.length}件`;
    const rows=items.map((o)=>{const origin=o.lane_id?`Lane自動 · ${ownerLabel(o.owner_kind)}`:'手動輸送';return `<tr><td>${esc(resourceName(o.resource_id))}<div class="cell-sub">${esc(origin)} · ${esc(o.id)}</div></td><td>${esc(locationName(o.source_id))} → ${esc(locationName(o.destination_id))}</td><td>${fmt(o.delivered_t)}/${fmt(o.amount_t)}t</td><td>${esc(stateLabels[o.status]||o.status)}</td><td>${(o.blockers||[]).length}</td></tr>`;}).join('');
    $('#cargoTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newCargoButton">単発資源輸送</button></div><table><thead><tr><th>資源</th><th>区間</th><th>配送済み/総量</th><th>状態</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="5">CargoOrderなし</td></tr>'}</tbody></table>`;
  }

  function renderRouteInspector(){
    const title=$('#routeInspectorTitle'),content=$('#routeInspectorContent');
    if(!state.selectedRouteId){title.textContent='輸送路を選択';content.innerHTML='<div class="empty-state">左の輸送路またはネットワーク上の接続を選択してください。</div>';return;}
    const route=(state.routes?.items||[]).find((r)=>r.id===state.selectedRouteId);if(!route)return;
    title.textContent=route.display_name;
    const blockers=[...new Map([...(route.blockers||[]),...(route.operational_blockers||[])].map((x)=>[JSON.stringify(x),x])).values()];
    const modes=(route.modes||[]).map((m)=>`<div class="route-mode-card ${m.usable_now?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name)}</span><span class="badge ${m.usable_now?'ok':'warn'}">${m.usable_now?'利用可':'利用不可'}</span></div><div class="cell-sub">${m.kind==='external_service'?'外部サービス':`ヴィークル · ${m.available_vehicle_count}機利用可`} · ${fmt(m.transit_days)}日 · ${fmt(m.dispatch_capacity_t)}t</div>${(m.blockers||[]).length?`<div class="issue-stack" style="margin-top:7px">${m.blockers.map(issueHtml).join('')}</div>`:''}</div>`).join('');
    content.innerHTML=section('区間',kv([['出発',esc(locationName(route.origin_id))],['到着',esc(locationName(route.destination_id))],['物理条件',route.available?'成立':'不成立'],['現在利用',route.usable_now?'はい':'いいえ'],['基準日数',fmt(route.transit_days)],['Δv',`${fmt(route.delta_v_km_s,2)} km/s`],['Dispatch能力',`${fmt(route.dispatch_capacity_t)} t`]]))+section('Operation',(route.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o)?o[0]:o))}</span>`).join(' ')||'—')+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('輸送方式 / ヴィークル',modes||'<div class="empty-state">方式情報なし</div>')+section('操作','<div class="action-stack"><button type="button" class="primary" id="routeLaneButton">この区間のLaneを作成</button><button type="button" id="routeCargoButton">この区間で単発輸送</button></div>');
  }

  function populateLocationSelects(){
    const locOpts=(state.world?.locations||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
    for(const id of ['cargoSource','cargoDestination','laneSource','laneDestination']){const el=$('#'+id);if(el){const value=el.value;el.innerHTML=locOpts;if([...el.options].some((o)=>o.value===value))el.value=value;}}
    const resource=$('#cargoResource');if(resource&&!resource.options.length)resource.innerHTML=(state.catalog?.resources||[]).map((r)=>`<option value="${esc(r.id)}">${esc(r.display_name)}</option>`).join('');
  }

  function modeLabel(mode){return mode.kind==='external_service'?`外部サービス: ${mode.display_name}`:`ヴィークル: ${mode.display_name} (${mode.available_vehicle_count}機利用可)`;}
  async function loadCargoPlans(){
    const source=$('#cargoSource').value,destination=$('#cargoDestination').value,planSelect=$('#cargoPlan'),legs=$('#cargoLegChoices');
    if(!source||!destination||source===destination){cargoPlans=null;planSelect.innerHTML='<option value="">出発地と到着地を指定</option>';legs.innerHTML='';return;}
    cargoPlans=await api(`/api/v1/transport-plans?source_id=${encodeURIComponent(source)}&destination_id=${encodeURIComponent(destination)}`);
    const options=cargoPlans?.options||[];
    planSelect.innerHTML=options.map((p,i)=>`<option value="${i}">${esc((p.path||[]).map((routeId)=>definitionName(routeId)).join(' → '))} · ${fmt(p.transit_days)}日 · ${fmt(p.estimated_cost_musd_per_t,2)} M$/t</option>`).join('')||'<option value="">現在実行可能な輸送計画なし</option>';
    const preferred=options.findIndex((p)=>p.policy===$('#cargoPolicy').value);if(preferred>=0)planSelect.value=String(preferred);renderCargoLegChoices();
  }
  function renderCargoLegChoices(){
    const options=cargoPlans?.options||[],plan=options[Number($('#cargoPlan').value||0)];
    if(!plan){$('#cargoLegChoices').innerHTML='<div class="empty-state">実行可能な輸送計画がありません。</div>';return;}
    const defaults=Object.fromEntries(plan.route_modes||[]);
    $('#cargoLegChoices').innerHTML=(plan.path||[]).map((routeId,index)=>{const route=(state.routes?.items||[]).find((r)=>r.id===routeId);if(!route)return'';const opts=(route.modes||[]).map((m)=>`<option value="${esc(m.id)}" ${m.id===defaults[routeId]?'selected':''} ${!m.usable_now?'disabled':''}>${esc(modeLabel(m))}${m.usable_now?'':' — 利用不可'}</option>`).join('');return `<div class="route-mode-card"><div class="mode-title"><span>Leg ${index+1}: ${esc(route.display_name)}</span></div><label>輸送方式 / ヴィークル<select data-cargo-route-mode="${esc(routeId)}">${opts}</select></label></div>`;}).join('');
  }
  async function openCargoDialog(route=null,contract=null){
    cargoContractId=contract?.id||null;populateLocationSelects();
    $('#cargoDialogTitle').textContent=contract?'契約貨物の輸送計画':'単発資源輸送';$('#cargoSubmitButton').textContent=contract?'契約輸送を開始':'輸送登録';
    for(const id of ['cargoSource','cargoDestination','cargoResource','cargoAmount'])$('#'+id).disabled=Boolean(contract);
    if(contract){$('#cargoSource').value=contract.source_id;$('#cargoDestination').value=contract.destination_id;$('#cargoResource').value=contract.resource_id;$('#cargoAmount').value=contract.cargo_t;}else if(route){$('#cargoSource').value=route.origin_id;$('#cargoDestination').value=route.destination_id;}
    $('#cargoDialog').showModal();try{await loadCargoPlans();}catch(e){banner(e.message,'error');}
  }
  function openLaneDialog(route=null){
    populateLocationSelects();
    if(route){$('#laneSource').value=route.origin_id;$('#laneDestination').value=route.destination_id;}
    $('#laneDialog').showModal();
  }

  function render(){
    if(!state.logisticsSummary||!state.routes)return;
    const s=state.logisticsSummary;
    $('#logisticsSummary').innerHTML=[['Lane',`${s.lane_count??(state.lanes?.items||[]).length}`],['Demand',`${s.demand_count??state.demands.length}`],['待ち需要',`${fmt(s.queued_demand_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');
    populateLocationSelects();renderRouteFilters();renderRouteList();renderNetwork();renderLanes();renderDemands();renderVehicles();renderCargo();renderRouteInspector();
  }

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='logistics')return;
    const routeBtn=event.target.closest('[data-route-id]');if(routeBtn){state.selectedRouteId=routeBtn.dataset.routeId;render();return;}
    const routeLine=event.target.closest('[data-route-line]');if(routeLine){state.selectedRouteId=routeLine.dataset.routeLine;render();return;}
    const network=event.target.closest('[data-network-location]');if(network){const id=network.dataset.networkLocation;$('#routeOriginFilter').value=id;renderRouteList();return;}
    if(event.target.closest('#newLaneButton')){openLaneDialog();return;}
    if(event.target.closest('#routeLaneButton')){openLaneDialog((state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId));return;}
    if(event.target.closest('#newCargoButton')){await openCargoDialog();return;}
    if(event.target.closest('#routeCargoButton')){await openCargoDialog((state.routes?.items||[]).find((x)=>x.id===state.selectedRouteId));return;}
    const toggle=event.target.closest('[data-lane-toggle]');if(toggle){try{await command(toggle.dataset.paused==='1'?'ResumeLogisticsLane':'PauseLogisticsLane',{lane_id:toggle.dataset.laneToggle});}catch{}return;}
    const del=event.target.closest('[data-lane-delete]');if(del){try{await command('DeleteLogisticsLane',{lane_id:del.dataset.laneDelete});}catch{}return;}
  });

  document.addEventListener('DOMContentLoaded',()=>{
    $('#routeOriginFilter').addEventListener('change',renderRouteList);$('#routeDestinationFilter').addEventListener('change',renderRouteList);
    $('#cargoSource').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoDestination').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoPolicy').addEventListener('change',()=>loadCargoPlans().catch((e)=>banner(e.message,'error')));$('#cargoPlan').addEventListener('change',renderCargoLegChoices);
    $('#cargoCloseButton').addEventListener('click',()=>$('#cargoDialog').close());$('#cargoCancelButton').addEventListener('click',()=>$('#cargoDialog').close());
    $('#laneCloseButton').addEventListener('click',()=>$('#laneDialog').close());$('#laneCancelButton').addEventListener('click',()=>$('#laneDialog').close());
    $('#laneForm').addEventListener('submit',async(event)=>{event.preventDefault();const source=$('#laneSource').value,destination=$('#laneDestination').value;if(source===destination){banner('Laneの出発地と到着地は異なる必要があります','error');return;}try{await command('CreateLogisticsLane',{source_id:source,destination_id:destination,requested_capacity_t_per_day:Number($('#laneCapacity').value),priority:Number($('#lanePriority').value),path:null,route_modes:[],path_policy:$('#lanePolicy').value});$('#laneDialog').close();banner('物流Laneを作成しました');}catch{}});
    $('#cargoForm').addEventListener('submit',async(event)=>{event.preventDefault();const options=cargoPlans?.options||[],plan=options[Number($('#cargoPlan').value||0)];if(!plan){banner('実行可能な輸送計画を選択してください','error');return;}const routeModes=$$('[data-cargo-route-mode]').map((sel)=>[sel.dataset.cargoRouteMode,sel.value]);try{if(cargoContractId)await command('DispatchContractCargo',{contract_id:cargoContractId,path:plan.path,route_modes:routeModes});else await command('SubmitCargo',{source_id:$('#cargoSource').value,destination_id:$('#cargoDestination').value,resource_id:$('#cargoResource').value,amount_t:Number($('#cargoAmount').value),priority:Number($('#cargoPriority').value),path:plan.path,route_modes:routeModes,path_policy:$('#cargoPolicy').value});$('#cargoDialog').close();cargoContractId=null;banner('単発輸送を登録しました');}catch{}});
  });

  window.SpaceIdleLogistics={render,openCargoDialog,openLaneDialog};
})();
