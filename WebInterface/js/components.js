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

    return `
      <div class="card" data-id="${item.service_id}">
        <div class="card-header">
          <div class="card-title">
            ${esc(item.name)}
            <span class="card-type">[${esc(type.toUpperCase())}]</span>
          </div>
          <div class="card-status-badge ${badgeClass}">${esc(statusText)}</div>
        </div>
        <div class="card-body">
          ${bodyHtml}
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
  }
};
