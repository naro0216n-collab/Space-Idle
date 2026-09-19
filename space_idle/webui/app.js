(() => {
  'use strict';

  const state = {
    revision:null, session:null, world:null, catalog:null, operationalNodeId:null, operationalNode:null,
    flow:null, dependencyAnalyticsCurrent:null, dependencyAnalyticsForecast:null, globalIssues:null, bottlenecks:null, projects:null, buildOptions:null,
    research:null, scientificExplorations:null, surveys:null, surfaceMap:null, contracts:null, logisticsSummary:null, logistics:null, movementPlans:null,
    fleet:null, transportAllocations:null, cargoFlows:null, market:null,
    selectedMovementPlanId:null, selectedGlobalNodeId:null, decisionContext:null, activeSection:'global', activeView:'global', activeTab:'overview', inspector:null,
    inspectorExpanded:false, sectionContexts:{location:null,research:null,exploration:null},
    activeDraft:null, busy:false, syncInFlight:null,
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
    basic_machinery_production:'基礎機械製造',basic_structural_material:'基礎構造材製造',
    industrial_water_supply:'工業用水供給',metal_ore_extraction:'金属鉱石採掘',aggregate_extraction:'骨材採掘',
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
  const playerTerms={
    movement_plan:'移動経路', transport_allocation:'輸送能力設定', supply_requirement:'補給需要',
    target_stock:'追加備蓄目標', provisioning_priority:'配備優先度', hard_constraint:'固定条件',
    execution_requirement_bundle:'稼働要件', transport_capacity:'輸送能力', cargo_flow:'輸送中貨物',
  };
  const playerTerm=(key,fallback=null)=>playerTerms[key]||fallback||key;
  const stateLabels={
    available:'利用可能',active:'稼働',paused:'停止',locked:'未解禁',complete:'完了',
    offered:'提示中',accepted:'受諾済み',declined:'辞退',failed:'失敗',waiting:'待機',
    in_transit:'輸送中',arrival_waiting:'到着待機',theory:'理論',prototype:'試作',demonstration:'実証',operational_experience:'運用経験',
    planned:'計画',procuring:'調達中',ready:'施工待ち',building:'施工中',cancelled:'取消済み',
    awaiting_inputs:'資材待ち',awaiting_vehicle:'Vehicle待ち',awaiting_fleet:'Fleet待ち',
    preparing:'出発準備',outbound:'往路移動中',exploration:'科学探査中',return_preparing:'復路準備',returning:'復路移動中',aborted:'中止済み',
  };
  const capabilityName=(id)=>capabilityLabels[id]||id||'—';
  const serviceLabels={
    construction_work:'建設施工能力',research_execution:'研究実行能力',surface_distribution:'地表物流能力',
    cargo_transfer:'貨物移送能力',vehicle_assembly:'輸送機組立能力',launch_vehicle_servicing:'打上げ機整備能力',
    spacecraft_servicing:'宇宙船整備能力',
  };
  const serviceName=(id)=>{
    if(!id)return '—';
    if(serviceLabels[id])return serviceLabels[id];
    if(id.startsWith('process:'))return `${definitionName(id.slice('process:'.length))} 工程能力`;
    if(id.startsWith('extraction:'))return `${resourceName(id.slice('extraction:'.length))} 採掘能力`;
    if(id.startsWith('survey_observation:'))return `${definitionName(id.slice('survey_observation:'.length))} 調査能力`;
    return capabilityName(id);
  };
  const operationName=(id)=>operationLabels[id]||id||'—';

  const genericValueLabels={
    facility:'設備',fleet:'Fleet',project:'建設案件',research:'研究',survey:'地表調査',scientific_exploration:'科学探査',
    construction:'建設',maintenance:'維持',process:'生産工程',extraction:'採掘',transport:'輸送',market:'市場',
    target_stock:'目標在庫',trade_order:'取引注文',contract:'契約',founding:'拠点設立',relocation:'移動',retirement:'退役',
    surface_location:'地表拠点',non_surface_operational_node:'宇宙拠点',organization:'組織共有',operational_node:'拠点',
    fixed:'固定',auto:'自動',vehicle:'機体',provider:'提供元',manual:'手動',
  };
  function userFacingText(value){
    const text=String(value??'');
    if(genericValueLabels[text])return genericValueLabels[text];
    if(stateLabels[text])return stateLabels[text];
    const defined=definitionName(text);
    return defined!==text?defined:text;
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

  const responseViewTokens=new Map();

  async function api(path,options={}){
    const {viewTokenKey=null,...fetchOptions}=options;
    const headers={'Accept':'application/json',...(fetchOptions.headers||{})};
    if(fetchOptions.body!==undefined)headers['Content-Type']='application/json';
    if(viewTokenKey&&responseViewTokens.has(viewTokenKey))headers['X-Space-Idle-Known-View']=responseViewTokens.get(viewTokenKey);
    const response=await fetch(path,{...fetchOptions,headers,cache:'no-store'});
    const viewToken=response.headers.get('ETag');
    if(viewTokenKey&&viewToken)responseViewTokens.set(viewTokenKey,viewToken);
    const text=await response.text();
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

  const structuredDraftScope=(control)=>control?.dataset?.structuredDraft!==undefined?(control.dataset.draftScope||''):'';
  const draftTitleForScope=(scope)=>{
    if(scope.startsWith('facility-build:'))return '設備建設計画';
    if(scope.startsWith('facility-upgrade:'))return '設備更新計画';
    if(scope.startsWith('facility-decommission:'))return '設備撤去計画';
    if(scope.startsWith('surface-build:'))return '地表設備建設';
    if(scope.startsWith('development:'))return '地表地域開発';
    if(scope.startsWith('foundation:'))return '拠点設立';
    if(scope==='survey:new')return '地表調査計画';
    if(scope.startsWith('survey:'))return '地表調査条件の編集';
    if(scope==='market:new')return '新規市場注文';
    if(scope.startsWith('market:'))return '市場注文の編集';
    return '計画編集';
  };
  const captureDraftRoute=()=>({
    operationalNodeId:state.operationalNodeId,activeSection:state.activeSection,activeTab:state.activeTab,
    inspector:state.inspector?{...state.inspector}:null,decisionContext:state.decisionContext?{...state.decisionContext}:null,
    selectedMovementPlanId:state.selectedMovementPlanId,
  });
  const interactionControl=(identity)=>{
    if(!identity)return null;
    if(identity.kind==='id')return document.getElementById(identity.key);
    if(identity.kind==='draft')return $$('[data-draft-key]').find((control)=>control.dataset.draftKey===identity.key&&(!identity.scope||control.dataset.draftScope===identity.scope))||null;
    if(identity.kind==='priority-choice'){
      const holder=identity.ownerKind==='draft'
        ? $$('[data-draft-key]').find((control)=>control.dataset.draftKey===identity.ownerKey&&(!identity.scope||control.dataset.draftScope===identity.scope))
        : document.getElementById(identity.ownerKey);
      return holder?.closest('.priority-segment')?.querySelector(`[data-priority-choice="${identity.choice}"]`)||null;
    }
    return null;
  };
  const controlIdentity=(control)=>{
    if(control?.matches?.('[data-priority-choice]')){
      const holder=control.closest('.priority-segment')?.querySelector('[data-priority-value-holder]');
      if(holder?.dataset?.draftKey)return {kind:'priority-choice',ownerKind:'draft',ownerKey:holder.dataset.draftKey,scope:holder.dataset.draftScope||'',choice:control.dataset.priorityChoice};
      if(holder?.id)return {kind:'priority-choice',ownerKind:'id',ownerKey:holder.id,choice:control.dataset.priorityChoice};
    }
    return control?.dataset?.draftKey?{kind:'draft',key:control.dataset.draftKey,scope:control.dataset.draftScope||''}:control?.id?{kind:'id',key:control.id}:null;
  };
  const controlBaseline=(control)=>{
    if(!control)return null;
    if(control.dataset?.draftBaseline!==undefined)return control.dataset.draftBaseline;
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
  const syncPrioritySegment=(control)=>{
    if(!control?.matches?.('[data-priority-value-holder]'))return;
    const group=control.closest('.priority-segment');
    if(!group)return;
    group.querySelectorAll('[data-priority-choice]').forEach((button)=>{
      const selected=button.dataset.priorityChoice===String(control.value);
      button.classList.toggle('is-selected',selected);
      button.setAttribute('aria-pressed',selected?'true':'false');
    });
  };
  const restoreDraftValue=(control,snapshot)=>{
    if(!control||!snapshot)return;
    const baseline=controlBaseline(control);
    if(baseline===snapshot.baseline||baseline===snapshot.value){control.value=snapshot.value;syncPrioritySegment(control);}
    if((control.type==='checkbox'||control.type==='radio')&&snapshot.checked!==undefined){
      const baselineChecked=control.defaultChecked;
      if(baselineChecked===snapshot.baselineChecked||baselineChecked===snapshot.checked)control.checked=snapshot.checked;
    }
  };
  const draftValueDirty=(snapshot)=>{
    if(snapshot.checked!==undefined&&snapshot.checked!==snapshot.baselineChecked)return true;
    return String(snapshot.value??'')!==String(snapshot.baseline??'');
  };
  function resetControlToBaseline(control){
    if(!control)return;
    if(control.type==='checkbox'||control.type==='radio')control.checked=control.defaultChecked;
    else control.value=controlBaseline(control)??'';
    syncPrioritySegment(control);
  }
  function renderActiveDraftBar(){
    const bar=$('#activeDraftBar');if(!bar)return;
    const draft=state.activeDraft;bar.hidden=!draft;
    const planning=$('#activeDraftPlanningState');
    if(!draft){if(planning)planning.hidden=true;return;}
    const title=$('#activeDraftTitle');if(title)title.textContent=draft.title||draftTitleForScope(draft.scope);
    if(planning){
      const mode=draft.planning;
      planning.hidden=!mode?.required;
      if(mode?.required)planning.textContent=mode.autoPaused&&!mode.playerOverrodeTime?'Planning · 自動停止中':mode.playerOverrodeTime?'Planning · 時間操作あり':'Planning · 停止中';
    }
  }
  async function ensurePlanningMode(draft){
    if(!draft?.planning?.required||draft.planning.started)return;
    const planning=draft.planning;planning.started=true;
    planning.previousPaused=Boolean(state.session?.time_paused);
    planning.previousSpeed=Number(state.session?.time_speed_multiplier||1);
    planning.autoPaused=!planning.previousPaused;
    planning.playerOverrodeTime=false;
    renderActiveDraftBar();
    if(!planning.autoPaused)return;
    planning.pausePromise=setTimeControl({paused:true},{source:'planning'}).then(()=>{
      if(state.activeDraft===draft){planning.pausePromise=null;renderActiveDraftBar();}
    }).catch((err)=>{
      planning.pausePromise=null;planning.autoPaused=false;planning.started=false;
      if(state.activeDraft===draft)renderActiveDraftBar();
      banner(`Planning停止に失敗しました: ${err.message}`,'error',7000);
    });
    await planning.pausePromise;
  }
  async function restorePlanningMode(draft){
    const planning=draft?.planning;
    if(!planning?.required)return;
    if(planning.pausePromise){try{await planning.pausePromise;}catch{}}
    if(!planning.autoPaused||planning.playerOverrodeTime)return;
    await setTimeControl({paused:Boolean(planning.previousPaused),speed_multiplier:Number(planning.previousSpeed||1)},{source:'planning'});
  }
  function restoreActiveDraftValues(){
    const draft=state.activeDraft;if(!draft)return;
    let restored=0;
    for(const [key,snapshot] of Object.entries(draft.values||{})){
      const control=interactionControl({kind:'draft',key,scope:draft.scope});
      if(!control)continue;
      const baseline=controlBaseline(control);
      const checkbox=control.type==='checkbox'||control.type==='radio';
      const authoritativeMatchesDraft=checkbox?snapshot.checked===control.defaultChecked:String(baseline??'')===String(snapshot.value??'');
      if(authoritativeMatchesDraft){delete draft.values[key];continue;}
      if(String(baseline??'')!==String(snapshot.baseline??'')){delete draft.values[key];continue;}
      restoreDraftValue(control,snapshot);restored+=1;
    }
    if(!Object.keys(draft.values||{}).length){
      state.activeDraft=null;renderActiveDraftBar();void restorePlanningMode(draft);return;
    }
    renderActiveDraftBar();
    if(restored)queueMicrotask(()=>document.dispatchEvent(new CustomEvent('spaceidle:draft-restored',{detail:{scope:draft.scope}})));
  }
  function trackStructuredDraft(control){
    const scope=structuredDraftScope(control);if(!scope||!control?.dataset?.draftKey)return;
    const snapshot=interactionValue(control),dirty=draftValueDirty(snapshot);
    if(state.activeDraft&&state.activeDraft.scope!==scope){
      if(dirty){resetControlToBaseline(control);banner(`「${state.activeDraft.title}」を編集中です。先に戻るかDraftを破棄してください。`,'error',6000);}
      return;
    }
    if(!state.activeDraft&&dirty){
      state.activeDraft={
        scope,title:control.dataset.draftTitle||draftTitleForScope(scope),route:captureDraftRoute(),values:{},
        planning:control.dataset.planningBaseline==='fixed'?{required:true,started:false,autoPaused:false,playerOverrodeTime:false}:null,
      };
      if(state.activeDraft.planning?.required)void ensurePlanningMode(state.activeDraft);
    }
    if(!state.activeDraft)return;
    if(dirty)state.activeDraft.values[control.dataset.draftKey]=snapshot;
    else delete state.activeDraft.values[control.dataset.draftKey];
    if(!Object.keys(state.activeDraft.values).length){
      const completed=state.activeDraft;state.activeDraft=null;renderActiveDraftBar();void restorePlanningMode(completed);return;
    }
    renderActiveDraftBar();
  }
  async function completeActiveDraft(scope){
    if(state.activeDraft?.scope!==scope)return;
    const completed=state.activeDraft;state.activeDraft=null;renderAll();await restorePlanningMode(completed);
  }
  async function discardActiveDraft(){
    const discarded=state.activeDraft;if(!discarded)return;
    state.activeDraft=null;renderAll();await restorePlanningMode(discarded);
  }
  async function returnToActiveDraft(){
    const draft=state.activeDraft;if(!draft)return;const route=draft.route||{};
    if(route.operationalNodeId&&route.operationalNodeId!==state.operationalNodeId)await loadLocation(route.operationalNodeId);
    if(route.activeSection)setActiveSection(route.activeSection);
    if(route.activeTab)state.activeTab=route.activeTab;
    state.inspector=route.inspector?{...route.inspector}:null;
    state.decisionContext=route.decisionContext?{...route.decisionContext}:null;
    state.selectedMovementPlanId=route.selectedMovementPlanId||null;
    if(['surface','survey'].includes(state.activeTab))await loadUiSnapshot({preserveInteraction:false});
    renderAll();
  }
  function captureInteraction(){
    const active=document.activeElement;
    const activeControl=active&&(/^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName)||active.matches?.('[data-priority-choice]'))?active:null;
    const identity=controlIdentity(activeControl);
    const drafts=$$('[data-draft-key]').map((control)=>({
      key:control.dataset.draftKey,
      scope:control.dataset.draftScope||'',
      ...interactionValue(control),
    }));
    const scroll=document.scrollingElement;
    const editableActive=activeControl&&/^(INPUT|SELECT|TEXTAREA)$/.test(activeControl.tagName);
    return {
      control:identity?{...identity,...(editableActive?interactionValue(activeControl):{}),selectionStart:editableActive&&typeof activeControl.selectionStart==='number'?activeControl.selectionStart:null,selectionEnd:editableActive&&typeof activeControl.selectionEnd==='number'?activeControl.selectionEnd:null}:null,
      drafts,
      scrollLeft:scroll?.scrollLeft||0,
      scrollTop:scroll?.scrollTop||0,
    };
  }
  function restoreInteraction(snapshot){
    if(!snapshot)return;
    for(const draft of snapshot.drafts||[]){
      restoreDraftValue(interactionControl({kind:'draft',key:draft.key,scope:draft.scope}),draft);
    }
    if(snapshot.control){
      const control=interactionControl(snapshot.control);
      if(control){
        if(/^(INPUT|SELECT|TEXTAREA)$/.test(control.tagName)){
          restoreDraftValue(control,snapshot.control);
          if(snapshot.control.selectionStart!==null&&typeof control.setSelectionRange==='function'){
            try{control.setSelectionRange(snapshot.control.selectionStart,snapshot.control.selectionEnd);}catch{}
          }
        }
        control.focus({preventScroll:true});
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
  async function setTimeControl(payload,{source='player'}={}){
    if(source==='player'&&state.activeDraft?.planning?.required){
      state.activeDraft.planning.playerOverrodeTime=true;
      renderActiveDraftBar();
    }
    await beginMutation();
    try{state.session=await api('/api/v1/time-control',{method:'POST',body:JSON.stringify(payload)});renderHeader();await loadUiSnapshot();}
    finally{endMutation();}
  }

  const constraintKindLabels={
    technology:'必要技術',capability:'必要能力',vehicle_capability:'必要機体能力',service:'サービス能力',
    resource:'必要資源',storage:'保管容量',power:'電力',knowledge:'調査知識',movement:'移動経路',routing:'経路条件',
    fleet:'Fleet',payload_capacity:'搭載能力',propellant_capacity:'推進剤容量',demand:'需要',
    external_dependency:'外部依存',research_point_capacity:'研究ポイント容量',infrastructure:'インフラ能力',
    active_upgrade_project:'更新案件進行中',storage_stock:'保管中資源あり',storage_over_capacity:'保管容量超過',
    physical_storage_full:'物理保管容量不足',usable_storage_full:'利用可能保管容量不足',
    knowledge_goal_reached:'調査目標へ到達済み',survey_decision_required:'観測手段の選択が必要',
    campaign_scope_conflict:'既存調査との対象重複',survey_candidate_unavailable:'利用可能な調査手段なし',
    no_transport_capacity:'輸送能力不足',market_interface_disabled:'市場接続停止中',offer_unavailable:'Market offerなし',
    price_condition:'価格条件外',provider_supply:'市場供給不足',provider_demand:'市場需要不足',
    resource_not_at_market_interface:'市場接続拠点に売却対象資源なし',paused_plan:'計画停止中',
    service_capacity_shortfall:'サービス能力不足',no_local_service_capacity:'拠点内サービス能力なし',
    no_organization_service_capacity:'組織共有サービス能力なし',outside_scope_service_dependency:'選択範囲外の共有サービス依存',
    arrival_backpressure:'到着先の受入能力不足',surface_infrastructure:'地表インフラ不足',provider_dependency:'供給元依存',
    constraint:'実行条件',
  };
  const affectedActionLabels={
    admit_inventory:'入庫',admit_storage:'保管',operate_facility:'設備運用',plan_facility_decommission:'設備撤去',
    plan_facility_upgrade:'設備更新',plan_build:'建設計画',progress_construction_project:'建設進行',develop_surface_cell:'地域開発',
    plan_founding:'拠点設立',select_research_execution_site:'研究地点選択',set_research_provider_fleet:'研究Fleet配備',
    operate_research_provider:'研究実行',progress_research:'研究進行',start_research:'研究開始',start_survey:'調査開始',
    progress_survey:'調査進行',progress_scientific_exploration:'科学探査進行',plan_vehicle_production:'輸送機生産計画',
    progress_vehicle_production:'輸送機生産',use_movement_plan:'移動',operate_transport_allocation:'輸送運用',
    satisfy_supply_requirement:'補給',satisfy_service_demand:'サービス需要',satisfy_forecast_service_demand:'将来サービス需要',
  };
  function constraintSubjectName(row){
    const id=row?.subject_id;if(id==null||id==='')return '';
    const kind=row.subject_kind||row.kind;
    if(kind==='resource'||kind==='knowledge')return resourceName(id);
    if(kind==='capability'||kind==='vehicle_capability'||kind==='infrastructure')return capabilityName(id);
    if(kind==='service')return serviceName(id);
    if(kind==='operational_node'||kind==='location')return locationName(id);
    const resolved=definitionName(id);
    return resolved===id?'':resolved;
  }
  function constraintValueText(value){
    if(value==null||value==='')return '';
    if(typeof value==='number')return fmt(value,Number.isInteger(value)?0:2);
    if(value==='positive')return '1以上';
    return String(value);
  }
  function constraintSummary(row){
    if(!row||typeof row!=='object')return '実行条件を確認してください';
    const label=constraintKindLabels[row.code]||constraintKindLabels[row.kind]||'実行条件';
    const subject=constraintSubjectName(row);
    const current=constraintValueText(row.current),required=constraintValueText(row.required);
    const unit=row.unit?` ${row.unit}`:'';
    if(current&&required)return `${label}${subject?` · ${subject}`:''}: ${current} / ${required}${unit}`;
    if(required)return `${label}${subject?` · ${subject}`:''}: 必要 ${required}${unit}`;
    if(current)return `${label}${subject?` · ${subject}`:''}: 現在 ${current}${unit}`;
    if(subject)return `${label}: ${subject}`;
    if(row.message&&row.message!==row.code)return String(row.message);
    return label;
  }
  function constraintMeta(row){
    if(!row||typeof row!=='object')return '';
    const parts=[];
    if(row.severity==='limiting')parts.push('制限要因');
    else if(row.severity==='blocking')parts.push('実行を阻害');
    if(row.affected_action&&affectedActionLabels[row.affected_action])parts.push(`対象: ${affectedActionLabels[row.affected_action]}`);
    const related=row.related_entity_id?definitionName(row.related_entity_id):'';
    if(related&&related!==row.related_entity_id)parts.push(related);
    if(row.category){
      const categoryLabels={technology:'技術条件',capability:'能力条件',environment:'環境条件',contract:'契約',logistics:'物流',construction:'建設',research:'研究',exploration:'科学探査',survey:'探査',storage:'保管',power:'電力'};
      const category=categoryLabels[row.category];if(category)parts.unshift(category);
    }
    return [...new Set(parts)].join(' · ');
  }
  function issueHtml(issue){
    const message=constraintSummary(issue);
    const meta=constraintMeta(issue);
    const nav=issue?.navigation;
    if(nav?.decision_area){
      const attrs=[
        ['data-issue-area',nav.decision_area],['data-issue-node',nav.operational_node_id],
        ['data-issue-subject-kind',nav.subject_kind],['data-issue-subject-id',nav.subject_id],
        ['data-issue-resource-id',nav.resource_id],
      ].filter(([,value])=>value!=null).map(([key,value])=>`${key}="${esc(value)}"`).join(' ');
      return `<button type="button" class="issue issue-link" ${attrs}><span class="issue-title">${esc(message)}</span>${meta?`<span class="issue-meta">${esc(meta)}</span>`:''}<span class="issue-open-hint">関連する判断へ</span></button>`;
    }
    return `<div class="issue"><div class="issue-title">${esc(message)}</div>${meta?`<div class="issue-meta">${esc(meta)}</div>`:''}</div>`;
  }
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  function prioritySegmentedHtml(selected=3,{inputAttributes='',disabled=false,label='優先度'}={}){
    const value=Math.min(5,Math.max(1,Number(selected)||3));
    const disabledAttr=disabled?'disabled':'';
    const buttons=[1,2,3,4,5].map((level)=>`<button type="button" data-priority-choice="${level}" class="${level===value?'is-selected':''}" aria-pressed="${level===value?'true':'false'}" ${disabledAttr}>${level}<span>${priorityLabels[level]}</span></button>`).join('');
    return `<div class="priority-field"><span class="priority-field-label">${esc(label)}</span><div class="priority-segment" role="group" aria-label="${esc(label)}">${buttons}<input type="hidden" data-priority-value-holder data-draft-baseline="${value}" value="${value}" ${inputAttributes}></div></div>`;
  }
  const metricHtml=([label,value])=>`<div class="metric-chip"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  const statHtml=(label,value)=>`<div class="stat-box"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  const signed=(v)=>{const n=Number(v||0);return `${n>0?'+':''}${fmt(n,2)}`;};
  function stableUiSignature(value){
    const text=JSON.stringify(value);
    let hash=2166136261;
    for(let index=0;index<text.length;index++){
      hash^=text.charCodeAt(index);
      hash=Math.imul(hash,16777619);
    }
    return (hash>>>0).toString(36);
  }

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
    const root=$('#locationList');if(!root)return;
    root.innerHTML=(state.world?.operational_nodes||[]).map((loc)=>`<button type="button" class="location-button ${loc.id===state.operationalNodeId?'is-active':''}" data-location-id="${esc(loc.id)}" aria-pressed="${loc.id===state.operationalNodeId?'true':'false'}"><span class="location-name">${esc(loc.display_name)}</span><span class="location-meta"><span>${esc(locationKindLabels[loc.kind]||loc.kind)}</span><span>設備 ${loc.facility_count}</span><span>建設 ${loc.active_project_count}</span></span></button>`).join('');
  }
  function renderGlobalIssues(){
    const issues=state.globalIssues?.items||[];
    $('#globalIssues').innerHTML=issues.length?issues.slice(0,8).map(issueHtml).join('')+(issues.length>8?`<div class="cell-sub">ほか ${issues.length-8} 件</div>`:''):'<div class="empty-state">現在、全体制約はありません。</div>';
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
    $('#globalHeadlineMetrics').innerHTML=[['拠点',nodes.length],['要確認',issues.length],['研究中',activeResearch],['Fleet',`${fleetFree}/${fleetTotal} 空き`]].map(metricHtml).join('');
    const attentionItems=issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state">現在、判断を必要とする全体制約はありません。</div>';
    canvas.innerHTML=`<div class="global-decision-grid">${renderGlobalMap(nodes)}<section class="card global-attention-card"><div class="card-heading"><h3>要確認</h3><span class="badge ${issues.length?'warn':'ok'}">${issues.length}</span></div><div class="card-body global-attention-list">${attentionItems}</div></section></div><div class="global-domain-strip"><button type="button" class="domain-entry" data-section="research"><span>研究</span><strong>${activeResearch}</strong><small>進行中</small></button><button type="button" class="domain-entry" data-section="exploration"><span>探査</span><strong>${activeExploration+activeSurvey}</strong><small>科学探査 / 地表調査</small></button><button type="button" class="domain-entry" data-section="logistics"><span>輸送</span><strong>${fleetFree}/${fleetTotal}</strong><small>空きFleet</small></button></div>`;
    const selectedId=state.selectedGlobalNodeId||state.operationalNodeId;
    const selectedNode=nodes.find((row)=>row.id===selectedId)||nodes[0]||null;
    const relatedPlans=(state.movementPlans?.items||[]).filter((row)=>selectedNode&&(row.origin_id===selectedNode.id||row.destination_id===selectedNode.id));
    const relatedIssues=issues.filter((issue)=>issue.navigation?.operational_node_id===selectedNode?.id);
    $('#globalInspectorTitle').textContent=selectedNode?.display_name||'全体状況';
    inspector.innerHTML=selectedNode?`<section class="inspector-section"><h3>拠点状況</h3>${kvHtml([['種別',esc(locationKindLabels[selectedNode.kind]||selectedNode.kind)],['設備',fmt(selectedNode.facility_count,0)],['進行中建設',fmt(selectedNode.active_project_count,0)],['接続経路',fmt(relatedPlans.length,0)],['要確認',fmt(relatedIssues.length,0)]])}</section><section class="inspector-section"><h3>次の操作</h3><div class="action-stack"><button type="button" class="primary" data-open-location="${esc(selectedNode.id)}">この拠点を開く</button><button type="button" data-open-node-logistics="${esc(selectedNode.id)}">関連輸送を見る</button></div></section><section class="inspector-section"><h3>選択の引き継ぎ</h3><div class="section-context-note">Map選択を維持したまま拠点・輸送へ移動します。内部IDを覚えて入力する必要はありません。</div></section>`:`<section class="inspector-section"><h3>組織全体</h3><div class="kv-grid"><dt>Research Point</dt><dd>${fmt(state.research?.stored_points,1)} / ${fmt(state.research?.storage_capacity_points,1)}</dd><dt>Fleet</dt><dd>${fleetFree} 機空き / ${fleetTotal} 機</dd></div></section>`;
  }
  function renderEconomyContext(){
    const root=$('#economyInspectorContent');if(!root)return;
    const market=state.market;
    root.innerHTML=market?`<section class="inspector-section"><h3>資金</h3><div class="kv-grid"><dt>総残高</dt><dd>$${fmt(market.funds_total_musd,2)}M</dd><dt>利用可能</dt><dd>$${fmt(market.funds_available_musd,2)}M</dd><dt>市場接続</dt><dd>${(market.interfaces||[]).length}</dd><dt>注文</dt><dd>${(market.orders||[]).length}</dd></div></section><section class="inspector-section"><h3>意味</h3><div class="section-context-note">資金は外部資源市場の決済専用です。建設・研究・輸送等の一般活動コストとしては使用しません。</div></section>`:'<div class="empty-state">市場状態を読み込み中です。</div>';
  }
  const operationsSections=new Set(['location','research','exploration']);
  function saveSectionContext(section=state.activeSection){
    if(!operationsSections.has(section))return;
    state.sectionContexts[section]={
      activeTab:state.activeTab,
      inspector:state.inspector?{...state.inspector}:null,
      decisionContext:state.decisionContext?{...state.decisionContext}:null,
    };
  }
  function defaultTabForSection(section){
    if(section==='research')return 'research';
    if(section==='exploration')return 'scientific-exploration';
    return 'overview';
  }
  function restoreSectionContext(section){
    const saved=state.sectionContexts[section];
    state.activeTab=saved?.activeTab||defaultTabForSection(section);
    state.inspector=saved?.inspector?{...saved.inspector}:null;
    state.decisionContext=saved?.decisionContext?{...saved.decisionContext}:null;
  }
  function renderInspectorWidth(){
    $$('.view-root').forEach((root)=>root.classList.toggle('is-inspector-expanded',state.inspectorExpanded));
    $$('[data-toggle-inspector]').forEach((button)=>{
      button.textContent=state.inspectorExpanded?'標準':'拡大';
      button.setAttribute('aria-pressed',state.inspectorExpanded?'true':'false');
      button.setAttribute('aria-label',state.inspectorExpanded?'詳細パネルを標準幅に戻す':'詳細パネルを拡大');
    });
  }

  function renderSectionChrome(){
    renderInspectorWidth();
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
    restoreActiveDraftValues(); renderActiveDraftBar();
  }

  function clearLocationSnapshot(){
    state.operationalNode=null; state.flow=null; state.dependencyAnalyticsCurrent=null; state.dependencyAnalyticsForecast=null; state.bottlenecks=null; state.projects=null;
    state.buildOptions=null; state.surveys=null; state.surfaceMap=null; state.inspector=null;state.decisionContext=null;
    if(state.sectionContexts.location)state.sectionContexts.location={...state.sectionContexts.location,inspector:null,decisionContext:null};
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
      if(locationSummary?.body_id&&['surface','survey'].includes(state.activeTab))params.set('surface_body_id',locationSummary.body_id);
      const suffix=params.size?`?${params.toString()}`:'';
      const snapshotPath=`/api/v1/ui-state${suffix}`;
      const data=await api(snapshotPath,{viewTokenKey:snapshotPath});
      if(data?.unchanged===true){setConnection('ok','PC Server');return data;}
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
    const previous=state.activeSection;
    saveSectionContext(previous);
    state.activeSection=section;
    state.activeView=['logistics','economy'].includes(section)?'logistics':section==='global'?'global':'operations';
    if(operationsSections.has(section))restoreSectionContext(section);
    else{state.inspector=null;state.decisionContext=null;}
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
    if(['surface','survey'].includes(state.activeTab))await loadUiSnapshot({preserveInteraction:false});
    if(target.subject_kind==='facility'&&target.subject_id)state.inspector={type:'facility',id:target.subject_id};
    else if(target.subject_kind==='project'&&target.subject_id)state.inspector={type:'project',id:target.subject_id};
    else if(target.subject_kind==='research'&&target.subject_id)state.inspector={type:'research',id:target.subject_id};
    else if(target.subject_kind==='scientific_exploration'&&target.subject_id)state.inspector={type:'scientific-exploration',id:target.subject_id};
    else if(target.subject_kind==='survey_campaign'&&target.subject_id)state.inspector={type:'survey-campaign',id:target.subject_id};
    else if(target.subject_kind==='inventory'&&target.resource_id)state.inspector={type:'resource',id:target.resource_id};
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
    state,$,$$,esc,fmt,pct,byId,definitionName,locationName,resourceName,capabilityName,serviceName,operationName,
    locationKindLabels,stateLabels,playerTerms,playerTerm,userFacingText,constraintSummary,issueHtml,metricHtml,statHtml,signed,stableUiSignature,prioritySegmentedHtml,
    api,command,banner,setConnection,loadUiSnapshot,loadLocation,setActiveSection,setActiveView,openDecisionContext,completeActiveDraft,restoreActiveDraftValues,
  };

  document.addEventListener('click',async(event)=>{
    if(event.target.closest('#activeDraftReturn')){try{await returnToActiveDraft();}catch(e){banner(e.message,'error');}return;}
    if(event.target.closest('#activeDraftDiscard')){await discardActiveDraft();banner('Draftを破棄しました');return;}
    const priorityChoice=event.target.closest('[data-priority-choice]');if(priorityChoice){const group=priorityChoice.closest('.priority-segment');const holder=group?.querySelector('[data-priority-value-holder]');if(holder){holder.value=priorityChoice.dataset.priorityChoice;syncPrioritySegment(holder);holder.dispatchEvent(new Event('change',{bubbles:true}));}return;}
    const inspectorToggle=event.target.closest('[data-toggle-inspector]');if(inspectorToggle){state.inspectorExpanded=!state.inspectorExpanded;renderInspectorWidth();return;}
    const sectionBtn=event.target.closest('[data-section]'); if(sectionBtn){setActiveSection(sectionBtn.dataset.section);return;}
    const openLocation=event.target.closest('[data-open-location]'); if(openLocation){await loadLocation(openLocation.dataset.openLocation);setActiveSection('location');return;}
    const globalNode=event.target.closest('[data-global-node-id]'); if(globalNode){state.selectedGlobalNodeId=globalNode.dataset.globalNodeId;renderGlobalView();return;}
    const globalLogistics=event.target.closest('[data-open-node-logistics]'); if(globalLogistics){state.selectedGlobalNodeId=globalLogistics.dataset.openNodeLogistics;setActiveSection('logistics');return;}
    const issueLink=event.target.closest('[data-issue-area]'); if(issueLink){await openDecisionContext({decision_area:issueLink.dataset.issueArea,operational_node_id:issueLink.dataset.issueNode||null,subject_kind:issueLink.dataset.issueSubjectKind||null,subject_id:issueLink.dataset.issueSubjectId||null,resource_id:issueLink.dataset.issueResourceId||null});return;}
    if(event.target.closest('#attentionButton')){setActiveSection('global');return;}
    const locBtn=event.target.closest('[data-location-id]'); if(locBtn){await loadLocation(locBtn.dataset.locationId);return;}
    if(event.target.closest('#timePauseButton')){try{await setTimeControl({paused:!Boolean(state.session?.time_paused)});}catch(e){banner(e.message,'error');}return;}
    const speed=event.target.closest('[data-time-speed]'); if(speed){try{await setTimeControl({speed_multiplier:Number(speed.dataset.timeSpeed)});}catch(e){banner(e.message,'error');}return;}
    if(event.target.closest('#refreshButton')){try{await loadUiSnapshot();banner('最新状態を取得しました');}catch(e){banner(e.message,'error');}return;}
  });
  document.addEventListener('input',(event)=>{const control=event.target.closest?.('[data-structured-draft][data-draft-key]');if(control)trackStructuredDraft(control);});
  document.addEventListener('change',(event)=>{const control=event.target.closest?.('[data-structured-draft][data-draft-key]');if(control)trackStructuredDraft(control);});
  window.addEventListener('online',()=>setConnection('ok','PC Server'));
  window.addEventListener('offline',()=>setConnection('error','オフライン'));
  window.setInterval(()=>{if(document.hidden||state.busy||$('#app')?.getAttribute('aria-busy')!=='false')return;loadUiSnapshot().catch((err)=>{setConnection('error','同期失敗');console.error(err);});},1000);
  document.addEventListener('DOMContentLoaded',()=>{
    $('#saveButton').addEventListener('click',async()=>{await beginMutation();try{await api('/api/v1/session/save',{method:'POST',body:JSON.stringify({slot:'manual'})});banner('manual スロットへ保存しました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
    $('#loadButton').addEventListener('click',async()=>{await beginMutation();try{await api('/api/v1/session/load',{method:'POST',body:JSON.stringify({slot:'manual',apply_offline:true})});state.activeDraft=null;await loadUiSnapshot({preserveInteraction:false});banner('manual スロットを読み込みました');}catch(e){banner(e.message,'error');}finally{endMutation();}});
    initialLoad().catch((err)=>{setConnection('error','接続失敗');banner(`Serverへ接続できません: ${err.message}`,'error',0);$('#app').setAttribute('aria-busy','false');});
  });
})();
