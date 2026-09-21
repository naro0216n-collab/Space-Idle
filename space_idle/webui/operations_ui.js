(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before operations_ui.js');
  const {state,$,$$,esc,fmt,pct,resourceName,locationName,definitionName,capabilityName,serviceName,stateLabels,issueHtml,statHtml,signed,api,command,banner}=A;

  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const setInspector=(title,html)=>{$('#inspectorTitle').textContent=title;$('#inspectorContent').innerHTML=html;A.restoreActiveDraftValues?.();};
  const resourceCards=(resources)=>(resources||[]).map((r)=>{
    const available=Number(r.available_t||0),required=Number(r.required_t||0),shortage=Math.max(0,required-available);
    const sourcing=shortage<=1e-9
      ? '<span class="badge ok">現地準備済み</span>'
      : r.projected_arrival_day!=null
        ? `<span class="cell-sub">不足 ${fmt(shortage,2)} t · ${esc(locationName(r.projected_source_id))} から Day ${fmt(r.projected_arrival_day,0)} 見込み</span>`
        : `<span class="cell-sub">不足 ${fmt(shortage,2)} t · 供給見込み未確定</span>`;
    return `<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(r.resource_id))}</span><span>${fmt(required)} t</span></div><div class="cell-sub">現地利用可能 ${fmt(available,2)} t</div>${sourcing}</div>`;
  }).join('')||'<div class="empty-state">追加資源なし</div>';
  const procurementPolicyLabels={immediate:'即時外部調達',standard_wait:'標準待機後に外部調達',extended_wait:'現地在庫を長く待つ'};
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  const knowledgeGoalLabels={1:'存在確認',2:'埋蔵量推定',3:'精密測定'};
  const knowledgeGoalName=(value)=>knowledgeGoalLabels[Number(value)]||`調査知識 ${fmt(value,0)}`;
  const priorityName=(value)=>priorityLabels[Number(value)]?`${value} ${priorityLabels[Number(value)]}`:String(value??'—');
  const priorityControl=(selected,inputAttributes,label='優先度',disabled=false)=>A.prioritySegmentedHtml(selected,{inputAttributes,label,disabled});
  const procurementPolicyName=(value)=>procurementPolicyLabels[value]||value||'—';
  const limitingHtml=(rows)=>(rows||[]).length?`<div class="issue-stack">${rows.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>';
  const environmentFacetLabels={gravity:'重力',atmosphere:'大気',thermal:'温度',illumination:'日照',radiation:'放射線'};
  const environmentFacetName=(key)=>environmentFacetLabels[key]||A.userFacingText(key);
  const surveyLayerNames={environment:'環境',knowledge:'調査知識',potential:'資源ポテンシャル',territory:'拠点領域',movement:'移動到達性'};
  function surveyLayerSummary(cell,knowledgeRows){
    const levels=(knowledgeRows||[]).map((row)=>Number(row.knowledge_level||0));
    const measured=(knowledgeRows||[]).filter((row)=>row.visible_potential!=null&&Number(row.visible_potential_precision_fraction||0)<=0).length;
    const estimated=(knowledgeRows||[]).filter((row)=>row.visible_potential!=null).length;
    const environment=(cell.environment||[]).slice(0,2).map((row)=>environmentFacetName(row.key)).join(' · ')||'環境情報なし';
    const knowledge=levels.length?`${levels.length}資源 · Lv ${Math.min(...levels)}–${Math.max(...levels)}`:'調査対象なし';
    const potential=estimated?`推定 ${estimated}資源${measured?` · 測定済み ${measured}`:''}`:'未推定';
    const territory=cell.location_id?`${locationName(cell.location_id)} · ${cell.is_location_core?'拠点中心':cell.developed?'開発済み':'所属'}`:'未所属';
    const movement=cell.movement_accessible==null?'到達性情報なし':cell.movement_accessible?`到達可能${cell.minimum_transit_days==null?'':` · 最短 ${fmt(cell.minimum_transit_days,0)}日`}`:'到達経路なし';
    return {environment,knowledge,potential,territory,movement};
  }
  let dependencyView='current';
  let detailedForecast=null;
  let detailedForecastLoading=false;
  let detailedForecastHorizon='SHORT_TERM';
  let surveyMapLayer='knowledge';
  const comparisonPins=new Map();
  function comparisonPinnedKeys(scopeKey,candidates){
    const valid=new Set((candidates||[]).map((row)=>row.comparison_key));
    const pins=(comparisonPins.get(scopeKey)||[]).filter((key)=>valid.has(key)).slice(0,4);
    comparisonPins.set(scopeKey,pins);
    return pins;
  }
  function toggleComparisonPin(scopeKey,candidates,key){
    const pins=comparisonPinnedKeys(scopeKey,candidates);
    const index=pins.indexOf(key);
    if(index>=0)pins.splice(index,1);else if(pins.length<4)pins.push(key);
    comparisonPins.set(scopeKey,pins);
    return pins;
  }
  function comparisonValue(row,axisKey){
    return (row.comparison_values||[]).find((value)=>value.axis_key===axisKey)||null;
  }
  function comparisonValueHtml(axis,value){
    if(!value)return '—';
    if(value.text_value!=null)return esc(value.text_value);
    if(value.number_value==null)return '—';
    const number=Number(value.number_value);
    if(axis.value_kind==='percent')return pct(number);
    if(axis.value_kind==='integer')return `${fmt(number,0)}${axis.unit?` ${esc(axis.unit)}`:''}`;
    return `${fmt(number,2)}${axis.unit?` ${esc(axis.unit)}`:''}`;
  }
  function comparisonSurfaceHtml({scopeKey,axes,candidates,emptyText,promptText,headingHtml,detailButtonHtml,blockerHtml}){
    if(!(axes||[]).length)return `<div class="empty-state">${esc(emptyText)}</div>`;
    const pins=comparisonPinnedKeys(scopeKey,candidates);
    if(pins.length<2)return `<div class="comparison-empty"><strong>${pins.length?`${pins.length}候補を選択中`:'比較候補を選択'}</strong><span>${esc(promptText)}</span></div>`;
    const pinned=pins.map((key)=>(candidates||[]).find((row)=>row.comparison_key===key)).filter(Boolean);
    const headers=pinned.map((row)=>`<div class="comparison-candidate-heading">${headingHtml(row)}${detailButtonHtml(row)}</div>`).join('');
    const rows=(axes||[]).map((axis)=>`<div class="comparison-axis-row ${axis.differs?'is-different':''}"><strong>${esc(axis.label)}</strong>${pinned.map((row)=>`<span>${comparisonValueHtml(axis,comparisonValue(row,axis.key))}</span>`).join('')}</div>`).join('');
    const blockerRows=pinned.map((row)=>`<div class="comparison-blocker-cell">${blockerHtml(row)}</div>`).join('');
    return `<div class="comparison-surface" style="--comparison-columns:${pinned.length}"><div class="comparison-heading-row"><div class="comparison-axis-heading">比較軸</div>${headers}</div>${rows}<div class="comparison-axis-row comparison-blocker-row"><strong>現在の制約</strong>${blockerRows}</div></div>`;
  }
  function surveyComparisonScope(campaign){return `survey:${campaign.id}`;}
  function surveyComparisonPinnedKeys(campaign){return comparisonPinnedKeys(surveyComparisonScope(campaign),campaign.candidates||[]);}
  function surveyComparisonHtml(campaign){
    return comparisonSurfaceHtml({
      scopeKey:surveyComparisonScope(campaign),
      axes:campaign.comparison_axes||[],
      candidates:campaign.candidates||[],
      emptyText:'現在の観測手段には、比較が必要な戦略差はありません。',
      promptText:'観測手段から2〜4候補を比較に追加すると、共通の比較軸で差を確認できます。',
      headingHtml:(row)=>`<strong>${esc(row.provider_display_name||'調査手段')}</strong><span>${esc(row.observation_mode_display_name||'観測方式')}</span><small>${esc(locationName(row.provider_operational_node_id))}</small>`,
      detailButtonHtml:(row)=>`<button type="button" data-survey-candidate-detail="${esc(campaign.id)}" data-comparison-key="${esc(row.comparison_key)}">詳細</button>`,
      blockerHtml:(row)=>(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">制約なし</span>',
    });
  }
  function foundationComparisonScope(){return `founding:${state.surfaceMap?.body_id||''}`;}
  function foundationComparisonCandidates(){
    return (state.surfaceMap?.cells||[]).filter((cell)=>!cell.developed).flatMap((cell)=>(cell.foundation_options||[]).map((option)=>({
      ...option,
      target_cell_id:cell.id,
      target_cell_name:surfaceCellLabel(cell.id),
    })));
  }
  function foundationComparisonCandidate(key){return foundationComparisonCandidates().find((row)=>row.comparison_key===key)||null;}
  function foundationComparisonPinnedKeys(){return comparisonPinnedKeys(foundationComparisonScope(),foundationComparisonCandidates());}
  function foundationComparisonHtml(){
    const candidates=foundationComparisonCandidates();
    return comparisonSurfaceHtml({
      scopeKey:foundationComparisonScope(),
      axes:state.surfaceMap?.founding_comparison_axes||[],
      candidates,
      emptyText:'現在の設立候補には、比較が必要な戦略差はありません。',
      promptText:'候補地点から2〜4候補を比較に追加すると、共通の比較軸と制約を並べて確認できます。',
      headingHtml:(row)=>`<strong>${esc(row.target_cell_name)}</strong><span>${esc(row.recipe_display_name)} · ${esc(row.vehicle_display_name)}</span><small>${esc(locationName(row.staging_node_id))} から出発</small>`,
      detailButtonHtml:(row)=>`<button type="button" data-founding-candidate-detail="${esc(row.comparison_key)}">詳細</button>`,
      blockerHtml:(row)=>(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">制約なし</span>',
    });
  }
  function buildOptionPrimaryEnable(row){
    const enables=[
      ...(row.process_options||[]).map(([,name])=>name),
      ...(row.capabilities||[]).map(capabilityName),
      ...(row.service_capacity_supplies||[]).map(([service])=>serviceName(service)),
    ];
    return enables[0]||'拠点能力を追加';
  }
  function constructionComparisonScope(){return `construction:${state.buildOptions?.operational_node_id||state.operationalNodeId||''}`;}
  function constructionComparisonCandidates(){return state.buildOptions?.items||[];}
  function constructionComparisonPinnedKeys(){return comparisonPinnedKeys(constructionComparisonScope(),constructionComparisonCandidates());}
  function constructionComparisonHtml(){
    const candidates=constructionComparisonCandidates();
    return comparisonSurfaceHtml({
      scopeKey:constructionComparisonScope(),
      axes:state.buildOptions?.comparison_axes||[],
      candidates,
      emptyText:'現在の建設候補には、比較が必要な戦略差はありません。',
      promptText:'建設候補から2〜4候補を比較に追加すると、必要工数・資源負担・追加機能の規模を共通軸で確認できます。',
      headingHtml:(row)=>`<strong>${esc(row.display_name)}</strong><span>${esc(buildOptionPrimaryEnable(row))}</span><small>${row.can_plan?'計画可能':'条件不足'}</small>`,
      detailButtonHtml:(row)=>`<button type="button" data-inspect="build-option" data-id="${esc(row.facility_definition_id)}">詳細</button>`,
      blockerHtml:(row)=>(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">制約なし</span>',
    });
  }
  function processComparisonScope(industry){return `process:${industry.facility_id}`;}
  function processComparisonHtml(industry){
    return comparisonSurfaceHtml({
      scopeKey:processComparisonScope(industry),
      axes:industry.process_comparison_axes||[],
      candidates:industry.process_options||[],
      emptyText:'現在の生産工程候補には、比較が必要な戦略差はありません。',
      promptText:'生産工程から2〜4候補を比較に追加すると、投入・産出・保管負荷と制約を共通軸で確認できます。',
      headingHtml:(row)=>`<strong>${esc(row.display_name||'生産工程')}</strong><small>${row.process_id===industry.process_id?'現在の工程':'切替候補'}</small>`,
      detailButtonHtml:()=>' ',
      blockerHtml:(row)=>(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">現在の制約なし</span>',
    });
  }
  function researchComparisonScope(research){return `research:${research.id}:${research.current_stage_id||''}:execution-context`;}
  function researchComparisonPinnedKeys(research){return comparisonPinnedKeys(researchComparisonScope(research),research.execution_context_options||[]);}
  function researchComparisonHtml(research){
    return comparisonSurfaceHtml({
      scopeKey:researchComparisonScope(research),
      axes:research.execution_context_comparison_axes||[],
      candidates:research.execution_context_options||[],
      emptyText:'現在の研究実行候補には、比較が必要な戦略差はありません。',
      promptText:'実行地点から2〜4候補を比較に追加すると、Fleet拘束・Resource・Service供給・所要時間を共通の比較軸で確認できます。',
      headingHtml:(row)=>`<strong>${esc(researchSiteLabel(row))}</strong><small>${row.can_select?'選択可能':'条件未達'}</small>`,
      detailButtonHtml:()=>'',
      blockerHtml:(row)=>(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">制約なし</span>',
    });
  }
  const surveyIntentPreviewSerial=new Map();
  const surveyIntentPreviewCache=new Map();
  const surveyIntentPreviewPending=new Map();
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
      : `<div class="issue-stack">${(result.blockers||[]).map((blocker)=>issueHtml(blocker)).join('')}</div>`;
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
      let pending=surveyIntentPreviewPending.get(signature);
      if(!pending){
        pending=api(`/api/v1/survey-campaign-intent-preview?${params.toString()}`)
          .finally(()=>surveyIntentPreviewPending.delete(signature));
        surveyIntentPreviewPending.set(signature,pending);
      }
      const result=await pending;
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
    const caps=(requirements?.capabilities||[]).map((row)=>`<div class="cell-sub">${row.required_state==='ACTIVE'?'稼働':'設置'}能力: ${esc(capabilityName(row.capability_id))}</div>`).join('');
    return spatial+env+caps||'<div class="cell-sub">追加条件なし</div>';
  };
  function constructionPlanControls(prefix,{draftScope=prefix,policyOptions=[],selectedPolicy='standard_wait',disabled=false}={}){
    const policyRows=(policyOptions||[]).map((value)=>`<option value="${esc(value)}" ${value===selectedPolicy?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const disabledAttr=disabled?'disabled':'';
    const draftAttrs=`data-structured-draft data-draft-scope="${esc(draftScope)}"`;
    return `<div class="form-row">${priorityControl(3,`id="${prefix}PriorityInput" data-draft-key="${esc(draftScope)}:priority" ${draftAttrs}`,'優先度',disabled)}<label>調達方針<select id="${prefix}ProcurementTimingPolicy" data-draft-key="${esc(draftScope)}:procurement" ${draftAttrs} ${disabledAttr}>${policyRows}</select></label></div>`;
  }

  const projectTargetLabel=(p)=>{
    if(p.target_kind==='facility_upgrade')return `設備更新 → Lv ${fmt(p.target_level,0)}`;
    if(p.target_kind==='facility_decommission')return '設備撤去';
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
  const environmentHtml=(rows)=>(rows||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(row.key)}</span></div>${(row.values||[]).map(([key,value])=>`<div class="cell-sub">${esc(key)}: ${esc(environmentValue(value))}</div>`).join('')}</div>`).join('')||'<div class="empty-state">環境情報なし</div>';
  const surfaceResourcesHtml=(rows,cellId=null)=>(rows||[]).map((row)=>{
    const surveyId=cellId==null?null:`${cellId}::${row.resource_id}`;
    const survey=(state.surveys?.items||[]).find((item)=>`${item.cell_id}::${item.resource_id}`===surveyId);
    const action=survey?`<div class="action-row" style="margin-top:8px"><button type="button" data-inspect="survey" data-id="${esc(surveyId)}">調査詳細・操作</button></div>`:'';
    return `<div class="detail-card"><div class="mode-title"><span>${esc(row.resource_name||resourceName(row.resource_id))}</span><span>調査知識 Lv ${row.knowledge_level}</span></div><div class="cell-sub">存在確率 ${row.presence_probability==null?'—':pct(row.presence_probability)} · 資源ポテンシャル ${row.visible_potential==null?'未確定':fmt(row.visible_potential,3)}${row.visible_potential_precision_fraction==null?'':row.visible_potential_precision_fraction<=0?' · 測定済み':` · ±${pct(row.visible_potential_precision_fraction)}`}</div>${action}</div>`;
  }).join('')||'<div class="empty-state">公開済み資源情報なし</div>';
  const tupleResourcesHtml=(rows)=>(rows||[]).map(([resourceId,amount])=>`<div class="cell-sub">${esc(resourceName(resourceId))}: ${fmt(amount,2)} t</div>`).join('')||'<div class="cell-sub">追加資源なし</div>';
  function surfacePlanControls(scope,option,disabled=false){
    const policy=(option.procurement_policy_options||[]).map((value)=>`<option value="${esc(value)}" ${value==='standard_wait'?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const d=disabled?'disabled':'';
    const draftAttrs=`data-structured-draft data-draft-scope="${esc(scope)}"`;
    return `<div class="form-row surface-plan-controls">${priorityControl(3,`data-surface-plan-priority data-draft-key="${esc(scope)}:priority" ${draftAttrs}`,'優先度',disabled)}<label>調達方針<select data-surface-plan-policy data-draft-key="${esc(scope)}:procurement" ${draftAttrs} ${d}>${policy}</select></label></div>`;
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
    return `<div class="form-row">${priorityControl(3,`data-founding-priority data-draft-key="${esc(scope)}:priority" data-structured-draft data-draft-scope="${esc(scope)}"`,'優先度',disabled)}</div>`;
  };

  function renderOverviewTab(){
    const loc=state.operationalNode,flow=state.flow,issues=state.bottlenecks?.items||[];
    const blockerText=(row)=>A.constraintSummary(row);
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
    const dependencyRows=(currentAnalytics?.current_resources||[]).filter((row)=>criticalIds.has(row.id)).map((row)=>`<button type="button" class="overview-dependency" data-inspect="dependency-resource" data-id="${esc(row.id)}"><strong>${esc(row.display_name)}</strong><span>外部依存 ${fmt(row.external_dependency_per_day,2)} /日</span><span>未充足 ${fmt(row.unmet_demand_t,2)} t</span></button>`).join('')||'<div class="empty-state compact-empty">重大な外部依存はありません。</div>';

    const infra=loc.surface_infrastructure;
    const infraCard=infra?`<section class="decision-card"><div class="decision-card-heading"><div><span class="eyebrow">地表</span><h3>地表インフラ</h3></div><span class="badge ${infra.fulfillment<0.999999?'warn':'ok'}">${pct(infra.fulfillment)}</span></div><div class="capacity-quad"><div><span>基準能力</span><strong>${fmt(infra.nominal_capacity,2)}</strong></div><div><span>利用可能</span><strong>${fmt(infra.available_capacity,2)}</strong></div><div><span>需要</span><strong>${fmt(infra.requested_capacity,2)}</strong></div><div><span>余力</span><strong>${fmt(infra.spare_capacity,2)}</strong></div></div>${(infra.limiting_factors||[]).length?`<div class="issue-stack compact-issues">${infra.limiting_factors.map((factor)=>`<div class="issue"><div class="issue-title">${esc(blockerText(factor))}</div></div>`).join('')}</div>`:''}</section>`:'';

    return `<div class="location-overview-board">
      <section class="decision-card attention-decision-card"><div class="decision-card-heading"><div><span class="eyebrow">判断</span><h3>現在の判断</h3></div><span class="badge ${issues.length?'warn':'ok'}">${issues.length} 件</span></div><div class="issue-stack overview-issues">${issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state compact-empty">現在、この拠点で判断を必要とする制約はありません。</div>'}</div></section>
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
    const blockerText=(row)=>A.constraintSummary(row);
    const cards=(state.operationalNode?.facilities||[]).map((facility)=>{
      const industry=industryByFacility[facility.id],extraction=extractionByFacility[facility.id];
      const primary=industry?.process_display_name||(extraction?`${resourceName(extraction.resource_id)}採掘`:(facility.capabilities||[]).map(capabilityName)[0])||'生産工程';
      const blockers=facility.operating_blockers||facility.activation_blockers||[];
      const mainBlocker=blockers.length?blockerText(blockers[0]):'';
      const utilization=Math.max(0,Math.min(1,Number(facility.operational_utilization||0)));
      const selected=state.inspector?.type==='facility'&&state.inspector.id===facility.id;
      return `<button type="button" class="facility-card ${selected?'is-selected':''}" data-inspect="facility" data-id="${esc(facility.id)}" aria-pressed="${selected?'true':'false'}"><span class="facility-card-heading"><span><strong>${esc(facility.display_name)}</strong><small>Lv ${fmt(facility.level,0)} · ${esc(primary)}</small></span><span class="badge ${facility.paused||blockers.length?'warn':'ok'}">${facility.paused?'停止':'稼働'}</span></span><span class="facility-utilization"><span><span>実効稼働</span><strong>${pct(utilization)}</strong></span><span class="progress-track"><span class="progress-bar" style="width:${utilization*100}%"></span></span></span><span class="facility-card-metrics"><span>維持 ${pct(facility.maintenance_satisfaction)}</span><span>活動優先 ${esc(priorityName(facility.activity_priority))}</span></span><span class="facility-card-blocker ${mainBlocker?'has-warning':''}">${mainBlocker?`制約: ${esc(mainBlocker)}`:'主要な制約なし'}</span></button>`;
    }).join('');
    return `<section class="facility-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">設備一覧</span><h2>設備</h2><p>稼働率と制約を比較し、対象を選択すると右の詳細パネルで入出力・維持・操作を確認できます。</p></div><span class="badge">${state.operationalNode?.facilities?.length||0} 設備</span></div><div class="facility-card-grid">${cards||'<div class="empty-state">設備なし</div>'}</div></section>`;
  }

  function detailedForecastHtml(){
    const currentNode=state.operationalNodeId;
    const forecast=detailedForecast&&(detailedForecast.node_ids||[]).includes(currentNode)?detailedForecast:null;
    const horizonButtons=[['SHORT_TERM','短期'],['MEDIUM_TERM','中期'],['STEADY_STATE','長期均衡']].map(([value,label])=>`<button type="button" data-detailed-forecast-horizon="${value}" class="${detailedForecastHorizon===value?'is-active':''}" aria-pressed="${detailedForecastHorizon===value?'true':'false'}">${label}</button>`).join('');
    const controls=`<div class="detailed-forecast-controls"><div class="segmented-control" role="group" aria-label="詳細予測の期間">${horizonButtons}</div><button type="button" class="primary" data-run-detailed-forecast ${detailedForecastLoading?'disabled':''}>${detailedForecastLoading?'予測中':'詳細予測を実行'}</button></div>`;
    if(!forecast)return `${controls}<div class="empty-state">広域予測は明示実行時だけ計算します。将来在庫、波及影響、複数区間の物流影響を短時間の操作プレビューから分離して確認できます。</div>`;
    const steadyLabels={stable:'収束/均衡',accumulating:'蓄積傾向',depleting:'枯渇傾向'};
    const inventory=(forecast.inventory||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(row.display_name||resourceName(row.resource_id))}</span><span class="badge">${esc(steadyLabels[row.steady_state]||A.userFacingText(row.steady_state))}</span></div><div class="dependency-metrics"><span><small>現在</small><strong>${fmt(row.current_amount,2)} ${esc(row.unit)}</strong></span><span><small>予測</small><strong>${fmt(row.projected_amount,2)} ${esc(row.unit)}</strong></span><span><small>変化</small><strong>${signed(row.delta_amount)} ${esc(row.unit)}</strong></span><span><small>生産</small><strong>${fmt(row.projected_production_per_day,2)}/日</strong></span><span><small>消費</small><strong>${fmt(row.projected_consumption_per_day,2)}/日</strong></span><span><small>外部依存</small><strong>${fmt(row.projected_external_dependency_per_day,2)}/日</strong></span></div></div>`).join('')||'<div class="empty-state">この予測期間で変化する在庫はありません。</div>';
    const impacts=(forecast.downstream_impacts||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(row.display_name)}</span><span class="badge">${esc(A.userFacingText(row.kind))}</span></div><div class="cell-sub">${esc(A.userFacingText(row.current_state))} → ${esc(A.userFacingText(row.projected_state))}</div></div>`).join('')||'<div class="empty-state">この予測期間で主要な案件・研究状態遷移はありません。</div>';
    const logistics=(forecast.logistics_impacts||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(row.resource_id))} → ${esc(locationName(row.destination_id))}</span><span class="badge ${row.remaining_t>1e-9?'warn':'ok'}">中継 ${fmt(row.handoff_count,0)} 回</span></div><div class="cell-sub">供給元 ${esc(row.source_id?locationName(row.source_id):'未確定')} · ${esc((row.service_ids||[]).map(serviceName).join(' → ')||'経路未確定')}</div><div class="cell-sub">予測到着 ${row.projected_arrival_day==null?'未確定':`Day ${fmt(row.projected_arrival_day,0)}`} · 輸送中 ${fmt(row.pipeline_t,2)} t · 残 ${fmt(row.remaining_t,2)} t</div></div>`).join('')||'<div class="empty-state">この予測期間で広域物流への影響はありません。</div>';
    return `${controls}<div class="cell-sub">基準 Day ${fmt(forecast.base_day,0)} → Day ${fmt(forecast.projected_day,0)} · 予測期間 ${fmt(forecast.period_days,0)}日</div><h3>将来在庫 / 長期傾向</h3><div class="dependency-card-grid">${inventory}</div><h3>波及影響</h3><div class="dependency-card-grid">${impacts}</div><h3>広域物流への影響</h3><div class="dependency-card-grid">${logistics}</div>`;
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
    const currentCriticalServices=new Set(currentAnalytics?.critical_dependency_service_types||[]);
    const forecastCriticalServices=new Set(forecastAnalytics?.critical_dependency_service_types||[]);
    const dependencyCards=(dependencyView==='current'?(currentAnalytics?.current_resources||[]):(forecastAnalytics?.forecast_resources||[])).map((r)=>{
      const isCurrent=dependencyView==='current';
      const critical=(isCurrent?currentCritical:forecastCritical).has(r.id);
      const sources=(r.dependency_source_node_ids||[]).map(locationName).join(' / ')||'依存元なし';
      const limits=(r.limiting_factors||[]).map(A.constraintSummary);
      const metrics=isCurrent
        ? `<span><small>生産</small><strong>${fmt(r.production_per_day,2)} /日</strong></span><span><small>消費</small><strong>${fmt(r.consumption_per_day,2)} /日</strong></span><span><small>外部依存</small><strong>${fmt(r.external_dependency_per_day,2)} /日</strong></span><span><small>流入中</small><strong>${fmt(r.imports_pipeline_t,2)} t</strong></span><span><small>未充足</small><strong>${fmt(r.unmet_demand_t,2)} t</strong></span>`
        : `<span><small>計画需要</small><strong>${fmt(r.planned_requirement_t,2)} t</strong></span><span><small>継続消費</small><strong>${fmt(r.recurring_consumption_per_day,2)} /日</strong></span><span><small>外部必要量</small><strong>${fmt(r.external_requirement_t,2)} t</strong></span><span><small>外部依存</small><strong>${fmt(r.external_recurring_dependency_per_day,2)} /日</strong></span><span><small>追加備蓄</small><strong>${fmt(r.target_stock_t,2)} t</strong></span>`;
      const timing=!isCurrent&&r.earliest_requirement_day!=null?`最早必要 Day ${fmt(r.earliest_requirement_day,0)}`:'';
      return `<button type="button" class="dependency-card ${critical?'has-warning':''}" data-inspect="dependency-resource" data-id="${esc(r.id)}"><span class="decision-card-title"><span><strong>${esc(r.display_name)}</strong><small>${esc(sources)}</small></span><span class="badge ${critical?'warn':'ok'}">${critical?'要対処':'安定'}</span></span><span class="dependency-metrics">${metrics}</span><span class="decision-card-footer ${limits.length?'has-warning':''}">${esc(limits[0]||timing||'主要な制約なし')}${timing&&limits.length?` · ${esc(timing)}`:''}</span></button>`;
    }).join('');
    const serviceRows=dependencyView==='current'?(currentAnalytics?.current_services||[]):(forecastAnalytics?.forecast_services||[]);
    const serviceCards=serviceRows.map((r)=>{
      const isCurrent=dependencyView==='current';
      const critical=(isCurrent?currentCriticalServices:forecastCriticalServices).has(r.service_type);
      const scope=r.scope==='ORGANIZATION'?'組織共有':'拠点内';
      const limits=(r.limiting_factors||[]).map(A.constraintSummary);
      const metrics=isCurrent
        ? `<span><small>利用可能</small><strong>${fmt(r.local_enabled_rate,2)} /日</strong></span><span><small>需要</small><strong>${fmt(r.requested_rate,2)} /日</strong></span><span><small>実使用</small><strong>${fmt(r.allocated_rate,2)} /日</strong></span><span><small>能力不足</small><strong>${fmt(r.unmet_rate,2)} /日</strong></span><span><small>範囲外依存</small><strong>${fmt(r.external_dependency_rate,2)} /日</strong></span>`
        : `<span><small>計画要求</small><strong>${fmt(r.planned_requirement,2)}</strong></span><span><small>現在能力</small><strong>${fmt(r.local_enabled_rate,2)} /日</strong></span><span><small>範囲外能力</small><strong>${fmt(r.outside_scope_enabled_rate,2)} /日</strong></span><span><small>必要時期</small><strong>${r.earliest_requirement_day==null?'未確定':`Day ${fmt(r.earliest_requirement_day,0)}`}</strong></span>`;
      return `<button type="button" class="dependency-card ${critical?'has-warning':''}" data-inspect="dependency-service" data-id="${esc(r.service_type)}"><span class="decision-card-title"><span><strong>${esc(serviceName(r.service_type))}</strong><small>${esc(scope)}</small></span><span class="badge ${critical?'warn':'ok'}">${critical?'要対処':'安定'}</span></span><span class="dependency-metrics">${metrics}</span><span class="decision-card-footer ${limits.length?'has-warning':''}">${esc(limits[0]||'主要な制約なし')}</span></button>`;
    }).join('');
    const groupRows=dependencyView==='current'?(currentAnalytics?.current_resource_groups||[]):(forecastAnalytics?.forecast_resource_groups||[]);
    const groupCards=groupRows.map((r)=>dependencyView==='current'
      ? `<div class="dependency-group-card"><strong>${esc(r.display_name)}</strong><span>生産 ${fmt(r.production_per_day,2)} /日</span><span>消費 ${fmt(r.consumption_per_day,2)} /日</span><span>外部依存 ${fmt(r.external_dependency_per_day,2)} /日</span><span>未充足 ${fmt(r.unmet_demand_t,2)} t</span></div>`
      : `<div class="dependency-group-card"><strong>${esc(r.display_name)}</strong><span>計画需要 ${fmt(r.planned_requirement_t,2)} t</span><span>外部必要量 ${fmt(r.external_requirement_t,2)} t</span><span>継続外部依存 ${fmt(r.external_recurring_dependency_per_day,2)} /日</span><span>${r.earliest_requirement_day==null?'必要日未定':`最早 Day ${fmt(r.earliest_requirement_day,0)}`}</span></div>`).join('');

    const criticalResourceCount=dependencyView==='current'?currentCritical.size:forecastCritical.size;
    const criticalServiceCount=dependencyView==='current'?currentCriticalServices.size:forecastCriticalServices.size;
    return `<div class="inventory-decision-surface">
      <section class="decision-surface-block"><div class="decision-surface-heading"><div><span class="eyebrow">資源</span><h2>在庫とフロー</h2><p>現在量・利用可能量・入出荷を比較し、資源を選択すると右の詳細パネルで供給源と制約を確認できます。</p></div><span class="badge">${state.operationalNode?.inventory?.length||0} 資源</span></div><div class="resource-flow-grid">${inventoryCards||'<div class="empty-state">表示対象の資源はありません。</div>'}</div></section>
      <section class="decision-surface-block"><div class="decision-card-heading"><div><span class="eyebrow">配分</span><h3>現在の資源配分</h3></div><span class="badge ${allocations.some((c)=>Number(c.unmet||0)>1e-9)?'warn':'ok'}">${allocations.length} 件</span></div><div class="resource-allocation-grid">${allocationCards||'<div class="empty-state compact-empty">現在の資源配分はありません。</div>'}</div></section>
      <section class="decision-surface-block dependency-surface"><div class="decision-surface-heading"><div><span class="eyebrow">依存分析</span><h2>外部依存</h2><p>現在の不足と、計画済み案件から生じる将来需要を切り替えて確認します。</p></div><div class="segmented-control dependency-mode-switch" role="group" aria-label="外部依存の表示"><button type="button" data-dependency-view="current" class="${dependencyView==='current'?'is-active':''}" aria-pressed="${dependencyView==='current'?'true':'false'}">現在</button><button type="button" data-dependency-view="forecast" class="${dependencyView==='forecast'?'is-active':''}" aria-pressed="${dependencyView==='forecast'?'true':'false'}">予測</button></div></div><div class="dependency-status-row"><span class="badge ${criticalResourceCount||criticalServiceCount?'warn':'ok'}">要対処 ${criticalResourceCount} 資源 · ${criticalServiceCount} サービス</span><span class="cell-sub">${dependencyView==='current'?'実際の生産・消費・物流状態':'計画済み需要・備蓄目標・必要時期'}</span></div><h3>資源依存</h3><div class="dependency-card-grid">${dependencyCards||'<div class="empty-state">資源外部依存の対象はありません。</div>'}</div>${groupCards?`<details class="dependency-group-details"><summary>資源グループ集計</summary><div class="dependency-group-grid">${groupCards}</div></details>`:''}<h3>サービス依存</h3><div class="dependency-card-grid">${serviceCards||'<div class="empty-state">サービス依存の対象はありません。</div>'}</div></section>
      <section class="decision-surface-block detailed-forecast-surface"><div class="decision-surface-heading"><div><span class="eyebrow">広域予測</span><h2>詳細予測</h2><p>将来在庫・波及影響・複数区間の物流影響・長期傾向を、現在/計画依存分析とは別契約で計算します。</p></div></div>${detailedForecastHtml()}</section>
    </div>`;
  }

  function planningOptionState(option, readyLabel='計画可'){
    const blockers=option?.blockers||[];
    const canPlan=Boolean(option?.can_plan);
    const label=canPlan
      ? (blockers.length?`計画可 · ${blockers.length} 制約`:readyLabel)
      : (blockers.length?`計画不可 · ${blockers.length} 制約`:'計画不可');
    return {blockers,canPlan,disabled:!canPlan,label};
  }

  function renderConstructionTab(){
    const projects=state.projects?.items||[],options=state.buildOptions?.items||[];
    const projectCards=projects.map((p)=>{
      const selected=state.inspector?.type==='project'&&state.inspector.id===p.id;
      const blockers=p.blockers||[];
      const done=p.progress??p.construction_done??0;
      const required=p.construction_required??0;
      return `<button type="button" class="construction-project-card ${selected?'is-selected':''}" data-inspect="project" data-id="${esc(p.id)}" aria-pressed="${selected?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(p.display_name||p.facility_display_name||'建設案件')}</strong><small>${esc(projectTargetLabel(p))}</small></span><span class="badge ${blockers.length?'warn':p.paused?'':'ok'}">${esc(stateLabels[p.status]||p.status||(p.paused?'停止':'進行中'))}</span></span><span class="construction-progress"><span><small>進捗</small><strong>${fmt(done,1)} / ${fmt(required,1)}</strong></span><span><small>優先度</small><strong>${esc(priorityName(p.priority))}</strong></span><span><small>調達</small><strong>${esc(procurementPolicyName(p.procurement_policy))}</strong></span></span><span class="decision-card-footer ${blockers.length?'has-warning':''}">${blockers.length?`制約: ${esc(A.constraintSummary(blockers[0]))}`:'主要な制約なし'}</span></button>`;
    }).join('');
    const optionCards=options.map((o)=>{
      const plan=planningOptionState(o,'建設可');
      const selected=state.inspector?.type==='build-option'&&state.inspector.id===o.facility_definition_id;
      const resources=(o.resources||[]).slice(0,3).map((r)=>`${resourceName(r.resource_id)} ${fmt(r.required_t,1)} t`).join(' · ');
      const primaryEnable=buildOptionPrimaryEnable(o);
      const readiness=o.projected_material_readiness_day==null?'未確定':Number(o.projected_material_readiness_day)<=Number(state.world?.day??state.session?.day??0)?'準備済み':`Day ${fmt(o.projected_material_readiness_day,0)}`;
      return `<button type="button" class="construction-option-card ${selected?'is-selected':''}" data-inspect="build-option" data-id="${esc(o.facility_definition_id)}" aria-pressed="${selected?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(o.display_name)}</strong><small>利用可能になる機能: ${esc(primaryEnable)}</small></span><span class="badge ${plan.blockers.length?'warn':plan.canPlan?'ok':''}">${esc(plan.canPlan?'計画可能':'条件不足')}</span></span><span class="construction-option-metrics"><span><small>必要工数</small><strong>${fmt(o.construction_required,0)}</strong></span><span><small>資材準備見込み</small><strong>${esc(readiness)}</strong></span><span><small>状態</small><strong>${esc(plan.label)}</strong></span></span><span class="decision-card-footer ${plan.blockers.length?'has-warning':''}">${plan.blockers.length?`制約: ${esc(A.constraintSummary(plan.blockers[0]))}`:esc(resources||'追加建設資源なし')}</span></button>`;
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
        <span class="decision-card-footer ${blocked?'has-warning':''}">${blocked?`制約 ${blocked}件 · 詳細を確認`:'重大な制約なし'}</span>
      </button>`;
    }).join('');
    return `<div class="exploration-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">科学探査</span><h2>科学探査案件</h2><p>候補を選び、右側で実行条件・Fleet拘束・往復移動・RP受入を確認します。輸送とのFleet競合も同じ判断画面で扱います。</p></div><span class="badge">${items.length} 件</span></div><div class="exploration-card-grid">${cards||'<div class="empty-state">現在利用できる科学探査案件はありません。</div>'}</div></div>`;
  }

  function renderSurveyTab(){
    const locationSummary=(state.world?.operational_nodes||[]).find((row)=>row.id===state.operationalNodeId);
    const expectedBodyId=locationSummary?.body_id||null;
    if(expectedBodyId&&state.surfaceMap?.body_id!==expectedBodyId){
      return `<section class="card survey-loading-card"><div class="card-heading"><div><h3>地表調査</h3><div class="cell-sub">${esc(locationSummary?.display_name||locationName(state.operationalNodeId))} に対応する地表情報を取得しています。</div></div><span class="badge">読込中</span></div><div class="empty-state">対象天体のSurface Mapが確定するまで調査範囲は編集できません。</div></section>`;
    }
    const providerFleet=state.surveys?.provider_fleet||[];
    const knowledge=state.surveys?.items||[];
    const visibleKnowledge=state.surfaceMap?.body_id?knowledge.filter((row)=>row.body_id===state.surfaceMap.body_id):knowledge;
    const cellMap=new Map();visibleKnowledge.forEach((row)=>cellMap.set(row.cell_id,row.cell_label));
    const resourceMap=new Map();visibleKnowledge.forEach((row)=>resourceMap.set(row.resource_id,row.resource_name));
    const cells=(state.surfaceMap?.cells||[]).filter((cell)=>cellMap.has(cell.id));
    const mapCellIds=new Set(cells.map((cell)=>cell.id));
    const fallbackCells=[...cellMap].filter(([id])=>!mapCellIds.has(id));
    const goalLabel=(level)=>({1:'存在確認',2:'埋蔵量推定',3:'精密測定'}[Number(level)]||`調査知識 ${fmt(level,0)}`);

    let scopeMap='';
    if(cells.length){
      const minLon=Math.min(...cells.map((c)=>Number(c.longitude_deg))),maxLon=Math.max(...cells.map((c)=>Number(c.longitude_deg)));
      const minLat=Math.min(...cells.map((c)=>Number(c.latitude_deg))),maxLat=Math.max(...cells.map((c)=>Number(c.latitude_deg)));
      const lonSpan=Math.max(1,maxLon-minLon),latSpan=Math.max(1,maxLat-minLat);
      const pos=Object.fromEntries(cells.map((c)=>[c.id,{x:8+84*(Number(c.longitude_deg)-minLon)/lonSpan,y:8+84*(maxLat-Number(c.latitude_deg))/latSpan}]));
      const seen=new Set(),lines=[];
      for(const cell of cells){for(const neighbor of cell.neighbor_ids||[]){if(!pos[neighbor])continue;const key=[cell.id,neighbor].sort().join('::');if(seen.has(key))continue;seen.add(key);lines.push(`<line x1="${pos[cell.id].x*10}" y1="${pos[cell.id].y*4.2}" x2="${pos[neighbor].x*10}" y2="${pos[neighbor].y*4.2}"></line>`);}}
      const knowledgeByCell=new Map();
      for(const row of visibleKnowledge){if(!knowledgeByCell.has(row.cell_id))knowledgeByCell.set(row.cell_id,[]);knowledgeByCell.get(row.cell_id).push(row);}
      const nodes=cells.map((cell)=>{const layers=surveyLayerSummary(cell,knowledgeByCell.get(cell.id)||[]);return `<label class="survey-scope-node" style="left:${pos[cell.id].x}%;top:${pos[cell.id].y}%"><input type="checkbox" data-survey-draft-cell data-draft-key="survey:new:cell:${esc(cell.id)}" data-structured-draft data-draft-scope="survey:new" value="${esc(cell.id)}"><span><strong>${esc(cellMap.get(cell.id)||cell.display_name||'地域')}</strong>${Object.entries(layers).map(([layer,value])=>`<small data-survey-layer-value="${esc(layer)}">${esc(value)}</small>`).join('')}</span></label>`;}).join('');
      const layerButtons=Object.entries(surveyLayerNames).map(([key,label])=>`<button type="button" class="survey-layer-button ${surveyMapLayer===key?'is-active':''}" data-survey-map-layer="${esc(key)}" aria-pressed="${surveyMapLayer===key?'true':'false'}">${esc(label)}</button>`).join('');
      scopeMap=`<div class="survey-layer-toolbar" role="group" aria-label="地表Map表示Layer">${layerButtons}</div><div class="survey-scope-map" data-survey-layer="${esc(surveyMapLayer)}"><svg viewBox="0 0 1000 420" preserveAspectRatio="none" aria-hidden="true">${lines.join('')}</svg>${nodes}</div>`;
    }
    const fallbackHtml=fallbackCells.map(([id,label])=>`<label class="survey-resource-choice"><input type="checkbox" data-survey-draft-cell data-draft-key="survey:new:cell:${esc(id)}" data-structured-draft data-draft-scope="survey:new" value="${esc(id)}"><span>${esc(label)}</span></label>`).join('');
    const resourceChoices=[...resourceMap].map(([id,label])=>`<label class="survey-resource-choice"><input type="checkbox" data-survey-draft-resource data-draft-key="survey:new:resource:${esc(id)}" data-structured-draft data-draft-scope="survey:new" value="${esc(id)}"><span>${esc(label)}</span></label>`).join('');
    const draftSignature=A.stableUiSignature({
      body_id:state.surfaceMap?.body_id||null,
      cells:cells.map((cell)=>({
        id:cell.id,
        environment:(cell.environment||[]).map((row)=>[row.key,row.value]),
        location_id:cell.location_id||null,
        developed:Boolean(cell.developed),
        is_location_core:Boolean(cell.is_location_core),
        movement_accessible:cell.movement_accessible,
        minimum_transit_days:cell.minimum_transit_days,
      })),
      knowledge:visibleKnowledge.map((row)=>({
        cell_id:row.cell_id,
        resource_id:row.resource_id,
        knowledge_level:row.knowledge_level,
        visible_potential:row.visible_potential,
        visible_potential_precision_fraction:row.visible_potential_precision_fraction,
      })),
    });
    const createSection=`<section class="survey-decision-card" data-survey-draft-surface data-survey-draft-signature="${esc(draftSignature)}"><div class="decision-card-heading"><div><span class="eyebrow">調査範囲</span><h3>調査範囲を地表から選択</h3></div><span class="badge">${cellMap.size} 地域 · ${resourceMap.size} 資源</span></div><div class="survey-decision-body"><div class="survey-map-column">${scopeMap||'<div class="empty-state">現在の選択範囲に地表位置情報はありません。</div>'}${fallbackHtml?`<div class="survey-fallback-cells">${fallbackHtml}</div>`:''}</div><div class="survey-intent-column"><div><h4>対象資源</h4><div class="survey-resource-choices">${resourceChoices||'<div class="empty-state">対象資源なし</div>'}</div></div><div class="form-row survey-goal-row"><label>調査目標<select id="surveyDraftGoal" data-draft-key="survey:new:goal" data-structured-draft data-draft-scope="survey:new"><option value="1">1 存在確認</option><option value="2">2 埋蔵量推定</option><option value="3">3 精密測定</option></select></label>${priorityControl(3,'id="surveyDraftPriority" data-draft-key="survey:new:priority" data-structured-draft data-draft-scope="survey:new"','活動優先度')}</div><div data-survey-start-intent-status><span class="badge">可否確認中</span></div><button type="button" class="primary survey-start-button" data-start-survey-campaign disabled>この条件で地表調査を開始</button><div class="cell-sub">観測手段と観測方式は自動選択し、戦略差がある場合だけ調査詳細で候補差を提示します。</div></div></div></section>`;

    const campaigns=(state.surveys?.campaigns||[]).map((c)=>{
      const provider=c.projected_provider_definition_id?`${c.projected_provider_display_name||'調査手段'} / ${c.projected_observation_mode_display_name||'—'}`:'未解決';
      const fleet=c.required_fleet_units==null?'—':`${fmt(c.assigned_fleet_units,0)} / 必要 ${fmt(c.required_fleet_units,0)}`;
      const eta=c.projected_remaining_days==null?'—':`${fmt(c.projected_remaining_days,1)}日`;
      const total=Number(c.covered_targets||0)+Number(c.remaining_targets||0);
      const completion=total>0?Math.min(1,Number(c.covered_targets||0)/total):0;
      const blocked=(c.blockers||[]).length;
      return `<button type="button" class="survey-campaign-card ${state.inspector?.type==='survey-campaign'&&state.inspector.id===c.id?'is-selected':''}" data-inspect="survey-campaign" data-id="${esc(c.id)}" aria-pressed="${state.inspector?.type==='survey-campaign'&&state.inspector.id===c.id?'true':'false'}"><span class="decision-card-title"><span><strong>${esc(goalLabel(c.goal_knowledge_level))}</strong><small>${c.target_cell_ids.length} 地域 × ${c.resource_ids.length} 資源</small></span><span class="badge ${blocked?'warn':''}">${esc(stateLabels[c.status]||c.status)}</span></span><span class="exploration-progress"><span>調査済み ${fmt(c.covered_targets,0)}/${fmt(total,0)}</span><span class="progress-track"><span class="progress-bar" style="width:${completion*100}%"></span></span></span><span class="decision-card-metrics"><span>解決手段 <strong>${esc(provider)}</strong></span><span>Fleet <strong>${esc(fleet)}</strong></span></span><span class="decision-card-metrics"><span>調査能力 <strong>${fmt(c.capacity_points_per_day,2)}/日</strong></span><span>予測残り <strong>${esc(eta)}</strong></span><span>優先度 <strong>${esc(priorityName(c.priority??3))}</strong></span></span><span class="decision-card-footer ${blocked?'has-warning':''}">${blocked?`制約 ${blocked}件 · 詳細を確認`:'重大な制約なし'}</span></button>`;
    }).join('');
    const campaignSection=`<section class="card"><div class="card-heading"><div><h3>進行中の地表調査</h3><div class="cell-sub">地表調査を選択すると右側で調査範囲、観測手段候補、Fleet、優先度、制約を編集できます。</div></div><span class="badge">${(state.surveys?.campaigns||[]).length}</span></div><div class="card-body"><div class="survey-campaign-grid">${campaigns||'<div class="empty-state">進行中の地表調査なし</div>'}</div></div></section>`;

    const knowledgeCards=visibleKnowledge.map((s)=>{const potential=s.visible_potential==null?'未確定':fmt(s.visible_potential,3),precision=s.visible_potential_precision_fraction==null?'':s.visible_potential_precision_fraction<=0?'測定済み':`精度 ±${pct(s.visible_potential_precision_fraction)}`;return `<button type="button" class="survey-knowledge-card ${state.inspector?.type==='survey'&&state.inspector.id===`${s.cell_id}::${s.resource_id}`?'is-selected':''}" data-inspect="survey" data-id="${esc(`${s.cell_id}::${s.resource_id}`)}"><span class="decision-card-title"><span><strong>${esc(s.resource_name)}</strong><small>${esc(s.cell_label)}</small></span><span class="badge">調査知識 ${fmt(s.knowledge_level,0)}</span></span><span class="decision-card-metrics"><span>進捗 <strong>${fmt(s.progress,2)}</strong></span><span>存在確率 <strong>${s.presence_probability==null?'—':pct(s.presence_probability)}</strong></span><span>推定量 <strong>${esc(potential)}</strong></span></span><span class="cell-sub">${esc(precision||'追加調査で精度向上')}</span></button>`;}).join('');
    const knowledgeSection=`<section class="card"><div class="card-heading"><div><h3>判明済みの地表知識</h3><div class="cell-sub">Surveyの進行状態とは独立した、現在の調査知識です。</div></div><span class="badge">${visibleKnowledge.length}</span></div><div class="card-body"><div class="survey-knowledge-grid">${knowledgeCards||'<div class="empty-state">この天体に調査対象なし</div>'}</div></div></section>`;

    const providerCards=providerFleet.map((row)=>`<div class="detail-card" data-survey-provider-fleet-card><div class="mode-title"><span>${esc(row.provider_display_name||'調査手段')}</span><span>配備 ${fmt(row.committed_units,0)} · 空き ${fmt(row.free_units,0)}</span></div><div class="cell-sub">${esc(locationName(row.operational_node_id))} · ${esc(definitionName(row.vehicle_definition_id))} · 調査能力 ${fmt(row.capacity_units_per_day,2)}/日</div>${(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(b)).join('')}</div>`:''}<div class="form-row"><label>地表調査へ配備する機数<input type="number" min="0" max="${Math.max(0,Number(row.max_units||0))}" step="1" value="${fmt(row.committed_units,0)}" data-survey-provider-fleet-quantity data-draft-key="survey-provider:${esc(row.provider_definition_id)}:${esc(row.operational_node_id)}:quantity" data-structured-draft data-draft-scope="survey-provider:${esc(row.provider_definition_id)}:${esc(row.operational_node_id)}" ${row.can_set_quantity?'':'disabled'}></label><button type="button" data-survey-provider-set-fleet="${esc(row.provider_definition_id)}" data-vehicle-definition-id="${esc(row.vehicle_definition_id)}" data-operational-node-id="${esc(row.operational_node_id)}" ${row.can_set_quantity?'':'disabled'}>配備数を適用</button></div></div>`).join('');
    const providerSection=`<section class="card"><div class="card-heading"><div><h3>地表調査能力の配備</h3><div class="cell-sub">地表調査の可否や進行が能力不足で制約される場合に調整します。</div></div><span class="badge">${providerFleet.filter((row)=>Number(row.committed_units||0)>0).length}</span></div><div class="card-body"><div class="detail-stack">${providerCards||'<div class="empty-state">Fleetを使う地表調査能力はありません。</div>'}</div></div></section>`;
    return `<div class="survey-decision-surface"><div class="decision-surface-heading"><div><span class="eyebrow">地表調査</span><h2>地表調査</h2><p>地域、対象資源、調査知識目標を直接選びます。観測手段は自動選択し、戦略差が意思決定に影響する場合だけ比較します。</p></div></div>${createSection}${campaignSection}${knowledgeSection}${providerSection}</div>`;
  }

  function renderSurfaceTab(){
    const map=state.surfaceMap;
    if(!map){
      const summary=(state.world?.operational_nodes||[]).find((row)=>row.id===state.operationalNodeId);
      const message=summary?.body_id?'地表マップを取得しています。':'このSpatial Nodeには表示可能な地表天体がありません。';
      return `<section class="card"><div class="card-heading"><h3>地表マップ</h3></div><div class="empty-state">${message}</div></section>`;
    }
    const cells=map.cells||[];
    if(!cells.length)return `<section class="card"><div class="card-heading"><h3>${esc(map.display_name)} 地表</h3></div><div class="empty-state">地表区画が定義されていません。</div></section>`;
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
    const locations=(map.locations||[]).map((loc)=>`<span class="badge">${esc(loc.display_name)} ${loc.developed_cell_ids?.length||0} 地域</span>`).join(' ');
    return `<div class="surface-layout"><section class="card surface-map-card"><div class="card-heading"><div><h3>${esc(map.display_name)} 地表</h3><div class="cell-sub">地域を選択してSurvey・開発・位置依存設備・新拠点設立を判断します。</div></div><span class="badge">${cells.length} 地域</span></div><div class="surface-map-stage"><svg class="surface-map-links" viewBox="0 0 1000 480" preserveAspectRatio="none" aria-hidden="true">${lines.join('')}</svg><div class="surface-map-nodes">${buttons}</div></div><div class="surface-map-legend"><span><i class="legend-dot core"></i>拠点中心</span><span><i class="legend-dot developed"></i>開発済み</span><span><i class="legend-dot undeveloped"></i>未開発</span></div></section><section class="card"><div class="card-heading"><h3>拠点領域</h3></div><div class="card-body">${locations||'<div class="empty-state">拠点なし</div>'}</div></section></div>`;
  }

  function patchSurveyDecisionSurface(root,html){
    const liveSurface=root.firstElementChild;
    const liveDraft=liveSurface?.querySelector?.('[data-survey-draft-surface]');
    if(!liveSurface?.classList?.contains('survey-decision-surface')||!liveDraft)return false;
    const template=document.createElement('template');
    template.innerHTML=html.trim();
    const nextSurface=template.content.firstElementChild;
    const nextDraft=nextSurface?.querySelector?.('[data-survey-draft-surface]');
    if(!nextDraft||nextDraft.dataset.surveyDraftSignature!==liveDraft.dataset.surveyDraftSignature)return false;

    // The draft controls are local intent, not authoritative state. Keep their DOM
    // nodes mounted so a periodic snapshot cannot detach an in-progress tap/click.
    // All sibling sections remain authoritative and are refreshed from the latest
    // Application projection on every sync.
    const nextChildren=[...nextSurface.children];
    const draftIndex=nextChildren.indexOf(nextDraft);
    const oldSiblings=[...liveSurface.children].filter((child)=>child!==liveDraft);
    const before=nextChildren.slice(0,draftIndex);
    const after=nextChildren.slice(draftIndex+1);
    if(before.length)liveDraft.before(...before);
    if(after.length)liveDraft.after(...after);
    oldSiblings.forEach((child)=>child.remove());
    return true;
  }

  function renderActiveTab(){
    const renderers={overview:renderOverviewTab,facilities:renderFacilitiesTab,inventory:renderInventoryTab,construction:renderConstructionTab,research:renderResearchTab,'scientific-exploration':renderScientificExplorationTab,survey:renderSurveyTab,surface:renderSurfaceTab};
    const root=$('#operationsTabContent');
    const html=(renderers[state.activeTab]||renderOverviewTab)();
    if(state.activeTab==='survey'&&patchSurveyDecisionSurface(root,html)){root.dataset.renderedTab=state.activeTab;return;}
    if(root.dataset.renderedTab===state.activeTab){
      A.replaceHtmlPreservingKeyed(root,html,[{selector:'[data-inspect][data-id]',attributes:['data-inspect','data-id']}]);
    }else if(root.innerHTML!==html){
      root.innerHTML=html;
    }
    root.dataset.renderedTab=state.activeTab;
  }

  function facilityUpgradeDifferencesHtml(upgrade){
    const rows=upgrade?.differences||[];
    if(!rows.length)return '<div class="empty-state">この更新で確認できる主要な能力差はありません。</div>';
    const value=(raw,unit)=>`${typeof raw==='number'?fmt(raw,2):esc(raw)}${unit?` ${esc(unit)}`:''}`;
    const cards=rows.map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(row.label)}</span><span class="badge">${esc(A.userFacingText(row.kind))}</span></div><div class="upgrade-delta"><span><small>現在</small><strong data-upgrade-value-role="current">${value(row.current_value,row.unit)}</strong></span><span aria-hidden="true">→</span><span><small>変更後</small><strong data-upgrade-value-role="target">${value(row.target_value,row.unit)}</strong></span></div></div>`).join('');
    const unchanged=(upgrade.unchanged_aspects||[]).length?`<div class="cell-sub">変更なし: ${(upgrade.unchanged_aspects||[]).map(esc).join(' · ')}</div>`:'';
    return cards+unchanged;
  }

  function renderFacilityInspector(id){
    const f=state.operationalNode?.facilities?.find((x)=>x.id===id);if(!f)return false;
    const blockers=f.operating_blockers||f.activation_blockers||[],u=f.next_upgrade;
    const researchRows=f.research_tier==null?[]:[['研究手段世代',fmt(f.research_tier,0)],['RP生成',`${fmt(f.research_generation_points_per_day,2)}/日`],['RP貯蔵',fmt(f.research_storage_capacity_points,1)]];
    const industry=state.operationalNode?.industry?.find((row)=>row.facility_id===id);
    const extraction=state.operationalNode?.extraction?.find((row)=>row.facility_id===id);
    const rateCards=(rows)=>(rows||[]).map(([resourceId,rate])=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(resourceId))}</span><span>${fmt(rate,3)} t/日</span></div></div>`).join('')||'<div class="empty-state">なし</div>';
    let productionSection='';
    if(industry){
      const comparisonAvailable=(industry.process_comparison_axes||[]).length>0;
      const pins=new Set(comparisonPinnedKeys(processComparisonScope(industry),industry.process_options||[]));
      const processOptions=(industry.process_options||[]).map((option)=>{
        const selected=option.process_id===industry.process_id,pinned=pins.has(option.comparison_key),pinDisabled=comparisonAvailable&&!pinned&&pins.size>=4;
        const inputs=(option.input_rates_per_day||[]).map(([resourceId,rate])=>`${resourceName(resourceId)} ${fmt(rate,3)} t/日`).join(' / ')||'投入なし';
        const outputs=(option.output_rates_per_day||[]).map(([resourceId,rate])=>`${resourceName(resourceId)} ${fmt(rate,3)} t/日`).join(' / ')||'産出なし';
        const services=(option.service_requirements||[]).map(([serviceId,rate])=>`${serviceName(serviceId)} ${fmt(rate,2)}`).join(' / ')||'追加Service要求なし';
        const compareAction=comparisonAvailable?`<button type="button" data-process-compare-pin="${esc(f.id)}" data-comparison-key="${esc(option.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button>`:'';
        return `<div class="detail-card ${selected?'is-usable':''}" data-process-option="${esc(option.process_id)}"><div class="mode-title"><span>${esc(option.display_name||definitionName(option.process_id))}</span><span class="badge ${selected?'ok':(option.blockers||[]).length?'warn':''}">${selected?'現在の工程':(option.blockers||[]).length?'実行制約あり':'切替候補'}</span></div><div class="cell-sub">投入: ${esc(inputs)}</div><div class="cell-sub">産出: ${esc(outputs)}</div><div class="cell-sub">必要能力: ${esc(services)}</div>${(option.blockers||[]).length?`<div class="issue-stack">${option.blockers.map(issueHtml).join('')}</div>`:''}<div class="action-row">${compareAction}<button type="button" data-facility-process="${esc(f.id)}" data-process-id="${esc(option.process_id)}" aria-pressed="${selected?'true':'false'}" ${selected?'disabled':''}>${selected?'選択中':'この工程へ切替'}</button></div></div>`;
      }).join('');
      const processControl=`<div class="choice-section"><div class="choice-label">生産工程を選択</div><div class="choice-grid facility-process-choices">${processOptions||'<div class="empty-state">候補なし</div>'}</div></div>${comparisonAvailable?`<h4>工程比較</h4>${processComparisonHtml(industry)}`:''}`;
      productionSection+=section('生産工程',kv([['現在の工程',esc(industry.process_display_name||'未選択')],['工程選択',industry.selection_required?'選択が必要':'確定'],['実効稼働率',pct(industry.scale)]])+processControl+`<h4>現在工程の投入/日</h4>${rateCards(industry.input_rates_per_day)}<h4>現在工程の生産物/日</h4>${rateCards(industry.output_rates_per_day)}<h4>現在の主な制約</h4>${limitingHtml(industry.limiting_factors)}`);
    }
    if(extraction){
      productionSection+=section('採掘',kv([['対象資源',esc(resourceName(extraction.resource_id))],['基準能力',`${fmt(extraction.nominal_capacity_t_per_day,3)} t/日`],['有効採掘機会',fmt(extraction.effective_opportunity,3)],['限界効率',pct(extraction.marginal_efficiency)],['産出資源',esc(resourceName(extraction.output_resource_id))],['生産物/日',`${fmt(extraction.output_t_per_day,3)} t/日`],['実効稼働率',pct(extraction.scale)]])+`<h4>主な制約</h4>${limitingHtml(extraction.limiting_factors)}`);
    }
    if(!productionSection)productionSection=section('生産・採掘','<div class="empty-state">この設備には現在の生産・採掘工程がありません。</div>');
    let upgradeSection='';
    if(u){
      const plan=planningOptionState(u,'更新計画可');
      const planOptions=state.buildOptions||{};
      const planControls=constructionPlanControls('upgradePlan',{draftScope:`facility-upgrade:${f.id}`,policyOptions:planOptions.procurement_policy_options||[],disabled:plan.disabled});
      upgradeSection=section(`次の更新 · Lv ${fmt(u.target_level,0)}`,`<h4>現在 → 変更後</h4>${facilityUpgradeDifferencesHtml(u)}`+kv([['必要工数',fmt(u.construction_required,0)],['既存案件',u.active_project_id?esc(u.active_project_id):'なし'],['計画可否',esc(plan.label)]])+`<h4>必要資源</h4>${resourceCards(u.resources)}${plan.blockers.length?`<div class="issue-stack">${plan.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">制約なし</span>'}${planControls}<button type="button" class="primary" data-upgrade="${esc(f.id)}" data-plan-prefix="upgradePlan" ${plan.disabled?'disabled':''}>Lv ${fmt(u.target_level,0)} 更新案件を作成</button>`);
    }else upgradeSection=section('次の更新','<div class="empty-state">現在定義されている次Levelの更新はありません。</div>');
    const investment=(f.invested_resources||[]).map(([r,a])=>`<div class="cell-sub">${esc(resourceName(r))}: ${fmt(a)} t</div>`).join('')||'<div class="empty-state">投入履歴なし</div>';
    const maintenance=(f.maintenance_demand_per_day||[]).map(([r,a])=>`<div class="cell-sub">${esc(resourceName(r))}: ${fmt(a,4)} t/日</div>`).join('')||'<div class="empty-state">維持資源要求なし</div>';
    const salvagePotential=(f.expected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし';
    const salvageProjected=(f.projected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし';
    const decommissionBlockers=f.decommission_blockers||[];
    const planOptions=state.buildOptions||{};
    const decommissionDisabled=!f.can_decommission;
    const decommissionControls=constructionPlanControls('decommissionPlan',{draftScope:`facility-decommission:${f.id}`,policyOptions:planOptions.procurement_policy_options||[],disabled:decommissionDisabled});
    const decommissionStatus=f.active_decommission_project_id
      ? `<span class="badge warn">撤去案件進行中</span><button type="button" data-inspect="project" data-id="${esc(f.active_decommission_project_id)}">案件を開く</button>`
      : f.can_decommission?'<span class="badge ok">撤去計画可</span>':'<span class="badge warn">撤去不可</span>';
    const decommissionSection=section('設備撤去',kv([['状態',decommissionStatus],['回収可能量',esc(salvagePotential)],['見込回収率',pct(f.projected_salvage_fraction??1)],['見込回収量',esc(salvageProjected)]])+`<h4>撤去条件</h4>${decommissionBlockers.length?`<div class="issue-stack">${decommissionBlockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">制約なし</span>'}${decommissionControls}<button type="button" class="danger-button" data-decommission="${esc(f.id)}" data-plan-prefix="decommissionPlan" ${decommissionDisabled?'disabled':''}>${f.active_decommission_project_id?'撤去案件進行中':'設備撤去案件を作成'}</button>`);
    setInspector(f.display_name,section('状態',kv([['Level',fmt(f.level,0)],['運転',f.paused?'手動停止':'稼働'],['電力利用率',pct(f.power_utilization)],['維持充足率',pct(f.maintenance_satisfaction)],['実効稼働率',pct(f.operational_utilization)],['活動優先度',esc(priorityName(f.activity_priority))],['維持優先度',esc(priorityName(f.maintenance_priority??3))],...researchRows]))+section('現在の制約',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<div class="badge ok">なし</div>')+section('運用操作',`<div class="action-stack"><button type="button" data-command="${f.paused?'ResumeFacility':'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused?'設備を再開':'設備を停止'}</button><div class="form-row">${priorityControl(f.activity_priority??3,`id="facilityPriorityInput" data-priority-direct="facility-activity" data-priority-id="${esc(f.id)}"`,'活動優先度')}</div><div class="form-row">${priorityControl(f.maintenance_priority??3,`id="maintenancePriorityInput" data-priority-direct="maintenance" data-priority-id="${esc(f.id)}"`,'維持優先度')}</div></div>`)+productionSection+upgradeSection+decommissionSection+section('建造・更新投入資源',investment)+section('維持資源需要',maintenance));
    return true;
  }
  function renderExtractionResourceInspector(id){
    const row=state.operationalNode?.extraction_resources?.find((item)=>item.resource_id===id);if(!row)return false;
    const infra=state.operationalNode?.surface_infrastructure;
    const infraLimit=infra?.limiting_factors?.some((factor)=>factor.code==='surface_infrastructure');
    setInspector(row.resource_name,section('資源機会 / 採掘',kv([['有効採掘機会',fmt(row.effective_opportunity,3)],['設置採掘能力',`${fmt(row.installed_nominal_capacity_t_per_day,3)} t/日`],['実採掘量',`${fmt(row.output_t_per_day,3)} t/日`],['規模逓減効率',pct(row.diminishing_efficiency)],['限界効率',pct(row.marginal_efficiency)],['運用充足率',pct(row.operational_fulfillment)]]))+section('地表インフラ',infra?kv([['充足率',pct(infra.fulfillment)],['主な制約',infraLimit?'<span class="badge warn">地表インフラ</span>':'<span class="badge ok">なし</span>']]):'<div class="empty-state">非地表Location</div>'));
    return true;
  }
  function renderResourceInspector(id){
    const inv=state.operationalNode?.inventory?.find((x)=>x.resource_id===id),f=state.flow?.resources?.find((x)=>x.resource_id===id);if(!inv)return false;
    setInspector(inv.display_name,section('在庫',kv([['在庫',fmt(inv.amount)],['予約',fmt(inv.reserved)],['利用可能',fmt(inv.available)],['物理容量',fmt(inv.physical_capacity)],['利用可能容量',fmt(inv.usable_capacity)],['入庫可能量',fmt(inv.admission_capacity)],['容量超過',fmt(inv.over_capacity)],['制限要因',esc((inv.limiting_factors||[]).map(A.constraintSummary).join(' / ')||'なし')],['入庫制約',esc((inv.admission_blockers||[]).map(A.constraintSummary).join(' / ')||'なし')]]))+section('フロー',kv([['生産/日',signed(f?.local_production_per_day)],['消費/日',signed(f?.local_consumption_per_day)],['純変化/日',signed(f?.local_net_per_day)],['入荷中',fmt(f?.inbound_in_transit_t)],['出荷中',fmt(f?.outbound_in_transit_t)],['到着待機',fmt(f?.arrival_waiting_t)]])));
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
    const contextActions=[];
    if(current?.navigation?.decision_area==='logistics')contextActions.push('<button type="button" data-dependency-transport="current">現在の関連輸送を見る</button>');
    if(forecast?.navigation?.decision_area==='logistics')contextActions.push('<button type="button" data-dependency-transport="forecast">計画需要の関連輸送を見る</button>');
    const actions=contextActions.length?section('関連判断',`<div class="action-stack">${contextActions.join('')}</div>`):'';
    setInspector(displayName,currentSection+forecastSection+actions);
    return true;
  }
  function renderDependencyServiceInspector(id){
    const current=(state.dependencyAnalyticsCurrent?.current_services||[]).find((row)=>row.service_type===id);
    const forecast=(state.dependencyAnalyticsForecast?.forecast_services||[]).find((row)=>row.service_type===id);
    if(!current&&!forecast)return false;
    const scopeName=(scope)=>scope==='ORGANIZATION'?'組織共有':'拠点内';
    const currentSection=current?section('現在',kv([
      ['適用範囲',esc(scopeName(current.scope))],
      ['基準能力',`${fmt(current.local_nominal_rate,2)} /日`],
      ['利用可能能力',`${fmt(current.local_enabled_rate,2)} /日`],
      ['需要',`${fmt(current.requested_rate,2)} /日`],
      ['実使用',`${fmt(current.allocated_rate,2)} /日`],
      ['能力不足',`${fmt(current.unmet_rate,2)} /日`],
      ['選択範囲外依存',`${fmt(current.external_dependency_rate,2)} /日`],
      ['選択範囲外能力',`${fmt(current.outside_scope_enabled_rate,2)} /日`],
      ['範囲内充足',pct(current.local_coverage_ratio)],
    ])+`<h4>主な制約</h4>${limitingHtml(current.limiting_factors)}`):section('現在','<div class="empty-state">現在のサービス需要はありません。</div>');
    const forecastSection=forecast?section('予測',kv([
      ['適用範囲',esc(scopeName(forecast.scope))],
      ['計画要求',fmt(forecast.planned_requirement,2)],
      ['現在の範囲内能力',`${fmt(forecast.local_enabled_rate,2)} /日`],
      ['選択範囲外能力',`${fmt(forecast.outside_scope_enabled_rate,2)} /日`],
      ['最早必要日',forecast.earliest_requirement_day==null?'未確定':`Day ${fmt(forecast.earliest_requirement_day,0)}`],
    ])+`<h4>主な制約</h4>${limitingHtml(forecast.limiting_factors)}`):section('予測','<div class="empty-state">計画済みの将来サービス需要はありません。</div>');
    setInspector(serviceName(id),currentSection+forecastSection);
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
      ? `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeFounding':'PauseFounding'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'準備再開':'準備停止'}</button><div class="form-row">${priorityControl(p.priority??3,`id="projectPriorityInput" data-priority-direct="founding" data-priority-id="${esc(p.id)}"`,'優先度',!p.settings_editable)}</div><button type="button" class="danger-button" data-command="CancelFounding" data-project-id="${esc(p.id)}" ${settingsDisabled}>設立計画を取消</button></div>`
      : `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'建設再開':'建設停止'}</button><div class="form-row">${priorityControl(p.priority??3,`id="projectPriorityInput" data-priority-direct="project" data-priority-id="${esc(p.id)}"`,'優先度',!p.settings_editable)}</div><div class="form-row"><label>調達方針<select id="projectProcurementTimingPolicy" data-draft-key="project:${esc(p.id)}:procurement" data-structured-draft data-draft-scope="project:${esc(p.id)}" ${procurementDisabled}>${procurementOptions}</select></label><button type="button" data-set-project-procurement="${esc(p.id)}" ${procurementDisabled}>方針を適用</button></div><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}" ${settingsDisabled}>案件取消</button></div>`;
    const foundingDecision=foundingProject?section('拠点設立判断',kv([['設立先種別',esc(p.founding_target_type==='surface_location'?'地表拠点':p.founding_target_type==='non_surface_operational_node'?'宇宙拠点':A.userFacingText(p.founding_target_type||'—'))],['設立段階',esc(stateLabels[p.deployment_phase]||stateLabels[p.status]||A.userFacingText(p.deployment_phase||p.status||'—'))],['展開資材',p.manifest_ready?'<span class="badge ok">準備済み</span>':'<span class="badge warn">準備不足</span>'],['設立用Fleet',p.fleet_commitment_id?'<span class="badge ok">確保済み</span>':'<span class="badge warn">未確保</span>']])+`<h3>調査知識条件</h3>${(p.founding_knowledge_requirements||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(row.subject_resource_id))}</span><span class="badge ${row.met?'ok':'warn'}">${fmt(row.current_level,0)} / ${fmt(row.minimum_level,0)}</span></div><div class="cell-sub">${esc(surfaceCellLabel(row.target_cell_id))}</div></div>`).join('')||'<div class="empty-state">調査知識条件なし</div>'}<h3>地点条件の制約</h3>${(p.site_blockers||[]).length?`<div class="issue-stack">${p.site_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}<h3>移動条件の制約</h3>${(p.movement_blockers||[]).length?`<div class="issue-stack">${p.movement_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}`):'';
    const disposalDecision=p.target_kind==='facility_decommission'?section('撤去時の回収',kv([['取消不能状態',p.irreversible_started?'開始済み':'未開始'],['回収可能量',esc((p.expected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')],['見込回収率',p.projected_salvage_fraction==null?'—':pct(p.projected_salvage_fraction)],['見込回収量',esc((p.projected_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')],['実績回収率',p.actual_salvage_fraction==null?'—':pct(p.actual_salvage_fraction)],['実績回収量',esc((p.actual_salvage||[]).map(([r,a])=>`${resourceName(r)} ${fmt(a,2)}t`).join(' / ')||'なし')]])):'';
    setInspector(p.display_name||p.facility_display_name||(foundingProject?'拠点設立案件':'建設案件'),section('案件',kv(targetRows))+section('主な制約',limitingHtml(p.limiting_factors||[]))+section('実行条件',(p.blockers||[]).length?`<div class="issue-stack">${p.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',projectControls)+foundingDecision+disposalDecision+section('必要資源 / 調達',resourceRows||'<div class="empty-state">追加資源なし</div>')+section('補給需要',requirementHtml));
    return true;
  }
  function renderBuildOptionInspector(id){
    const o=state.buildOptions?.items?.find((x)=>x.facility_definition_id===id);if(!o)return false;
    const plan=planningOptionState(o,'建設計画可');
    const planOptions=state.buildOptions||{};
    const planControls=constructionPlanControls('buildPlan',{draftScope:`facility-build:${o.facility_definition_id}`,policyOptions:planOptions.procurement_policy_options||[],disabled:plan.disabled});
    const capabilityCards=(o.capabilities||[]).map((id)=>`<div class="detail-card"><div class="mode-title"><span>能力</span><strong>${esc(capabilityName(id))}</strong></div></div>`).join('');
    const serviceCards=(o.service_capacity_supplies||[]).map(([service,rate])=>`<div class="detail-card"><div class="mode-title"><span>サービス</span><strong>${esc(serviceName(service))}</strong></div><div class="cell-sub">基準供給 ${fmt(rate,2)}</div></div>`).join('');
    const processCards=(o.process_options||[]).map(([,name])=>`<div class="detail-card"><div class="mode-title"><span>生産工程</span><strong>${esc(name)}</strong></div></div>`).join('');
    const enables=capabilityCards+serviceCards+processCards||'<div class="empty-state">追加される能力情報なし</div>';
    const placement=o.placement_scope==='SURFACE_CELL'?'地表地域':'拠点';
    const comparisonAvailable=(state.buildOptions?.comparison_axes||[]).length>0;
    const pinnedKeys=new Set(constructionComparisonPinnedKeys());
    const pinned=pinnedKeys.has(o.comparison_key);
    const pinDisabled=comparisonAvailable&&!pinned&&pinnedKeys.size>=4;
    const compareAction=comparisonAvailable?`<button type="button" data-construction-compare-pin="${esc(o.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button>`:'';
    const readiness=o.projected_material_readiness_day==null?'未確定':Number(o.projected_material_readiness_day)<=Number(state.world?.day??state.session?.day??0)?'現地準備済み':`Day ${fmt(o.projected_material_readiness_day,0)}`;
    setInspector(o.display_name,
      section('建設',kv([['必要工数',fmt(o.construction_required,0)],['資材準備見込み',esc(readiness)],['配置先',esc(placement)],['自己展開',o.self_deploying?'はい':'いいえ'],['計画可否',esc(plan.label)]]))+
      section('実行条件',plan.blockers.length?plan.blockers.map(issueHtml).join(''):'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack">${compareAction}${planControls}<button type="button" class="primary" data-build="${esc(o.facility_definition_id)}" data-plan-prefix="buildPlan" ${plan.disabled?'disabled':''}>この条件で建設計画を作成</button></div>`)+
      (comparisonAvailable?section('建設候補比較',constructionComparisonHtml()):'')+
      section('建設後に利用可能',enables)+
      section('必要資源',resourceCards(o.resources))
    );
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
    const options=r.execution_context_options||[],selected=r.execution_context,comparisonAvailable=(r.execution_context_comparison_axes||[]).length>0,pins=new Set(researchComparisonPinnedKeys(r));
    if(!options.length)return '<div class="empty-state">候補地点なし</div>';
    return options.map((site)=>{const blockers=site.blockers||[],blocked=blockers.length,isSelected=Boolean(selected)&&site.operational_node_id===selected.operational_node_id&&(site.surface_cell_id||null)===(selected.surface_cell_id||null),canSelect=Boolean(site.can_select),attr=kind==='prototype'?'data-research-prototype-site':'data-research-demo-site',pinned=pins.has(site.comparison_key),pinDisabled=comparisonAvailable&&!pinned&&pins.size>=4;const badge=isSelected?'選択中':canSelect?(blocked?`選択可 · ${blocked} 稼働制約`:'選択可'):`${blocked||1} 制約`;const compareAction=comparisonAvailable?`<button type="button" data-research-compare-pin="${esc(r.id)}" data-comparison-key="${esc(site.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button>`:'';return `<div class="detail-card ${isSelected?'is-usable':''}"><div class="mode-title"><span>${esc(researchSiteLabel(site))}</span><span class="badge ${blocked?'warn':canSelect||isSelected?'ok':''}">${badge}</span></div>${blocked?`<div class="issue-stack">${blockers.map((x)=>issueHtml(x)).join('')}</div>`:''}<div class="action-row">${compareAction}<button type="button" ${attr}="${esc(site.operational_node_id)}" data-surface-cell-id="${esc(site.surface_cell_id||'')}" data-id="${esc(r.id)}" data-stage-id="${esc(r.current_stage_id||'')}" ${!canSelect||isSelected?'disabled':''}>${kind==='prototype'?'試作地点に設定':'実証地点に設定'}</button></div></div>`;}).join('');
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
  function researchUnlocksHtml(r){
    const kindLabels={research:'次の研究',facility:'設備',facility_upgrade:'設備更新',surface_development:'地表開発',facility_decommission:'設備撤去'};
    const rows=r.unlocks||[];
    if(!rows.length)return '<div class="empty-state">この研究から直接つながる新しい研究・設備・開発操作はありません。</div>';
    return rows.map((row)=>{
      const remaining=row.remaining_prerequisite_ids||[];
      const stateBadge=remaining.length
        ? `<span class="badge">追加前提 ${remaining.length}</span>`
        : '<span class="badge ok">完了時に解禁</span>';
      const remainingText=remaining.length
        ? `<div class="cell-sub">ほかに必要: ${remaining.map((id)=>esc(definitionName(id))).join(' · ')}</div>`
        : '<div class="cell-sub">この研究の完了で前提技術が成立します。</div>';
      return `<div class="detail-card"><div class="mode-title"><span><small>${esc(kindLabels[row.kind]||'解禁')}</small><strong>${esc(row.display_name)}</strong></span>${stateBadge}</div>${remainingText}</div>`;
    }).join('');
  }
  function renderResearchInspector(id){
    const r=state.research?.items?.find((x)=>x.id===id);if(!r)return false;
    const action=lifecycleButton({domain:'research',id:r.id,canStart:r.can_start,canPause:r.can_pause,canResume:r.can_resume,complete:r.status==='complete',startLabel:'研究開始',pauseLabel:'研究停止',resumeLabel:'研究再開',completeLabel:'研究完了'});
    const phaseBlockers=researchBlockers(r);let phase='';
    if(r.status==='theory'){
      phase=section('理論研究',kv([['進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)} RP`],['RP要求 / 割当',`${fmt(r.rp_requested,2)} / ${fmt(r.rp_allocated,2)} /日`],['残りRP',`${fmt(r.rp_remaining,1)} RP`],['研究実行要求 / 割当',`${fmt(r.execution_requested,2)} / ${fmt(r.execution_allocated,2)} /日`]]));
    }else if(r.status==='prototype'){
      phase=section('試作',`<div class="cell-sub">地点 ${esc(researchSiteLabel(r.execution_context))} · 研究実行 ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'prototype')}${(r.execution_context_comparison_axes||[]).length?`<h3>実行地点比較</h3>${researchComparisonHtml(r)}`:''}<h3>試作資材</h3>${prototypeResourceHtml(r)}`);
    }else if(r.status==='demonstration'){
      phase=section('実証',`<div class="cell-sub">進捗 ${fmt(r.stage_progress,1)}/${fmt(r.stage_required,1)}日 · 地点 ${esc(researchSiteLabel(r.execution_context))} · 研究実行 ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'demonstration')}${(r.execution_context_comparison_axes||[]).length?`<h3>実行地点比較</h3>${researchComparisonHtml(r)}`:''}`);
    }else if(r.status==='operational_experience'){
      phase=section('運用経験',experienceHtml(r));
    }
    const stageNames={theory:'理論',prototype:'試作',demonstration:'実証',operational_experience:'運用経験'};
    const stageSequence=(r.stages||[]).map((x)=>stageNames[x.stage_type]||A.userFacingText(x.stage_type)).join(' → ')||'—';
    const startRows=[['研究段階',esc(stageSequence)],['保有RP',fmt(state.research?.stored_points,1)],['RP貯蔵上限',fmt(state.research?.storage_capacity_points,1)]];
    if((r.stages||[]).some((x)=>x.stage_type==='theory'))startRows.splice(1,0,['理論研究の必要RP',fmt(r.total_theory_research_point_cost,1)]);
    const startState=['available','locked'].includes(r.status)?section('開始条件',kv(startRows)):'';
    const researchPriorityAttributes=r.can_set_priority?`id="researchPriorityInput" data-priority-direct="research" data-priority-id="${esc(r.id)}"`:`id="researchPriorityInput" data-draft-key="research:${esc(r.id)}:priority"`;
    const priorityControlHtml=`<div class="form-row">${priorityControl(r.priority??3,researchPriorityAttributes,'研究優先度',!(r.can_start||r.can_set_priority))}</div>`;
    setInspector(r.display_name,
      section('研究状態',kv([['段階',esc(stateLabels[r.status]||A.userFacingText(r.status))],['優先度',esc(priorityName(r.priority??3))],['段階進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)}`],['RP要求 / 割当',`${fmt(r.rp_requested,2)} / ${fmt(r.rp_allocated,2)}`],['研究実行要求 / 割当',`${fmt(r.execution_requested,2)} / ${fmt(r.execution_allocated,2)}`]]))+
      section('解禁内容',researchUnlocksHtml(r))+
      section('現在の制約',phaseBlockers.length?`<div class="issue-stack">${phaseBlockers.map((x)=>issueHtml(x)).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('研究操作',`<div class="action-stack">${priorityControlHtml}${action}</div>`)+
      phase+
      startState+
      section('前提技術',(r.prerequisites||[]).length?(r.prerequisites||[]).map((x)=>`<span class="badge">${esc(definitionName(x))}</span>`).join(' '):'<span class="badge ok">なし</span>')
    );
    return true;
  }
  function renderScientificExplorationInspector(id){
    const x=state.scientificExplorations?.items?.find((row)=>row.id===id);if(!x)return false;
    const vehicleRows=(x.fleet_options||[]).map((v)=>{
      const blockers=v.blockers||[];const selected=v.vehicle_definition_id===x.assigned_vehicle_definition_id;
      const badge=selected?'配備中':blockers.length?'条件不一致':v.can_assign?'配備可':'Fleet不足';
      return `<div class="detail-card"><div class="mode-title"><span>${esc(v.display_name)}</span><span class="badge ${selected||v.can_assign?'ok':blockers.length?'warn':''}">${badge}</span></div><div class="cell-sub">${esc(locationName(v.operational_node_id))} · 保有 ${fmt(v.total_units,0)} / 空き ${fmt(v.free_units,0)} / 必要 ${fmt(v.required_units,0)}</div><div class="cell-sub">往路 ${v.outbound_latency_days==null?'—':`${fmt(v.outbound_latency_days,0)}日`}${v.return_latency_days==null?'':` / 復路 ${fmt(v.return_latency_days,0)}日`}</div>${blockers.length?`<div class="issue-stack" style="margin-top:7px">${blockers.map((b)=>issueHtml(b)).join('')}</div>`:''}<div class="action-row" style="margin-top:8px"><button type="button" data-exploration-assign="${esc(x.id)}" data-vehicle-definition-id="${esc(v.vehicle_definition_id)}" ${v.can_assign?'':'disabled'}>このFleetを配備</button></div></div>`;
    }).join('')||'<div class="empty-state">利用可能なFleet候補なし</div>';
    const inputs=(x.consumable_resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)}t`).join(' / ')||'追加消耗資源なし';
    const operations=(x.movement_operations||[]).map(([op,dv])=>`${esc(A.operationName(op))} ${fmt(dv,2)} km/s`).join(' / ')||'Fleet配備前は未確定';
    const vehicleCapabilities=(x.required_vehicle_capabilities||[]).map((capabilityId)=>esc(capabilityName(capabilityId))).join(' / ')||'追加能力要件なし';
    const blockers=x.blockers||[];
    const transitionLabels={start:'開始',assign_fleet:'Fleet配備',continue:'継続',pause:'停止',resume:'再開',abort:'中止',return:'帰還',unassign_fleet:'Fleet解除'};
    const transitions=(x.transition_options||[]).map((option)=>transitionLabels[option]||A.userFacingText(option)).join(' / ')||'なし';
    const dispositionLabels={return_to_origin_then_release:'出発地へ帰還後にFleet解放',release_at_destination:'到着地点でFleet解放'};
    const disposition=dispositionLabels[x.completion_disposition]||A.userFacingText(x.completion_disposition)||'—';
    let action=lifecycleButton({domain:'exploration',id:x.id,canStart:x.can_start,canPause:x.can_pause,canResume:x.can_resume,complete:['complete','aborted'].includes(x.status),startLabel:'探査開始',pauseLabel:'探査停止',resumeLabel:'探査再開',completeLabel:x.status==='aborted'?'探査中止済み':'探査完了'});
    if(x.can_return)action+=`<button type="button" data-exploration-return="${esc(x.id)}">出発地へ帰還</button>`;
    if(x.can_abort)action+=`<button type="button" class="danger" data-exploration-abort="${esc(x.id)}">探査を中止</button>`;
    if(x.can_unassign)action+=`<button type="button" data-exploration-unassign="${esc(x.id)}">Fleet配備を解除</button>`;
    const dispositionControl=x.can_set_completion_disposition?`<label class="form-field"><span>完了時のFleet</span><select data-exploration-disposition="${esc(x.id)}"><option value="release_at_destination" ${x.completion_disposition==='release_at_destination'?'selected':''}>探査先に残して解放</option><option value="return_to_origin" ${x.completion_disposition==='return_to_origin_then_release'?'selected':''}>出発地へ帰還して解放</option></select></label>`:'';
    setInspector(x.display_name,
      section('探査状態',kv([['出発地',esc(locationName(x.origin_id))],['探査先',esc(locationName(x.destination_id))],['往路時間',x.outbound_latency_days==null?'未確定':`${fmt(x.outbound_latency_days,0)}日`],['復路時間',x.return_latency_days==null?(x.assigned_vehicle_definition_id?'なし':'未確定'):`${fmt(x.return_latency_days,0)}日`],['現地活動期間',`${fmt(x.duration_days,1)}日`],['活動進捗',`${fmt(x.progress_days,1)}日`],['獲得RP',`${fmt(x.research_points_awarded,1)} / ${fmt(x.research_points_total,1)}`],['RP獲得速度',`${fmt(x.research_points_per_day,2)} /日`],['本日のRP要求 / 受入',`${fmt(x.rp_requested_today,2)} / ${fmt(x.rp_admitted_today,2)}`],['RP受入余力',fmt(x.rp_admission_headroom,2)],['RP受入制約',x.rp_admission_blocker?esc(A.constraintSummary(x.rp_admission_blocker)):'なし'],['必要機数',fmt(x.required_units,0)],['活動優先度',esc(priorityName(x.priority??3))],['配備Fleet',x.assigned_vehicle_definition_id?`${esc(definitionName(x.assigned_vehicle_definition_id))} · ${fmt(x.committed_units,0)} 機`:'未配備'],['完了時のFleet',esc(disposition)],['現在可能な操作',esc(transitions)]]))+
      section('現在の制約',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack"><div class="form-row">${priorityControl(x.priority??3,x.can_set_priority?`id="explorationPriorityInput" data-priority-direct="exploration" data-priority-id="${esc(x.id)}"`:`id="explorationPriorityInput" data-draft-key="exploration:${esc(x.id)}:priority"`,'活動優先度',!(x.can_start||x.can_set_priority))}</div>${dispositionControl}${action||'<span class="badge">操作なし</span>'}</div>`)+
      section('Fleet適合性',vehicleRows)+
      section('必要条件',`<div class="cell-sub">移動要件: ${operations}</div><div class="cell-sub">最低搭載量: ${fmt(x.minimum_payload_t,2)} t</div><div class="cell-sub">必要機体能力: ${vehicleCapabilities}</div><div class="cell-sub">消耗資源: ${inputs}</div><h3>${esc(locationName(x.origin_id))} の地点条件</h3>${siteRequirementsHtml(x.origin_requirements)}<h3>${esc(locationName(x.destination_id))} の地点条件</h3>${siteRequirementsHtml(x.destination_requirements)}`)
    );
    return true;
  }

  function renderSurveyInspector(id){
    const s=state.surveys?.items?.find((x)=>`${x.cell_id}::${x.resource_id}`===id);if(!s)return false;
    const potential=s.visible_potential==null?'—':fmt(s.visible_potential,3);
    const precision=s.visible_potential_precision_fraction==null?'—':s.visible_potential_precision_fraction<=0?'測定済み':`±${pct(s.visible_potential_precision_fraction)}`;
    const containing=(state.surveys?.campaigns||[]).filter((c)=>(c.target_cell_ids||[]).includes(s.cell_id)&&(c.resource_ids||[]).includes(s.resource_id));
    setInspector(`${s.resource_name} · ${s.cell_label}`,
      section('地表知識',kv([['調査知識レベル',String(s.knowledge_level)],['調査進捗',fmt(s.progress,2)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['推定埋蔵量',potential],['推定精度',precision]]))+
      section('関連する調査',containing.length?containing.map((c)=>`<button type="button" data-inspect="survey-campaign" data-id="${esc(c.id)}">${esc(knowledgeGoalName(c.goal_knowledge_level))} · ${c.target_cell_ids.length} 地域 × ${c.resource_ids.length} 資源</button>`).join(' '):'<div class="cell-sub">この対象を含む調査はありません。地表Mapで範囲と資源を選択して開始できます。</div>')
    );return true;
  }

  function renderSurveyCampaignInspector(id){
    const c=state.surveys?.campaigns?.find((row)=>row.id===id);if(!c)return false;
    const all=state.surveys?.items||[],cellMap=new Map(),resourceMap=new Map();
    all.forEach((row)=>{cellMap.set(row.cell_id,row.cell_label);resourceMap.set(row.resource_id,row.resource_name);});
    const cellChecks=[...cellMap].map(([cellId,label])=>`<label class="check-row"><input type="checkbox" data-survey-campaign-cell data-draft-key="survey:${esc(c.id)}:cell:${esc(cellId)}" data-structured-draft data-draft-scope="survey:${esc(c.id)}" value="${esc(cellId)}" ${(c.target_cell_ids||[]).includes(cellId)?'checked':''}>${esc(label)}</label>`).join('');
    const resourceChecks=[...resourceMap].map(([resourceId,label])=>`<label class="check-row"><input type="checkbox" data-survey-campaign-resource data-draft-key="survey:${esc(c.id)}:resource:${esc(resourceId)}" data-structured-draft data-draft-scope="survey:${esc(c.id)}" value="${esc(resourceId)}" ${(c.resource_ids||[]).includes(resourceId)?'checked':''}>${esc(label)}</label>`).join('');
    const comparisonAvailable=(c.comparison_axes||[]).length>0;
    const pinnedComparisonKeys=new Set(surveyComparisonPinnedKeys(c));
    const candidates=(c.candidates||[]).map((row)=>{
      const pinned=pinnedComparisonKeys.has(row.comparison_key);
      const pinDisabled=comparisonAvailable&&!pinned&&pinnedComparisonKeys.size>=4;
      const compareAction=comparisonAvailable?`<button type="button" data-survey-compare-pin="${esc(c.id)}" data-comparison-key="${esc(row.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button>`:'';
      return `<div class="detail-card"><div class="mode-title"><span>${esc(row.provider_display_name||'調査手段')} / ${esc(row.observation_mode_display_name||'観測方式')}</span><span class="badge ${row.viable?'ok':'warn'}">${row.viable?'利用可能':'利用不可'}</span></div><div class="cell-sub">${esc(locationName(row.provider_operational_node_id))} · ${esc(A.userFacingText(row.provider_source_kind))} · 調査速度 ${fmt(row.survey_rate,2)} · 到達可能 Lv ${fmt(row.max_knowledge_level,0)}</div><div class="cell-sub">配備 ${fmt(row.assigned_source_units,0)} / 最低 ${fmt(row.minimum_source_units,0)} · 能力 ${fmt(row.capacity_units_per_day,2)}/日</div><div class="cell-sub">推定精度 ±${pct(row.estimate_uncertainty_fraction)} / 測定精度 ±${pct(row.measurement_precision_fraction)}</div>${(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(b)).join('')}</div>`:''}<div class="action-row">${compareAction}<button type="button" data-survey-candidate-detail="${esc(c.id)}" data-comparison-key="${esc(row.comparison_key)}">詳細</button><button type="button" data-survey-constrain-candidate="${esc(c.id)}" data-provider-definition-id="${esc(row.provider_definition_id)}" data-operational-node-id="${esc(row.provider_operational_node_id)}" data-observation-mode-id="${esc(row.observation_mode_id)}">この観測手段に固定</button></div></div>`;
    }).join('')||'<div class="empty-state">現在利用可能な観測手段はありません。</div>';
    const targetCards=(c.targets||[]).map((row)=>{
      const ratio=Number(row.target_threshold)>0?Math.max(0,Math.min(1,Number(row.progress||0)/Number(row.target_threshold))):(row.complete?1:0);
      return `<div class="survey-target-progress-card ${row.complete?'is-complete':''}"><div class="mode-title"><span>${esc(surfaceCellLabel(row.cell_id))} · ${esc(resourceName(row.resource_id))}</span><span class="badge ${row.complete?'ok':''}">${row.complete?'目標到達':'調査中'}</span></div><div class="cell-sub">調査知識 Lv ${fmt(row.current_knowledge_level,0)} → Lv ${fmt(row.goal_knowledge_level,0)}</div><div class="progress-track"><span class="progress-bar" style="width:${ratio*100}%"></span></div><div class="cell-sub">進捗 ${fmt(row.progress,2)} / ${fmt(row.target_threshold,2)}</div></div>`;
    }).join('');
    const blockers=c.blockers||[];
    const provider=c.projected_provider_definition_id?`${c.projected_provider_display_name||'調査手段'} @ ${locationName(c.projected_provider_operational_node_id)} / ${c.projected_observation_mode_display_name||'観測方式'}`:'未解決';
    const actions=lifecycleButton({domain:'survey-campaign',id:c.id,canStart:false,canPause:c.can_pause,canResume:c.can_resume,complete:c.status==='completed',pauseLabel:'調査停止',resumeLabel:'調査再開',completeLabel:'調査完了'});
    setInspector(`地表調査 · ${knowledgeGoalName(c.goal_knowledge_level)}`,
      section('調査状態',kv([['状態',esc(stateLabels[c.status]||A.userFacingText(c.status))],['調査目標',esc(knowledgeGoalName(c.goal_knowledge_level))],['完了 / 残り対象',`${fmt(c.covered_targets,0)} / ${fmt(c.remaining_targets,0)}`],['解決された観測手段',esc(provider)],['能力要求 / 割当',`${fmt(c.requested_service_units_per_day,2)} / ${fmt(c.allocated_service_units_per_day,2)}`],['調査進行能力',`${fmt(c.capacity_points_per_day,2)} /日`],['必要 / 配備Fleet',c.required_fleet_units==null?'—':`${fmt(c.required_fleet_units,0)} / ${fmt(c.assigned_fleet_units,0)}`],['予測残り時間',c.projected_remaining_days==null?'—':`${fmt(c.projected_remaining_days,1)}日`],['優先度',esc(priorityName(c.priority??3))]]))+
      section('現在の制約',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack">${actions}<div class="form-row">${priorityControl(c.priority??3,`id="surveyPriorityInput" data-priority-direct="survey" data-priority-id="${esc(c.id)}"`,'活動優先度',!c.can_set_priority)}</div></div>`)+
      section('範囲・目標の編集',`<div class="detail-grid"><div class="detail-card"><div class="mode-title"><span>対象地域</span></div>${cellChecks}</div><div class="detail-card"><div class="mode-title"><span>対象資源</span></div>${resourceChecks}</div></div><div class="form-row"><label>調査目標<select id="surveyCampaignGoal" data-draft-key="survey:${esc(c.id)}:goal" data-structured-draft data-draft-scope="survey:${esc(c.id)}"><option value="1" ${Number(c.goal_knowledge_level)===1?'selected':''}>1 存在確認</option><option value="2" ${Number(c.goal_knowledge_level)===2?'selected':''}>2 埋蔵量推定</option><option value="3" ${Number(c.goal_knowledge_level)===3?'selected':''}>3 精密測定</option></select></label><button type="button" data-update-survey-campaign="${esc(c.id)}" disabled>範囲・目標を適用</button></div><div data-survey-update-intent-status><span class="badge">可否確認中</span></div>`)+
      section('対象ごとの進捗',`<div class="survey-target-progress-grid">${targetCards||'<div class="empty-state">調査対象はありません。</div>'}</div>`)+
      section('観測手段の候補',candidates)+
      (comparisonAvailable?section('候補比較',surveyComparisonHtml(c)):'')+
      section('観測手段の固定',`<div class="cell-sub">観測手段: ${esc(c.provider_constraint_definition_id?`${definitionName(c.provider_constraint_definition_id)} @ ${locationName(c.provider_constraint_operational_node_id)}`:'自動')} · 観測方式: ${esc(c.observation_mode_constraint?(c.observation_mode_constraint_display_name||'観測方式'):'自動')}</div><button type="button" data-clear-survey-constraint="${esc(c.id)}">自動選択へ戻す</button>`)
    );return true;
  }


  function renderSurveyCandidateInspector(id){
    const split=id.indexOf('@@');if(split<0)return false;
    const campaignId=id.slice(0,split),candidateKey=id.slice(split+2);
    const c=state.surveys?.campaigns?.find((row)=>row.id===campaignId);if(!c)return false;
    const row=(c.candidates||[]).find((candidate)=>candidate.comparison_key===candidateKey);if(!row)return false;
    const axes=c.comparison_axes||[];
    const details=axes.length?kv(axes.map((axis)=>[axis.label,comparisonValueHtml(axis,comparisonValue(row,axis.key))])):kv([['調査速度',fmt(row.survey_rate,2)],['到達可能な調査知識',fmt(row.max_knowledge_level,0)],['最低配備数',`${fmt(row.minimum_source_units,0)} 機`],['利用可能能力',`${fmt(row.capacity_units_per_day,2)} /日`]]);
    const blockers=row.blockers||[];
    const pinned=surveyComparisonPinnedKeys(c).includes(row.comparison_key);
    setInspector(`${row.provider_display_name||'調査手段'} · ${row.observation_mode_display_name||'観測方式'}`,
      section('観測手段の状態',kv([['提供地点',esc(locationName(row.provider_operational_node_id))],['提供方式',esc(A.userFacingText(row.provider_source_kind))],['利用可否',row.viable?'利用可能':'利用不可'],['現在の固定条件に一致',row.matches_constraints?'一致':'不一致']]))+
      section('現在の制約',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(b)).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack"><button type="button" data-survey-constrain-candidate="${esc(c.id)}" data-provider-definition-id="${esc(row.provider_definition_id)}" data-operational-node-id="${esc(row.provider_operational_node_id)}" data-observation-mode-id="${esc(row.observation_mode_id)}">この観測手段に固定</button>${(c.comparison_axes||[]).length?`<button type="button" data-survey-compare-pin="${esc(c.id)}" data-comparison-key="${esc(row.comparison_key)}" aria-pressed="${pinned?'true':'false'}">${pinned?'比較から外す':'比較に追加'}</button>`:''}<button type="button" data-inspect="survey-campaign" data-id="${esc(c.id)}">調査判断へ戻る</button></div>`)+
      section('比較軸の詳細',details)
    );
    return true;
  }

  function renderFoundingCandidateInspector(id){
    const row=foundationComparisonCandidate(id);if(!row)return false;
    const axes=state.surfaceMap?.founding_comparison_axes||[];
    const blockers=row.blockers||[];
    const foundingPins=foundationComparisonPinnedKeys();
    const pinned=foundingPins.includes(row.comparison_key);
    const pinDisabled=!pinned&&foundingPins.length>=4;
    const details=axes.length
      ?kv(axes.map((axis)=>[axis.label,comparisonValueHtml(axis,comparisonValue(row,axis.key))]))
      :kv([
          ['移動時間',row.transit_days==null?'到達不可':`${fmt(row.transit_days,0)} 日`],
          ['準備工数',fmt(row.preparation_work,0)],
          ['必要機数',`${fmt(row.required_units,0)} 機`],
          ['搭載量',`${fmt(row.payload_t,2)} t`],
        ]);
    setInspector(`設立候補 · ${row.target_cell_name}`,
      section('候補状態',kv([
        ['出発拠点',esc(locationName(row.staging_node_id))],
        ['展開方式',esc(row.recipe_display_name)],
        ['使用機体',esc(row.vehicle_display_name)],
        ['移動時間',row.transit_days==null?'到達不可':`${fmt(row.transit_days,0)} 日`],
        ['設立可否',row.can_plan?'設立可能':'条件未達'],
      ]))+
      section('現在の制約',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('操作',`<div class="action-stack">${axes.length?`<button type="button" data-founding-compare-pin="${esc(row.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button>`:''}<button type="button" data-inspect="surface-cell" data-id="${esc(row.target_cell_id)}">候補地点へ戻る</button></div>`)+
      section('比較軸の詳細',details)+
      section(row.transit_days==null?'最低展開資材':'出発拠点で必要な資源',`<div class="surface-resource-list">${tupleResourcesHtml(row.resources)}</div>${row.transit_days==null?'<div class="cell-sub">移動経路が未成立のため、運用資源を含む出発時総量は未確定です。</div>':''}`)
    );
    return true;
  }

  function renderSurfaceCellInspector(id){
    const cell=surfaceCell(id);if(!cell)return false;
    const terrain=Object.fromEntries(cell.terrain||[]);
    const owner=cell.location_id?locationName(cell.location_id):'未所属';
    const neighbors=(cell.neighbor_ids||[]).map((neighbor)=>`<span class="badge">${esc(surfaceCellLabel(neighbor))}</span>`).join(' ')||'<span class="badge">なし</span>';
    const foundingComparisonAvailable=(state.surfaceMap?.founding_comparison_axes||[]).length>0;
    const foundingPinnedKeys=new Set(foundationComparisonPinnedKeys());

    const foundation=(cell.foundation_options||[]).map((option)=>{
      const plan=planningOptionState(option,'設立可'),blockers=plan.blockers,active=option.active_project_id;
      const disabled=plan.disabled;
      const scope=`foundation:${cell.id}:${option.staging_node_id}:${option.deployment_recipe_id}:${option.vehicle_definition_id}`;
      const pinned=foundingPinnedKeys.has(option.comparison_key);
      const pinDisabled=foundingComparisonAvailable&&!pinned&&foundingPinnedKeys.size>=4;
      const compareActions=foundingComparisonAvailable?`<div class="action-row"><button type="button" data-founding-compare-pin="${esc(option.comparison_key)}" aria-pressed="${pinned?'true':'false'}" ${pinDisabled?'disabled':''}>${pinned?'比較から外す':'比較に追加'}</button><button type="button" data-founding-candidate-detail="${esc(option.comparison_key)}">詳細</button></div>`:'';
      const transit=option.transit_days==null?'到達不可':`${fmt(option.transit_days,0)}日`;
      const resourceHeading=option.transit_days==null?'最低展開資材':'出発拠点で必要な資源';
      const unresolvedMovement=option.transit_days==null?'<div class="cell-sub">移動経路が未成立のため、運用資源を含む出発時総量は未確定です。</div>':'';
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(locationName(option.staging_node_id))} · ${esc(option.recipe_display_name)} · ${esc(option.vehicle_display_name)}</span><span class="badge ${disabled?'warn':'ok'}">${active?'案件進行中':esc(plan.label)}</span></div><div class="cell-sub">準備工数 ${fmt(option.preparation_work,0)} · 輸送 ${transit} · 搭載量 ${fmt(option.payload_t,2)} t (${fmt(option.payload_t_per_unit,2)} t/機 × ${fmt(option.required_units,0)}機)</div><div class="cell-sub">${resourceHeading}</div><div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${unresolvedMovement}${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${active?`<div class="cell-sub">進行中の案件あり</div>`:''}${compareActions}<div class="form-row"><label>拠点名<input type="text" data-new-location-name data-draft-key="${esc(scope)}:name" data-structured-draft data-draft-scope="${esc(scope)}" placeholder="新規地表拠点"></label></div>${foundingPlanControls(scope,option,disabled)}<button type="button" class="primary" data-surface-found data-staging-node-id="${esc(option.staging_node_id)}" data-recipe-id="${esc(option.deployment_recipe_id)}" data-vehicle-id="${esc(option.vehicle_definition_id)}" data-cell-id="${esc(cell.id)}" data-body-id="${esc(cell.body_id)}" ${disabled?'disabled':''}>この地点へ拠点設立を開始</button></div>`;
    }).join('')||'<div class="empty-state">この地域へ利用可能な拠点設立候補がありません。</div>';

    const development=(cell.development_options||[]).map((option)=>{
      const plan=planningOptionState(option,'開発可'),blockers=plan.blockers,active=option.active_project_id;
      const disabled=plan.disabled;
      const infra=option.projected_surface_infrastructure_fulfillment==null?'—':pct(option.projected_surface_infrastructure_fulfillment);
      const limiting=(option.limiting_factors||[]).map((factor)=>`<span class="badge warn">${esc(A.constraintSummary(factor))}</span>`).join(' ');
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(locationName(option.location_id))} へ編入</span><span class="badge ${disabled?'warn':'ok'}">${active?'案件進行中':esc(plan.label)}</span></div><div class="cell-sub">工数 ${fmt(option.construction_required,0)} · 予測地表インフラ充足率 ${infra}</div>${option.projected_surface_infrastructure_demand==null?'':`<div class="cell-sub">予測インフラ需要 ${fmt(option.projected_surface_infrastructure_demand,2)}</div>`}<div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${limiting?`<div class="cell-sub">主な制約: ${limiting}</div>`:''}${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${active?`<div class="cell-sub">進行中の案件あり</div>`:''}${surfacePlanControls(`development:${cell.id}:${option.location_id}`,option,disabled)}<button type="button" class="primary" data-surface-develop="${esc(option.location_id)}" data-cell-id="${esc(cell.id)}" ${disabled?'disabled':''}>この地域の開発案件を作成</button></div>`;
    }).join('')||'<div class="empty-state">既存拠点への開発候補なし</div>';

    const facilities=(cell.facility_placement_options||[]).map((option)=>{
      const plan=planningOptionState(option,'建設可'),blockers=plan.blockers,disabled=plan.disabled;
      return `<div class="detail-card surface-action-card"><div class="mode-title"><span>${esc(option.display_name)}</span><span class="badge ${blockers.length?'warn':plan.canPlan?'ok':''}">${esc(plan.label)}</span></div><div class="cell-sub">工数 ${fmt(option.construction_required,0)} · ${option.self_deploying?'自己展開':'通常施工'}</div><div class="cell-sub">出発拠点で必要な資源</div><div class="surface-resource-list">${tupleResourcesHtml(option.resources)}</div>${blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:''}${surfacePlanControls(`surface-build:${cell.id}:${option.facility_definition_id}`,option,disabled)}<button type="button" class="primary" data-surface-build="${esc(option.facility_definition_id)}" data-location-id="${esc(option.location_id)}" data-cell-id="${esc(cell.id)}" ${disabled?'disabled':''}>この地域へ建設案件を作成</button></div>`;
    }).join('')||'<div class="empty-state">この地域へ配置可能な位置依存設備はありません。</div>';

    const foundationSection=cell.developed?'':section('新拠点設立',foundation);
    const foundationComparisonSection=cell.developed||!foundingComparisonAvailable?'':section('設立候補比較',foundationComparisonHtml());
    const developmentSection=cell.developed?'':section('既存拠点から開発',development);
    const facilitySection=cell.developed?section('位置依存設備',facilities):'';
    setInspector(surfaceCellLabel(cell.id),
      section('地域状態',kv([
        ['所属拠点',esc(owner)],
        ['拠点中心',cell.is_location_core?'はい':'いいえ'],
        ['面積',`${fmt(cell.area_km2,0)} km²`],
        ['緯度',`${fmt(cell.latitude_deg,2)}°`],
        ['経度',`${fmt(cell.longitude_deg,2)}°`],
      ]))+
      foundationSection+foundationComparisonSection+developmentSection+facilitySection+
      section('資源調査情報',surfaceResourcesHtml(cell.resources,cell.id))+
      section('現在の環境',environmentHtml(cell.environment))+
      section('地形',kv([
        ['地形係数',fmt(terrain.terrain_factor,2)],
        ['支持力係数',fmt(terrain.bearing_capacity_factor,2)],
        ['粉塵係数',fmt(terrain.dust_factor,2)],
        ['傾斜係数',fmt(terrain.slope_factor,2)],
      ]))+
      section('隣接地域',neighbors)
    );
    return true;
  }

  function renderInspector(){
    if(!state.inspector){setInspector('選択項目','<div class="empty-state">中央の項目を選択すると、状態・条件・操作をここに表示します。</div>');return;}
    const {type,id}=state.inspector;
    const handlers={facility:renderFacilityInspector,resource:renderResourceInspector,'dependency-resource':renderDependencyResourceInspector,'dependency-service':renderDependencyServiceInspector,'extraction-resource':renderExtractionResourceInspector,project:renderProjectInspector,'build-option':renderBuildOptionInspector,research:renderResearchInspector,'scientific-exploration':renderScientificExplorationInspector,survey:renderSurveyInspector,'survey-campaign':renderSurveyCampaignInspector,'survey-candidate':renderSurveyCandidateInspector,'founding-candidate':renderFoundingCandidateInspector,'surface-cell':renderSurfaceCellInspector};
    if(!handlers[type]?.(id)){state.inspector=null;setInspector('選択項目','<div class="empty-state">項目の状態が変化しました。再選択してください。</div>');return;}
    if(type==='survey-campaign')queueMicrotask(refreshVisibleSurveyIntentPreview);
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
    $('#locationKind').textContent=`${A.locationKindName(kind)}拠点`;
    $('#headlineMetrics').innerHTML=[['発電',`${fmt(loc.power_generation_mw)} MW`],['需要',`${fmt(loc.power_demand_mw)} MW`],['建設能力',`${fmt(loc.construction_capacity_per_day)} /日`],['設備',`${loc.facilities.length}`]].map(A.metricHtml).join('');
    $$('.tab-button').forEach((b)=>b.classList.toggle('is-active',b.dataset.tab===state.activeTab));
    renderActiveTab();renderInspector();queueMicrotask(refreshVisibleSurveyIntentPreview);
  }

  document.addEventListener('change',(event)=>{
    if(state.activeView!=='operations')return;
    const explorationDisposition=event.target.closest('[data-exploration-disposition]');
    if(explorationDisposition){
      void command('SetScientificExplorationCompletionDisposition',{
        exploration_id:explorationDisposition.dataset.explorationDisposition,
        disposition:explorationDisposition.value,
      }).catch(()=>{});
      return;
    }
    const priorityHolder=event.target.closest('[data-priority-direct]');
    if(priorityHolder){
      const id=priorityHolder.dataset.priorityId,priority=Number(priorityHolder.value),kind=priorityHolder.dataset.priorityDirect;
      const commands={
        'facility-activity':['SetFacilityActivityPriority','facility_id'], maintenance:['SetMaintenancePriority','facility_id'],
        project:['SetProjectPriority','project_id'], founding:['SetFoundingPriority','project_id'], research:['SetResearchPriority','research_id'],
        exploration:['SetScientificExplorationPriority','exploration_id'], survey:['SetSurveyPriority','campaign_id'],
        'research-provider':['SetResearchProviderAssignmentPriority','assignment_id'],
      };
      const spec=commands[kind];if(spec&&id)void command(spec[0],{[spec[1]]:id,priority}).catch(()=>{});
      return;
    }
    if(event.target.matches('[data-survey-draft-cell],[data-survey-draft-resource],#surveyDraftGoal')){
      void refreshSurveyIntentPreview();
      return;
    }
    if(event.target.matches('[data-survey-campaign-cell],[data-survey-campaign-resource],#surveyCampaignGoal')){
      const update=$('[data-update-survey-campaign]');
      if(update)void refreshSurveyIntentPreview(update.dataset.updateSurveyCampaign);
    }
  });

  document.addEventListener('spaceidle:draft-restored',()=>refreshVisibleSurveyIntentPreview());

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='operations')return;
    const surveyLayer=event.target.closest('[data-survey-map-layer]');if(surveyLayer){surveyMapLayer=surveyLayer.dataset.surveyMapLayer||'knowledge';const map=$('.survey-scope-map');if(map)map.dataset.surveyLayer=surveyMapLayer;$$('[data-survey-map-layer]').forEach((button)=>{const active=button.dataset.surveyMapLayer===surveyMapLayer;button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',active?'true':'false');});return;}
    const dependencyToggle=event.target.closest('[data-dependency-view]');if(dependencyToggle){dependencyView=dependencyToggle.dataset.dependencyView==='forecast'?'forecast':'current';renderActiveTab();renderInspector();return;}
    const dependencyTransport=event.target.closest('[data-dependency-transport]');if(dependencyTransport){const id=state.inspector?.type==='dependency-resource'?state.inspector.id:null;if(!id)return;const rows=dependencyTransport.dataset.dependencyTransport==='forecast'?(state.dependencyAnalyticsForecast?.forecast_resources||[]):(state.dependencyAnalyticsCurrent?.current_resources||[]);const row=rows.find((item)=>item.id===id);if(row?.navigation)await A.openDecisionContext(row.navigation);return;}
    const forecastHorizon=event.target.closest('[data-detailed-forecast-horizon]');if(forecastHorizon){detailedForecastHorizon=forecastHorizon.dataset.detailedForecastHorizon||'SHORT_TERM';renderActiveTab();return;}
    const runForecast=event.target.closest('[data-run-detailed-forecast]');if(runForecast){if(detailedForecastLoading)return;detailedForecastLoading=true;renderActiveTab();try{const nodeId=state.operationalNodeId;detailedForecast=await api(`/api/v1/detailed-forecast?scope_kind=operational_nodes&node_id=${encodeURIComponent(nodeId)}&horizon=${encodeURIComponent(detailedForecastHorizon)}`);}catch(error){banner(error.message||'詳細予測の取得に失敗しました','error');}finally{detailedForecastLoading=false;renderActiveTab();}return;}
    const tab=event.target.closest('[data-tab]');if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;render();if(['surface','survey'].includes(state.activeTab)){try{await A.loadUiSnapshot({preserveInteraction:false});}catch(e){banner(e.message,'error');}}return;}
    const inspect=event.target.closest('[data-inspect]');if(inspect){state.inspector={type:inspect.dataset.inspect,id:inspect.dataset.id};if(inspect.dataset.inspect==='surface-cell')render();else{renderInspector();$$('#operationsTabContent [data-inspect]').forEach((target)=>{const selected=target.dataset.inspect===inspect.dataset.inspect&&target.dataset.id===inspect.dataset.id;target.classList.toggle('is-selected',selected);if(target.hasAttribute('aria-pressed'))target.setAttribute('aria-pressed',selected?'true':'false');});}return;}
    const foundingCandidateDetail=event.target.closest('[data-founding-candidate-detail]');if(foundingCandidateDetail){state.inspector={type:'founding-candidate',id:foundingCandidateDetail.dataset.foundingCandidateDetail};renderInspector();return;}
    const foundingComparePin=event.target.closest('[data-founding-compare-pin]');if(foundingComparePin){const candidates=foundationComparisonCandidates(),key=foundingComparePin.dataset.foundingComparePin;toggleComparisonPin(foundationComparisonScope(),candidates,key);renderInspector();return;}
    const constructionComparePin=event.target.closest('[data-construction-compare-pin]');if(constructionComparePin){toggleComparisonPin(constructionComparisonScope(),constructionComparisonCandidates(),constructionComparePin.dataset.constructionComparePin);renderInspector();return;}
    const preserveSurfaceDecision=(cellId)=>{state.inspector={type:'surface-cell',id:cellId};render();};
    const surfaceBuild=event.target.closest('[data-surface-build]');if(surfaceBuild){const cellId=surfaceBuild.dataset.cellId,plan=surfacePlanPayload(surfaceBuild);try{await command('PlanBuild',{operational_node_id:surfaceBuild.dataset.locationId,facility_id:surfaceBuild.dataset.surfaceBuild,site_cell_id:cellId,...plan});await A.completeActiveDraft(`surface-build:${cellId}:${surfaceBuild.dataset.surfaceBuild}`);preserveSurfaceDecision(cellId);banner('地表設備の建設案件を作成しました');}catch{}return;}
    const surfaceDevelop=event.target.closest('[data-surface-develop]');if(surfaceDevelop){const cellId=surfaceDevelop.dataset.cellId,plan=surfacePlanPayload(surfaceDevelop);try{await command('DevelopSurfaceCell',{location_id:surfaceDevelop.dataset.surfaceDevelop,cell_id:cellId,...plan});await A.completeActiveDraft(`development:${cellId}:${surfaceDevelop.dataset.surfaceDevelop}`);preserveSurfaceDecision(cellId);banner('地表地域の開発案件を作成しました');}catch{}return;}
    const surfaceFound=event.target.closest('[data-surface-found]');if(surfaceFound){const cellId=surfaceFound.dataset.cellId,card=surfaceFound.closest('.surface-action-card'),displayName=card?.querySelector('[data-new-location-name]')?.value.trim();if(!displayName){banner('拠点名を入力してください','error');return;}const priority=Number(card?.querySelector('[data-founding-priority]')?.value??3);try{await command('PlanOperationalNodeFounding',{staging_node_id:surfaceFound.dataset.stagingNodeId,display_name:displayName,target_spec:{target_type:'surface_location',body_id:surfaceFound.dataset.bodyId,core_cell_id:cellId},deployment_recipe_id:surfaceFound.dataset.recipeId,vehicle_definition_id:surfaceFound.dataset.vehicleId,priority});await A.completeActiveDraft(`foundation:${cellId}:${surfaceFound.dataset.stagingNodeId}:${surfaceFound.dataset.recipeId}:${surfaceFound.dataset.vehicleId}`);preserveSurfaceDecision(cellId);banner('拠点設立を開始しました');}catch{}return;}
    const build=event.target.closest('[data-build]');if(build){const prefix=build.dataset.planPrefix||'buildPlan',priority=Number($(`#${prefix}PriorityInput`)?.value??3),procurementPolicy=$(`#${prefix}ProcurementTimingPolicy`)?.value||'standard_wait';try{await command('PlanBuild',{operational_node_id:state.operationalNodeId,facility_id:build.dataset.build,priority,procurement_policy:procurementPolicy});await A.completeActiveDraft(`facility-build:${build.dataset.build}`);banner('建設計画を作成しました');}catch{}return;}
    const upgrade=event.target.closest('[data-upgrade]');if(upgrade){const prefix=upgrade.dataset.planPrefix||'upgradePlan',priority=Number($(`#${prefix}PriorityInput`)?.value??3),procurementPolicy=$(`#${prefix}ProcurementTimingPolicy`)?.value||'standard_wait';try{await command('PlanFacilityUpgrade',{facility_id:upgrade.dataset.upgrade,priority,procurement_policy:procurementPolicy});await A.completeActiveDraft(`facility-upgrade:${upgrade.dataset.upgrade}`);banner('設備更新案件を作成しました');}catch{}return;}
    const decommission=event.target.closest('[data-decommission]');if(decommission){const prefix=decommission.dataset.planPrefix||'decommissionPlan',priority=Number($(`#${prefix}PriorityInput`)?.value??3),procurementPolicy=$(`#${prefix}ProcurementTimingPolicy`)?.value||'standard_wait';try{await command('PlanFacilityDecommission',{facility_id:decommission.dataset.decommission,priority,procurement_policy:procurementPolicy});await A.completeActiveDraft(`facility-decommission:${decommission.dataset.decommission}`);state.inspector={type:'facility',id:decommission.dataset.decommission};renderInspector();banner('設備撤去案件を作成しました');}catch{}return;}
    const cmd=event.target.closest('[data-command]');if(cmd){const payload={};if(cmd.dataset.facilityId)payload.facility_id=cmd.dataset.facilityId;if(cmd.dataset.projectId)payload.project_id=cmd.dataset.projectId;try{await command(cmd.dataset.command,payload);}catch{}return;}
    const processComparePin=event.target.closest('[data-process-compare-pin]');if(processComparePin){const industry=(state.operationalNode?.industry||[]).find((row)=>row.facility_id===processComparePin.dataset.processComparePin);if(!industry)return;toggleComparisonPin(processComparisonScope(industry),industry.process_options||[],processComparePin.dataset.comparisonKey);renderInspector();return;}
    const process=event.target.closest('[data-facility-process]');if(process){try{await command('SetFacilityProcess',{facility_id:process.dataset.facilityProcess,process_id:process.dataset.processId});state.inspector={type:'facility',id:process.dataset.facilityProcess};renderInspector();banner('生産工程を更新しました');}catch{}return;}
    const projectSourcing=event.target.closest('[data-set-project-procurement]');if(projectSourcing){try{await command('SetProjectProcurementPolicy',{project_id:projectSourcing.dataset.setProjectProcurement,procurement_policy:$('#projectProcurementTimingPolicy').value});}catch{}return;}
    const projectRouting=event.target.closest('[data-project-routing-constraint]');if(projectRouting){const prefill={destination_id:projectRouting.dataset.destinationId,owner_kind:projectRouting.dataset.ownerKind,owner_id:projectRouting.dataset.ownerId,resource_id:projectRouting.dataset.resourceId};const existing=(state.logistics?.routing_constraints||[]).find((x)=>x.destination_id===prefill.destination_id&&x.owner_kind===prefill.owner_kind&&x.owner_id===prefill.owner_id&&x.resource_id===prefill.resource_id);window.SpaceIdleLogistics?.openRoutingConstraintDialog(existing||null,prefill);return;}
    const ra=event.target.closest('[data-research-action]');if(ra){const map={start:'StartResearch',pause:'PauseResearch',resume:'ResumeResearch'},payload={research_id:ra.dataset.id};if(ra.dataset.researchAction==='start')payload.priority=Number($('#researchPriorityInput')?.value??3);try{await command(map[ra.dataset.researchAction],payload);}catch{}return;}
    const researchComparePin=event.target.closest('[data-research-compare-pin]');if(researchComparePin){const r=(state.research?.items||[]).find((row)=>row.id===researchComparePin.dataset.researchComparePin);if(!r)return;toggleComparisonPin(researchComparisonScope(r),r.execution_context_options||[],researchComparePin.dataset.comparisonKey);renderInspector();return;}
    const protoSite=event.target.closest('[data-research-prototype-site]');if(protoSite){try{await command('SetResearchPrototypeSite',{research_id:protoSite.dataset.id,stage_id:protoSite.dataset.stageId,operational_node_id:protoSite.dataset.researchPrototypeSite,surface_cell_id:protoSite.dataset.surfaceCellId||null});}catch{}return;}
    const demo=event.target.closest('[data-research-demo-site]');if(demo){try{await command('SetResearchDemonstrationSite',{research_id:demo.dataset.id,stage_id:demo.dataset.stageId,operational_node_id:demo.dataset.researchDemoSite,surface_cell_id:demo.dataset.surfaceCellId||null});}catch{}return;}
    const providerFleet=event.target.closest('[data-research-provider-set-fleet]');if(providerFleet){const card=providerFleet.closest('[data-research-provider-fleet-card]'),quantity=Number(card?.querySelector('[data-research-provider-fleet-quantity]')?.value??0);try{await command('SetResearchProviderFleetQuantity',{provider_definition_id:providerFleet.dataset.researchProviderSetFleet,operational_node_id:providerFleet.dataset.operationalNodeId,vehicle_definition_id:providerFleet.dataset.vehicleDefinitionId,quantity});banner('研究用途のFleet数量を更新しました');}catch{}return;}
    const providerPause=event.target.closest('[data-research-provider-pause]');if(providerPause){try{await command('PauseResearchProviderAssignment',{assignment_id:providerPause.dataset.researchProviderPause});}catch{}return;}
    const providerResume=event.target.closest('[data-research-provider-resume]');if(providerResume){try{await command('ResumeResearchProviderAssignment',{assignment_id:providerResume.dataset.researchProviderResume});}catch{}return;}
    const surveyProviderFleet=event.target.closest('[data-survey-provider-set-fleet]');if(surveyProviderFleet){const card=surveyProviderFleet.closest('[data-survey-provider-fleet-card]'),quantity=Number(card?.querySelector('[data-survey-provider-fleet-quantity]')?.value??0);try{await command('SetSurveyProviderFleetQuantity',{provider_definition_id:surveyProviderFleet.dataset.surveyProviderSetFleet,operational_node_id:surveyProviderFleet.dataset.operationalNodeId,vehicle_definition_id:surveyProviderFleet.dataset.vehicleDefinitionId,quantity});banner('地表調査用途のFleet数量を更新しました');}catch{}return;}
    const ea=event.target.closest('[data-exploration-action]');if(ea){const map={start:'StartScientificExploration',pause:'PauseScientificExploration',resume:'ResumeScientificExploration'},payload={exploration_id:ea.dataset.id};if(ea.dataset.explorationAction==='start')payload.priority=Number($('#explorationPriorityInput')?.value??3);try{await command(map[ea.dataset.explorationAction],payload);}catch{}return;}
    const er=event.target.closest('[data-exploration-return]');if(er){try{await command('ReturnScientificExploration',{exploration_id:er.dataset.explorationReturn});}catch{}return;}
    const eb=event.target.closest('[data-exploration-abort]');if(eb){try{await command('AbortScientificExploration',{exploration_id:eb.dataset.explorationAbort});}catch{}return;}
    const assign=event.target.closest('[data-exploration-assign]');if(assign){try{await command('AssignExplorationFleet',{exploration_id:assign.dataset.explorationAssign,vehicle_definition_id:assign.dataset.vehicleDefinitionId});}catch{}return;}
    const unassign=event.target.closest('[data-exploration-unassign]');if(unassign){try{await command('UnassignExplorationFleet',{exploration_id:unassign.dataset.explorationUnassign});}catch{}return;}
    const startSurvey=event.target.closest('[data-start-survey-campaign]');if(startSurvey){const target_cell_ids=$$('[data-survey-draft-cell]:checked').map((x)=>x.value),resource_ids=$$('[data-survey-draft-resource]:checked').map((x)=>x.value);if(!target_cell_ids.length||!resource_ids.length){banner('対象地域と資源を1つ以上選択してください','error');return;}try{const result=await command('StartSurvey',{target_cell_ids,resource_ids,goal_knowledge_level:Number($('#surveyDraftGoal')?.value??1),priority:Number($('#surveyDraftPriority')?.value??3),provider_constraint:null,observation_mode_constraint:null});await A.completeActiveDraft('survey:new');banner('地表調査を開始しました');}catch{}return;}
    const campaignAction=event.target.closest('[data-survey-campaign-action]');if(campaignAction){const map={pause:'PauseSurvey',resume:'ResumeSurvey'};try{await command(map[campaignAction.dataset.surveyCampaignAction],{campaign_id:campaignAction.dataset.id});}catch{}return;}
    const updateSurvey=event.target.closest('[data-update-survey-campaign]');if(updateSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===updateSurvey.dataset.updateSurveyCampaign);if(!c)return;const target_cell_ids=$$('[data-survey-campaign-cell]:checked').map((x)=>x.value),resource_ids=$$('[data-survey-campaign-resource]:checked').map((x)=>x.value);try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids,resource_ids,goal_knowledge_level:Number($('#surveyCampaignGoal')?.value??c.goal_knowledge_level),provider_constraint:c.provider_constraint_definition_id?{provider_definition_id:c.provider_constraint_definition_id,operational_node_id:c.provider_constraint_operational_node_id}:null,observation_mode_constraint:c.observation_mode_constraint});await A.completeActiveDraft(`survey:${c.id}`);}catch{}return;}
    const candidateDetail=event.target.closest('[data-survey-candidate-detail]');if(candidateDetail){state.inspector={type:'survey-candidate',id:`${candidateDetail.dataset.surveyCandidateDetail}@@${candidateDetail.dataset.comparisonKey}`};renderInspector();return;}
    const comparePin=event.target.closest('[data-survey-compare-pin]');if(comparePin){const campaignId=comparePin.dataset.surveyComparePin,key=comparePin.dataset.comparisonKey;const c=(state.surveys?.campaigns||[]).find((row)=>row.id===campaignId);if(!c)return;toggleComparisonPin(surveyComparisonScope(c),c.candidates||[],key);if(state.inspector?.type==='survey-candidate')renderInspector();else{state.inspector={type:'survey-campaign',id:campaignId};renderInspector();}return;}
    const constrainSurvey=event.target.closest('[data-survey-constrain-candidate]');if(constrainSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===constrainSurvey.dataset.surveyConstrainCandidate);if(!c)return;try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids:c.target_cell_ids,resource_ids:c.resource_ids,goal_knowledge_level:c.goal_knowledge_level,provider_constraint:{provider_definition_id:constrainSurvey.dataset.providerDefinitionId,operational_node_id:constrainSurvey.dataset.operationalNodeId},observation_mode_constraint:constrainSurvey.dataset.observationModeId});}catch{}return;}
    const clearSurvey=event.target.closest('[data-clear-survey-constraint]');if(clearSurvey){const c=(state.surveys?.campaigns||[]).find((row)=>row.id===clearSurvey.dataset.clearSurveyConstraint);if(!c)return;try{await command('UpdateSurvey',{campaign_id:c.id,target_cell_ids:c.target_cell_ids,resource_ids:c.resource_ids,goal_knowledge_level:c.goal_knowledge_level,provider_constraint:null,observation_mode_constraint:null});}catch{}return;}
  });

  window.SpaceIdleOperations={render};
})();
