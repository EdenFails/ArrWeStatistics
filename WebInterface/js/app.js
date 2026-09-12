const state = {
  isInitialized: false,
  isAuthenticated: false,
  services: [],
  telemetry: [],
  pollTimer: null,
  pollIntervalMs: 5000,
};

async function api(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });

  if (res.status === 401) {
    state.isAuthenticated = false;
    stopPolling();
    showView('login');
    throw new Error('Authentication required');
  }

  const payload = await res.json();
  if (!res.ok) {
    throw new Error(payload.detail || payload.message || `HTTP ${res.status}`);
  }
  return payload;
}

function showView(viewName) {
  document.getElementById('view-setup').classList.add('hidden');
  document.getElementById('view-login').classList.add('hidden');
  document.getElementById('view-dashboard').classList.add('hidden');

  if (viewName === 'setup') {
    document.getElementById('view-setup').classList.remove('hidden');
    document.getElementById('setup-password').focus();
  } else if (viewName === 'login') {
    document.getElementById('view-login').classList.remove('hidden');
    document.getElementById('login-password').focus();
  } else if (viewName === 'dashboard') {
    document.getElementById('view-dashboard').classList.remove('hidden');
  }
}

async function checkInitStatus() {
  try {
    const s = await api('/api/auth/status');
    state.isInitialized = s.is_initialized;
    state.isAuthenticated = s.is_authenticated;

    if (!state.isInitialized) {
      showView('setup');
    } else if (!state.isAuthenticated) {
      showView('login');
    } else {
      showView('dashboard');
      startPolling();
      loadServices();
    }
  } catch (err) {
    showView('login');
  }
}

async function handleSetupSubmit(e) {
  e.preventDefault();
  const pw = document.getElementById('setup-password').value;
  const errBox = document.getElementById('setup-error');
  errBox.classList.add('hidden');

  try {
    await api('/api/auth/setup', {
      method: 'POST',
      body: JSON.stringify({ password: pw }),
    });
    state.isInitialized = true;
    state.isAuthenticated = true;
    showView('dashboard');
    startPolling();
    loadServices();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove('hidden');
  }
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const pw = document.getElementById('login-password').value;
  const errBox = document.getElementById('login-error');
  errBox.classList.add('hidden');

  try {
    await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password: pw }),
    });
    state.isAuthenticated = true;
    showView('dashboard');
    startPolling();
    loadServices();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove('hidden');
  }
}

async function handleLogout() {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } catch (err) {}
  state.isAuthenticated = false;
  stopPolling();
  closeSettings();
  showView('login');
}

async function pollTelemetry(force = false) {
  if (!state.isAuthenticated) return;
  const statusTag = document.getElementById('telemetry-status-tag');

  try {
    const res = await api(`/api/telemetry?force=${force}`);
    state.telemetry = res.telemetry || [];
    renderTelemetryCards();
    updateAggregates();
    if (statusTag) {
      statusTag.textContent = 'ACTIVE';
      statusTag.className = 'tag tag-ok';
    }
  } catch (err) {
    if (statusTag && state.isAuthenticated) {
      statusTag.textContent = 'UNREACHABLE';
      statusTag.className = 'tag tag-bad';
    }
  }
}

function startPolling() {
  stopPolling();
  pollTelemetry(true);
  state.pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') {
      pollTelemetry(false);
    }
  }, state.pollIntervalMs);
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && state.isAuthenticated) {
    pollTelemetry(true);
  }
});

function renderTelemetryCards() {
  const container = document.getElementById('cards-container');
  if (!state.telemetry || state.telemetry.length === 0) {
    container.innerHTML = `
      <div class="empty-state">No services registered or enabled. Open Services menu to configure targets.</div>
    `;
    return;
  }

  container.innerHTML = state.telemetry.map(item => UI.renderCard(item)).join('');
}

function updateAggregates() {
  let dl = 0;
  let up = 0;
  let streams = 0;
  let reqs = 0;

  for (const item of state.telemetry) {
    if (item.status !== 'online') continue;
    const d = item.data || {};
    const t = item.service_type;

    if (t === 'qbittorrent') {
      dl += d.dl_speed_bytes || 0;
      up += d.up_speed_bytes || 0;
    } else if (t === 'sabnzbd') {
      dl += d.speed_bytes_sec || 0;
    } else if (t === 'jellyfin') {
      streams += d.active_stream_count || 0;
    } else if (t === 'jellyseer' || t === 'jellyseerr') {
      reqs += d.pending_requests || 0;
    }
  }

  document.getElementById('sum-dl-rate').textContent = fmtSpeed(dl);
  document.getElementById('sum-up-rate').textContent = fmtSpeed(up);
  document.getElementById('sum-active-streams').textContent = String(streams);
  document.getElementById('sum-pending-requests').textContent = String(reqs);
}

async function loadServices() {
  if (!state.isAuthenticated) return;
  try {
    state.services = await api('/api/services');
    renderServicesTable();
  } catch (err) {}
}

function renderServicesTable() {
  const box = document.getElementById('services-list');
  if (!state.services || state.services.length === 0) {
    box.innerHTML = `<div class="empty-state" style="padding: 16px;">No targets configured.</div>`;
    return;
  }

  box.innerHTML = state.services.map(s => `
    <div class="svc-row">
      <div class="svc-row-info">
        <span class="svc-row-name">${esc(s.name)} [${esc(s.service_type.toUpperCase())}]</span>
        <span class="svc-row-meta">${esc(s.base_url)} | ${s.is_enabled ? 'ENABLED' : 'DISABLED'}</span>
      </div>
      <div class="svc-row-actions">
        <button class="btn btn-sm" onclick="testServiceTarget(${s.id})">TEST</button>
        <button class="btn btn-sm btn-danger" onclick="deleteServiceTarget(${s.id})">DELETE</button>
      </div>
    </div>
  `).join('');
}

window.testServiceTarget = async function(id) {
  try {
    const res = await api(`/api/services/${id}/test`, { method: 'POST' });
    alert(`Status: ${res.status.toUpperCase()}\nLatency: ${res.response_time_ms}ms\nMessage: ${res.error_message || 'OK'}`);
  } catch (err) {
    alert(`Test error: ${err.message}`);
  }
};

window.deleteServiceTarget = async function(id) {
  if (!confirm('Delete this service configuration?')) return;
  try {
    await api(`/api/services/${id}`, { method: 'DELETE' });
    await loadServices();
    pollTelemetry(true);
  } catch (err) {
    alert(err.message);
  }
};

async function handleAddService(e) {
  e.preventDefault();
  const errBox = document.getElementById('service-error');
  errBox.classList.add('hidden');

  const payload = {
    name: document.getElementById('svc-name').value,
    service_type: document.getElementById('svc-type').value,
    base_url: document.getElementById('svc-url').value,
    apikey: document.getElementById('svc-apikey').value || null,
    username: document.getElementById('svc-user').value || null,
    password: document.getElementById('svc-password').value || null,
    display_order: parseInt(document.getElementById('svc-order').value || '0', 10),
    is_enabled: document.getElementById('svc-enabled').checked ? 1 : 0,
  };

  try {
    await api('/api/services', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    document.getElementById('form-add-service').reset();
    document.getElementById('svc-enabled').checked = true;
    await loadServices();
    pollTelemetry(true);
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove('hidden');
  }
}

function openSettings() {
  loadServices();
  document.getElementById('overlay-settings').classList.remove('hidden');
}

function closeSettings() {
  document.getElementById('overlay-settings').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
  checkInitStatus();

  document.getElementById('form-setup').addEventListener('submit', handleSetupSubmit);
  document.getElementById('form-login').addEventListener('submit', handleLoginSubmit);

  document.getElementById('btn-manual-poll').addEventListener('click', () => {
    pollTelemetry(true);
  });

  document.getElementById('btn-open-settings').addEventListener('click', openSettings);
  document.getElementById('btn-close-settings').addEventListener('click', closeSettings);
  document.getElementById('btn-logout').addEventListener('click', handleLogout);

  document.getElementById('form-add-service').addEventListener('submit', handleAddService);
});
