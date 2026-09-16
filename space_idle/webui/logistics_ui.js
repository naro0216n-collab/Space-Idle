(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before logistics_ui.js');
  const {state,$,esc,fmt,locationName,resourceName,definitionName,capabilityName,operationName,issueHtml,metricHtml,api,command,banner}=A;
  let editingAllocationId=null;
  let allocationOptionsView=null;
  let allocationOptionSerial=0;
  let relocationContext=null;
  let relocationPreviewSerial=0;
  let relocationPreviewKey=null;

  const ownerLabels={project:'建設',research:'研究',industry:'産業',facility_maintenance:'設備維持',vehicle_production:'機体建造',scientific_exploration:'科学探査',contract:'契約'};
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  const priorityOptions=(selected=3)=>[1,2,3,4,5].map((level)=>`<option value="${level}" ${Number(selected)===level?'selected':''}>${level} ${priorityLabels[level]}</option>`).join('');
  const priorityText=(value)=>`${Number(value)} ${priorityLabels[Number(value)]||''}`.trim();
  const ownerLabel=(kind)=>ownerLabels[kind]||kind;
  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const capText=(c)=>c?`${fmt(c.forward_t_per_day,2)} / ${fmt(c.reverse_t_per_day,2)} t/日`:'—';
  const infrastructureText=(rows)=>{const items=rows||[];return items.length?items.map((r)=>`${locationName(r.operational_node_id)}: ${capabilityName(r.capability_id)} (${r.required_state==='ACTIVE'?'Active':'Installed'})`).join(' / '):'追加Capability要件なし';};
  const policyLabels={fastest:'最速',lowest_propellant:'推進剤最少'};
  const policyLabel=(value)=>policyLabels[value]||value;
  const pathText=(path)=>{const rows=path||[];return rows.length?rows.map((id)=>definitionName(id)).join(' → '):'—';};
  const relocationKey=(destination,units,policy)=>`${destination}\u001f${units}\u001f${policy}`;

  function renderAllocationServiceOptions(view=allocationOptionsView){
    const root=$('#allocationServiceOptions');if(!root)return;
    if(!view){root.innerHTML='<div class="cell-sub">Transport Service候補を取得中…</div>';return;}
    const selectedVehicle=$('#allocationVehicle')?.value,selectedPolicy=$('#allocationPolicy')?.value;
    const cards=(view.options||[]).map((option)=>{
      const selected=option.vehicle_definition_id===selectedVehicle&&option.policy===selectedPolicy;
      const resources=(option.operational_supply_at_full_unit||[]).map(([locationId,resourceId,amount])=>`${locationName(locationId)}: ${resourceName(resourceId)} ${fmt(amount,2)} t/日`).join(' / ')||'追加運用Resourceなし';
      const blockers=(option.blockers||[]).length?`<div class="issue-stack">${option.blockers.map((b)=>issueHtml(['transport',b])).join('')}</div>`:'<span class="badge ok">Service成立</span>';
      return `<div class="detail-card ${selected?'is-usable':''}" data-allocation-option-card="${esc(option.vehicle_definition_id)}:${esc(option.policy)}"><div class="mode-title"><span>${esc(option.display_name)} · ${esc(policyLabel(option.policy))}</span><button type="button" class="secondary" data-allocation-option="${esc(option.vehicle_definition_id)}" data-allocation-option-policy="${esc(option.policy)}">${selected?'選択中':'この候補を選択'}</button></div>${kv([
        ['往路',esc(pathText(option.forward_path))],
        ['復路 / 回収',esc(pathText(option.reverse_path))],
        ['Nominal F/R',esc(capText(option.nominal_capacity))],
        ['Cycle / latency',`${fmt(option.cycle_days,1)} 日 / F ${fmt(option.forward_latency_days,0)} 日${option.reverse_latency_days==null?'':` / R ${fmt(option.reverse_latency_days,0)} 日`}`],
        ['Fleet',`${fmt(option.fleet_free_units,0)} free / ${fmt(option.fleet_total_units,0)} total`],
        ['Infrastructure',esc(infrastructureText(option.infrastructure_requirements))],
        ['Full-use Resource',esc(resources)],
      ])}${blockers}</div>`;
    }).join('');
    root.innerHTML=`<h3>Transport Service候補</h3><div class="cell-sub">Vehicle性能と経路・運用PolicyからApplicationが導出した候補です。戦略上異なる方式をここで比較して選択します。</div>${cards||'<div class="empty-state">候補なし</div>'}`;
  }

  async function updateAllocationServiceOptions(){
    if(!$('#allocationDialog')?.open)return;
    const source=$('#allocationSource').value,destination=$('#allocationDestination').value;
    const serial=++allocationOptionSerial;allocationOptionsView=null;
    if(!source||!destination||source===destination){
      const root=$('#allocationServiceOptions');if(root)root.innerHTML='<h3>Transport Service候補</h3><div class="cell-sub">異なる出発地と到着地を選択してください。</div>';
      return;
    }
    renderAllocationServiceOptions(null);
    try{
      const params=new URLSearchParams({source_id:source,destination_id:destination});
      const view=await api(`/api/v1/transport-allocation-options?${params}`);
      if(serial!==allocationOptionSerial||!$('#allocationDialog')?.open)return;
      allocationOptionsView=view;renderAllocationServiceOptions(view);
    }catch(err){
      if(serial===allocationOptionSerial&&$('#allocationDialog')?.open){
        const root=$('#allocationServiceOptions');if(root)root.innerHTML=`<h3>Transport Service候補</h3><div class="issue"><div class="issue-title">${esc(err.message||'候補を取得できません')}</div></div>`;
      }
    }
  }

  function renderRelocationPreview(preview){
    const root=$('#relocationPreview'),submit=$('#relocationSubmitButton');if(!root)return;
    if(!preview){relocationPreviewKey=null;root.innerHTML='<div class="cell-sub">移動計画を取得中…</div>';if(submit)submit.disabled=true;return;}
    relocationPreviewKey=relocationKey(preview.destination_id,preview.units,preview.path_policy);
    const resources=(preview.resource_requirements||[]).map((r)=>`<div class="cell-sub">${esc(locationName(r.operational_node_id))}: ${esc(resourceName(r.resource_id))} ${fmt(r.required_t,2)} t 必要 / ${fmt(r.available_t,2)} t 利用可能</div>`).join('')||'<div class="cell-sub">運用Resource消費なし</div>';
    const blockers=(preview.blockers||[]).map((row)=>`<div class="issue"><div class="issue-title">${esc(A.userFacingText(row))}</div></div>`).join('');
    root.innerHTML=`<h3>移動計画 <span class="badge ${preview.feasible?'ok':'warn'}">${preview.feasible?'実行可能':'blockerあり'}</span></h3>${kv([
      ['経路',(preview.path||[]).length?(preview.path||[]).map((id)=>esc(definitionName(id))).join(' → '):'—'],
      ['所要時間',preview.arrival_day===null?'—':`${fmt(preview.travel_days,0)} 日（Day ${fmt(preview.arrival_day,0)} 到着）`],
      ['Infrastructure',esc(infrastructureText(preview.infrastructure_requirements))],
    ])}<div class="cell-main">必要Resource</div>${resources}${blockers?`<div class="issue-list">${blockers}</div>`:'<div class="cell-sub">現在のblockerなし</div>'}`;
    if(submit){submit.disabled=!preview.feasible;submit.title=preview.feasible?'':(preview.blockers||[]).map(A.userFacingText).join(' / ');}
  }

  async function updateRelocationPreview(){
    if(!relocationContext||!$('#relocationDialog')?.open)return;
    const destination=$('#relocationDestination').value,units=Number($('#relocationUnits').value),policy=$('#relocationPolicy').value;
    const key=relocationKey(destination,units,policy);
    const serial=++relocationPreviewSerial;if(key!==relocationPreviewKey)renderRelocationPreview(null);
    try{
      const params=new URLSearchParams({vehicle_definition_id:relocationContext.vehicle_definition_id,source_id:relocationContext.source_id,destination_id:destination,units:String(units),path_policy:policy});
      const preview=await api(`/api/v1/logistics/fleet-relocation-preview?${params}`);
      if(serial===relocationPreviewSerial&&relocationContext)renderRelocationPreview(preview);
    }catch(err){if(serial===relocationPreviewSerial&&relocationContext){$('#relocationPreview').innerHTML=`<div class="issue"><div class="issue-title">${esc(err.message||'移動計画を取得できません')}</div></div>`;$('#relocationSubmitButton').disabled=true;}}
  }

  function logistics(){return state.logistics||{};}

  function renderMovementPlanFilters(){
    const locs=state.world?.operational_nodes||[];
    for(const [selId,label] of [['#movementPlanOriginFilter','全出発地'],['#movementPlanDestinationFilter','全到着地']]){
      const sel=$(selId); if(!sel)continue; const current=sel.value;
      sel.innerHTML=`<option value="">${label}</option>`+locs.map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
      if([...sel.options].some((o)=>o.value===current))sel.value=current;
    }
  }
  function filteredMovementPlans(){
    const origin=$('#movementPlanOriginFilter')?.value||'',dest=$('#movementPlanDestinationFilter')?.value||'';
    return (state.movementPlans?.items||[]).filter((r)=>(!origin||r.origin_id===origin)&&(!dest||r.destination_id===dest));
  }
  function renderMovementPlanList(){
    $('#movementPlanList').innerHTML=filteredMovementPlans().map((r)=>`<button type="button" class="movement-plan-button ${r.id===state.selectedMovementPlanId?'is-selected':''}" data-movement-plan-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="movement-plan-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.service_feasible_now?'ok':r.available?'warn':''}">${r.service_feasible_now?'Service可':r.available?'運用条件待ち':'Movement不成立'}</span></div></button>`).join('')||'<div class="empty-state">条件に一致するMovement Planなし</div>';
  }

  function networkPositions(locations){
    const groups=new Map();
    for(const loc of locations){
      const groupKey=loc.body_id||`unbound:${loc.id}`;
      if(!groups.has(groupKey))groups.set(groupKey,[]);
      groups.get(groupKey).push(loc);
    }
    const keys=[...groups.keys()].sort((a,b)=>a.localeCompare(b));
    const positions={};
    keys.forEach((key,groupIndex)=>{
      const members=groups.get(key).slice().sort((a,b)=>`${a.kind}:${a.display_name}:${a.id}`.localeCompare(`${b.kind}:${b.display_name}:${b.id}`));
      const x=keys.length===1?50:12+(76*groupIndex/(keys.length-1));
      members.forEach((loc,index)=>{
        const y=members.length===1?50:18+(64*index/(members.length-1));
        positions[loc.id]=[x,y];
      });
    });
    return positions;
  }
  function renderNetwork(){
    const svg=$('#networkSvg'),nodes=$('#networkNodes'),movementPlans=state.movementPlans?.items||[],locations=state.world?.operational_nodes||[],positions=networkPositions(locations);
    svg.innerHTML=movementPlans.map((r)=>{const a=positions[r.origin_id],b=positions[r.destination_id];if(!a||!b)return'';return `<line x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}" class="network-line ${r.service_feasible_now?'available':''} ${r.id===state.selectedMovementPlanId?'selected':''}" data-movement-plan-line="${esc(r.id)}" />`;}).join('');
    nodes.innerHTML=locations.map((loc)=>{const p=positions[loc.id]||[50,50];return `<div class="network-node" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`;}).join('');
  }

  function renderSupplyPolicies(){
    const policies=logistics().supply_policies||[],targets=logistics().target_stocks||[];
    $('#supplyPolicyCountBadge').textContent=`${policies.length}方針 / ${targets.length}目標`;
    const policyRows=policies.map((row)=>`<tr><td>${esc(locationName(row.destination_id))}</td><td>${esc(resourceName(row.resource_id))}</td><td>${row.preferred_source_id?esc(locationName(row.preferred_source_id)):'自動選択'}</td><td>${esc(policyLabel(row.path_policy))}</td><td><button type="button" class="danger-button" data-supply-policy-delete="${esc(row.destination_id)}" data-resource-id="${esc(row.resource_id)}">削除</button></td></tr>`).join('');
    const targetRows=targets.map((row)=>`<tr><td>${esc(locationName(row.destination_id))}</td><td>${esc(resourceName(row.resource_id))}</td><td>${fmt(row.target_quantity_t)} t</td><td>${esc(priorityText(row.priority))}</td><td><button type="button" class="danger-button" data-target-stock-delete="${esc(row.destination_id)}" data-resource-id="${esc(row.resource_id)}">削除</button></td></tr>`).join('');
    $('#supplyPolicyTable').innerHTML=`<div style="padding:8px" class="action-row"><button type="button" class="primary" id="newSupplyPolicyButton">Supply Policyを設定</button><button type="button" id="newTargetStockButton">Target Stockを設定</button></div><div class="cell-main" style="padding:8px">Supply Policy</div><table><thead><tr><th>需要地</th><th>資源</th><th>優先供給元</th><th>経路方針</th><th>操作</th></tr></thead><tbody>${policyRows||'<tr><td colspan="5">明示Supply Policyなし。利用可能な供給元を自動選択します。</td></tr>'}</tbody></table><div class="cell-main" style="padding:8px">Target Stock</div><table><thead><tr><th>需要地</th><th>資源</th><th>目標</th><th>優先度</th><th>操作</th></tr></thead><tbody>${targetRows||'<tr><td colspan="5">Target Stockなし</td></tr>'}</tbody></table>`;
  }

  function requirementStateLabel(d){return {local_covered:'現地充足',pipeline_covered:'輸送中で充足',no_source:'供給元なし',transport_blocked:'輸送能力阻害',source_shortage:'供給元不足',coverage_gap:'供給空白',low_runway:'猶予小',uncovered:'未充足'}[d.supply_state]||d.supply_state;}
  function renderRequirements(){
    const items=logistics().requirements||[];$('#requirementCountBadge').textContent=`${items.length}件`;
    const rows=items.map((d)=>{const runway=d.local_runway_days==null?'—':`${fmt(d.local_runway_days,1)}日`,forecast=d.forecast_requirement_day==null?'—':`Day ${fmt(d.forecast_requirement_day,0)}`,arrival=d.earliest_confirmed_arrival_day==null?'—':`Day ${fmt(d.earliest_confirmed_arrival_day,0)}`,gap=d.projected_gap_days==null?'—':`${fmt(d.projected_gap_days,1)}日`,stateClass=['local_covered','pipeline_covered'].includes(d.supply_state)?'ok':'warn';return `<tr><td><div class="cell-main">${esc(ownerLabel(d.owner_kind))}</div><div class="cell-sub">${esc(d.owner_id)}</div></td><td>${esc(resourceName(d.resource_id))}</td><td>${d.source_id?esc(locationName(d.source_id)):'Planner選択'} → ${esc(locationName(d.destination_id))}</td><td>${fmt(d.requested_t)} t<div class="cell-sub">現地 ${fmt(d.local_supply_t)} / 外部 ${fmt(d.external_required_t)} t</div></td><td>${esc(forecast)}</td><td>${fmt(d.pipeline_t)} t<div class="cell-sub">最短確定到着 ${esc(arrival)}</div></td><td>${fmt(d.remaining_t)} t<div class="cell-sub">猶予 ${esc(runway)} · gap ${esc(gap)}</div></td><td><span class="badge ${stateClass}">${esc(requirementStateLabel(d))}</span><div class="cell-sub">供給元 ${d.operational_source_count}/${d.candidate_source_count} · 在庫源 ${d.stocked_source_count}</div></td><td>${esc(priorityText(d.priority))}</td></tr>`;}).join('');
    $('#requirementTable').innerHTML=`<table><thead><tr><th>発生元</th><th>資源</th><th>供給→需要地</th><th>要求/現地</th><th>必要時期</th><th>輸送系内</th><th>未充足/猶予</th><th>供給状態</th><th>優先</th></tr></thead><tbody>${rows||'<tr><td colspan="9">現在のSupply Requirementなし</td></tr>'}</tbody></table>`;
  }

  function renderFleet(){
    const pools=state.fleet?.pools||logistics().fleet_pools||[]; const relocations=state.fleet?.relocations||logistics().relocations||[]; const releases=state.fleet?.releases||logistics().releases||[];
    $('#vehicleCountBadge').textContent=`${pools.reduce((n,p)=>n+Number(p.total_units||0),0)} unit`;
    const rows=pools.map((p)=>`<tr><td><div class="cell-main">${esc(p.display_name)}</div><div class="cell-sub">${esc(p.vehicle_definition_id)}</div></td><td>${esc(locationName(p.operational_node_id))}</td><td>${fmt(p.total_units,0)}</td><td>${fmt(p.free_units,0)}</td><td>${fmt(p.transport_units,0)}</td><td>${fmt(p.exploration_units,0)}</td><td>${fmt(p.other_reserved_units,0)}</td><td>${fmt(p.relocating_units,0)}</td><td>${fmt(p.releasing_units,0)}</td><td><button type="button" data-fleet-relocate="${esc(p.vehicle_definition_id)}" data-fleet-source="${esc(p.operational_node_id)}" data-fleet-free="${fmt(p.free_units,0)}" ${Number(p.free_units||0)<=0?'disabled title="free Fleetなし"':''}>移動</button></td></tr>`).join('');
    const relocationRows=relocations.map((r)=>`<div class="cell-sub">${esc(r.display_name)} ${fmt(r.units,0)} unit · ${esc(locationName(r.source_id))} → ${esc(locationName(r.destination_id))} · Day ${fmt(r.arrival_day,0)} 到着</div>`).join('');
    const releaseRows=releases.map((r)=>`<div class="cell-sub">${esc(r.display_name)} ${fmt(r.units,0)} unit · ${esc(locationName(r.operational_node_id))} · ${esc(r.allocation_id)} から回収中 · Day ${fmt(r.release_day,0)} 解放（残り ${fmt(r.remaining_days,0)}日）</div>`).join('');
    $('#vehicleTable').innerHTML=`<table><thead><tr><th>Vehicle type</th><th>所在地</th><th>総数</th><th>free</th><th>Transport</th><th>Exploration</th><th>その他拘束</th><th>relocating</th><th>releasing</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="10">Fleetなし</td></tr>'}</tbody></table>${relocationRows?`<div style="padding:8px"><strong>移動中</strong>${relocationRows}</div>`:''}${releaseRows?`<div style="padding:8px"><strong>回収中</strong>${releaseRows}</div>`:''}`;
  }

  function allocationTarget(a){return a.control_mode==='units'?`${fmt(a.target_units,0)} unit`:`F ${fmt(a.target_capacity?.forward_t_per_day,2)} / R ${fmt(a.target_capacity?.reverse_t_per_day,2)} t/日`;}
  function renderAllocations(){
    const items=state.transportAllocations?.items||logistics().allocations||[]; $('#allocationCountBadge').textContent=`${items.length}件`;
    const rows=items.map((a)=>{const blocked=(a.blockers||[]).length+(a.limiting_factors||[]).length;return `<tr data-allocation-row="${esc(a.id)}"><td><div class="cell-main">${esc(a.display_name)}</div><div class="cell-sub">${esc(locationName(a.anchor_node_id))} → ${esc(locationName(a.destination_id))} · ${esc(a.id)}</div><div class="cell-sub">Infrastructure: ${esc(infrastructureText(a.infrastructure_requirements))}</div><div class="cell-sub">Resource: ${(a.operational_supply||[]).map(([loc,rid,amount])=>`${esc(locationName(loc))} ${esc(resourceName(rid))} ${fmt(amount,2)} t/日`).join(' / ')||'追加運用Resourceなし'}</div></td><td><span class="badge">${esc(a.control_mode.toUpperCase())}</span><div class="cell-sub">正本: ${esc(allocationTarget(a))}</div></td><td>${fmt(a.active_units,0)} / ${fmt(a.required_units,0)}<div class="cell-sub">unfilled ${fmt(a.unfilled_units,0)}</div></td><td>${capText(a.nominal)}</td><td>${capText(a.available)}</td><td>${capText(a.used)}</td><td>${capText(a.spare)}</td><td>${fmt(a.cycle_days,1)}日<div class="cell-sub">latency ${fmt(a.forward_latency_days,0)}日</div></td><td>${blocked}<div class="cell-sub">${esc([...(a.blockers||[]),...(a.limiting_factors||[])].slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><div class="action-row"><button type="button" data-allocation-edit="${esc(a.id)}">設定</button><button type="button" data-allocation-mode="${esc(a.id)}" data-mode="${esc(a.control_mode)}">${a.control_mode==='units'?'CAPACITYへ':'UNITSへ'}</button><button type="button" data-allocation-toggle="${esc(a.id)}" data-paused="${a.paused?'1':'0'}">${a.paused?'再開':'停止'}</button><button type="button" class="danger-button" data-allocation-delete="${esc(a.id)}">削除</button></div></td></tr>`;}).join('');
    $('#allocationTable').innerHTML=`<div style="padding:8px"><button type="button" class="primary" id="newAllocationButton">Transport Allocationを作成</button></div><table><thead><tr><th>Service</th><th>control / target</th><th>active / required</th><th>Nominal F/R</th><th>Available F/R</th><th>Used F/R</th><th>Spare F/R</th><th>cycle</th><th>blocker</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="10">Transport Allocationなし。Fleetはfreeのままです。</td></tr>'}</tbody></table>`;
  }

  function renderVehicleProduction(){
    const projects=logistics().vehicle_production||[],options=logistics().vehicle_production_options||[]; $('#vehicleProductionCountBadge').textContent=`${projects.length}件`;
    const projectRows=projects.map((p)=>{const blockers=p.blockers||[],toggle=p.phase==='complete'?'<span class="badge ok">完成</span>':`<button type="button" data-production-toggle="${esc(p.id)}" data-paused="${p.paused?'1':'0'}">${p.paused?'再開':'停止'}</button>`;return `<tr data-production-project-row="${esc(p.id)}"><td><div class="cell-main">${esc(p.display_name)}</div><div class="cell-sub">${esc(locationName(p.operational_node_id))}</div></td><td>${esc(p.phase)}</td><td>${fmt(p.progress_days,1)}/${fmt(p.required_days,1)}日</td><td><select data-production-priority-value data-draft-key="production:${esc(p.id)}:priority" ${p.priority_editable?'':'disabled'}>${priorityOptions(p.priority??3)}</select></td><td>${blockers.length}<div class="cell-sub">${esc(blockers.slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><div class="action-row">${toggle}${p.phase==='complete'?'':`<button type="button" data-production-settings="${esc(p.id)}" ${p.priority_editable?'':'disabled'}>設定適用</button>`}</div></td></tr>`;}).join('');
    const optionRows=options.map((o)=>`<tr data-production-option-row><td><div class="cell-main">${esc(o.display_name)}</div><div class="cell-sub">${esc(locationName(o.operational_node_id))}</div></td><td>${fmt(o.production_days,1)}日</td><td>${(o.resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)}t`).join(' / ')}</td><td><select data-production-priority-value data-draft-key="production-option:${esc(o.vehicle_definition_id)}:${esc(o.operational_node_id)}:priority">${priorityOptions(3)}</select></td><td>${(o.blockers||[]).length}<div class="cell-sub">${esc((o.blockers||[]).slice(0,2).map(A.userFacingText).join(' / '))}</div></td><td><button type="button" data-produce-vehicle="${esc(o.vehicle_definition_id)}" data-production-location="${esc(o.operational_node_id)}" ${o.can_plan?'':'disabled'}>建造</button></td></tr>`).join('');
    $('#vehicleProductionTable').innerHTML=`<table><thead><tr><th>建造中</th><th>進捗</th><th>状態</th><th>優先度</th><th>blocker</th><th>操作</th></tr></thead><tbody>${projectRows||'<tr><td colspan="6">建造中Vehicleなし</td></tr>'}</tbody></table><table><thead><tr><th>建造候補</th><th>期間</th><th>必要資源</th><th>優先度</th><th>blocker</th><th>操作</th></tr></thead><tbody>${optionRows||'<tr><td colspan="6">建造候補なし</td></tr>'}</tbody></table>`;
  }

  function numberOrNull(input){const raw=input?.value?.trim();return raw===''?null:Number(raw);}
  function marketOfferRows(){
    return (state.market?.interfaces||[]).flatMap((iface)=>(iface.offers||[]).map((offer)=>({iface,offer})));
  }
  function marketResourceOptions(){
    const seen=new Set();const rows=[];
    for(const {offer} of marketOfferRows()){
      if(seen.has(offer.resource_id))continue;seen.add(offer.resource_id);
      rows.push(`<option value="${esc(offer.resource_id)}">${esc(resourceName(offer.resource_id))}</option>`);
    }
    return rows.join('');
  }
  function marketInterfaceOptions(){
    return (state.market?.interfaces||[]).map((row)=>`<option value="${esc(row.id)}">${esc(row.provider_name)} · ${esc(locationName(row.operational_node_id))}</option>`).join('');
  }
  function marketTargetFields(prefix,mode,quantity,rate){
    const q=quantity==null?'':quantity,r=rate==null?'':rate;
    return `<select data-market-mode data-draft-key="${prefix}:mode"><option value="quantity" ${mode==='quantity'?'selected':''}>QUANTITY</option><option value="rate" ${mode==='rate'?'selected':''}>RATE / 日</option></select><input data-market-target type="number" min="0" step="0.01" value="${esc(mode==='rate'?r:q)}" data-draft-key="${prefix}:target">`;
  }
  function renderMarket(){
    const market=state.market;if(!market)return;
    $('#marketFundsBadge').textContent=`$${fmt(market.funds_available_musd,2)}M available`;
    const offerRows=(market.interfaces||[]).flatMap((iface)=>(iface.offers||[]).map((offer)=>`<tr><td><div class="cell-main">${esc(iface.provider_name)}</div><div class="cell-sub">${esc(locationName(iface.operational_node_id))}${iface.enabled?'':' · 停止'}</div></td><td>${esc(resourceName(offer.resource_id))}</td><td>${offer.buy_price_musd_per_t==null?'—':`$${fmt(offer.buy_price_musd_per_t,2)}M/t`}<div class="cell-sub">供給 ${fmt(offer.provider_supply_available_t,2)} t</div></td><td>${offer.sell_price_musd_per_t==null?'—':`$${fmt(offer.sell_price_musd_per_t,2)}M/t`}<div class="cell-sub">需要 ${fmt(offer.provider_demand_available_t,2)} t</div></td></tr>`)).join('');
    const orderRows=(market.orders||[]).map((row)=>{
      const blockers=(row.blockers||[]).map(A.userFacingText);const limiting=(row.limiting_factors||[]).map(A.userFacingText);
      const progress=row.direction==='sell'?`settled ${fmt(row.settled_quantity_t,2)} / presented ${fmt(row.presented_quantity_t,2)} / in-flight ${fmt(row.in_flight_quantity_t,2)}`:`settled ${fmt(row.settled_quantity_t,2)} / committed ${fmt(row.committed_quantity_t,2)}`;
      return `<tr data-market-order-row="${esc(row.id)}"><td><div class="cell-main">${row.direction==='buy'?'Buy':'Sell'} ${esc(resourceName(row.resource_id))}</div><div class="cell-sub">${esc(row.id)} · ${esc(definitionName(row.market_interface_id))}</div></td><td>${row.current_offer_price_musd_per_t==null?'—':`$${fmt(row.current_offer_price_musd_per_t,2)}M/t`}<div class="cell-sub">条件 ${row.price_limit_musd_per_t==null?'なし':`$${fmt(row.price_limit_musd_per_t,2)}M/t`}</div></td><td>${marketTargetFields(`market:${esc(row.id)}`,row.control_mode,row.quantity_target_t,row.rate_target_t_per_day)}</td><td><select data-market-priority data-draft-key="market:${esc(row.id)}:priority">${priorityOptions(row.priority)}</select><input data-market-price type="number" min="0" step="0.01" value="${row.price_limit_musd_per_t==null?'':esc(row.price_limit_musd_per_t)}" placeholder="価格条件なし" data-draft-key="market:${esc(row.id)}:price"></td><td>${esc(progress)}${blockers.length?`<div class="cell-sub">blocker: ${esc(blockers.join(' / '))}</div>`:''}${limiting.length?`<div class="cell-sub">limiting: ${esc(limiting.join(' / '))}</div>`:''}</td><td><div class="action-row"><button type="button" data-market-save="${esc(row.id)}">設定適用</button><button type="button" class="danger-button" data-market-cancel="${esc(row.id)}">取消</button></div></td></tr>`;
    }).join('');
    const commitmentRows=(market.buy_commitments||[]).map((row)=>`<tr><td>${esc(resourceName(row.resource_id))}<div class="cell-sub">${esc(row.id)} / ${esc(row.order_id)}</div></td><td>${fmt(row.remaining_quantity_t,2)} t</td><td>$${fmt(row.committed_price_musd_per_t,2)}M/t</td><td>$${fmt(row.reserved_funds_musd,2)}M</td><td>Day ${fmt(row.maturity_day,0)}</td><td>${esc((row.blockers||[]).map(A.userFacingText).join(' / ')||'なし')}</td></tr>`).join('');
    const canCreate=(market.interfaces||[]).length&&marketOfferRows().length;
    const createCard=`<div class="detail-card" data-new-market-order><div class="mode-title"><span>Trade Order作成</span></div>${kv([
      ['Market Interface',`<select data-market-interface data-draft-key="market:new:interface">${marketInterfaceOptions()}</select>`],
      ['Direction','<select data-market-direction data-draft-key="market:new:direction"><option value="buy">Buy</option><option value="sell">Sell</option></select>'],
      ['Resource',`<select data-market-resource data-draft-key="market:new:resource">${marketResourceOptions()}</select>`],
      ['Control',marketTargetFields('market:new','quantity',0,null)],
      ['Priority',`<select data-market-priority data-draft-key="market:new:priority">${priorityOptions(3)}</select>`],
      ['Price condition','<input data-market-price type="number" min="0" step="0.01" placeholder="Buy上限 / Sell下限" data-draft-key="market:new:price">'],
    ])}<button type="button" class="primary" data-market-create ${canCreate?'':'disabled'}>Trade Order作成</button></div>`;
    $('#marketPanel').innerHTML=`<div style="padding:8px">${kv([['Funds total',`$${fmt(market.funds_total_musd,2)}M`],['Funds available',`$${fmt(market.funds_available_musd,2)}M`]])}<h4>Market Offer / finite availability</h4><div class="table-wrap"><table><thead><tr><th>Provider / Interface</th><th>Resource</th><th>Buy</th><th>Sell</th></tr></thead><tbody>${offerRows||'<tr><td colspan="4">利用可能Market offerなし</td></tr>'}</tbody></table></div><h4>Trade Order</h4><div class="table-wrap"><table><thead><tr><th>Order</th><th>Offer / 条件</th><th>Target</th><th>Priority / 価格</th><th>進捗 / blocker</th><th>操作</th></tr></thead><tbody>${orderRows||'<tr><td colspan="6">Trade Orderなし</td></tr>'}</tbody></table></div>${createCard}<h4>Buy Commitment</h4><div class="table-wrap"><table><thead><tr><th>Resource</th><th>未settle</th><th>commit価格</th><th>予約Funds</th><th>maturity</th><th>Admission blocker</th></tr></thead><tbody>${commitmentRows||'<tr><td colspan="6">Buy Commitmentなし</td></tr>'}</tbody></table></div></div>`;
  }
  function marketOrderPayload(root,{create=false}={}){
    const mode=root.querySelector('[data-market-mode]')?.value||'quantity';
    const target=Number(root.querySelector('[data-market-target]')?.value||0);
    const payload={priority:Number(root.querySelector('[data-market-priority]')?.value||3),control_mode:mode,quantity_target_t:mode==='quantity'?target:null,rate_target_t_per_day:mode==='rate'?target:null,price_limit_musd_per_t:numberOrNull(root.querySelector('[data-market-price]'))};
    if(create){payload.direction=root.querySelector('[data-market-direction]').value;payload.resource_id=root.querySelector('[data-market-resource]').value;payload.market_interface_id=root.querySelector('[data-market-interface]').value;}
    return payload;
  }

  function renderCargoFlows(){
    const cargo=state.cargoFlows?.items||logistics().cargo_flows||[];
    $('#cargoCountBadge').textContent=`${cargo.length}件`;
    const cargoRows=cargo.map((f)=>`<tr><td><div class="cell-main">${esc(resourceName(f.resource_id))}</div><div class="cell-sub">${esc(ownerLabel(f.owner_kind))} · ${esc(f.owner_id)}</div></td><td>${esc(locationName(f.source_id))} → ${esc(locationName(f.destination_id))}</td><td>${fmt(f.amount_t)} t</td><td>${esc(f.status)}</td><td>Day ${fmt(f.departure_day,0)} → ${fmt(f.ready_day,0)}</td><td>${esc((f.service_ids||[]).map(definitionName).join(' → '))}</td><td>${esc((f.admission_blockers||[]).map(A.userFacingText).join(' / ')||'なし')}</td></tr>`).join('');
    $('#cargoTable').innerHTML=`<table><thead><tr><th>資源 / 発生元</th><th>区間</th><th>量</th><th>状態</th><th>dispatch / arrival</th><th>Service path</th><th>入庫blocker</th></tr></thead><tbody>${cargoRows||'<tr><td colspan="7">輸送中・到着待機Cargo Flowなし</td></tr>'}</tbody></table>`;
  }

  function renderMovementPlanInspector(){
    const title=$('#movementPlanInspectorTitle'),content=$('#movementPlanInspectorContent');
    if(!state.selectedMovementPlanId){title.textContent='Movement Planを選択';content.innerHTML='<div class="empty-state">左のMovement Planまたはネットワーク上の接続を選択してください。</div>';return;}
    const movementPlan=(state.movementPlans?.items||[]).find((row)=>row.id===state.selectedMovementPlanId);if(!movementPlan)return;
    title.textContent=movementPlan.display_name;
    const modes=(movementPlan.modes||[]).map((m)=>`<div class="detail-card ${m.service_feasible?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name)}</span><span class="badge ${m.service_feasible?'ok':'warn'}">${m.service_feasible?'Service可':'阻害'}</span></div><div class="cell-sub">Fleet total ${fmt(m.fleet_total_units,0)} / free ${fmt(m.fleet_free_units,0)} · nominal ${capText(m.nominal_capacity)} · cycle ${m.cycle_days==null?'—':fmt(m.cycle_days,1)+'日'}</div><div class="cell-sub">Infrastructure: ${esc(infrastructureText(m.infrastructure_requirements))}</div>${(m.blockers||[]).length?`<div class="issue-stack">${m.blockers.map((b)=>issueHtml(['transport',b])).join('')}</div>`:''}</div>`).join('');
    const endpointText=(endpoint)=>endpoint?`${locationName(endpoint.node_id)} · ${endpoint.locator_kind}:${endpoint.locator_id}${endpoint.surface_cell_id?` · cell ${endpoint.surface_cell_id}`:''}`:'—';
    const segmentRows=[['出発',esc(endpointText(movementPlan.origin_endpoint))],['到着',esc(endpointText(movementPlan.destination_endpoint))],['Movement条件',movementPlan.available?'成立':'不成立'],['Service成立',movementPlan.service_feasible_now?'はい':'いいえ']];
    if(movementPlan.same_body_surface&&movementPlan.distance_km!=null)segmentRows.push(['地表距離',`${fmt(movementPlan.distance_km,1)} km`]);else segmentRows.push(['基準日数',fmt(movementPlan.transit_days)]);
    segmentRows.push(['Δv',`${fmt(movementPlan.delta_v_km_s,2)} km/s`]);
    content.innerHTML=section('区間',kv(segmentRows))+section('Operation',(movementPlan.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o)?o[0]:o))}</span>`).join(' ')||'—')+section('Blocker',(movementPlan.blockers||[]).length?`<div class="issue-stack">${movementPlan.blockers.map((b)=>issueHtml(['transport',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+section('Service候補',modes||'<div class="empty-state">候補なし</div>')+section('操作','<div class="action-stack"><button type="button" class="primary" id="movementPlanAllocationButton">この関係へFleetを配分</button><button type="button" id="movementPlanSupplyPolicyButton">この関係を優先供給元に設定</button></div>');
  }

  function populateLocationSelects(){
    const opts=(state.world?.operational_nodes||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
    for(const id of ['supplyPolicyDestination','targetStockDestination','allocationSource','allocationDestination','relocationDestination']){const el=$('#'+id);if(el){const current=el.value;el.innerHTML=opts;if([...el.options].some((o)=>o.value===current))el.value=current;}}
    const source=$('#supplyPolicySource');if(source){const current=source.value;source.innerHTML='<option value="">自動選択</option>'+opts;if([...source.options].some((o)=>o.value===current))source.value=current;}
    const resourceOpts=(state.catalog?.resources||[]).map((row)=>`<option value="${esc(row.id)}">${esc(row.display_name)}</option>`).join('');
    for(const id of ['supplyPolicyResource','targetStockResource']){const el=$('#'+id);if(el){const current=el.value;el.innerHTML=resourceOpts;if([...el.options].some((o)=>o.value===current))el.value=current;}}
    const vehicle=$('#allocationVehicle'); if(vehicle){const current=vehicle.value;vehicle.innerHTML=(state.catalog?.vehicles||[]).map((v)=>`<option value="${esc(v.id)}">${esc(v.display_name)}</option>`).join('');if([...vehicle.options].some((o)=>o.value===current))vehicle.value=current;}
  }
  function openSupplyPolicyDialog(movementPlan=null){
    populateLocationSelects();
    if(movementPlan){$('#supplyPolicySource').value=movementPlan.origin_id;$('#supplyPolicyDestination').value=movementPlan.destination_id;}
    $('#supplyPolicyDialog').showModal();
  }
  function openTargetStockDialog(){populateLocationSelects();$('#targetStockDialog').showModal();}

  function updateAllocationModeFields(){const capacity=$('#allocationMode').value==='capacity';$('#allocationUnitsGroup').hidden=capacity;$('#allocationCapacityGroup').hidden=!capacity;}
  function openAllocationDialog(movementPlan=null,allocation=null){
    editingAllocationId=allocation?.id||null;allocationOptionsView=null;allocationOptionSerial++;populateLocationSelects();const editing=Boolean(allocation);
    $('#allocationDialog h2').textContent=editing?'Transport Allocationを編集':'Fleetを輸送へ配分';
    $('#allocationForm button[type="submit"]').textContent=editing?'設定を更新':'Allocation作成';
    for(const id of ['allocationVehicle','allocationSource','allocationDestination','allocationMode'])$('#'+id).disabled=editing;
    if(allocation){
      $('#allocationVehicle').value=allocation.vehicle_definition_id;$('#allocationSource').value=allocation.anchor_node_id;$('#allocationDestination').value=allocation.destination_id;$('#allocationMode').value=allocation.control_mode;$('#allocationPriority').value=String(allocation.provisioning_priority);$('#allocationPolicy').value=allocation.path_policy;
      if(allocation.control_mode==='units')$('#allocationUnits').value=String(allocation.target_units??0);else{$('#allocationForward').value=String(allocation.target_capacity?.forward_t_per_day??0);$('#allocationReverse').value=String(allocation.target_capacity?.reverse_t_per_day??0);}
    }else if(movementPlan){$('#allocationSource').value=movementPlan.origin_id;$('#allocationDestination').value=movementPlan.destination_id;}
    else if($('#allocationSource').value===$('#allocationDestination').value){const other=[...$('#allocationDestination').options].find((o)=>o.value!==$('#allocationSource').value);if(other)$('#allocationDestination').value=other.value;}
    updateAllocationModeFields();$('#allocationDialog').showModal();updateAllocationServiceOptions();
  }
  function openRelocationDialog(vehicleDefinitionId,sourceId,freeUnits){
    relocationContext={vehicle_definition_id:vehicleDefinitionId,source_id:sourceId};relocationPreviewKey=null;populateLocationSelects();
    $('#relocationVehicle').textContent=definitionName(vehicleDefinitionId);$('#relocationSource').textContent=locationName(sourceId);$('#relocationFree').textContent=String(freeUnits);$('#relocationUnits').max=String(freeUnits);$('#relocationUnits').value=String(Math.min(1,Number(freeUnits)));
    const destination=$('#relocationDestination');if(destination.value===sourceId){const other=[...destination.options].find((o)=>o.value!==sourceId);if(other)destination.value=other.value;}
    $('#relocationDialog').showModal();
    updateRelocationPreview();
  }

  function render(){
    if(!state.logisticsSummary||!state.movementPlans)return;const s=state.logisticsSummary;
    $('#logisticsSummary').innerHTML=[['Fleet',`${s.free_fleet_units}/${s.fleet_units} free`],['Allocation',`${s.allocation_count} · 未充足 ${s.unfilled_allocation_units}`],['Supply Policy',`${s.supply_policy_count}`],['Target Stock',`${s.target_stock_count}`],['Requirement',`${s.requirement_count}`],['待ち供給',`${fmt(s.queued_supply_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');
    populateLocationSelects();renderMovementPlanFilters();renderMovementPlanList();renderNetwork();renderSupplyPolicies();renderRequirements();renderFleet();renderAllocations();renderVehicleProduction();renderCargoFlows();renderMarket();renderMovementPlanInspector();
  }

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='logistics')return;
    const movementPlanButton=event.target.closest('[data-movement-plan-id]');if(movementPlanButton){state.selectedMovementPlanId=movementPlanButton.dataset.movementPlanId;render();return;}
    const movementPlanLine=event.target.closest('[data-movement-plan-line]');if(movementPlanLine){state.selectedMovementPlanId=movementPlanLine.dataset.movementPlanLine;render();return;}
    const network=event.target.closest('[data-network-location]');if(network){$('#movementPlanOriginFilter').value=network.dataset.networkLocation;renderMovementPlanList();return;}
    if(event.target.closest('#newSupplyPolicyButton')){openSupplyPolicyDialog();return;} if(event.target.closest('#newTargetStockButton')){openTargetStockDialog();return;} if(event.target.closest('#movementPlanSupplyPolicyButton')){openSupplyPolicyDialog((state.movementPlans?.items||[]).find((x)=>x.id===state.selectedMovementPlanId));return;}
    if(event.target.closest('#newAllocationButton')){openAllocationDialog();return;} if(event.target.closest('#movementPlanAllocationButton')){openAllocationDialog((state.movementPlans?.items||[]).find((x)=>x.id===state.selectedMovementPlanId));return;}
    const allocationEdit=event.target.closest('[data-allocation-edit]');if(allocationEdit){const a=(state.transportAllocations?.items||[]).find((x)=>x.id===allocationEdit.dataset.allocationEdit);if(a)openAllocationDialog(null,a);return;}
    const allocationOption=event.target.closest('[data-allocation-option]');if(allocationOption){$('#allocationVehicle').value=allocationOption.dataset.allocationOption;$('#allocationPolicy').value=allocationOption.dataset.allocationOptionPolicy;renderAllocationServiceOptions();return;}
    const relocate=event.target.closest('[data-fleet-relocate]');if(relocate){openRelocationDialog(relocate.dataset.fleetRelocate,relocate.dataset.fleetSource,Number(relocate.dataset.fleetFree));return;}
    const allocationMode=event.target.closest('[data-allocation-mode]');if(allocationMode){try{await command('ChangeTransportAllocationMode',{allocation_id:allocationMode.dataset.allocationMode,control_mode:allocationMode.dataset.mode==='units'?'capacity':'units'});}catch{}return;}
    const allocationToggle=event.target.closest('[data-allocation-toggle]');if(allocationToggle){try{await command(allocationToggle.dataset.paused==='1'?'ResumeTransportAllocation':'PauseTransportAllocation',{allocation_id:allocationToggle.dataset.allocationToggle});}catch{}return;}
    const allocationDelete=event.target.closest('[data-allocation-delete]');if(allocationDelete){try{await command('DeleteTransportAllocation',{allocation_id:allocationDelete.dataset.allocationDelete});}catch{}return;}
    const produce=event.target.closest('[data-produce-vehicle]');if(produce){const row=produce.closest('[data-production-option-row]');try{await command('ProduceVehicle',{vehicle_definition_id:produce.dataset.produceVehicle,operational_node_id:produce.dataset.productionLocation,priority:Number(row.querySelector('[data-production-priority-value]').value)});}catch{}return;}
    const productionToggle=event.target.closest('[data-production-toggle]');if(productionToggle){try{await command(productionToggle.dataset.paused==='1'?'ResumeVehicleProduction':'PauseVehicleProduction',{production_id:productionToggle.dataset.productionToggle});}catch{}return;}
    const productionSettings=event.target.closest('[data-production-settings]');if(productionSettings){const row=productionSettings.closest('[data-production-project-row]');try{await command('SetVehicleProductionSettings',{production_id:productionSettings.dataset.productionSettings,priority:Number(row.querySelector('[data-production-priority-value]').value)});}catch{}return;}
    const marketCreate=event.target.closest('[data-market-create]');if(marketCreate){const root=marketCreate.closest('[data-new-market-order]');try{await command('CreateTradeOrder',marketOrderPayload(root,{create:true}));}catch{}return;}
    const marketSave=event.target.closest('[data-market-save]');if(marketSave){const root=marketSave.closest('[data-market-order-row]');try{await command('UpdateTradeOrder',{order_id:marketSave.dataset.marketSave,...marketOrderPayload(root)});}catch{}return;}
    const marketCancel=event.target.closest('[data-market-cancel]');if(marketCancel){try{await command('CancelTradeOrder',{order_id:marketCancel.dataset.marketCancel});}catch{}return;}
    const supplyDelete=event.target.closest('[data-supply-policy-delete]');if(supplyDelete){try{await command('DeleteSupplyPolicy',{destination_id:supplyDelete.dataset.supplyPolicyDelete,resource_id:supplyDelete.dataset.resourceId});}catch{}return;}
    const targetDelete=event.target.closest('[data-target-stock-delete]');if(targetDelete){try{await command('DeleteTargetStock',{destination_id:targetDelete.dataset.targetStockDelete,resource_id:targetDelete.dataset.resourceId});}catch{}return;}
  });

  document.addEventListener('DOMContentLoaded',()=>{
    $('#movementPlanOriginFilter').addEventListener('change',renderMovementPlanList);$('#movementPlanDestinationFilter').addEventListener('change',renderMovementPlanList);
    $('#supplyPolicyCloseButton').addEventListener('click',()=>$('#supplyPolicyDialog').close());$('#supplyPolicyCancelButton').addEventListener('click',()=>$('#supplyPolicyDialog').close());
    $('#supplyPolicyForm').addEventListener('submit',async(event)=>{event.preventDefault();const destination=$('#supplyPolicyDestination').value,source=$('#supplyPolicySource').value;if(source&&source===destination){banner('供給元と需要地は異なる必要があります','error');return;}try{await command('SetSupplyPolicy',{destination_id:destination,resource_id:$('#supplyPolicyResource').value,preferred_source_id:source||null,path_policy:$('#supplyPolicyPathPolicy').value,explicit_path:null});$('#supplyPolicyDialog').close();}catch{}});
    $('#targetStockCloseButton').addEventListener('click',()=>$('#targetStockDialog').close());$('#targetStockCancelButton').addEventListener('click',()=>$('#targetStockDialog').close());
    $('#targetStockForm').addEventListener('submit',async(event)=>{event.preventDefault();try{await command('SetTargetStock',{destination_id:$('#targetStockDestination').value,resource_id:$('#targetStockResource').value,target_quantity_t:Number($('#targetStockQuantity').value),priority:Number($('#targetStockPriority').value)});$('#targetStockDialog').close();}catch{}});
    $('#allocationMode').addEventListener('change',updateAllocationModeFields);$('#allocationVehicle').addEventListener('change',()=>renderAllocationServiceOptions());$('#allocationPolicy').addEventListener('change',()=>renderAllocationServiceOptions());$('#allocationSource').addEventListener('change',updateAllocationServiceOptions);$('#allocationDestination').addEventListener('change',updateAllocationServiceOptions);$('#allocationCloseButton').addEventListener('click',()=>{editingAllocationId=null;allocationOptionSerial++;allocationOptionsView=null;$('#allocationDialog').close();});$('#allocationCancelButton').addEventListener('click',()=>{editingAllocationId=null;allocationOptionSerial++;allocationOptionsView=null;$('#allocationDialog').close();});
    $('#allocationForm').addEventListener('submit',async(event)=>{event.preventDefault();const mode=$('#allocationMode').value;try{if(editingAllocationId){const payload={allocation_id:editingAllocationId,provisioning_priority:Number($('#allocationPriority').value),path_policy:$('#allocationPolicy').value};if(mode==='units')payload.target_units=Number($('#allocationUnits').value);else{payload.target_forward_t_per_day=Number($('#allocationForward').value);payload.target_reverse_t_per_day=Number($('#allocationReverse').value);}await command('UpdateTransportAllocation',payload);editingAllocationId=null;}else{const payload={vehicle_definition_id:$('#allocationVehicle').value,anchor_node_id:$('#allocationSource').value,destination_id:$('#allocationDestination').value,provisioning_priority:Number($('#allocationPriority').value),control_mode:mode,path:null,path_policy:$('#allocationPolicy').value};if(mode==='units')payload.target_units=Number($('#allocationUnits').value);else{payload.target_forward_t_per_day=Number($('#allocationForward').value);payload.target_reverse_t_per_day=Number($('#allocationReverse').value);}await command('CreateTransportAllocation',payload);}$('#allocationDialog').close();}catch{}});
    $('#relocationCloseButton').addEventListener('click',()=>{relocationContext=null;relocationPreviewKey=null;relocationPreviewSerial++;$('#relocationDialog').close();});$('#relocationCancelButton').addEventListener('click',()=>{relocationContext=null;relocationPreviewKey=null;relocationPreviewSerial++;$('#relocationDialog').close();});
    $('#relocationDestination').addEventListener('change',updateRelocationPreview);$('#relocationUnits').addEventListener('input',updateRelocationPreview);$('#relocationPolicy').addEventListener('change',updateRelocationPreview);
    $('#relocationForm').addEventListener('submit',async(event)=>{event.preventDefault();if(!relocationContext)return;const destination=$('#relocationDestination').value;if(destination===relocationContext.source_id){banner('Fleet移動の出発地と到着地は異なる必要があります','error');return;}try{await command('RelocateFleet',{vehicle_definition_id:relocationContext.vehicle_definition_id,units:Number($('#relocationUnits').value),source_id:relocationContext.source_id,destination_id:destination,path:null,path_policy:$('#relocationPolicy').value});relocationContext=null;relocationPreviewKey=null;$('#relocationDialog').close();}catch{}});
  });

  document.addEventListener('spaceidle:snapshot',()=>{if(relocationContext&&$('#relocationDialog')?.open)updateRelocationPreview();});

  window.SpaceIdleLogistics={render,openSupplyPolicyDialog,openTargetStockDialog,openAllocationDialog};
})();
