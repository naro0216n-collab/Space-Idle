(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before logistics_ui.js');
  const {state,$,esc,fmt,locationName,resourceName,definitionName,capabilityName,operationName,playerTerm,issueHtml,metricHtml,api,command,banner}=A;
  let editingAllocationId=null;
  let editingRoutingConstraintScope=null;
  let routingConstraintDraftScope=null;
  let routingConstraintViaSelection=new Set();
  let routingConstraintAllocationSelection=new Set();
  let targetStockOptionsView=null;
  let targetStockOptionsSerial=0;
  let allocationOptionsView=null;
  let allocationOptionSerial=0;
  let allocationMovementSelection=[];
  let allocationCapacityInitialized=false;
  let allocationPreviewSerial=0;
  let allocationPreviewTimer=null;
  let relocationContext=null;
  let relocationPreviewSerial=0;
  let relocationPreviewKey=null;

  const ownerLabels={project:'建設',founding:'拠点設立',target_stock:'追加備蓄',research:'研究',industry:'産業',facility_maintenance:'設備維持',vehicle_production:'機体建造',scientific_exploration:'科学探査',contract:'契約'};
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  const priorityControl=(selected,inputAttributes,label='優先度',disabled=false)=>A.prioritySegmentedHtml(selected,{inputAttributes,label,disabled});
  const priorityText=(value)=>`${Number(value)} ${priorityLabels[Number(value)]||''}`.trim();
  const ownerLabel=(kind)=>ownerLabels[kind]||kind;
  const fleetUsageLabels={transport:'輸送',research:'研究',survey:'地表調査',scientific_exploration:'科学探査',founding:'拠点設立',relocating:'移動',releasing:'回収',retirement:'退役',other:'その他'};
  const fleetUsageLabel=(kind)=>fleetUsageLabels[kind]||'その他';
  function ownerContextName(kind,id){
    if(!kind)return '需要地全体';
    if(!id)return ownerLabel(kind);
    if(kind==='project'||kind==='founding'){const row=(state.projects?.items||[]).find((x)=>x.id===id);if(row?.display_name)return row.display_name;}
    if(kind==='research'){const row=(state.research?.items||[]).find((x)=>x.id===id);if(row?.display_name)return row.display_name;}
    if(kind==='scientific_exploration'){const row=(state.scientificExplorations?.items||[]).find((x)=>x.id===id);if(row?.display_name)return row.display_name;}
    return ownerLabel(kind);
  }
  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const capText=(c)=>c?`${fmt(c.forward_t_per_day,2)} / ${fmt(c.reverse_t_per_day,2)} t/日`:'—';
  const infrastructureText=(rows)=>{const items=rows||[];return items.length?items.map((r)=>`${locationName(r.operational_node_id)}: ${capabilityName(r.capability_id)} (${r.required_state==='ACTIVE'?'稼働中':'設置済み'})`).join(' / '):'追加の機能要件なし';};
  const pathText=(path)=>{const rows=path||[];return rows.length?rows.map((id)=>definitionName(id)).join(' → '):'—';};
  const relocationKey=(destination,units)=>`${destination}\u001f${units}`;

  function setAllocationPriority(priority){
    const value=String(priority??3);$('#allocationPriority').value=value;
    for(const button of document.querySelectorAll('[data-allocation-priority]'))button.classList.toggle('is-selected',button.dataset.allocationPriority===value);
  }
  function setAllocationCapacity(direction,value,{expandRange=false}={}){
    const number=Math.max(0,Number(value)||0),range=$(`#allocation${direction}Range`),input=$(`#allocation${direction}`),label=$(`#allocation${direction}Value`);
    if(expandRange&&number>Number(range.max||0))range.max=String(number);
    range.value=String(Math.min(number,Number(range.max||number||1)));input.value=String(number);label.textContent=`${fmt(number,2)} t/日`;
    scheduleAllocationPreview();
  }
  function selectedAllocationOption(){
    const vehicle=$('#allocationVehicle')?.value;return (allocationOptionsView?.options||[]).find((row)=>row.vehicle_definition_id===vehicle)||null;
  }
  function renderAllocationCapacityAssistance(source){
    if(!source)return;
    const forwardMax=Math.max(0.01,Number(source.suggested_capacity_max?.forward_t_per_day)||0.01),reverseMax=Math.max(0.01,Number(source.suggested_capacity_max?.reverse_t_per_day)||0.01);
    $('#allocationForwardRange').max=String(Math.max(forwardMax,Number($('#allocationForward').value)||0));$('#allocationReverseRange').max=String(Math.max(reverseMax,Number($('#allocationReverse').value)||0));
    const presets=source.capacity_presets||[];
    $('#allocationForwardPresets').innerHTML=`<button type="button" data-allocation-capacity-preset="forward" data-allocation-capacity-value="0">停止</button>`+presets.map((row)=>`<button type="button" data-allocation-capacity-preset="forward" data-allocation-capacity-value="${esc(row.capacity.forward_t_per_day)}">${esc(row.display_name)}<span class="cell-sub">${fmt(row.capacity.forward_t_per_day,2)} t/日</span></button>`).join('');
    $('#allocationReversePresets').innerHTML=`<button type="button" data-allocation-capacity-preset="reverse" data-allocation-capacity-value="0">なし</button>`+presets.map((row)=>`<button type="button" data-allocation-capacity-preset="reverse" data-allocation-capacity-value="${esc(row.capacity.reverse_t_per_day)}">${esc(row.display_name)}<span class="cell-sub">${fmt(row.capacity.reverse_t_per_day,2)} t/日</span></button>`).join('');
  }
  function renderAllocationCapacityControls(){
    const option=selectedAllocationOption();if(!option)return;
    renderAllocationCapacityAssistance(option);
    if(!allocationCapacityInitialized){setAllocationCapacity('Forward',option.nominal_capacity?.forward_t_per_day||0,{expandRange:true});setAllocationCapacity('Reverse',0,{expandRange:true});allocationCapacityInitialized=true;}else{setAllocationCapacity('Forward',$('#allocationForward').value,{expandRange:true});setAllocationCapacity('Reverse',$('#allocationReverse').value,{expandRange:true});}
  }
  function renderAllocationMovementChoices(){
    const root=$('#allocationMovementChoices');if(!root)return;const source=$('#allocationSource').value,destination=$('#allocationDestination').value;
    const candidates=(state.movementPlans?.items||[]).filter((row)=>row.origin_id===source&&row.destination_id===destination);
    root.innerHTML=candidates.map((row)=>{const index=allocationMovementSelection.indexOf(row.id),selected=index>=0;return `<button type="button" class="choice-button ${selected?'is-selected':''}" data-allocation-movement="${esc(row.id)}"><span class="cell-main">${selected?`${index+1}. `:''}${esc(row.display_name)}</span><span class="cell-sub">${esc(locationName(row.origin_id))} → ${esc(locationName(row.destination_id))} · ${row.service_feasible_now?'運用可能':row.available?'運用条件待ち':'不成立'}</span></button>`;}).join('')||'<span class="cell-sub">固定候補なし。自動選択を使用します。</span>';
  }

  function renderAllocationPreview(preview=null,{loading=false,error=null}={}){
    const root=$('#allocationPreview');if(!root)return;
    if(loading){root.innerHTML='<h3>設定結果</h3><div class="cell-sub">必要Fleetと成立見込みを計算中…</div>';return;}
    if(error){root.innerHTML=`<h3>設定結果</h3><div class="issue"><div class="issue-title">${esc(error)}</div></div>`;return;}
    if(!preview){root.innerHTML='<h3>設定結果</h3><div class="cell-sub">輸送能力目標を調整すると必要Fleetと成立見込みを表示します。</div>';return;}
    renderAllocationCapacityAssistance(preview);
    const required=preview.required_units==null?'算出不可':fmt(preview.required_units,0);
    const unfilled=preview.unfilled_units==null?'—':fmt(preview.unfilled_units,0);
    const route=`F ${pathText(preview.selected_forward_path)}${(preview.selected_reverse_path||[]).length?` / R ${pathText(preview.selected_reverse_path)}`:''}`;
    const blockers=(preview.blockers||[]).length?`<div class="issue-stack">${preview.blockers.map((row)=>issueHtml(row)).join('')}</div>`:'<span class="badge ok">現在の制約なし</span>';
    root.innerHTML=`<h3>設定結果</h3>${kv([
      ['Target',esc(capText(preview.target_capacity))],
      ['必要Fleet',`${esc(required)} 機`],
      ['利用可能Fleet',`${fmt(preview.available_units,0)} 機`],
      ['不足',`${esc(unfilled)} 機`],
      ['成立可能Capacity',esc(capText(preview.achievable_capacity))],
      ['選択経路',esc(route)],
      ['運行周期 / 所要時間',`${fmt(preview.cycle_days,1)} 日 / F ${fmt(preview.forward_latency_days,0)} 日${preview.reverse_latency_days==null?'':` / R ${fmt(preview.reverse_latency_days,0)} 日`}`],
    ])}${blockers}`;
  }

  function scheduleAllocationPreview({immediate=false}={}){
    if(allocationPreviewTimer){clearTimeout(allocationPreviewTimer);allocationPreviewTimer=null;}
    if(!$('#allocationDialog')?.open)return;
    const run=()=>updateAllocationPreview();
    if(immediate)run();else allocationPreviewTimer=setTimeout(run,150);
  }

  async function updateAllocationPreview(){
    allocationPreviewTimer=null;
    if(!$('#allocationDialog')?.open)return;
    const vehicle=$('#allocationVehicle').value,source=$('#allocationSource').value,destination=$('#allocationDestination').value;
    if(!vehicle||!source||!destination||source===destination){renderAllocationPreview();return;}
    const serial=++allocationPreviewSerial;renderAllocationPreview(null,{loading:true});
    const params=new URLSearchParams({
      vehicle_definition_id:vehicle,source_id:source,destination_id:destination,
      target_forward_t_per_day:$('#allocationForward').value||'0',
      target_reverse_t_per_day:$('#allocationReverse').value||'0',
    });
    for(const movementId of allocationMovementSelection)params.append('movement_plan_id',movementId);
    if(editingAllocationId)params.set('allocation_id',editingAllocationId);
    try{
      const preview=await api(`/api/v1/transport-allocation-preview?${params}`);
      if(serial!==allocationPreviewSerial||!$('#allocationDialog')?.open)return;
      renderAllocationPreview(preview);
    }catch(err){if(serial===allocationPreviewSerial&&$('#allocationDialog')?.open)renderAllocationPreview(null,{error:err.message||'設定結果を取得できません'});}
  }

  function renderAllocationServiceOptions(view=allocationOptionsView){
    const root=$('#allocationServiceOptions');if(!root)return;
    if(!view){root.innerHTML='<div class="cell-sub">輸送手段候補を取得中…</div>';return;}
    const selectedVehicle=$('#allocationVehicle')?.value;
    const cards=(view.options||[]).map((option)=>{
      const selected=option.vehicle_definition_id===selectedVehicle;
      const resources=(option.operational_supply_at_full_unit||[]).map(([locationId,resourceId,amount])=>`${locationName(locationId)}: ${resourceName(resourceId)} ${fmt(amount,2)} t/日`).join(' / ')||'追加運用資源なし';
      const blockers=(option.blockers||[]).length?`<div class="issue-stack">${option.blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">輸送可能</span>';
      return `<div class="detail-card ${selected?'is-usable':''}" data-allocation-option-card="${esc(option.vehicle_definition_id)}"><div class="mode-title"><span>${esc(option.display_name)}</span><button type="button" class="secondary" data-allocation-option="${esc(option.vehicle_definition_id)}">${selected?'選択中':'このVehicleを選択'}</button></div>${kv([
        ['往路',esc(pathText(option.forward_path))],
        ['復路 / 回収',esc(pathText(option.reverse_path))],
        ['基準輸送能力（往路 / 復路）',esc(capText(option.nominal_capacity))],
        ['運行周期 / 所要時間',`${fmt(option.cycle_days,1)} 日 / F ${fmt(option.forward_latency_days,0)} 日${option.reverse_latency_days==null?'':` / R ${fmt(option.reverse_latency_days,0)} 日`}`],
        ['Fleet',`${fmt(option.fleet_free_units,0)} 機空き / ${fmt(option.fleet_total_units,0)} 機`],
        ['必要インフラ',esc(infrastructureText(option.infrastructure_requirements))],
        ['最大運用時の必要資源',esc(resources)],
      ])}${blockers}</div>`;
    }).join('');
    root.innerHTML=`<h3>輸送手段候補</h3><div class="cell-sub">機体性能と正準移動評価からApplicationが導出した候補です。経路を固定する必要がある場合だけ候補経路を選択します。</div>${cards||'<div class="empty-state">候補なし</div>'}`;
  }

  async function updateAllocationServiceOptions(){
    if(!$('#allocationDialog')?.open)return;
    const source=$('#allocationSource').value,destination=$('#allocationDestination').value;
    const serial=++allocationOptionSerial;allocationOptionsView=null;
    if(!source||!destination||source===destination){
      const root=$('#allocationServiceOptions');if(root)root.innerHTML='<h3>輸送手段候補</h3><div class="cell-sub">異なる出発地と到着地を選択してください。</div>';
      return;
    }
    renderAllocationServiceOptions(null);
    try{
      const params=new URLSearchParams({source_id:source,destination_id:destination});
      const view=await api(`/api/v1/transport-allocation-options?${params}`);
      if(serial!==allocationOptionSerial||!$('#allocationDialog')?.open)return;
      allocationOptionsView=view;renderAllocationServiceOptions(view);renderAllocationCapacityControls();renderAllocationMovementChoices();scheduleAllocationPreview({immediate:true});
    }catch(err){
      if(serial===allocationOptionSerial&&$('#allocationDialog')?.open){
        const root=$('#allocationServiceOptions');if(root)root.innerHTML=`<h3>輸送手段候補</h3><div class="issue"><div class="issue-title">${esc(err.message||'候補を取得できません')}</div></div>`;
      }
    }
  }

  function renderRelocationPreview(preview){
    const root=$('#relocationPreview'),submit=$('#relocationSubmitButton');if(!root)return;
    if(!preview){relocationPreviewKey=null;root.innerHTML='<div class="cell-sub">移動計画を取得中…</div>';if(submit)submit.disabled=true;return;}
    relocationPreviewKey=relocationKey(preview.destination_id,preview.units);
    const resources=(preview.resource_requirements||[]).map((r)=>`<div class="cell-sub">${esc(locationName(r.operational_node_id))}: ${esc(resourceName(r.resource_id))} ${fmt(r.required_t,2)} t 必要 / ${fmt(r.available_t,2)} t 利用可能</div>`).join('')||'<div class="cell-sub">運用Resource消費なし</div>';
    const blockers=(preview.blockers||[]).map(issueHtml).join('');
    root.innerHTML=`<h3>移動計画 <span class="badge ${preview.feasible?'ok':'warn'}">${preview.feasible?'実行可能':'制約あり'}</span></h3>${kv([
      ['経路',(preview.path||[]).length?(preview.path||[]).map((id)=>esc(definitionName(id))).join(' → '):'—'],
      ['所要時間',preview.arrival_day===null?'—':`${fmt(preview.travel_days,0)} 日（Day ${fmt(preview.arrival_day,0)} 到着）`],
      ['必要インフラ',esc(infrastructureText(preview.infrastructure_requirements))],
    ])}<div class="cell-main">必要資源</div>${resources}${blockers?`<div class="issue-list">${blockers}</div>`:'<div class="cell-sub">現在の制約なし</div>'}`;
    if(submit){submit.disabled=!preview.feasible;submit.title=preview.feasible?'':(preview.blockers||[]).map(A.constraintSummary).join(' / ');}
  }

  async function updateRelocationPreview(){
    if(!relocationContext||!$('#relocationDialog')?.open)return;
    const destination=$('#relocationDestination').value,units=Number($('#relocationUnits').value);
    const key=relocationKey(destination,units);
    const serial=++relocationPreviewSerial;if(key!==relocationPreviewKey)renderRelocationPreview(null);
    try{
      const params=new URLSearchParams({vehicle_definition_id:relocationContext.vehicle_definition_id,source_id:relocationContext.source_id,destination_id:destination,units:String(units)});
      const preview=await api(`/api/v1/logistics/fleet-relocation-preview?${params}`);
      if(serial===relocationPreviewSerial&&relocationContext)renderRelocationPreview(preview);
    }catch(err){if(serial===relocationPreviewSerial&&relocationContext){$('#relocationPreview').innerHTML=`<div class="issue"><div class="issue-title">${esc(err.message||'移動計画を取得できません')}</div></div>`;$('#relocationSubmitButton').disabled=true;}}
  }

  function logistics(){return state.logistics||{};}
  function isDecisionContext(kind,id){return state.decisionContext?.subject_kind===kind&&state.decisionContext?.subject_id===id;}

  function contextSupplyRequirement(){
    const target=state.decisionContext;if(target?.decision_area!=='logistics'||target.subject_kind!=='supply_requirement')return null;
    return (logistics().requirements||[]).find((row)=>row.id===target.subject_id)||null;
  }
  function contextTransportAllocation(){
    const target=state.decisionContext;if(target?.decision_area!=='logistics'||target.subject_kind!=='transport_allocation')return null;
    return (state.transportAllocations?.items||logistics().allocations||[]).find((row)=>row.id===target.subject_id)||null;
  }
  function contextMovementPlanIds(){
    const target=state.decisionContext;if(target?.decision_area!=='logistics')return new Set();
    if(target.subject_kind==='movement_plan'&&target.subject_id)return new Set([target.subject_id]);
    if(target.subject_kind==='operational_node'&&target.subject_id)return new Set((state.movementPlans?.items||[]).filter((row)=>row.origin_id===target.subject_id||row.destination_id===target.subject_id).map((row)=>row.id));
    const requirement=contextSupplyRequirement();if(requirement){
      const selected=requirement.selected_movement_plan_ids||[];
      if(selected.length)return new Set(selected);
      return new Set((requirement.path_candidates||[]).flatMap(([,planIds])=>planIds||[]));
    }
    const allocation=contextTransportAllocation();if(allocation)return new Set([...(allocation.selected_forward_path||[]),...(allocation.selected_reverse_path||[])]);
    return new Set();
  }
  function contextNetworkNodeIds(planIds){
    const ids=new Set(),plans=state.movementPlans?.items||[];
    for(const plan of plans){if(planIds.has(plan.id)){ids.add(plan.origin_id);ids.add(plan.destination_id);}}
    const requirement=contextSupplyRequirement();if(requirement){if(requirement.selected_source_id)ids.add(requirement.selected_source_id);if(requirement.destination_id)ids.add(requirement.destination_id);}
    const allocation=contextTransportAllocation();if(allocation){ids.add(allocation.anchor_node_id);ids.add(allocation.destination_id);}
    if(state.decisionContext?.subject_kind==='operational_node'&&state.decisionContext.subject_id)ids.add(state.decisionContext.subject_id);
    return ids;
  }
  function logisticsDecisionItems(){
    const items=[];
    for(const row of logistics().requirements||[]){
      const blockers=row.blockers||[];
      const stateNeedsDecision=!['local_covered','pipeline_covered'].includes(row.supply_state);
      if(!stateNeedsDecision&&!blockers.length)continue;
      const supplyState=requirementStateLabel(row);
      const primary=blockers[0]?`${supplyState} · ${A.constraintSummary(blockers[0])}`:supplyState;
      items.push({
        kind:'supply_requirement',id:row.id,severity:'attention',
        eyebrow:'補給需要',title:`${resourceName(row.resource_id)} · ${locationName(row.destination_id)}`,
        detail:`${primary}${Number(row.remaining_t||0)>1e-9?` · 未充足 ${fmt(row.remaining_t,2)} t`:''}`,
      });
    }
    for(const row of state.transportAllocations?.items||logistics().allocations||[]){
      const issues=[...(row.blockers||[]),...(row.limiting_factors||[])];
      const unfilled=Math.max(0,Number(row.unfilled_units||0));
      if(!issues.length&&unfilled<=0&&!row.paused)continue;
      const primary=row.paused?'停止中':issues[0]?A.constraintSummary(issues[0]):`Fleet不足 ${fmt(unfilled,0)} 機`;
      items.push({
        kind:'transport_allocation',id:row.id,severity:issues.length||unfilled>0?'attention':'state',
        eyebrow:'輸送能力',title:row.display_name,
        detail:`${primary} · 目標 ${allocationTarget(row)}`,
      });
    }
    for(const row of state.cargoFlows?.items||logistics().cargo_flows||[]){
      const blockers=row.admission_blockers||[];
      if(row.status!=='arrival_waiting'&&!blockers.length)continue;
      items.push({
        kind:'cargo_flow',id:row.id,severity:'attention',eyebrow:'到着待機',
        title:`${resourceName(row.resource_id)} · ${locationName(row.destination_id)}`,
        detail:blockers[0]?A.constraintSummary(blockers[0]):`${fmt(row.amount_t,2)} t が受入待ち`,
      });
    }
    return items;
  }
  function renderLogisticsDecisionLane(){
    const root=$('#logisticsDecisionLane');if(!root)return;
    const items=logisticsDecisionItems();
    const visible=items.slice(0,6);
    const cards=visible.map((item)=>{
      const selected=isDecisionContext(item.kind,item.id);
      const attrs=item.kind==='cargo_flow'
        ? 'data-logistics-decision-target="cargo"'
        : `data-logistics-decision-kind="${esc(item.kind)}" data-logistics-decision-id="${esc(item.id)}"`;
      return `<button type="button" class="logistics-decision-item ${item.severity==='attention'?'has-warning':''} ${selected?'is-selected':''}" ${attrs}><span class="eyebrow">${esc(item.eyebrow)}</span><strong>${esc(item.title)}</strong><span>${esc(item.detail)}</span><small>${item.kind==='cargo_flow'?'輸送中貨物で確認':'Networkで原因を確認'}</small></button>`;
    }).join('');
    root.innerHTML=`<div class="logistics-decision-heading"><div><span class="eyebrow">現在の輸送判断</span><h2>${items.length?'対処が必要な物流状態':'重大な輸送判断なし'}</h2></div><span class="badge ${items.length?'warn':'ok'}">${items.length} 件</span></div>${items.length?`<div class="logistics-decision-grid">${cards}</div>${items.length>visible.length?`<div class="cell-sub">ほか ${items.length-visible.length} 件。詳細一覧は下段で確認できます。</div>`:''}`:'<div class="logistics-decision-clear">現在の補給需要、輸送能力、到着待機にPlayer判断を要求する状態はありません。Networkと詳細状態は引き続き下段で確認できます。</div>'}`;
  }

  function renderNetworkDecisionContext(){
    const box=$('#networkDecisionContext');if(!box)return;const target=state.decisionContext;
    if(target?.decision_area!=='logistics'){box.hidden=true;box.textContent='';return;}
    const requirement=contextSupplyRequirement();
    if(requirement){box.hidden=false;box.innerHTML=`<span class="eyebrow">選択中の判断</span><strong>${esc(resourceName(requirement.resource_id))} · ${esc(locationName(requirement.destination_id))}</strong><span>補給需要に関係する経路を強調中</span>`;return;}
    const allocation=contextTransportAllocation();
    if(allocation){box.hidden=false;box.innerHTML=`<span class="eyebrow">選択中の判断</span><strong>${esc(allocation.display_name)}</strong><span>この輸送能力設定で利用する経路を強調中</span>`;return;}
    if(target.subject_kind==='movement_plan'&&target.subject_id){const plan=(state.movementPlans?.items||[]).find((row)=>row.id===target.subject_id);box.hidden=false;box.innerHTML=`<span class="eyebrow">選択中の判断</span><strong>${esc(plan?.display_name||playerTerm('movement_plan'))}</strong><span>選択した移動経路を強調中</span>`;return;}
    if(target.subject_kind==='operational_node'&&target.subject_id){box.hidden=false;box.innerHTML=`<span class="eyebrow">全体Mapから引き継ぎ</span><strong>${esc(locationName(target.subject_id))}</strong><span>この拠点に接続する輸送Networkを強調中</span>`;return;}
    box.hidden=true;box.textContent='';
  }

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
    $('#movementPlanList').innerHTML=filteredMovementPlans().map((r)=>`<button type="button" class="movement-plan-button ${r.id===state.selectedMovementPlanId?'is-selected':''}" data-movement-plan-id="${esc(r.id)}"><div class="cell-main">${esc(r.display_name)}</div><div class="movement-plan-status"><span>${esc(locationName(r.origin_id))} → ${esc(locationName(r.destination_id))}</span><span class="badge ${r.service_feasible_now?'ok':r.available?'warn':''}">${r.service_feasible_now?'運用可能':r.available?'運用条件待ち':'移動不可'}</span></div></button>`).join('')||`<div class="empty-state">条件に一致する${playerTerm('movement_plan')}なし</div>`;
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
    const contextPlans=contextMovementPlanIds(),contextNodes=contextNetworkNodeIds(contextPlans);
    svg.innerHTML=movementPlans.map((r)=>{const a=positions[r.origin_id],b=positions[r.destination_id];if(!a||!b)return'';const coords=`x1="${a[0]*9}" y1="${a[1]*4.7}" x2="${b[0]*9}" y2="${b[1]*4.7}"`;const contextClass=contextPlans.has(r.id)?'is-context-related':'';return `<line ${coords} class="network-line-hit" data-movement-plan-line="${esc(r.id)}" /><line ${coords} class="network-line ${r.service_feasible_now?'available':''} ${contextClass} ${r.id===state.selectedMovementPlanId?'selected':''}" data-network-plan-visual="${esc(r.id)}" aria-hidden="true" />`;}).join('');
    nodes.innerHTML=locations.map((loc)=>{const p=positions[loc.id]||[50,50],contextClass=contextNodes.has(loc.id)?'is-context-related':'';return `<div class="network-node ${contextClass}" data-network-node-visual="${esc(loc.id)}" style="left:${p[0]}%;top:${p[1]}%"><button type="button" data-network-location="${esc(loc.id)}"><span class="node-name">${esc(loc.display_name)}</span><span class="node-meta">設備 ${loc.facility_count} · 建設 ${loc.active_project_count}</span></button></div>`;}).join('');
    renderNetworkDecisionContext();
  }

  function constraintScopeKey(row){return encodeURIComponent(JSON.stringify([row.destination_id,row.owner_kind||null,row.owner_id||null,row.resource_id||null]));}
  function constraintScopePayload(row){return {destination_id:row.destination_id,owner_kind:row.owner_kind||null,owner_id:row.owner_id||null,resource_id:row.resource_id||null};}
  function selectedRouteText(d){
    const source=d.selected_source_id?locationName(d.selected_source_id):'未選択';
    const path=(d.selected_service_ids||[]).map(definitionName).join(' → ')||'直送/経路未確定';
    return `${source} → ${locationName(d.destination_id)} · ${path}`;
  }
  function renderSupplyPolicies(){
    const constraints=logistics().routing_constraints||[],targets=logistics().target_stocks||[];
    $('#routingConstraintCountBadge').textContent=`${constraints.length}制約 / ${targets.length}目標`;
    const constraintCards=constraints.map((row)=>{
      const scope=[ownerContextName(row.owner_kind,row.owner_id),row.resource_id?resourceName(row.resource_id):'全資源'].join(' / ');
      const via=(row.required_via_node_ids||[]).map(locationName).join(' → ')||'指定なし';
      const allocations=(row.required_transport_allocation_ids||[]).map((id)=>{const a=(state.transportAllocations?.items||[]).find((x)=>x.id===id);return a?`${locationName(a.anchor_node_id)} → ${locationName(a.destination_id)}`:'輸送区間';}).join(' / ')||'指定なし';
      const key=constraintScopeKey(row);
      return `<article class="supply-policy-card"><div class="decision-card-title"><span><strong>${esc(locationName(row.destination_id))}</strong><small>${esc(scope)}</small></span><span class="badge">固定条件</span></div><div class="supply-policy-metrics"><span><small>供給元</small><strong>${row.source_node_id?esc(locationName(row.source_node_id)):'自動選択'}</strong></span><span><small>必須経由</small><strong>${esc(via)}</strong></span><span><small>必須輸送区間</small><strong>${esc(allocations)}</strong></span></div><div class="action-row"><button type="button" data-routing-constraint-edit="${esc(key)}">編集</button><button type="button" class="danger-button" data-routing-constraint-clear="${esc(key)}">解除</button></div></article>`;
    }).join('');
    const targetCards=targets.map((row)=>`<article class="target-stock-card" data-target-stock-row><div class="decision-card-title"><span><strong>${esc(resourceName(row.resource_id))}</strong><small>${esc(locationName(row.destination_id))}</small></span><span class="badge">${esc(priorityText(row.priority))}</span></div><div class="target-stock-value"><span>追加備蓄目標</span><strong>${fmt(row.target_quantity_t)} t</strong></div><div class="action-row"><button type="button" data-target-stock-edit="${esc(row.destination_id)}" data-resource-id="${esc(row.resource_id)}">設定</button><button type="button" class="danger-button" data-target-stock-delete="${esc(row.destination_id)}" data-resource-id="${esc(row.resource_id)}">削除</button></div></article>`).join('');
    $('#routingConstraintTable').innerHTML=`<div class="supply-policy-surface"><div class="supply-policy-heading"><div><span class="eyebrow">追加備蓄</span><h4>需要地の在庫目標</h4><p>通常需要とは別に、需要地へ追加で確保したい備蓄量を設定します。</p></div><button type="button" id="newTargetStockButton" class="primary">追加備蓄を設定</button></div><div class="target-stock-grid">${targetCards||'<div class="empty-state compact-empty">追加備蓄目標はありません。</div>'}</div><div class="supply-policy-heading"><div><span class="eyebrow">経路条件</span><h4>供給経路の固定条件</h4><p>通常はNetworkから自動選択します。固定が必要な需要だけ供給元・経由・輸送区間を指定します。</p></div></div><div class="supply-policy-grid">${constraintCards||'<div class="empty-state compact-empty">固定条件はありません。既存Networkから自動選択します。</div>'}</div></div>`;
  }

  function requirementStateLabel(d){return {local_covered:'現地充足',pipeline_covered:'輸送中で充足',no_source:'供給元なし',transport_blocked:'輸送能力阻害',source_shortage:'供給元不足',coverage_gap:'供給空白',low_runway:'猶予小',uncovered:'未充足'}[d.supply_state]||d.supply_state;}
  function transportAllocationLabel(id){
    const allocation=(state.transportAllocations?.items||logistics().allocations||[]).find((row)=>row.id===id);
    return allocation?`${locationName(allocation.anchor_node_id)} → ${locationName(allocation.destination_id)}`:'現在利用できない輸送区間';
  }
  function renderRequirements(){
    const items=logistics().requirements||[];$('#requirementCountBadge').textContent=`${items.length}件`;
    const cards=items.map((d)=>{
      const runway=d.local_runway_days==null?'—':`${fmt(d.local_runway_days,1)}日`,forecast=d.forecast_requirement_day==null?'—':`Day ${fmt(d.forecast_requirement_day,0)}`,arrival=d.projected_arrival_day==null?(d.earliest_confirmed_arrival_day==null?'—':`Day ${fmt(d.earliest_confirmed_arrival_day,0)}`):`Day ${fmt(d.projected_arrival_day,0)}`,gap=d.projected_gap_days==null?'—':`${fmt(d.projected_gap_days,1)}日`,stateClass=['local_covered','pipeline_covered'].includes(d.supply_state)?'ok':'warn';
      const constrained=Boolean(d.routing_constraint_source_id||(d.routing_constraint_via_node_ids||[]).length||(d.routing_constraint_transport_allocation_ids||[]).length);
      const metrics=[d.selected_latency_days==null?null:`${fmt(d.selected_latency_days,1)}日`,d.selected_propellant_t_per_t==null?null:`推進剤 ${fmt(d.selected_propellant_t_per_t,3)} t/t`,d.selected_handoff_count==null?null:`中継 ${fmt(d.selected_handoff_count,0)}`,d.selected_bottleneck_capacity_t_per_day==null?null:`最小能力 ${fmt(d.selected_bottleneck_capacity_t_per_day,2)} t/日`].filter(Boolean).join(' · ')||'経路指標未確定';
      const hardAllocations=(d.routing_constraint_transport_allocation_ids||[]).map(transportAllocationLabel).join(' / ')||'なし';
      const blockers=(d.blockers||[]).map(A.constraintSummary);
      return `<article class="supply-requirement-card ${isDecisionContext('supply_requirement',d.id)?'is-context-target':''} ${stateClass==='warn'?'has-warning':''}" data-requirement-id="${esc(d.id)}"><div class="decision-card-title"><span><strong>${esc(resourceName(d.resource_id))}</strong><small>${esc(ownerContextName(d.owner_kind,d.owner_id))} · ${esc(locationName(d.destination_id))}</small></span><span class="badge ${stateClass}">${esc(requirementStateLabel(d))}</span></div><div class="requirement-quantity-grid"><span><small>要求</small><strong>${fmt(d.requested_t)} t</strong></span><span><small>現地供給</small><strong>${fmt(d.local_supply_t)} t</strong></span><span><small>外部必要</small><strong>${fmt(d.external_required_t)} t</strong></span><span><small>輸送系内</small><strong>${fmt(d.pipeline_t)} t</strong></span><span><small>未充足</small><strong>${fmt(d.remaining_t)} t</strong></span><span><small>猶予</small><strong>${esc(runway)}</strong></span></div><div class="requirement-route"><strong>${esc(selectedRouteText(d))}</strong><span>${esc(metrics)}</span><span>必要 ${esc(forecast)} · 到着見込 ${esc(arrival)} · 供給空白 ${esc(gap)}</span>${constrained?`<span>固定: 供給元 ${esc(d.routing_constraint_source_id?locationName(d.routing_constraint_source_id):'自動')} · 経由 ${esc((d.routing_constraint_via_node_ids||[]).map(locationName).join(', ')||'なし')} · 区間 ${esc(hardAllocations)}</span>`:''}</div><div class="requirement-footer"><span>${blockers.length?`制約: ${esc(blockers[0])}`:`供給元 ${d.operational_source_count}/${d.candidate_source_count} · 在庫源 ${d.stocked_source_count}`}</span><span>優先 ${esc(priorityText(d.priority))}</span></div><div class="action-row"><button type="button" data-requirement-network="${esc(d.id)}">Networkで確認</button><button type="button" data-requirement-constraint data-owner-kind="${esc(d.owner_kind)}" data-owner-id="${esc(d.owner_id)}" data-destination-id="${esc(d.destination_id)}" data-resource-id="${esc(d.resource_id)}">${constrained?'経路条件を編集':'経路条件を設定'}</button></div></article>`;
    }).join('');
    $('#requirementTable').innerHTML=`<div class="supply-requirement-grid">${cards||`<div class="empty-state">現在の${playerTerm('supply_requirement')}はありません。</div>`}</div>`;
  }

  function fleetCommitmentContext(commitment){
    if(commitment.usage_kind==='transport')return transportAllocationLabel(commitment.owner_activity_id);
    if(commitment.usage_kind==='scientific_exploration'){const row=(state.scientificExplorations?.items||[]).find((item)=>item.id===commitment.owner_activity_id);return row?.display_name||'科学探査';}
    if(commitment.usage_kind==='founding'){const row=(state.projects?.items||[]).find((item)=>item.id===commitment.owner_activity_id);return row?.display_name||'拠点設立';}
    if(commitment.usage_kind==='research')return '研究支援';
    if(commitment.usage_kind==='survey')return '地表調査支援';
    return fleetUsageLabel(commitment.usage_kind);
  }

  function renderFleet(){
    const pools=state.fleet?.pools||logistics().fleet_pools||[]; const commitments=state.fleet?.commitments||logistics().fleet_commitments||[]; const relocations=state.fleet?.relocations||logistics().relocations||[]; const releases=state.fleet?.releases||logistics().releases||[]; const retirements=state.fleet?.retirements||logistics().retirements||[];
    $('#vehicleCountBadge').textContent=`${pools.reduce((n,p)=>n+Number(p.total_units||0),0)} 機`;
    const poolCards=pools.map((p)=>{
      const free=Number(p.free_units||0);
      const active=Number(p.total_units||0)-free;
      const poolCommitments=commitments.filter((c)=>c.vehicle_definition_id===p.vehicle_definition_id&&c.operational_node_id===p.operational_node_id&&!['relocating','releasing','retirement'].includes(c.usage_kind));
      const assignmentRows=poolCommitments.map((c)=>`<div class="fleet-assignment-row"><span><strong>${esc(fleetUsageLabel(c.usage_kind))}</strong><small>${esc(fleetCommitmentContext(c))}</small></span><strong>${fmt(c.quantity,0)} 機</strong></div>`).join('');
      const otherMetric=Number(p.other_committed_units||0)>0?`<span><small>その他</small><strong>${fmt(p.other_committed_units,0)}</strong></span>`:'';
      return `<article class="fleet-pool-card" data-fleet-pool-row><div class="decision-card-title"><span><strong>${esc(p.display_name)}</strong><small>${esc(locationName(p.operational_node_id))}</small></span><span class="badge ${free>0?'ok':'warn'}">空き ${fmt(free,0)} / ${fmt(p.total_units,0)}</span></div><div class="fleet-commitment-grid"><span><small>輸送</small><strong>${fmt(p.transport_units,0)}</strong></span><span><small>研究</small><strong>${fmt(p.research_units,0)}</strong></span><span><small>地表調査</small><strong>${fmt(p.survey_units,0)}</strong></span><span><small>科学探査</small><strong>${fmt(p.exploration_units,0)}</strong></span><span><small>拠点設立</small><strong>${fmt(p.founding_units,0)}</strong></span><span><small>移動中</small><strong>${fmt(p.relocating_units,0)}</strong></span><span><small>回収中</small><strong>${fmt(p.releasing_units,0)}</strong></span><span><small>退役中</small><strong>${fmt(p.retirement_units,0)}</strong></span>${otherMetric}</div><div class="fleet-utilization-line"><span>配備中 ${fmt(active,0)} 機</span><span>空き ${fmt(free,0)} 機</span></div>${assignmentRows?`<div class="fleet-assignment-list"><span class="eyebrow">現在の配備先</span>${assignmentRows}</div>`:''}<div class="fleet-card-actions"><button type="button" data-fleet-relocate="${esc(p.vehicle_definition_id)}" data-fleet-source="${esc(p.operational_node_id)}" data-fleet-free="${fmt(free,0)}" ${free<=0?'disabled title="空き機体なし"':''}>機体を移動</button><label>退役数<input data-retirement-units type="number" min="1" max="${fmt(free,0)}" value="1" ${free<=0?'disabled':''}></label>${priorityControl(3,'data-retirement-priority','優先度',free<=0)}<button type="button" data-fleet-retire="${esc(p.vehicle_definition_id)}" data-fleet-retire-node="${esc(p.operational_node_id)}" ${free<=0?'disabled title="空き機体なし"':''}>退役を計画</button></div></article>`;
    }).join('');
    const relocationCards=relocations.map((r)=>`<article class="fleet-transition-card"><span class="badge">移動中</span><strong>${esc(r.display_name)} · ${fmt(r.units,0)} 機</strong><span>${esc(locationName(r.source_id))} → ${esc(locationName(r.destination_id))}</span><small>到着予定 Day ${fmt(r.arrival_day,0)}</small></article>`).join('');
    const releaseCards=releases.map((r)=>`<article class="fleet-transition-card"><span class="badge">回収中</span><strong>${esc(r.display_name)} · ${fmt(r.units,0)} 機</strong><span>${esc(locationName(r.operational_node_id))}</span><small>解放予定 Day ${fmt(r.release_day,0)} · 残り ${fmt(r.remaining_days,0)} 日</small></article>`).join('');
    const retirementCards=retirements.map((r)=>{const salvage=(r.expected_salvage||[]).map(([rid,amount])=>`${resourceName(rid)} ${fmt(amount,2)} t`).join(' / ')||'なし';const projected=(r.projected_salvage||[]).map(([rid,amount])=>`${resourceName(rid)} ${fmt(amount,2)} t`).join(' / ')||'なし';const blockers=(r.blockers||[]).map(A.constraintSummary);return `<article class="fleet-retirement-card" data-retirement-row="${esc(r.id)}"><div class="decision-card-title"><span><strong>${esc(r.display_name)} · ${fmt(r.units,0)} 機</strong><small>${esc(locationName(r.operational_node_id))}</small></span><span class="badge ${r.phase==='complete'?'ok':blockers.length?'warn':''}">${r.phase==='complete'?'完了':'退役処理中'}</span></div><div class="fleet-retirement-metrics"><span>進捗 <strong>${fmt(r.progress_work,1)} / ${fmt(r.required_work,1)}</strong></span><span>回収見込 <strong>${esc(projected)}</strong></span><span>回収可能性 <strong>${esc(salvage)}</strong></span></div>${blockers.length?`<div class="decision-card-footer has-warning">制約: ${esc(blockers[0])}</div>`:''}<div class="fleet-card-actions">${priorityControl(r.priority??3,`data-retirement-active-priority data-priority-direct="retirement" data-priority-id="${esc(r.id)}"`,'優先度',['complete','cancelled'].includes(r.phase))}<button type="button" class="danger-button" data-retirement-cancel="${esc(r.id)}" ${r.irreversible_started||['complete','cancelled'].includes(r.phase)?'disabled title="不可逆処理開始後は取消不可"':''}>退役取消</button></div></article>`;}).join('');
    const transitions=relocationCards+releaseCards+retirementCards;
    $('#vehicleTable').innerHTML=`<div class="fleet-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">機体配備</span><h3>Fleet</h3><p>所在地ごとに空き機体と用途別の拘束を確認し、移動・退役を判断します。研究・地表調査・科学探査・輸送を同じ配備群で比較できます。</p></div><span class="badge">${pools.length} 配備群</span></div><div class="fleet-pool-grid">${poolCards||'<div class="empty-state">Fleetはありません。</div>'}</div>${transitions?`<section class="fleet-transition-section"><h4>進行中の機体状態変更</h4><div class="fleet-transition-grid">${transitions}</div></section>`:''}</div>`;
  }

  function allocationTarget(a){return `F ${fmt(a.target_capacity?.forward_t_per_day,2)} / R ${fmt(a.target_capacity?.reverse_t_per_day,2)} t/日`;}
  function renderAllocations(){
    const items=state.transportAllocations?.items||logistics().allocations||[]; $('#allocationCountBadge').textContent=`${items.length}件`;
    const cards=items.map((a)=>{
      const issues=[...(a.blockers||[]),...(a.limiting_factors||[])].map(A.constraintSummary);
      const constraint=(a.movement_hard_constraint||[]).length?`固定: ${pathText(a.movement_hard_constraint)}`:'自動選択';
      const selected=`往路 ${pathText(a.selected_forward_path)}${(a.selected_reverse_path||[]).length?` / 復路 ${pathText(a.selected_reverse_path)}`:''}`;
      return `<article class="transport-allocation-card ${isDecisionContext('transport_allocation',a.id)?'is-context-target':''} ${issues.length?'has-warning':''}" data-allocation-row="${esc(a.id)}"><div class="decision-card-title"><span><strong>${esc(a.display_name)}</strong><small>${esc(locationName(a.anchor_node_id))} → ${esc(locationName(a.destination_id))}</small></span><span class="badge ${a.paused?'warn':issues.length?'warn':'ok'}">${a.paused?'停止中':issues.length?'制約あり':'稼働中'}</span></div><div class="allocation-capacity-grid"><span><small>目標</small><strong>${esc(allocationTarget(a))}</strong></span><span><small>必要機体</small><strong>${fmt(a.active_units,0)} / ${fmt(a.required_units,0)}</strong></span><span><small>利用可能</small><strong>${capText(a.available)}</strong></span><span><small>使用中</small><strong>${capText(a.used)}</strong></span><span><small>余力</small><strong>${capText(a.spare)}</strong></span><span><small>周期</small><strong>${fmt(a.cycle_days,1)}日</strong></span></div><div class="allocation-route-summary"><strong>${esc(selected)}</strong><span>${esc(constraint)} · 片道 ${fmt(a.forward_latency_days,0)}日</span><span>必要インフラ: ${esc(infrastructureText(a.infrastructure_requirements))}</span><span>運用資源: ${(a.operational_supply||[]).map(([loc,rid,amount])=>`${esc(locationName(loc))} ${esc(resourceName(rid))} ${fmt(amount,2)} t/日`).join(' / ')||'追加なし'}</span></div><div class="decision-card-footer ${issues.length?'has-warning':''}">${issues.length?`制約: ${esc(issues[0])}`:`未配備 ${fmt(a.unfilled_units,0)} 機`}</div><div class="action-row"><button type="button" data-allocation-network="${esc(a.id)}">Networkで確認</button><button type="button" data-allocation-edit="${esc(a.id)}">設定</button><button type="button" data-allocation-toggle="${esc(a.id)}" data-paused="${a.paused?'1':'0'}">${a.paused?'再開':'停止'}</button><button type="button" class="danger-button" data-allocation-delete="${esc(a.id)}">削除</button></div></article>`;
    }).join('');
    $('#allocationTable').innerHTML=`<div class="transport-allocation-surface"><div class="supply-policy-heading"><div><span class="eyebrow">輸送能力</span><h4>NetworkへのFleet配備</h4><p>目標能力・必要機体・現在の余力と制約を区間ごとに比較します。</p></div><button type="button" class="primary" id="newAllocationButton">輸送能力を設定</button></div><div class="transport-allocation-grid">${cards||'<div class="empty-state">輸送能力設定はありません。機体は空き状態です。</div>'}</div></div>`;
  }

  function renderVehicleProduction(){
    const projects=logistics().vehicle_production||[],options=logistics().vehicle_production_options||[]; $('#vehicleProductionCountBadge').textContent=`${projects.length}件`;
    const projectCards=projects.map((p)=>{const blockers=(p.blockers||[]).map(A.constraintSummary),toggle=p.phase==='complete'?'<span class="badge ok">完成</span>':`<button type="button" data-production-toggle="${esc(p.id)}" data-paused="${p.paused?'1':'0'}">${p.paused?'再開':'停止'}</button>`;return `<article class="vehicle-production-card ${isDecisionContext('vehicle_production',p.id)?'is-context-target':''} ${blockers.length?'has-warning':''}" data-production-project-row="${esc(p.id)}"><div class="decision-card-title"><span><strong>${esc(p.display_name)}</strong><small>${esc(locationName(p.operational_node_id))}</small></span><span class="badge ${p.phase==='complete'?'ok':blockers.length?'warn':''}">${p.phase==='complete'?'完成':p.paused?'停止中':'建造中'}</span></div><div class="vehicle-production-metrics"><span><small>進捗</small><strong>${fmt(p.progress_days,1)} / ${fmt(p.required_days,1)}日</strong></span>${priorityControl(p.priority??3,`data-production-priority-value data-priority-direct="production" data-priority-id="${esc(p.id)}"`,'優先度',!p.priority_editable)}</div><div class="decision-card-footer ${blockers.length?'has-warning':''}">${blockers.length?`制約: ${esc(blockers[0])}`:'主要な制約なし'}</div><div class="action-row">${toggle}</div></article>`;}).join('');
    const optionCards=options.map((o)=>{const blockers=(o.blockers||[]).map(A.constraintSummary);return `<article class="vehicle-production-card ${blockers.length?'has-warning':''}" data-production-option-row><div class="decision-card-title"><span><strong>${esc(o.display_name)}</strong><small>${esc(locationName(o.operational_node_id))}</small></span><span class="badge ${o.can_plan?'ok':'warn'}">${o.can_plan?'建造可能':'条件不足'}</span></div><div class="vehicle-production-resource"><span>所要 ${fmt(o.production_days,1)}日</span><span>${(o.resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)} t`).join(' / ')||'追加資源なし'}</span></div><div class="vehicle-production-priority">${priorityControl(3,`data-production-priority-value data-draft-key="production-option:${esc(o.vehicle_definition_id)}:${esc(o.operational_node_id)}:priority"`)}</div><div class="decision-card-footer ${blockers.length?'has-warning':''}">${blockers.length?`制約: ${esc(blockers[0])}`:'主要な制約なし'}</div><button type="button" data-produce-vehicle="${esc(o.vehicle_definition_id)}" data-production-location="${esc(o.operational_node_id)}" ${o.can_plan?'':'disabled'}>建造を開始</button></article>`;}).join('');
    $('#vehicleProductionTable').innerHTML=`<div class="vehicle-production-surface"><div class="supply-policy-heading"><div><span class="eyebrow">建造中</span><h4>機体建造</h4></div></div><div class="vehicle-production-grid">${projectCards||'<div class="empty-state compact-empty">建造中の機体はありません。</div>'}</div><div class="supply-policy-heading"><div><span class="eyebrow">候補</span><h4>新規建造</h4></div></div><div class="vehicle-production-grid">${optionCards||'<div class="empty-state compact-empty">現在の建造候補はありません。</div>'}</div></div>`;
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
    return `<div class="market-target-control"><select data-market-mode data-draft-key="${prefix}:mode" data-structured-draft data-planning-baseline="fixed" data-draft-scope="${prefix}" aria-label="取引目標の種類"><option value="quantity" ${mode==='quantity'?'selected':''}>総量</option><option value="rate" ${mode==='rate'?'selected':''}>日量</option></select><input data-market-target type="number" min="0" step="0.01" value="${esc(mode==='rate'?r:q)}" data-draft-key="${prefix}:target" data-structured-draft data-planning-baseline="fixed" data-draft-scope="${prefix}" aria-label="取引目標値"><span>${mode==='rate'?'t/日':'t'}</span></div>`;
  }
  function renderMarket(){
    const market=state.market;if(!market)return;
    $('#marketFundsBadge').textContent=`利用可能 $${fmt(market.funds_available_musd,2)}M`;
    const offerCards=(market.interfaces||[]).flatMap((iface)=>(iface.offers||[]).map((offer)=>{
      const canBuy=offer.buy_price_musd_per_t!=null;
      const canSell=offer.sell_price_musd_per_t!=null;
      return `<article class="market-offer-card ${iface.enabled?'':'is-disabled'}"><div class="decision-card-title"><span><strong>${esc(resourceName(offer.resource_id))}</strong><small>${esc(iface.provider_name)} · ${esc(locationName(iface.operational_node_id))}</small></span><span class="badge ${iface.enabled?'ok':'warn'}">${iface.enabled?'取引可能':'停止中'}</span></div><div class="market-offer-sides"><div><small>買う</small><strong>${canBuy?`$${fmt(offer.buy_price_musd_per_t,2)}M/t`:'取扱なし'}</strong><span>供給可能 ${fmt(offer.provider_supply_available_t,2)} t</span></div><div><small>売る</small><strong>${canSell?`$${fmt(offer.sell_price_musd_per_t,2)}M/t`:'取扱なし'}</strong><span>需要可能 ${fmt(offer.provider_demand_available_t,2)} t</span></div></div></article>`;
    })).join('');
    const orderCards=(market.orders||[]).map((row)=>{
      const blockers=(row.blockers||[]).map(A.constraintSummary);const limiting=(row.limiting_factors||[]).map(A.constraintSummary);
      const direction=row.direction==='buy'?'買う':'売る';
      const progress=row.direction==='sell'
        ? `<span>成立 ${fmt(row.settled_quantity_t,2)} t</span><span>市場提示 ${fmt(row.presented_quantity_t,2)} t</span><span>輸送中 ${fmt(row.in_flight_quantity_t,2)} t</span>`
        : `<span>成立 ${fmt(row.settled_quantity_t,2)} t</span><span>確保済み ${fmt(row.committed_quantity_t,2)} t</span>`;
      const issue=[...blockers,...limiting][0];
      return `<article class="market-order-card ${issue?'has-warning':''}" data-market-order-row="${esc(row.id)}"><div class="decision-card-title"><span><strong>${direction} · ${esc(resourceName(row.resource_id))}</strong><small>${esc(definitionName(row.market_interface_id))}</small></span><span class="badge ${issue?'warn':'ok'}">${issue?'要確認':'稼働中'}</span></div><div class="market-order-price"><span><small>現在価格</small><strong>${row.current_offer_price_musd_per_t==null?'—':`$${fmt(row.current_offer_price_musd_per_t,2)}M/t`}</strong></span><label>価格条件<input data-market-price type="number" min="0" step="0.01" value="${row.price_limit_musd_per_t==null?'':esc(row.price_limit_musd_per_t)}" placeholder="条件なし" data-draft-key="market:${esc(row.id)}:price" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:${esc(row.id)}"></label></div><div class="market-order-controls"><label>取引目標${marketTargetFields(`market:${esc(row.id)}`,row.control_mode,row.quantity_target_t,row.rate_target_t_per_day)}</label>${priorityControl(row.priority,`data-market-priority data-draft-key="market:${esc(row.id)}:priority" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:${esc(row.id)}"`)}</div><div class="market-order-progress">${progress}</div>${issue?`<div class="decision-card-footer has-warning">制約: ${esc(issue)}</div>`:''}<div class="action-row"><button type="button" data-market-save="${esc(row.id)}">設定適用</button><button type="button" class="danger-button" data-market-cancel="${esc(row.id)}">取消</button></div></article>`;
    }).join('');
    const commitmentCards=(market.buy_commitments||[]).map((row)=>{const blockers=(row.blockers||[]).map(A.constraintSummary);return `<article class="market-commitment-card ${blockers.length?'has-warning':''}"><div class="decision-card-title"><span><strong>${esc(resourceName(row.resource_id))}</strong><small>買付確保</small></span><span class="badge ${blockers.length?'warn':'ok'}">${blockers.length?'入庫待ち':'輸送待ち'}</span></div><div class="market-commitment-metrics"><span><small>未成立量</small><strong>${fmt(row.remaining_quantity_t,2)} t</strong></span><span><small>確保価格</small><strong>$${fmt(row.committed_price_musd_per_t,2)}M/t</strong></span><span><small>予約資金</small><strong>$${fmt(row.reserved_funds_musd,2)}M</strong></span><span><small>確定予定</small><strong>Day ${fmt(row.maturity_day,0)}</strong></span></div><div class="decision-card-footer ${blockers.length?'has-warning':''}">${esc(blockers[0]||'主要な入庫制約なし')}</div></article>`;}).join('');
    const canCreate=(market.interfaces||[]).length&&marketOfferRows().length;
    const createCard=`<section class="market-create-card" data-new-market-order><div class="decision-surface-heading"><div><span class="eyebrow">新規注文</span><h3>取引を設定</h3><p>市場・方向・資源を選び、総量または日量のどちらか一方を目標として設定します。</p></div></div><div class="market-create-grid"><label>市場<select data-market-interface data-draft-key="market:new:interface" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:new">${marketInterfaceOptions()}</select></label><label>方向<select data-market-direction data-draft-key="market:new:direction" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:new"><option value="buy">買う</option><option value="sell">売る</option></select></label><label>資源<select data-market-resource data-draft-key="market:new:resource" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:new">${marketResourceOptions()}</select></label><label>取引目標${marketTargetFields('market:new','quantity',0,null)}</label>${priorityControl(3,'data-market-priority data-draft-key="market:new:priority" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:new"')}<label>価格条件<input data-market-price type="number" min="0" step="0.01" placeholder="買い上限 / 売り下限" data-draft-key="market:new:price" data-structured-draft data-planning-baseline="fixed" data-draft-scope="market:new"></label></div><button type="button" class="primary" data-market-create ${canCreate?'':'disabled'}>取引注文を作成</button></section>`;
    $('#marketPanel').innerHTML=`<div class="market-decision-surface"><section class="market-funds-strip"><div><span>総資金</span><strong>$${fmt(market.funds_total_musd,2)}M</strong></div><div><span>利用可能資金</span><strong>$${fmt(market.funds_available_musd,2)}M</strong></div><div><span>市場</span><strong>${market.interfaces?.length||0}</strong></div><div><span>注文</span><strong>${market.orders?.length||0}</strong></div></section><section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">市場</span><h3>取引条件</h3><p>価格だけでなく、相手側の供給・需要可能量も同時に比較します。</p></div></div><div class="market-offer-grid">${offerCards||'<div class="empty-state">利用可能な取引条件はありません。</div>'}</div></section><section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">注文</span><h3>進行中の取引</h3><p>目標・価格条件・物流上の制約を同じカードで確認します。</p></div></div><div class="market-order-grid">${orderCards||'<div class="empty-state">進行中の取引注文はありません。</div>'}</div></section>${createCard}${commitmentCards?`<section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">買付確保</span><h3>確保済み資源</h3></div></div><div class="market-commitment-grid">${commitmentCards}</div></section>`:''}</div>`;
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
    const cards=cargo.map((f)=>{const blockers=(f.admission_blockers||[]).map(A.constraintSummary);return `<article class="cargo-flow-card ${blockers.length?'has-warning':''}"><div class="decision-card-title"><span><strong>${esc(resourceName(f.resource_id))} · ${fmt(f.amount_t)} t</strong><small>${esc(ownerLabel(f.owner_kind))}</small></span><span class="badge ${blockers.length?'warn':'ok'}">${esc(A.userFacingText(f.status))}</span></div><div class="cargo-route"><strong>${esc(locationName(f.source_id))} → ${esc(locationName(f.destination_id))}</strong><span>${esc((f.service_ids||[]).map(definitionName).join(' → ')||'経路情報なし')}</span></div><div class="cargo-timing"><span>出発 Day ${fmt(f.departure_day,0)}</span><span>到着可能 Day ${fmt(f.ready_day,0)}</span></div><div class="decision-card-footer ${blockers.length?'has-warning':''}">${blockers.length?`入庫制約: ${esc(blockers[0])}`:'入庫制約なし'}</div></article>`;}).join('');
    $('#cargoTable').innerHTML=`<div class="cargo-flow-grid">${cards||'<div class="empty-state">輸送中・到着待ちの貨物はありません。</div>'}</div>`;
  }

  function renderMovementPlanInspector(){
    const title=$('#movementPlanInspectorTitle'),content=$('#movementPlanInspectorContent');
    if(!state.selectedMovementPlanId){title.textContent='移動経路を選択';content.innerHTML=`<div class="empty-state">上の${playerTerm('movement_plan')}またはNetwork上の接続を選択してください。</div>`;return;}
    const movementPlan=(state.movementPlans?.items||[]).find((row)=>row.id===state.selectedMovementPlanId);if(!movementPlan)return;
    title.textContent=movementPlan.display_name;
    const modes=(movementPlan.modes||[]).map((m)=>`<div class="detail-card ${m.service_feasible?'is-usable':''}"><div class="mode-title"><span>${esc(m.display_name)}</span><span class="badge ${m.service_feasible?'ok':'warn'}">${m.service_feasible?'運用可能':'条件不足'}</span></div><div class="cell-sub">Fleet 保有 ${fmt(m.fleet_total_units,0)} / 空き ${fmt(m.fleet_free_units,0)} · 基準能力 ${capText(m.nominal_capacity)} · 往復周期 ${m.cycle_days==null?'—':fmt(m.cycle_days,1)+'日'}</div><div class="cell-sub">必要インフラ: ${esc(infrastructureText(m.infrastructure_requirements))}</div>${(m.blockers||[]).length?`<div class="issue-stack">${m.blockers.map((b)=>issueHtml(b)).join('')}</div>`:''}</div>`).join('');
    const endpointText=(endpoint)=>endpoint?`${locationName(endpoint.node_id)}${endpoint.surface_cell_id?' · 地表Cell':''}`:'—';
    const segmentRows=[['出発',esc(endpointText(movementPlan.origin_endpoint))],['到着',esc(endpointText(movementPlan.destination_endpoint))],['移動条件',movementPlan.available?'成立':'不成立'],['輸送運用',movementPlan.service_feasible_now?'可能':'不可']];
    if(movementPlan.same_body_surface&&movementPlan.distance_km!=null)segmentRows.push(['地表距離',`${fmt(movementPlan.distance_km,1)} km`]);else segmentRows.push(['基準移動日数',`${fmt(movementPlan.transit_days)}日`]);
    segmentRows.push(['必要Δv',`${fmt(movementPlan.delta_v_km_s,2)} km/s`]);
    content.innerHTML=section('区間',kv(segmentRows))+section('必要移動操作',(movementPlan.operations||[]).map((o)=>`<span class="badge">${esc(operationName(Array.isArray(o)?o[0]:o))}</span>`).join(' ')||'—')+section('現在のblocker',(movementPlan.blockers||[]).length?`<div class="issue-stack">${movementPlan.blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">なし</span>')+section('輸送手段候補',modes||'<div class="empty-state">候補なし</div>')+section('操作','<div class="action-stack"><button type="button" class="primary" id="movementPlanAllocationButton">この区間へFleetを配備</button></div>');
  }

  function populateLocationSelects(){
    const opts=(state.world?.operational_nodes||[]).map((l)=>`<option value="${esc(l.id)}">${esc(l.display_name)}</option>`).join('');
    for(const id of ['targetStockDestination','allocationSource','allocationDestination','relocationDestination']){const el=$('#'+id);if(el){const current=el.value;el.innerHTML=opts;if([...el.options].some((o)=>o.value===current))el.value=current;}}
    const source=$('#routingConstraintSource');if(source){const current=source.value;source.innerHTML='<option value="">自動選択</option>'+opts;if([...source.options].some((o)=>o.value===current))source.value=current;}
    const resourceOpts=(state.catalog?.resources||[]).map((row)=>`<option value="${esc(row.id)}">${esc(row.display_name)}</option>`).join('');
    for(const id of ['targetStockResource']){const el=$('#'+id);if(el){const current=el.value;el.innerHTML=resourceOpts;if([...el.options].some((o)=>o.value===current))el.value=current;}}
    const vehicle=$('#allocationVehicle'); if(vehicle){const current=vehicle.value;vehicle.innerHTML=(state.catalog?.vehicles||[]).map((v)=>`<option value="${esc(v.id)}">${esc(v.display_name)}</option>`).join('');if([...vehicle.options].some((o)=>o.value===current))vehicle.value=current;}
  }
  function renderRoutingConstraintChoices(){
    const scope=routingConstraintDraftScope;
    if(!scope)return;
    $('#routingConstraintScopeSummary').innerHTML=`<div class="cell-main">${esc(ownerContextName(scope.owner_kind,scope.owner_id))}</div><div class="cell-sub">${esc(locationName(scope.destination_id))} · ${esc(scope.resource_id?resourceName(scope.resource_id):'全Resource')}</div>`;
    const via=(state.world?.operational_nodes||[]).filter((row)=>row.id!==scope.destination_id).map((row)=>`<button type="button" class="choice-button ${routingConstraintViaSelection.has(row.id)?'is-selected':''}" data-routing-via-node="${esc(row.id)}">${esc(row.display_name)}</button>`).join('');
    $('#routingConstraintViaChoices').innerHTML=via||'<div class="cell-sub">選択可能な経由拠点なし</div>';
    const allocations=state.transportAllocations?.items||logistics().allocations||[];
    $('#routingConstraintAllocationChoices').innerHTML=allocations.map((row)=>`<button type="button" class="choice-button ${routingConstraintAllocationSelection.has(row.id)?'is-selected':''}" data-routing-allocation="${esc(row.id)}"><span>${esc(locationName(row.anchor_node_id))} → ${esc(locationName(row.destination_id))}</span><span class="cell-sub">${esc(allocationTarget(row))}</span></button>`).join('')||'<div class="cell-sub">成立済み輸送区間なし</div>';
  }
  function openRoutingConstraintDialog(row=null,prefill=null){
    const value=row||prefill;if(!value?.destination_id){banner('補給需要から対象需要を選択してください','error');return;}
    populateLocationSelects();
    routingConstraintDraftScope={destination_id:value.destination_id,owner_kind:value.owner_kind||null,owner_id:value.owner_id||null,resource_id:value.resource_id||null};
    editingRoutingConstraintScope=row?constraintScopePayload(row):null;
    routingConstraintViaSelection=new Set(value.required_via_node_ids||value.routing_constraint_via_node_ids||[]);
    routingConstraintAllocationSelection=new Set(value.required_transport_allocation_ids||value.routing_constraint_transport_allocation_ids||[]);
    $('#routingConstraintSource').value=value.source_node_id||value.routing_constraint_source_id||'';
    renderRoutingConstraintChoices();
    $('#routingConstraintDialog').showModal();
  }
  function setTargetStockPriority(priority){
    const value=String(priority??3);$('#targetStockPriority').value=value;
    for(const button of document.querySelectorAll('[data-target-stock-priority]'))button.classList.toggle('is-selected',button.dataset.targetStockPriority===value);
  }
  function setTargetStockQuantity(value,{expandRange=false}={}){
    const number=Math.max(0,Number(value)||0),range=$('#targetStockQuantityRange');
    if(expandRange&&number>Number(range.max||0))range.max=String(number);
    range.value=String(Math.min(number,Number(range.max||number)));
    $('#targetStockQuantity').value=String(number);
    $('#targetStockQuantityValue').textContent=`${fmt(number,2)} t`;
  }
  function renderTargetStockOptions(view){
    if(!view)return;
    targetStockOptionsView=view;
    $('#targetStockOptionSummary').innerHTML=`<div class="cell-main">${esc(locationName(view.destination_id))} · ${esc(resourceName(view.resource_id))}</div><div class="cell-sub">現在在庫 ${fmt(view.current_stock_t,2)} t · Inbound ${fmt(view.inbound_t,2)} t · 通常需要 ${fmt(view.normal_demand_t_per_day,3)} t/日</div><div class="cell-sub">追加備蓄目標は通常需要とは別に保持したい在庫量です。</div>`;
    const range=$('#targetStockQuantityRange');range.max=String(Math.max(1,Number(view.suggested_max_t)||1));
    setTargetStockQuantity(view.current_target_quantity_t,{expandRange:true});setTargetStockPriority(view.priority);
    $('#targetStockPresets').innerHTML=(view.presets||[]).map((row)=>`<button type="button" class="choice-button" data-target-stock-preset="${esc(row.key)}" data-target-stock-value="${esc(row.target_quantity_t)}">${esc(row.display_name)}<span class="cell-sub">${fmt(row.target_quantity_t,2)} t</span></button>`).join('')||'<span class="cell-sub">通常需要がないため日数Presetはありません。必要な追加備蓄量を直接設定してください。</span>';
  }
  async function updateTargetStockOptions(){
    if(!$('#targetStockDialog')?.open)return;
    const destination=$('#targetStockDestination').value,resource=$('#targetStockResource').value,serial=++targetStockOptionsSerial;
    targetStockOptionsView=null;$('#targetStockOptionSummary').innerHTML='<div class="cell-sub">現在状態を取得中…</div>';$('#targetStockPresets').innerHTML='';
    if(!destination||!resource)return;
    try{
      const params=new URLSearchParams({destination_id:destination,resource_id:resource});const view=await api(`/api/v1/target-stock-options?${params}`);
      if(serial!==targetStockOptionsSerial||!$('#targetStockDialog')?.open)return;renderTargetStockOptions(view);
    }catch(err){if(serial===targetStockOptionsSerial&&$('#targetStockDialog')?.open)$('#targetStockOptionSummary').innerHTML=`<div class="issue"><div class="issue-title">${esc(err.message||'追加備蓄候補を取得できません')}</div></div>`;}
  }
  function openTargetStockDialog(destinationId=null,resourceId=null){
    populateLocationSelects();
    if(destinationId&&[...$('#targetStockDestination').options].some((row)=>row.value===destinationId))$('#targetStockDestination').value=destinationId;
    if(resourceId&&[...$('#targetStockResource').options].some((row)=>row.value===resourceId))$('#targetStockResource').value=resourceId;
    $('#targetStockDialog').showModal();updateTargetStockOptions();
  }

  function openAllocationDialog(movementPlan=null,allocation=null){
    editingAllocationId=allocation?.id||null;allocationOptionsView=null;allocationOptionSerial++;allocationCapacityInitialized=Boolean(allocation);populateLocationSelects();const editing=Boolean(allocation);
    $('#allocationDialog h2').textContent=editing?'輸送能力を編集':'輸送能力を設定';
    $('#allocationForm button[type="submit"]').textContent=editing?'設定を更新':'輸送設定を作成';
    for(const id of ['allocationVehicle','allocationSource','allocationDestination'])$('#'+id).disabled=editing;
    allocationMovementSelection=allocation?.movement_hard_constraint?[...(allocation.movement_hard_constraint||[])]:movementPlan?.id?[movementPlan.id]:[];
    if(allocation){
      $('#allocationVehicle').value=allocation.vehicle_definition_id;$('#allocationSource').value=allocation.anchor_node_id;$('#allocationDestination').value=allocation.destination_id;setAllocationPriority(allocation.provisioning_priority);setAllocationCapacity('Forward',allocation.target_capacity?.forward_t_per_day??0,{expandRange:true});setAllocationCapacity('Reverse',allocation.target_capacity?.reverse_t_per_day??0,{expandRange:true});
    }else{setAllocationPriority(3);setAllocationCapacity('Forward',0);setAllocationCapacity('Reverse',0);if(movementPlan){$('#allocationSource').value=movementPlan.origin_id;$('#allocationDestination').value=movementPlan.destination_id;}}
    if($('#allocationSource').value===$('#allocationDestination').value){const other=[...$('#allocationDestination').options].find((o)=>o.value!==$('#allocationSource').value);if(other)$('#allocationDestination').value=other.value;}
    renderAllocationMovementChoices();renderAllocationPreview();$('#allocationDialog').showModal();updateAllocationServiceOptions();
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
    $('#logisticsSummary').innerHTML=[['保有機体',`${s.free_fleet_units}/${s.fleet_units} 使用可能`],['輸送能力',`${s.allocation_count} · 未充足 ${s.unfilled_allocation_units}`],['経路固定',`${s.routing_constraint_count}`],['追加備蓄',`${s.target_stock_count}`],['補給需要',`${s.requirement_count}`],['待ち供給',`${fmt(s.queued_supply_t)} t`],['輸送中',`${fmt(s.in_transit_t)} t`],['到着待機',`${fmt(s.arrival_waiting_t)} t`]].map(metricHtml).join('');
    populateLocationSelects();renderMovementPlanFilters();renderMovementPlanList();renderLogisticsDecisionLane();renderNetwork();renderSupplyPolicies();renderRequirements();renderFleet();renderAllocations();renderVehicleProduction();renderCargoFlows();renderMarket();renderMovementPlanInspector();
  }

  document.addEventListener('change',(event)=>{
    if(state.activeView!=='logistics')return;
    if(event.target.matches('[data-market-mode]')){const control=event.target.closest('.market-target-control');const unit=control?.querySelector(':scope > span');if(unit)unit.textContent=event.target.value==='rate'?'t/日':'t';}
  });

  document.addEventListener('change',(event)=>{
    const holder=event.target.closest('[data-priority-direct]');if(!holder)return;
    const id=holder.dataset.priorityId,priority=Number(holder.value);
    if(holder.dataset.priorityDirect==='retirement')void command('SetFleetRetirementPriority',{retirement_id:id,priority}).catch(()=>{});
    else if(holder.dataset.priorityDirect==='production')void command('SetVehicleProductionSettings',{production_id:id,priority}).catch(()=>{});
  });

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='logistics')return;
    const decision=event.target.closest('[data-logistics-decision-kind]');if(decision){
      state.decisionContext={decision_area:'logistics',subject_kind:decision.dataset.logisticsDecisionKind,subject_id:decision.dataset.logisticsDecisionId};
      state.selectedMovementPlanId=null;render();$('#networkStage')?.scrollIntoView?.({block:'nearest'});return;
    }
    const decisionTarget=event.target.closest('[data-logistics-decision-target]');if(decisionTarget){
      const target=decisionTarget.dataset.logisticsDecisionTarget;
      if(target==='cargo')$('#cargoTable')?.scrollIntoView?.({block:'nearest'});
      return;
    }
    const movementPlanButton=event.target.closest('[data-movement-plan-id]');if(movementPlanButton){state.selectedMovementPlanId=movementPlanButton.dataset.movementPlanId;render();return;}
    const movementPlanLine=event.target.closest('[data-movement-plan-line]');if(movementPlanLine){state.selectedMovementPlanId=movementPlanLine.dataset.movementPlanLine;render();return;}
    const network=event.target.closest('[data-network-location]');if(network){$('#movementPlanOriginFilter').value=network.dataset.networkLocation;renderMovementPlanList();return;}
    if(event.target.closest('#newTargetStockButton')){openTargetStockDialog();return;}
    if(event.target.closest('#newAllocationButton')){openAllocationDialog();return;} if(event.target.closest('#movementPlanAllocationButton')){openAllocationDialog((state.movementPlans?.items||[]).find((x)=>x.id===state.selectedMovementPlanId));return;}
    const requirementNetwork=event.target.closest('[data-requirement-network]');if(requirementNetwork){state.decisionContext={decision_area:'logistics',subject_kind:'supply_requirement',subject_id:requirementNetwork.dataset.requirementNetwork};state.selectedMovementPlanId=null;render();$('#networkStage')?.scrollIntoView?.({block:'nearest'});return;}
    const allocationNetwork=event.target.closest('[data-allocation-network]');if(allocationNetwork){state.decisionContext={decision_area:'logistics',subject_kind:'transport_allocation',subject_id:allocationNetwork.dataset.allocationNetwork};state.selectedMovementPlanId=null;render();$('#networkStage')?.scrollIntoView?.({block:'nearest'});return;}
    const allocationEdit=event.target.closest('[data-allocation-edit]');if(allocationEdit){const a=(state.transportAllocations?.items||[]).find((x)=>x.id===allocationEdit.dataset.allocationEdit);if(a)openAllocationDialog(null,a);return;}
    const allocationOption=event.target.closest('[data-allocation-option]');if(allocationOption){$('#allocationVehicle').value=allocationOption.dataset.allocationOption;allocationCapacityInitialized=false;renderAllocationServiceOptions();renderAllocationCapacityControls();scheduleAllocationPreview({immediate:true});return;}
    const allocationPriority=event.target.closest('[data-allocation-priority]');if(allocationPriority){setAllocationPriority(allocationPriority.dataset.allocationPriority);return;}
    const allocationPreset=event.target.closest('[data-allocation-capacity-preset]');if(allocationPreset){const direction=allocationPreset.dataset.allocationCapacityPreset==='forward'?'Forward':'Reverse';setAllocationCapacity(direction,Number(allocationPreset.dataset.allocationCapacityValue),{expandRange:true});scheduleAllocationPreview({immediate:true});return;}
    const allocationMovement=event.target.closest('[data-allocation-movement]');if(allocationMovement){const id=allocationMovement.dataset.allocationMovement,index=allocationMovementSelection.indexOf(id);if(index>=0)allocationMovementSelection.splice(index,1);else allocationMovementSelection.push(id);renderAllocationMovementChoices();scheduleAllocationPreview();return;}
    const relocate=event.target.closest('[data-fleet-relocate]');if(relocate){openRelocationDialog(relocate.dataset.fleetRelocate,relocate.dataset.fleetSource,Number(relocate.dataset.fleetFree));return;}
    const retire=event.target.closest('[data-fleet-retire]');if(retire){const row=retire.closest('[data-fleet-pool-row]');try{await command('RetireFleet',{vehicle_definition_id:retire.dataset.fleetRetire,operational_node_id:retire.dataset.fleetRetireNode,units:Number(row.querySelector('[data-retirement-units]').value),priority:Number(row.querySelector('[data-retirement-priority]').value)});}catch{}return;}
    const retirementCancel=event.target.closest('[data-retirement-cancel]');if(retirementCancel){try{await command('CancelFleetRetirement',{retirement_id:retirementCancel.dataset.retirementCancel});}catch{}return;}
    const allocationToggle=event.target.closest('[data-allocation-toggle]');if(allocationToggle){try{await command(allocationToggle.dataset.paused==='1'?'ResumeTransportAllocation':'PauseTransportAllocation',{allocation_id:allocationToggle.dataset.allocationToggle});}catch{}return;}
    const allocationDelete=event.target.closest('[data-allocation-delete]');if(allocationDelete){try{await command('DeleteTransportAllocation',{allocation_id:allocationDelete.dataset.allocationDelete});}catch{}return;}
    const produce=event.target.closest('[data-produce-vehicle]');if(produce){const row=produce.closest('[data-production-option-row]');try{await command('ProduceVehicle',{vehicle_definition_id:produce.dataset.produceVehicle,operational_node_id:produce.dataset.productionLocation,priority:Number(row.querySelector('[data-production-priority-value]').value)});}catch{}return;}
    const productionToggle=event.target.closest('[data-production-toggle]');if(productionToggle){try{await command(productionToggle.dataset.paused==='1'?'ResumeVehicleProduction':'PauseVehicleProduction',{production_id:productionToggle.dataset.productionToggle});}catch{}return;}
    const marketCreate=event.target.closest('[data-market-create]');if(marketCreate){const root=marketCreate.closest('[data-new-market-order]');try{await command('CreateTradeOrder',marketOrderPayload(root,{create:true}));await A.completeActiveDraft('market:new');}catch{}return;}
    const marketSave=event.target.closest('[data-market-save]');if(marketSave){const root=marketSave.closest('[data-market-order-row]');try{await command('UpdateTradeOrder',{order_id:marketSave.dataset.marketSave,...marketOrderPayload(root)});await A.completeActiveDraft(`market:${marketSave.dataset.marketSave}`);}catch{}return;}
    const marketCancel=event.target.closest('[data-market-cancel]');if(marketCancel){try{await command('CancelTradeOrder',{order_id:marketCancel.dataset.marketCancel});await A.completeActiveDraft(`market:${marketCancel.dataset.marketCancel}`);}catch{}return;}
    const constraintEdit=event.target.closest('[data-routing-constraint-edit]');if(constraintEdit){const row=(logistics().routing_constraints||[]).find((x)=>constraintScopeKey(x)===constraintEdit.dataset.routingConstraintEdit);if(row)openRoutingConstraintDialog(row);return;}
    const viaChoice=event.target.closest('[data-routing-via-node]');if(viaChoice){const id=viaChoice.dataset.routingViaNode;if(routingConstraintViaSelection.has(id))routingConstraintViaSelection.delete(id);else routingConstraintViaSelection.add(id);renderRoutingConstraintChoices();return;}
    const allocationChoice=event.target.closest('[data-routing-allocation]');if(allocationChoice){const id=allocationChoice.dataset.routingAllocation;if(routingConstraintAllocationSelection.has(id))routingConstraintAllocationSelection.delete(id);else routingConstraintAllocationSelection.add(id);renderRoutingConstraintChoices();return;}
    const constraintClear=event.target.closest('[data-routing-constraint-clear]');if(constraintClear){const row=(logistics().routing_constraints||[]).find((x)=>constraintScopeKey(x)===constraintClear.dataset.routingConstraintClear);if(row){try{await command('ClearSupplyRoutingConstraint',constraintScopePayload(row));}catch{}}return;}
    const requirementConstraint=event.target.closest('[data-requirement-constraint]');if(requirementConstraint){const prefill={destination_id:requirementConstraint.dataset.destinationId,owner_kind:requirementConstraint.dataset.ownerKind,owner_id:requirementConstraint.dataset.ownerId,resource_id:requirementConstraint.dataset.resourceId};const existing=(logistics().routing_constraints||[]).find((x)=>x.destination_id===prefill.destination_id&&x.owner_kind===prefill.owner_kind&&x.owner_id===prefill.owner_id&&x.resource_id===prefill.resource_id);openRoutingConstraintDialog(existing||null,prefill);return;}
    const targetEdit=event.target.closest('[data-target-stock-edit]');if(targetEdit){openTargetStockDialog(targetEdit.dataset.targetStockEdit,targetEdit.dataset.resourceId);return;}
    const targetPreset=event.target.closest('[data-target-stock-preset]');if(targetPreset){setTargetStockQuantity(Number(targetPreset.dataset.targetStockValue),{expandRange:true});return;}
    const priorityButton=event.target.closest('[data-target-stock-priority]');if(priorityButton){setTargetStockPriority(priorityButton.dataset.targetStockPriority);return;}
    const targetDelete=event.target.closest('[data-target-stock-delete]');if(targetDelete){try{await command('DeleteTargetStock',{destination_id:targetDelete.dataset.targetStockDelete,resource_id:targetDelete.dataset.resourceId});}catch{}return;}
  });

  document.addEventListener('DOMContentLoaded',()=>{
    $('#movementPlanOriginFilter').addEventListener('change',renderMovementPlanList);$('#movementPlanDestinationFilter').addEventListener('change',renderMovementPlanList);
    const closeRoutingConstraint=()=>{editingRoutingConstraintScope=null;routingConstraintDraftScope=null;routingConstraintViaSelection.clear();routingConstraintAllocationSelection.clear();$('#routingConstraintDialog').close();};
    $('#routingConstraintCloseButton').addEventListener('click',closeRoutingConstraint);$('#routingConstraintCancelButton').addEventListener('click',closeRoutingConstraint);
    $('#routingConstraintForm').addEventListener('submit',async(event)=>{event.preventDefault();if(!routingConstraintDraftScope){banner('補給需要から対象需要を選択してください','error');return;}const payload={...routingConstraintDraftScope,source_node_id:$('#routingConstraintSource').value||null,required_via_node_ids:[...routingConstraintViaSelection],required_transport_allocation_ids:[...routingConstraintAllocationSelection]};if(!payload.source_node_id&&!payload.required_via_node_ids.length&&!payload.required_transport_allocation_ids.length){banner('固定供給元、必須経由拠点、必須輸送区間のいずれかを選択してください','error');return;}try{await command('SetSupplyRoutingConstraint',payload);editingRoutingConstraintScope=null;routingConstraintDraftScope=null;$('#routingConstraintDialog').close();}catch{}});
    const closeTargetStock=()=>{targetStockOptionsSerial++;targetStockOptionsView=null;$('#targetStockDialog').close();};
    $('#targetStockCloseButton').addEventListener('click',closeTargetStock);$('#targetStockCancelButton').addEventListener('click',closeTargetStock);
    $('#targetStockDestination').addEventListener('change',updateTargetStockOptions);$('#targetStockResource').addEventListener('change',updateTargetStockOptions);
    $('#targetStockQuantityRange').addEventListener('input',(event)=>setTargetStockQuantity(event.target.value));$('#targetStockQuantity').addEventListener('input',(event)=>setTargetStockQuantity(event.target.value,{expandRange:true}));
    $('#targetStockForm').addEventListener('submit',async(event)=>{event.preventDefault();try{await command('SetTargetStock',{destination_id:$('#targetStockDestination').value,resource_id:$('#targetStockResource').value,target_quantity_t:Number($('#targetStockQuantity').value),priority:Number($('#targetStockPriority').value)});closeTargetStock();}catch{}});
    $('#allocationVehicle').addEventListener('change',()=>{allocationCapacityInitialized=false;renderAllocationServiceOptions();renderAllocationCapacityControls();scheduleAllocationPreview();});$('#allocationSource').addEventListener('change',()=>{allocationMovementSelection=[];renderAllocationMovementChoices();updateAllocationServiceOptions();});$('#allocationDestination').addEventListener('change',()=>{allocationMovementSelection=[];renderAllocationMovementChoices();updateAllocationServiceOptions();});$('#allocationCloseButton').addEventListener('click',()=>{editingAllocationId=null;allocationOptionSerial++;allocationOptionsView=null;allocationMovementSelection=[];allocationPreviewSerial++;if(allocationPreviewTimer){clearTimeout(allocationPreviewTimer);allocationPreviewTimer=null;}$('#allocationDialog').close();});$('#allocationCancelButton').addEventListener('click',()=>{editingAllocationId=null;allocationOptionSerial++;allocationOptionsView=null;allocationMovementSelection=[];allocationPreviewSerial++;if(allocationPreviewTimer){clearTimeout(allocationPreviewTimer);allocationPreviewTimer=null;}$('#allocationDialog').close();});
    $('#allocationForwardRange').addEventListener('input',(event)=>setAllocationCapacity('Forward',event.target.value));$('#allocationReverseRange').addEventListener('input',(event)=>setAllocationCapacity('Reverse',event.target.value));$('#allocationForward').addEventListener('input',(event)=>setAllocationCapacity('Forward',event.target.value,{expandRange:true}));$('#allocationReverse').addEventListener('input',(event)=>setAllocationCapacity('Reverse',event.target.value,{expandRange:true}));
    $('#allocationForm').addEventListener('submit',async(event)=>{event.preventDefault();const constraint=[...allocationMovementSelection];try{const capacity={target_forward_t_per_day:Number($('#allocationForward').value),target_reverse_t_per_day:Number($('#allocationReverse').value),provisioning_priority:Number($('#allocationPriority').value)};if(editingAllocationId){await command('UpdateTransportAllocation',{allocation_id:editingAllocationId,...capacity});if(constraint.length)await command('SetTransportMovementConstraint',{allocation_id:editingAllocationId,movement_plan_ids:constraint});else await command('ClearTransportMovementConstraint',{allocation_id:editingAllocationId});editingAllocationId=null;}else{await command('CreateTransportAllocation',{vehicle_definition_id:$('#allocationVehicle').value,anchor_node_id:$('#allocationSource').value,destination_id:$('#allocationDestination').value,...capacity,movement_hard_constraint:constraint.length?constraint:null});}allocationMovementSelection=[];$('#allocationDialog').close();}catch{}});
    $('#relocationCloseButton').addEventListener('click',()=>{relocationContext=null;relocationPreviewKey=null;relocationPreviewSerial++;$('#relocationDialog').close();});$('#relocationCancelButton').addEventListener('click',()=>{relocationContext=null;relocationPreviewKey=null;relocationPreviewSerial++;$('#relocationDialog').close();});
    $('#relocationDestination').addEventListener('change',updateRelocationPreview);$('#relocationUnits').addEventListener('input',updateRelocationPreview);
    $('#relocationForm').addEventListener('submit',async(event)=>{event.preventDefault();if(!relocationContext)return;const destination=$('#relocationDestination').value;if(destination===relocationContext.source_id){banner('Fleet移動の出発地と到着地は異なる必要があります','error');return;}try{await command('RelocateFleet',{vehicle_definition_id:relocationContext.vehicle_definition_id,units:Number($('#relocationUnits').value),source_id:relocationContext.source_id,destination_id:destination,movement_hard_constraint:null});relocationContext=null;relocationPreviewKey=null;$('#relocationDialog').close();}catch{}});
  });

  document.addEventListener('spaceidle:snapshot',()=>{if(relocationContext&&$('#relocationDialog')?.open)updateRelocationPreview();});

  window.SpaceIdleLogistics={render,openRoutingConstraintDialog,openTargetStockDialog,openAllocationDialog};
})();
