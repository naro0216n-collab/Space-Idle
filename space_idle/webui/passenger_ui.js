(() => {
  'use strict';
  const A=window.SpaceIdleApp;
  if (!A) throw new Error('SpaceIdleApp must load before passenger_ui.js');
  const {state,esc,fmt,locationName,definitionName,resourceName,api,command,banner}=A;
  const drafts=new Map();
  const pending=new Map();
  const views=new Map();
  const statusName={pending:'未出発',active:'輸送中',completed:'完了',cancelled:'取消済み',failed:'輸送中に死亡'};
  const blockers={no_passenger_seats:'座席なし',no_source_people:'出発人員不足',seats_or_payload_limit:'座席・質量容量不足',
    operation_or_onboard_resources:'燃料・船内生活Resource不足',destination_life_support_or_housing:'到着先Housing・生命維持不足',
    transport_service_required:'成立済みTransport Serviceが必要'};
  const roots=()=>[['location',document.getElementById('passengerLocationMount')],['logistics',document.getElementById('passengerLogisticsMount')]].filter(([,el])=>el);
  const key=(kind)=>`passengers:${kind}`;
  function currentDraft(kind){
    if(!drafts.has(kind))drafts.set(kind,{origin:'',destination:'',count:'1',source:'',priority:'3',choice:'service'});
    return drafts.get(kind);
  }
  function routeOptions(kind){
    const d=currentDraft(kind),nodes=(state.world?.operational_nodes||[]).slice().sort((a,b)=>String(a.id).localeCompare(String(b.id)));
    return {nodes,origin:d.origin||state.operationalNodeId||nodes[0]?.id||''};
  }
  function render(kind,root){
    const d=currentDraft(kind),{nodes,origin}=routeOptions(kind);
    if(!nodes.length)return;
    if(kind==='location')d.origin=state.operationalNodeId||origin;
    else if(!d.origin)d.origin=origin;
    if(d.destination===d.origin||!nodes.some(row=>row.id===d.destination))d.destination=nodes.find(row=>row.id!==d.origin)?.id||'';
    const html=`<section class="decision-card passenger-decision-card"><div class="decision-card-heading"><div><span class="eyebrow">旅客移送</span><h3>一回限りの人員輸送</h3></div></div>
      <div class="form-row"><label>出発地<select data-passenger-field="origin" ${kind==='location'?'disabled':''}>${nodes.map(n=>`<option value="${esc(n.id)}" ${n.id===d.origin?'selected':''}>${esc(locationName(n.id))}</option>`).join('')}</select></label>
      <label>目的地<select data-passenger-field="destination">${nodes.filter(n=>n.id!==d.origin).map(n=>`<option value="${esc(n.id)}" ${n.id===d.destination?'selected':''}>${esc(locationName(n.id))}</option>`).join('')}</select></label>
      <label>人数<input type="number" min="1" step="1" data-passenger-field="count" value="${esc(d.count)}"></label><label>活動優先度<select data-passenger-field="priority">${[1,2,3,4,5].map(n=>`<option value="${n}" ${Number(d.priority)===n?'selected':''}>${n}</option>`).join('')}</select></label></div>
      <div class="cell-sub">人口目標とは別の有限Commandです。発車後の旅客は取消しても消えません。</div>
      <div class="form-row"><button type="button" data-passenger-preview>候補・受入条件を確認</button></div>
      <div data-passenger-options class="passenger-options"></div><div data-passenger-orders class="passenger-orders"></div></section>`;
    const existing=root.querySelector('[data-passenger-field="count"]');
    // Unchanged form remains in DOM across the game's periodic 1-second refresh.
    const formKey=`${kind}\u001f${d.origin}\u001f${nodes.map(n=>n.id).join('|')}`;
    if(root.dataset.passengerFormKey!==formKey){root.innerHTML=html;root.dataset.passengerFormKey=formKey;}
    showOptions(kind,root);showOrders(kind,root);
    const revision=state.revision;
    if(!pending.has(key(kind))&&(!views.has(key(kind))||views.get(key(kind)).revision!==revision))refreshOrders(kind,root);
  }
  function showOptions(kind,root){
    const target=root.querySelector('[data-passenger-options]');if(!target)return;
    const record=views.get('preview:'+kind);
    if(!record){target.innerHTML='<div class="cell-sub">候補の確認後、必要Resourceと出発可能人数を表示します。</div>';return;}
    const value=record.data;
    const draft=currentDraft(kind);
    const sourceChoices=(value.external_sources||[]).map(([id,remaining,quota,available])=>
      `<option value="${esc(id)}" ${draft.source===id?'selected':''}>${esc(id)} · 残員 ${fmt(remaining,0)} 人 / 上限 ${fmt(quota,0)} 人/日 / 当日 ${fmt(available,0)} 人</option>`).join('');
    const rows=(value.options||[]).map((option,index)=>`<label class="passenger-option"><input type="radio" name="passenger-option-${kind}" value="${index}" ${currentDraft(kind).choice===String(index)?'checked':''}>
      <strong>${option.mode==='service'?'定常Service':`専用便 ${esc(definitionName(option.vehicle_definition_id))}`}</strong>
      <span>所要 ${fmt(option.travel_days,0)} 日 · 出発可能 ${fmt(option.dispatchable_people,0)} 人 · 残待機 ${fmt(option.waiting_people,0)} 人 · 積載 ${fmt(option.passenger_payload_t,3)} t</span>
      <span>利用: ${esc(option.transport_allocation_ids.join(' / ')||`${option.units} 機`)}</span>
      <span>生活Resource / 運行: ${(option.resources||[]).map(([,r,a])=>`${esc(resourceName(r))} ${fmt(a,3)} t`).join(' / ')||'なし'}</span>
      ${(option.blockers||[]).length?`<span class="cell-sub">${option.blockers.map(code=>esc(blockers[code]||code)).join(' / ')}</span>`:''}</label>`).join('');
    target.innerHTML=`<div class="form-row"><label>人員供給元<select data-passenger-source><option value="" ${!draft.source?'selected':''}>Player-owned人口</option>${sourceChoices}</select></label></div>
      <div class="cell-sub">出発可能な非拘束人員・当日供給 ${fmt(value.available_source_people,0)} 人 / 到着Housing余力 ${fmt(value.destination_housing_spare,0)} 人 / 生命維持受入 ${fmt(value.destination_life_support_receivable,0)} 人${value.origin_target_deficit_after_requested_transfer===null?'':` / 移送後の供給元目標欠員 ${fmt(value.origin_target_deficit_after_requested_transfer,0)} 人`}</div>
      <div class="choice-grid">${rows||'<div class="cell-sub">利用可能な輸送能力なし</div>'}</div>
      <button type="button" data-passenger-submit ${!rows?'disabled':''}>この条件で一回だけ移送を要求</button>`;
  }
  function showOrders(kind,root){
    const el=root.querySelector('[data-passenger-orders]');if(!el)return;
    const list=views.get(key(kind))?.data?.items||[];
    const d=currentDraft(kind);
    const relevant=kind==='location'?list.filter(row=>row.origin_node_id===d.origin||row.destination_node_id===d.origin):list;
    el.innerHTML=`<h4>有限旅客移送Order</h4><div class="overview-project-list">${relevant.map(row=>`<div class="detail-card"><strong>${esc(locationName(row.origin_node_id))} → ${esc(locationName(row.destination_node_id))}</strong>
      <div class="cell-sub">${esc(statusName[row.status]||row.status)} · 要求 ${fmt(row.requested_count,0)} / 出発待ち ${fmt(row.pending_count,0)} / 輸送中 ${fmt(row.transit_count,0)} / 到着 ${fmt(row.delivered_count,0)} / 取消済み ${fmt(row.cancelled_count,0)} / 航行中死亡 ${fmt(row.deceased_count,0)} 人</div>
      <div class="cell-sub">${(row.blockers||[]).map(code=>esc(blockers[code]||code)).join(' / ')}</div>
      <button type="button" data-passenger-cancel="${esc(row.id)}" ${row.pending_count===0?'disabled':''}>未発送分を取消</button></div>`).join('')||'<div class="cell-sub">現在の有限旅客Orderなし</div>'}</div>`;
  }
  async function refreshOrders(kind,root){
    const token=key(kind);pending.set(token,true);
    try{const data=await api('/api/v1/population/passenger-transfers');views.set(token,{revision:state.revision,data});if(root.isConnected)showOrders(kind,root);}
    catch(e){root.querySelector('[data-passenger-orders]').textContent=e.message;}
    finally{pending.delete(token);}
  }
  function validRequest(kind){
    const d=currentDraft(kind),count=Number(d.count);
    if(!d.origin||!d.destination||d.origin===d.destination||!Number.isSafeInteger(count)||count<=0)throw new Error('異なる拠点と正の整数人数を指定してください');
    return {origin_node_id:d.origin,destination_node_id:d.destination,requested_count:count};
  }
  async function requestPreview(kind,root){
    const data=validRequest(kind),d=currentDraft(kind);
    const query=new URLSearchParams(data);if(d.source)query.set('source_external_provider_id',d.source);
    const view=await api('/api/v1/population/passenger-preview?'+query);
    views.set('preview:'+kind,{revision:state.revision,data:view});d.choice='0';showOptions(kind,root);
  }
  document.addEventListener('input',e=>{
    const field=e.target.closest('[data-passenger-field]');if(!field)return;
    const root=field.closest('.passenger-controls');const kind=root?.id==='passengerLocationMount'?'location':'logistics';
    currentDraft(kind)[field.dataset.passengerField]=field.value;
    if(field.dataset.passengerField!=='priority')views.delete('preview:'+kind);
  });
  document.addEventListener('change',e=>{
    const sourceField=e.target.closest('[data-passenger-source]');
    if(sourceField){
      const root=sourceField.closest('.passenger-controls'),kind=root?.id==='passengerLocationMount'?'location':'logistics';
      currentDraft(kind).source=sourceField.value;
      requestPreview(kind,root).catch(error=>banner(error.message,'error'));
      return;
    }
    const field=e.target.closest('[data-passenger-field]');if(!field)return;
    const root=field.closest('.passenger-controls'),kind=root?.id==='passengerLocationMount'?'location':'logistics';
    currentDraft(kind)[field.dataset.passengerField]=field.value;
    if(field.dataset.passengerField==='origin'){currentDraft(kind).destination='';currentDraft(kind).source='';root.dataset.passengerFormKey='';render(kind,root);}
    const radio=e.target.closest('.passenger-option input[type="radio"]');if(radio)currentDraft(kind).choice=radio.value;
  });
  document.addEventListener('change',e=>{
    const radio=e.target.closest('.passenger-option input[type="radio"]');if(!radio)return;
    const kind=radio.closest('#passengerLocationMount')?'location':'logistics';currentDraft(kind).choice=radio.value;
  });
  document.addEventListener('click',async e=>{
    const action=e.target.closest('[data-passenger-preview],[data-passenger-submit],[data-passenger-cancel]');if(!action)return;
    const root=action.closest('.passenger-controls'),kind=root?.id==='passengerLocationMount'?'location':'logistics';
    try{
      if(action.hasAttribute('data-passenger-preview'))await requestPreview(kind,root);
      else if(action.hasAttribute('data-passenger-cancel')){
        await command('CancelPassengerTransfer',{order_id:action.dataset.passengerCancel});
        await refreshOrders(kind,root);banner('未発送分を取消しました');
      }else{
        const selected=root.querySelector('.passenger-option input:checked');
        const row=views.get('preview:'+kind)?.data?.options?.[Number(selected?.value)];
        if(!row)throw new Error('輸送候補を選択してください');
        const payload={...validRequest(kind),activity_priority:Number(currentDraft(kind).priority)};
        if(currentDraft(kind).source)payload.source_external_provider_id=currentDraft(kind).source;
        if(row.mode==='dedicated')payload.capacity_source_constraint={dedicated_vehicle_definition_id:row.vehicle_definition_id,dedicated_units:row.units};
        else payload.capacity_source_constraint={transport_allocation_ids:row.transport_allocation_ids};
        await command('RequestPassengerTransfer',payload);await refreshOrders(kind,root);
        banner('有限旅客移送Orderを受け付けました');
      }
    }catch(error){banner(error.message,'error');}
  });
  window.SpaceIdlePassengers={render:()=>{for(const [kind,root] of roots())if((kind==='location'&&state.activeSection==='location'&&state.activeTab==='overview')||(kind==='logistics'&&state.activeSection==='logistics'))render(kind,root);}};
})();
