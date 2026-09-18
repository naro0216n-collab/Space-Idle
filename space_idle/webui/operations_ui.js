(() => {
  'use strict';

  const A=window.SpaceIdleApp;
  if(!A)throw new Error('SpaceIdleApp must load before operations_ui.js');
  const {state,$,$$,esc,fmt,pct,resourceName,locationName,definitionName,capabilityName,stateLabels,issueHtml,statHtml,signed,command,banner}=A;

  const section=(title,body)=>`<section class="inspector-section"><h3>${esc(title)}</h3>${body}</section>`;
  const kv=(rows)=>`<dl class="kv-grid">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  const setInspector=(title,html)=>{$('#inspectorTitle').textContent=title;$('#inspectorContent').innerHTML=html;};
  const resourceCards=(resources)=>(resources||[]).map((r)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(r.resource_id))}</span><span>${fmt(r.required_t)} t</span></div></div>`).join('')||'<div class="empty-state">追加資源なし</div>';
  const procurementPolicyLabels={immediate:'即時外部調達',standard_wait:'標準待機後に外部調達',extended_wait:'現地在庫を長く待つ'};
  const priorityLabels={1:'最低',2:'低',3:'標準',4:'高',5:'最高'};
  const priorityOptions=(selected=3)=>[1,2,3,4,5].map((level)=>`<option value="${level}" ${Number(selected)===level?'selected':''}>${level} ${priorityLabels[level]}</option>`).join('');
  const priorityName=(value)=>priorityLabels[Number(value)]?`${value} ${priorityLabels[Number(value)]}`:String(value??'—');
  const procurementPolicyName=(value)=>procurementPolicyLabels[value]||value||'—';
  const limitingHtml=(rows)=>(rows||[]).length?`<div class="issue-stack">${rows.map((factor)=>`<div class="issue"><div class="issue-title">${esc(A.userFacingText(factor))}</div></div>`).join('')}</div>`:'<span class="badge ok">なし</span>';
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
    if(p.target_kind==='facility_upgrade')return `Facility Upgrade → Lv ${fmt(p.target_level,0)}`;
    if(p.target_kind==='operational_node_founding')return 'Operational Node Founding';
    if(p.target_kind==='surface_cell_development')return 'Surface Cell開発';
    return '新規施設建設';
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
    const storageRows=(loc.storage||[]).map((s)=>`<tr><td>${esc(s.storage_pool_key)}</td><td>${fmt(s.stock_t)}</td><td>${fmt(s.physical_capacity_t)}</td><td>${fmt(s.usable_capacity_t)}</td><td>${fmt(s.free_usable_t)}</td><td>${fmt(s.unusable_occupied_t)}</td><td>${esc((s.admission_blockers||[]).map(A.userFacingText).join(' / ')||'なし')}</td></tr>`).join('');
    const capabilityRows=(loc.capabilities||[]).map((c)=>`<tr><td>${esc(capabilityName(c.id))}</td><td>${c.installed?'✓':'—'}</td><td>${c.active?'✓':'—'}</td></tr>`).join('');
    const serviceRows=(loc.service_capacities||[]).map((c)=>`<tr><td>${esc(capabilityName(c.service_type))}</td><td>${fmt(c.nominal)}</td><td>${fmt(c.enabled)}</td><td>${fmt(c.requested)}</td><td>${fmt(c.allocated)}</td><td>${fmt(c.spare)}</td><td>${esc((c.limiting_factors||[]).map(A.userFacingText).join(' / ')||'なし')}</td></tr>`).join('');
    const infra=loc.surface_infrastructure;
    const infraLoads=(infra?.load_sources||[]).map((row)=>`<div class="cell-sub">${esc(A.userFacingText(row.code))}: ${fmt(row.demand,2)}</div>`).join('')||'<div class="empty-state">追加負荷なし</div>';
    const infraLimits=(infra?.limiting_factors||[]).map((factor)=>`<span class="badge warn">${esc(A.userFacingText(factor))}</span>`).join(' ')||'<span class="badge ok">なし</span>';
    const infraImprovements=(infra?.improvement_facility_definition_ids||[]).map((id)=>`<span class="badge">${esc(definitionName(id))}</span>`).join(' ')||'<span class="badge">候補なし</span>';
    const infrastructureCard=infra?`<section class="card"><div class="card-heading"><h3>Surface Infrastructure</h3><span class="badge ${infra.fulfillment<0.999999?'warn':'ok'}">${pct(infra.fulfillment)}</span></div><div class="card-body">${kv([['Nominal',fmt(infra.nominal_capacity,2)],['Enabled',fmt(infra.available_capacity,2)],['Requested',fmt(infra.requested_capacity,2)],['Allocated',fmt(infra.allocated_capacity,2)],['Spare',fmt(infra.spare_capacity,2)],['Fulfillment',pct(infra.fulfillment)]])}<h4>主な負荷源</h4>${infraLoads}<h4>Limiting factor</h4>${infraLimits}<h4>改善可能Facility</h4>${infraImprovements}</div></section>`:'';
    const surface=loc.surface_location;
    const accessAnchors=(surface?.active_access_anchors||[]).map((row)=>`<div class="cell-sub">${esc(definitionName(row.facility_definition_id))} · ${esc(row.cell_id)}</div>`).join('')||'<div class="empty-state">Active access anchorなし</div>';
    const environmentSummary=(surface?.environment_summary||[]).map((row)=>{const global=(row.location_values||[]).map(([key,value])=>`${esc(key)}=${esc(environmentValue(value))}`).join(' · ');const cells=(row.cell_values||[]).map(([cellId,values])=>`<div class="cell-sub">${esc(cellId)}: ${(values||[]).map(([key,value])=>`${esc(key)}=${esc(environmentValue(value))}`).join(' · ')}</div>`).join('');return `<div class="detail-card"><div class="mode-title"><span>${esc(row.key)}</span><span class="badge">${esc(row.scope)}</span></div>${global?`<div class="cell-sub">Body / Node: ${global}</div>`:''}${cells}</div>`;}).join('')||'<div class="empty-state">Environment summaryなし</div>';
    const surfaceSpatialCard=surface?`<section class="card"><div class="card-heading"><h3>Surface Location</h3><span class="badge">${surface.developed_cell_ids?.length||0} Cell</span></div><div class="card-body">${kv([['Founding core cell',surface.core_cell_id],['Developed cells',(surface.developed_cell_ids||[]).join(' / ')||'—']])}<h4>Active Surface Access Anchors</h4>${accessAnchors}<h4>Physical Environment Summary</h4>${environmentSummary}</div></section>`:'';
    const extractionRows=(loc.extraction_resources||[]).map((row)=>`<tr class="selectable" data-inspect="extraction-resource" data-id="${esc(row.resource_id)}"><td>${esc(row.resource_name)}</td><td>${fmt(row.effective_opportunity,3)}</td><td>${fmt(row.installed_nominal_capacity_t_per_day,3)}</td><td>${fmt(row.output_t_per_day,3)}</td><td>${pct(row.diminishing_efficiency)}</td><td>${pct(row.marginal_efficiency)}</td><td>${pct(row.operational_fulfillment)}</td></tr>`).join('');
    const extractionCard=extractionRows?`<section class="card"><div class="card-heading"><h3>Resource Opportunity / Extraction</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>Opportunity</th><th>Installed</th><th>Actual/日</th><th>効率</th><th>限界効率</th><th>運用充足</th></tr></thead><tbody>${extractionRows}</tbody></table></div></section>`:'';
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>運用状態</h3></div><div class="card-body"><div class="stat-grid">${statHtml('電力利用率',pct(flow?.power_utilization))}${statHtml('利用可能電力',`${fmt(loc.power_allocated_mw)} MW`)}${statHtml('建設能力',`${fmt(loc.construction_capacity_per_day)} /日`)}${statHtml('進行中建設',`${loc.projects?.length||0}`)}</div></div></section><section class="card"><div class="card-heading"><h3>地点blocker</h3><span class="badge ${issues.length?'warn':'ok'}">${issues.length} 件</span></div><div class="card-body issue-stack">${issues.length?issues.slice(0,8).map(issueHtml).join(''):'<div class="empty-state">現在のblockerはありません。</div>'}</div></section>${surfaceSpatialCard}${infrastructureCard}${extractionCard}<section class="card"><div class="card-heading"><h3>Current Environment</h3></div><div class="card-body">${environmentHtml(loc.environment)}</div></section><section class="card"><div class="card-heading"><h3>Stock Capacity</h3></div><div class="table-wrap"><table><thead><tr><th>Class</th><th>在庫t</th><th>Physical</th><th>Usable</th><th>入庫可能</th><th>Usable超過</th><th>blocker</th></tr></thead><tbody>${storageRows||'<tr><td colspan="7">保管設備なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>Capability</h3></div><div class="table-wrap"><table><thead><tr><th>Capability</th><th>Installed</th><th>Active</th></tr></thead><tbody>${capabilityRows||'<tr><td colspan="3">Capabilityなし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>Service Capacity</h3></div><div class="table-wrap"><table><thead><tr><th>Service</th><th>Nominal</th><th>Enabled</th><th>Requested</th><th>Allocated</th><th>Spare</th><th>Limiting factor</th></tr></thead><tbody>${serviceRows||'<tr><td colspan="7">Service Capacityなし</td></tr>'}</tbody></table></div></section></div>`;
  }

  function renderFacilitiesTab(){
    const rows=(state.operationalNode?.facilities||[]).map((f)=>{const u=f.next_upgrade;const upgrade=u?(u.active_project_id?`案件 ${esc(u.active_project_id)}`:`→ Lv ${fmt(u.target_level,0)}`):'—';return `<tr class="selectable" data-inspect="facility" data-id="${esc(f.id)}"><td><div class="cell-main">${esc(f.display_name)}</div><div class="cell-sub">${esc(f.id)}</div></td><td>Lv ${fmt(f.level,0)}</td><td>${f.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">稼働</span>'}</td><td>${pct(f.operational_utilization)}</td><td>${pct(f.maintenance_satisfaction)}</td><td>${esc(priorityName(f.activity_priority))}</td><td>${esc(priorityName(f.maintenance_priority??3))}</td><td>${upgrade}</td><td>${(f.activation_blockers||[]).length}</td></tr>`;}).join('');
    return `<section class="card"><div class="card-heading"><h3>設備一覧</h3><span class="badge">${state.operationalNode?.facilities?.length||0}</span></div><div class="table-wrap"><table><thead><tr><th>設備</th><th>Level</th><th>状態</th><th>実効稼働</th><th>維持</th><th>活動優先度</th><th>維持優先度</th><th>Upgrade</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="9">設備なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderInventoryTab(){
    const flowMap=Object.fromEntries((state.flow?.resources||[]).map((r)=>[r.resource_id,r]));
    const rows=(state.operationalNode?.inventory||[]).filter((r)=>r.amount||r.reserved||flowMap[r.resource_id]?.local_production_per_day||flowMap[r.resource_id]?.local_consumption_per_day||flowMap[r.resource_id]?.inbound_in_transit_t||flowMap[r.resource_id]?.arrival_waiting_t).map((r)=>{const f=flowMap[r.resource_id]||{};return `<tr class="selectable" data-inspect="resource" data-id="${esc(r.resource_id)}"><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.storage_pool_key)}</div></td><td>${fmt(r.amount)}</td><td>${fmt(r.available)}</td><td>${signed(f.local_net_per_day)}</td><td>${fmt(f.inbound_in_transit_t)}</td><td>${fmt(f.outbound_in_transit_t)}</td><td>${fmt(f.arrival_waiting_t)}</td><td>${fmt(r.admission_capacity)}</td><td>${r.over_capacity>1e-9?`<span class="badge warn">${fmt(r.over_capacity)}</span>`:'—'}</td></tr>`;}).join('');
    const allocationRows=(state.operationalNode?.resource_allocations||[]).map((c)=>`<tr><td><div class="cell-main">${esc(c.display_name)}</div><div class="cell-sub">${esc(c.resource_id)}</div></td><td><div class="cell-main">${esc(A.userFacingText(c.owner_kind))}</div><div class="cell-sub">${esc(c.owner_id)}</div></td><td>${esc(A.userFacingText(c.purpose))}</td><td>${c.priority}</td><td>${fmt(c.requested,2)}</td><td>${fmt(c.allocated,2)}</td><td>${fmt(c.unmet,2)}</td></tr>`).join('');
    const allocationCard=`<section class="card"><div class="card-heading"><h3>Current Resource Allocations</h3><span class="badge ${(state.operationalNode?.resource_allocations||[]).some((c)=>Number(c.unmet)>1e-9)?'warn':'ok'}">${state.operationalNode?.resource_allocations?.length||0}</span></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>Owner</th><th>用途</th><th>Priority</th><th>Requested</th><th>Allocated</th><th>Unmet</th></tr></thead><tbody>${allocationRows||'<tr><td colspan="7">当tickのResource allocationなし</td></tr>'}</tbody></table></div></section>`;
    const currentAnalytics=state.dependencyAnalyticsCurrent;
    const forecastAnalytics=state.dependencyAnalyticsForecast;
    const currentRows=(currentAnalytics?.current_resources||[]).map((r)=>{
      const sources=(r.dependency_source_node_ids||[]).map(locationName).join(' / ')||'—';
      const limits=(r.limiting_factors||[]).map(A.userFacingText).join(' / ')||'なし';
      return `<tr><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.id)}</div></td><td>${fmt(r.production_per_day,2)}</td><td>${fmt(r.consumption_per_day,2)}</td><td>${fmt(r.demand_per_day,2)}</td><td>${r.local_coverage_ratio==null?'—':pct(r.local_coverage_ratio)}</td><td>${fmt(r.external_dependency_per_day,2)}</td><td>${fmt(r.imports_per_day,2)}</td><td>${fmt(r.exports_per_day,2)}</td><td>${fmt(r.imports_pipeline_t,2)}</td><td>${fmt(r.exports_pipeline_t,2)}</td><td>${fmt(r.unmet_demand_t,2)}</td><td>${esc(sources)}</td><td>${esc(limits)}</td></tr>`;
    }).join('');
    const currentGroupRows=(currentAnalytics?.current_resource_groups||[]).map((r)=>`<tr><td>${esc(r.display_name)}</td><td>${fmt(r.production_per_day,2)}</td><td>${fmt(r.consumption_per_day,2)}</td><td>${fmt(r.demand_per_day,2)}</td><td>${r.local_coverage_ratio==null?'—':pct(r.local_coverage_ratio)}</td><td>${fmt(r.external_dependency_per_day,2)}</td><td>${fmt(r.imports_per_day,2)}</td><td>${fmt(r.exports_per_day,2)}</td><td>${fmt(r.imports_pipeline_t,2)}</td><td>${fmt(r.exports_pipeline_t,2)}</td><td>${fmt(r.unmet_demand_t,2)}</td></tr>`).join('');
    const forecastRows=(forecastAnalytics?.forecast_resources||[]).map((r)=>{
      const sources=(r.dependency_source_node_ids||[]).map(locationName).join(' / ')||'—';
      const limits=(r.limiting_factors||[]).map(A.userFacingText).join(' / ')||'なし';
      return `<tr><td><div class="cell-main">${esc(r.display_name)}</div><div class="cell-sub">${esc(r.id)}</div></td><td>${fmt(r.planned_requirement_t,2)}</td><td>${fmt(r.recurring_consumption_per_day,2)}</td><td>${fmt(r.external_requirement_t,2)}</td><td>${fmt(r.external_recurring_dependency_per_day,2)}</td><td>${fmt(r.target_stock_t,2)}</td><td>${r.earliest_requirement_day==null?'—':fmt(r.earliest_requirement_day,0)}</td><td>${esc(sources)}</td><td>${esc(limits)}</td></tr>`;
    }).join('');
    const forecastGroupRows=(forecastAnalytics?.forecast_resource_groups||[]).map((r)=>`<tr><td>${esc(r.display_name)}</td><td>${fmt(r.planned_requirement_t,2)}</td><td>${fmt(r.recurring_consumption_per_day,2)}</td><td>${fmt(r.external_requirement_t,2)}</td><td>${fmt(r.external_recurring_dependency_per_day,2)}</td><td>${fmt(r.target_stock_t,2)}</td><td>${r.earliest_requirement_day==null?'—':fmt(r.earliest_requirement_day,0)}</td></tr>`).join('');
    const currentCard=`<section class="card"><div class="card-heading"><h3>External Dependency — CURRENT</h3><span class="badge ${(currentAnalytics?.critical_dependency_resource_ids||[]).length?'warn':'ok'}">${(currentAnalytics?.critical_dependency_resource_ids||[]).length} critical</span></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>現在生産/日</th><th>現在消費/日</th><th>現在需要/日</th><th>Local coverage</th><th>現在外部依存/日</th><th>現在流入/日</th><th>現在流出/日</th><th>Import pipeline</th><th>Export pipeline</th><th>現在未充足</th><th>依存元</th><th>Limiting factor</th></tr></thead><tbody>${currentRows||'<tr><td colspan="13">現在フローなし</td></tr>'}</tbody></table></div>${currentGroupRows?`<div class="table-wrap"><table><thead><tr><th>Resource Group</th><th>現在生産/日</th><th>現在消費/日</th><th>現在需要/日</th><th>Local coverage</th><th>現在外部依存/日</th><th>現在流入/日</th><th>現在流出/日</th><th>Import pipeline</th><th>Export pipeline</th><th>現在未充足</th></tr></thead><tbody>${currentGroupRows}</tbody></table></div>`:''}</section>`;
    const forecastCard=`<section class="card"><div class="card-heading"><h3>External Dependency — FORECAST</h3><span class="badge ${(forecastAnalytics?.critical_dependency_resource_ids||[]).length?'warn':'ok'}">${(forecastAnalytics?.critical_dependency_resource_ids||[]).length} critical</span></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>計画需要量</th><th>継続消費/日</th><th>外部必要量</th><th>継続外部依存/日</th><th>Target Stock</th><th>最早必要日</th><th>依存元</th><th>Limiting factor</th></tr></thead><tbody>${forecastRows||'<tr><td colspan="9">計画済み将来需要なし</td></tr>'}</tbody></table></div>${forecastGroupRows?`<div class="table-wrap"><table><thead><tr><th>Resource Group</th><th>計画需要量</th><th>継続消費/日</th><th>外部必要量</th><th>継続外部依存/日</th><th>Target Stock</th><th>最早必要日</th></tr></thead><tbody>${forecastGroupRows}</tbody></table></div>`:''}</section>`;
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>在庫・ローカルフロー・物流状態</h3></div><div class="table-wrap"><table><thead><tr><th>資源</th><th>在庫</th><th>利用可</th><th>Local net/日</th><th>入荷中</th><th>出荷中</th><th>到着待機</th><th>空容量</th></tr></thead><tbody>${rows||'<tr><td colspan="8">表示対象なし</td></tr>'}</tbody></table></div></section>${allocationCard}${currentCard}${forecastCard}</div>`;
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
    const pRows=projects.map((p)=>{const target=projectTargetLabel(p);return `<tr class="selectable" data-inspect="project" data-id="${esc(p.id)}"><td><div class="cell-main">${esc(p.display_name||p.facility_display_name||p.id)}</div><div class="cell-sub">${esc(target)} · ${esc(p.id)}</div></td><td>${esc(stateLabels[p.status]||p.status||(p.paused?'paused':'active'))}</td><td>${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}</td><td>${p.priority??'—'}</td><td>${esc(procurementPolicyName(p.procurement_policy))}</td><td>${(p.blockers||[]).length}</td></tr>`;}).join('');
    const optionCards=options.map((o)=>{const plan=planningOptionState(o,'建設可');return `<div class="detail-card"><div class="mode-title"><span>${esc(o.display_name)}</span><span class="badge ${plan.blockers.length?'warn':plan.canPlan?'ok':''}">${esc(plan.label)}</span></div><div class="cell-sub">工数 ${fmt(o.construction_required,0)} · 資源 ${o.resources?.length||0}種</div><div class="action-row" style="margin-top:8px"><button type="button" data-inspect="build-option" data-id="${esc(o.facility_definition_id)}">条件・詳細</button></div></div>`;}).join('');
    return `<div class="card-grid"><section class="card"><div class="card-heading"><h3>建設案件</h3><span class="badge">${projects.length}</span></div><div class="table-wrap"><table><thead><tr><th>案件</th><th>状態</th><th>進捗</th><th>優先</th><th>配分</th><th>調達</th><th>blocker</th></tr></thead><tbody>${pRows||'<tr><td colspan="7">進行中案件なし</td></tr>'}</tbody></table></div></section><section class="card"><div class="card-heading"><h3>新規建設</h3><span class="badge">${options.length}</span></div><div class="card-body">${optionCards||'<div class="empty-state">建設候補なし</div>'}</div></section></div>`;
  }

  function renderResearchTab(){
    if(!window.SpaceIdleResearchTree)return '<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="empty-state">技術ツリー描画機構を読み込めませんでした。</div></section>';
    return window.SpaceIdleResearchTree.render(state.research||{items:[],providers:[]});
  }
  function renderScientificExplorationTab(){
    const items=state.scientificExplorations?.items||[];
    const rows=items.map((x)=>{
      const rewardLeft=Math.max(0,Number(x.research_points_total||0)-Number(x.research_points_awarded||0));
      const blocked=(x.blockers||[]).length;
      const assigned=x.assigned_vehicle_definition_id?`${definitionName(x.assigned_vehicle_definition_id)} · ${fmt(x.committed_units,0)} unit`:'未割当';
      const outbound=x.outbound_latency_days==null?'—':`${fmt(x.outbound_latency_days,0)}日`;
      const returning=x.return_latency_days==null?'':` / 復路 ${fmt(x.return_latency_days,0)}日`;
      return `<tr class="selectable" data-inspect="scientific-exploration" data-id="${esc(x.id)}"><td><div class="cell-main">${esc(x.display_name)}</div><div class="cell-sub">${esc(locationName(x.origin_id))} → ${esc(locationName(x.destination_id))}</div></td><td>${esc(stateLabels[x.status]||x.status)}</td><td>${fmt(x.progress_days,1)}/${fmt(x.duration_days,1)}日<div class="cell-sub">移動 往路 ${outbound}${returning}</div></td><td>${fmt(x.research_points_awarded,1)}/${fmt(x.research_points_total,1)} RP<div class="cell-sub">当日 requested/admitted ${fmt(x.rp_requested_today,2)} / ${fmt(x.rp_admitted_today,2)}</div><div class="cell-sub">Pool headroom ${fmt(x.rp_admission_headroom,2)}</div></td><td>${esc(priorityName(x.priority??3))}</td><td>${esc(assigned)}</td><td>${blocked}</td></tr>`;
    }).join('');
    return `<section class="card"><div class="card-heading"><h3>Scientific Exploration</h3><span class="badge">${items.length}</span></div><div class="card-body"><div class="cell-sub">Vehicleを輸送へ使うか科学探査へ拘束するかを選択します。Campaign報酬は有限で、資源Surveyとは別状態です。</div></div><div class="table-wrap"><table><thead><tr><th>Campaign</th><th>状態</th><th>期間</th><th>Research Point</th><th>活動優先度</th><th>割当Fleet</th><th>blocker</th></tr></thead><tbody>${rows||'<tr><td colspan="7">Scientific Exploration候補なし</td></tr>'}</tbody></table></div></section>`;
  }

  function renderSurveyTab(){
    const assignments=state.surveys?.provider_assignments||[];
    const assignmentOptions=state.surveys?.provider_assignment_options||[];
    const assignmentCards=assignments.map((row)=>`<div class="detail-card" data-survey-provider-card><div class="mode-title"><span>${esc(definitionName(row.provider_definition_id))}</span><span>${fmt(row.committed_units,0)} unit</span></div><div class="cell-sub">${esc(locationName(row.operational_node_id))} · ${esc(definitionName(row.source_definition_id))} · Survey capacity ${fmt(row.capacity_units_per_day,2)}/日</div><div class="cell-sub">Fleet commitment ${esc(row.fleet_commitment_id)}</div><div class="form-row"><label>Fleet unit<input type="number" min="1" step="1" value="${fmt(row.committed_units,0)}" data-survey-provider-quantity data-draft-key="survey-provider:${esc(row.id)}:quantity" ${row.can_resize?'':'disabled'}></label><button type="button" data-survey-provider-resize="${esc(row.id)}" ${row.can_resize?'':'disabled'}>割当数を変更</button><button type="button" class="danger-button" data-survey-provider-release="${esc(row.id)}" ${row.can_release?'':'disabled'}>Fleet割当を解除</button></div></div>`).join('');
    const optionCards=assignmentOptions.map((row)=>`<div class="detail-card" data-survey-provider-create-card><div class="mode-title"><span>${esc(definitionName(row.provider_definition_id))}</span><span>free ${fmt(row.free_units,0)}</span></div><div class="cell-sub">${esc(locationName(row.operational_node_id))} · ${esc(definitionName(row.source_definition_id))}</div>${(row.blockers||[]).length?`<div class="issue-stack">${row.blockers.map((b)=>issueHtml(['survey_provider',b])).join('')}</div>`:''}<div class="form-row"><label>Fleet unit<input type="number" min="1" max="${Math.max(1,Number(row.free_units||0))}" step="1" value="1" data-survey-provider-create-quantity data-draft-key="survey-provider-create:${esc(row.provider_definition_id)}:quantity" ${row.can_create?'':'disabled'}></label><button type="button" data-survey-provider-create="${esc(row.provider_definition_id)}" data-operational-node-id="${esc(row.operational_node_id)}" ${row.can_create?'':'disabled'}>Survey ProviderへFleet割当</button></div></div>`).join('');
    const providerSection=`<section class="card"><div class="card-heading"><h3>Survey Provider Fleet Assignment</h3><span class="badge">${assignments.length}</span></div><div class="card-body"><div class="cell-sub">Fleet-backed Survey Providerへ継続観測能力を配備します。Campaignの停止・再開とは独立したFleet配備判断です。</div><div class="detail-stack">${assignmentCards||optionCards||'<div class="empty-state">Fleet-backed Survey Providerなし</div>'}${assignmentCards&&optionCards?optionCards:''}</div></div></section>`;
    const rows=(state.surveys?.items||[]).map((s)=>{
      const status=s.complete?'<span class="badge ok">完了</span>':s.active?(s.paused?'<span class="badge warn">停止</span>':'<span class="badge ok">探査中</span>'):'<span class="badge">未開始</span>';
      const id=`${s.cell_id}::${s.resource_id}`;
      const potential=s.visible_potential==null?'—':fmt(s.visible_potential,3);
      const precision=s.visible_potential_precision_fraction==null?'':s.visible_potential_precision_fraction<=0?' · 測定済み':` · 精度 ±${pct(s.visible_potential_precision_fraction)}`;
      return `<tr class="selectable" data-inspect="survey" data-id="${esc(id)}"><td><div class="cell-main">${esc(s.resource_name)}</div><div class="cell-sub">${esc(s.cell_label)} · 知識Lv ${s.knowledge_level}</div></td><td>${status}</td><td>${pct(s.progress_fraction)}</td><td>${fmt(s.capacity_points_per_day,2)}</td><td>${s.presence_probability==null?'—':pct(s.presence_probability)}</td><td>${potential}${precision}</td></tr>`;
    }).join('');
    return `${providerSection}<section class="card"><div class="card-heading"><h3>地表資源Survey</h3></div><div class="table-wrap"><table><thead><tr><th>資源・地域</th><th>状態</th><th>進捗</th><th>能力/日</th><th>存在確率</th><th>Resource Potential</th></tr></thead><tbody>${rows||'<tr><td colspan="6">この天体にSurvey対象なし</td></tr>'}</tbody></table></div></section>`;
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
      productionSection+=section('生産工程',kv([['現在Process',esc(industry.process_display_name||industry.process_id||'未選択')],['Process選択',industry.selection_required?'選択が必要':'確定'],['実効稼働率',pct(industry.scale)]])+processControl+`<h4>投入/日</h4>${rateCards(industry.input_rates_per_day)}<h4>生産物/日</h4>${rateCards(industry.output_rates_per_day)}<h4>limiting factor</h4>${limitingHtml(industry.limiting_factors)}`);
    }
    if(extraction){
      productionSection+=section('採掘',kv([['対象資源',esc(resourceName(extraction.resource_id))],['Nominal Capacity',`${fmt(extraction.nominal_capacity_t_per_day,3)} t/日`],['Effective Opportunity',fmt(extraction.effective_opportunity,3)],['限界効率',pct(extraction.marginal_efficiency)],['産出資源',esc(resourceName(extraction.output_resource_id))],['生産物/日',`${fmt(extraction.output_t_per_day,3)} t/日`],['実効稼働率',pct(extraction.scale)]])+`<h4>limiting factor</h4>${limitingHtml(extraction.limiting_factors)}`);
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
    setInspector(f.display_name,section('状態',kv([['ID',esc(f.id)],['定義',esc(f.definition_id)],['Level',fmt(f.level,0)],['運転',f.paused?'手動停止':'稼働'],['電力利用率',pct(f.power_utilization)],['維持充足率',pct(f.maintenance_satisfaction)],['実効稼働率',pct(f.operational_utilization)],['活動優先度',esc(priorityName(f.activity_priority))],['維持優先度',esc(priorityName(f.maintenance_priority??3))],...researchRows]))+productionSection+section('建造・Upgrade投入資源',investment)+section('維持資源需要',maintenance)+section('Blocker',blockers.length?`<div class="issue-stack">${blockers.map(issueHtml).join('')}</div>`:'<div class="badge ok">なし</div>')+upgradeSection+section('運用操作',`<div class="action-stack"><button type="button" data-command="${f.paused?'ResumeFacility':'PauseFacility'}" data-facility-id="${esc(f.id)}">${f.paused?'設備を再開':'設備を停止'}</button><div class="form-row"><label>活動優先度<select id="facilityPriorityInput" data-draft-key="facility:${esc(f.id)}:activity-priority">${priorityOptions(f.activity_priority??3)}</select></label><button type="button" data-set-facility-activity-priority="${esc(f.id)}">活動優先度を適用</button></div><div class="form-row"><label>維持優先度<select id="maintenancePriorityInput" data-draft-key="facility:${esc(f.id)}:maintenance-priority">${priorityOptions(f.maintenance_priority??3)}</select></label><button type="button" data-set-maintenance-priority="${esc(f.id)}">維持優先を適用</button></div></div>`));
    return true;
  }
  function renderExtractionResourceInspector(id){
    const row=state.operationalNode?.extraction_resources?.find((item)=>item.resource_id===id);if(!row)return false;
    const infra=state.operationalNode?.surface_infrastructure;
    const infraLimit=infra?.limiting_factors?.includes('surface_infrastructure');
    setInspector(row.resource_name,section('Resource Opportunity / Extraction',kv([['Effective Opportunity',fmt(row.effective_opportunity,3)],['Installed Nominal Capacity',`${fmt(row.installed_nominal_capacity_t_per_day,3)} t/日`],['Actual Extraction',`${fmt(row.output_t_per_day,3)} t/日`],['Diminishing efficiency',pct(row.diminishing_efficiency)],['Marginal efficiency',pct(row.marginal_efficiency)],['Operational fulfillment',pct(row.operational_fulfillment)]]))+section('Surface Infrastructure',infra?kv([['Fulfillment',pct(infra.fulfillment)],['Limiting factor',infraLimit?'<span class="badge warn">Surface Infrastructure</span>':'<span class="badge ok">なし</span>']]):'<div class="empty-state">非地表Location</div>'));
    return true;
  }
  function renderResourceInspector(id){
    const inv=state.operationalNode?.inventory?.find((x)=>x.resource_id===id),f=state.flow?.resources?.find((x)=>x.resource_id===id);if(!inv)return false;
    setInspector(inv.display_name,section('在庫',kv([['在庫',fmt(inv.amount)],['予約',fmt(inv.reserved)],['利用可能',fmt(inv.available)],['Physical',fmt(inv.physical_capacity)],['Usable',fmt(inv.usable_capacity)],['入庫可能',fmt(inv.admission_capacity)],['超過',fmt(inv.over_capacity)],['制限要因',esc((inv.limiting_factors||[]).map(A.userFacingText).join(' / ')||'なし')],['入庫blocker',esc((inv.admission_blockers||[]).map(A.userFacingText).join(' / ')||'なし')],['Storage pool',esc(inv.storage_pool_key)]]))+section('フロー',kv([['生産/日',signed(f?.local_production_per_day)],['消費/日',signed(f?.local_consumption_per_day)],['Local net/日',signed(f?.local_net_per_day)],['入荷中',fmt(f?.inbound_in_transit_t)],['出荷中',fmt(f?.outbound_in_transit_t)],['到着待機',fmt(f?.arrival_waiting_t)]])));
    return true;
  }
  function renderProjectInspector(id){
    const p=state.projects?.items?.find((x)=>x.id===id);if(!p)return false;
    const target=projectTargetLabel(p);
    const readiness=p.projected_material_readiness_day==null?'未確定':`Day ${fmt(p.projected_material_readiness_day,0)}`;
    const targetRows=[['ID',esc(p.id)],['種別',esc(target)],['状態',esc(stateLabels[p.status]||p.status||(p.paused?'paused':'active'))],['優先度',esc(p.priority??'—')],['施工充足',pct(p.construction_fulfillment??1)],['Projected Material Readiness',esc(readiness)],['調達方針',esc(procurementPolicyName(p.procurement_policy))],['工数',`${fmt(p.progress??p.construction_done??0)}/${fmt(p.construction_required??0)}`]];
    if(p.target_facility_id)targetRows.push(['対象設備',esc(p.target_facility_id)]);
    if(p.target_cell_id)targetRows.push(['対象Cell',esc(surfaceCellLabel(p.target_cell_id))]);
    if(p.target_location_id)targetRows.push(['対象Location',esc(locationName(p.target_location_id))]);
    if(p.completed_facility_id)targetRows.push(['反映設備',esc(p.completed_facility_id)]);
    const foundingProject=p.target_kind==='operational_node_founding';
    const committedLabel=foundingProject?'準備済':'投入済';
    const resourceRows=(p.resources||[]).map((r)=>{
      const securedLabel=p.target_kind==="operational_node_founding"
        ? `展開payload ${fmt(r.staged_t||0)} t`
        : `予約済み ${fmt(r.reserved_t||0)} t`;
      return `<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(r.resource_id))}</span><span>${fmt(r.required_t)} t</span></div><div class="cell-sub">${securedLabel} · ${committedLabel} ${fmt(r.committed_t)} t · 不足 ${fmt(r.shortage_t)} t</div></div>`;
    }).join('');
    const requirements=(state.logistics?.requirements||[]).filter((d)=>d.owner_kind===(foundingProject?'founding':'project')&&d.owner_id===p.id);
    const requirementHtml=requirements.length?requirements.map((d)=>{const forecast=d.forecast_requirement_day==null?'指定なし':`Day ${fmt(d.forecast_requirement_day,0)}`,arrival=d.projected_arrival_day==null?(d.earliest_confirmed_arrival_day==null?'未確定':`Day ${fmt(d.earliest_confirmed_arrival_day,0)}`):`Day ${fmt(d.projected_arrival_day,0)}`;const source=d.selected_source_id?locationName(d.selected_source_id):'未選択';const services=(d.selected_service_ids||[]).map(definitionName).join(' → ')||'経路未確定';const constrained=Boolean(d.routing_constraint_source_id||(d.routing_constraint_via_node_ids||[]).length||(d.routing_constraint_transport_allocation_ids||[]).length);return `<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(d.resource_id))}</span><span>${fmt(d.remaining_t)} t 待ち</span></div><div class="cell-main">${esc(source)} → ${esc(locationName(d.destination_id))}</div><div class="cell-sub">${esc(services)} · 輸送系内 ${fmt(d.pipeline_t)} t</div><div class="cell-sub">必要時期 ${esc(forecast)} · 予測到着 ${esc(arrival)}${d.selected_latency_days==null?'':` · latency ${fmt(d.selected_latency_days,1)}日`}${d.selected_handoff_count==null?'':` · handoff ${fmt(d.selected_handoff_count,0)}`}</div>${constrained?`<div class="cell-sub">Hard constraint: source ${esc(d.routing_constraint_source_id?locationName(d.routing_constraint_source_id):'自動')} / via ${esc((d.routing_constraint_via_node_ids||[]).map(locationName).join(', ')||'なし')} / allocation ${esc((d.routing_constraint_transport_allocation_ids||[]).join(', ')||'なし')}</div>`:''}<button type="button" data-project-routing-constraint data-owner-kind="${esc(d.owner_kind)}" data-owner-id="${esc(d.owner_id)}" data-destination-id="${esc(d.destination_id)}" data-resource-id="${esc(d.resource_id)}">${constrained?'Routing Constraint編集':'Routing Constraint設定'}</button></div>`;}).join(''):'<div class="empty-state">現在のSupply Requirementなし</div>';
    const settingsDisabled=p.settings_editable?'':'disabled';
    const procurementDisabled=p.procurement_editable?'':'disabled';
    const procurementOptions=(p.procurement_policy_options||[]).map((value)=>`<option value="${esc(value)}" ${value===p.procurement_policy?'selected':''}>${esc(procurementPolicyName(value))}</option>`).join('');
    const projectControls=foundingProject
      ? `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeFounding':'PauseFounding'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'準備再開':'準備停止'}</button><div class="form-row"><label>優先度<select id="projectPriorityInput" ${settingsDisabled}>${priorityOptions(p.priority??3)}</select></label><button type="button" data-set-founding-priority="${esc(p.id)}" ${settingsDisabled}>優先度を適用</button></div><button type="button" class="danger-button" data-command="CancelFounding" data-project-id="${esc(p.id)}" ${settingsDisabled}>Deployment取消</button></div>`
      : `<div class="action-stack"><button type="button" data-command="${p.paused?'ResumeBuild':'PauseBuild'}" data-project-id="${esc(p.id)}" ${settingsDisabled}>${p.paused?'建設再開':'建設停止'}</button><div class="form-row"><label>優先度<select id="projectPriorityInput" data-draft-key="project:${esc(p.id)}:priority" ${settingsDisabled}>${priorityOptions(p.priority??3)}</select></label><button type="button" data-set-project-priority="${esc(p.id)}" ${settingsDisabled}>優先度を適用</button></div><div class="form-row"><label>調達方針<select id="projectProcurementTimingPolicy" data-draft-key="project:${esc(p.id)}:procurement" ${procurementDisabled}>${procurementOptions}</select></label><button type="button" data-set-project-procurement="${esc(p.id)}" ${procurementDisabled}>方針を適用</button></div><button type="button" class="danger-button" data-command="CancelBuild" data-project-id="${esc(p.id)}" ${settingsDisabled}>案件取消</button></div>`;
    const foundingDecision=foundingProject?section('Founding Decision State',kv([['Target type',esc(p.founding_target_type||'—')],['Deployment phase',esc(p.deployment_phase||p.status||'—')],['Manifest readiness',p.manifest_ready?'<span class="badge ok">ready</span>':'<span class="badge warn">not ready</span>'],['Fleet commitment',p.fleet_commitment_id?esc(p.fleet_commitment_id):'—']])+`<h3>Knowledge Requirement</h3>${(p.founding_knowledge_requirements||[]).map((row)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(row.subject_resource_id))}</span><span class="badge ${row.met?'ok':'warn'}">${fmt(row.current_level,0)} / ${fmt(row.minimum_level,0)}</span></div><div class="cell-sub">${esc(surfaceCellLabel(row.target_cell_id))}</div></div>`).join('')||'<div class="empty-state">Knowledge Requirementなし</div>'}<h3>Site blocker</h3>${(p.site_blockers||[]).length?`<div class="issue-stack">${p.site_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}<h3>Movement blocker</h3>${(p.movement_blockers||[]).length?`<div class="issue-stack">${p.movement_blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>'}`):'';
    setInspector(p.display_name||p.facility_display_name||p.id,section('案件',kv(targetRows))+foundingDecision+section('必要資源 / 調達',resourceRows||'<div class="empty-state">追加資源なし</div>')+section('Supply Requirement',requirementHtml)+section('Limiting factor',limitingHtml(p.limiting_factors||[]))+section('Blocker',(p.blockers||[]).length?`<div class="issue-stack">${p.blockers.map(issueHtml).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',projectControls));
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
  function researchSiteLabel(site){if(!site)return '未選択';return `${locationName(site.operational_node_id)}${site.surface_cell_id?` / ${site.surface_cell_id}`:''}`;}
  function siteOptionsHtml(r,kind){
    const options=r.execution_context_options||[],selected=r.execution_context;
    if(!options.length)return '<div class="empty-state">候補地点なし</div>';
    return options.map((site)=>{const blockers=site.blockers||[],blocked=blockers.length,isSelected=Boolean(selected)&&site.operational_node_id===selected.operational_node_id&&(site.surface_cell_id||null)===(selected.surface_cell_id||null),canSelect=Boolean(site.can_select),attr=kind==='prototype'?'data-research-prototype-site':'data-research-demo-site';const badge=isSelected?'選択中':canSelect?(blocked?`選択可 · ${blocked} 稼働blocker`:'選択可'):`${blocked||1} blocker`;return `<div class="detail-card ${isSelected?'is-usable':''}"><div class="mode-title"><span>${esc(researchSiteLabel(site))}</span><span class="badge ${blocked?'warn':canSelect||isSelected?'ok':''}">${badge}</span></div>${blocked?`<div class="issue-stack">${blockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:''}<button type="button" ${attr}="${esc(site.operational_node_id)}" data-surface-cell-id="${esc(site.surface_cell_id||'')}" data-id="${esc(r.id)}" data-stage-id="${esc(r.current_stage_id||'')}" ${!canSelect||isSelected?'disabled':''}>${kind==='prototype'?'試作地点に設定':'実証地点に設定'}</button></div>`;}).join('');
  }
  function prototypeResourceHtml(r){
    const rows=r.stage_resources||[];
    if(!rows.length)return '<div class="empty-state">追加試作資材なし</div>';
    return rows.map((x)=>`<div class="detail-card"><div class="mode-title"><span>${esc(resourceName(x.resource_id))}</span><span>${fmt(x.reserved_t)} / ${fmt(x.required_t)} t reserved</span></div><div class="cell-sub">current claim ${fmt(x.requested_t)} t · allocated ${fmt(x.allocated_t)} t · unmet ${fmt(x.unmet_t)} t · pipeline ${fmt(x.pipeline_t)} t</div></div>`).join('');
  }
  function experienceHtml(r){
    const rows=r.operational_experience||[];
    if(!rows.length)return '<div class="empty-state">Operational Experience要件なし</div>';
    return rows.map((x)=>`<div class="detail-card"><div class="mode-title"><span>${esc(x.category_id)}</span><span>${fmt(x.current,1)} / ${fmt(x.required,1)}</span></div><div class="cell-sub">未充足 ${fmt(x.unmet,1)}</div></div>`).join('');
  }
  function renderResearchInspector(id){
    const r=state.research?.items?.find((x)=>x.id===id);if(!r)return false;
    const action=lifecycleButton({domain:'research',id:r.id,canStart:r.can_start,canPause:r.can_pause,canResume:r.can_resume,complete:r.status==='complete',startLabel:'研究Project開始',pauseLabel:'研究停止',resumeLabel:'研究再開',completeLabel:'研究完了'});
    const phaseBlockers=researchBlockers(r);let phase='';
    if(r.status==='theory'){
      phase=section('Theory',kv([['進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)} RP`],['RP requested',`${fmt(r.rp_requested,2)} /日`],['RP allocated',`${fmt(r.rp_allocated,2)} /日`],['Theory残り',`${fmt(r.rp_remaining,1)} RP`],['Research execution requested',`${fmt(r.execution_requested,2)} /日`],['Research execution allocated',`${fmt(r.execution_allocated,2)} /日`]]));
    }else if(r.status==='prototype'){
      phase=section('Prototype',`<div class="cell-sub">地点 ${esc(researchSiteLabel(r.execution_context))} · Research execution ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'prototype')}<h3>Resource Claim / staging / pipeline</h3>${prototypeResourceHtml(r)}`);
    }else if(r.status==='demonstration'){
      phase=section('Demonstration',`<div class="cell-sub">進捗 ${fmt(r.stage_progress,1)}/${fmt(r.stage_required,1)}日 · 地点 ${esc(researchSiteLabel(r.execution_context))} · Research execution ${fmt(r.execution_allocated,2)}/${fmt(r.execution_requested,2)} /日</div>${siteOptionsHtml(r,'demonstration')}`);
    }else if(r.status==='operational_experience'){
      phase=section('Operational Experience',experienceHtml(r));
    }
    const stageNames={theory:'Theory',prototype:'Prototype',demonstration:'Demonstration',operational_experience:'Operational Experience'};
    const stageSequence=(r.stages||[]).map((x)=>`${stageNames[x.stage_type]||x.stage_type} [${x.stage_id||'—'}]`).join(' → ')||'—';
    const startRows=[['Stage構成',esc(stageSequence)],['保有RP',fmt(state.research?.stored_points,1)],['RP Pool容量',fmt(state.research?.storage_capacity_points,1)]];
    if((r.stages||[]).some((x)=>x.stage_type==='theory'))startRows.splice(1,0,['Theory総必要RP',fmt(r.total_theory_research_point_cost,1)]);
    const startState=['available','locked'].includes(r.status)?section('開始条件',kv(startRows)):'';
    const priorityControl=`<div class="form-row"><label>研究優先度<select id="researchPriorityInput" data-draft-key="research:${esc(r.id)}:priority">${priorityOptions(r.priority??3)}</select></label>${r.can_set_priority?`<button type="button" data-set-research-priority="${esc(r.id)}">優先度を適用</button>`:''}</div>`;
    setInspector(r.display_name,section('状態',kv([['段階',esc(stateLabels[r.status]||r.status)],['Stage ID',esc(r.current_stage_id||'—')],['優先度',fmt(r.priority,0)],['Stage進捗',`${fmt(r.stage_progress,1)} / ${fmt(r.stage_required,1)}`],['RP requested / allocated',`${fmt(r.rp_requested,2)} / ${fmt(r.rp_allocated,2)}`],['Execution requested / allocated',`${fmt(r.execution_requested,2)} / ${fmt(r.execution_allocated,2)}`]]))+section('前提',(r.prerequisites||[]).length?(r.prerequisites||[]).map((x)=>`<span class="badge">${esc(definitionName(x))}</span>`).join(' '):'<span class="badge ok">なし</span>')+startState+section('現在のblocker',phaseBlockers.length?`<div class="issue-stack">${phaseBlockers.map((x)=>issueHtml(['research',x[1]||x])).join('')}</div>`:'<span class="badge ok">なし</span>')+phase+section('研究操作',`<div class="action-stack">${priorityControl}${action}</div>`));
    return true;
  }
  function renderScientificExplorationInspector(id){
    const x=state.scientificExplorations?.items?.find((row)=>row.id===id);if(!x)return false;
    const vehicleRows=(x.fleet_options||[]).map((v)=>{
      const blockers=v.blockers||[];const selected=v.vehicle_definition_id===x.assigned_vehicle_definition_id;
      const badge=selected?'予約中':blockers.length?'不適合':v.can_assign?'割当可':'Fleet不足';
      return `<div class="detail-card"><div class="mode-title"><span>${esc(v.display_name)}</span><span class="badge ${selected||v.can_assign?'ok':blockers.length?'warn':''}">${badge}</span></div><div class="cell-sub">${esc(locationName(v.operational_node_id))} · total ${fmt(v.total_units,0)} / free ${fmt(v.free_units,0)} / required ${fmt(v.required_units,0)}</div><div class="cell-sub">往路 ${v.outbound_latency_days==null?'—':`${fmt(v.outbound_latency_days,0)}日`}${v.return_latency_days==null?'':` / 復路 ${fmt(v.return_latency_days,0)}日`}</div>${blockers.length?`<div class="issue-stack" style="margin-top:7px">${blockers.map((b)=>issueHtml(['exploration',b])).join('')}</div>`:''}<div class="action-row" style="margin-top:8px"><button type="button" data-exploration-assign="${esc(x.id)}" data-vehicle-definition-id="${esc(v.vehicle_definition_id)}" ${v.can_assign?'':'disabled'}>Fleetを割り当て</button></div></div>`;
    }).join('')||'<div class="empty-state">Fleet候補なし</div>';
    const inputs=(x.consumable_resources||[]).map(([rid,amount])=>`${esc(resourceName(rid))} ${fmt(amount)}t`).join(' / ')||'追加消耗資源なし';
    const operations=(x.movement_operations||[]).map(([op,dv])=>`${esc(A.operationName(op))} ${fmt(dv,2)} km/s`).join(' / ')||'Fleet割当前は未確定';
    const vehicleCapabilities=(x.required_vehicle_capabilities||[]).map((id)=>esc(capabilityName(id))).join(' / ')||'追加Vehicle能力なし';
    const blockers=x.blockers||[];
    const transitionLabels={start:'開始',assign_fleet:'Fleet割当',continue:'継続',pause:'停止',resume:'再開',unassign_fleet:'Fleet割当解除'};
    const transitions=(x.transition_options||[]).map((option)=>transitionLabels[option]||option).join(' / ')||'なし';
    const dispositionLabels={return_to_origin_then_release:'帰還後Fleet解放',release_at_destination:'到着地点でFleet解放'};
    const disposition=dispositionLabels[x.completion_disposition]||x.completion_disposition||'—';
    let action=lifecycleButton({domain:'exploration',id:x.id,canStart:x.can_start,canPause:x.can_pause,canResume:x.can_resume,complete:x.status==='complete',startLabel:'Campaign開始',pauseLabel:'停止',resumeLabel:'再開',completeLabel:'Campaign完了'});
    if(x.can_unassign)action+=`<button type="button" data-exploration-unassign="${esc(x.id)}">Fleet割当解除</button>`;
    setInspector(x.display_name,
      section('Campaign',kv([['出発',esc(locationName(x.origin_id))],['対象/到着',esc(locationName(x.destination_id))],['往路latency',x.outbound_latency_days==null?'未確定':`${fmt(x.outbound_latency_days,0)}日`],['復路latency',x.return_latency_days==null?(x.assigned_vehicle_definition_id?'なし':'未確定'):`${fmt(x.return_latency_days,0)}日`],['Campaign所要期間',`${fmt(x.duration_days,1)}日`],['進捗',`${fmt(x.progress_days,1)}日`],['RP budget / awarded',`${fmt(x.research_points_total,1)} / ${fmt(x.research_points_awarded,1)}`],['RP/日',fmt(x.research_points_per_day,2)],['当日RP requested / admitted',`${fmt(x.rp_requested_today,2)} / ${fmt(x.rp_admitted_today,2)}`],['RP admission headroom',fmt(x.rp_admission_headroom,2)],['RP admission blocker',x.rp_admission_blocker?esc(A.userFacingText(x.rp_admission_blocker)):'なし'],['必要unit',fmt(x.required_units,0)],['活動優先度',esc(priorityName(x.priority??3))],['Fleet commitment',x.fleet_commitment_id?esc(x.fleet_commitment_id):'なし'],['割当Fleet',x.assigned_vehicle_definition_id?`${esc(definitionName(x.assigned_vehicle_definition_id))} · ${fmt(x.committed_units,0)} unit`:'未割当'],['完了時処理',esc(disposition)],['現在の遷移候補',esc(transitions)]]))+
      section('必要条件',`<div class="cell-sub">Operation: ${operations}</div><div class="cell-sub">Minimum Payload: ${fmt(x.minimum_payload_t,2)} t</div><div class="cell-sub">Vehicle Capability: ${vehicleCapabilities}</div><div class="cell-sub">消耗資源: ${inputs}</div><h3>${esc(locationName(x.origin_id))} の地点条件</h3>${siteRequirementsHtml(x.origin_requirements)}<h3>${esc(locationName(x.destination_id))} の地点条件</h3>${siteRequirementsHtml(x.destination_requirements)}`)+
      section('現在のblocker',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(['exploration',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+
      section('Fleet適合性',vehicleRows)+
      section('操作',`<div class="action-stack"><div class="form-row"><label>活動優先度<select id="explorationPriorityInput" data-draft-key="exploration:${esc(x.id)}:priority" ${(x.can_start||x.can_set_priority)?'':'disabled'}>${priorityOptions(x.priority??3)}</select></label><button type="button" data-set-exploration-priority="${esc(x.id)}" ${x.can_set_priority?'':'disabled'}>優先度を適用</button></div>${action||'<span class="badge">操作なし</span>'}</div>`)
    );
    return true;
  }

  function renderSurveyInspector(id){
    const s=state.surveys?.items?.find((x)=>`${x.cell_id}::${x.resource_id}`===id);if(!s)return false;
    const blockers=s.blockers||[],priorityEditable=s.can_start||s.can_set_priority,priority=s.priority??3,startOptions=s.start_options||[];
    const actions=lifecycleButton({domain:'survey',id,canStart:s.can_start,canPause:s.can_pause,canResume:s.can_resume,complete:s.complete,startLabel:'探査開始',pauseLabel:'探査停止',resumeLabel:'探査再開',completeLabel:'探査完了'});
    const potential=s.visible_potential==null?'—':fmt(s.visible_potential,3);
    const precision=s.visible_potential_precision_fraction==null?'—':s.visible_potential_precision_fraction<=0?'測定済み':`±${pct(s.visible_potential_precision_fraction)}`;
    const assignment=(state.surveys?.provider_assignments||[]).find((row)=>row.provider_definition_id===s.provider_definition_id&&row.operational_node_id===s.provider_operational_node_id);
    const startSelect=startOptions.length?`<div class="form-row"><label>Provider / Mode / Goal<select id="surveyStartOption" data-draft-key="survey:${esc(id)}:start-option">${startOptions.map((option,index)=>`<option value="${index}" ${option.can_start?'':'disabled'}>${esc(definitionName(option.provider_definition_id))} · ${esc(option.observation_mode_id)} · Knowledge ${fmt(option.target_knowledge_level,0)} · ${esc(option.provider_source_kind)}</option>`).join('')}</select></label></div><div class="detail-stack">${startOptions.map((option)=>`<div class="cell-sub">${esc(definitionName(option.provider_definition_id))} / ${esc(option.observation_mode_id)} / K${fmt(option.target_knowledge_level,0)} · capacity ${fmt(option.capacity_points_per_day,2)} · minimum source ${fmt(option.minimum_source_units,0)}${(option.blockers||[]).length?` · ${esc((option.blockers||[]).map((b)=>A.userFacingText(b)).join(' / '))}`:' · 開始可'}</div>`).join('')}</div>`:'<div class="cell-sub">現在の拠点から選択可能なSurvey Provider / Mode / Goalはありません。</div>';
    setInspector(`${s.resource_name} · ${s.cell_label}`,section('探査状態',kv([['進捗',pct(s.progress_fraction)],['知識レベル',String(s.knowledge_level)],['目標Knowledge',String(s.target_knowledge_level)],['Survey能力/日',fmt(s.capacity_points_per_day,2)],['Service要求/割当',`${fmt(s.requested_service_points_per_day,2)} / ${fmt(s.allocated_service_points_per_day,2)}`],['優先度',String(priority)],['存在確率',s.presence_probability==null?'—':pct(s.presence_probability)],['Resource Potential',potential],['推定精度',precision],['探査実施拠点',s.provider_operational_node_id?esc(locationName(s.provider_operational_node_id)):'—'],['Provider',s.provider_definition_id?esc(definitionName(s.provider_definition_id)):'—'],['Provider種別',s.provider_source_kind?esc(s.provider_source_kind):'—'],['Observation Mode',s.observation_mode_id?esc(s.observation_mode_id):'—'],['Provider Fleet Assignment',assignment?`${fmt(assignment.committed_units,0)} unit · ${esc(assignment.fleet_commitment_id)}`:'—']]))+section('開始候補',startSelect)+section('現在のblocker',blockers.length?`<div class="issue-stack">${blockers.map((b)=>issueHtml(['survey',b])).join('')}</div>`:'<span class="badge ok">なし</span>')+section('操作',`<div class="action-stack">${actions}<div class="form-row"><label>優先度<select id="surveyPriorityInput" data-draft-key="survey:${esc(id)}:priority" ${priorityEditable?'':'disabled'}>${priorityOptions(priority)}</select></label><button data-set-survey-priority="${esc(id)}" ${s.can_set_priority?'':'disabled'}>優先度を適用</button></div></div>`));return true;
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
    const handlers={facility:renderFacilityInspector,resource:renderResourceInspector,'extraction-resource':renderExtractionResourceInspector,project:renderProjectInspector,'build-option':renderBuildOptionInspector,research:renderResearchInspector,'scientific-exploration':renderScientificExplorationInspector,survey:renderSurveyInspector,'surface-cell':renderSurfaceCellInspector};
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
    renderActiveTab();renderInspector();
  }

  document.addEventListener('click',async(event)=>{
    if(state.activeView!=='operations')return;
    const tab=event.target.closest('[data-tab]');if(tab){state.activeTab=tab.dataset.tab;state.inspector=null;render();if(state.activeTab==='surface'){try{await A.loadUiSnapshot({preserveInteraction:false});}catch(e){banner(e.message,'error');}}return;}
    const inspect=event.target.closest('[data-inspect]');if(inspect){state.inspector={type:inspect.dataset.inspect,id:inspect.dataset.id};if(inspect.dataset.inspect==='surface-cell')render();else{renderInspector();$$('#operationsTabContent tr').forEach((tr)=>tr.classList.toggle('is-selected',tr.dataset.id===inspect.dataset.id));}return;}
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
    const providerCreate=event.target.closest('[data-research-provider-create]');if(providerCreate){const card=providerCreate.closest('[data-research-provider-create-card]'),quantity=Number(card?.querySelector('[data-research-provider-create-quantity]')?.value??1),priority=Number(card?.querySelector('[data-research-provider-create-priority]')?.value??3);try{await command('CreateResearchProviderAssignment',{provider_definition_id:providerCreate.dataset.researchProviderCreate,operational_node_id:providerCreate.dataset.operationalNodeId,quantity,priority});banner('FleetをResearch Providerへ割り当てました');}catch{}return;}
    const providerResize=event.target.closest('[data-research-provider-resize]');if(providerResize){const card=providerResize.closest('[data-research-provider-card]'),quantity=Number(card?.querySelector('[data-research-provider-quantity]')?.value??0);try{await command('ResizeResearchProviderAssignment',{assignment_id:providerResize.dataset.researchProviderResize,quantity});}catch{}return;}
    const providerPriority=event.target.closest('[data-research-provider-set-priority]');if(providerPriority){const card=providerPriority.closest('[data-research-provider-card]'),priority=Number(card?.querySelector('[data-research-provider-priority]')?.value??3);try{await command('SetResearchProviderAssignmentPriority',{assignment_id:providerPriority.dataset.researchProviderSetPriority,priority});}catch{}return;}
    const providerPause=event.target.closest('[data-research-provider-pause]');if(providerPause){try{await command('PauseResearchProviderAssignment',{assignment_id:providerPause.dataset.researchProviderPause});}catch{}return;}
    const providerResume=event.target.closest('[data-research-provider-resume]');if(providerResume){try{await command('ResumeResearchProviderAssignment',{assignment_id:providerResume.dataset.researchProviderResume});}catch{}return;}
    const providerRelease=event.target.closest('[data-research-provider-release]');if(providerRelease){try{await command('ReleaseResearchProviderAssignment',{assignment_id:providerRelease.dataset.researchProviderRelease});banner('Research ProviderのFleet commitmentを解放しました');}catch{}return;}
    const surveyProviderCreate=event.target.closest('[data-survey-provider-create]');if(surveyProviderCreate){const card=surveyProviderCreate.closest('[data-survey-provider-create-card]'),quantity=Number(card?.querySelector('[data-survey-provider-create-quantity]')?.value??1);try{await command('CreateSurveyProviderAssignment',{provider_definition_id:surveyProviderCreate.dataset.surveyProviderCreate,operational_node_id:surveyProviderCreate.dataset.operationalNodeId,quantity});banner('FleetをSurvey Providerへ割り当てました');}catch{}return;}
    const surveyProviderResize=event.target.closest('[data-survey-provider-resize]');if(surveyProviderResize){const card=surveyProviderResize.closest('[data-survey-provider-card]'),quantity=Number(card?.querySelector('[data-survey-provider-quantity]')?.value??0);try{await command('ResizeSurveyProviderAssignment',{assignment_id:surveyProviderResize.dataset.surveyProviderResize,quantity});}catch{}return;}
    const surveyProviderRelease=event.target.closest('[data-survey-provider-release]');if(surveyProviderRelease){try{await command('ReleaseSurveyProviderAssignment',{assignment_id:surveyProviderRelease.dataset.surveyProviderRelease});banner('Survey ProviderのFleet commitmentを解放しました');}catch{}return;}
    const ea=event.target.closest('[data-exploration-action]');if(ea){const map={start:'StartScientificExploration',pause:'PauseScientificExploration',resume:'ResumeScientificExploration'},payload={exploration_id:ea.dataset.id};if(ea.dataset.explorationAction==='start')payload.priority=Number($('#explorationPriorityInput')?.value??3);try{await command(map[ea.dataset.explorationAction],payload);}catch{}return;}
    const ep=event.target.closest('[data-set-exploration-priority]');if(ep){try{await command('SetScientificExplorationPriority',{exploration_id:ep.dataset.setExplorationPriority,priority:Number($('#explorationPriorityInput').value)});}catch{}return;}
    const assign=event.target.closest('[data-exploration-assign]');if(assign){try{await command('AssignExplorationFleet',{exploration_id:assign.dataset.explorationAssign,vehicle_definition_id:assign.dataset.vehicleDefinitionId});}catch{}return;}
    const unassign=event.target.closest('[data-exploration-unassign]');if(unassign){try{await command('UnassignExplorationFleet',{exploration_id:unassign.dataset.explorationUnassign});}catch{}return;}
    const sa=event.target.closest('[data-survey-action]');if(sa){const row=(state.surveys?.items||[]).find((x)=>`${x.cell_id}::${x.resource_id}`===sa.dataset.id);if(!row)return;const action=sa.dataset.surveyAction;const map={start:'StartSurvey',pause:'PauseSurvey',resume:'ResumeSurvey'};const payload={cell_id:row.cell_id,resource_id:row.resource_id};if(action==='start'){const option=(row.start_options||[])[Number($('#surveyStartOption')?.value??0)];if(!option||!option.can_start){banner('開始可能なSurvey Provider / Mode / Goalを選択してください','error');return;}payload.provider_operational_node_id=option.provider_operational_node_id;payload.provider_definition_id=option.provider_definition_id;payload.observation_mode_id=option.observation_mode_id;payload.target_knowledge_level=option.target_knowledge_level;payload.priority=Number($('#surveyPriorityInput')?.value??3);}try{await command(map[action],payload);}catch{}return;}
    const sp=event.target.closest('[data-set-survey-priority]');if(sp){const row=(state.surveys?.items||[]).find((x)=>`${x.cell_id}::${x.resource_id}`===sp.dataset.setSurveyPriority);if(!row)return;try{await command('SetSurveyPriority',{cell_id:row.cell_id,resource_id:row.resource_id,priority:Number($('#surveyPriorityInput').value)});}catch{}return;}
  });

  window.SpaceIdleOperations={render};
})();
