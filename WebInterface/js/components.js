function fmtBytes(bytes, decimals = 1) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function fmtSpeed(bytesPerSec) {
  return fmtBytes(bytesPerSec) + '/s';
}

function fmtSeconds(seconds) {
  if (!seconds || seconds <= 0) return '0s';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const UI = {
  renderCard(item) {
    const type = (item.service_type || '').toLowerCase();
    const isOnline = item.status === 'online';
    const badgeClass = isOnline ? 'badge-online' : 'badge-offline';
    const statusText = isOnline ? `${item.response_time_ms}ms` : 'OFFLINE';

    let bodyHtml = '';

    if (!isOnline) {
      bodyHtml = `
        <div class="stat-box">
          <div class="stat-box-lbl">DIAGNOSTIC</div>
          <div class="stat-box-val" style="color: var(--status-offline); font-size: 11px;">
            ${esc(item.error_message || 'Host unreachable or connection refused')}
          </div>
        </div>
      `;
    } else {
      switch (type) {
        case 'qbittorrent':
          bodyHtml = this.qbittorrent(item.data);
          break;
        case 'sabnzbd':
          bodyHtml = this.sabnzbd(item.data);
          break;
        case 'jellyfin':
          bodyHtml = this.jellyfin(item.data);
          break;
        case 'jellyseer':
        case 'jellyseerr':
          bodyHtml = this.jellyseerr(item.data);
          break;
        default:
          bodyHtml = `<div>Unsupported type</div>`;
      }
    }

    const clickableClass = isOnline ? 'card-clickable' : '';
    const clickHandler = isOnline ? `onclick="openServiceDetail(${item.service_id})"` : '';
    const clickHint = isOnline ? `<div class="card-action-hint">CLICK TO VIEW FULL STATS &amp; DETAILS</div>` : '';

    return `
      <div class="card ${clickableClass}" data-id="${item.service_id}" ${clickHandler}>
        <div class="card-header">
          <div class="card-title">
            ${esc(item.name)}
            <span class="card-type">[${esc(type.toUpperCase())}]</span>
          </div>
          <div class="card-status-badge ${badgeClass}">${esc(statusText)}</div>
        </div>
        <div class="card-body">
          ${bodyHtml}
          ${clickHint}
        </div>
      </div>
    `;
  },

  qbittorrent(d = {}) {
    const torrents = d.torrents || {};
    const items = d.active_items || [];

    let listHtml = '';
    if (items.length > 0) {
      listHtml = `
        <div class="card-list-title">ACTIVE TRANSFERS (${items.length})</div>
        <div class="card-items-list">
          ${items.map(t => `
            <div class="card-item-row">
              <div class="item-row-top">
                <span class="item-row-name" title="${esc(t.name)}">${esc(t.name)}</span>
                <span class="item-row-meta">${t.progress}% | DL ${fmtSpeed(t.dlspeed)} | ETA ${fmtSeconds(t.eta)}</span>
              </div>
              <div class="progress-bar-track">
                <div class="progress-bar-fill" style="width: ${t.progress}%;"></div>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    return `
      <div class="stat-grid-2">
        <div class="stat-box">
          <div class="stat-box-lbl">DOWNLOAD SPEED</div>
          <div class="stat-box-val">${fmtSpeed(d.dl_speed_bytes)}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">UPLOAD SPEED</div>
          <div class="stat-box-val">${fmtSpeed(d.up_speed_bytes)}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">TORRENT COUNTS</div>
          <div class="stat-box-val">${torrents.active || 0} active / ${torrents.total || 0} total</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">DISK AVAILABLE</div>
          <div class="stat-box-val">${fmtBytes(d.free_space_bytes)}</div>
        </div>
      </div>
      ${listHtml}
    `;
  },

  sabnzbd(d = {}) {
    const jobs = d.active_jobs || [];

    let listHtml = '';
    if (jobs.length > 0) {
      listHtml = `
        <div class="card-list-title">QUEUE SLOTS (${jobs.length})</div>
        <div class="card-items-list">
          ${jobs.map(j => `
            <div class="card-item-row">
              <div class="item-row-top">
                <span class="item-row-name" title="${esc(j.filename)}">${esc(j.filename)}</span>
                <span class="item-row-meta">${esc(j.percentage)}% | ${esc(j.mbleft)}MB left | ETA ${esc(j.timeleft)}</span>
              </div>
              <div class="progress-bar-track">
                <div class="progress-bar-fill" style="width: ${j.percentage}%;"></div>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    return `
      <div class="stat-grid-2">
        <div class="stat-box">
          <div class="stat-box-lbl">DOWNLOAD RATE</div>
          <div class="stat-box-val">${esc(d.speed_display || '0 KB/s')}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">REMAINING QUEUE</div>
          <div class="stat-box-val">${esc(d.size_left || '0 MB')}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">TIME REMAINING</div>
          <div class="stat-box-val">${esc(d.time_left || '0:00:00')}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">QUEUE STATUS</div>
          <div class="stat-box-val">${esc(d.status || 'Idle')}</div>
        </div>
      </div>
      ${listHtml}
    `;
  },

  jellyfin(d = {}) {
    const streams = d.streams || [];

    let listHtml = '';
    if (streams.length > 0) {
      listHtml = `
        <div class="card-list-title">ACTIVE STREAMS (${streams.length})</div>
        <div class="card-items-list">
          ${streams.map(s => {
            const txLabel = s.is_transcoding 
              ? (s.hardware_acceleration ? `Transcode (HW: ${esc(s.hardware_acceleration)})` : 'Transcode (SW)')
              : 'Direct Play';
            return `
              <div class="card-item-row">
                <div class="item-row-top">
                  <span class="item-row-name" title="${esc(s.media_title)}">${esc(s.media_title)}</span>
                  <span class="item-row-meta">${esc(s.user_name)} | ${esc(s.client)}</span>
                </div>
                <div class="item-row-top" style="margin-top: 2px;">
                  <span class="item-row-meta" style="color: var(--text-main); font-size: 9px;">${txLabel}</span>
                  <span class="item-row-meta">${s.progress_percent}%</span>
                </div>
                <div class="progress-bar-track">
                  <div class="progress-bar-fill" style="width: ${s.progress_percent}%;"></div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    return `
      <div class="stat-grid-2">
        <div class="stat-box">
          <div class="stat-box-lbl">ACTIVE STREAMS</div>
          <div class="stat-box-val">${d.active_stream_count || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">TRANSCODES</div>
          <div class="stat-box-val">${d.transcoding_count || 0} (${d.hardware_transcoding_count || 0} HW)</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">DIRECT PLAY</div>
          <div class="stat-box-val">${d.direct_play_count || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">SERVER VERSION</div>
          <div class="stat-box-val" style="font-size: 11px;">${esc(d.version || 'Unknown')}</div>
        </div>
      </div>
      ${listHtml}
    `;
  },

  jellyseerr(d = {}) {
    const recent = d.recent_requests || [];

    let listHtml = '';
    if (recent.length > 0) {
      listHtml = `
        <div class="card-list-title">RECENT REQUESTS (${recent.length})</div>
        <div class="card-items-list">
          ${recent.map(r => `
            <div class="card-item-row">
              <div class="item-row-top">
                <span class="item-row-name" title="${esc(r.title)}">${esc(r.title)}</span>
                <span class="item-row-meta">${esc(r.status)}</span>
              </div>
              <div class="item-row-top" style="margin-top: 2px;">
                <span class="item-row-meta">Type: ${esc(r.media_type)}</span>
                <span class="item-row-meta">User: ${esc(r.requested_by)}</span>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    return `
      <div class="stat-grid-2">
        <div class="stat-box">
          <div class="stat-box-lbl">PENDING</div>
          <div class="stat-box-val">${d.pending_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">PROCESSING</div>
          <div class="stat-box-val">${d.processing_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">AVAILABLE</div>
          <div class="stat-box-val">${d.available_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">TOTAL</div>
          <div class="stat-box-val">${d.total_requests || 0}</div>
        </div>
      </div>
      ${listHtml}
    `;
  },

  renderStorageCard(pool) {
    const isOnline = pool.is_accessible;
    const badgeClass = isOnline ? 'badge-online' : 'badge-offline';
    const statusText = isOnline ? `${fmtBytes(pool.free_bytes)} FREE` : 'UNMOUNTED';

    let bodyHtml = '';

    if (!isOnline) {
      bodyHtml = `
        <div class="stat-box">
          <div class="stat-box-lbl">DIAGNOSTIC</div>
          <div class="stat-box-val" style="color: var(--status-offline); font-size: 11px;">
            ${esc(pool.error_message || 'Mount path not found or permission denied')}
          </div>
        </div>
      `;
    } else {
      const pct = pool.used_percent || 0;
      let fillClass = 'storage';
      if (pct > 90) fillClass = 'danger';
      else if (pct > 75) fillClass = 'warn';

      let foldersHtml = '';
      if (pool.folders && pool.folders.length > 0) {
        foldersHtml = `
          <div class="card-list-title" style="margin-top: 14px; margin-bottom: 6px;">WATCHED SUBFOLDERS</div>
          <div class="storage-folders-list">
            ${pool.folders.map(f => {
              const fPct = pool.total_bytes > 0 ? ((f.bytes / pool.total_bytes) * 100).toFixed(1) : 0;
              const fSize = f.exists ? fmtBytes(f.bytes) : 'NOT FOUND';
              return `
                <div class="folder-row">
                  <div class="folder-row-head">
                    <span class="folder-name">${esc(f.name)}</span>
                    <span class="folder-meta">${fSize} ${f.exists ? `(${fPct}%)` : ''}</span>
                  </div>
                  ${f.exists ? `
                    <div class="progress-track">
                      <div class="progress-fill" style="width: ${Math.min(fPct, 100)}%;"></div>
                    </div>
                  ` : ''}
                </div>
              `;
            }).join('')}
          </div>
        `;
      }

      const scanBtnText = pool.is_scanning ? 'SCANNING FOLDERS...' : 'SCAN FOLDERS';
      const scanBtnDisabled = pool.is_scanning ? 'disabled' : '';

      bodyHtml = `
        <div class="stat-grid-2">
          <div class="stat-box">
            <div class="stat-box-lbl">TOTAL CAPACITY</div>
            <div class="stat-box-val">${fmtBytes(pool.total_bytes)}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">USED SPACE (${pct}%)</div>
            <div class="stat-box-val">${fmtBytes(pool.used_bytes)}</div>
          </div>
        </div>

        <div style="margin-top: 10px;">
          <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
            <span>USAGE</span>
            <span>${fmtBytes(pool.free_bytes)} AVAILABLE</span>
          </div>
          <div class="progress-track" style="height: 8px;">
            <div class="progress-fill ${fillClass}" style="width: ${Math.min(pct, 100)}%;"></div>
          </div>
        </div>

        ${foldersHtml}

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding-top: 8px; border-top: 1px dashed var(--border-dim);">
          <span style="font-size: 9px; font-family: var(--font-mono); color: var(--text-dim);">
            ${pool.last_scanned_ts ? `Scanned: ${new Date(pool.last_scanned_ts).toLocaleTimeString()}` : 'Folders not scanned yet'}
          </span>
          <button class="btn btn-sm" onclick="scanStorageMountTarget(${pool.id}, event)" ${scanBtnDisabled}>
            ${scanBtnText}
          </button>
        </div>
      `;
    }

    return `
      <div class="card" data-storage-id="${pool.id}">
        <div class="card-header">
          <div class="card-title">
            ${esc(pool.name)}
            <span class="card-type">[${esc(pool.mount_path)}]</span>
          </div>
          <div class="card-status-badge ${badgeClass}">${esc(statusText)}</div>
        </div>
        <div class="card-body">
          ${bodyHtml}
        </div>
      </div>
    `;
  },

  renderDetailView(item, filter = 'all', searchQuery = '') {
    const type = (item.service_type || '').toLowerCase();
    const d = item.data || {};

    if (type === 'qbittorrent') {
      const allTorrents = d.all_items || d.active_items || [];
      const q = (searchQuery || '').trim().toLowerCase();

      // Counts per category
      const counts = {
        all: allTorrents.length,
        downloading: 0,
        seeding: 0,
        completed: 0,
        paused: 0,
        active: 0
      };

      allTorrents.forEach(t => {
        const st = (t.state || '').toLowerCase();
        const isDl = st.includes('dl') || st === 'downloading';
        const isUp = st.includes('up') || st === 'uploading';
        const isPaused = st.includes('pause');
        const isCompleted = t.progress === 100 || (t.ratio && t.ratio >= 1) || isUp;
        const isActive = (t.dlspeed > 0) || (t.upspeed > 0);

        if (isDl) counts.downloading++;
        if (isUp) counts.seeding++;
        if (isCompleted) counts.completed++;
        if (isPaused) counts.paused++;
        if (isActive) counts.active++;
      });

      // Filter
      let filtered = allTorrents.filter(t => {
        const st = (t.state || '').toLowerCase();
        if (filter === 'downloading') return st.includes('dl') || st === 'downloading';
        if (filter === 'seeding') return st.includes('up') || st === 'uploading';
        if (filter === 'completed') return t.progress === 100 || (t.ratio && t.ratio >= 1) || st.includes('up');
        if (filter === 'paused') return st.includes('pause');
        if (filter === 'active') return (t.dlspeed > 0) || (t.upspeed > 0);
        return true;
      });

      if (q) {
        filtered = filtered.filter(t => {
          const nameMatch = (t.name || '').toLowerCase().includes(q);
          const catMatch = (t.category || '').toLowerCase().includes(q);
          return nameMatch || catMatch;
        });
      }

      let rowsHtml = '';
      if (filtered.length === 0) {
        rowsHtml = `
          <tr>
            <td colspan="9" style="text-align: center; padding: 30px; color: var(--text-dim); font-family: var(--font-mono);">
              No torrents match the selected filter or search query.
            </td>
          </tr>
        `;
      } else {
        rowsHtml = filtered.map(t => {
          const dl = t.dlspeed > 0 ? fmtSpeed(t.dlspeed) : '0 B/s';
          const up = t.upspeed > 0 ? fmtSpeed(t.upspeed) : '0 B/s';
          const eta = t.eta > 0 && t.eta < 864000 ? fmtSeconds(t.eta) : 'N/A';
          const ratio = (typeof t.ratio === 'number') ? t.ratio.toFixed(2) : '0.00';
          const seeds = (t.num_seeds !== undefined) ? `${t.num_seeds} (${t.num_leechs || 0})` : 'N/A';

          return `
            <tr>
              <td style="max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${esc(t.name)}">
                <div style="font-weight: 500;">${esc(t.name)}</div>
                ${t.category ? `<div style="font-size: 9px; color: var(--text-dim);">${esc(t.category)}</div>` : ''}
              </td>
              <td style="font-family: var(--font-mono); white-space: nowrap;">${fmtBytes(t.size)}</td>
              <td>
                <div style="display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 9px; margin-bottom: 2px;">
                  <span>${t.progress}%</span>
                  <span>${esc(t.state)}</span>
                </div>
                <div class="progress-track">
                  <div class="progress-fill ${t.progress === 100 ? 'success' : ''}" style="width: ${t.progress}%;"></div>
                </div>
              </td>
              <td style="font-family: var(--font-mono); white-space: nowrap; color: ${t.dlspeed > 0 ? 'var(--status-online)' : 'inherit'};">${dl}</td>
              <td style="font-family: var(--font-mono); white-space: nowrap; color: ${t.upspeed > 0 ? 'var(--accent)' : 'inherit'};">${up}</td>
              <td style="font-family: var(--font-mono); white-space: nowrap;">${eta}</td>
              <td style="font-family: var(--font-mono); white-space: nowrap;">${ratio}</td>
              <td style="font-family: var(--font-mono); white-space: nowrap;">${seeds}</td>
              <td style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);">${esc(t.state)}</td>
            </tr>
          `;
        }).join('');
      }

      return `
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">DOWNLOAD SPEED</div>
            <div class="stat-box-val">${fmtSpeed(d.dl_speed_bytes || 0)}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">UPLOAD SPEED</div>
            <div class="stat-box-val">${fmtSpeed(d.up_speed_bytes || 0)}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TORRENT TOTAL</div>
            <div class="stat-box-val">${allTorrents.length} items</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">FREE DISK SPACE</div>
            <div class="stat-box-val">${fmtBytes(d.free_space_bytes || 0)}</div>
          </div>
        </div>

        <div class="detail-filters">
          <button class="filter-chip ${filter === 'all' ? 'active' : ''}" onclick="setDetailFilter('all')">ALL (${counts.all})</button>
          <button class="filter-chip ${filter === 'downloading' ? 'active' : ''}" onclick="setDetailFilter('downloading')">DOWNLOADING (${counts.downloading})</button>
          <button class="filter-chip ${filter === 'seeding' ? 'active' : ''}" onclick="setDetailFilter('seeding')">SEEDING (${counts.seeding})</button>
          <button class="filter-chip ${filter === 'completed' ? 'active' : ''}" onclick="setDetailFilter('completed')">COMPLETED (${counts.completed})</button>
          <button class="filter-chip ${filter === 'paused' ? 'active' : ''}" onclick="setDetailFilter('paused')">PAUSED (${counts.paused})</button>
          <button class="filter-chip ${filter === 'active' ? 'active' : ''}" onclick="setDetailFilter('active')">ACTIVE (${counts.active})</button>
          <div style="flex: 1; min-width: 180px; margin-left: auto;">
            <input type="text" id="detail-search-input" class="input-text" style="width: 100%; padding: 4px 8px; font-size: 11px;" placeholder="Search torrents by name or category..." value="${esc(searchQuery)}" oninput="handleDetailSearch(this.value)">
          </div>
        </div>

        <div style="overflow-x: auto; max-height: 550px; overflow-y: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>NAME</th>
                <th>SIZE</th>
                <th style="width: 160px;">PROGRESS</th>
                <th>DL SPEED</th>
                <th>UP SPEED</th>
                <th>ETA</th>
                <th>RATIO</th>
                <th>SEEDS/PEERS</th>
                <th>STATE</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      `;
    }

    if (type === 'sabnzbd') {
      const jobs = d.active_jobs || [];
      return `
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">DOWNLOAD RATE</div>
            <div class="stat-box-val">${esc(d.speed_display || '0 KB/s')}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">REMAINING SIZE</div>
            <div class="stat-box-val">${esc(d.size_left || '0 MB')}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TIME REMAINING</div>
            <div class="stat-box-val">${esc(d.time_left || '0:00:00')}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">STATUS</div>
            <div class="stat-box-val">${esc(d.status || 'Idle')}</div>
          </div>
        </div>

        <div class="section-title" style="margin-bottom: 8px;">QUEUE SLOTS (${jobs.length})</div>
        <div style="overflow-x: auto; max-height: 550px; overflow-y: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>NZB NAME</th>
                <th>SIZE REMAINING</th>
                <th style="width: 180px;">PROGRESS</th>
                <th>ETA</th>
                <th>CATEGORY</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              ${jobs.length === 0 ? `
                <tr><td colspan="6" style="text-align: center; padding: 24px; color: var(--text-dim);">Queue is empty</td></tr>
              ` : jobs.map(j => `
                <tr>
                  <td style="max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${esc(j.filename)}</td>
                  <td style="font-family: var(--font-mono);">${esc(j.mbleft)} MB</td>
                  <td>
                    <div style="font-family: var(--font-mono); font-size: 9px; margin-bottom: 2px;">${esc(j.percentage)}%</div>
                    <div class="progress-track"><div class="progress-fill" style="width: ${j.percentage}%;"></div></div>
                  </td>
                  <td style="font-family: var(--font-mono);">${esc(j.timeleft)}</td>
                  <td style="font-family: var(--font-mono);">${esc(j.category || 'default')}</td>
                  <td style="font-family: var(--font-mono);">${esc(j.status)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    if (type === 'jellyfin') {
      const streams = d.streams || [];
      return `
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">ACTIVE SESSIONS</div>
            <div class="stat-box-val">${d.active_stream_count || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TRANSCODING SESSIONS</div>
            <div class="stat-box-val">${d.transcoding_count || 0} (${d.hardware_transcoding_count || 0} HW)</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">DIRECT PLAY SESSIONS</div>
            <div class="stat-box-val">${d.direct_play_count || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">SERVER VERSION</div>
            <div class="stat-box-val" style="font-size: 11px;">${esc(d.version || 'Unknown')}</div>
          </div>
        </div>

        <div class="section-title" style="margin-bottom: 8px;">ACTIVE SESSIONS DETAIL (${streams.length})</div>
        <div style="overflow-x: auto; max-height: 550px; overflow-y: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>TITLE</th>
                <th>USER</th>
                <th>CLIENT / DEVICE</th>
                <th>PLAY METHOD</th>
                <th style="width: 160px;">PROGRESS</th>
              </tr>
            </thead>
            <tbody>
              ${streams.length === 0 ? `
                <tr><td colspan="5" style="text-align: center; padding: 24px; color: var(--text-dim);">No active playback sessions</td></tr>
              ` : streams.map(s => {
                const method = s.is_transcoding ? `Transcode ${s.hardware_acceleration ? `(HW: ${esc(s.hardware_acceleration)})` : '(SW)'}` : 'Direct Play';
                return `
                  <tr>
                    <td style="font-weight: 500;">${esc(s.media_title)}</td>
                    <td style="font-family: var(--font-mono);">${esc(s.user_name)}</td>
                    <td style="font-family: var(--font-mono); font-size: 10px;">${esc(s.client)} (${esc(s.device_name)})</td>
                    <td style="font-family: var(--font-mono); font-size: 10px; color: ${s.is_transcoding ? 'var(--status-warn)' : 'var(--status-online)'};">${method}</td>
                    <td>
                      <div style="font-family: var(--font-mono); font-size: 9px; margin-bottom: 2px;">${s.progress_percent}%</div>
                      <div class="progress-track"><div class="progress-fill" style="width: ${s.progress_percent}%;"></div></div>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    if (type === 'jellyseer' || type === 'jellyseerr') {
      const recent = d.recent_requests || [];
      return `
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">PENDING</div>
            <div class="stat-box-val">${d.pending_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">PROCESSING</div>
            <div class="stat-box-val">${d.processing_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">AVAILABLE</div>
            <div class="stat-box-val">${d.available_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TOTAL REQUESTS</div>
            <div class="stat-box-val">${d.total_requests || 0}</div>
          </div>
        </div>

        <div class="section-title" style="margin-bottom: 8px;">RECENT REQUESTS (${recent.length})</div>
        <div style="overflow-x: auto; max-height: 550px; overflow-y: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>TITLE</th>
                <th>TYPE</th>
                <th>REQUESTED BY</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              ${recent.length === 0 ? `
                <tr><td colspan="4" style="text-align: center; padding: 24px; color: var(--text-dim);">No requests logged</td></tr>
              ` : recent.map(r => `
                <tr>
                  <td style="font-weight: 500;">${esc(r.title)}</td>
                  <td style="font-family: var(--font-mono); text-transform: uppercase;">${esc(r.media_type)}</td>
                  <td style="font-family: var(--font-mono);">${esc(r.requested_by)}</td>
                  <td style="font-family: var(--font-mono);">${esc(r.status)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    return `<div class="empty-state">No detailed telemetry available for this service type.</div>`;
  }
};
