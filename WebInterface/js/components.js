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
        case 'handbrake':
        case 'autovideoconverter':
          bodyHtml = this.handbrake(item.data);
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
    const libraries = d.libraries || [];

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

    let librariesHtml = '';
    if (libraries.length > 0) {
      librariesHtml = `
        <div class="card-list-title" style="margin-top: 10px;">LIBRARIES (${libraries.length})</div>
        <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px;">
          ${libraries.map(lib => `
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-dim); border-radius: 4px; padding: 4px 8px; font-size: 10px; display: flex; align-items: center; gap: 6px;">
              <span style="font-weight: 600; color: var(--accent);">${esc(lib.name)}:</span>
              <span style="font-family: var(--font-mono); color: var(--text-main);">${esc(lib.formatted || (lib.count + ' items'))}</span>
            </div>
          `).join('')}
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
      ${librariesHtml}
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
          ${recent.slice(0, 5).map(r => {
            let statusColor = 'var(--text-dim)';
            if (r.status === 'Available') statusColor = 'var(--status-online)';
            else if (r.status === 'Processing' || r.status === 'Approved') statusColor = 'var(--accent)';
            else if (r.status === 'Pending Approval') statusColor = 'var(--status-warn)';
            else if (r.status === 'Declined') statusColor = 'var(--status-offline)';

            const typeLabel = r.seasons ? `${r.media_type.toUpperCase()} (${esc(r.seasons)})` : r.media_type.toUpperCase();
            const yearStr = r.year ? ` (${esc(r.year)})` : '';
            const tag4k = r.is_4k ? '<span style="color: var(--accent); font-size: 8px; font-weight: bold; margin-left: 4px;">4K</span>' : '';

            return `
              <div class="card-item-row">
                <div class="item-row-top">
                  <span class="item-row-name" title="${esc(r.title)}">${esc(r.title)}${yearStr}${tag4k}</span>
                  <span class="item-row-meta" style="color: ${statusColor}; font-weight: 600;">${esc(r.status)}</span>
                </div>
                <div class="item-row-top" style="margin-top: 2px;">
                  <span class="item-row-meta">${typeLabel}</span>
                  <span class="item-row-meta">By ${esc(r.requested_by)}</span>
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
          <div class="stat-box-lbl">TOTAL REQUESTS</div>
          <div class="stat-box-val">${d.total_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">PENDING APPROVAL</div>
          <div class="stat-box-val" style="color: ${d.pending_requests > 0 ? 'var(--status-warn)' : 'inherit'};">${d.pending_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">PROCESSING</div>
          <div class="stat-box-val">${d.processing_requests || 0}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">AVAILABLE</div>
          <div class="stat-box-val">${d.available_requests || 0}</div>
        </div>
      </div>
      <div style="display: flex; gap: 8px; font-size: 10px; color: var(--text-dim); margin-top: 6px; padding: 2px 4px;">
        <span>Movies: <strong style="color: var(--text-main);">${d.movie_requests || 0}</strong></span>
        <span>|</span>
        <span>Series: <strong style="color: var(--text-main);">${d.tv_requests || 0}</strong></span>
        ${d.open_issues ? `<span>|</span><span style="color: var(--status-warn);">Open Issues: <strong>${d.open_issues}</strong></span>` : ''}
      </div>
      ${listHtml}
    `;
  },

  handbrake(d = {}) {
    const isEnc = Boolean(d.is_encoding && d.current_job);
    const job = d.current_job || {};
    const recent = d.recent_completed || [];

    let currentJobHtml = '';

    if (isEnc) {
      const prog = Math.min(Math.max(job.progress_percent || 0, 0), 100);
      const catBadge = job.category ? `<span class="badge" style="font-size: 9px; margin-left: 6px; padding: 2px 6px; background: rgba(56, 189, 248, 0.15); color: var(--accent);">${esc(job.category.toUpperCase())}</span>` : '';

      currentJobHtml = `
        <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-dim); border-radius: var(--radius-sm); padding: 10px; margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <div style="font-size: 11px; font-weight: 600; color: var(--text-bright); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80%;" title="${esc(job.filename)}">
              ${esc(job.title || job.filename)}${catBadge}
            </div>
            <div style="font-family: var(--font-mono); font-size: 10px; color: var(--accent); font-weight: 700;">
              ${prog.toFixed(1)}%
            </div>
          </div>
          <div class="progress-track" style="height: 6px; margin-bottom: 8px;">
            <div class="progress-fill" style="width: ${prog}%; background: var(--accent);"></div>
          </div>
          <div style="display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 10px; color: var(--text-dim);">
            <span>Task ${job.task_current} of ${job.task_total}</span>
            <span>${job.fps ? `${job.fps.toFixed(0)} FPS` : ''}${job.avg_fps ? ` (avg ${job.avg_fps.toFixed(0)})` : ''}</span>
            <span>ETA: ${esc(job.eta_formatted || job.eta || '-')}</span>
          </div>
        </div>
      `;
    } else {
      currentJobHtml = `
        <div style="background: rgba(255, 255, 255, 0.02); border: 1px dashed var(--border-dim); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 12px; text-align: center;">
          <div style="font-family: var(--font-mono); font-size: 11px; color: var(--status-online); font-weight: 600; margin-bottom: 2px;">
            ${esc(d.state_label || 'IDLE / WAITING')}
          </div>
          <div style="font-size: 10px; color: var(--text-dim);">
            ${recent.length > 0 ? `Last completed: ${esc(recent[0].title || recent[0].filename)}` : 'Watching folder for incoming media'}
          </div>
        </div>
      `;
    }

    let recentHtml = '';
    if (recent.length > 0) {
      recentHtml = `
        <div class="card-list-title">RECENT CONVERSIONS (${recent.length})</div>
        <div class="card-items-list">
          ${recent.slice(0, 4).map(r => `
            <div class="card-item-row">
              <div class="item-row-top">
                <span class="item-row-name" title="${esc(r.filename)}">${esc(r.title || r.filename)}</span>
                <span class="item-row-meta" style="color: var(--status-online); font-weight: 600;">DONE</span>
              </div>
              <div class="item-row-top" style="margin-top: 2px;">
                <span class="item-row-meta">${esc((r.category || 'media').toUpperCase())}</span>
              </div>
            </div>
          `).join('')}
        </div>
      `;
    }

    return `
      ${currentJobHtml}
      <div class="stat-grid-2">
        <div class="stat-box">
          <div class="stat-box-lbl">STATE</div>
          <div class="stat-box-val" style="color: ${isEnc ? 'var(--accent)' : 'var(--status-online)'}; font-size: 12px;">
            ${isEnc ? 'ENCODING' : 'IDLE'}
          </div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">CURRENT SPEED</div>
          <div class="stat-box-val">${isEnc && job.fps ? `${job.fps.toFixed(0)} FPS` : '0 FPS'}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">TOTAL COMPLETED</div>
          <div class="stat-box-val">${recent.length}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">SOURCE TYPE</div>
          <div class="stat-box-val" style="font-size: 11px;">${d.is_http ? 'HTTP STREAM' : 'LOCAL LOG'}</div>
        </div>
      </div>
      ${recentHtml}
    `;
  },

  renderStorageCard(pool) {
    const isOnline = Boolean(pool.is_accessible ?? pool.exists);
    const badgeClass = isOnline ? 'badge-online' : 'badge-offline';
    const statusText = isOnline ? `${fmtBytes(pool.free_bytes)} FREE` : 'UNMOUNTED';

    let bodyHtml = '';

    if (!isOnline) {
      bodyHtml = `
        <div class="stat-box">
          <div class="stat-box-lbl">DIAGNOSTIC</div>
          <div class="stat-box-val" style="color: var(--status-offline); font-size: 11px; margin-bottom: 6px;">
            ${esc(pool.error_message || pool.error || 'Mount path not found or permission denied')}
          </div>
          <div style="font-size: 10px; color: var(--text-dim); line-height: 1.4;">
            Container path: <span style="font-family: var(--font-mono); color: var(--text-main);">${esc(pool.mount_path)}</span>.<br>
            If running in Docker, ensure this path is mapped in <span style="font-family: var(--font-mono);">docker-compose.yml</span> under <span style="font-family: var(--font-mono);">volumes</span> (e.g. <span style="font-family: var(--font-mono);">- /mnt/storage:/storage:ro</span>) and run <span style="font-family: var(--font-mono);">docker compose up -d</span>.
          </div>
        </div>
      `;
    } else {
      const pct = pool.used_percent ?? pool.used_pct ?? 0;
      let fillClass = 'storage';
      if (pct > 90) fillClass = 'danger';
      else if (pct > 75) fillClass = 'warn';

      let foldersHtml = '';
      if (pool.folders && pool.folders.length > 0) {
        foldersHtml = `
          <div class="card-list-title" style="margin-top: 14px; margin-bottom: 6px;">WATCHED SUBFOLDERS</div>
          <div class="storage-folders-list">
            ${pool.folders.map(f => {
              const bytes = Number(f.bytes ?? f.size_bytes ?? 0);
              const exists = f.exists !== false;
              const fPctNum = (pool.total_bytes > 0 && !isNaN(bytes)) ? ((bytes / pool.total_bytes) * 100) : 0;
              const fPct = fPctNum.toFixed(1);
              const fSize = exists ? fmtBytes(bytes) : 'NOT FOUND';
              return `
                <div class="folder-row">
                  <div class="folder-row-head">
                    <span class="folder-name">${esc(f.name)}</span>
                    <span class="folder-meta">${fSize} ${exists ? `(${fPct}%)` : ''}</span>
                  </div>
                  ${exists ? `
                    <div class="progress-track">
                      <div class="progress-fill" style="width: ${Math.min(fPctNum, 100)}%;"></div>
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

  renderSystemCpuCard(sys) {
    const cpu = sys.cpu || {};
    const ram = sys.ram || {};
    const cpuPct = Math.min(Math.max(cpu.percent || 0, 0), 100);
    const ramPct = Math.min(Math.max(ram.percent || 0, 0), 100);

    let cpuFillClass = '';
    if (cpuPct > 90) cpuFillClass = 'danger';
    else if (cpuPct > 75) cpuFillClass = 'warn';

    let ramFillClass = 'storage';
    if (ramPct > 90) ramFillClass = 'danger';
    else if (ramPct > 75) ramFillClass = 'warn';

    const freqStr = cpu.freq_mhz ? `${(cpu.freq_mhz / 1000).toFixed(1)} GHz` : '';
    const coresStr = `${cpu.count_physical || 0}C / ${cpu.count_logical || 0}T`;
    const tempStr = cpu.temp_c ? ` • ${cpu.temp_c}°C` : '';
    const badgeText = `${freqStr ? `${freqStr} • ` : ''}${coresStr}${tempStr}`;

    return `
      <div class="card card-clickable" onclick="openSystemDetail('cpu')">
        <div class="card-header">
          <div class="card-title" title="${esc(cpu.brand || 'Host Processor')}">
            ${esc(cpu.brand || 'Host Processor')}
            <span class="card-type">[CPU / RAM]</span>
          </div>
          <div class="card-status-badge badge-online">${esc(badgeText)}</div>
        </div>
        <div class="card-body">
          <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
              <span>CPU UTILIZATION</span>
              <span style="color: ${cpuPct > 80 ? 'var(--status-warn)' : 'var(--text-bright)'}; font-weight: 700;">${cpuPct.toFixed(1)}%</span>
            </div>
            <div class="progress-track" style="height: 6px;">
              <div class="progress-fill ${cpuFillClass}" style="width: ${cpuPct}%;"></div>
            </div>
          </div>

          <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
              <span>MEMORY (${fmtBytes(ram.used_bytes)} / ${fmtBytes(ram.total_bytes)})</span>
              <span style="color: ${ramPct > 80 ? 'var(--status-warn)' : 'var(--text-bright)'}; font-weight: 700;">${ramPct.toFixed(1)}%</span>
            </div>
            <div class="progress-track" style="height: 6px;">
              <div class="progress-fill ${ramFillClass}" style="width: ${ramPct}%;"></div>
            </div>
          </div>

          <div class="stat-grid-2">
            <div class="stat-box">
              <div class="stat-box-lbl">AVAILABLE RAM</div>
              <div class="stat-box-val">${fmtBytes(ram.free_bytes)}</div>
            </div>
            <div class="stat-box">
              <div class="stat-box-lbl">SYSTEM UPTIME</div>
              <div class="stat-box-val" style="font-size: 11px;">${fmtSeconds(sys.uptime_seconds)}</div>
            </div>
          </div>
          <div class="card-action-hint">CLICK TO VIEW PER-CORE METRICS &amp; MEMORY</div>
        </div>
      </div>
    `;
  },

  renderSystemGpuCard(gpu) {
    const gpuPct = Math.min(Math.max(gpu.utilization_gpu_percent || 0, 0), 100);
    const vramPct = Math.min(Math.max(gpu.memory_percent || 0, 0), 100);

    let gpuFillClass = '';
    if (gpuPct > 90) gpuFillClass = 'danger';
    else if (gpuPct > 75) gpuFillClass = 'warn';

    let vendorTag = '[GPU]';
    let vendorColor = 'var(--accent)';
    const v = (gpu.vendor || '').toLowerCase();
    if (v === 'intel') {
      vendorTag = '[INTEL ARC]';
      vendorColor = '#0071c5';
    } else if (v === 'nvidia') {
      vendorTag = '[NVIDIA]';
      vendorColor = '#76b900';
    } else if (v === 'amd') {
      vendorTag = '[AMD RADEON]';
      vendorColor = '#ed1c24';
    }

    const tempStr = gpu.temperature_c ? `${gpu.temperature_c}°C` : (gpu.power_watts ? `${gpu.power_watts}W` : 'ONLINE');

    return `
      <div class="card card-clickable" onclick="openSystemDetail('${esc(gpu.id)}')">
        <div class="card-header">
          <div class="card-title" title="${esc(gpu.name)}">
            ${esc(gpu.name)}
            <span class="card-type" style="color: ${vendorColor};">${vendorTag}</span>
          </div>
          <div class="card-status-badge badge-online">${esc(tempStr)}</div>
        </div>
        <div class="card-body">
          <div style="margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
              <span>GPU CORE UTILIZATION</span>
              <span style="color: ${gpuPct > 80 ? 'var(--status-warn)' : 'var(--text-bright)'}; font-weight: 700;">${gpuPct.toFixed(1)}%</span>
            </div>
            <div class="progress-track" style="height: 6px;">
              <div class="progress-fill ${gpuFillClass}" style="width: ${gpuPct}%;"></div>
            </div>
          </div>

          ${gpu.memory_total_bytes > 0 ? `
            <div style="margin-bottom: 12px;">
              <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
                <span>VRAM (${fmtBytes(gpu.memory_used_bytes)} / ${fmtBytes(gpu.memory_total_bytes)})</span>
                <span style="font-weight: 700;">${vramPct.toFixed(1)}%</span>
              </div>
              <div class="progress-track" style="height: 6px;">
                <div class="progress-fill storage" style="width: ${vramPct}%;"></div>
              </div>
            </div>
          ` : ''}

          <div class="stat-grid-2">
            <div class="stat-box">
              <div class="stat-box-lbl">TEMPERATURE</div>
              <div class="stat-box-val" style="color: ${gpu.temperature_c && gpu.temperature_c > 80 ? 'var(--status-warn)' : 'inherit'};">
                ${gpu.temperature_c ? `${gpu.temperature_c}°C` : '-'}
              </div>
            </div>
            <div class="stat-box">
              <div class="stat-box-lbl">POWER DRAW</div>
              <div class="stat-box-val">${gpu.power_watts ? `${gpu.power_watts} W` : '-'}</div>
            </div>
          </div>
          <div class="card-action-hint">CLICK TO VIEW DETAILED GPU SPECS &amp; TELEMETRY</div>
        </div>
      </div>
    `;
  },

  renderSystemDetailView(sys, targetId = 'cpu') {
    const cpu = sys.cpu || {};
    const ram = sys.ram || {};
    const gpus = sys.gpus || [];

    const cpuPct = Math.min(Math.max(cpu.percent || 0, 0), 100);
    const ramPct = Math.min(Math.max(ram.percent || 0, 0), 100);

    const freqStr = cpu.freq_mhz ? `${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : '-';
    const tempStr = cpu.temp_c ? `${cpu.temp_c}°C` : '-';

    const coresList = cpu.cores || [];

    return `
      <div class="stat-grid-2" style="margin-bottom: 16px;">
        <div class="stat-box">
          <div class="stat-box-lbl">HOST OPERATING SYSTEM</div>
          <div class="stat-box-val" style="font-size: 11px;">${esc(sys.os || '-')} (${esc(sys.hostname || 'Server')})</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">SYSTEM UPTIME</div>
          <div class="stat-box-val" style="font-size: 11px;">${fmtSeconds(sys.uptime_seconds)}</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">CPU OVERALL LOAD</div>
          <div class="stat-box-val" style="color: ${cpuPct > 80 ? 'var(--status-warn)' : 'inherit'};">${cpuPct.toFixed(1)}%</div>
        </div>
        <div class="stat-box">
          <div class="stat-box-lbl">CPU CLOCK / TEMP</div>
          <div class="stat-box-val" style="font-size: 11px;">${esc(freqStr)} / ${esc(tempStr)}</div>
        </div>
      </div>

      <div class="section-title" style="margin-bottom: 6px;">CPU ARCHITECTURE &amp; PER-CORE UTILIZATION (${coresList.length} LOGICAL THREADS)</div>
      <div class="core-grid" style="margin-bottom: 18px;">
        ${coresList.map((cp, idx) => {
          const cPct = Math.min(Math.max(cp || 0, 0), 100);
          let fillClass = '';
          if (cPct > 85) fillClass = 'danger';
          else if (cPct > 70) fillClass = 'warn';
          return `
            <div class="core-box">
              <div class="core-box-top">
                <span>CORE ${idx}</span>
                <span style="font-weight: 700;">${cPct.toFixed(0)}%</span>
              </div>
              <div class="progress-track" style="height: 4px;">
                <div class="progress-fill ${fillClass}" style="width: ${cPct}%;"></div>
              </div>
            </div>
          `;
        }).join('')}
      </div>

      <div class="section-title" style="margin-bottom: 6px;">MEMORY &amp; SWAP ALLOCATION</div>
      <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-dim); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 18px;">
        <div style="margin-bottom: 12px;">
          <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
            <span>PHYSICAL RAM (${fmtBytes(ram.used_bytes)} USED / ${fmtBytes(ram.total_bytes)} TOTAL)</span>
            <span style="font-weight: 700;">${ramPct.toFixed(1)}%</span>
          </div>
          <div class="progress-track" style="height: 6px;">
            <div class="progress-fill storage" style="width: ${ramPct}%;"></div>
          </div>
        </div>

        ${ram.swap_total_bytes > 0 ? `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-bottom: 4px;">
              <span>SWAP / PAGEFILE (${fmtBytes(ram.swap_used_bytes)} USED / ${fmtBytes(ram.swap_total_bytes)} TOTAL)</span>
              <span style="font-weight: 700;">${(ram.swap_percent || 0).toFixed(1)}%</span>
            </div>
            <div class="progress-track" style="height: 6px;">
              <div class="progress-fill warn" style="width: ${Math.min(ram.swap_percent || 0, 100)}%;"></div>
            </div>
          </div>
        ` : ''}
      </div>

      <div class="section-title" style="margin-bottom: 8px;">GRAPHICS HARDWARE (${gpus.length} DETECTED)</div>
      ${gpus.length === 0 ? `
        <div style="font-size: 11px; color: var(--text-dim); font-family: var(--font-mono); padding: 12px; border: 1px dashed var(--border-dim);">
          No dedicated graphics adapters detected on host server.
        </div>
      ` : `
        <div style="overflow-x: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>GPU NAME</th>
                <th>VENDOR</th>
                <th>DRIVER</th>
                <th>CORE USAGE</th>
                <th>VRAM (USED / TOTAL)</th>
                <th>TEMP</th>
                <th>POWER</th>
              </tr>
            </thead>
            <tbody>
              ${gpus.map(g => {
                const gUtil = Math.min(Math.max(g.utilization_gpu_percent || 0, 0), 100);
                const gMem = Math.min(Math.max(g.memory_percent || 0, 0), 100);
                let vColor = 'var(--accent)';
                if (g.vendor === 'intel') vColor = '#0071c5';
                else if (g.vendor === 'nvidia') vColor = '#76b900';
                else if (g.vendor === 'amd') vColor = '#ed1c24';

                const vramStr = g.memory_total_bytes > 0 ? `${fmtBytes(g.memory_used_bytes)} / ${fmtBytes(g.memory_total_bytes)} (${gMem.toFixed(0)}%)` : '-';
                const tempStr = g.temperature_c ? `${g.temperature_c}°C` : '-';
                const pwrStr = g.power_watts ? `${g.power_watts} W` : '-';

                return `
                  <tr>
                    <td style="font-weight: 600; color: var(--text-bright);">${esc(g.name)}</td>
                    <td style="font-family: var(--font-mono); font-size: 10px; font-weight: 700; color: ${vColor}; text-transform: uppercase;">${esc(g.vendor)}</td>
                    <td style="font-family: var(--font-mono); font-size: 10px; color: var(--text-dim);">${esc(g.driver_version || '-')}</td>
                    <td style="font-family: var(--font-mono); font-weight: 700; color: ${gUtil > 80 ? 'var(--status-warn)' : 'var(--text-bright)'};">${gUtil.toFixed(1)}%</td>
                    <td style="font-family: var(--font-mono); font-size: 11px;">${esc(vramStr)}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: ${g.temperature_c && g.temperature_c > 80 ? 'var(--status-warn)' : 'inherit'};">${esc(tempStr)}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px;">${esc(pwrStr)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `}
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
      const libraries = d.libraries || [];
      const counts = d.item_counts || {};

      let librarySummaryHtml = '';
      if (counts.movies || counts.series || counts.episodes || counts.songs || counts.books || counts.total) {
        librarySummaryHtml = `
          <div class="stat-grid-2" style="margin-bottom: 16px;">
            <div class="stat-box">
              <div class="stat-box-lbl">TOTAL MOVIES</div>
              <div class="stat-box-val">${(counts.movies || 0).toLocaleString()}</div>
            </div>
            <div class="stat-box">
              <div class="stat-box-lbl">TOTAL SHOWS / SERIES</div>
              <div class="stat-box-val">${(counts.series || 0).toLocaleString()} <span style="font-size: 10px; color: var(--text-dim);">(${(counts.episodes || 0).toLocaleString()} eps)</span></div>
            </div>
            <div class="stat-box">
              <div class="stat-box-lbl">MUSIC TRACKS / ALBUMS</div>
              <div class="stat-box-val">${(counts.songs || 0).toLocaleString()} <span style="font-size: 10px; color: var(--text-dim);">(${(counts.albums || 0).toLocaleString()} albums)</span></div>
            </div>
            <div class="stat-box">
              <div class="stat-box-lbl">TOTAL CATALOG ITEMS</div>
              <div class="stat-box-val">${(counts.total || 0).toLocaleString()}</div>
            </div>
          </div>
        `;
      }

      let librariesTableHtml = '';
      if (libraries.length > 0) {
        librariesTableHtml = `
          <div class="section-title" style="margin-top: 18px; margin-bottom: 8px;">MEDIA LIBRARIES (${libraries.length})</div>
          <div style="overflow-x: auto; max-height: 350px; overflow-y: auto; border: 1px solid var(--border-dim); margin-bottom: 16px;">
            <table class="detail-table">
              <thead>
                <tr>
                  <th>LIBRARY NAME</th>
                  <th>CONTENT TYPE</th>
                  <th>TOTAL ITEMS</th>
                  <th>BREAKDOWN</th>
                </tr>
              </thead>
              <tbody>
                ${libraries.map(lib => `
                  <tr>
                    <td style="font-weight: 600; color: var(--text-bright);">${esc(lib.name)}</td>
                    <td style="font-family: var(--font-mono); text-transform: uppercase; font-size: 10px; color: var(--accent);">${esc(lib.type)}</td>
                    <td style="font-family: var(--font-mono); font-weight: 600;">${(lib.count || 0).toLocaleString()}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-main);">${esc(lib.formatted || (lib.count + ' items'))}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      }

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

        ${librarySummaryHtml}
        ${librariesTableHtml}

        <div class="section-title" style="margin-bottom: 8px;">ACTIVE SESSIONS DETAIL (${streams.length})</div>
        <div style="overflow-x: auto; max-height: 400px; overflow-y: auto; border: 1px solid var(--border-dim);">
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
      const allRequests = d.recent_requests || [];
      const filter = state.detailFilter || 'all';
      const search = (state.detailSearch || '').toLowerCase().trim();

      const counts = {
        all: allRequests.length,
        pending: allRequests.filter(r => r.status === 'Pending Approval').length,
        processing: allRequests.filter(r => r.status === 'Processing').length,
        available: allRequests.filter(r => r.status === 'Available').length,
        approved: allRequests.filter(r => r.status === 'Approved').length,
      };

      const filtered = allRequests.filter(r => {
        if (filter === 'pending' && r.status !== 'Pending Approval') return false;
        if (filter === 'processing' && r.status !== 'Processing') return false;
        if (filter === 'available' && r.status !== 'Available') return false;
        if (filter === 'approved' && r.status !== 'Approved') return false;
        if (filter === 'movies' && r.media_type !== 'movie') return false;
        if (filter === 'tv' && r.media_type !== 'tv') return false;

        if (search) {
          const t = (r.title || '').toLowerCase();
          const u = (r.requested_by || '').toLowerCase();
          if (!t.includes(search) && !u.includes(search)) return false;
        }
        return true;
      });

      return `
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">TOTAL REQUESTS</div>
            <div class="stat-box-val">${d.total_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">PENDING APPROVAL</div>
            <div class="stat-box-val" style="color: ${d.pending_requests > 0 ? 'var(--status-warn)' : 'inherit'};">${d.pending_requests || 0}</div>
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
            <div class="stat-box-lbl">MOVIE REQUESTS</div>
            <div class="stat-box-val">${d.movie_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TV SHOW REQUESTS</div>
            <div class="stat-box-val">${d.tv_requests || 0}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">SERVER VERSION</div>
            <div class="stat-box-val" style="font-size: 11px;">${esc(d.version || 'Jellyseerr')}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">OPEN ISSUES</div>
            <div class="stat-box-val" style="color: ${d.open_issues > 0 ? 'var(--status-warn)' : 'inherit'};">${d.open_issues || 0}</div>
          </div>
        </div>

        <div class="detail-filters">
          <button class="filter-chip ${filter === 'all' ? 'active' : ''}" onclick="setDetailFilter('all')">ALL (${counts.all})</button>
          <button class="filter-chip ${filter === 'pending' ? 'active' : ''}" onclick="setDetailFilter('pending')">PENDING (${counts.pending})</button>
          <button class="filter-chip ${filter === 'processing' ? 'active' : ''}" onclick="setDetailFilter('processing')">PROCESSING (${counts.processing})</button>
          <button class="filter-chip ${filter === 'available' ? 'active' : ''}" onclick="setDetailFilter('available')">AVAILABLE (${counts.available})</button>
          <button class="filter-chip ${filter === 'approved' ? 'active' : ''}" onclick="setDetailFilter('approved')">APPROVED (${counts.approved})</button>
          <button class="filter-chip ${filter === 'movies' ? 'active' : ''}" onclick="setDetailFilter('movies')">MOVIES</button>
          <button class="filter-chip ${filter === 'tv' ? 'active' : ''}" onclick="setDetailFilter('tv')">SERIES</button>
          <div style="flex: 1; min-width: 180px; margin-left: auto;">
            <input type="text" id="detail-search-input" class="input-text" style="width: 100%; padding: 4px 8px; font-size: 11px;" placeholder="Search requests by title or user..." value="${esc(search)}" oninput="handleDetailSearch(this.value)">
          </div>
        </div>

        <div class="section-title" style="margin-top: 14px; margin-bottom: 8px;">REQUEST CATALOG (${filtered.length})</div>
        <div style="overflow-x: auto; max-height: 500px; overflow-y: auto; border: 1px solid var(--border-dim);">
          <table class="detail-table">
            <thead>
              <tr>
                <th>MEDIA TITLE</th>
                <th>TYPE</th>
                <th>SEASONS</th>
                <th>REQUESTED BY</th>
                <th>DATE REQUESTED</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.length === 0 ? `
                <tr><td colspan="6" style="text-align: center; padding: 24px; color: var(--text-dim);">No matching requests found</td></tr>
              ` : filtered.map(r => {
                let statusColor = 'var(--text-dim)';
                if (r.status === 'Available') statusColor = 'var(--status-online)';
                else if (r.status === 'Processing' || r.status === 'Approved') statusColor = 'var(--accent)';
                else if (r.status === 'Pending Approval') statusColor = 'var(--status-warn)';
                else if (r.status === 'Declined') statusColor = 'var(--status-offline)';

                const yearStr = r.year ? ` (${esc(r.year)})` : '';
                const tag4k = r.is_4k ? '<span style="color: var(--accent); font-size: 9px; font-weight: bold; margin-left: 6px;">4K</span>' : '';
                const dateStr = r.created_at ? r.created_at.replace('T', ' ').substring(0, 16) : '-';

                return `
                  <tr>
                    <td style="font-weight: 600; color: var(--text-bright);">${esc(r.title)}${yearStr}${tag4k}</td>
                    <td style="font-family: var(--font-mono); text-transform: uppercase; font-size: 10px; color: var(--accent);">${esc(r.media_type)}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px;">${esc(r.seasons || '-')}</td>
                    <td style="font-family: var(--font-mono);">${esc(r.requested_by)}</td>
                    <td style="font-family: var(--font-mono); font-size: 10px; color: var(--text-dim);">${esc(dateStr)}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: ${statusColor}; font-weight: 600;">${esc(r.status)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    if (type === 'handbrake' || type === 'autovideoconverter') {
      const job = d.current_job;
      const recent = d.recent_completed || [];
      const logTail = d.log_tail || [];
      const search = (state.detailSearch || '').toLowerCase().trim();

      const filteredRecent = recent.filter(r => {
        if (!search) return true;
        return (r.title || '').toLowerCase().includes(search) || (r.filename || '').toLowerCase().includes(search) || (r.category || '').toLowerCase().includes(search);
      });

      const filteredLog = logTail.filter(line => {
        if (!search) return true;
        return line.toLowerCase().includes(search);
      });

      let currentJobCard = '';
      if (job) {
        const prog = Math.min(Math.max(job.progress_percent || 0, 0), 100);
        currentJobCard = `
          <div style="background: rgba(56, 189, 248, 0.05); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: var(--radius-sm); padding: 16px; margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
              <div>
                <div style="font-size: 10px; font-family: var(--font-mono); color: var(--accent); letter-spacing: 1px; margin-bottom: 4px;">ACTIVE TRANSCODE JOB</div>
                <div style="font-size: 14px; font-weight: 700; color: var(--text-bright);">${esc(job.title || job.filename)}</div>
                <div style="font-size: 10px; font-family: var(--font-mono); color: var(--text-dim); margin-top: 2px;">${esc(job.file_path)}</div>
              </div>
              <div style="text-align: right;">
                <div style="font-size: 20px; font-family: var(--font-mono); font-weight: 800; color: var(--accent);">${prog.toFixed(1)}%</div>
                <div style="font-size: 10px; font-family: var(--font-mono); color: var(--text-dim);">Task ${job.task_current} of ${job.task_total}</div>
              </div>
            </div>

            <div class="progress-track" style="height: 10px; margin: 12px 0;">
              <div class="progress-fill" style="width: ${prog}%; background: var(--accent);"></div>
            </div>

            <div class="stat-grid-2" style="margin-top: 12px;">
              <div class="stat-box">
                <div class="stat-box-lbl">ENCODING SPEED</div>
                <div class="stat-box-val">${job.fps ? `${job.fps.toFixed(1)} FPS` : '-'}</div>
              </div>
              <div class="stat-box">
                <div class="stat-box-lbl">AVERAGE SPEED</div>
                <div class="stat-box-val">${job.avg_fps ? `${job.avg_fps.toFixed(1)} FPS` : '-'}</div>
              </div>
              <div class="stat-box">
                <div class="stat-box-lbl">ESTIMATED TIME (ETA)</div>
                <div class="stat-box-val" style="color: var(--accent);">${esc(job.eta_formatted || job.eta || '-')}</div>
              </div>
              <div class="stat-box">
                <div class="stat-box-lbl">TARGET CATEGORY</div>
                <div class="stat-box-val" style="text-transform: uppercase;">${esc(job.category || 'General')}</div>
              </div>
            </div>
          </div>
        `;
      }

      return `
        ${currentJobCard}
        <div class="stat-grid-2" style="margin-bottom: 16px;">
          <div class="stat-box">
            <div class="stat-box-lbl">CONVERTER STATE</div>
            <div class="stat-box-val" style="color: ${job ? 'var(--accent)' : 'var(--status-online)'};">${esc(d.state_label || 'IDLE')}</div>
          </div>
          <div class="stat-box">
            <div class="stat-box-lbl">TARGET LOG SOURCE</div>
            <div class="stat-box-val" style="font-size: 11px; word-break: break-all;">${esc(d.target || '-')}</div>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <div class="section-title" style="margin: 0;">LOG ACTIVITY &amp; RECENT CONVERSIONS</div>
          <div style="width: 240px;">
            <input type="text" id="detail-search-input" class="input-text" style="width: 100%; padding: 4px 8px; font-size: 11px;" placeholder="Search log or conversions..." value="${esc(search)}" oninput="handleDetailSearch(this.value)">
          </div>
        </div>

        ${filteredRecent.length > 0 ? `
          <div class="section-title" style="font-size: 11px; margin-bottom: 6px;">RECENT COMPLETED (${filteredRecent.length})</div>
          <div style="overflow-x: auto; margin-bottom: 16px; border: 1px solid var(--border-dim);">
            <table class="detail-table">
              <thead>
                <tr>
                  <th>MEDIA FILENAME</th>
                  <th>CATEGORY</th>
                  <th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                ${filteredRecent.map(r => `
                  <tr>
                    <td style="font-weight: 600; color: var(--text-bright);">${esc(r.title || r.filename)}</td>
                    <td style="font-family: var(--font-mono); text-transform: uppercase; font-size: 10px; color: var(--accent);">${esc(r.category || '-')}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: var(--status-online); font-weight: 600;">Completed</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        ` : ''}

        <div class="section-title" style="font-size: 11px; margin-bottom: 6px;">LIVE LOG TAIL (LAST ${filteredLog.length} LINES)</div>
        <div style="background: #090d13; border: 1px solid var(--border-dim); border-radius: var(--radius-sm); padding: 12px; font-family: var(--font-mono); font-size: 11px; line-height: 1.6; max-height: 350px; overflow-y: auto; color: #94a3b8; white-space: pre-wrap; word-break: break-all;">
          ${filteredLog.length === 0 ? 'No log lines available.' : filteredLog.map(l => {
            let color = '#94a3b8';
            const low = l.toLowerCase();
            if (low.includes('encoding')) color = '#38bdf8';
            else if (low.includes('finished') || low.includes('completed') || low.includes('done') || low.includes('rip done')) color = '#34d399';
            else if (low.includes('error') || low.includes('fail')) color = '#f87171';
            return `<div style="color: ${color};">${esc(l)}</div>`;
          }).join('')}
        </div>
      `;
    }

    return `<div class="empty-state">No detailed telemetry available for this service type.</div>`;
  }
};
