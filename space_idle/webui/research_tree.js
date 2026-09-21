(() => {
  'use strict';

  let selectedId = null;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;',
  }[char]));
  const fmt = (value, digits = 1) => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('ja-JP', {maximumFractionDigits: digits})
    : '—';
  const statusLabels = {
    available:'利用可能', locked:'未解禁', complete:'完了',
    theory:'理論', prototype:'試作', demonstration:'実証', operational_experience:'運用経験',
  };

  function blockers(item) {
    return item.current_blockers || [];
  }

  function progress(item) {
    if (item.status === 'complete') return {ratio:1, text:'完了'};
    const required = Number(item.stage_required || 0);
    const done = Number(item.stage_progress || 0);
    if (['theory','prototype','demonstration','operational_experience'].includes(item.status)) {
      const label = statusLabels[item.status] || item.status;
      return {ratio:required > 0 ? done / required : 0, text:`${label} ${fmt(done,1)}/${fmt(required,1)}`};
    }
    const firstStage = (item.stages || [])[0];
    const firstType = firstStage?.stage_type;
    const firstLabel = statusLabels[firstType] || firstType || '未定義';
    if (firstType === 'theory') {
      return {ratio:0, text:`開始: ${firstLabel} · 必要RP ${fmt(item.total_theory_research_point_cost,1)}`};
    }
    return {ratio:0, text:`開始: ${firstLabel}`};
  }


  function layout(items) {
    const byId = new Map(items.map((item) => [item.id, item]));
    const memo = new Map();
    const visiting = new Set();
    const depthOf = (id) => {
      if (memo.has(id)) return memo.get(id);
      if (visiting.has(id)) return 0;
      visiting.add(id);
      const item = byId.get(id);
      const parents = (item?.prerequisites || []).filter((parentId) => byId.has(parentId));
      const depth = parents.length ? 1 + Math.max(...parents.map(depthOf)) : 0;
      visiting.delete(id);
      memo.set(id, depth);
      return depth;
    };

    const levels = new Map();
    for (const item of items) {
      const depth = depthOf(item.id);
      if (!levels.has(depth)) levels.set(depth, []);
      levels.get(depth).push(item);
    }
    for (const level of levels.values()) {
      level.sort((a, b) => a.display_name.localeCompare(b.display_name, 'ja'));
    }

    const nodeWidth = 232;
    const nodeHeight = 116;
    const columnGap = 74;
    const rowGap = 26;
    const padding = 22;
    const maxDepth = Math.max(0, ...levels.keys());
    const maxRows = Math.max(1, ...Array.from(levels.values(), (level) => level.length));
    const width = Math.max(680, padding * 2 + (maxDepth + 1) * nodeWidth + maxDepth * columnGap);
    const height = Math.max(480, padding * 2 + maxRows * nodeHeight + (maxRows - 1) * rowGap);
    const positions = new Map();

    for (let depth = 0; depth <= maxDepth; depth += 1) {
      const level = levels.get(depth) || [];
      const blockHeight = level.length * nodeHeight + Math.max(0, level.length - 1) * rowGap;
      const y0 = Math.max(padding, (height - blockHeight) / 2);
      level.forEach((item, index) => {
        positions.set(item.id, {
          x: padding + depth * (nodeWidth + columnGap),
          y: y0 + index * (nodeHeight + rowGap),
        });
      });
    }
    return {byId, positions, nodeWidth, nodeHeight, width, height};
  }

  function providerHtml(providers, providerFleet) {
    const app = window.SpaceIdleApp;
    const definitionName = (id) => app?.definitionName?.(id) || id || '—';
    const locationName = (id) => app?.locationName?.(id) || id || '—';
    const issueText = (row) => app?.constraintSummary?.(row) || '実行条件を確認してください';
    const providerRows = providers.length ? `<div class="research-provider-grid">${providers.map((provider) => {
      const blocked = (provider.blockers || []).length;
      const isFleet = provider.source_kind === 'fleet';
      const sourceId = isFleet ? provider.source_definition_id : provider.facility_definition_id || provider.source_definition_id;
      const sourceLabel = definitionName(sourceId);
      const levelLabel = provider.level == null ? `${fmt(provider.committed_units,0)} 機` : `Lv ${fmt(provider.level,0)}`;
      const admitted = Number(provider.admitted_generation_points_per_day || 0);
      const controls = isFleet ? `<div class="action-stack research-provider-actions">
        <div class="form-row">${app.prioritySegmentedHtml(provider.priority,{inputAttributes:`data-research-provider-priority data-priority-direct="research-provider" data-priority-id="${esc(provider.id)}"`,label:'配備優先度'})}</div>
        <div class="action-row"><button type="button" data-research-provider-pause="${esc(provider.id)}" ${provider.can_pause?'':'disabled'}>停止</button><button type="button" data-research-provider-resume="${esc(provider.id)}" ${provider.can_resume?'':'disabled'}>再開</button></div>
      </div>` : '';
      return `<div class="detail-card research-provider-card" data-research-provider-card="${esc(provider.id)}">
        <div class="mode-title"><span>${esc(sourceLabel)}</span><span class="badge ${blocked ? 'warn' : 'ok'}">Tier ${fmt(provider.tier,0)} · ${levelLabel}</span></div>
        <div class="cell-sub">${esc(locationName(provider.operational_node_id))} · RP要求 ${fmt(provider.generation_points_per_day,2)}/日 · 受入 ${fmt(admitted,2)}/日</div>
        <div class="cell-sub">RP貯蔵 ${fmt(provider.storage_capacity_points,1)} · 研究実行 ${fmt(provider.research_execution_per_day,2)}/日</div>
        ${blocked ? `<div class="issue-stack">${(provider.blockers||[]).map((row)=>`<div class="issue warn"><span>${esc(issueText(row))}</span></div>`).join('')}</div>` : ''}
        ${controls}
      </div>`;
    }).join('')}</div>` : '<div class="research-tree-empty research-provider-empty">現在利用できる研究能力はありません。</div>';

    const fleetRows = (providerFleet || []).length ? `<div class="research-provider-grid">${providerFleet.map((row) => {
      const blocked = (row.blockers || []).length;
      return `<div class="detail-card research-provider-card" data-research-provider-fleet-card>
        <div class="mode-title"><span>${esc(definitionName(row.vehicle_definition_id))}</span><span class="badge ${row.can_set_quantity?'ok':'warn'}">Tier ${fmt(row.tier,0)} · 配備 ${fmt(row.committed_units,0)} · 空き ${fmt(row.free_units,0)}</span></div>
        <div class="cell-sub">${esc(locationName(row.operational_node_id))} · ${esc(definitionName(row.provider_definition_id))}</div>
        ${blocked ? `<div class="issue-stack">${(row.blockers||[]).map((item)=>`<div class="issue warn"><span>${esc(issueText(item))}</span></div>`).join('')}</div>` : ''}
        <div class="form-row"><label>研究へ配備する機数<input type="number" min="0" max="${Math.max(0,Number(row.max_units||0))}" step="1" value="${fmt(row.committed_units,0)}" data-research-provider-fleet-quantity ${row.can_set_quantity?'':'disabled'}></label><button type="button" data-research-provider-set-fleet="${esc(row.provider_definition_id)}" data-vehicle-definition-id="${esc(row.vehicle_definition_id)}" data-operational-node-id="${esc(row.operational_node_id)}" ${row.can_set_quantity?'':'disabled'}>配備数を適用</button></div>
      </div>`;
    }).join('')}</div>` : '<div class="empty-state">Fleetを使う研究能力はありません。</div>';
    return `<div class="research-provider-sections"><section><h4>現在の研究能力</h4>${providerRows}</section><section><h4>Fleetによる研究能力</h4>${fleetRows}</section></div>`;
  }

  function render(research) {
    const items = research?.items || [];
    const providers = research?.providers || [];
    const stored = Number(research?.stored_points || 0);
    const capacity = Number(research?.storage_capacity_points || 0);
    const generation = Number(research?.generation_points_per_day || 0);
    const admittedGeneration = Number(research?.admitted_generation_points_per_day || 0);
    const providerFleet = research?.provider_fleet || [];
    const overCapacity = Boolean(research?.over_capacity);
    const rpStrip = `<div class="research-rp-strip"><div><span>保有RP</span><strong>${fmt(stored,1)}</strong></div><div><span>貯蔵上限</span><strong>${fmt(capacity,1)}</strong></div><div><span>生成要求</span><strong>${fmt(generation,2)}/日</strong></div><div><span>受入可能</span><strong>${fmt(admittedGeneration,2)}/日</strong></div><span class="badge ${overCapacity ? 'warn' : 'ok'}">${overCapacity ? '容量超過' : '貯蔵可能'}</span></div>`;
    const providerSummary = `<section class="card research-provider-summary"><div class="card-heading"><div><h3>研究能力の配備</h3><div class="cell-sub">研究先を選んだ後、必要な場合だけ研究能力やFleet配備を調整します。</div></div></div><div class="card-body">${providerHtml(providers, providerFleet)}</div></section>`;

    if (!items.length) {
      return `<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div>${rpStrip}<div class="research-tree-empty">研究定義なし</div></section>${providerSummary}`;
    }

    const graph = layout(items);
    const links = [];
    for (const item of items) {
      const target = graph.positions.get(item.id);
      if (!target) continue;
      for (const prerequisiteId of item.prerequisites || []) {
        const source = graph.positions.get(prerequisiteId);
        if (!source) continue;
        const x1 = source.x + graph.nodeWidth;
        const y1 = source.y + graph.nodeHeight / 2;
        const x2 = target.x;
        const y2 = target.y + graph.nodeHeight / 2;
        const bend = (x1 + x2) / 2;
        const complete = graph.byId.get(prerequisiteId)?.status === 'complete';
        links.push(`<path class="research-tree-link${complete ? ' is-complete' : ''}" d="M ${x1} ${y1} C ${bend} ${y1}, ${bend} ${y2}, ${x2} ${y2}" />`);
      }
    }

    const nodes = items.map((item) => {
      const pos = graph.positions.get(item.id);
      const state = statusLabels[item.status] || item.status;
      const phase = progress(item);
      const blockerCount = blockers(item).length;
      const prerequisiteCount = (item.prerequisites || []).length;
      const selected = selectedId === item.id;
      return `<button type="button" class="research-node status-${esc(item.status)}${selected ? ' is-selected' : ''}" data-inspect="research" data-id="${esc(item.id)}" style="left:${pos.x}px;top:${pos.y}px" aria-label="${esc(item.display_name)} ${esc(state)}">
        <span class="research-node-head"><span class="research-node-title">${esc(item.display_name)}</span><span class="badge ${item.status === 'complete' ? 'ok' : blockerCount ? 'warn' : ''}">${esc(state)}</span></span>
        <span class="research-node-meta">前提 ${prerequisiteCount} · 制約 ${blockerCount} · 優先度 ${fmt(item.priority,0)}</span>
        <span class="research-node-progress"><span>${esc(phase.text)}</span>${item.status==='theory'?`<span>RP ${fmt(item.rp_allocated,1)}/${fmt(item.rp_requested,1)} /日</span>`:''}</span>
        <span class="progress-track"><span class="progress-bar" style="width:${Math.max(0, Math.min(100, phase.ratio * 100))}%"></span></span>
      </button>`;
    }).join('');

    const completed = items.filter((item) => item.status === 'complete').length;
    const tree = `<section class="card research-tree-card"><div class="card-heading"><div><h3>技術ツリー</h3><div class="cell-sub">技術を選択すると、右側に前提・進行段階・実行条件・制約を表示します。</div></div><span class="badge">完了 ${completed}/${items.length}</span></div>${rpStrip}<div id="researchTreeScroll" class="research-tree-scroll" data-preserve-scroll="research-tree"><div id="researchTree" class="research-tree-stage" style="width:${graph.width}px;height:${graph.height}px"><svg class="research-tree-links" viewBox="0 0 ${graph.width} ${graph.height}" aria-hidden="true">${links.join('')}</svg>${nodes}</div></div></section>`;
    return `${tree}${providerSummary}`;
  }

  document.addEventListener('click', (event) => {
    const node = event.target.closest?.('.research-node[data-id]');
    if (node) {
      selectedId = node.dataset.id;
      document.querySelectorAll('.research-node').forEach((candidate) => {
        candidate.classList.toggle('is-selected', candidate.dataset.id === selectedId);
      });
      return;
    }
    const tab = event.target.closest?.('[data-tab]');
    if (tab && tab.dataset.tab !== 'research') selectedId = null;
  }, true);

  window.SpaceIdleResearchTree = {render};
})();
