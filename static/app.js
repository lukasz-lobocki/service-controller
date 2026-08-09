const POLL_MS = 5000;
const SERVICES = window.__SERVICES__ || [];

const rack = document.getElementById('rack');
const tmpl = document.getElementById('panel-template');
const panels = {}; // service id -> { els, busy }

function fmtSince(raw) {
  if (!raw) return '—';
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw;
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function showError(els, msg) {
  if (!msg) {
    els['error-banner'].classList.remove('show');
    els['error-banner'].textContent = '';
    return;
  }
  els['error-banner'].textContent = msg;
  els['error-banner'].classList.add('show');
}

function buildPanels() {
  for (const svc of SERVICES) {
    const node = tmpl.content.firstElementChild.cloneNode(true);
    node.dataset.id = svc.id;

    const els = {};
    node.querySelectorAll('[data-el]').forEach((n) => { els[n.dataset.el] = n; });

    els.label.textContent = svc.label;
    els['unit-name'].textContent = svc.unit;

    panels[svc.id] = { els, busy: false };

    els['toggle-btn'].addEventListener('click', () => act(svc.id, els['toggle-btn'].dataset.verb));
    els['restart-btn'].addEventListener('click', () => act(svc.id, 'restart'));

    rack.appendChild(node);
  }
}

function render(id, status) {
  const panel = panels[id];
  if (!panel || panel.busy) return;
  const { els } = panel;
  const state = status.active_state;

  els['state-word'].textContent = state.toUpperCase();
  els['sub-state'].textContent = status.sub_state;
  els['enabled-state'].textContent = status.enabled_state;
  els['since'].textContent = status.is_active ? fmtSince(status.since) : '—';

  els.led.classList.toggle('pulse', status.is_active);

  if (status.is_active) {
    els.led.style.setProperty('--led-color', 'var(--led-active)');
    els.led.style.setProperty('--led-glow', 'var(--led-active-glow)');
    els['state-word'].style.color = 'var(--led-active)';
  } else if (status.is_failed) {
    els.led.style.setProperty('--led-color', 'var(--led-failed)');
    els.led.style.setProperty('--led-glow', 'var(--led-failed-glow)');
    els['state-word'].style.color = 'var(--led-failed)';
  } else if (status.is_transitioning) {
    els.led.style.setProperty('--led-color', 'var(--led-warn)');
    els.led.style.setProperty('--led-glow', 'transparent');
    els['state-word'].style.color = 'var(--led-warn)';
  } else {
    els.led.style.setProperty('--led-color', 'var(--led-inactive)');
    els.led.style.setProperty('--led-glow', 'transparent');
    els['state-word'].style.color = 'var(--text-dim)';
  }

  if (status.is_active || status.is_transitioning) {
    els['toggle-btn'].textContent = status.is_transitioning ? '…' : 'Stop';
    els['toggle-btn'].className = 'btn-primary action-stop';
    els['toggle-btn'].dataset.verb = 'stop';
  } else {
    els['toggle-btn'].textContent = 'Start';
    els['toggle-btn'].className = 'btn-primary action-start';
    els['toggle-btn'].dataset.verb = 'start';
  }
  els['toggle-btn'].disabled = status.is_transitioning || !status.ok;
  els['restart-btn'].disabled = !status.is_active || !status.ok;

  showError(els, status.ok ? null : (status.error || 'failed to read unit status'));
  els['last-updated'].textContent = `updated ${new Date().toLocaleTimeString()}`;
}

async function pollAll() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    for (const id of Object.keys(data)) render(id, data[id]);
  } catch (e) {
    for (const id of Object.keys(panels)) {
      showError(panels[id].els, 'lost contact with llama-control backend');
    }
  }
}

async function act(id, verb) {
  const panel = panels[id];
  if (!panel || panel.busy) return;
  panel.busy = true;

  const { els } = panel;
  els['toggle-btn'].disabled = true;
  els['restart-btn'].disabled = true;
  els['toggle-btn'].textContent = verb === 'start' ? 'Starting…' : verb === 'stop' ? 'Stopping…' : 'Restarting…';

  try {
    const res = await fetch(`/api/${id}/${verb}`, { method: 'POST' });
    const data = await res.json();
    panel.busy = false;
    if (!data.ok) showError(els, data.error || `${verb} failed`);
    render(id, data.status);
  } catch (e) {
    panel.busy = false;
    showError(els, `${verb} request failed`);
  } finally {
    pollAll();
  }
}

buildPanels();
pollAll();
setInterval(pollAll, POLL_MS);
