(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before operations_ui.js');
  const {state,$,$$,esc,fmt,pct,resourceName,locationName,definitionName,capabilityName,stateLabels,issueHtml,statHtml,signed,api,command,banner}=A;

  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const setInspector=(title,html)=>{$('#inspectorTitle').textContent=title;$('#inspectorContent').innerHTML=html;};
  const resourceCards=(resources)=>(resources||[]).map((r)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(r.resource_id))}</span><span>${fmt(r.required_t)} t</span></div></div>`).join('')||'<div class="empty-state">追加資源なし</div>';
  const procurementPolicyLabels={immediate:'即時外部調達',standard_wait:'標準待機後に外部調達',extended_wait:'現地在庫を長く待つ'};
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  const knowledgeGoalLabels={1:'存在確認',2:'埋蔵量推定',3:'精密測定'};
  const knowledgeGoalName=(value)=>knowledgeGoalLabels[Number(value)]||`Knowledge ${fmt(value,0)}`;
  const priorityOptions=(selected=3)=>[1,2,3,4,5].map((level)=>`<option value="${level}" ${Number(selected)===level?'selected':''}>${level} ${priorityLabels[level]}</option>`).join('');
  const priorityName=(value)=>priorityLabels[Number(value)]?`${value} ${priorityLabels[Number(value)]}`:String(value??'—');
  const procurementPolicyName=(value)=>procurementPolicyLabels[value]||value||'—';
  const limitingHtml=(rows)=>(rows||[]).length?`<div class="issue-stack">${rows.map((factor)=>`<div class="issue"><div class="issue-title">${esc(A.userFacingText(factor))}</div></div>`).join('')}</div>`:'<span class="badge ok">なし</span>';
  let dependencyView='current';
  const surveyIntentPreviewSerial=new Map();
  const surveyIntentPreviewCache=new Map();
  function surveyIntentDraft(campaignId=null){
    const editing=campaignId!=null;
    return {
      campaign_id:campaignId,
      target_cell_ids:$$(editing?'[data-survey-campaign-cell]:checked':'[data-survey-draft-cell]:checked').map((x)=>x.value),
      resource_ids:$$(editing?'[data-survey-campaign-resource]:checked':'[data-survey-draft-resource]:checked').map((x)=>x.value),
      goal_knowledge_level:Number($(editing?'#surveyCampaignGoal':'#surveyDraftGoal')?.value??1),
    };
  }
  function surveyIntentSignature(intent){
    return JSON.stringify([
      state.revision??0,
      intent.campaign_id,
      [...intent.target_cell_ids].sort(),
      [...intent.resource_ids].sort(),
      intent.goal_knowledge_level,
    ]);
  }
  function applySurveyIntentPreview(intent,result){
    const editing=intent.campaign_id!=null;
    const button=editing
      ? $(`[data-update-survey-campaign="${CSS.escape(intent.campaign_id)}"]`)
      : $('[data-start-survey-campaign]');
    const status=$(editing?'[data-survey-update-intent-status]':'[data-survey-start-intent-status]');
    if(!button||!status)return;
    button.disabled=!result.can_apply;
    status.innerHTML=result.can_apply
      ? '<span class="badge ok">適用可能</span>'
      : `<div class="issue-stack">${(result.blockers||[]).map((blocker)=>issueHtml(['survey',blocker])).join('')}</div>`;
  }
  async function refreshSurveyIntentPreview(campaignId=null){
    const editing=campaignId!=null;
    const previewKey=campaignId??'new';
    const button=editing
      ? $(`[data-update-survey-campaign="${CSS.escape(campaignId)}"]`)
      : $('[data-start-survey-campaign]');
    const status=$(editing?'[data-survey-update-intent-status]':'[data-survey-start-intent-status]');
    if(!button||!status)return;
    const intent=surveyIntentDraft(campaignId);
    const signature=surveyIntentSignature(intent);
    const cached=surveyIntentPreviewCache.get(signature);
    if(cached){applySurveyIntentPreview(intent,cached);return;}
    button.disabled=true;
    status.innerHTML='<span class="badge">可否確認中</span>';
    const serial=(surveyIntentPreviewSerial.get(previewKey)||0)+1;
    surveyIntentPreviewSerial.set(previewKey,serial);
    const params=new URLSearchParams();
    intent.target_cell_ids.forEach((value)=>params.append('target_cell_id',value));
    intent.resource_ids.forEach((value)=>params.append('resource_id',value));
    params.set('goal_knowledge_level',String(intent.goal_knowledge_level));
    if(campaignId!=null)params.set('campaign_id',campaignId);
    try{
      const result=await api(`/api/v1/survey-campaign-intent-preview?${params.toString()}`);
      surveyIntentPreviewCache.set(signature,result);
      if(serial!==surveyIntentPreviewSerial.get(previewKey)||surveyIntentSignature(surveyIntentDraft(campaignId))!==signature)return;
      applySurveyIntentPreview(intent,result);
    }catch(err){
      if(serial!==surveyIntentPreviewSerial.get(previewKey))return;
      status.innerHTML=`<div class="issue"><div class="issue-title">${esc(err.message||'可否を取得できません')}</div></div>`;
    }
  }
  function refreshVisibleSurveyIntentPreview(){
    if($('[data-start-survey-campaign]'))void refreshSurveyIntentPreview();
    const update=$('[data-update-survey-campaign]');
    if(update)void refreshSurveyIntentPreview(update.dataset.updateSurveyCampaign);
  }
  const siteRequirementsHtml=(requirements)=>{
    const spatial=(requirements?.spatial_classifications||[]).map((row)=>`<div class="cell-sub">空間条件: ${esc(row.description||row.code)}</div>`).join('');
    const env=(requirements?.environment||[]).map((row)=>`<div class="cell-sub">物理環境: ${esc(row.description||row.code)}</div>`).join('');
    const caps=(requirements?.capabilities||[]).map((row)=>`<div class="cell-sub">${row.required_state==='ACTIVE'?'稼働':'設置'}Capability: ${esc(capabilityName(row.capability_id))}</div>`).join('');
    return spatial+env+caps||'<div class="cell-sub">追加条件なし</div>';
  };
  function constructionPlanControls(prefix,{draftScope=prefix,policyOptions=[],selectedPolicy='standard_wait',disabled=false}={}){
    const policyRows=(policyOptions||[]).map((value)=>`<option value="${esc(value)}" ${value===selectedPolicy?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const disabledAttr=disabled?'disabled':'';
    return `<div class="form-row"><label>優先度<select id="${prefix}PriorityInput" data-draft-key="${esc(draftScope)}:priority" ${disabledAttr}>${priorityOptions(3)}</select></label><label>調達方針<select id="${prefix}ProcurementTimingPolicy" data-draft-key="${esc(draftScope)}:procurement" ${disabledAttr}>${policyRows}</select></label></div>`;
  }

  const projectTargetLabel=(p)=>{
    if(p.target_kind==='facility_upgrade')return `設備更新 → Lv ${fmt(p.target_level,0)}`;
    if(p.target_kind==='operational_node_founding')return '新拠点設立';
    if(p.target_kind==='surface_cell_development')return '地表区域開発';
    return '新規設備建設';
  };
  const surfaceCell=(id)=>(state.surfaceMap?.cells||[]).find((row)=>row.id===id);
  const surfaceCellLabel=(id)=>{
    const cell=surfaceCell(id);
    if(!cell)return id||'—';
    const name=cell.display_name||'名称未設定地域';
    if(cell.is_location_core&&cell.location_id)return `${locationName(cell.location_id)} 中心 · ${name}`;
    return cell.location_id?`${locationName(cell.location_id)} · ${name}`:name;
  };
  const environmentValue=(value)=>{
    if(value==null)return '—';
    if(typeof value==='number')return fmt(value,3);
    if(Array.isArray(value))return value.map((item)=>Array.isArray(item)?`${item[0]} ${fmt(item[1],3)}`:String(item)).join(', ');
    if(typeof value==='object')return Object.entries(value).map(([key,item])=>`${key} ${typeof item==='number'?fmt(item,3):String(item)}`).join(', ');
    return String(value);
  };
  const environmentHtml=(rows)=>(rows||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(row.key)}</span></div>${(row.values||[]).map(([key,value])=>`<div class="cell-sub">${esc(key)}: ${esc(environmentValue(value))}</div>`).join('')}</div>`).join('')||'<div class="empty-state">Environment情報なし</div>';
  const surfaceResourcesHtml=(rows,cellId=null)=>(rows||[]).map((row)=>{
    const surveyId=cellId==null?null:`${cellId}::${row.resource_id}`;
    const survey=(state.surveys?.items||[]).find((item)=>`${item.cell_id}::${item.resource_id}`===surveyId);
    const action=survey?`<div class="action-row" style="margin-top:8px"><button type="button" data-inspect="survey" data-id="${esc(surveyId)}">Survey詳細・操作</button></div>`:'';
    return `<div class="detail-card"><div class="mode-title"><span>${esc(row.resource_name||resourceName(row.resource_id))}</span><span>Knowledge Lv ${row.knowledge_level}</span></div><div class="cell-sub">存在確率 ${row.presence_probability==null?'—':pct(row.presence_probability)} · Potential ${row.visible_potential==null?'未確定':fmt(row.visible_potential,3)}${row.visible_potential_precision_fraction==null?'':row.visible_potential_precision_fraction<=0?' · 測定済み':` · ±${pct(row.visible_potential_precision_fraction)}`}</div>${action}</div>`;
  }).join('')||'<div class="empty-state">公開済み資源情報なし</div>';
  const tupleResourcesHtml=(rows)=>(rows||[]).map(([resourceId,amount])=>`<div class="cell-sub">${esc(resourceName(resourceId))}: ${fmt(amount,2)} t</div>`).join('')||'<div class="cell-sub">追加資源なし</div>';
  function surfacePlanControls(scope,option,disabled=false){
    const policy=(option.procurement_policy_options||[]).map((value)=>`<option value="${esc(value)}" ${value==='standard_wait'?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const d=disabled?'disabled':'';
    return `<div class="form-row surface-plan-controls"><label>優先度<select data-surface-plan-priority data-draft-key="${esc(scope)}:priority" ${d}>${priorityOptions(3)}</select></label><label>調達方針<select data-surface-plan-policy data-draft-key="${esc(scope)}:procurement" ${d}>${policy}</select></label></div>`;
  }
  const surfacePlanPayload=(button)=>{
    const card=button.closest('.surface-action-card');
    return {
      priority:Number(card?.querySelector('[data-surface-plan-priority]')?.value??3),
      procurement_policy:card?.querySelector('[data-surface-plan-policy]')?.value||'standard_wait',
    };
  };
  const foundingPlanControls=(scope,option,disabled=false)=>{
    const d=disabled?'disabled':'';
    return `<div class="form-row"><label>優先度<select data-founding-priority data-draft-key="${esc(scope)}:priority" ${d}>${priorityOptions(3)}</select></label></div>`;
  };

  function renderOverviewTab(){
    const loc=state.operationalNode,flow=state.flow,issues=state.bottlenecks?.items||[];
    const blockerText=(row)=>A.userFacingText(Array.isArray(row)?(row[1]||row[0]):row);
    const issueResourceIds=new Set(issues.map((issue)=>issue?.resource_id).filter(Boolean));
    const flowRows=(flow?.resources||[]).filter((row)=>
      Math.abs(Number(row.local_production_per_day||0))+Math.abs(Number(row.local_consumption_per_day||0))+
      Math.abs(Number(row.inbound_in_transit_t||0))+Math.abs(Number(row.arrival_waiting_t||0))+Math.abs(Number(row.stock||0))>1e-9
    );
    const resourceSummary=flowRows.map((row)=>{
      const waiting=Number(row.arrival_waiting_t||0);
      const net=Number(row.local_net_per_day||0);
      const warned=issueResourceIds.has(row.resource_id);
      return `<button type="button" class="overview-resource ${warned?'has-warning':''}" data-inspect="resource" data-id="${esc(row.resource_id)}"><span class="overview-resource-name">${esc(row.display_name||resourceName(row.resource_id))}</span><strong>${fmt(row.stock)} ${esc(row.unit||'t')}</strong><span>${net===0?'±0':signed(net)} /日</span><span>入荷中 ${fmt(row.inbound_in_transit_t)} · 到着待ち ${fmt(waiting)}</span></button>`;
    }).join('')||'<div class="empty-state">現在の資源フローはありません。</div>';

    const services=(loc.service_capacities||[]).map((row)=>{
      const limiting=(row.limiting_factors||[]).map(blockerText).join(' / ');
      return `<div class="overview-capacity ${limiting?'has-warning':''}"><div class="overview-capacity-heading"><strong>${esc(capabilityName(row.service_type))}</strong><span>割当 ${fmt(row.allocated,2)} / 要求 ${fmt(row.requested,2)}</span></div><div class="cell-sub">利用可能 ${fmt(row.enabled,2)} · 余力 ${fmt(row.spare,2)}${limiting?` · 制約 ${esc(limiting)}`:''}</div></div>`;
    }).join('')||'<div class="empty-state">サービス能力はありません。</div>';

    const projectRows=(loc.projects||[]).map((project)=>{
      const progress=Number(project.construction_required)>1e-9?Number(project.construction_done||0)/Number(project.construction_required):0;
      const blockers=(project.blockers||[]).map(blockerText);
      return `<button type="button" class="overview-project ${state.inspector?.type==='project'&&state.inspector.id===project.id?'is-selected':''}" data-inspect="project" data-id="${esc(project.id)}"><span class="overview-project-heading"><strong>${esc(project.display_name)}</strong><span class="badge ${blockers.length?'warn':''}">${esc(stateLabels[project.status]||project.status)}</span></span><span class="progress-track"><span class="progress-bar" style="width:${Math.max(0,Math.min(100,progress*100))}%"></span></span><span class="cell-sub">${pct(progress)}${project.projected_material_readiness_day!=null?` · 資材準備見込み Day ${fmt(project.projected_material_readiness_day,0)}`:''}${blockers.length?` · ${esc(blockers[0])}`:''}</span></button>`;
    }).join('')||'<div class="empty-state">進行中案件はありません。</div>';

    const constrainedFacilities=(loc.facilities||[]).filter((facility)=>facility.paused||(facility.operating_blockers||facility.activation_blockers||[]).length);
    const facilityRows=constrainedFacilities.map((facility)=>{
      const blockers=facility.operating_blockers||facility.activation_blockers||[];
      const main=blockers.length?blockerText(blockers[0]):facility.paused?'手動停止':'稼働率低下';
      return `<button type="button" class="overview-facility" data-inspect="facility" data-id="${esc(facility.id)}"><span class="overview-project-heading"><strong>${esc(facility.display_name)}</strong><span class="badge warn">${facility.paused?'停止':pct(facility.operational_utilization)}</span></span><span class="cell-sub">${esc(main)}</span></button>`;
    }).join('')||'<div class="empty-state compact-empty">要確認の設備はありません。</div>';

    const currentAnalytics=state.dependencyAnalyticsCurrent;
    const criticalIds=new Set(currentAnalytics?.critical_dependency_resource_ids||[]);
    const dependencyRows=(currentAnalytics?.current_resources||[]).filter((row)=>criticalIds.has(row.id)).map((row)=>`<button type="button" class="overview-dependency" data-inspect="resource" data-id="${esc(row.id)}"><strong>${esc(row.display_name)}</strong><span>外部依存 ${fmt(row.external_dependency_per_day,2)} /日</span><span>未充足 ${fmt(row.unmet_demand_t,2)} t</span></button>`).join('')||'<div class="empty-state compact-empty">重大な外部依存はありません。</div>';

    const infra=loc.surface_infrastructure;
    const infraCard=infra?`<section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">地表</span><h3>地表インフラ</h3></div><span class="badge ${infra.fulfillment<0.999999?'warn':'ok'}">${pct(infra.fulfillment)}</span></div><div class="capacity-quad"><div><span>基準能力</span><strong>${fmt(infra.nominal_capacity,2)}</strong></div><div><span>利用可能</span><strong>${fmt(infra.available_capacity,2)}</strong></div><div><span>需要</span><strong>${fmt(infra.requested_capacity,2)}</strong></div><div><span>余力</span><strong>${fmt(infra.spare_capacity,2)}</strong></div></div>${(infra.limiting_factors||[]).length?`<div class="issue-stack compact-issues">${infra.limiting_factors.map((factor)=>`<div class="issue"><div class="issue-title">${esc(blockerText(factor))}</div></div>`).join('')}</div>`:''}</section>`:'';

    return `<div class="location-overview-board">
      <section class="decision-card attention-decision-card"><div class="decision-card-heading"><div><span class="eyebrow">判断</span><h3>現在の判断</h3></div><span class="badge ${issues.length?'warn':'ok'}">${issues.length} 件</span></div><div class="issue-stack overview-issues">${issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state compact-empty">現在、この拠点で判断を必要とするblockerはありません。</div>'}</div></section>
      <section class="decision-card resource-decision-card"><div class="decision-card-heading"><div><span class="eyebrow">資源</span><h3>在庫とフロー</h3></div><button type="button" class="small-action" data-tab="inventory">詳細</button></div><div class="overview-resource-grid">${resourceSummary}</div></section>
      <section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">サービス</span><h3>サービス能力</h3></div></div><div class="overview-capacity-list">${services}</div></section>
      <section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">案件</span><h3>進行中案件</h3></div><button type="button" class="small-action" data-tab="construction">建設へ</button></div><div class="overview-project-list">${projectRows}</div></section>
      <section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">設備</span><h3>要確認の設備</h3></div><button type="button" class="small-action" data-tab="facilities">設備へ</button></div><div class="overview-project-list">${facilityRows}</div></section>
      <section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">依存</span><h3>外部依存</h3></div><button type="button" class="small-action" data-tab="inventory">分析</button></div><div class="overview-dependency-list">${dependencyRows}</div></section>
      ${infraCard}
    </div>`;
  }

  function renderFacilitiesTab(){
    const industryByFacility=Object.fromEntries((state.operationalNode?.industry||[]).map((row)=>[row.facility_id,row]));
    const extractionByFacility=Object.fromEntries((state.operationalNode?.extraction||[]).map((row)=>[row.facility_id,row]));
    const blockerText=(row)=>A.userFacingText(Array.isArray(row)?(row[1]||row[0]):row);
    const cards=(state.operationalNode?.facilities||[]).map((facility)=>{
      const industry=industryByFacility[facility.id],extraction=extractionByFacility[facility.id];
      const primary=industry?.process_display_name||industry?.process_id||(extraction?`${resourceName(extraction.resource_id)}採掘`:(facility.capabilities||[]).map(capabilityName)[0])||'運用設備';
      const blockers=facility.operating_blockers||facility.activation_blockers||[];
      const mainBlocker=blockers.length?blockerText(blockers[0]):'';
      const utilization=Math.max(0,Math.min(1,Number(facility.operational_utilization||0)));
      const selected=state.inspector?.type==='facility'&&state.inspector.id===facility.id;
      return `<button type="button" class="facility-card ${selected?'is-selected':''}" data-inspect="facility" data-id="${esc(facility.id)}" aria-pressed="${selected?'true':'false'}"><span class="facility-card-heading"><span><strong>${esc(facility.display_name)}</strong><small>Lv ${fmt(facility.level,0)} · ${esc(primary)}</small></span><span class="badge ${facility.paused||blockers.length?'warn':'ok'}">${facility.paused?'停止':'稼働'}</span></span><span class="facility-utilization"><span><span>実効稼働</span><strong>${pct(utilization)}</strong></span><span class="progress-track"><span class="progress-bar" style="width:${utilization*100}%"></span></span></span><span class="facility-card-metrics"><span>維持 ${pct(facility.maintenance_satisfaction)}</span><span>活動優先 ${esc(priorityName(facility.activity_priority))}</span></span><span class="facility-card-blocker ${mainBlocker?'has-warning':''}">${mainBlocker?`制約: ${esc(mainBlocker)}`:'主要な制約なし'}</span></button>`;
    }).join('');
    return `<section class="facility-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">設備一覧</span><h2>設備</h2><p>稼働率と制約を比較し、対象を選択すると右の詳細パネルで入出力・維持・操作を確認できます。</p></div><span class="badge">${state.operationalNode?.facilities?.length||0} 設備</span></div><div class="facility-card-grid">${cards||'<div class="empty-state">設備なし</div>'}</div></section>`;
  }

  function renderInventoryTab(){
    const flowMap=Object.fromEntries((state.flow?.resources||[]).map((r)=>[r.resource_id,r]));
    const inventoryCards=(state.operationalNode?.inventory||[])
      .filter((r)=>r.amount||r.reserved||flowMap[r.resource_id]?.local_production_per_day||flowMap[r.resource_id]?.local_consumption_per_day||flowMap[r.resource_id]?.inbound_in_transit_t||flowMap[r.resource_id]?.arrival_waiting_t)
      .map((r)=>{
        const f=flowMap[r.resource_id]||{};
        const selected=state.inspector?.type==='resource'&&state.inspector.id===r.resource_id;
        const warnings=[];
        if(Number(r.over_capacity||0)>1e-9)warnings.push(`超過 ${fmt(r.over_capacity,2)} t`);
        if(Number(f.arrival_waiting_t||0)>1e-9)warnings.push(`到着待ち ${fmt(f.arrival_waiting_t,2)} t`);
        return `<button type="button" class="resource-flow-card ${selected?'is-selected':''}" data-inspect="resource" data-id="${esc(r.resource_id)}" aria-pressed="${selected?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(r.display_name)}</strong><small>予約 ${fmt(r.reserved,2)} t</small></span>${warnings.length?`<span class="badge warn">要確認</span>`:'<span class="badge ok">通常</span>'}</span><span class="resource-stock-line"><span><small>在庫</small><strong>${fmt(r.amount,2)} t</strong></span><span><small>利用可能</small><strong>${fmt(r.available,2)} t</strong></span><span><small>空容量</small><strong>${fmt(r.admission_capacity,2)} t</strong></span></span><span class="resource-flow-line"><span>生産 <strong>${fmt(f.local_production_per_day,2)}</strong> /日</span><span>消費 <strong>${fmt(f.local_consumption_per_day,2)}</strong> /日</span><span>純変化 <strong>${signed(f.local_net_per_day)}</strong> /日</span></span><span class="decision-card-footer ${warnings.length?'has-warning':''}">${warnings.length?esc(warnings.join(' · ')):`入荷中 ${fmt(f.inbound_in_transit_t,2)} t · 出荷中 ${fmt(f.outbound_in_transit_t,2)} t`}</span></button>`;
      }).join('');

    const allocations=state.operationalNode?.resource_allocations||[];
    const allocationCards=allocations.map((c)=>`<article class="resource-allocation-card ${Number(c.unmet||0)>1e-9?'has-warning':''}"><div class="decision-card-title"><span><strong>${esc(c.display_name)}</strong><small>${esc(A.userFacingText(c.purpose))} · ${esc(A.userFacingText(c.owner_kind))}</small></span><span class="badge ${Number(c.unmet||0)>1e-9?'warn':'ok'}">優先 ${esc(String(c.priority))}</span></div><div class="allocation-metrics"><span><small>要求</small><strong>${fmt(c.requested,2)}</strong></span><span><small>割当</small><strong>${fmt(c.allocated,2)}</strong></span><span><small>未充足</small><strong>${fmt(c.unmet,2)}</strong></span></div></article>`).join('');

    const currentAnalytics=state.dependencyAnalyticsCurrent;
    const forecastAnalytics=state.dependencyAnalyticsForecast;
    const currentCritical=new Set(currentAnalytics?.critical_dependency_resource_ids||[]);
    const forecastCritical=new Set(forecastAnalytics?.critical_dependency_resource_ids||[]);
    const dependencyCards=(dependencyView==='current'?(currentAnalytics?.current_resources||[]):(forecastAnalytics?.forecast_resources||[])).map((r)=>{
      const isCurrent=dependencyView==='current';
      const critical=(isCurrent?currentCritical:forecastCritical).has(r.id);
      const sources=(r.dependency_source_node_ids||[]).map(locationName).join(' / ')||'依存元なし';
      const limits=(r.limiting_factors||[]).map(A.userFacingText);
      const metrics=isCurrent
        ? `<span><small>生産</small><strong>${fmt(r.production_per_day,2)} /日</strong></span><span><small>消費</small><strong>${fmt(r.consumption_per_day,2)} /日</strong></span><span><small>外部依存</small><strong>${fmt(r.external_dependency_per_day,2)} /日</strong></span><span><small>流入中</small><strong>${fmt(r.imports_pipeline_t,2)} t</strong></span><span><small>未充足</small><strong>${fmt(r.unmet_demand_t,2)} t</strong></span>`
        : `<span><small>計画需要</small><strong>${fmt(r.planned_requirement_t,2)} t</strong></span><span><small>継続消費</small><strong>${fmt(r.recurring_consumption_per_day,2)} /日</strong></span><span><small>外部必要量</small><strong>${fmt(r.external_requirement_t,2)} t</strong></span><span><small>外部依存</small><strong>${fmt(r.external_recurring_dependency_per_day,2)} /日</strong></span><span><small>追加備蓄</small><strong>${fmt(r.target_stock_t,2)} t</strong></span>`;
      const timing=!isCurrent&&r.earliest_requirement_day!=null?`最早必要 Day ${fmt(r.earliest_requirement_day,0)}`:'';
      return `<button type="button" class="dependency-card ${critical?'has-warning':''}" data-inspect="dependency-resource" data-id="${esc(r.id)}"><span class="decision-card-title"><span><strong>${esc(r.display_name)}</strong><small>${esc(sources)}</small></span><span class="badge ${critical?'warn':'ok'}">${critical?'要対処':'安定'}</span></span><span class="dependency-metrics">${metrics}</span><span class="decision-card-footer ${limits.length?'has-warning':''}">${esc(limits[0]||timing||'主要な制約なし')}${timing&&limits.length?` · ${esc(timing)}`:''}</span></button>`;
    }).join('');
    const groupRows=dependencyView==='current'?(currentAnalytics?.current_resource_groups||[]):(forecastAnalytics?.forecast_resource_groups||[]);
    const groupCards=groupRows.map((r)=>dependencyView==='current'
      ? `<div class="dependency-group-card"><strong>${esc(r.display_name)}</strong><span>生産 ${fmt(r.production_per_day,2)} /日</span><span>消費 ${fmt(r.consumption_per_day,2)} /日</span><span>外部依存 ${fmt(r.external_dependency_per_day,2)} /日</span><span>未充足 ${fmt(r.unmet_demand_t,2)} t</span></div>`
      : `<div class="dependency-group-card"><strong>${esc(r.display_name)}</strong><span>計画需要 ${fmt(r.planned_requirement_t,2)} t</span><span>外部必要量 ${fmt(r.external_requirement_t,2)} t</span><span>継続外部依存 ${fmt(r.external_recurring_dependency_per_day,2)} /日</span><span>${r.earliest_requirement_day==null?'必要日未定':`最早 Day ${fmt(r.earliest_requirement_day,0)}`}</span></div>`).join('');

    const criticalCount=dependencyView==='current'?currentCritical.size:forecastCritical.size;
    return `<div class="inventory-decision-surface">
      <section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">資源</span><h2>在庫とフロー</h2><p>現在量・利用可能量・入出荷を比較し、資源を選択すると右の詳細パネルで供給源と制約を確認できます。</p></div><span class="badge">${state.operationalNode?.inventory?.length||0} 資源</span></div><div class="resource-flow-grid">${inventoryCards||'<div class="empty-state">表示対象の資源はありません。</div>'}</div></section>
      <section class="decision-surface-block"><div class="decision-card-heading"><div><span class="eyebrow">配分</span><h3>現在の資源配分</h3></div><span class="badge ${allocations.some((c)=>Number(c.unmet||0)>1e-9)?'warn':'ok'}">${allocations.length} 件</span></div><div class="resource-allocation-grid">${allocationCards||'<div class="empty-state compact-empty">現在の資源配分はありません。</div>'}</div></section>
      <section class="decision-surface-block dependency-surface"><div class="decision-surface-heading"><div><span class="eyebrow">依存分析</span><h2>外部依存</h2><p>現在の不足と、計画済み案件から生じる将来需要を切り替えて確認します。</p></div><div class="segmented-control dependency-mode-switch" role="group" aria-label="外部依存の表示"><button type="button" data-dependency-view="current" class="${dependencyView==='current'?'is-active':''}" aria-pressed="${dependencyView==='current'?'true':'false'}">現在</button><button type="button" data-dependency-view="forecast" class="${dependencyView==='forecast'?'is-active':''}" aria-pressed="${dependencyView==='forecast'?'true':'false'}">予測</button></div></div><div class="dependency-status-row"><span class="badge ${criticalCount?'warn':'ok'}">要対処 ${criticalCount} 資源</span><span class="cell-sub">${dependencyView==='current'?'実際の生産・消費・物流状態':'計画済み需要・備蓄目標・必要時期'}</span></div><div class="dependency-card-grid">${dependencyCards||'<div class="empty-state">外部依存の対象はありません。</div>'}</div>${groupCards?`<details class="dependency-group-details"><summary>資源グループ集計</summary><div class="dependency-group-grid">${groupCards}</div></details>`:''}</section>
    </div>`;
  }

  function planningOptionState(option, readyLabel='計画可'){
    const blockers=option?.blockers||[];
    const canPlan=Boolean(option?.can_plan);
    const label=canPlan
      ? (blockers.length?`計画可 · ${blockers.length} blocker`:readyLabel)
      : (blockers.length?`計画不可 · ${blockers.length} blocker`:'計画不可');
    return {blockers,canPlan,disabled:!canPlan,label};
  }

  function renderConstructionTab(){
    const projects=state.projects?.items||[],options=state.buildOptions?.items||[];
    const projectCards=projects.map((p)=>{
      const selected=state.inspector?.type==='project'&&state.inspector.id===p.id;
      const blockers=p.blockers||[];
      const done=p.progress??p.construction_done??0;
      const required=p.construction_required??0;
      return `<button type="button" class="construction-project-card ${selected?'is-selected':''}" data-inspect="project" data-id="${esc(p.id)}" aria-pressed="${selected?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(p.display_name||p.facility_display_name||'建設案件')}</strong><small>${esc(projectTargetLabel(p))}</small></span><span class="badge ${blockers.length?'warn':p.paused?'':'ok'}">${esc(stateLabels[p.status]||p.status||(p.paused?'停止':'進行中'))}</span></span><span class="construction-progress"><span><small>進捗</small><strong>${fmt(done,1)} / ${fmt(required,1)}</strong></span><span><small>優先度</small><strong>${esc(priorityName(p.priority))}</strong></span><span><small>調達</small><strong>${esc(procurementPolicyName(p.procurement_policy))}</strong></span></span><span class="decision-card-footer ${blockers.length?'has-warning':''}">${blockers.length?`制約: ${esc(A.userFacingText(blockers[0]))}`:'主要な制約なし'}</span></button>`;
    }).join('');
    const optionCards=options.map((o)=>{
      const plan=planningOptionState(o,'建設可');
      const selected=state.inspector?.type==='build-option'&&state.inspector.id===o.facility_definition_id;
      const resources=(o.resources||[]).slice(0,3).map((r)=>`${resourceName(r.resource_id)} ${fmt(r.required_t,1)} t`).join(' · ');
      return `<button type="button" class="construction-option-card ${selected?'is-selected':''}" data-inspect="build-option" data-id="${esc(o.facility_definition_id)}" aria-pressed="${selected?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(o.display_name)}</strong><small>${esc(resources||'追加建設資源なし')}</small></span><span class="badge ${plan.blockers.length?'warn':plan.canPlan?'ok':''}">${esc(plan.canPlan?'計画可能':'条件不足')}</span></span><span class="construction-option-metrics"><span><small>必要工数</small><strong>${fmt(o.construction_required,0)}</strong></span><span><small>必要資源</small><strong>${o.resources?.length||0} 種</strong></span><span><small>状態</small><strong>${esc(plan.label)}</strong></span></span><span class="decision-card-footer ${plan.blockers.length?'has-warning':''}">${plan.blockers.length?`制約: ${esc(A.userFacingText(plan.blockers[0]))}`:'選択して能力・必要資源・配置条件を確認'}</span></button>`;
    }).join('');
    return `<div class="construction-decision-surface">
      <section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">進行中</span><h2>建設案件</h2><p>進捗・優先度・調達・制約を比較し、案件を選択すると右の詳細パネルから設定を変更できます。</p></div><span class="badge">${projects.length} 件</span></div><div class="construction-project-grid">${projectCards||'<div class="empty-state">進行中の建設案件はありません。</div>'}</div></section>
      <section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">候補</span><h2>新規建設</h2><p>候補を選び、何が可能になるか・必要資源・現在の制約を確認してから計画します。</p></div><span class="badge">${options.length} 候補</span></div><div class="construction-option-grid">${optionCards||'<div class="empty-state">現在建設できる候補はありません。</div>'}</div></section>
    </div>`;
  }

  function renderResearchTab(){
    if(!window.SpaceIdleResearchTree)return '<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="empty-state">技術ツリー描画機構を読み込めませんでした。</div></section>';
    return window.SpaceIdleResearchTree.render(state.research||{items:[],providers:[]});
  }
  function renderScientificExplorationTab(){
    const items=state.scientificExplorations?.items||[];
    const cards=items.map((x)=>{
      const blocked=(x.blockers||[]).length;
      const assigned=x.assigned_vehicle_definition_id?`${definitionName(x.assigned_vehicle_definition_id)} · ${fmt(x.committed_units,0)} 機`:'未配備';
      const outbound=x.outbound_latency_days==null?'—':`${fmt(x.outbound_latency_days,0)}日`;
      const returning=x.return_latency_days==null?'—':`${fmt(x.return_latency_days,0)}日`;
      const progressTotal=Math.max(0,Number(x.duration_days||0));
      const progressDone=Math.max(0,Number(x.progress_days||0));
      const ratio=progressTotal>0?Math.min(1,progressDone/progressTotal):(x.status==='complete'?1:0);
      const rpTotal=Math.max(0,Number(x.research_points_total||0));
      const rpDone=Math.max(0,Number(x.research_points_awarded||0));
      return `<button type="button" class="exploration-decision-card ${state.inspector?.type==='scientific-exploration'&&state.inspector.id===x.id?'is-selected':''}" data-inspect="scientific-exploration" data-id="${esc(x.id)}" aria-pressed="${state.inspector?.type==='scientific-exploration'&&state.inspector.id===x.id?'true':'false'}">
        <span class="decision-card-title"><span><strong>${esc(x.display_name)}</strong><small>${esc(locationName(x.origin_id))} → ${esc(locationName(x.destination_id))}</small></span><span class="badge ${blocked?'warn':x.status==='complete'?'ok':''}">${esc(stateLabels[x.status]||x.status)}</span></span>
        <span class="exploration-progress"><span>科学活動 ${fmt(progressDone,1)}/${fmt(progressTotal,1)}日</span><span class="progress-track"><span class="progress-bar" style="width:${ratio*100}%"></span></span></span>
        <span class="decision-card-metrics"><span>獲得RP <strong>${fmt(rpDone,1)}/${fmt(rpTotal,1)}</strong></span><span>当日受入 <strong>${fmt(x.rp_admitted_today,2)}</strong></span><span>優先度 <strong>${esc(priorityName(x.priority??3))}</strong></span></span>
        <span class="decision-card-metrics"><span>Fleet <strong>${esc(assigned)}</strong></span><span>往路 <strong>${esc(outbound)}</strong></span><span>復路 <strong>${esc(returning)}</strong></span></span>
        <span class="decision-card-footer ${blocked?'has-warning':''}">${blocked?`blocker ${blocked}件 · 詳細を確認`:'実行条件に重大なblockerなし'}</span>
      </button>`;
    }).join('');
    return `<div class="exploration-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">科学探査</span><h2>探査Campaign</h2><p>候補を選び、右側で実行条件・Fleet拘束・往復移動・RP受入を確認します。輸送とのFleet競合も同じ判断Contextで扱います。</p></div><span class="badge">${items.length} Campaign</span></div><div class="exploration-card-grid">${cards||'<div class="empty-state">現在利用できる科学探査Campaignはありません。</div>'}</div></div>`;
  }

  function renderSurveyTab(){
    const providerFleet=state.surveys?.provider_fleet||[];
    const knowledge=state.surveys?.items||[];
    const visibleKnowledge=state.surfaceMap?.body_id?knowledge.filter((row)=>row.body_id===state.surfaceMap.body_id):knowledge;
    const cellMap=new Map();visibleKnowledge.forEach((row)=>cellMap.set(row.cell_id,row.cell_label));
    const resourceMap=new Map();visibleKnowledge.forEach((row)=>resourceMap.set(row.resource_id,row.resource_name));
    const cells=(state.surfaceMap?.cells||[]).filter((cell)=>cellMap.has(cell.id));
    const mapCellIds=new Set(cells.map((cell)=>cell.id));
    const fallbackCells=[...cellMap].filter(([id])=>!mapCellIds.has(id));
    const goalLabel=(level)=>({1:'存在確認',2:'埋蔵量推定',3:'精密測定'}[Number(level)]||`Knowledge ${fmt(level,0)}`);

    let scopeMap='';
    if(cells.length){
      const minLon=Math.min(...cells.map((c)=>Number(c.longitude_deg))),maxLon=Math.max(...cells.map((c)=>Number(c.longitude_deg)));
      const minLat=Math.min(...cells.map((c)=>Number(c.latitude_deg))),maxLat=Math.max(...cells.map((c)=>Number(c.latitude_deg)));
      const lonSpan=Math.max(1,maxLon-minLon),latSpan=Math.max(1,maxLat-minLat);
      const pos=Object.fromEntries(cells.map((c)=>[c.id,{x:8+84*(Number(c.longitude_deg)-minLon)/lonSpan,y:8+84*(maxLat-Number(c.latitude_deg))/latSpan}]));
      const seen=new Set(),lines=[];
      for(const cell of cells){for(const neighbor of cell.neighbor_ids||[]){if(!pos[neighbor])continue;const key=[cell.id,neighbor].sort().join('::');if(seen.has(key))continue;seen.add(key);lines.push(`<line x1="${pos[cell.id].x*10}" y1="${pos[cell.id].y*4.2}" x2="${pos[neighbor].x*10}" y2="${pos[neighbor].y*4.2}"></line>`);}}
      const nodes=cells.map((cell)=>`<label class="survey-scope-node" style="left:${pos[cell.id].x}%;top:${pos[cell.id].y}%"><input type="checkbox" data-survey-draft-cell data-draft-key="survey:new:cell:${esc(cell.id)}" value="${esc(cell.id)}"><span><strong>${esc(cellMap.get(cell.id))}</strong><small>${cell.location_id?esc(locationName(cell.location_id)):'未所属'} · ${fmt(cell.area_km2,0)} km²</small></span></label>`).join('');
      scopeMap=`<div class="survey-scope-map"><svg viewBox="0 0 1000 420" preserveAspectRatio="none" aria-hidden="true">${lines.join('')}</svg>${nodes}</div>`;
    }
    const fallbackHtml=fallbackCells.map(([id,label])=>`<label class="survey-resource-choice"><input type="checkbox" data-survey-draft-cell data-draft-key="survey:new:cell:${esc(id)}" value="${esc(id)}"><span>${esc(label)}</span></label>`).join('');
    const resourceChoices=[...resourceMap].map(([id,label])=>`<label class="survey-resource-choice"><input type="checkbox" data-survey-draft-resource data-draft-key="survey:new:resource:${esc(id)}" value="${esc(id)}"><span>${esc(label)}</span></label>`).join('');
    const createSection=`<section class="survey-decision-card"><div class="decision-card-heading"><div><span class="eyebrow">Survey scope</span><h3>調査範囲を地表から選択</h3></div><span class="badge">${cellMap.size} Cell · ${resourceMap.size} 資源</span></div><div class="survey-decision-body"><div class="survey-map-column">${scopeMap||'<div class="empty-state">このContextに地表位置情報はありません。</div>'}${fallbackHtml?`<div class="survey-fallback-cells">${fallbackHtml}</div>`:''}</div><div class="survey-intent-column"><div><h4>対象資源</h4><div class="survey-resource-choices">${resourceChoices||'<div class="empty-state">対象資源なし</div>'}</div></div><div class="form-row survey-goal-row"><label>調査目標<select id="surveyDraftGoal" data-draft-key="survey:new:goal"><option value="1">1 存在確認</option><option value="2">2 埋蔵量推定</option><option value="3">3 精密測定</option></select></label><label>活動優先度<select id="surveyDraftPriority" data-draft-key="survey:new:priority">${priorityOptions(3)}</select></label></div><div data-survey-start-intent-status><span class="badge">可否確認中</span></div><button type="button" class="primary survey-start-button" data-start-survey-campaign disabled>この条件でSurveyを開始</button><div class="cell-sub">Providerと観測ModeはApplicationが解決し、戦略差がある場合だけCampaign詳細で候補差を提示します。</div></div></div></section>`;

    const campaigns=(state.surveys?.campaigns||[]).map((c)=>{
      const provider=c.projected_provider_definition_id?`${definitionName(c.projected_provider_definition_id)} / ${definitionName(c.projected_observation_mode_id)||c.projected_observation_mode_id||'—'}`:'未解決';
      const fleet=c.required_fleet_units==null?'—':`${fmt(c.assigned_fleet_units,0)} / 必要 ${fmt(c.required_fleet_units,0)}`;
      const eta=c.projected_remaining_days==null?'—':`${fmt(c.projected_remaining_days,1)}日`;
      const total=Number(c.covered_targets||0)+Number(c.remaining_targets||0);
      const completion=total>0?Math.min(1,Number(c.covered_targets||0)/total):0;
      const blocked=(c.blockers||[]).length;
      return `<button type="button" class="survey-campaign-card ${state.inspector?.type==='survey-campaign'&&state.inspector.id===c.id?'is-selected':''}" data-inspect="survey-campaign" data-id="${esc(c.id)}" aria-pressed="${state.inspector?.type==='survey-campaign'&&state.inspector.id===c.id?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(goalLabel(c.goal_knowledge_level))}</strong><small>${c.target_cell_ids.length} Cell × ${c.resource_ids.length} Resource</small></span><span class="badge ${blocked?'warn':''}">${esc(stateLabels[c.status]||c.status)}</span></span><span class="exploration-progress"><span>調査済み ${fmt(c.covered_targets,0)}/${fmt(total,0)}</span><span class="progress-track"><span class="progress-bar" style="width:${completion*100}%"></span></span></span><span class="decision-card-metrics"><span>解決手段 <strong>${esc(provider)}</strong></span><span>Fleet <strong>${esc(fleet)}</strong></span></span><span class="decision-card-metrics"><span>調査能力 <strong>${fmt(c.capacity_points_per_day,2)}/日</strong></span><span>予測残り <strong>${esc(eta)}</strong></span><span>優先度 <strong>${esc(priorityName(c.priority??3))}</strong></span></span><span class="decision-card-footer ${blocked?'has-warning':''}">${blocked?`blocker ${blocked}件 · 詳細を確認`:'実行条件に重大なblockerなし'}</span></button>`;
    }).join('');
    const campaignSection=`<section class="card"><div class="card-heading"><div><h3>進行中のSurvey</h3><div class="cell-sub">Campaignを選択すると右側でScope、Provider候補差、Fleet、優先度、blockerを編集できます。</div></div><span class="badge">${(state.surveys?.campaigns||[]).length}</span></div><div class="card-body"><div class="survey-campaign-grid">${campaigns||'<div class="empty-state">進行中Campaignなし</div>'}</div></div></section>`;

    const knowledgeCards=visibleKnowledge.map((s)=>{const potential=s.visible_potential==null?'未確定':fmt(s.visible_potential,3),precision=s.visible_potential_precision_fraction==null?'':s.visible_potential_precision_fraction<=0?'測定済み':`精度 ±${pct(s.visible_potential_precision_fraction)}`;return `<button type="button" class="survey-knowledge-card ${state.inspector?.type==='survey'&&state.inspector.id===`${s.cell_id}::${s.resource_id}`?'is-selected':''}" data-inspect="survey" data-id="${esc(`${s.cell_id}::${s.resource_id}`)}"><span class="decision-card-title"><span><strong>${esc(s.resource_name)}</strong><small>${esc(s.cell_label)}</small></span><span class="badge">Knowledge ${fmt(s.knowledge_level,0)}</span></span><span class="decision-card-metrics"><span>進捗 <strong>${fmt(s.progress,2)}</strong></span><span>存在確率 <strong>${s.presence_probability==null?'—':pct(s.presence_probability)}</strong></span><span>推定量 <strong>${esc(potential)}</strong></span></span><span class="cell-sub">${esc(precision||'追加Surveyで精度向上')}</span></button>`;}).join('');
    const knowledgeSection=`<section class="card"><div class="card-heading"><div><h3>判明済みの地表知識</h3><div class="cell-sub">Campaign lifecycleとは独立した、現在のKnowledge stateです。</div></div><span class="badge">${visibleKnowledge.length}</span></div><div class="card-body"><div class="survey-knowledge-grid">${knowledgeCards||'<div class="empty-state">この天体にSurvey対象なし</div>'}</div></div></section>`;

    const providerCards=providerFleet.map((row)=>`<div class="detail-card" data-survey-provider-fleet-card><div class="mode-title"><span>${esc(definitionName(row.provider_definition_id))}</span><span>配備 ${fmt(row.committed_units,0)} · 空き ${fmt(row.free_units,0)}</span></div><div class="cell-sub">${esc(locationName(row.operational_node_id))} · ${esc(definitionName(row.vehicle_definition_id))} · 調査能力 ${fmt(row.capacity_units_per_day,2)}/日</div>${(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(['survey_provider',b])).join('')}</div>`:''}<div class="form-row"><label>Surveyへ配備する機数<input type="number" min="0" max="${Math.max(0,Number(row.max_units||0))}" step="1" value="${fmt(row.committed_units,0)}" data-survey-provider-fleet-quantity data-draft-key="survey-provider:${esc(row.provider_definition_id)}:${esc(row.operational_node_id)}:quantity" ${row.can_set_quantity?'':'disabled'}></label><button type="button" data-survey-provider-set-fleet="${esc(row.provider_definition_id)}" data-vehicle-definition-id="${esc(row.vehicle_definition_id)}" data-operational-node-id="${esc(row.operational_node_id)}" ${row.can_set_quantity?'':'disabled'}>配備数を適用</button></div></div>`).join('');
    const providerSection=`<section class="card"><div class="card-heading"><div><h3>Survey能力の配備</h3><div class="cell-sub">Campaignの可否や進行が能力不足で制約される場合に調整します。</div></div><span class="badge">${providerFleet.filter((row)=>Number(row.committed_units||0)>0).length}</span></div><div class="card-body"><div class="detail-stack">${providerCards||'<div class="empty-state">Fleetを使うSurvey能力はありません。</div>'}</div></div></section>`;
    return `<div class="survey-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">資源Survey</span><h2>地表調査</h2><p>Cell、対象資源、Knowledge目標を直接選びます。実行手段はApplicationが解決し、差が意思決定に影響する場合だけ比較します。</p></div></div>${createSection}${campaignSection}${knowledgeSection}${providerSection}</div>`;
  }

  function renderSurfaceTab(){
    const map=state.surfaceMap;
    if(!map){
      const summary=(state.world?.operational_nodes||[]).find((row)=>row.id===state.operationalNodeId);
      const message=summary?.body_id?'地表マップを取得しています。':'このSpatial Nodeには表示可能な地表天体がありません。';
      return `<section class="card"><div class="card-heading"><h3>地表マップ</h3></div><div class="empty-state">${message}</div></section>`;
    }
    const cells=map.cells||[];
    if(!cells.length)return `<section class="card"><div class="card-heading"><h3>${esc(map.display_name)} 地表</h3></div><div class="empty-state">Surface Cellが定義されていません。</div></section>`;
    const minLon=Math.min(...cells.map((c)=>Number(c.longitude_deg))),maxLon=Math.max(...cells.map((c)=>Number(c.longitude_deg)));
    const minLat=Math.min(...cells.map((c)=>Number(c.latitude_deg))),maxLat=Math.max(...cells.map((c)=>Number(c.latitude_deg)));
    const lonSpan=Math.max(1,maxLon-minLon),latSpan=Math.max(1,maxLat-minLat);
    const pos=Object.fromEntries(cells.map((c)=>[c.id,{
      x:8+84*(Number(c.longitude_deg)-minLon)/lonSpan,
      y:8+84*(maxLat-Number(c.latitude_deg))/latSpan,
    }]));
    const seen=new Set(),lines=[];
    for(const cell of cells){
      for(const neighbor of cell.neighbor_ids||[]){
        if(!pos[neighbor])continue;
        const key=[cell.id,neighbor].sort().join('::');if(seen.has(key))continue;seen.add(key);
        lines.push(`<line x1="${pos[cell.id].x*10}" y1="${pos[cell.id].y*4.8}" x2="${pos[neighbor].x*10}" y2="${pos[neighbor].y*4.8}"></line>`);
      }
    }
    const buttons=cells.map((cell)=>{
      const classes=['surface-cell-button',cell.developed?'is-developed':'',cell.is_location_core?'is-core':'',state.inspector?.type==='surface-cell'&&state.inspector.id===cell.id?'is-selected':''].filter(Boolean).join(' ');
      const owner=cell.location_id?locationName(cell.location_id):'未所属';
      return `<div class="surface-cell-node" style="left:${pos[cell.id].x}%;top:${pos[cell.id].y}%"><button type="button" class="${classes}" data-inspect="surface-cell" data-id="${esc(cell.id)}"><span class="surface-cell-name">${esc(surfaceCellLabel(cell.id))}</span><span class="surface-cell-meta">${esc(owner)} · ${fmt(cell.area_km2,0)} km²</span></button></div>`;
    }).join('');
    const locations=(map.locations||[]).map((loc)=>`<span class="badge">${esc(loc.display_name)} ${loc.developed_cell_ids?.length||0} Cell</span>`).join(' ');
    return `<div class="surface-layout"><section class="card surface-map-card"><div class="card-heading"><div><h3>${esc(map.display_name)} 地表</h3><div class="cell-sub">Cellを選択してSurvey・開発・位置依存Facility・Location設立を判断します。</div></div><span class="badge">${cells.length} Cell</span></div><div class="surface-map-stage"><svg class="surface-map-links" viewBox="0 0 1000 480" preserveAspectRatio="none" aria-hidden="true">${lines.join('')}</svg><div class="surface-map-nodes">${buttons}</div></div><div class="surface-map-legend"><span><i class="legend-dot core"></i>Location中心</span><span><i class="legend-dot developed"></i>開発済み</span><span><i class="legend-dot undeveloped"></i>未開発</span></div></section><section class="card"><div class="card-heading"><h3>Location Territory</h3></div><div class="card-body">${locations||'<div class="empty-state">Locationなし</div>'}</div></section></div>`;
  }

  function renderActiveTab(){
    const renderers={overview:renderOverviewTab,facilities:renderFacilitiesTab,inventory:renderInventoryTab,construction:renderConstructionTab,research:renderResearchTab,'scientific-exploration':renderScientificExplorationTab,survey:renderSurveyTab,surface:renderSurfaceTab};
    const root=$('#operationsTabContent');
    const html=(renderers[state.activeTab]||renderOverviewTab)();
    // Keep the current interaction surface mounted when the authoritative view is
    // unchanged. Periodic synchronization must not detach a button while the user
    // is clicking it or replace in-progress form controls with identical markup.
    if(root.innerHTML!==html)root.innerHTML=html;
  }

  function renderFacilityInspector(id){
    const f=state.operationalNode?.facilities?.find((x)=>x.id===id);if(!f)return false;
    const blockers=f.operating_blockers||f.activation_blockers||[],u=f.next_upgrade;
    const researchRows=f.research_tier==null?[]:[['Research Tier',fmt(f.research_tier,0)],['RP生成',`${fmt(f.research_generation_points_per_day,2)}/日`],['RP貯蔵',fmt(f.research_storage_capacity_points,1)]];
    const industry=state.operationalNode?.industry?.find((row)=>row.facility_id===id);
    const extraction=state.operationalNode?.extraction?.find((row)=>row.facility_id===id);
    const rateCards=(rows)=>(rows||[]).map(([resourceId,rate])=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(resourceId))}</span><span>${fmt(rate,3)} t/日</span></div></div>`).join('')||'<div class="empty-state">なし</div>';
    let productionSection='';
    if(industry){
      const processOptions=(industry.process_options||[]).map(([processId,name])=>`<option value="${esc(processId)}" ${processId===industry.process_id?'selected':''}>${esc(name||definitionName(processId))}</option>`).join('');
      const processControl=`<div class="form-row"><label>Process<select id="facilityProcessSelect" data-draft-key="facility:${esc(f.id)}:process" ${processOptions?'':'disabled'}>${processOptions||'<option>候補なし</option>'}</select></label><button type="button" data-set-facility-process="${esc(f.id)}" ${processOptions?'':'disabled'}>Processを適用</button></div>`;
      productionSection+=section('生産工程',kv([['現在Process',esc(industry.process_display_name||industry.process_id||'未選択')],['Process選択',industry.selection_required?'選択が必要':'確定'],['実効稼働率',pct(industry.scale)]])+processControl+`<h4>投入/日</h4>${rateCards(industry.input_rates_per_day)}<h4>生産物/日</h4>${rateCards(industry.output_rates_per_day)}<h4>主な制約</h4>${limitingHtml(industry.limiting_factors)}`);
    }
    if(extraction){
      productionSection+=section('採掘',kv([['対象資源',esc(resourceName(extraction.resource_id))],['基準能力',`${fmt(extraction.nominal_capacity_t_per_day,3)} t/日`],['有効採掘機会',fmt(extraction.effective_opportunity,3)],['限界効率',pct(extraction.marginal_efficiency)],['産出資源',esc(resourceName(extraction.output_resource_id))],['生産物/日',`${fmt(extraction.output_t_per_day,3)} t/日`],['実効稼働率',pct(extraction.scale)]])+`<h4>主な制約</h4>${limitingHtml(extraction.limiting_factors)}`);
    }
    if(!productionSection)productionSection=section('生産・採掘','<div class="empty-state">この設備には現在の生産・採掘工程がありません。</div>');
    let upgradeSection='';
    if(u){
      const plan=planningOptionState(u,'Upgrade計画可');
      const planOptions=state.buildOptions||{};
      const planControls=constructionPlanControls('upgradePlan',{draftScope:`facility-upgrade:${f.id}`,policyOptions:planOptions.procurement_policy_options||[],disabled:plan.disabled});
      upgradeSection=section(`次のUpgrade · Lv ${fmt(u.target_level,0)}`,kv([['必要工数',fmt(u.construction_required,0)],['既存案件',u.active_project_id?esc(u.active_project_id):'なし'],['計画可否',esc(plan.label)]])+`<h4>必要資源</h4>${resourceCards(u.resources)}${plan.blockers.length?`<div class="issue-stack">${plan.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">blockerなし</span>'}${planControls}<button type="button" class="primary" data-upgrade="${esc(f.id)}" data-plan-prefix="upgradePlan" ${plan.disabled?'disabled':''}>Lv ${fmt(u.target_level,0)} Upgrade案件を作成</button>`);
    }else upgradeSection=section('次のUpgrade','<div class="empty-state">現在定義されている次LevelのUpgradeはありません。</div>');
    const investment=(f.invested_resources||[]).map(([r,a])=>`<div class="cell-sub">${esc(resourceName(r))}: ${fmt(a)} t</div>`).join('')||'<div class="empty-state">投入履歴なし</div>';
    const maintenance=(f.maintenance_demand_per_day||[]).map(([r,a])=>`<div class="cell-sub">${esc(resourceName(r))}: ${fmt(a,4)} t/日</div>`).join('')||'<div class="empty-state">維持資源要求なし</div>';
    const salvagePotential=(f.expected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし';
    const salvageProjected=(f.projected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし';
    const salvageSection=section('撤去時の回収',kv([['回収可能量',esc(salvagePotential)],['見込回収率',pct(f.projected_salvage_fraction??1)],['見込回収量',esc(salvageProjected)],['既存在庫による制約',esc((f.decommission_blockers||[]).map(([code,detail])=>`${code}: ${detail}`).join(' / ')||'なし')]]));
    setInspector(f.display_name,section('状態',kv([['Level',fmt(f.level,0)],['運転',f.paused?'手動停止':'稼働'],['電力利用率',pct(f.power_utilization)],['維持充足率',pct(f.maintenance_satisfaction)],['実効稼働率',pct(f.operational_utilization)],['活動優先度',esc(priorityName(f.activity_priority))],['維持優先度',esc(priorityName(f.maintenance_priority??3))],...researchRows]))+productionSection+section('建造・Upgrade投入資源',investment)+section('維持資源需要',maintenance)+salvageSection+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<div class="badge ok">なし</div>')+upgradeSection+section('運用操作',`<div class="action-stack"><button type="button" data-command="${f.paused?'ResumeFacility':'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused?'設備を再開':'設備を停止'}</button><div class="form-row"><label>活動優先度<select id="facilityPriorityInput" data-draft-key="facility:${esc(f.id)}:activity-priority">${priorityOptions(f.activity_priority??3)}</select></label><button type="button" data-set-facility-activity-priority="${esc(f.id)}">活動優先度を適用</button></div><div class="form-row"><label>維持優先度<select id="maintenancePriorityInput" data-draft-key="facility:${esc(f.id)}:maintenance-priority">${priorityOptions(f.maintenance_priority??3)}</select></label><button type="button" data-set-maintenance-priority="${esc(f.id)}">維持優先を適用</button></div></div>`));
    return true;
  }
  function renderExtractionResourceInspector(id){
    const row=state.operationalNode?.extraction_resources?.find((item)=>item.resource_id===id);if(!row)return false;
    const infra=state.operationalNode?.surface_infrastructure;
    const infraLimit=infra?.limiting_factors?.includes('surface_infrastructure');
    setInspector(row.resource_name,section('Resource Opportunity / Extraction',kv([['有効採掘機会',fmt(row.effective_opportunity,3)],['Installed Nominal Capacity',`${fmt(row.installed_nominal_capacity_t_per_day,3)} t/日`],['Actual Extraction',`${fmt(row.output_t_per_day,3)} t/日`],['Diminishing efficiency',pct(row.diminishing_efficiency)],['Marginal efficiency',pct(row.marginal_efficiency)],['Operational fulfillment',pct(row.operational_fulfillment)]]))+section('Surface Infrastructure',infra?kv([['Fulfillment',pct(infra.fulfillment)],['Limiting factor',infraLimit?'<span class="badge warn">Surface Infrastructure</span>':'<span class="badge ok">なし</span>']]):'<div class="empty-state">非地表Location</div>'));
    return true;
  }
  function renderResourceInspector(id){
    const inv=state.operationalNode?.inventory?.find((x)=>x.resource_id===id),f=state.flow?.resources?.find((x)=>x.resource_id===id);if(!inv)return false;
    setInspector(inv.display_name,section('在庫',kv([['在庫',fmt(inv.amount)],['予約',fmt(inv.reserved)],['利用可能',fmt(inv.available)],['物理容量',fmt(inv.physical_capacity)],['利用可能容量',fmt(inv.usable_capacity)],['入庫可能量',fmt(inv.admission_capacity)],['容量超過',fmt(inv.over_capacity)],['制限要因',esc((inv.limiting_factors||[]).map(A.userFacingText).join(' / ')||'なし')],['入庫制約',esc((inv.admission_blockers||[]).map(A.userFacingText).join(' / ')||'なし')]]))+section('フロー',kv([['生産/日',signed(f?.local_production_per_day)],['消費/日',signed(f?.local_consumption_per_day)],['純変化/日',signed(f?.local_net_per_day)],['入荷中',fmt(f?.inbound_in_transit_t)],['出荷中',fmt(f?.outbound_in_transit_t)],['到着待機',fmt(f?.arrival_waiting_t)]])));
    return true;
  }
  function renderDependencyResourceInspector(id){
    const current=(state.dependencyAnalyticsCurrent?.current_resources||[]).find((row)=>row.id===id);
    const forecast=(state.dependencyAnalyticsForecast?.forecast_resources||[]).find((row)=>row.id===id);
    if(!current&&!forecast)return false;
    const displayName=current?.display_name||forecast?.display_name||resourceName(id);
    const currentSection=current?section('現在',kv([
      ['生産',`${fmt(current.production_per_day,2)} /日`],
      ['消費',`${fmt(current.consumption_per_day,2)} /日`],
      ['需要',`${fmt(current.demand_per_day,2)} /日`],
      ['外部依存',`${fmt(current.external_dependency_per_day,2)} /日`],
      ['流入',`${fmt(current.imports_per_day,2)} /日`],
      ['流出',`${fmt(current.exports_per_day,2)} /日`],
      ['流入中',`${fmt(current.imports_pipeline_t,2)} t`],
      ['流出中',`${fmt(current.exports_pipeline_t,2)} t`],
      ['未充足',`${fmt(current.unmet_demand_t,2)} t`],
      ['依存元',esc((current.dependency_source_node_ids||[]).map(locationName).join(' / ')||'なし')],
    ])+`<h4>主な制約</h4>${limitingHtml(current.limiting_factors)}`):section('現在','<div class="empty-state">現在の依存状態はありません。</div>');
    const forecastSection=forecast?section('予測',kv([
      ['計画需要',`${fmt(forecast.planned_requirement_t,2)} t`],
      ['継続消費',`${fmt(forecast.recurring_consumption_per_day,2)} /日`],
      ['外部必要量',`${fmt(forecast.external_requirement_t,2)} t`],
      ['継続外部依存',`${fmt(forecast.external_recurring_dependency_per_day,2)} /日`],
      ['追加備蓄目標',`${fmt(forecast.target_stock_t,2)} t`],
      ['最早必要日',forecast.earliest_requirement_day==null?'未定':`Day ${fmt(forecast.earliest_requirement_day,0)}`],
      ['依存元',esc((forecast.dependency_source_node_ids||[]).map(locationName).join(' / ')||'なし')],
    ])+`<h4>主な制約</h4>${limitingHtml(forecast.limiting_factors)}`):section('予測','<div class="empty-state">計画済みの将来依存はありません。</div>');
    setInspector(displayName,currentSection+forecastSection);
    return true;
  }
  function renderProjectInspector(id){
    const p=state.projects?.items?.find((x)=>x.id===id);if(!p)return false;
    const target=projectTargetLabel(p);
    const readiness=p.projected_material_readiness_day==null?'未確定':`Day ${fmt(p.projected_material_readiness_day,0)}`;
    const targetRows=[['種別',esc(target)],['状態',esc(stateLabels[p.status]||p.status||(p.paused?'停止':'進行中'))],['優先度',esc(priorityName(p.priority))],['施工充足',pct(p.construction_fulfillment??1)],['資材準備見込',esc(readiness)],['調達方針',esc(procurementPolicyName(p.procurement_policy))],['工数',`${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}`]];
    if(p.target_facility_id){const facility=state.operationalNode?.facilities?.find((row)=>row.id===p.target_facility_id);targetRows.push(['対象設備',esc(facility?.display_name||'設備')]);}
    if(p.target_cell_id)targetRows.push(['対象Cell',esc(surfaceCellLabel(p.target_cell_id))]);
    if(p.target_location_id)targetRows.push(['対象Location',esc(locationName(p.target_location_id))]);
    if(p.completed_facility_id){const facility=state.operationalNode?.facilities?.find((row)=>row.id===p.completed_facility_id);targetRows.push(['反映設備',esc(facility?.display_name||'設備')]);}
    const foundingProject=p.target_kind==='operational_node_founding';
    const committedLabel=foundingProject?'準備済':'投入済';
    const resourceRows=(p.resources||[]).map((r)=>{
      const securedLabel=p.target_kind==="operational_node_founding"
        ? `展開payload ${fmt(r.staged_t||0)} t`
        : `予約済み ${fmt(r.reserved_t||0)} t`;
      return `<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(r.resource_id))}</span><span>${fmt(r.required_t)} t</span></div><div class="cell-sub">${securedLabel} · ${committedLabel} ${fmt(r.committed_t)} t · 不足 ${fmt(r.shortage_t)} t</div></div>`;
    }).join('');
    const requirements=(state.logistics?.requirements||[]).filter((d)=>d.owner_kind===(foundingProject?'founding':'project')&&d.owner_id===p.id);
    const requirementHtml=requirements.length?requirements.map((d)=>{const forecast=d.forecast_requirement_day==null?'指定なし':`Day ${fmt(d.forecast_requirement_day,0)}`,arrival=d.projected_arrival_day==null?(d.earliest_confirmed_arrival_day==null?'未確定':`Day ${fmt(d.earliest_confirmed_arrival_day,0)}`):`Day ${fmt(d.projected_arrival_day,0)}`;const source=d.selected_source_id?locationName(d.selected_source_id):'未選択';const services=(d.selected_service_ids||[]).map(definitionName).join(' → ')||'経路未確定';const constrained=Boolean(d.routing_constraint_source_id||(d.routing_constraint_via_node_ids||[]).length||(d.routing_constraint_transport_allocation_ids||[]).length);return `<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(d.resource_id))}</span><span>${fmt(d.remaining_t)} t 待ち</span></div><div class="cell-main">${esc(source)} → ${esc(locationName(d.destination_id))}</div><div class="cell-sub">${esc(services)} · 輸送系内 ${fmt(d.pipeline_t)} t</div><div class="cell-sub">必要時期 ${esc(forecast)} · 予測到着 ${esc(arrival)}${d.selected_latency_days==null?'':` · 輸送 ${fmt(d.selected_latency_days,1)}日`}${d.selected_handoff_count==null?'':` · 積替 ${fmt(d.selected_handoff_count,0)}`}</div>${constrained?`<div class="cell-sub">固定条件: 供給元 ${esc(d.routing_constraint_source_id?locationName(d.routing_constraint_source_id):'自動')} / 経由 ${esc((d.routing_constraint_via_node_ids||[]).map(locationName).join(', ')||'なし')} / 固定輸送区間 ${(d.routing_constraint_transport_allocation_ids||[]).length} 件</div>`:''}<button type="button" data-project-routing-constraint data-owner-kind="${esc(d.owner_kind)}" data-owner-id="${esc(d.owner_id)}" data-destination-id="${esc(d.destination_id)}" data-resource-id="${esc(d.resource_id)}">${constrained?'固定条件を編集':'固定条件を設定'}</button></div>`;}).join(''):'<div class="empty-state">現在の補給需要なし</div>';
    const settingsDisabled=p.settings_editable?'':'disabled';
    const procurementDisabled=p.procurement_editable?'':'disabled';
    const procurementOptions=(p.procurement_policy_options||[]).map((value)=>`<option value="${esc(value)}" ${value===p.procurement_policy?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const projectControls=foundingProject
      ? `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeFounding':'PauseFounding'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'準備再開':'準備停止'}</button><div class="form-row"><label>優先度<select id="projectPriorityInput" ${settingsDisabled}>${priorityOptions(p.priority??3)}</select></label><button type="button" data-set-founding-priority="${esc(p.id)}" ${settingsDisabled}>優先度を適用</button></div><button type="button" class="danger-button" data-command="CancelFounding" data-project-id="${esc(p.id)}" ${settingsDisabled}>設立計画を取消</button></div>`
      : `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'建設再開':'建設停止'}</button><div class="form-row"><label>優先度<select id="projectPriorityInput" data-draft-key="project:${esc(p.id)}:priority" ${settingsDisabled}>${priorityOptions(p.priority??3)}</select></label><button type="button" data-set-project-priority="${esc(p.id)}" ${settingsDisabled}>優先度を適用</button></div><div class="form-row"><label>調達方針<select id="projectProcurementTimingPolicy" data-draft-key="project:${esc(p.id)}:procurement" ${procurementDisabled}>${procurementOptions}</select></label><button type="button" data-set-project-procurement="${esc(p.id)}" ${procurementDisabled}>方針を適用</button></div><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}" ${settingsDisabled}>案件取消</button></div>`;
    const foundingDecision=foundingProject?section('Founding Decision State',kv([['Target type',esc(p.founding_target_type||'—')],['Deployment phase',esc(p.deployment_phase||p.status||'—')],['Manifest readiness',p.manifest_ready?'<span class="badge ok">ready</span>':'<span class="badge warn">not ready</span>'],['Fleet commitment',p.fleet_commitment_id?esc(p.fleet_commitment_id):'—']])+`<h3>Knowledge Requirement</h3>${(p.founding_knowledge_requirements||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(row.subject_resource_id))}</span><span class="badge ${row.met?'ok':'warn'}">${fmt(row.current_level,0)} / ${fmt(row.minimum_level,0)}</span></div><div class="cell-sub">${esc(surfaceCellLabel(row.target_cell_id))}</div></div>`).join('')||'<div class="empty-state">Knowledge Requirementなし</div>'}<h3>Site blocker</h3>${(p.site_blockers||[]).length?`<div class="issue-stack">${p.site_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}<h3>Movement blocker</h3>${(p.movement_blockers||[]).length?`<div class="issue-stack">${p.movement_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}`):'';
    const disposalDecision=p.target_kind==='facility_decommission'?section('撤去時の回収',kv([['Irreversible',p.irreversible_started?'開始済み':'未開始'],['Recovery potential',esc((p.expected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')],['Projected fraction',p.projected_salvage_fraction==null?'—':pct(p.projected_salvage_fraction)],['Projected recovery',esc((p.projected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')],['Actual fraction',p.actual_salvage_fraction==null?'—':pct(p.actual_salvage_fraction)],['Actual recovery',esc((p.actual_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')]])):'';
    setInspector(p.display_name||p.facility_display_name||p.id,section('案件',kv(targetRows))+foundingDecision+disposalDecision+section('必要資源 / 調達',resourceRows||'<div class="empty-state">追加資源なし</div>')+section('補給需要',requirementHtml)+section('Limiting factor',limitingHtml(p.limiting_factors||[]))+section('Blocker',(p.blockers||[]).length?`<div class="issue-stack">${p.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',projectControls));
    return true;
  }
  function renderBuildOptionInspector(id){
    const o=state.buildOptions?.items?.find((x)=>x.facility_definition_id===id);if(!o)return false;
    const plan=planningOptionState(o,'建設計画可');
    const planOptions=state.buildOptions||{};
    const planControls=constructionPlanControls('buildPlan',{draftScope:`facility-build:${o.facility_definition_id}`,policyOptions:planOptions.procurement_policy_options||[],disabled:plan.disabled});
    setInspector(o.display_name,section('建設',kv([['必要工数',fmt(o.construction_required,0)],['自己展開',o.self_deploying?'はい':'いいえ'],['計画可否',esc(plan.label)]]))+section('必要資源',resourceCards(o.resources))+section('Blocker',plan.blockers.length?plan.blockers.map(issueHtml).join(''):'<span class="badge ok">なし</span>')+section('操作',`${planControls}<button type="button" class="primary" data-build="${esc(o.facility_definition_id)}" data-plan-prefix="buildPlan" ${plan.disabled?'disabled':''}>この条件で建設計画を作成</button>`));
    return true;
  }

  function lifecycleButton({domain,id,canStart,canPause,canResume,complete=false,startLabel,pauseLabel,resumeLabel,completeLabel='完了'}){
    let action='start',label=startLabel,enabled=Boolean(canStart),primary=Boolean(canStart);
    if(canPause){action='pause';label=pauseLabel;enabled=true;primary=false;}
    else if(canResume){action='resume';label=resumeLabel;enabled=true;primary=true;}
    else if(complete)return `<button type="button" data-lifecycle-control="${esc(domain)}" disabled>${esc(completeLabel)}</button>`;
    return `<button type="button" ${primary?'class="primary" ':''}data-lifecycle-control="${esc(domain)}" data-${domain}-action="${action}" data-id="${esc(id)}" ${enabled?'':'disabled'}>${label}</button>`;
  }
  function researchBlockers(r){return r.current_blockers||[];}
  function researchSiteLabel(site){if(!site)return '未選択';return `${locationName(site.operational_node_id)}${site.surface_cell_id?` / ${surfaceCellLabel(site.surface_cell_id)}`:''}`;}
  function siteOptionsHtml(r,kind){
    const options=r.execution_context_options||[],selected=r.execution_context;
    if(!options.length)return '<div class="empty-state">候補地点なし</div>';
    return options.map((site)=>{const blockers=site.blockers||[],blocked=blockers.length,isSelected=Boolean(selected)&&site.operational_node_id===selected.operational_node_id&&(site.surface_cell_id||null)===(selected.surface_cell_id||null),canSelect=Boolean(site.can_select),attr=kind==='prototype'?'data-research-prototype-site':'data-research-demo-site';const badge=isSelected?'選択中':canSelect?(blocked?`選択可 · ${blocked} 稼働blocker`:'選択可'):`${blocked||1} blocker`;return `<div class="detail-card ${isSelected?'is-usable':''}"><div class="mode-title"><span>${esc(researchSiteLabel(site))}</span><span class="badge ${blocked?'warn':canSelect||isSelected?'ok':''}">${badge}</span></div>${blocked?`<div class="issue-stack">${blockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:''}<button type="button" ${attr}="${esc(site.operational_node_id)}" data-surface-cell-id="${esc(site.surface_cell_id||'')}" data-id="${esc(r.id)}" data-stage-id="${esc(r.current_stage_id||'')}" ${!canSelect||isSelected?'disabled':''}>${kind==='prototype'?'試作地点に設定':'実証地点に設定'}</button></div>`;}).join('');
  }
  function prototypeResourceHtml(r){
    const rows=r.stage_resources||[];
    if(!rows.length)return '<div class="empty-state">追加試作資材なし</div>';
    return rows.map((x)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(x.resource_id))}</span><span>予約 ${fmt(x.reserved_t)} / 必要 ${fmt(x.required_t)} t</span></div><div class="cell-sub">今回要求 ${fmt(x.requested_t)} t · 割当 ${fmt(x.allocated_t)} t · 不足 ${fmt(x.unmet_t)} t · 輸送中 ${fmt(x.pipeline_t)} t</div></div>`).join('');
  }
  function experienceHtml(r){
    const rows=r.operational_experience||[];
    if(!rows.length)return '<div class="empty-state">運用経験要件なし</div>';
    return rows.map((x)=>`<div class="detail-card"><div class="mode-title"><span>${esc(definitionName(x.category_id))}</span><span>${fmt(x.current,1)} / ${fmt(x.required,1)}</span></div><div class="cell-sub">残り ${fmt(x.unmet,1)}</div></div>`).join('');
  }
  function renderResearchInspector(id){
    const r=state.research?.items?.find((x)=>x.id===id);if(!r)return false;
    const action=lifecycleButton({domain:'research',id:r.id,canStart:r.can_start,canPause:r.can_pause,canResume:r.can_resume,complete:r.status==='complete',startLabel:'研究開始',pauseLabel:'研究停止',resumeLabel:'研究再開',completeLabel:'研究完了'});
    const phaseBlockers=researchBlockers(r);let phase='';
    if(r.status==='theory'){
      phase=section('理論研究',kv([['進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)} RP`],['RP要求 / 割当',`${fmt(r.rp_requested,2)} / ${fmt(r.rp_allocated,2)} /日`],['残りRP',`${fmt(r.rp_remaining,1)} RP`],['研究実行要求 / 割当',`${fmt(r.execution_requested,2)} / ${fmt(r.execution_allocated,2)} /日`]]));
    }else if(r.status==='prototype'){
      phase=section('試作',`<div class="cell-sub">地点 ${esc(researchSiteLabel(r.execution_context))} · 研究実行 ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'prototype')}<h3>試作資材</h3>${prototypeResourceHtml(r)}`);
    }else if(r.status==='demonstration'){
      phase=section('実証',`<div class="cell-sub">進捗 ${fmt(r.stage_progress,1)}/${fmt(r.stage_required,1)}日 · 地点 ${esc(researchSiteLabel(r.execution_context))} · 研究実行 ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'demonstration')}`);
    }else if(r.status==='operational_experience'){
      phase=section('運用経験',experienceHtml(r));
    }
    const stageNames={theory:'理論',prototype:'試作',demonstration:'実証',operational_experience:'運用経験'};
    const stageSequence=(r.stages||[]).map((x)=>stageNames[x.stage_type]||A.userFacingText(x.stage_type)).join(' → ')||'—';
    const startRows=[['研究段階',esc(stageSequence)],['保有RP',fmt(state.research?.stored_points,1)],['RP貯蔵上限',fmt(state.research?.storage_capacity_points,1)]];
    if((r.stages||[]).some((x)=>x.stage_type==='theory'))startRows.splice(1,0,['理論研究の必要RP',fmt(r.total_theory_research_point_cost,1)]);
    const startState=['available','locked'].includes(r.status)?section('開始条件',kv(startRows)):'';
    const priorityControl=`<div class="form-row"><label>研究優先度<select id="researchPriorityInput" data-draft-key="research:${esc(r.id)}:priority">${priorityOptions(r.priority??3)}</select></label>${r.can_set_priority?`<button type="button" data-set-research-priority="${esc(r.id)}">優先度を適用</button>`:''}</div>`;
    setInspector(r.display_name,
      section('研究状態',kv([['段階',esc(stateLabels[r.status]||A.userFacingText(r.status))],['優先度',esc(priorityName(r.priority??3))],['段階進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)}`],['RP要求 / 割当',`${fmt(r.rp_requested,2)} / ${fmt(r.rp_allocated,2)}`],['研究実行要求 / 割当',`${fmt(r.execution_requested,2)} / ${fmt(r.execution_allocated,2)}`]]))+
      section('前提技術',(r.prerequisites||[]).length?(r.prerequisites||[]).map((x)=>`<span class="badge">${esc(definitionName(x))}</span>`).join(' '):'<span class="badge ok">なし</span>')+
      startState+
      section('現在のblocker',phaseBlockers.length?`<div class="issue-stack">${phaseBlockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:'<span class="badge ok">なし</span>')+
      phase+
      section('研究操作',`<div class="action-stack">${priorityControl}${action}</div>`)
    );
    return true;
  }
  function renderScientificExplorationInspector(id){
    const x=state.scientificExplorations?.items?.find((row)=>row.id===id);if(!x)return false;
    const vehicleRows=(x.fleet_options||[]).map((v)=>{
      const blockers=v.blockers||[];const selected=v.vehicle_definition_id===x.assigned_vehicle_definition_id;
      const badge=selected?'配備中':blockers.length?'条件不一致':v.can_assign?'配備可':'Fleet不足';
      return `<div class="detail-card"><div class="mode-title"><span>${esc(v.display_name)}</span><span class="badge ${selected||v.can_assign?'ok':blockers.length?'warn':''}">${badge}</span></div><div class="cell-sub">${esc(locationName(v.operational_node_id))} · 保有 ${fmt(v.total_units,0)} / 空き ${fmt(v.free_units,0)} / 必要 ${fmt(v.required_units,0)}</div><div class="cell-sub">往路 ${v.outbound_latency_days==null?'—':`${fmt(v.outbound_latency_days,0)}日`}${v.return_latency_days==null?'':` / 復路 ${fmt(v.return_latency_days,0)}日`}</div>${blockers.length?`<div class="issue-stack" style="margin-top:7px">${blockers.map((b)=>issueHtml(['exploration',b])).join('')}</div>`:''}<div class="action-row" style="margin-top:8px"><button type="button" data-exploration-assign="${esc(x.id)}" data-vehicle-definition-id="${esc(v.vehicle_definition_id)}" ${v.can_assign?'':'disabled'}>このFleetを配備</button></div></div>`;
    }).join('')||'<div class="empty-state">利用可能なFleet候補なし</div>';
    const inputs=(x.consumable_resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)}t`).join(' / ')||'追加消耗資源なし';
    const operations=(x.movement_operations||[]).map(([op,dv])=>`${esc(A.operationName(op))} ${fmt(dv,2)} km/s`).join(' / ')||'Fleet配備前は未確定';
    const vehicleCapabilities=(x.required_vehicle_capabilities||[]).map((capabilityId)=>esc(capabilityName(capabilityId))).join(' / ')||'追加能力要件なし';
    const blockers=x.blockers||[];
    const transitionLabels={start:'開始',assign_fleet:'Fleet配備',continue:'継続',pause:'停止',resume:'再開',unassign_fleet:'Fleet解除'};
    const transitions=(x.transition_options||[]).map((option)=>transitionLabels[option]||A.userFacingText(option)).join(' / ')||'なし';
    const dispositionLabels={return_to_origin_then_release:'出発地へ帰還後にFleet解放',release_at_destination:'到着地点でFleet解放'};
    const disposition=dispositionLabels[x.completion_disposition]||A.userFacingText(x.completion_disposition)||'—';
    let action=lifecycleButton({domain:'exploration',id:x.id,canStart:x.can_start,canPause:x.can_pause,canResume:x.can_resume,complete:x.status==='complete',startLabel:'探査開始',pauseLabel:'探査停止',resumeLabel:'探査再開',completeLabel:'探査完了'});
    if(x.can_unassign)action+=`<button type="button" data-exploration-unassign="${esc(x.id)}">Fleet配備を解除</button>`;
    setInspector(x.display_name,
      section('探査状態',kv([['出発地',esc(locationName(x.origin_id))],['探査先',esc(locationName(x.destination_id))],['往路時間',x.outbound_latency_days==null?'未確定':`${fmt(x.outbound_latency_days,0)}日`],['復路時間',x.return_latency_days==null?(x.assigned_vehicle_definition_id?'なし':'未確定'):`${fmt(x.return_latency_days,0)}日`],['現地活動期間',`${fmt(x.duration_days,1)}日`],['活動進捗',`${fmt(x.progress_days,1)}日`],['獲得RP',`${fmt(x.research_points_awarded,1)} / ${fmt(x.research_points_total,1)}`],['RP獲得速度',`${fmt(x.research_points_per_day,2)} /日`],['本日のRP要求 / 受入',`${fmt(x.rp_requested_today,2)} / ${fmt(x.rp_admitted_today,2)}`],['RP受入余力',fmt(x.rp_admission_headroom,2)],['RP受入blocker',x.rp_admission_blocker?esc(A.userFacingText(x.rp_admission_blocker)):'なし'],['必要機数',fmt(x.required_units,0)],['活動優先度',esc(priorityName(x.priority??3))],['配備Fleet',x.assigned_vehicle_definition_id?`${esc(definitionName(x.assigned_vehicle_definition_id))} · ${fmt(x.committed_units,0)} 機`:'未配備'],['完了時のFleet',esc(disposition)],['現在可能な操作',esc(transitions)]]))+
      section('必要条件',`<div class="cell-sub">移動要件: ${operations}</div><div class="cell-sub">最低payload: ${fmt(x.minimum_payload_t,2)} t</div><div class="cell-sub">必要Vehicle能力: ${vehicleCapabilities}</div><div class="cell-sub">消耗資源: ${inputs}</div><h3>${esc(locationName(x.origin_id))} の地点条件</h3>${siteRequirementsHtml(x.origin_requirements)}<h3>${esc(locationName(x.destination_id))} の地点条件</h3>${siteRequirementsHtml(x.destination_requirements)}`)+
      section('現在のblocker',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(['exploration',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('Fleet適合性',vehicleRows)+
      section('操作',`<div class="action-stack"><div class="form-row"><label>活動優先度<select id="explorationPriorityInput" data-draft-key="exploration:${esc(x.id)}:priority" ${(x.can_start||x.can_set_priority)?'':'disabled'}>${priorityOptions(x.priority??3)}</select></label><button type="button" data-set-exploration-priority="${esc(x.id)}" ${x.can_set_priority?'':'disabled'}>優先度を適用</button></div>${action||'<span class="badge">操作なし</span>'}</div>`)
    );
    return true;
  }

  function renderSurveyInspector(id){
    const s=state.surveys?.items?.find((x)=>`${x.cell_id}::${x.resource_id}`===id);if(!s)return false;
    const potential=s.visible_potential==null?'—':fmt(s.visible_potential,3);
    const precision=s.visible_potential_precision_fraction==null?'—':s.visible_potential_precision_fraction<=0?'測定済み':`±${pct(s.visible_potential_precision_fraction)}`;
    const containing=(state.surveys?.campaigns||[]).filter((c)=>(c.target_cell_ids||[]).includes(s.cell_id)&&(c.resource_ids||[]).includes(s.resource_id));
    setInspector(`${s.resource_name} · ${s.cell_label}`,
      section('地表知識',kv([['Knowledge Level',String(s.knowledge_level)],['調査進捗',fmt(s.progress,2)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['推定埋蔵量',potential],['推定精度',precision]]))+
      section('関連Survey',containing.length?containing.map((c)=>`<button type="button" data-inspect="survey-campaign" data-id="${esc(c.id)}">${esc(knowledgeGoalName(c.goal_knowledge_level))} · ${c.target_cell_ids.length} Cell × ${c.resource_ids.length} Resource</button>`).join(' '):'<div class="cell-sub">この対象を含むSurveyはありません。地表Mapで範囲と資源を選択して開始できます。</div>')
    );return true;
  }

  function renderSurveyCampaignInspector(id){
    const c=state.surveys?.campaigns?.find((row)=>row.id===id);if(!c)return false;
    const all=state.surveys?.items||[],cellMap=new Map(),resourceMap=new Map();
    all.forEach((row)=>{cellMap.set(row.cell_id,row.cell_label);resourceMap.set(row.resource_id,row.resource_name);});
    const cellChecks=[...cellMap].map(([cellId,label])=>`<label class="check-row"><input type="checkbox" data-survey-campaign-cell data-draft-key="survey:${esc(c.id)}:cell:${esc(cellId)}" value="${esc(cellId)}" ${(c.target_cell_ids||[]).includes(cellId)?'checked':''}>${esc(label)}</label>`).join('');
    const resourceChecks=[...resourceMap].map(([resourceId,label])=>`<label class="check-row"><input type="checkbox" data-survey-campaign-resource data-draft-key="survey:${esc(c.id)}:resource:${esc(resourceId)}" value="${esc(resourceId)}" ${(c.resource_ids||[]).includes(resourceId)?'checked':''}>${esc(label)}</label>`).join('');
    const candidates=(c.candidates||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(definitionName(row.provider_definition_id))} / ${esc(definitionName(row.observation_mode_id))}</span><span class="badge ${row.viable?'ok':'warn'}">${row.viable?'利用可能':'利用不可'}</span></div><div class="cell-sub">${esc(locationName(row.provider_operational_node_id))} · ${esc(A.userFacingText(row.provider_source_kind))} · 調査速度 ${fmt(row.survey_rate,2)} · 到達可能 K${fmt(row.max_knowledge_level,0)}</div><div class="cell-sub">配備 ${fmt(row.assigned_source_units,0)} / 最低 ${fmt(row.minimum_source_units,0)} · 能力 ${fmt(row.capacity_units_per_day,2)}/日</div><div class="cell-sub">推定精度 ±${pct(row.estimate_uncertainty_fraction)} / 測定精度 ±${pct(row.measurement_precision_fraction)}</div>${(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(['survey',b])).join('')}</div>`:''}<button type="button" data-survey-constrain-candidate="${esc(c.id)}" data-provider-definition-id="${esc(row.provider_definition_id)}" data-operational-node-id="${esc(row.provider_operational_node_id)}" data-observation-mode-id="${esc(row.observation_mode_id)}">この観測手段に固定</button></div>`).join('')||'<div class="empty-state">現在利用可能な観測手段はありません。</div>';
    const targetRows=(c.targets||[]).map((row)=>`<tr><td>${esc(surfaceCellLabel(row.cell_id))}</td><td>${esc(resourceName(row.resource_id))}</td><td>K${fmt(row.current_knowledge_level,0)} → K${fmt(row.goal_knowledge_level,0)}</td><td>${fmt(row.progress,2)} / ${fmt(row.target_threshold,2)}</td><td>${row.complete?'✓':'—'}</td></tr>`).join('');
    const blockers=c.blockers||[];
    const provider=c.projected_provider_definition_id?`${definitionName(c.projected_provider_definition_id)} @ ${locationName(c.projected_provider_operational_node_id)} / ${definitionName(c.projected_observation_mode_id)}`:'未解決';
    const actions=lifecycleButton({domain:'survey-campaign',id:c.id,canStart:false,canPause:c.can_pause,canResume:c.can_resume,complete:c.status==='completed',pauseLabel:'Survey停止',resumeLabel:'Survey再開',completeLabel:'Survey完了'});
    setInspector(`Survey · ${knowledgeGoalName(c.goal_knowledge_level)}`,
      section('Survey状態',kv([['状態',esc(stateLabels[c.status]||A.userFacingText(c.status))],['調査目標',esc(knowledgeGoalName(c.goal_knowledge_level))],['完了 / 残り対象',`${fmt(c.covered_targets,0)} / ${fmt(c.remaining_targets,0)}`],['解決された観測手段',esc(provider)],['能力要求 / 割当',`${fmt(c.requested_service_units_per_day,2)} / ${fmt(c.allocated_service_units_per_day,2)}`],['調査進行能力',`${fmt(c.capacity_points_per_day,2)} /日`],['必要 / 配備Fleet',c.required_fleet_units==null?'—':`${fmt(c.required_fleet_units,0)} / ${fmt(c.assigned_fleet_units,0)}`],['予測残り時間',c.projected_remaining_days==null?'—':`${fmt(c.projected_remaining_days,1)}日`],['優先度',esc(priorityName(c.priority??3))]]))+
      section('範囲・目標の編集',`<div class="detail-grid"><div class="detail-card"><div class="mode-title"><span>対象Cell</span></div>${cellChecks}</div><div class="detail-card"><div class="mode-title"><span>対象資源</span></div>${resourceChecks}</div></div><div class="form-row"><label>調査目標<select id="surveyCampaignGoal" data-draft-key="survey:${esc(c.id)}:goal"><option value="1" ${Number(c.goal_knowledge_level)===1?'selected':''}>1 存在確認</option><option value="2" ${Number(c.goal_knowledge_level)===2?'selected':''}>2 埋蔵量推定</option><option value="3" ${Number(c.goal_knowledge_level)===3?'selected':''}>3 精密測定</option></select></label><button type="button" data-update-survey-campaign="${esc(c.id)}" disabled>範囲・目標を適用</button></div><div data-survey-update-intent-status><span class="badge">可否確認中</span></div>`)+
      section('対象ごとの進捗',`<div class="table-wrap"><table><thead><tr><th>Cell</th><th>資源</th><th>Knowledge</th><th>進捗</th><th>目標到達</th></tr></thead><tbody>${targetRows}</tbody></table></div>`)+
      section('観測手段の候補差',candidates)+
      section('観測手段の固定',`<div class="cell-sub">Provider: ${esc(c.provider_constraint_definition_id?`${definitionName(c.provider_constraint_definition_id)} @ ${locationName(c.provider_constraint_operational_node_id)}`:'自動')} · Mode: ${esc(c.observation_mode_constraint?definitionName(c.observation_mode_constraint):'自動')}</div><button type="button" data-clear-survey-constraint="${esc(c.id)}">自動選択へ戻す</button>`)+
      section('現在のblocker',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(['survey',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack">${actions}<div class="form-row"><label>活動優先度<select id="surveyPriorityInput" data-draft-key="survey:${esc(c.id)}:priority">${priorityOptions(c.priority??3)}</select></label><button data-set-survey-priority="${esc(c.id)}" ${c.can_set_priority?'':'disabled'}>優先度を適用</button></div></div>`)
    );return true;
  }


  function renderSurfaceCellInspector(id){
    const cell=surfaceCell(id);if(!cell)return false;
    const terrain=Object.fromEntries(cell.terrain||[]);
    const owner=cell.location_id?locationName(cell.location_id):'未所属';
    const neighbors=(cell.neighbor_ids||[]).map((neighbor)=>`<span class="badge">${esc(surfaceCellLabel(neighbor))}</span>`).join(' ')||'<span class="badge">なし</span>';

    const foundation=(cell.foundation_options||[]).map((option)=>{
      const plan=planningOptionState(option,'設立可'),blockers=plan.blockers,active=option.active_project_id;
      const disabled=plan.disabled;
      const scope=`foundation:${cell.id}:${option.staging_node_id}:${option.deployment_recipe_id}:${option.vehicle_definition_id}`;
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(locationName(option.staging_node_id))} · ${esc(option.recipe_display_name)} · ${esc(option.vehicle_display_name)}</span><span class="badge ${disabled?'warn':'ok'}">${active?'案件進行中':esc(plan.label)}</span></div><div class="cell-sub">準備工数 ${fmt(option.preparation_work,0)} · 輸送 ${fmt(option.transit_days,0)}日 · Payload ${fmt(option.payload_t,2)} t (${fmt(option.payload_t_per_unit,2)} t/機 × ${fmt(option.required_units,0)}機)</div><div class="cell-sub">Staging必要Resource</div><div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${active?`<div class="cell-sub">Active Project: ${esc(active)}</div>`:''}<div class="form-row"><label>Location名<input type="text" data-new-location-name data-draft-key="${esc(scope)}:name" placeholder="新規地表拠点"></label></div>${foundingPlanControls(scope,option,disabled)}<button type="button" class="primary" data-surface-found data-staging-node-id="${esc(option.staging_node_id)}" data-recipe-id="${esc(option.deployment_recipe_id)}" data-vehicle-id="${esc(option.vehicle_definition_id)}" data-cell-id="${esc(cell.id)}" data-body-id="${esc(cell.body_id)}" ${disabled?'disabled':''}>Founding Deploymentを開始</button></div>`;
    }).join('')||'<div class="empty-state">このCellへ利用可能なFounding Deployment候補がありません。</div>';

    const development=(cell.development_options||[]).map((option)=>{
      const plan=planningOptionState(option,'開発可'),blockers=plan.blockers,active=option.active_project_id;
      const disabled=plan.disabled;
      const infra=option.projected_surface_infrastructure_fulfillment==null?'—':pct(option.projected_surface_infrastructure_fulfillment);
      const limiting=(option.limiting_factors||[]).map((factor)=>`<span class="badge warn">${esc(A.userFacingText(factor))}</span>`).join(' ');
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(locationName(option.location_id))} へ編入</span><span class="badge ${disabled?'warn':'ok'}">${active?'案件進行中':esc(plan.label)}</span></div><div class="cell-sub">工数 ${fmt(option.construction_required,0)} · Projected Surface Infrastructure ${infra}</div>${option.projected_surface_infrastructure_demand==null?'':`<div class="cell-sub">Projected Demand ${fmt(option.projected_surface_infrastructure_demand,2)}</div>`}<div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${limiting?`<div class="cell-sub">Limiting: ${limiting}</div>`:''}${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${active?`<div class="cell-sub">Active Project: ${esc(active)}</div>`:''}${surfacePlanControls(`development:${cell.id}:${option.location_id}`,option,disabled)}<button type="button" class="primary" data-surface-develop="${esc(option.location_id)}" data-cell-id="${esc(cell.id)}" ${disabled?'disabled':''}>Surface Cell開発Projectを作成</button></div>`;
    }).join('')||'<div class="empty-state">既存Locationへの開発候補なし</div>';

    const facilities=(cell.facility_placement_options||[]).map((option)=>{
      const plan=planningOptionState(option,'建設可'),blockers=plan.blockers,disabled=plan.disabled;
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(option.display_name)}</span><span class="badge ${blockers.length?'warn':plan.canPlan?'ok':''}">${esc(plan.label)}</span></div><div class="cell-sub">工数 ${fmt(option.construction_required,0)} · ${option.self_deploying?'自己展開':'通常施工'}</div><div class="cell-sub">Staging必要Resource</div><div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${surfacePlanControls(`surface-build:${cell.id}:${option.facility_definition_id}`,option,disabled)}<button type="button" class="primary" data-surface-build="${esc(option.facility_definition_id)}" data-location-id="${esc(option.location_id)}" data-cell-id="${esc(cell.id)}" ${disabled?'disabled':''}>このCellへ建設Projectを作成</button></div>`;
    }).join('')||'<div class="empty-state">このCellへ配置可能な位置依存Facilityはありません。</div>';

    const foundationSection=cell.developed?'':section('Location設立',foundation);
    const developmentSection=cell.developed?'':section('既存Locationから開発',development);
    const facilitySection=cell.developed?section('位置依存Facility',facilities):'';
    setInspector(surfaceCellLabel(cell.id),
      section('Cell状態',kv([
        ['Cell ID',esc(cell.id)],
        ['所属Location',esc(owner)],
        ['Location中心',cell.is_location_core?'はい':'いいえ'],
        ['面積',`${fmt(cell.area_km2,0)} km²`],
        ['緯度',`${fmt(cell.latitude_deg,2)}°`],
        ['経度',`${fmt(cell.longitude_deg,2)}°`],
      ]))+
      section('Terrain',kv([
        ['Terrain factor',fmt(terrain.terrain_factor,2)],
        ['Bearing capacity',fmt(terrain.bearing_capacity_factor,2)],
        ['Dust',fmt(terrain.dust_factor,2)],
        ['Slope',fmt(terrain.slope_factor,2)],
      ]))+
      section('隣接Cell',neighbors)+
      section('Current Environment',environmentHtml(cell.environment))+
      section('Resource Knowledge',surfaceResourcesHtml(cell.resources,cell.id))+
      foundationSection+developmentSection+facilitySection
    );
    return true;
  }

  function renderInspector(){
    if(!state.inspector){setInspector('選択項目','<div class="empty-state">中央の項目を選択すると、状態・条件・操作をここに表示します。</div>');return;}
    const {type,id}=state.inspector;
    const handlers={facility:renderFacilityInspector,resource:renderResourceInspector,'dependency-resource':renderDependencyResourceInspector,'extraction-resource':renderExtractionResourceInspector,project:renderProjectInspector,'build-option':renderBuildOptionInspector,research:renderResearchInspector,'scientific-exploration':renderScientificExplorationInspector,survey:renderSurveyInspector,'survey-campaign':renderSurveyCampaignInspector,'surface-cell':renderSurfaceCellInspector};
    if(!handlers[type]?.(id)){state.inspector=null;setInspector('選択項目','<div class="empty-state">項目の状態が変化しました。再選択してください。</div>');}
  }

  function render(){
    const loc=state.operationalNode;
    if(!loc){
      $('#locationTitle').textContent=locationName(state.operationalNodeId);
      $('#locationKind').textContent='地点状態を取得中';
      $('#headlineMetrics').innerHTML='';
      $$('.tab-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.tab===state.activeTab));
      $('#operationsTabContent').innerHTML='<div class="empty-state">地点状態を取得しています。</div>';
      setInspector('選択項目','<div class="empty-state">地点状態の取得後に操作できます。</div>');
      return;
    }
    $('#locationTitle').textContent=loc.display_name;
    const kind=(state.world?.operational_nodes||[]).find((x)=>x.id===loc.id)?.kind;
    $('#locationKind').textContent=`${A.locationKindLabels[kind]||kind||'拠点'}拠点`;
    $('#headlineMetrics').innerHTML=[['発電',`${fmt(loc.power_generation_mw)} MW`],['需要',`${fmt(loc.power_demand_mw)} MW`],['建設能力',`${fmt(loc.construction_capacity_per_day)} /日`],['設備',`${loc.facilities.length}`]].map(A.metricHtml).join('');
    $$('.tab-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.tab===state.activeTab));
    renderActiveTab();renderInspector();queueMicrotask(refreshVisibleSurveyIntentPreview);
  }

  document.addEventListener('change',(event)=>{
    if(state.activeView!=='operations')return;
    if(event.target.matches('[data-survey-draft-cell],[data-survey-draft-resource],#surveyDraftGoal')){
      void refreshSurveyIntentPreview();
      return;
    }
    if(event.target.matches('[data-survey-campaign-cell],[data-survey-campaign-resource],#surveyCampaignGoal')){
      const update=$('[data-update-survey-campaign]');
      if(update)void refreshSurveyIntentPreview(update.dataset.updateSurveyCampaign);
    }
  });

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='operations')return;
    const dependencyToggle=event.target.closest('[data-dependency-view]');if(dependencyToggle){dependencyView=dependencyToggle.dataset.dependencyView==='forecast'?'forecast':'current';renderActiveTab();renderInspector();return;}
    const tab=event.target.closest('[data-tab]');if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;render();if(['surface','survey'].includes(state.activeTab)){try{await A.loadUiSnapshot({preserveInteraction:false});}catch(e){banner(e.message,'error');}}return;}
    const inspect=event.target.closest('[data-inspect]');if(inspect){state.inspector={type:inspect.dataset.inspect,id:inspect.dataset.id};if(inspect.dataset.inspect==='surface-cell')render();else{renderInspector();$$('#operationsTabContent [data-inspect]').forEach((target)=>{const selected=target.dataset.inspect===inspect.dataset.inspect&&target.dataset.id===inspect.dataset.id;target.classList.toggle('is-selected',selected);if(target.hasAttribute('aria-pressed'))target.setAttribute('aria-pressed',selected?'true':'false');});}return;}
    const surfaceBuild=event.target.closest('[data-surface-build]');if(surfaceBuild){const plan=surfacePlanPayload(surfaceBuild);try{await command('PlanBuild',{operational_node_id:surfaceBuild.dataset.locationId,facility_id:surfaceBuild.dataset.surfaceBuild,site_cell_id:surfaceBuild.dataset.cellId,...plan});banner('Surface Cell建設Projectを作成しました');}catch{}return;}
    const surfaceDevelop=event.target.closest('[data-surface-develop]');if(surfaceDevelop){const plan=surfacePlanPayload(surfaceDevelop);try{await command('DevelopSurfaceCell',{location_id:surfaceDevelop.dataset.surfaceDevelop,cell_id:surfaceDevelop.dataset.cellId,...plan});banner('Surface Cell開発Projectを作成しました');}catch{}return;}
    const surfaceFound=event.target.closest('[data-surface-found]');if(surfaceFound){const card=surfaceFound.closest('.surface-action-card'),displayName=card?.querySelector('[data-new-location-name]')?.value.trim();if(!displayName){banner('Location名を入力してください','error');return;}const priority=Number(card?.querySelector('[data-founding-priority]')?.value??3);try{await command('PlanOperationalNodeFounding',{staging_node_id:surfaceFound.dataset.stagingNodeId,display_name:displayName,target_spec:{target_type:'surface_location',body_id:surfaceFound.dataset.bodyId,core_cell_id:surfaceFound.dataset.cellId},deployment_recipe_id:surfaceFound.dataset.recipeId,vehicle_definition_id:surfaceFound.dataset.vehicleId,priority});banner('Founding Deploymentを開始しました');}catch{}return;}
    const build=event.target.closest('[data-build]');if(build){const prefix=build.dataset.planPrefix||'buildPlan',priority=Number($(`#${prefix}PriorityInput`)?.value??3),procurementPolicy=$(`#${prefix}ProcurementTimingPolicy`)?.value||'standard_wait';try{await command('PlanBuild',{operational_node_id:state.operationalNodeId,facility_id:build.dataset.build,priority,procurement_policy:procurementPolicy});banner('建設計画を作成しました');}catch{}return;}
    const upgrade=event.target.closest('[data-upgrade]');if(upgrade){const prefix=upgrade.dataset.planPrefix||'upgradePlan',priority=Number($(`#${prefix}PriorityInput`)?.value??3),procurementPolicy=$(`#${prefix}ProcurementTimingPolicy`)?.value||'standard_wait';try{const result=await command('PlanFacilityUpgrade',{facility_id:upgrade.dataset.upgrade,priority,procurement_policy:procurementPolicy});banner(`Upgrade案件 ${result?.created_id||''} を作成しました`);}catch{}return;}
    const cmd=event.target.closest('[data-command]');if(cmd){const payload={};if(cmd.dataset.facilityId)payload.facility_id=cmd.dataset.facilityId;if(cmd.dataset.projectId)payload.project_id=cmd.dataset.projectId;try{await command(cmd.dataset.command,payload);}catch{}return;}
    const process=event.target.closest('[data-set-facility-process]');if(process){const select=$('#facilityProcessSelect');if(select?.value){try{await command('SetFacilityProcess',{facility_id:process.dataset.setFacilityProcess,process_id:select.value});banner('生産Processを更新しました');}catch{}}return;}
    const fp=event.target.closest('[data-set-facility-activity-priority]');if(fp){try{await command('SetFacilityActivityPriority',{facility_id:fp.dataset.setFacilityActivityPriority,priority:Number($('#facilityPriorityInput').value)});}catch{}return;}
    const mp=event.target.closest('[data-set-maintenance-priority]');if(mp){try{await command('SetMaintenancePriority',{facility_id:mp.dataset.setMaintenancePriority,priority:Number($('#maintenancePriorityInput').value)});}catch{}return;}
    const projectPriority=event.target.closest('[data-set-project-priority]');if(projectPriority){try{await command('SetProjectPriority',{project_id:projectPriority.dataset.setProjectPriority,priority:Number($('#projectPriorityInput').value)});}catch{}return;}
    const foundingPriority=event.target.closest('[data-set-founding-priority]');if(foundingPriority){try{await command('SetFoundingPriority',{project_id:foundingPriority.dataset.setFoundingPriority,priority:Number($('#projectPriorityInput').value)});}catch{}return;}
    const projectSourcing=event.target.closest('[data-set-project-procurement]');if(projectSourcing){try{await command('SetProjectProcurementPolicy',{project_id:projectSourcing.dataset.setProjectProcurement,procurement_policy:$('#projectProcurementTimingPolicy').value});}catch{}return;}
    const projectRouting=event.target.closest('[data-project-routing-constraint]');if(projectRouting){const prefill={destination_id:projectRouting.dataset.destinationId,owner_kind:projectRouting.dataset.ownerKind,owner_id:projectRouting.dataset.ownerId,resource_id:projectRouting.dataset.resourceId};const existing=(state.logistics?.routing_constraints||[]).find((x)=>x.destination_id===prefill.destination_id&&x.owner_kind===prefill.owner_kind&&x.owner_id===prefill.owner_id&&x.resource_id===prefill.resource_id);window.SpaceIdleLogistics?.openRoutingConstraintDialog(existing||null,prefill);return;}
    const ra=event.target.closest('[data-research-action]');if(ra){const map={start:'StartResearch',pause:'PauseResearch',resume:'ResumeResearch'},payload={research_id:ra.dataset.id};if(ra.dataset.researchAction==='start')payload.priority=Number($('#researchPriorityInput')?.value??3);try{await command(map[ra.dataset.researchAction],payload);}catch{}return;}
    const protoSite=event.target.closest('[data-research-prototype-site]');if(protoSite){try{await command('SetResearchPrototypeSite',{research_id:protoSite.dataset.id,stage_id:protoSite.dataset.stageId,operational_node_id:protoSite.dataset.researchPrototypeSite,surface_cell_id:protoSite.dataset.surfaceCellId||null});}catch{}return;}
    const researchPriority=event.target.closest('[data-set-research-priority]');if(researchPriority){try{await command('SetResearchPriority',{research_id:researchPriority.dataset.setResearchPriority,priority:Number($('#researchPriorityInput').value)});}catch{}return;}
    const demo=event.target.closest('[data-research-demo-site]');if(demo){try{await command('SetResearchDemonstrationSite',{research_id:demo.dataset.id,stage_id:demo.dataset.stageId,operational_node_id:demo.dataset.researchDemoSite,surface_cell_id:demo.dataset.surfaceCellId||null});}catch{}return;}
    const providerFleet=event.target.closest('[data-research-provider-set-fleet]');if(providerFleet){const card=providerFleet.closest('[data-research-provider-fleet-card]'),quantity=Number(card?.querySelector('[data-research-provider-fleet-quantity]')?.value??0);try{await command('SetResearchProviderFleetQuantity',{provider_definition_id:providerFleet.dataset.researchProviderSetFleet,operational_node_id:providerFleet.dataset.operationalNodeId,vehicle_definition_id:providerFleet.dataset.vehicleDefinitionId,quantity});banner('Research Provider用途のFleet数量を更新しました');}catch{}return;}
    const providerPriority=event.target.closest('[data-research-provider-set-priority]');if(providerPriority){const card=providerPriority.closest('[data-research-provider-card]'),priority=Number(card?.querySelector('[data-research-provider-priority]')?.value??3);try{await command('SetResearchProviderAssignmentPriority',{assignment_id:providerPriority.dataset.researchProviderSetPriority,priority});}catch{}return;}
    const providerPause=event.target.closest('[data-research-provider-pause]');if(providerPause){try{await command('PauseResearchProviderAssignment',{assignment_id:providerPause.dataset.researchProviderPause});}catch{}return;}
    const providerResume=event.target.closest('[data-research-provider-resume]');if(providerResume){try{await command('ResumeResearchProviderAssignment',{assignment_id:providerResume.dataset.researchProviderResume});}catch{}return;}
    const surveyProviderFleet=event.target.closest('[data-survey-provider-set-fleet]');if(surveyProviderFleet){const card=surveyProviderFleet.closest('[data-survey-provider-fleet-card]'),quantity=Number(card?.querySelector('[data-survey-provider-fleet-quantity]')?.value??0);try{await command('SetSurveyProviderFleetQuantity',{provider_definition_id:surveyProviderFleet.dataset.surveyProviderSetFleet,operational_node_id:surveyProviderFleet.dataset.operationalNodeId,vehicle_definition_id:surveyProviderFleet.dataset.vehicleDefinitionId,quantity});banner('Survey Provider用途のFleet数量を更新しました');}catch{}return;}
    const ea=event.target.closest('[data-exploration-action]');if(ea){const map={start:'StartScientificExploration',pause:'PauseScientificExploration',resume:'ResumeScientificExploration'},payload={exploration_id:ea.dataset.id};if(ea.dataset.explorationAction==='start')payload.priority=Number($('#explorationPriorityInput')?.value??3);try{await command(map[ea.dataset.explorationAction],payload);}catch{}return;}
    const ep=event.target.closest('[data-set-exploration-priority]');if(ep){try{await command('SetScientificExplorationPriority',{exploration_id:ep.dataset.setExplorationPriority,priority:Number($('#explorationPriorityInput').value)});}catch{}return;}
    const assign=event.target.closest('[data-exploration-assign]');if(assign){try{await command('AssignExplorationFleet',{exploration_id:assign.dataset.explorationAssign,vehicle_definition_id:assign.dataset.vehicleDefinitionId});}catch{}return;}
    const unassign=event.target.closest('[data-exploration-unassign]');if(unassign){try{await command('UnassignExplorationFleet',{exploration_id:unassign.dataset.explorationUnassign});}catch{}return;}
    const startSurvey=event.target.closest('[data-start-survey-campaign]');if(startSurvey){const target_cell_ids=$$('[data-survey-draft-cell]:checked').map((x)=>x.value),resource_ids=$$('[data-survey-draft-resource]:checked').map((x)=>x.value);if(!target_cell_ids.length||!resource_ids.length){banner('対象CellとResourceを1つ以上選択してください','error');return;}try{const result=await command('StartSurvey',{target_cell_ids,resource_ids,goal_knowledge_level:Number($('#surveyDraftGoal')?.value??1),priority:Number($('#surveyDraftPriority')?.value??3),provider_constraint:null,observation_mode_constraint:null});banner(`Survey Campaign ${result?.created_id||''} を作成しました`);}catch{}return;}
    const campaignAction=event.target.closest('[data-survey-campaign-action]');if(campaignAction){const map={pause:'PauseSurvey',resume:'ResumeSurvey'};try{await command(map[campaignAction.dataset.surveyCampaignAction],{campaign_id:campaignAction.dataset.id});}catch{}return;}
    const updateSurvey=event.target.closest('[data-update-survey-campaign]');if(updateSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===updateSurvey.dataset.updateSurveyCampaign);if(!c)return;const target_cell_ids=$$('[data-survey-campaign-cell]:checked').map((x)=>x.value),resource_ids=$$('[data-survey-campaign-resource]:checked').map((x)=>x.value);try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids,resource_ids,goal_knowledge_level:Number($('#surveyCampaignGoal')?.value??c.goal_knowledge_level),provider_constraint:c.provider_constraint_definition_id?{provider_definition_id:c.provider_constraint_definition_id,operational_node_id:c.provider_constraint_operational_node_id}:null,observation_mode_constraint:c.observation_mode_constraint});}catch{}return;}
    const constrainSurvey=event.target.closest('[data-survey-constrain-candidate]');if(constrainSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===constrainSurvey.dataset.surveyConstrainCandidate);if(!c)return;try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids:c.target_cell_ids,resource_ids:c.resource_ids,goal_knowledge_level:c.goal_knowledge_level,provider_constraint:{provider_definition_id:constrainSurvey.dataset.providerDefinitionId,operational_node_id:constrainSurvey.dataset.operationalNodeId},observation_mode_constraint:constrainSurvey.dataset.observationModeId});}catch{}return;}
    const clearSurvey=event.target.closest('[data-clear-survey-constraint]');if(clearSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===clearSurvey.dataset.clearSurveyConstraint);if(!c)return;try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids:c.target_cell_ids,resource_ids:c.resource_ids,goal_knowledge_level:c.goal_knowledge_level,provider_constraint:null,observation_mode_constraint:null});}catch{}return;}
    const sp=event.target.closest('[data-set-survey-priority]');if(sp){try{await command('SetSurveyPriority',{campaign_id:sp.dataset.setSurveyPriority,priority:Number($('#surveyPriorityInput').value)});}catch{}return;}
  });

  window.SpaceIdleOperations={render};
})();
