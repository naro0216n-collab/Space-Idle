(() => {
  'use strict';

  const state = {
    revision:null, session:null, world:null, catalog:null, locationId:null, location:null,
    flow:null, globalIssues:null, bottlenecks:null, projects:null, buildOptions:null,
    research:null, scientificExplorations:null, surveys:null, surfaceMap:null, contracts:null, logisticsSummary:null, logistics:null, routes:null,
    fleet:null, transportAllocations:null, cargoFlows:null, lanes:null, demands:[],
    selectedRouteId:null, activeView:'operations', activeTab:'overview', inspector:null,
    busy:false, syncInFlight:null,
  };

  const $ = (sel, root=document) => root.querySelector(sel);
  const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]));
  const fmt = (v, digits=1) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('ja-JP',{maximumFractionDigits:digits}) : '—';
  const pct = (v) => Number.isFinite(Number(v)) ? `${Math.round(Number(v)*100)}%` : '—';
  const byId = (items=[]) => Object.fromEntries(items.map((x)=>[x.id,x]));
  const resourceMap = () => byId(state.catalog?.resources || []);
  const locationMap = () => byId(state.world?.locations || []);
  const definitionMaps = () => [
    state.catalog?.resources, state.catalog?.facilities, state.catalog?.vehicles,
    state.catalog?.locations, state.catalog?.processes, state.catalog?.research,
    state.catalog?.routes, state.catalog?.transport_services,
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
  const storageClassLabels={bulk:'バルク',cryogenic:'極低温',general_cargo:'一般貨物',liquid:'液体'};
  const stateLabels={
    available:'利用可能',active:'稼働',paused:'停止',locked:'未解禁',complete:'完了',
    offered:'提示中',accepted:'受諾済み',declined:'辞退',failed:'失敗',waiting:'待機',
    in_transit:'輸送中',arrival_waiting:'到着待機',prototype:'試作',demonstration:'実証',
    planned:'計画',procuring:'調達中',ready:'施工待ち',building:'施工中',cancelled:'取消済み',
    awaiting_inputs:'資材待ち',awaiting_vehicle:'Vehicle待ち',exploration:'科学探査中',
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
  const interactionValue=(control)=>({value:control.value,baseline:controlBaseline(control)});
  const restoreDraftValue=(control,snapshot)=>{
    if(!control||!snapshot)return;
    const baseline=controlBaseline(control);
    if(baseline===snapshot.baseline||baseline===snapshot.value)control.value=snapshot.value;
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
    state.routes=data.routes; state.fleet=data.fleet; state.transportAllocations=data.transport_allocations; state.cargoFlows=data.cargo_flows;
    state.lanes=data.lanes??state.lanes; state.demands=state.lanes?.demands||[];
    if(data.location!==undefined)state.location=data.location;
    if(data.flow!==undefined)state.flow=data.flow;
    if(data.projects!==undefined)state.projects=data.projects;
    if(data.build_options!==undefined)state.buildOptions=data.build_options;
    if(data.bottlenecks!==undefined)state.bottlenecks=data.bottlenecks;
    if(data.surveys!==undefined)state.surveys=data.surveys;
    if(data.surface_map!==undefined)state.surfaceMap=data.surface_map;
    if(state.selectedRouteId&&!(state.routes?.items||[]).some((r)=>r.id===state.selectedRouteId))state.selectedRouteId=null;
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
    $('#fundsValue').textContent=`${fmt(state.world?.funds_musd,1)} M$`;
    $('#revisionValue').textContent=state.revision??state.session?.revision??'—';
    $('#appVersion').textContent=`v${state.session?.app_version||'0.4.5'}`;
    const paused=Boolean(state.session?.time_paused),speed=Number(state.session?.time_speed_multiplier||1),pause=$('#timePauseButton');
    pause.textContent=paused?'▶ 再開':'⏸ 一時停止'; pause.setAttribute('aria-label',paused?'再開':'一時停止'); pause.setAttribute('aria-pressed',paused?'true':'false');
    $$('[data-time-speed]').forEach((button)=>{const selected=Number(button.dataset.timeSpeed)===speed;button.setAttribute('aria-pressed',selected?'true':'false');button.disabled=selected;});
    const timeState=$('#timeState'); if(timeState)timeState.textContent=state.session?.automatic_progress_enabled===false?'自動進行無効':paused?`停止中 · ${speed}×`:`自動進行 · ${speed}×`;
  }
  function renderLocations(){
    $('#locationList').innerHTML=(state.world?.locations||[]).map((loc)=>`<button type="button" class="location-button ${loc.id===state.locationId?'is-active':''}" data-location-id="${esc(loc.id)}"><span class="location-name">${esc(loc.display_name)}</span><span class="location-meta"><span>${esc(locationKindLabels[loc.kind]||loc.kind)}</span><span>設備 ${loc.facility_count}</span><span>建設 ${loc.active_project_count}</span></span></button>`).join('');
  }
  function renderGlobalIssues(){
    const issues=state.globalIssues?.items||[];
    $('#globalIssues').innerHTML=issues.length?issues.slice(0,8).map(issueHtml).join('')+(issues.length>8?`<div class="cell-sub">ほか ${issues.length-8} 件</div>`:''):'<div class="empty-state">現在、全体blockerはありません。</div>';
  }
  function renderAll(){
    renderHeader(); renderLocations(); renderGlobalIssues();
    if(state.activeView==='operations')window.SpaceIdleOperations?.render();
    else window.SpaceIdleLogistics?.render();
  }

  function clearLocationSnapshot(){
    state.location=null; state.flow=null; state.bottlenecks=null; state.projects=null;
    state.buildOptions=null; state.surveys=null; state.surfaceMap=null; state.inspector=null;
  }
  async function loadUiSnapshot({preserveInteraction=true}={}){
    while(state.syncInFlight){
      const pending=state.syncInFlight;
      if(pending.locationId===state.locationId)return pending.promise;
      try{await pending.promise;}catch{}
      if(state.syncInFlight===pending)state.syncInFlight=null;
    }
    const locationId=state.locationId;
    const request={locationId,promise:null};
    request.promise=(async()=>{
      const locationSummary=(state.world?.locations||[]).find((row)=>row.id===locationId);
      const params=new URLSearchParams();
      if(locationId)params.set('location_id',locationId);
      if(locationSummary?.body_id&&state.activeTab==='surface')params.set('surface_body_id',locationSummary.body_id);
      const suffix=params.size?`?${params.toString()}`:'';
      const data=await api(`/api/v1/ui-state${suffix}`);
      if(locationId!==state.locationId)return data;
      applyUiSnapshot(data);
      if(!state.locationId||!(state.world?.locations||[]).some((x)=>x.id===state.locationId)){
        state.locationId=state.world?.locations?.[0]?.id??null;
        if(state.locationId&&data.location===undefined){const nested=await api(`/api/v1/ui-state?location_id=${encodeURIComponent(state.locationId)}`);applyUiSnapshot(nested);}
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
    if(!locationId||locationId===state.locationId)return;
    state.locationId=locationId;
    clearLocationSnapshot();
    renderAll();
    await loadUiSnapshot({preserveInteraction:false});
  }
  function setActiveView(view){
    state.activeView=view;
    $$('.view-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.view===view));
    $('#operationsView').hidden=view!=='operations'; $('#logisticsView').hidden=view!=='logistics'; renderAll();
  }

  async function initialLoad(){
    setConnection('pending','接続中');
    const [catalog,world]=await Promise.all([api('/api/v1/catalog'),api('/api/v1/world')]);
    state.catalog=catalog; state.world=world; state.locationId=world.locations?.[0]?.id??null;
    await loadUiSnapshot({preserveInteraction:false}); $('#app').setAttribute('aria-busy','false');
  }

  window.SpaceIdleApp={
    state,$,$$,esc,fmt,pct,byId,definitionName,locationName,resourceName,capabilityName,operationName,
    locationKindLabels,storageClassLabels,stateLabels,userFacingText,issueHtml,metricHtml,statHtml,signed,
    api,command,banner,setConnection,loadUiSnapshot,loadLocation,setActiveView,
  };

  document.addEventListener('click',async(event)=>{
    const viewBtn=event.target.closest('[data-view]'); if(viewBtn){setActiveView(viewBtn.dataset.view);return;}
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
