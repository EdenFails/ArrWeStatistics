const state = {
  isInitialized: false,
  isAuthenticated: false,
  services: [],
  telemetry: [],
  storagePools: [],
  selectedServiceDetailId: null,
  detailFilter: 'all',
  detailSearch: '',
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
      loadStoragePools();
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
    loadStoragePools();
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
    loadStoragePools();
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
  closeServiceDetail();
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
    if (state.selectedServiceDetailId) {
      updateDetailView();
    }
    loadStoragePools();
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

function showServiceFeedback(text, type = 'error') {
  const box = document.getElementById('service-feedback');
  if (!box) return;
  box.className = `form-feedback ${type}`;
  box.textContent = text;
  box.classList.remove('hidden');
}

function hideServiceFeedback() {
  const box = document.getElementById('service-feedback');
  if (!box) return;
  box.className = 'form-feedback hidden';
  box.textContent = '';
}

function updateServiceFormFields() {
  const typeSelect = document.getElementById('svc-type');
  if (!typeSelect) return;
  const stype = (typeSelect.value || 'qbittorrent').toLowerCase();
  const grpApikey = document.getElementById('grp-svc-apikey');
  const grpAuth = document.getElementById('grp-svc-auth');
  const urlInput = document.getElementById('svc-url');
  const nameInput = document.getElementById('svc-name');
  const apiKeyInput = document.getElementById('svc-apikey');

  const userInput = document.getElementById('svc-user');
  const passwordInput = document.getElementById('svc-password');

  if (stype === 'qbittorrent') {
    if (grpApikey) grpApikey.classList.remove('hidden');
    if (grpAuth) grpAuth.classList.remove('hidden');
    if (apiKeyInput) apiKeyInput.placeholder = 'Auth key / API token (optional if using username & password)';
    if (userInput) userInput.placeholder = 'Username';
    if (passwordInput) passwordInput.placeholder = 'Password';
    if (urlInput && (!urlInput.value || urlInput.value.includes('localhost') || urlInput.value.includes('docker'))) {
      urlInput.placeholder = 'http://gluetun:8085 or LAN IP';
    }
    if (nameInput && !nameInput.value) {
      nameInput.placeholder = 'Primary qBittorrent';
    }
  } else if (stype === 'jellyfin') {
    if (grpApikey) grpApikey.classList.remove('hidden');
    if (grpAuth) grpAuth.classList.remove('hidden');
    if (apiKeyInput) apiKeyInput.placeholder = 'API Key (Jellyfin Dashboard > API Keys) or blank if using User/Pass';
    if (userInput) userInput.placeholder = 'Jellyfin Username (optional if using API Key)';
    if (passwordInput) passwordInput.placeholder = 'Jellyfin Password (optional if using API Key)';
    if (urlInput && (!urlInput.value || urlInput.value.includes('localhost') || urlInput.value.includes('docker'))) {
      urlInput.placeholder = 'http://host.docker.internal:8096 or LAN IP';
    }
    if (nameInput && !nameInput.value) nameInput.placeholder = 'Home Jellyfin';
  } else {
    if (grpAuth) grpAuth.classList.add('hidden');
    if (grpApikey) grpApikey.classList.remove('hidden');
    if (apiKeyInput) apiKeyInput.placeholder = 'Service API key / token';
    if (stype === 'sabnzbd') {
      if (urlInput && (!urlInput.value || urlInput.value.includes('localhost') || urlInput.value.includes('docker'))) {
        urlInput.placeholder = 'http://gluetun:8080 or LAN IP';
      }
      if (nameInput && !nameInput.value) nameInput.placeholder = 'Primary SABnzbd';
    } else if (stype === 'jellyseer' || stype === 'jellyseerr') {
      if (urlInput && (!urlInput.value || urlInput.value.includes('localhost') || urlInput.value.includes('docker'))) {
        urlInput.placeholder = 'http://host.docker.internal:5055 or LAN IP';
      }
      if (nameInput && !nameInput.value) nameInput.placeholder = 'Jellyseerr';
    }
  }
}

function getServiceFormPayload() {
  const name = (document.getElementById('svc-name').value || '').trim();
  const service_type = (document.getElementById('svc-type').value || '').trim();
  let base_url = (document.getElementById('svc-url').value || '').trim();
  const apikey = (document.getElementById('svc-apikey').value || '').trim() || null;
  const username = (document.getElementById('svc-user').value || '').trim() || null;
  const password = document.getElementById('svc-password').value || null;
  const display_order = parseInt(document.getElementById('svc-order').value || '0', 10);
  const is_enabled = document.getElementById('svc-enabled').checked ? 1 : 0;

  if (base_url && !base_url.startsWith('http://') && !base_url.startsWith('https://')) {
    base_url = 'http://' + base_url;
  }

  return {
    name,
    service_type,
    base_url,
    apikey,
    username,
    password,
    display_order: isNaN(display_order) ? 0 : display_order,
    is_enabled,
  };
}

async function handleTestServiceClick() {
  hideServiceFeedback();
  const payload = getServiceFormPayload();
  if (!payload.name || !payload.base_url) {
    showServiceFeedback('Please provide a display name and base URL to test.', 'error');
    return;
  }

  const btnTest = document.getElementById('btn-test-service');
  const btnSave = document.getElementById('btn-save-service');
  if (btnTest) btnTest.disabled = true;
  if (btnSave) btnSave.disabled = true;
  showServiceFeedback('Testing connection to target...', 'info');

  try {
    const res = await api('/api/services/test-config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (res.status === 'online') {
      showServiceFeedback(`Connection verified! Response time: ${res.response_time_ms}ms. Configuration is valid.`, 'success');
    } else {
      let msg = res.error_message || 'Service target is offline or unreachable.';
      if (payload.base_url.includes('localhost') || payload.base_url.includes('127.0.0.1')) {
        msg += ' (Docker note: "localhost" refers to the container itself. Use http://host.docker.internal:PORT or your host LAN IP e.g. http://192.168.x.x:PORT).';
      }
      showServiceFeedback(`Test failed: ${msg}`, 'error');
    }
  } catch (err) {
    showServiceFeedback(`Test request failed: ${err.message}`, 'error');
  } finally {
    if (btnTest) btnTest.disabled = false;
    if (btnSave) btnSave.disabled = false;
  }
}

async function handleAddService(e) {
  e.preventDefault();
  hideServiceFeedback();

  const payload = getServiceFormPayload();
  if (!payload.name || !payload.base_url) {
    showServiceFeedback('Display name and base URL are required.', 'error');
    return;
  }

  const btnTest = document.getElementById('btn-test-service');
  const btnSave = document.getElementById('btn-save-service');
  if (btnTest) btnTest.disabled = true;
  btnSave.disabled = true;
  const originalSaveText = btnSave.textContent;
  btnSave.textContent = 'TESTING...';
  showServiceFeedback('Testing target before saving...', 'info');

  try {
    const testRes = await api('/api/services/test-config', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (testRes.status !== 'online') {
      let msg = testRes.error_message || 'Service target failed connectivity check.';
      if (payload.base_url.includes('localhost') || payload.base_url.includes('127.0.0.1')) {
        msg += ' (Docker note: "localhost" refers to the container itself. Use http://host.docker.internal:PORT or your host LAN IP e.g. http://192.168.x.x:PORT).';
      }
      showServiceFeedback(`Cannot save: ${msg}. Please edit connection settings and try again.`, 'error');
      // Do not reset form - user can edit and retry immediately!
      return;
    }

    btnSave.textContent = 'SAVING...';
    await api('/api/services', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    showServiceFeedback(`Service "${payload.name}" verified and added successfully!`, 'success');
    document.getElementById('form-add-service').reset();
    document.getElementById('svc-enabled').checked = true;
    updateServiceFormFields();
    await loadServices();
    pollTelemetry(true);
  } catch (err) {
    showServiceFeedback(`Error: ${err.message}`, 'error');
  } finally {
    if (btnTest) btnTest.disabled = false;
    btnSave.disabled = false;
    btnSave.textContent = originalSaveText;
  }
}

// Service Detail Drill-Down Modal Logic
window.openServiceDetail = function(id) {
  state.selectedServiceDetailId = id;
  state.detailFilter = 'all';
  state.detailSearch = '';
  const item = state.telemetry.find(t => t.service_id === id);
  if (!item) return;

  const titleEl = document.getElementById('detail-title');
  if (titleEl) {
    titleEl.textContent = `${item.name.toUpperCase()} [${item.service_type.toUpperCase()}]`;
  }
  updateDetailView();
  document.getElementById('overlay-service-detail').classList.remove('hidden');
};

window.closeServiceDetail = function() {
  state.selectedServiceDetailId = null;
  document.getElementById('overlay-service-detail').classList.add('hidden');
};

window.setDetailFilter = function(filter) {
  state.detailFilter = filter;
  updateDetailView();
};

window.handleDetailSearch = function(q) {
  state.detailSearch = q;
  updateDetailView(true);
};

function updateDetailView(preserveSearchFocus = false) {
  if (!state.selectedServiceDetailId) return;
  const item = state.telemetry.find(t => t.service_id === state.selectedServiceDetailId);
  if (!item) return;

  const bodyEl = document.getElementById('detail-body');
  if (!bodyEl) return;

  const cursorPosition = preserveSearchFocus ? (document.getElementById('detail-search-input')?.selectionStart || 0) : null;
  bodyEl.innerHTML = UI.renderDetailView(item, state.detailFilter, state.detailSearch);

  if (preserveSearchFocus) {
    const input = document.getElementById('detail-search-input');
    if (input) {
      input.focus();
      input.setSelectionRange(cursorPosition, cursorPosition);
    }
  }
}

// Storage Pools Management
async function loadStoragePools() {
  if (!state.isAuthenticated) return;
  try {
    state.storagePools = await api('/api/storage');
    renderStorageCards();
    renderStorageTable();
  } catch (err) {}
}

function renderStorageCards() {
  const container = document.getElementById('storage-container');
  if (!container) return;

  if (!state.storagePools || state.storagePools.length === 0) {
    container.innerHTML = `
      <div class="empty-state">No storage pools configured. Click "+ ADD DRIVE / POOL" to monitor your MergerFS or host drives.</div>
    `;
    return;
  }

  container.innerHTML = state.storagePools.map(pool => UI.renderStorageCard(pool)).join('');
}

function renderStorageTable() {
  const box = document.getElementById('storage-list');
  if (!box) return;

  if (!state.storagePools || state.storagePools.length === 0) {
    box.innerHTML = `<div class="empty-state" style="padding: 16px;">No storage pools configured.</div>`;
    return;
  }

  box.innerHTML = state.storagePools.map(p => `
    <div class="svc-row">
      <div class="svc-row-info">
        <span class="svc-row-name">${esc(p.name)} [${esc(p.mount_path)}]</span>
        <span class="svc-row-meta">
          Folders: ${(p.folders || []).map(f => esc(f.name)).join(', ') || 'None'} | ${p.is_enabled ? 'ENABLED' : 'DISABLED'}
        </span>
      </div>
      <div class="svc-row-actions">
        <button class="btn btn-sm" onclick="scanStorageMountTarget(${p.id}, event)">SCAN</button>
        <button class="btn btn-sm btn-danger" onclick="deleteStorageMountTarget(${p.id})">DELETE</button>
      </div>
    </div>
  `).join('');
}

window.scanStorageMountTarget = async function(id, e) {
  if (e) {
    e.stopPropagation();
    if (e.target && e.target.tagName === 'BUTTON') {
      e.target.disabled = true;
      e.target.textContent = 'SCANNING...';
    }
  }
  try {
    await api(`/api/storage/${id}/scan`, { method: 'POST' });
    await loadStoragePools();
  } catch (err) {
    alert(`Scan error: ${err.message}`);
  }
};

window.deleteStorageMountTarget = async function(id) {
  if (!confirm('Delete this storage pool configuration?')) return;
  try {
    await api(`/api/storage/${id}`, { method: 'DELETE' });
    await loadStoragePools();
  } catch (err) {
    alert(err.message);
  }
};

function showStorageFeedback(text, type = 'error') {
  const box = document.getElementById('storage-feedback');
  if (!box) return;
  box.className = `form-feedback ${type}`;
  box.textContent = text;
  box.classList.remove('hidden');
}

function hideStorageFeedback() {
  const box = document.getElementById('storage-feedback');
  if (!box) return;
  box.className = 'form-feedback hidden';
  box.textContent = '';
}

async function handleAddStorage(e) {
  e.preventDefault();
  hideStorageFeedback();

  const name = (document.getElementById('storage-name').value || '').trim();
  const mount_path = (document.getElementById('storage-path').value || '').trim();
  const foldersRaw = (document.getElementById('storage-folders').value || '').trim();
  const display_order = parseInt(document.getElementById('storage-order').value || '0', 10);
  const is_enabled = document.getElementById('storage-enabled').checked ? 1 : 0;

  if (!name || !mount_path) {
    showStorageFeedback('Pool name and mount path are required.', 'error');
    return;
  }

  const folders = foldersRaw
    ? foldersRaw.split(',').map(s => s.trim()).filter(Boolean)
    : [];

  const btnSave = document.getElementById('btn-save-storage');
  if (btnSave) btnSave.disabled = true;

  try {
    await api('/api/storage', {
      method: 'POST',
      body: JSON.stringify({
        name,
        mount_path,
        folders,
        display_order: isNaN(display_order) ? 0 : display_order,
        is_enabled,
      }),
    });

    showStorageFeedback(`Storage pool "${name}" added successfully!`, 'success');
    document.getElementById('form-add-storage').reset();
    document.getElementById('storage-enabled').checked = true;
    await loadStoragePools();
  } catch (err) {
    showStorageFeedback(`Error: ${err.message}`, 'error');
  } finally {
    if (btnSave) btnSave.disabled = false;
  }
}

// Configuration Tabs
function switchSettingsTab(tabName) {
  const tabBtnServices = document.getElementById('tab-btn-services');
  const tabBtnStorage = document.getElementById('tab-btn-storage');
  const panelServices = document.getElementById('tab-panel-services');
  const panelStorage = document.getElementById('tab-panel-storage');

  if (tabName === 'storage') {
    tabBtnServices.classList.remove('active');
    tabBtnStorage.classList.add('active');
    panelServices.classList.add('hidden');
    panelStorage.classList.remove('hidden');
    loadStoragePools();
  } else {
    tabBtnServices.classList.add('active');
    tabBtnStorage.classList.remove('active');
    panelServices.classList.remove('hidden');
    panelStorage.classList.add('hidden');
    loadServices();
  }
}

function openSettings(defaultTab = 'services') {
  hideServiceFeedback();
  hideStorageFeedback();
  switchSettingsTab(defaultTab);
  updateServiceFormFields();
  document.getElementById('overlay-settings').classList.remove('hidden');
}

function closeSettings() {
  document.getElementById('overlay-settings').classList.add('hidden');
}

// Folder & Filesystem Browser State
const browserState = {
  currentPath: '/',
  parentPath: null,
  mode: 'mount', // 'mount' or 'subfolders'
  watchedFolders: new Set(),
  lastDirectories: [],
};

function syncWatchedFoldersInput() {
  const input = document.getElementById('storage-folders');
  const chipsContainer = document.getElementById('watched-folders-chips');
  if (!input) return;

  const arr = Array.from(browserState.watchedFolders);
  input.value = arr.join(', ');

  if (chipsContainer) {
    if (arr.length === 0) {
      chipsContainer.innerHTML = '';
    } else {
      chipsContainer.innerHTML = arr.map(f => `
        <span class="folder-chip">
          <span>${esc(f)}</span>
          <span class="folder-chip-remove" onclick="removeWatchedFolder('${esc(f)}')">×</span>
        </span>
      `).join('');
    }
  }
}

window.removeWatchedFolder = function(name) {
  browserState.watchedFolders.delete(name);
  syncWatchedFoldersInput();
  renderBrowserDirectoryList();
};

window.toggleWatchFolder = function(name) {
  if (browserState.watchedFolders.has(name)) {
    browserState.watchedFolders.delete(name);
  } else {
    browserState.watchedFolders.add(name);
  }
  syncWatchedFoldersInput();
  renderBrowserDirectoryList();
};

async function openFolderBrowser(targetPath = '', mode = 'mount') {
  browserState.mode = mode;

  // Sync existing input into watchedFolders set
  const input = document.getElementById('storage-folders');
  if (input && input.value) {
    browserState.watchedFolders.clear();
    input.value.split(',').forEach(s => {
      const trimmed = s.trim();
      if (trimmed) browserState.watchedFolders.add(trimmed);
    });
  }
  syncWatchedFoldersInput();

  const titleEl = document.getElementById('browser-title');
  if (titleEl) {
    titleEl.textContent = mode === 'mount' ? 'BROWSE MOUNT PATH' : 'SELECT WATCHED SUBFOLDERS';
  }

  document.getElementById('overlay-folder-browser').classList.remove('hidden');
  await browseToPath(targetPath);
}

function closeFolderBrowser() {
  document.getElementById('overlay-folder-browser').classList.add('hidden');
}

window.browseToPath = async function(path) {
  const pathInput = document.getElementById('browser-current-path');
  const listEl = document.getElementById('browser-list');
  const feedbackEl = document.getElementById('browser-feedback');
  if (feedbackEl) feedbackEl.classList.add('hidden');

  if (listEl) {
    listEl.innerHTML = `<div class="empty-state" style="padding: 20px;">Loading directory...</div>`;
  }

  try {
    const res = await api(`/api/filesystem/browse?path=${encodeURIComponent(path || '')}`);
    browserState.currentPath = res.current_path;
    browserState.parentPath = res.parent_path;

    if (pathInput) {
      pathInput.value = res.current_path;
    }

    const btnUp = document.getElementById('btn-browser-up');
    if (btnUp) {
      btnUp.disabled = !res.parent_path;
    }

    // Render Windows drives if available
    const drivesEl = document.getElementById('browser-drives');
    if (drivesEl) {
      if (res.drives && res.drives.length > 0) {
        drivesEl.innerHTML = res.drives.map(d => `
          <button type="button" class="btn btn-sm" onclick="browseToPath('${esc(d.path)}')">${esc(d.name)}</button>
        `).join('');
      } else {
        drivesEl.innerHTML = '';
      }
    }

    browserState.lastDirectories = res.directories || [];
    renderBrowserDirectoryList();

    if (res.error && feedbackEl) {
      feedbackEl.className = 'form-feedback error';
      feedbackEl.textContent = res.error;
      feedbackEl.classList.remove('hidden');
    }
  } catch (err) {
    if (listEl) {
      listEl.innerHTML = `<div class="empty-state" style="color: var(--status-offline); padding: 20px;">Error: ${esc(err.message)}</div>`;
    }
  }
};

function renderBrowserDirectoryList() {
  const listEl = document.getElementById('browser-list');
  if (!listEl) return;

  const dirs = browserState.lastDirectories || [];
  if (dirs.length === 0) {
    listEl.innerHTML = `<div class="empty-state" style="padding: 24px;">No subdirectories found in this folder.</div>`;
    return;
  }

  listEl.innerHTML = dirs.map(d => {
    const isWatched = browserState.watchedFolders.has(d.name);
    return `
      <div class="svc-row" style="padding: 6px 10px;">
        <div class="svc-row-info" style="cursor: pointer; flex: 1;" onclick="browseToPath('${esc(d.path)}')">
          <span class="svc-row-name" style="font-family: var(--font-mono); font-size: 11px;">📁 ${esc(d.name)}</span>
        </div>
        <div class="svc-row-actions">
          <button type="button" class="btn btn-sm" onclick="browseToPath('${esc(d.path)}')">OPEN</button>
          <button type="button" class="btn btn-sm ${isWatched ? 'btn-primary' : 'btn-subtle'}" onclick="toggleWatchFolder('${esc(d.name)}')">
            ${isWatched ? 'WATCHED ✓' : '+ WATCH'}
          </button>
        </div>
      </div>
    `;
  }).join('');
}

document.addEventListener('DOMContentLoaded', () => {
  checkInitStatus();

  document.getElementById('form-setup').addEventListener('submit', handleSetupSubmit);
  document.getElementById('form-login').addEventListener('submit', handleLoginSubmit);

  document.getElementById('btn-manual-poll').addEventListener('click', () => {
    pollTelemetry(true);
    loadStoragePools();
  });

  document.getElementById('btn-open-settings').addEventListener('click', () => openSettings('services'));
  document.getElementById('btn-close-settings').addEventListener('click', closeSettings);
  document.getElementById('btn-logout').addEventListener('click', handleLogout);

  // Storage Pool Navigation & Browsing
  const btnOpenStorage = document.getElementById('btn-open-storage-modal');
  if (btnOpenStorage) {
    btnOpenStorage.addEventListener('click', () => openSettings('storage'));
  }

  const btnBrowseMount = document.getElementById('btn-browse-mount');
  if (btnBrowseMount) {
    btnBrowseMount.addEventListener('click', () => {
      const currentVal = document.getElementById('storage-path').value || '/';
      openFolderBrowser(currentVal, 'mount');
    });
  }

  const btnBrowseSub = document.getElementById('btn-browse-subfolders');
  if (btnBrowseSub) {
    btnBrowseSub.addEventListener('click', () => {
      const currentVal = document.getElementById('storage-path').value || '/';
      openFolderBrowser(currentVal, 'subfolders');
    });
  }

  const btnCloseBrowser = document.getElementById('btn-close-browser');
  if (btnCloseBrowser) btnCloseBrowser.addEventListener('click', closeFolderBrowser);
  const btnDoneBrowser = document.getElementById('btn-browser-done');
  if (btnDoneBrowser) btnDoneBrowser.addEventListener('click', closeFolderBrowser);

  const btnBrowserUp = document.getElementById('btn-browser-up');
  if (btnBrowserUp) {
    btnBrowserUp.addEventListener('click', () => {
      if (browserState.parentPath) {
        browseToPath(browserState.parentPath);
      }
    });
  }

  const btnBrowserGo = document.getElementById('btn-browser-go');
  const pathInput = document.getElementById('browser-current-path');
  if (btnBrowserGo && pathInput) {
    btnBrowserGo.addEventListener('click', () => browseToPath(pathInput.value));
    pathInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        browseToPath(pathInput.value);
      }
    });
  }

  const btnSelectMount = document.getElementById('btn-browser-select-mount');
  if (btnSelectMount) {
    btnSelectMount.addEventListener('click', () => {
      const targetInput = document.getElementById('storage-path');
      if (targetInput) {
        targetInput.value = browserState.currentPath;
      }
      closeFolderBrowser();
    });
  }

  const foldersInput = document.getElementById('storage-folders');
  if (foldersInput) {
    foldersInput.addEventListener('input', () => {
      browserState.watchedFolders.clear();
      foldersInput.value.split(',').forEach(s => {
        const trimmed = s.trim();
        if (trimmed) browserState.watchedFolders.add(trimmed);
      });
      syncWatchedFoldersInput();
    });
  }

  // Tabs
  const tabBtnServices = document.getElementById('tab-btn-services');
  if (tabBtnServices) {
    tabBtnServices.addEventListener('click', () => switchSettingsTab('services'));
  }
  const tabBtnStorage = document.getElementById('tab-btn-storage');
  if (tabBtnStorage) {
    tabBtnStorage.addEventListener('click', () => switchSettingsTab('storage'));
  }

  // Forms
  const typeSelect = document.getElementById('svc-type');
  if (typeSelect) {
    typeSelect.addEventListener('change', updateServiceFormFields);
  }

  const btnTest = document.getElementById('btn-test-service');
  if (btnTest) {
    btnTest.addEventListener('click', handleTestServiceClick);
  }

  document.getElementById('form-add-service').addEventListener('submit', handleAddService);
  document.getElementById('form-add-storage').addEventListener('submit', (e) => {
    handleAddStorage(e).then(() => {
      browserState.watchedFolders.clear();
      syncWatchedFoldersInput();
    });
  });

  // Detail Modal Close
  const btnCloseDetail = document.getElementById('btn-close-detail');
  if (btnCloseDetail) {
    btnCloseDetail.addEventListener('click', closeServiceDetail);
  }

  // Close modals when clicking outside the dialog content (on the overlay background)
  document.querySelectorAll('.overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        if (overlay.id === 'overlay-service-detail') {
          closeServiceDetail();
        } else if (overlay.id === 'overlay-settings') {
          closeSettings();
        } else if (overlay.id === 'overlay-folder-browser') {
          closeFolderBrowser();
        }
      }
    });
  });

  // Escape key closes modals
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeFolderBrowser();
      closeSettings();
      closeServiceDetail();
    }
  });

  updateServiceFormFields();
});
