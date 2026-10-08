(() => {
  'use strict';

  // A single presentation surface is moved between the Overview and Transport workspaces.
  // Its positions and viewport are UI-only; they never constitute Spatial or Transport state.
  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before system_map.js');
  const {state,esc,fmt,locationName,locationKindName}=A;
  const viewport={scale:1,x:0,y:0};
  let stage=null;
  let dragging=null;

  function selectedResource(){return state.systemMapResourceId||null;}
  function requirementRows(){return state.logistics?.requirements||[];}
  function cargoRows(){return state.cargoFlows?.items||state.logistics?.cargo_flows||[];}
  function contextRelations(allocations){
    const target=state.decisionContext;
    const selectedAllocations=new Set();
    const selectedNodes=new Set();
    if(target?.decision_area!=='logistics')return {selectedAllocations,selectedNodes};
    const requirements=requirementRows().filter((row)=>
      (target.subject_kind==='supply_requirement'&&row.id===target.subject_id)
      ||(target.subject_kind==='dependency_resource'&&row.destination_id===target.operational_node_id&&row.resource_id===target.resource_id));
    for(const row of requirements){
      selectedNodes.add(row.destination_id);
      if(row.selected_source_id)selectedNodes.add(row.selected_source_id);
      for(const id of row.selected_transport_allocation_ids||[])selectedAllocations.add(id);
    }
    const flow=target.subject_kind==='cargo_flow'?cargoRows().find((row)=>row.id===target.subject_id):null;
    if(flow){
      for(const id of [flow.source_id,flow.destination_id,flow.final_destination_id,...(flow.service_destinations||[])])if(id)selectedNodes.add(id);
    }
    if(target.subject_kind==='transport_allocation')selectedAllocations.add(target.subject_id);
    if(target.subject_kind==='transport_relation'){
      for(const row of allocations){if(pairKey(row.anchor_node_id,row.destination_id)===target.subject_id)selectedAllocations.add(row.id);}
    }
    if(target.operational_node_id)selectedNodes.add(target.operational_node_id);
    return {selectedAllocations,selectedNodes};
  }
  function positionsFor(nodes){
    // Stable body groups are diagrammatic, not a proportional distance projection.
    const groups=new Map();
    for(const node of nodes){
      const key=node.body_id||`context:${node.id}`;
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(node);
    }
    const keys=[...groups.keys()].sort((a,b)=>a.localeCompare(b));
    const positions={};
    keys.forEach((key,groupIndex)=>{
      const group=groups.get(key).slice().sort((a,b)=>
        String(a.kind||'').localeCompare(String(b.kind||''))||String(a.id).localeCompare(String(b.id)));
      const x=keys.length===1?50:14+72*groupIndex/(keys.length-1);
      group.forEach((node,index)=>{
        const y=group.length===1?50:20+60*index/(group.length-1);
        positions[node.id]=[x,y];
      });
    });
    return positions;
  }

  function pairKey(a,b){return [String(a),String(b)].sort().join('\u001f');}
  function allocationPairs(allocations){
    const pairs=new Map();
    for(const row of allocations){
      if(!row.anchor_node_id||!row.destination_id)continue;
      const key=pairKey(row.anchor_node_id,row.destination_id);
      if(!pairs.has(key))pairs.set(key,{key,from:row.anchor_node_id,to:row.destination_id,items:[]});
      pairs.get(key).items.push(row);
    }
    return [...pairs.values()].sort((a,b)=>a.key.localeCompare(b.key));
  }

  function ensureStage(){
    if(stage)return stage;
    stage=document.createElement('section');
    stage.className='system-map-frame';
    stage.innerHTML=`<div class="system-map-toolbar"><div><div class="eyebrow">SYSTEM MAP</div><strong id="systemMapMode">空間概要</strong><span class="system-map-note">概略配置 · 距離と移動日数は数値で確認</span></div><div class="system-map-controls"><label class="system-map-resource-label">Resource <select id="systemMapResourceFilter" aria-label="地図で強調するResource"></select></label><button type="button" data-system-zoom="out" aria-label="縮小">−</button><button type="button" data-system-zoom="reset" aria-label="表示位置をリセット">等倍</button><button type="button" data-system-zoom="in" aria-label="拡大">＋</button></div></div><div id="systemMapBodies" class="system-map-bodies" aria-label="天体と地表マップへの移動"></div><div id="systemMapStage" class="system-map-stage" role="group" aria-label="共通System Map"><div id="systemMapViewport" class="system-map-viewport"><svg class="system-map-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"></svg><div class="system-map-nodes"></div></div></div><div class="system-map-legend" id="systemMapLegend"></div><div class="system-map-relations" id="systemMapRelations" aria-label="輸送関係一覧"></div>`;
    return stage;
  }
  function applyViewport(){
    if(!stage)return;
    stage.querySelector('#systemMapViewport').style.transform=`translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`;
  }
  function detach(){if(stage?.isConnected)stage.remove();}
  function render(signals={}){
    const host=document.querySelector(state.activeSection==='logistics'?'#systemMapMountLogistics':'#systemMapMountGlobal');
    if(!host)return;
    const root=ensureStage();
    if(root.parentElement!==host)host.appendChild(root);
    const logistics=state.activeSection==='logistics';
    const nodes=state.world?.operational_nodes||[];
    const bodies=state.catalog?.celestial_bodies||[];
    const bodyNames=new Map(bodies.map((body)=>[body.id,body.display_name]));
    const bodyLinks=`<span>天体 · 地表へ</span>`+bodies.map((body)=>
      `<button type="button" data-system-body-id="${esc(body.id)}" aria-pressed="${state.selectedSurfaceBodyId===body.id?'true':'false'}">${esc(body.display_name)} <small>地表Map</small></button>`
    ).join('');
    A.setHtmlIfChanged(root.querySelector('#systemMapBodies'),bodyLinks);
    const positions=positionsFor(nodes);
    const allocations=state.transportAllocations?.items||[];
    const pairs=allocationPairs(allocations);
    const resourceFilter=root.querySelector('#systemMapResourceFilter');
    const resourceOptions=`<option value="">すべて</option>`+(state.catalog?.resources||[]).map((r)=>`<option value="${esc(r.id)}">${esc(r.display_name)}</option>`).join('');
    A.setHtmlIfChanged(resourceFilter,resourceOptions);
    resourceFilter.value=selectedResource()||'';
    const context=contextRelations(allocations);
    const relevantRequirements=requirementRows().filter((row)=>!selectedResource()||row.resource_id===selectedResource());
    const relevantFlows=cargoRows().filter((row)=>!selectedResource()||row.resource_id===selectedResource());
    const relatedNodes=new Set(context.selectedNodes);
    for(const row of relevantRequirements)if(selectedResource())relatedNodes.add(row.destination_id);
    for(const row of relevantFlows)if(selectedResource())for(const id of [row.source_id,row.destination_id,row.final_destination_id])if(id)relatedNodes.add(id);
    const present=new Set(nodes.map((node)=>node.id));
    const selected=present.has(state.selectedGlobalNodeId)?state.selectedGlobalNodeId:present.has(state.operationalNodeId)?state.operationalNodeId:nodes[0]?.id||null;
    if(selected!==state.selectedGlobalNodeId)state.selectedGlobalNodeId=selected;
    root.querySelector('#systemMapMode').textContent=logistics?'物流 · 実輸送能力':'活動領域 · 拠点';
    // Only actual allocation edges are shown by default. Movement feasibility is not a service.
    let edges=pairs.map((pair)=>{
      const a=positions[pair.from],b=positions[pair.to];if(!a||!b)return'';
      const selectedPair=pair.items.some((row)=>context.selectedAllocations.has(row.id))
        ||(state.decisionContext?.subject_kind==='operational_node'&&(pair.from===selected||pair.to===selected));
      const active=pair.items.some((row)=>!row.paused&&(Number(row.available?.forward_t_per_day)||Number(row.available?.reverse_t_per_day)));
      const coords=`x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"`;
      return `<line class="system-map-edge-hit" ${coords} data-system-pair="${esc(pair.key)}"/><line class="system-map-edge ${active?'is-service':'is-unavailable'} ${selectedPair?'is-context-related':''}" ${coords}><title>${esc(locationName(pair.from))} ↔ ${esc(locationName(pair.to))} · ${pair.items.length} 設定</title></line>`;
    }).join('');
    const selectedPlan=(state.movementPlans?.items||[]).find((row)=>row.id===state.selectedMovementPlanId);
    if(selectedPlan){
      const a=positions[selectedPlan.origin_id],b=positions[selectedPlan.destination_id];
      if(a&&b)edges+=`<line class="system-map-edge is-candidate" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"><title>選択中のMovement候補（運用中とは限りません）</title></line>`;
    }
    // A selected Cargo Flow is displayed as physical cargo, never as a service
    // allocation or an un-dispatched requirement. Arrival-waiting has no motion.
    const cargoContext=state.decisionContext?.decision_area==='logistics'&&state.decisionContext.subject_kind==='cargo_flow'
      ?cargoRows().find((row)=>row.id===state.decisionContext.subject_id):null;
    if(logistics&&cargoContext){
      const a=positions[cargoContext.source_id],b=positions[cargoContext.destination_id];
      if(a&&b){
        const waiting=cargoContext.status==='arrival_waiting';
        edges+=`<line class="system-map-edge ${waiting?'is-cargo-waiting':'is-cargo-in-transit'}" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}"><title>${esc(waiting?'到着済み・受入／引継ぎ待ち':'輸送中Cargo')} · ${esc(locationName(cargoContext.source_id))} → ${esc(locationName(cargoContext.destination_id))} · ${fmt(cargoContext.amount_t,2)} t</title></line>`;
      }
    }
    A.setHtmlIfChanged(root.querySelector('.system-map-links'),edges);
    const html=nodes.map((node)=>{
      const [x,y]=positions[node.id];
      const signal=signals[node.id]||{};
      const highlighted=node.id===selected;
      const related=logistics&&relatedNodes.has(node.id);
      const counters=[['attention','要確認',signal.attention],['projects','案件',signal.projects],['founding','設立',signal.founding],['research','研究',signal.research],['survey','調査',signal.survey],['exploration','探査',signal.exploration]].filter(([, ,v])=>Number(v)>0);
      const signalClass=signal.attention?'has-attention':counters.length?'has-activity':'';
      return `<div class="system-map-node-shell" style="left:${x}%;top:${y}%"><button type="button" class="global-map-node ${highlighted?'is-selected':''} ${signalClass} ${related?'is-related':''}" data-system-node-id="${esc(node.id)}" aria-pressed="${highlighted?'true':'false'}"><span class="global-map-node-name">${esc(node.display_name)}</span><span class="global-map-node-meta">${esc(locationKindName(node.kind))} · ${esc(bodyNames.get(node.body_id)||'非地表Context')} · 設備 ${fmt(node.facility_count,0)}</span>${!logistics&&counters.length?`<span class="global-map-node-signals">${counters.map(([kind,label,n])=>`<span class="global-map-signal is-${kind}">${label} ${fmt(n,0)}</span>`).join('')}</span>`:''}</button></div>`;
    }).join('');
    A.replaceHtmlPreservingKeyed(root.querySelector('.system-map-nodes'),html,[{selector:'[data-system-node-id]',attributes:['data-system-node-id']}]);
    root.querySelector('#systemMapLegend').textContent=logistics?'実輸送設定（実線：利用可能／破線：停止・容量不足）、選択Movement候補（点線）、選択Cargo（太い破線：輸送中／点線：入庫待機）。需要・Cargo・Stockは別状態です。':'設定済みTransport接続と拠点Activity。選択中のMovement候補は点線。位置は概略であり移動可能性を保証しません。';
    const relationHtml=logistics?pairs.map((pair)=>{
      const title=`${locationName(pair.from)} ↔ ${locationName(pair.to)}`;
      return `<div class="system-map-relation"><button type="button" class="system-map-pair-button ${pair.items.some((r)=>context.selectedAllocations.has(r.id))?'is-selected':''}" data-system-pair="${esc(pair.key)}">${esc(title)} · ${pair.items.length} 設定を比較</button><div class="system-map-relation-options">${pair.items.map((row)=>{
        const selectedAllocation=context.selectedAllocations.has(row.id);
        const target=row.target_capacity||row.target||{};
        return `<button type="button" class="${selectedAllocation?'is-selected':''}" data-system-allocation-id="${esc(row.id)}" aria-pressed="${selectedAllocation?'true':'false'}"><span>${esc(row.display_name||row.id)} · ${esc(locationName(row.anchor_node_id))} → ${esc(locationName(row.destination_id))}</span><small>往路 / 復路 · 目標 ${fmt(target.forward_t_per_day,2)} / ${fmt(target.reverse_t_per_day,2)} t/日 · 利用可 ${fmt(row.available?.forward_t_per_day,2)} / ${fmt(row.available?.reverse_t_per_day,2)} t/日 · 使用 ${fmt(row.used?.forward_t_per_day,2)} / ${fmt(row.used?.reverse_t_per_day,2)} t/日 · 余力 ${fmt(row.spare?.forward_t_per_day,2)} / ${fmt(row.spare?.reverse_t_per_day,2)} t/日</small></button>`;
      }).join('')}</div></div>`;
    }).join(''):'';
    const relations=root.querySelector('#systemMapRelations');
    const focused=document.activeElement;
    const focusedKey=focused?.closest?.('[data-system-allocation-id],[data-system-pair]');
    const selector=focusedKey?.hasAttribute('data-system-allocation-id')?'[data-system-allocation-id]':'[data-system-pair]';
    const key=focusedKey?.getAttribute(selector==='[data-system-allocation-id]'?'data-system-allocation-id':'data-system-pair');
    A.setHtmlIfChanged(relations,relationHtml||'<span class="cell-sub">設定済みTransport Allocationなし</span>');
    if(key&&focusedKey&&!focusedKey.isConnected){
      const replacement=[...relations.querySelectorAll(selector)].find((element)=>
        element.getAttribute(selector==='[data-system-allocation-id]'?'data-system-allocation-id':'data-system-pair')===key);
      replacement?.focus({preventScroll:true});
    }
    applyViewport();
  }
  document.addEventListener('change',(event)=>{
    if(event.target.id!=='systemMapResourceFilter')return;
    state.systemMapResourceId=event.target.value||null;
    window.SpaceIdleSystemMap.onSelect();
  });
  document.addEventListener('click',async(event)=>{
    const body=event.target.closest('[data-system-body-id]');
    if(body){
      const bodyId=body.dataset.systemBodyId;
      if(!(state.catalog?.celestial_bodies||[]).some((item)=>item.id===bodyId))return;
      await A.openDecisionContext({decision_area:'exploration',subject_kind:'celestial_body',subject_id:bodyId});
      return;
    }
    const zoom=event.target.closest('[data-system-zoom]');
    if(zoom){const action=zoom.dataset.systemZoom;if(action==='reset'){viewport.scale=1;viewport.x=0;viewport.y=0;}else viewport.scale=Math.min(2.5,Math.max(.75,viewport.scale*(action==='in'?1.25:.8)));applyViewport();return;}
    const node=event.target.closest('[data-system-node-id]');
    if(node){state.selectedGlobalNodeId=node.dataset.systemNodeId;if(state.activeSection==='logistics')state.decisionContext={decision_area:'logistics',subject_kind:'operational_node',subject_id:state.selectedGlobalNodeId,resource_id:selectedResource()};window.SpaceIdleSystemMap.onSelect();return;}
    const pairButton=event.target.closest('[data-system-pair]');
    if(pairButton){
      const pair=allocationPairs(state.transportAllocations?.items||[]).find((row)=>row.key===pairButton.dataset.systemPair);
      if(!pair)return;
      if(state.activeSection!=='logistics')A.setActiveSection('logistics');
      state.selectedGlobalNodeId=pair.to;
      state.decisionContext={decision_area:'logistics',subject_kind:'transport_relation',subject_id:pair.key,resource_id:selectedResource()};
      window.SpaceIdleSystemMap.onSelect();return;
    }
    const alloc=event.target.closest('[data-system-allocation-id]');
    if(alloc){const row=(state.transportAllocations?.items||[]).find((item)=>item.id===alloc.dataset.systemAllocationId);if(row){state.selectedGlobalNodeId=row.destination_id;state.decisionContext={decision_area:'logistics',subject_kind:'transport_allocation',subject_id:row.id,operational_node_id:row.destination_id,resource_id:selectedResource()};window.SpaceIdleSystemMap.onSelect();}return;}
  });
  document.addEventListener('pointerdown',(event)=>{
    const area=event.target.closest('#systemMapStage');
    if(!area||event.target.closest('button'))return;
    dragging={id:event.pointerId,x:event.clientX,y:event.clientY,ox:viewport.x,oy:viewport.y};
    area.setPointerCapture(event.pointerId);
  });
  document.addEventListener('pointermove',(event)=>{
    if(!dragging||dragging.id!==event.pointerId)return;
    viewport.x=dragging.ox+event.clientX-dragging.x;viewport.y=dragging.oy+event.clientY-dragging.y;applyViewport();
  });
  for(const type of ['pointerup','pointercancel'])document.addEventListener(type,(event)=>{if(dragging?.id===event.pointerId)dragging=null;});
  window.SpaceIdleSystemMap={detach,render,positionsFor,allocationPairs,contextRelations,onSelect:()=>{}};
})();
