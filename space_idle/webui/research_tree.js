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
    available:'利用可能', active:'稼働', paused:'停止', locked:'未解禁', complete:'完了',
    theory:'理論研究', prototype:'試作', demonstration:'実証',
  };

  function blockers(item) {
    if (item.status === 'prototype') return item.prototype_blockers || [];
    if (item.status === 'demonstration') return item.demonstration_blockers || [];
    return item.theory_blockers || [];
  }

  function progress(item) {
    if (item.status === 'complete') return {ratio:1, text:'完了'};
    if (item.status === 'prototype') return {ratio:1, text:'Theory完了 · 試作待ち'};
    if (item.status === 'demonstration') {
      const required = Number(item.demonstration_required_days || 0);
      const done = Number(item.demonstration_done_days || 0);
      return {ratio:required > 0 ? done / required : 0, text:`実証 ${fmt(done,0)}/${fmt(required,0)}日`};
    }
    const required = Number(item.theory_required || 0);
    const done = Number(item.theory_done || 0);
    return {ratio:required > 0 ? done / required : 0, text:`Theory ${fmt(done)}/${fmt(required)}`};
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

  function render(items, capacityPointsPerDay) {
    const existingScroller = document.getElementById('researchTreeScroll');
    if (existingScroller) {
      scrollLeft = existingScroller.scrollLeft;
      scrollTop = existingScroller.scrollTop;
    }
    const restoreLeft = scrollLeft;
    const restoreTop = scrollTop;

    if (!items.length) {
      return '<section class="card"><div class="card-heading"><h3>技術ツリー</h3></div><div class="research-tree-empty">研究定義なし</div></section>';
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
        <span class="research-node-meta">前提 ${prerequisiteCount} · blocker ${blockerCount} · 適格能力 ${fmt(item.eligible_capacity_points_per_day,2)}/日</span>
        <span class="research-node-progress"><span>${esc(phase.text)}</span>${item.status === 'complete' ? '' : `<span>配分 ${fmt(item.allocation_weight,2)}</span>`}</span>
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
    return `<section class="card"><div class="card-heading"><h3>技術ツリー</h3><span class="badge">研究能力 ${fmt(capacityPointsPerDay,2)}/日 · 完了 ${completed}/${items.length}</span></div><div id="researchTreeScroll" class="research-tree-scroll"><div id="researchTree" class="research-tree-stage" style="width:${graph.width}px;height:${graph.height}px"><svg class="research-tree-links" viewBox="0 0 ${graph.width} ${graph.height}" aria-hidden="true">${links.join('')}</svg>${nodes}</div></div></section>`;
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
