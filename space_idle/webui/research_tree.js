(() => {
  'use strict';

  let selectedId = null;
  let scrollLeft = 0;
  let scrollTop = 0;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;',
  }[char]));
  const fmt = (value, digits = 1) => Number.isFinite(Number(value))
    ? Number(value).toLocaleString('ja-JP', {maximumFractionDigits: digits})
    : '—';
  const statusLabels = {
    available:'利用可能', locked:'未解禁', complete:'完了',
    prototype:'試作', demonstration:'実証',
  };

  function blockers(item) {
    if (item.status === 'prototype') return item.prototype_blockers || [];
    if (item.status === 'demonstration') return item.demonstration_blockers || [];
    return item.start_blockers || [];
  }

  function progress(item) {
    if (item.status === 'complete') return {ratio:1, text:'完了'};
    if (item.status === 'prototype') return {ratio:0, text:'RP支払済み · 試作待ち'};
    if (item.status === 'demonstration') {
      const required = Number(item.demonstration_required_days || 0);
      const done = Number(item.demonstration_done_days || 0);
      return {ratio:required > 0 ? done / required : 0, text:`実証 ${fmt(done,0)}/${fmt(required,0)}日`};
    }
    return {ratio:0, text:`必要RP ${fmt(item.research_point_cost,1)}`};
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

  function providerHtml(providers) {
    if (!providers.length) return '<div class="research-tree-empty">研究設備なし</div>';
    return `<div class="research-provider-grid">${providers.map((provider) => {
      const blocked = (provider.blockers || []).length;
      return `<div class="route-mode-card">
        <div class="mode-title"><span>${esc(provider.facility_definition_id)}</span><span class="badge ${blocked ? 'warn' : 'ok'}">Tier ${fmt(provider.tier,0)} · Lv ${fmt(provider.level,0)}</span></div>
        <div class="cell-sub">${esc(provider.location_id)} · RP ${fmt(provider.generation_points_per_day,2)}/日 · 貯蔵 ${fmt(provider.storage_capacity_points,1)}</div>
        ${blocked ? `<div class="cell-sub">${blocked} blocker</div>` : ''}
      </div>`;
    }).join('')}</div>`;
  }

  function render(research) {
    const items = research?.items || [];
    const providers = research?.providers || [];
    const existingScroller = document.getElementById('researchTreeScroll');
    if (existingScroller) {
      scrollLeft = existingScroller.scrollLeft;
      scrollTop = existingScroller.scrollTop;
    }
    const restoreLeft = scrollLeft;
    const restoreTop = scrollTop;

    const stored = Number(research?.stored_points || 0);
    const capacity = Number(research?.storage_capacity_points || 0);
    const generation = Number(research?.generation_points_per_day || 0);
    const overCapacity = Boolean(research?.over_capacity);
    const summary = `<section class="card"><div class="card-heading"><h3>Research Point</h3><span class="badge ${overCapacity ? 'warn' : 'ok'}">${overCapacity ? '容量超過' : '貯蔵可能'}</span></div><div class="card-body"><div class="stat-grid"><div class="stat-box"><span>保有RP</span><strong>${fmt(stored,1)}</strong></div><div class="stat-box"><span>利用可能容量</span><strong>${fmt(capacity,1)}</strong></div><div class="stat-box"><span>生成</span><strong>${fmt(generation,2)}/日</strong></div><div class="stat-box"><span>研究設備</span><strong>${providers.length}</strong></div></div>${providerHtml(providers)}</div></section>`;

    if (!items.length) {
      return `${summary}<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="research-tree-empty">研究定義なし</div></section>`;
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
      const affordable = stored + 1e-9 >= Number(item.research_point_cost || 0);
      return `<button type="button" class="research-node status-${esc(item.status)}${selected ? ' is-selected' : ''}" data-inspect="research" data-id="${esc(item.id)}" style="left:${pos.x}px;top:${pos.y}px" aria-label="${esc(item.display_name)} ${esc(state)}">
        <span class="research-node-head"><span class="research-node-title">${esc(item.display_name)}</span><span class="badge ${item.status === 'complete' ? 'ok' : blockerCount ? 'warn' : ''}">${esc(state)}</span></span>
        <span class="research-node-meta">前提 ${prerequisiteCount} · blocker ${blockerCount} · RP ${fmt(item.research_point_cost,1)}</span>
        <span class="research-node-progress"><span>${esc(phase.text)}</span>${['available','locked'].includes(item.status) ? `<span>${affordable ? 'RP充足' : 'RP不足'}</span>` : ''}</span>
        <span class="progress-track"><span class="progress-bar" style="width:${Math.max(0, Math.min(100, phase.ratio * 100))}%"></span></span>
      </button>`;
    }).join('');

    requestAnimationFrame(() => {
      const scroller = document.getElementById('researchTreeScroll');
      if (scroller) {
        scroller.scrollLeft = restoreLeft;
        scroller.scrollTop = restoreTop;
      }
    });

    const completed = items.filter((item) => item.status === 'complete').length;
    const tree = `<section class="card"><div class="card-heading"><h3>技術ツリー</h3><span class="badge">完了 ${completed}/${items.length}</span></div><div id="researchTreeScroll" class="research-tree-scroll"><div id="researchTree" class="research-tree-stage" style="width:${graph.width}px;height:${graph.height}px"><svg class="research-tree-links" viewBox="0 0 ${graph.width} ${graph.height}" aria-hidden="true">${links.join('')}</svg>${nodes}</div></div></section>`;
    return `${summary}${tree}`;
  }

  document.addEventListener('scroll', (event) => {
    if (event.target?.id === 'researchTreeScroll') {
      scrollLeft = event.target.scrollLeft;
      scrollTop = event.target.scrollTop;
    }
  }, true);

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
