(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const speedButtons = () => Array.from(document.querySelectorAll('[data-time-speed]'));
  let lastDay = null;
  let autoRefreshInFlight = false;

  function renderSession(session) {
    if (!session) return;
    const day = Number(session.day);
    const dayEl = $('#dayValue');
    if (dayEl && Number.isFinite(day)) dayEl.textContent = day.toLocaleString('ja-JP');
    const revisionEl = $('#revisionValue');
    if (revisionEl && session.revision !== undefined) revisionEl.textContent = session.revision;

    const paused = Boolean(session.time_paused);
    const speed = Number(session.time_speed_multiplier || 1);
    const pauseButton = $('#timePauseButton');
    if (pauseButton) {
      pauseButton.textContent = paused ? '▶ 再開' : '⏸ 一時停止';
      pauseButton.setAttribute('aria-pressed', paused ? 'true' : 'false');
    }
    speedButtons().forEach((button) => {
      const selected = Number(button.dataset.timeSpeed) === speed;
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
      button.disabled = selected;
    });
    const stateEl = $('#timeState');
    if (stateEl) {
      stateEl.textContent = session.automatic_progress_enabled === false
        ? '自動進行無効'
        : paused ? `停止中 · ${speed}×` : `自動進行 · ${speed}×`;
    }

    if (lastDay !== null && day !== lastDay && !document.body.classList.contains('is-busy')) {
      refreshVisibleContext();
    }
    lastDay = day;
  }

  async function readSession() {
    const response = await fetch('/api/v1/session', {headers: {'Accept': 'application/json'}, cache: 'no-store'});
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const payload = await response.json();
    renderSession(payload.data);
    return payload.data;
  }

  async function setTimeControl(payload) {
    const response = await fetch('/api/v1/time-control', {
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      cache: 'no-store',
      body: JSON.stringify(payload),
    });
    const document = await response.json();
    if (!response.ok) throw new Error(document?.error?.message || `${response.status} ${response.statusText}`);
    renderSession(document.data);
    refreshVisibleContext();
  }

  function refreshVisibleContext() {
    if (autoRefreshInFlight) return;
    const button = $('#refreshButton');
    if (!button || document.body.classList.contains('is-busy')) return;
    autoRefreshInFlight = true;
    button.click();
    window.setTimeout(() => { autoRefreshInFlight = false; }, 750);
  }

  function suppressAutomaticRefreshBanner() {
    const banner = $('#statusBanner');
    if (!banner) return;
    const observer = new MutationObserver(() => {
      if (autoRefreshInFlight && banner.textContent === '最新状態を取得しました') {
        banner.hidden = true;
      }
    });
    observer.observe(banner, {childList: true, characterData: true, subtree: true, attributes: true});
  }

  document.addEventListener('click', async (event) => {
    const pauseButton = event.target.closest('#timePauseButton');
    if (pauseButton) {
      try {
        const session = await readSession();
        await setTimeControl({paused: !Boolean(session.time_paused)});
      } catch (error) {
        console.error(error);
      }
      return;
    }
    const speedButton = event.target.closest('[data-time-speed]');
    if (speedButton) {
      try {
        await setTimeControl({speed_multiplier: Number(speedButton.dataset.timeSpeed)});
      } catch (error) {
        console.error(error);
      }
    }
  });

  suppressAutomaticRefreshBanner();
  readSession().catch(console.error);
  window.setInterval(() => {
    if (!document.hidden) readSession().catch(console.error);
  }, 1000);
})();
