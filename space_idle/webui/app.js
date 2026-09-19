(() => {
  'use strict';

  const state = {
    revision:null, session:null, world:null, catalog:null, operationalNodeId:null, operationalNode:null,
    flow:null, dependencyAnalyticsCurrent:null, dependencyAnalyticsForecast:null, globalIssues:null, bottlenecks:null, projects:null, buildOptions:null,
    research:null, scientificExplorations:null, surveys:null, surfaceMap:null, contracts:null, logisticsSummary:null, logistics:null, movementPlans:null,
    fleet:null, transportAllocations:null, cargoFlows:null, market:null,
    selectedMovementPlanId:null, selectedGlobalNodeId:null, decisionContext:null, activeSection:'global', activeView:'global', activeTab:'overview', inspector:null,
    busy:false, syncInFlight:null,
  };

  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]));
  const fmt = (v, digits=1) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ja-JP',{maximumFractionDigits:digits}) : '—';
  const pct = (v) => Number.isFinite(Number(v)) ? `${Math.round(Number(v)*100)}%` : '—';
  const byId = (items=[]) => Object.fromEntries(items.map((x)=>[x.id,x]));
  const resourceMap = () => byId(state.catalog?.resources || []);
  const locationMap = () => byId(state.world?.operational_nodes || []);
  const definitionMaps = () => [
    state.catalog?.resources, state.catalog?.facilities, state.catalog?.vehicles,
    state.catalog?.operational_nodes, state.catalog?.processes, state.catalog?.research,
    state.catalog?.movement_plans,
  ].filter(Boolean).map(byId);
  const definitionName = (id) => {
    if(!id)return '—';
    for(const map of definitionMaps()){
      const item=map[id]; if(item?.display_name)return item.display_name;
    }
    return id;
  };
  const locationName = (id) => locationMap()[id]?.display_name || definitionName(id);
  const resourceName = (id) => resourceMap()[id]?.display_name || definitionName(id);

  const capabilityLabels={
    base_construction:'基礎建設',basic_machine_shop:'基礎機械加工',bulk_storage:'バルク保管',
    cargo_storage:'一般貨物保管',cargo_transfer:'貨物移送',construction_yard:'建設ヤード',
    cryogenic_storage:'極低温保管',grid_power:'外部電力網',heavy_equipment_assembly:'重機組立',
    industrial_electrolysis:'工業電解',industrial_power:'産業電力',launch_operations:'打上げ運用',
    launch_vehicle_servicing:'打上げ機整備',metallurgy:'金属精錬',ore_processing:'鉱石処理',
    power_grid:'電力網',propellant_production:'推進剤製造',regolith_excavation:'レゴリス採掘',
    research_lab:'研究設備',robotic_operations:'ロボット運用',sintering:'焼結',
    spacecraft_servicing:'宇宙船整備',structural_fabrication:'構造材加工',surface_survey:'地表探査',
    refueling_interface:'補給インターフェース',docking_interface:'ドッキングインターフェース',
    vehicle_assembly:'輸送機組立',vehicle_refueling:'輸送機補給',water_extraction:'水抽出',water_storage:'水保管',
  };
  const operationLabels={powered_ascent:'動力離昇',launch:'打上げ',spaceflight:'宇宙航行',landing:'着陸',atmospheric_entry:'大気圏突入'};
  const locationKindLabels={surface:'地表',orbital:'軌道',orbit:'軌道'};
  const stateLabels={
    available:'利用可能',active:'稼働',paused:'停止',locked:'未解禁',complete:'完了',
    offered:'提示中',accepted:'受諾済み',declined:'辞退',failed:'失敗',waiting:'待機',
    in_transit:'輸送中',arrival_waiting:'到着待機',theory:'理論',prototype:'試作',demonstration:'実証',operational_experience:'運用経験',
    planned:'計画',procuring:'調達中',ready:'施工待ち',building:'施工中',cancelled:'取消済み',
    awaiting_inputs:'資材待ち',awaiting_vehicle:'Vehicle待ち',awaiting_fleet:'Fleet待ち',
    preparing:'出発準備',outbound:'往路移動中',exploration:'科学探査中',return_preparing:'復路準備',returning:'復路移動中',
  };
  const capabilityName=(id)=>capabilityLabels[id]||id||'—';
  const operationName=(id)=>operationLabels[id]||id||'—';

  function userFacingText(value){
    let text=String(value??'');
    text=text.replace(/fleet_units:([0-9.+-]+)\/([0-9.+-]+)/g,(_,current,required)=>`free Fleet不足: ${current} / ${required} unit`);
    text=text.replace(/relocation_units:positive_required/g,'移動unit数は1以上が必要です');
    text=text.replace(/relocation_endpoints:must_differ/g,'出発地と到着地は異なる必要があります');
    text=text.replace(/endurance:([0-9.+-]+)\/([0-9.+-]+)/g,(_,required,available)=>`航続期間不足: ${required} / ${available} 日`);
    text=text.replace(/resource:([^:;]+):([^:;]+):([0-9.+-]+)\/([0-9.+-]+)/g,(_,locationId,resourceId,current,required)=>`${locationName(locationId)}の${resourceName(resourceId)}不足: ${current} / ${required} t`);
    text=text.replace(/relocation_path:(.+)/g,(_,detail)=>`移動経路不成立: ${detail}`);
    text=text.replace(/market_interface_disabled/g,'Market Interface停止');
    text=text.replace(/offer_unavailable/g,'Market offerなし');
    text=text.replace(/price_condition/g,'価格条件外');
    text=text.replace(/provider_supply/g,'Market Provider供給不足');
    text=text.replace(/provider_demand/g,'Market Provider需要不足');
    text=text.replace(/resource_not_at_market_interface/g,'Market Interfaceに売却対象Resourceなし');
    text=text.replace(/survey_scope_empty/g,'Survey対象Cellを1つ以上選択してください');
    text=text.replace(/survey_resource_scope_empty/g,'Survey対象Resourceを1つ以上選択してください');
    text=text.replace(/knowledge_goal_reached/g,'選択範囲は指定したKnowledge Goalへ到達済みです');
    text=text.replace(/invalid_target_knowledge_level/g,'Knowledge Goalが不正です');
    text=text.replace(/campaign_scope_conflict:([^;]+)/g,(_,id)=>`既存Survey Campaignと対象が重複しています: ${id}`);
    text=text.replace(/unknown_target:([^:;]+):([^;]+)/g,(_,cellId,resourceId)=>`Survey対象外の組み合わせです: ${cellId} / ${resourceName(resourceId)}`);
    text=text.replace(/unknown_target:([^;]+)/g,(_,cellId)=>`Survey対象外のCellです: ${cellId}`);
    text=text.replace(/unmet_demand/g,'未充足需要');
    text=text.replace(/external_dependency/g,'外部依存');
    text=text.replace(/storage_over_capacity/g,'Usable Storage Capacity超過');
    text=text.replace(/physical_storage_full/g,'Physical Storage Capacity満杯');
    text=text.replace(/usable_storage_full/g,'Usable Storage Capacity満杯');
    for(const map of definitionMaps()){
      for(const [id,item] of Object.entries(map)){
        if(text.includes(id)&&item?.display_name)text=text.split(id).join(item.display_name);
      }
    }
    text=text.replace(/technology:([^;]+)/g,(_,ids)=>`技術不足: ${ids.split(',').map((x)=>definitionName(x.trim())).join('、')}`);
    text=text.replace(/vehicle_capability:([a-zA-Z0-9_.-]+)/g,(_,id)=>`Vehicle能力不足: ${capabilityName(id)}`);
    text=text.replace(/capability:([a-zA-Z0-9_.-]+)/g,(_,id)=>`能力不足: ${capabilityName(id)}`);
    text=text.replace(/payload_capacity:([0-9.+-]+)\/([0-9.+-]+)/g,(_,current,required)=>`利用可能Payload不足: ${current} / ${required} t`);
    text=text.replace(/(available|active|infrastructure):([a-zA-Z0-9_.-]+):([0-9.+-]+)\/([0-9.+-]+)/g,(_,kind,id,current,required)=>{
      const label=kind==='available'?'利用可能能力':kind==='active'?'稼働能力':'インフラ能力';
      return `${label}不足: ${capabilityName(id)} ${current} / ${required}`;
    });
    return text;
  }

  function banner(message,kind='info',timeout=4200){
    const el=$('#statusBanner'); if(!el)return;
    el.textContent=message; el.className=`status-banner${kind==='error'?' error':''}`; el.hidden=false;
    clearTimeout(banner.timer); if(timeout)banner.timer=setTimeout(()=>{el.hidden=true;},timeout);
  }
  function setConnection(kind,text){
    const el=$('#connectionState'); if(!el)return;
    el.className=`connection-state ${kind==='ok'?'is-ok':kind==='error'?'is-error':''}`;
    if(el.lastElementChild)el.lastElementChild.textContent=text;
  }

  async function api(path,options={}){
    const headers={'Accept':'application/json',...(options.headers||{})};
    if(options.body!==undefined)headers['Content-Type']='application/json';
    const response=await fetch(path,{...options,headers,cache:'no-store'});
    const text=response.status===304?'':await response.text();
    const payload=text?JSON.parse(text):null;
    const rev=response.headers.get('X-Space-Idle-Revision');
    if(rev!==null)state.revision=Math.max(state.revision??0,Number(rev));
    if(!response.ok){
      const err=new Error(payload?.error?.message||`${response.status} ${response.statusText}`);
      err.code=payload?.error?.code; err.status=response.status; err.details=payload?.error?.details; throw err;
    }
    if(payload?.revision!==undefined)state.revision=Math.max(state.revision??0,Number(payload.revision));
    return payload?.data??payload;
  }

  const interactionControl=(identity)=>{
    if(!identity)return null;
    if(identity.kind==='id')return document.getElementById(identity.key);
    if(identity.kind==='draft')return $$('[data-draft-key]').find((control)=>control.dataset.draftKey===identity.key)||null;
    return null;
  };
  const controlIdentity=(control)=>control?.dataset?.draftKey?{kind:'draft',key:control.dataset.draftKey}:control?.id?{kind:'id',key:control.id}:null;
  const controlBaseline=(control)=>{
    if(!control)return null;
    if(control.tagName==='SELECT'){
      const option=[...control.options].find((row)=>row.defaultSelected);
      return option?.value??control.options[0]?.value??'';
    }
    return control.defaultValue;
  };
  const interactionValue=(control)=>{
    const snapshot={value:control.value,baseline:controlBaseline(control)};
    if(control?.type==='checkbox'||control?.type==='radio'){
      snapshot.checked=control.checked;
      snapshot.baselineChecked=control.defaultChecked;
    }
    return snapshot;
  };
  const restoreDraftValue=(control,snapshot)=>{
    if(!control||!snapshot)return;
    const baseline=controlBaseline(control);
    if(baseline===snapshot.baseline||baseline===snapshot.value)control.value=snapshot.value;
    if((control.type==='checkbox'||control.type==='radio')&&snapshot.checked!==undefined){
      const baselineChecked=control.defaultChecked;
      if(baselineChecked===snapshot.baselineChecked||baselineChecked===snapshot.checked)control.checked=snapshot.checked;
    }
  };
  function captureInteraction(){
    const active=document.activeElement;
    const activeControl=active&&/^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName)?active:null;
    const identity=controlIdentity(activeControl);
    const drafts=$$('[data-draft-key]').map((control)=>({
      key:control.dataset.draftKey,
      ...interactionValue(control),
    }));
    const scroll=document.scrollingElement;
    return {
      control:identity?{...identity,...interactionValue(activeControl),selectionStart:typeof activeControl.selectionStart==='number'?activeControl.selectionStart:null,selectionEnd:typeof activeControl.selectionEnd==='number'?activeControl.selectionEnd:null}:null,
      drafts,
      scrollLeft:scroll?.scrollLeft||0,
      scrollTop:scroll?.scrollTop||0,
    };
  }
  function restoreInteraction(snapshot){
    if(!snapshot)return;
    for(const draft of snapshot.drafts||[]){
      restoreDraftValue(interactionControl({kind:'draft',key:draft.key}),draft);
    }
    if(snapshot.control){
      const control=interactionControl(snapshot.control);
      if(control&&/^(INPUT|SELECT|TEXTAREA)$/.test(control.tagName)){
        restoreDraftValue(control,snapshot.control);
        control.focus({preventScroll:true});
        if(snapshot.control.selectionStart!==null&&typeof control.setSelectionRange==='function'){
          try{control.setSelectionRange(snapshot.control.selectionStart,snapshot.control.selectionEnd);}catch{}
        }
      }
    }
    if(document.scrollingElement){document.scrollingElement.scrollLeft=snapshot.scrollLeft;document.scrollingElement.scrollTop=snapshot.scrollTop;}
  }

  function applyUiSnapshot(data){
    state.session=data.session; state.world=data.world; state.globalIssues=data.global_issues;
    state.research=data.research; state.scientificExplorations=data.scientific_explorations; state.contracts=data.contracts; state.logisticsSummary=data.logistics_summary; state.logistics=data.logistics;
    state.movementPlans=data.movement_plans; state.fleet=data.fleet; state.transportAllocations=data.transport_allocations; state.cargoFlows=data.cargo_flows;
    state.market=data.market??state.market;
    if(data.operational_node!==undefined)state.operationalNode=data.operational_node;
    if(data.flow!==undefined)state.flow=data.flow;
    if(data.dependency_analytics_current!==undefined)state.dependencyAnalyticsCurrent=data.dependency_analytics_current;
    if(data.dependency_analytics_forecast!==undefined)state.dependencyAnalyticsForecast=data.dependency_analytics_forecast;
    if(data.projects!==undefined)state.projects=data.projects;
    if(data.build_options!==undefined)state.buildOptions=data.build_options;
    if(data.bottlenecks!==undefined)state.bottlenecks=data.bottlenecks;
    if(data.surveys!==undefined)state.surveys=data.surveys;
    if(data.surface_map!==undefined)state.surfaceMap=data.surface_map;
    if(state.selectedMovementPlanId&&!(state.movementPlans?.items||[]).some((r)=>r.id===state.selectedMovementPlanId))state.selectedMovementPlanId=null;
  }

  async function beginMutation(){
    while(state.busy)await new Promise((resolve)=>setTimeout(resolve,20));
    state.busy=true; document.body.classList.add('is-busy');
    const pending=state.syncInFlight?.promise; if(pending){try{await pending;}catch{}}
  }
  function endMutation(){state.busy=false;document.body.classList.remove('is-busy');}
  async function command(type,payload={}){
    await beginMutation();
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
    await beginMutation();
    try{state.session=await api('/api/v1/time-control',{method:'POST',body:JSON.stringify(payload)});renderHeader();await loadUiSnapshot();}
    finally{endMutation();}
  }

  function issueHtml(issue){
    const rawMessage=Array.isArray(issue)?issue[1]:issue.message||issue.code||String(issue);
    const rawCategory=Array.isArray(issue)?issue[0]:issue.category||issue.source||'';
    let message=userFacingText(rawMessage);
    if(rawCategory==='technology'&&definitionName(rawMessage)!==rawMessage)message=`必要技術: ${definitionName(rawMessage)}`;
    if(rawCategory==='capability')message=`必要能力: ${capabilityName(rawMessage)}`;
    const categoryLabels={technology:'技術条件',capability:'能力条件',environment:'環境条件',contract:'契約',logistics:'物流',construction:'建設',research:'研究',exploration:'科学探査',survey:'探査',storage:'保管',power:'電力'};
    const category=categoryLabels[rawCategory]||userFacingText(rawCategory);
    const context=!Array.isArray(issue)&&issue.entity_id?definitionName(issue.entity_id):'';
    const meta=[category,context&&context!==issue.entity_id?context:''].filter(Boolean).join(' · ');
    return `<div class="issue"><div class="issue-title">${esc(message)}</div>${meta?`<div class="issue-meta">${esc(meta)}</div>`:''}</div>`;
  }
  const metricHtml=([label,value])=>`<div class="metric-chip"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  const statHtml=(label,value)=>`<div class="stat-box"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  const signed=(v)=>{const n=Number(v||0);return `${n>0?'+':''}${fmt(n,2)}`;};

  function renderHeader(){
    $('#dayValue').textContent=fmt(state.world?.day??state.session?.day,0);
    const stored=state.research?.stored_points,capacity=state.research?.storage_capacity_points;
    $('#researchPointValue').textContent=stored==null?'—':`${fmt(stored,1)} / ${fmt(capacity,1)}`;
    const attention=(state.globalIssues?.items||[]).length;
    $('#attentionCount').textContent=String(attention);
    $('#attentionButton').classList.toggle('has-attention',attention>0);
    $('#revisionValue').textContent=state.revision??state.session?.revision??'—';
    $('#appVersion').textContent=`v${state.session?.app_version||'0.4.5'}`;
    const paused=Boolean(state.session?.time_paused),speed=Number(state.session?.time_speed_multiplier||1),pause=$('#timePauseButton');
    pause.textContent=paused?'▶ 再開':'⏸ 一時停止'; pause.setAttribute('aria-label',paused?'再開':'一時停止'); pause.setAttribute('aria-pressed',paused?'true':'false');
    $$('[data-time-speed]').forEach((button)=>{const selected=Number(button.dataset.timeSpeed)===speed;button.setAttribute('aria-pressed',selected?'true':'false');button.disabled=selected;});
    const timeState=$('#timeState'); if(timeState)timeState.textContent=state.session?.automatic_progress_enabled===false?'自動進行無効':paused?`停止中 · ${speed}×`:`自動進行 · ${speed}×`;
  }
  function renderLocations(){
    $('#locationList').innerHTML=(state.world?.operational_nodes||[]).map((loc)=>`<button type="button" class="location-button ${loc.id===state.operationalNodeId?'is-active':''}" data-location-id="${esc(loc.id)}"><span class="location-name">${esc(loc.display_name)}</span><span class="location-meta"><span>${esc(locationKindLabels[loc.kind]||loc.kind)}</span><span>設備 ${loc.facility_count}</span><span>建設 ${loc.active_project_count}</span></span></button>`).join('');
  }
  function renderGlobalIssues(){
    const issues=state.globalIssues?.items||[];
    $('#globalIssues').innerHTML=issues.length?issues.slice(0,8).map(issueHtml).join('')+(issues.length>8?`<div class="cell-sub">ほか ${issues.length-8} 件</div>`:''):'<div class="empty-state">現在、全体blockerはありません。</div>';
  }
  const kvHtml=(rows)=>`<dl class="kv-grid">${rows.map(([key,value])=>`<dt>${key}</dt><dd>${value}</dd>`).join('')}</dl>`;
  function globalMapPositions(nodes){
    const order={surface:0,orbital:1,orbit:1};
    const rows=new Map();
    [...nodes].sort((a,b)=>{
      const ka=order[a.kind]??2,kb=order[b.kind]??2;
      if(ka!==kb)return ka-kb;
      return String(a.display_name||a.id).localeCompare(String(b.display_name||b.id),'ja');
    }).forEach((node)=>{
      const band=order[node.kind]??2;
      if(!rows.has(band))rows.set(band,[]);
      rows.get(band).push(node);
    });
    const positions={};
    [...rows.entries()].sort(([a],[b])=>a-b).forEach(([band,items],rowIndex)=>{
      const y=[72,42,18][Math.min(rowIndex,2)];
      items.forEach((node,index)=>{
        const x=items.length===1?50:14+(72*index/(items.length-1));
        positions[node.id]=[x,y];
      });
    });
    return positions;
  }
  function renderGlobalMap(nodes){
    const positions=globalMapPositions(nodes);
    const selected=state.selectedGlobalNodeId||state.operationalNodeId||nodes[0]?.id||null;
    if(selected&&!state.selectedGlobalNodeId)state.selectedGlobalNodeId=selected;
    const edges=(state.movementPlans?.items||[]).map((plan)=>{
      const a=positions[plan.origin_id],b=positions[plan.destination_id];
      if(!a||!b)return'';
      const className=plan.service_feasible_now?'global-map-link is-available':'global-map-link';
      return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" class="${className}"><title>${esc(locationName(plan.origin_id))} → ${esc(locationName(plan.destination_id))}</title></line>`;
    }).join('');
    const nodeHtml=nodes.map((node)=>{
      const [x,y]=positions[node.id]||[50,50];
      const active=node.id===selected;
      return `<button type="button" class="global-map-node ${active?'is-selected':''}" style="left:${x}%;top:${y}%" data-global-node-id="${esc(node.id)}" aria-pressed="${active?'true':'false'}"><span class="global-map-node-name">${esc(node.display_name)}</span><span class="global-map-node-meta">${esc(locationKindLabels[node.kind]||node.kind)} · 設備 ${node.facility_count}</span></button>`;
    }).join('');
    return `<section class="global-map-card"><div class="global-map-toolbar"><div><div class="eyebrow">SYSTEM MAP</div><h2>活動領域</h2></div><span class="badge">${nodes.length} 拠点</span></div><div class="global-map-stage" role="group" aria-label="全体Map"><svg class="global-map-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${edges}</svg>${nodeHtml||'<div class="empty-state">拠点なし</div>'}</div></section>`;
  }
  function renderGlobalView(){
    const canvas=$('#globalCanvasContent'),inspector=$('#globalInspectorContent');
    if(!canvas||!inspector)return;
    const nodes=state.world?.operational_nodes||[],issues=state.globalIssues?.items||[];
    const researchItems=state.research?.items||[],explorations=state.scientificExplorations?.items||[],campaigns=state.surveys?.campaigns||[];
    const activeResearch=researchItems.filter((row)=>row.state==='active').length;
    const activeExploration=explorations.filter((row)=>!['complete','completed','cancelled','failed'].includes(row.state)).length;
    const activeSurvey=campaigns.filter((row)=>!['complete','completed','cancelled','failed'].includes(row.state)).length;
    const fleetTotal=Number(state.logisticsSummary?.fleet_units||0),fleetFree=Number(state.logisticsSummary?.free_fleet_units||0);
    $('#globalHeadlineMetrics').innerHTML=[['拠点',nodes.length],['要確認',issues.length],['研究中',activeResearch],['Fleet',`${fleetFree}/${fleetTotal} free`]].map(metricHtml).join('');
    const attentionItems=issues.length?issues.slice(0,8).map((issue,index)=>issue.navigation?`<button type="button" class="global-attention-item" data-attention-index="${index}">${issueHtml(issue)}<span class="attention-open-hint">関連箇所を開く</span></button>`:`<div class="global-attention-item">${issueHtml(issue)}</div>`).join(''):'<div class="empty-state">現在、Player判断を必要とする全体blockerはありません。</div>';
    canvas.innerHTML=`<div class="global-decision-grid">${renderGlobalMap(nodes)}<section class="card global-attention-card"><div class="card-heading"><h3>要確認</h3><span class="badge ${issues.length?'warn':'ok'}">${issues.length}</span></div><div class="card-body global-attention-list">${attentionItems}</div></section></div><div class="global-domain-strip"><button type="button" class="domain-entry" data-section="research"><span>研究</span><strong>${activeResearch}</strong><small>進行中</small></button><button type="button" class="domain-entry" data-section="exploration"><span>探査</span><strong>${activeExploration+activeSurvey}</strong><small>科学探査 / Survey</small></button><button type="button" class="domain-entry" data-section="logistics"><span>輸送</span><strong>${fleetFree}/${fleetTotal}</strong><small>free Fleet</small></button></div>`;
    const selectedId=state.selectedGlobalNodeId||state.operationalNodeId;
    const selectedNode=nodes.find((row)=>row.id===selectedId)||nodes[0]||null;
    const relatedPlans=(state.movementPlans?.items||[]).filter((row)=>selectedNode&&(row.origin_id===selectedNode.id||row.destination_id===selectedNode.id));
    const relatedIssues=issues.filter((issue)=>issue.navigation?.operational_node_id===selectedNode?.id);
    $('#globalInspectorTitle').textContent=selectedNode?.display_name||'全体状況';
    inspector.innerHTML=selectedNode?`<section class="inspector-section"><h3>拠点Context</h3>${kvHtml([['種別',esc(locationKindLabels[selectedNode.kind]||selectedNode.kind)],['設備',fmt(selectedNode.facility_count,0)],['進行中建設',fmt(selectedNode.active_project_count,0)],['接続経路',fmt(relatedPlans.length,0)],['要確認',fmt(relatedIssues.length,0)]])}</section><section class="inspector-section"><h3>次の操作</h3><div class="action-stack"><button type="button" class="primary" data-open-location="${esc(selectedNode.id)}">この拠点を開く</button><button type="button" data-open-node-logistics="${esc(selectedNode.id)}">関連輸送を見る</button></div></section><section class="inspector-section"><h3>Context</h3><div class="section-context-note">Map選択を維持したまま拠点・輸送へ移動します。内部IDを覚えて入力する必要はありません。</div></section>`:`<section class="inspector-section"><h3>組織全体</h3><div class="kv-grid"><dt>Research Point</dt><dd>${fmt(state.research?.stored_points,1)} / ${fmt(state.research?.storage_capacity_points,1)}</dd><dt>Fleet</dt><dd>${fleetFree} free / ${fleetTotal}</dd></div></section>`;
  }
  function renderEconomyContext(){
    const root=$('#economyInspectorContent');if(!root)return;
    const market=state.market;
    root.innerHTML=market?`<section class="inspector-section"><h3>Funds</h3><div class="kv-grid"><dt>総残高</dt><dd>$${fmt(market.funds_total_musd,2)}M</dd><dt>利用可能</dt><dd>$${fmt(market.funds_available_musd,2)}M</dd><dt>Interface</dt><dd>${(market.interfaces||[]).length}</dd><dt>Order</dt><dd>${(market.orders||[]).length}</dd></div></section><section class="inspector-section"><h3>意味</h3><div class="section-context-note">FundsはExternal Resource Marketの決済専用です。建設・研究・輸送等の一般活動コストとしては使用しません。</div></section>`:'<div class="empty-state">Market状態を読み込み中です。</div>';
  }
  function renderSectionChrome(){
    $$('.primary-nav-button').forEach((button)=>button.classList.toggle('is-active',button.dataset.section===state.activeSection));
    $('#globalView').hidden=state.activeSection!=='global';
    $('#operationsView').hidden=!['location','research','exploration'].includes(state.activeSection);
    $('#logisticsView').hidden=state.activeSection!=='logistics';
    $('#economyView').hidden=state.activeSection!=='economy';
    $$('[data-section-tab]').forEach((button)=>{button.hidden=button.dataset.sectionTab!==state.activeSection;});
    const tabbar=$('#operationsView .tabbar');if(tabbar)tabbar.hidden=state.activeSection==='research';
  }
  function renderAll(){
    renderHeader(); renderLocations(); renderGlobalIssues(); renderSectionChrome(); renderGlobalView(); renderEconomyContext();
    if(['location','research','exploration'].includes(state.activeSection))window.SpaceIdleOperations?.render();
    if(['logistics','economy'].includes(state.activeSection))window.SpaceIdleLogistics?.render();
  }

  function clearLocationSnapshot(){
    state.operationalNode=null; state.flow=null; state.dependencyAnalyticsCurrent=null; state.dependencyAnalyticsForecast=null; state.bottlenecks=null; state.projects=null;
    state.buildOptions=null; state.surveys=null; state.surfaceMap=null; state.inspector=null;
  }
  async function loadUiSnapshot({preserveInteraction=true}={}){
    while(state.syncInFlight){
      const pending=state.syncInFlight;
      if(pending.operationalNodeId===state.operationalNodeId)return pending.promise;
      try{await pending.promise;}catch{}
      if(state.syncInFlight===pending)state.syncInFlight=null;
    }
    const locationId=state.operationalNodeId;
    const request={operationalNodeId:locationId,promise:null};
    request.promise=(async()=>{
      const locationSummary=(state.world?.operational_nodes||[]).find((row)=>row.id===locationId);
      const params=new URLSearchParams();
      if(locationId)params.set('operational_node_id',locationId);
      if(locationSummary?.body_id&&state.activeTab==='surface')params.set('surface_body_id',locationSummary.body_id);
      const suffix=params.size?`?${params.toString()}`:'';
      const data=await api(`/api/v1/ui-state${suffix}`);
      if(locationId!==state.operationalNodeId)return data;
      applyUiSnapshot(data);
      if(!state.operationalNodeId||!(state.world?.operational_nodes||[]).some((x)=>x.id===state.operationalNodeId)){
        state.operationalNodeId=state.world?.operational_nodes?.[0]?.id??null;
        if(state.operationalNodeId&&data.operational_node===undefined){const nested=await api(`/api/v1/ui-state?operational_node_id=${encodeURIComponent(state.operationalNodeId)}`);applyUiSnapshot(nested);}
      }
      const interaction=preserveInteraction?captureInteraction():null;
      renderAll(); restoreInteraction(interaction); setConnection('ok','PC Server');
      document.dispatchEvent(new CustomEvent('spaceidle:snapshot',{detail:state}));
      return data;
    })();
    state.syncInFlight=request;
    try{return await request.promise;}finally{if(state.syncInFlight===request)state.syncInFlight=null;}
  }
  async function loadLocation(locationId){
    if(!locationId||locationId===state.operationalNodeId)return;
    state.operationalNodeId=locationId;
    clearLocationSnapshot();
    renderAll();
    await loadUiSnapshot({preserveInteraction:false});
  }
  function setActiveSection(section){
    if(!['global','location','research','exploration','logistics','economy'].includes(section))return;
    state.activeSection=section;
    state.activeView=['logistics','economy'].includes(section)?'logistics':section==='global'?'global':'operations';
    if(section==='location'&&!['overview','facilities','inventory','construction'].includes(state.activeTab))state.activeTab='overview';
    if(section==='research')state.activeTab='research';
    if(section==='exploration'&&!['scientific-exploration','survey','surface'].includes(state.activeTab))state.activeTab='scientific-exploration';
    state.inspector=null;
    state.decisionContext=null;
    renderAll();
  }

  function decisionContextTab(target){
    if(target.decision_area==='location'){
      if(target.subject_kind==='facility')return 'facilities';
      if(target.subject_kind==='project')return 'construction';
      if(target.subject_kind==='inventory')return 'inventory';
      return 'overview';
    }
    if(target.decision_area==='research')return 'research';
    if(target.decision_area==='exploration')return target.subject_kind==='survey_campaign'?'survey':'scientific-exploration';
    return null;
  }

  async function openDecisionContext(target){
    if(!target?.decision_area)return;
    if(target.operational_node_id&&target.operational_node_id!==state.operationalNodeId){
      await loadLocation(target.operational_node_id);
    }
    setActiveSection(target.decision_area);
    state.decisionContext={...target};
    const tab=decisionContextTab(target);
    if(tab)state.activeTab=tab;
    if(target.subject_kind==='facility'&&target.subject_id)state.inspector={type:'facility',id:target.subject_id};
    else if(target.subject_kind==='project'&&target.subject_id)state.inspector={type:'project',id:target.subject_id};
    else if(target.subject_kind==='research'&&target.subject_id)state.inspector={type:'research',id:target.subject_id};
    else if(target.subject_kind==='scientific_exploration'&&target.subject_id)state.inspector={type:'scientific-exploration',id:target.subject_id};
    else if(target.subject_kind==='survey_campaign'&&target.subject_id)state.inspector={type:'survey-campaign',id:target.subject_id};
    if(target.subject_kind==='movement_plan'&&target.subject_id)state.selectedMovementPlanId=target.subject_id;
    renderAll();
    queueMicrotask(()=>{
      const selected=document.querySelector('.is-context-target, tbody tr.is-selected, .movement-plan-button.is-selected');
      selected?.scrollIntoView?.({block:'nearest',inline:'nearest'});
    });
  }
  function setActiveView(view){setActiveSection(view==='logistics'?'logistics':'location');}

  async function initialLoad(){
    setConnection('pending','接続中');
    const [catalog,world]=await Promise.all([api('/api/v1/catalog'),api('/api/v1/world')]);
    state.catalog=catalog; state.world=world; state.operationalNodeId=world.operational_nodes?.[0]?.id??null;
    await loadUiSnapshot({preserveInteraction:false}); $('#app').setAttribute('aria-busy','false');
  }

  window.SpaceIdleApp={
    state,$,$$,esc,fmt,pct,byId,definitionName,locationName,resourceName,capabilityName,operationName,
    locationKindLabels,stateLabels,userFacingText,issueHtml,metricHtml,statHtml,signed,
    api,command,banner,setConnection,loadUiSnapshot,loadLocation,setActiveSection,setActiveView,openDecisionContext,
  };

  document.addEventListener('click',async(event)=>{
    const sectionBtn=event.target.closest('[data-section]'); if(sectionBtn){setActiveSection(sectionBtn.dataset.section);return;}
    const openLocation=event.target.closest('[data-open-location]'); if(openLocation){await loadLocation(openLocation.dataset.openLocation);setActiveSection('location');return;}
    const globalNode=event.target.closest('[data-global-node-id]'); if(globalNode){state.selectedGlobalNodeId=globalNode.dataset.globalNodeId;renderGlobalView();return;}
    const globalLogistics=event.target.closest('[data-open-node-logistics]'); if(globalLogistics){state.selectedGlobalNodeId=globalLogistics.dataset.openNodeLogistics;setActiveSection('logistics');return;}
    const attentionItem=event.target.closest('[data-attention-index]'); if(attentionItem){const issue=(state.globalIssues?.items||[])[Number(attentionItem.dataset.attentionIndex)];if(issue?.navigation)await openDecisionContext(issue.navigation);return;}
    if(event.target.closest('#attentionButton')){setActiveSection('global');return;}
    const locBtn=event.target.closest('[data-location-id]'); if(locBtn){await loadLocation(locBtn.dataset.locationId);return;}
    if(event.target.closest('#timePauseButton')){try{await setTimeControl({paused:!Boolean(state.session?.time_paused)});}catch(e){banner(e.message,'error');}return;}
    const speed=event.target.closest('[data-time-speed]'); if(speed){try{await setTimeControl({speed_multiplier:Number(speed.dataset.timeSpeed)});}catch(e){banner(e.message,'error');}return;}
    if(event.target.closest('#refreshButton')){try{await loadUiSnapshot();banner('最新状態を取得しました');}catch(e){banner(e.message,'error');}return;}
  });
  window.addEventListener('online',()=>setConnection('ok','PC Server'));
  window.addEventListener('offline',()=>setConnection('error','オフライン'));
  window.setInterval(()=>{if(document.hidden||state.busy||$('#app')?.getAttribute('aria-busy')!=='false')return;loadUiSnapshot().catch((err)=>{setConnection('error','同期失敗');console.error(err);});},1000);
  document.addEventListener('DOMContentLoaded',()=>{
    $('#saveButton').addEventListener('click',async()=>{await beginMutation();try{await api('/api/v1/session/save',{method:'POST',body:JSON.stringify({slot:'manual'})});banner('manual スロットへ保存しました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
    $('#loadButton').addEventListener('click',async()=>{await beginMutation();try{await api('/api/v1/session/load',{method:'POST',body:JSON.stringify({slot:'manual',apply_offline:true})});await loadUiSnapshot({preserveInteraction:false});banner('manual スロットを読み込みました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
    initialLoad().catch((err)=>{setConnection('error','接続失敗');banner(`Serverへ接続できません: ${err.message}`,'error',0);$('#app').setAttribute('aria-busy','false');});
  });
})();
