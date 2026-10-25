const SAMPLES = [
  "aHR0cHM6Ly9wYXN0ZS5zaC93NFRiUm0wWiNuOTROWXFtYk9PSzN5MnJkcmg3ZWZtZk0=",
  "aHR0cHM6Ly9wYXN0ZS5zaC9fWnhsQTlWNSMyZVgyT1U3cjdwODNuUnQ4V1M1V2JKUVg=",
  "aHR0cHM6Ly9wYXN0ZS5zaC94akZ3LW5pVCN4OVRDSHBFZkl3VWZLSTh1NDdqQ0htNk0=",
  "aHR0cHM6Ly9wYXN0ZS5zaC9OQkFKM3VRUiNuX25wX3EtUFNCdzBEQWlJVDZiQS1fYlE"
];

// State
let allResults = [];
let currentFilter = 'all';
let searchQuery = '';
let isAuditing = false;
let isPaused = false;
let currentSessionId = null;
let abortController = null;
let auditStartTime = 0;

// DOM Elements
const inputStrings = document.getElementById('input-strings');
const btnSample = document.getElementById('btn-sample');
const btnClear = document.getElementById('btn-clear');
const btnAudit = document.getElementById('btn-audit');
const btnPause = document.getElementById('btn-pause');
const btnStop = document.getElementById('btn-stop');
const pauseIcon = document.getElementById('pause-icon');
const pauseText = document.getElementById('pause-text');
const btnIcon = document.getElementById('btn-icon');
const btnText = document.getElementById('btn-text');

const optProbe = document.getElementById('opt-probe-stream');
const optMode = document.getElementById('opt-mode');
const optConcurrency = document.getElementById('opt-concurrency');

const progressContainer = document.getElementById('progress-container');
const progressStatus = document.getElementById('progress-status');
const progressCount = document.getElementById('progress-count');
const progressBar = document.getElementById('progress-bar');
const speedMeter = document.getElementById('speed-meter');

const statsSection = document.getElementById('stats-section');
const statTotal = document.getElementById('stat-total');
const statWorking = document.getElementById('stat-working');
const statFailed = document.getElementById('stat-failed');
const statAdult = document.getElementById('stat-adult');

const toolbarSection = document.getElementById('toolbar-section');
const searchInput = document.getElementById('search-input');
const filterBtns = document.querySelectorAll('.filter-btn');
const btnCopyWorking = document.getElementById('btn-copy-working');
const btnExportCsv = document.getElementById('btn-export-csv');

const resultsCard = document.getElementById('results-card');
const resultsTbody = document.getElementById('results-tbody');
const emptyState = document.getElementById('empty-state');
const globalBadge = document.getElementById('global-badge');

// Sample button
btnSample.addEventListener('click', () => {
  inputStrings.value = SAMPLES.join('\n');
  showToast('Loaded 4 sample encoded strings!');
});

// Clear button
btnClear.addEventListener('click', () => {
  inputStrings.value = '';
});

// Search input
searchInput.addEventListener('input', (e) => {
  searchQuery = e.target.value.toLowerCase().trim();
  renderTable();
});

// Filter buttons
filterBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    filterBtns.forEach(b => {
      b.classList.remove('bg-orange-600', 'text-white');
      b.classList.add('text-slate-400');
    });
    btn.classList.add('bg-orange-600', 'text-white');
    btn.classList.remove('text-slate-400');
    currentFilter = btn.dataset.filter;
    renderTable();
  });
});

// Audit Start / Trigger
btnAudit.addEventListener('click', () => {
  const text = inputStrings.value.trim();
  if (!text) {
    showToast('Please paste at least one string or URL first.', 'error');
    return;
  }
  if (isAuditing) return;
  startAudit(text);
});

// Pause / Resume Button
btnPause.addEventListener('click', async () => {
  if (!currentSessionId || !isAuditing) return;

  if (!isPaused) {
    // Request Pause
    try {
      await fetch(`/api/audit/pause/${currentSessionId}`, { method: 'POST' });
      isPaused = true;
      pauseIcon.className = 'fa-solid fa-play';
      pauseText.textContent = 'Resume';
      btnPause.classList.remove('bg-amber-600/20', 'text-amber-300', 'border-amber-500/30');
      btnPause.classList.add('bg-emerald-600/30', 'text-emerald-300', 'border-emerald-500/40');
      progressStatus.textContent = 'Audit Paused';
      globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span> Paused`;
      showToast('Audit paused.');
    } catch (e) {
      console.error(e);
    }
  } else {
    // Request Resume
    try {
      await fetch(`/api/audit/resume/${currentSessionId}`, { method: 'POST' });
      isPaused = false;
      pauseIcon.className = 'fa-solid fa-pause';
      pauseText.textContent = 'Pause';
      btnPause.classList.remove('bg-emerald-600/30', 'text-emerald-300', 'border-emerald-500/40');
      btnPause.classList.add('bg-amber-600/20', 'text-amber-300', 'border-amber-500/30');
      progressStatus.textContent = 'Resuming audit...';
      globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-orange-400 animate-ping"></span> Auditing...`;
      showToast('Audit resumed.');
    } catch (e) {
      console.error(e);
    }
  }
});

// Stop Button
btnStop.addEventListener('click', async () => {
  if (!currentSessionId && !isAuditing) return;

  try {
    if (currentSessionId) {
      await fetch(`/api/audit/stop/${currentSessionId}`, { method: 'POST' });
    }
  } catch (e) {
    console.error(e);
  }

  if (abortController) {
    abortController.abort();
  }

  isAuditing = false;
  isPaused = false;
  setControlButtonsState(false);
  progressStatus.textContent = `Stopped. Retained ${allResults.length} audited servers.`;
  speedMeter.textContent = '';
  showToast('Audit stopped by user.', 'error');
});

async function startAudit(text) {
  isAuditing = true;
  isPaused = false;
  setControlButtonsState(true);
  allResults = [];
  resultsTbody.innerHTML = '';
  auditStartTime = Date.now();

  emptyState.classList.add('hidden');
  progressContainer.classList.remove('hidden');
  statsSection.classList.remove('hidden');
  toolbarSection.classList.remove('hidden');
  resultsCard.classList.remove('hidden');

  updateStats();
  progressBar.style.width = '3%';
  progressStatus.textContent = 'Connecting...';
  progressCount.textContent = '0%';
  speedMeter.textContent = '';

  abortController = new AbortController();

  try {
    const response = await fetch('/api/audit/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: abortController.signal,
      body: JSON.stringify({
        input_text: text,
        probe_stream: optProbe.checked,
        audit_mode: optMode.value,
        concurrency: parseInt(optConcurrency.value) || 25
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP error ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop();

      for (const block of lines) {
        if (!block.trim().startsWith('data:')) continue;
        const jsonStr = block.replace(/^data:\s*/, '').trim();
        try {
          const event = JSON.parse(jsonStr);
          handleSSEEvent(event);
        } catch (e) {
          console.error('Error parsing SSE event:', e, jsonStr);
        }
      }
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      return;
    }
    showToast(`Audit failed: ${err.message}`, 'error');
    progressStatus.textContent = `Error: ${err.message}`;
  } finally {
    isAuditing = false;
    isPaused = false;
    currentSessionId = null;
    setControlButtonsState(false);
  }
}

function handleSSEEvent(event) {
  if (event.type === 'session_init') {
    currentSessionId = event.session_id;
  } else if (event.type === 'status' || event.type === 'warning') {
    progressStatus.textContent = event.message;
  } else if (event.type === 'extracted_urls') {
    progressStatus.textContent = event.message;
    progressBar.style.width = '10%';
  } else if (event.type === 'parsed_servers') {
    progressStatus.textContent = event.message;
    progressBar.style.width = '15%';
  } else if (event.type === 'server_result') {
    const data = event.data;
    allResults.push(data);
    updateStats();

    if (data.total && data.completed) {
      const pct = Math.round((data.completed / data.total) * 100);
      progressBar.style.width = `${Math.max(15, pct)}%`;
      progressCount.textContent = `${pct}%`;
      progressStatus.textContent = `Audited ${data.completed} of ${data.total} servers...`;

      // Live speed meter
      const elapsedSec = (Date.now() - auditStartTime) / 1000;
      if (elapsedSec > 1) {
        const rate = (data.completed / elapsedSec).toFixed(1);
        speedMeter.textContent = `(${rate} servers/sec)`;
      }
    }

    renderTable();
  } else if (event.type === 'audit_complete') {
    progressBar.style.width = '100%';
    progressCount.textContent = '100%';
    const elapsedSec = ((Date.now() - auditStartTime) / 1000).toFixed(1);
    progressStatus.textContent = `Completed ${allResults.length} servers in ${elapsedSec}s!`;
    speedMeter.textContent = '';
    showToast(`Audit complete in ${elapsedSec}s!`, 'success');
  } else if (event.type === 'audit_stopped') {
    progressStatus.textContent = event.message;
    speedMeter.textContent = '';
  } else if (event.type === 'error') {
    progressStatus.textContent = event.message;
    showToast(event.message, 'error');
  }
}

function setControlButtonsState(active) {
  if (active) {
    btnAudit.disabled = true;
    btnAudit.classList.add('opacity-50', 'cursor-not-allowed');
    btnIcon.className = 'fa-solid fa-spinner fa-spin';
    btnText.textContent = 'Auditing...';

    // Enable Pause & Stop
    btnPause.disabled = false;
    btnPause.classList.remove('text-amber-400/50', 'border-amber-500/20', 'cursor-not-allowed');
    btnPause.classList.add('text-amber-300', 'border-amber-500/40', 'hover:bg-amber-600/30', 'cursor-pointer');
    pauseIcon.className = 'fa-solid fa-pause';
    pauseText.textContent = 'Pause';

    btnStop.disabled = false;
    btnStop.classList.remove('text-red-400/50', 'border-red-500/20', 'cursor-not-allowed');
    btnStop.classList.add('text-red-300', 'border-red-500/40', 'hover:bg-red-600/30', 'cursor-pointer');

    globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-orange-400 animate-ping"></span> Auditing...`;
  } else {
    btnAudit.disabled = false;
    btnAudit.classList.remove('opacity-50', 'cursor-not-allowed');
    btnIcon.className = 'fa-solid fa-play';
    btnText.textContent = 'Audit Servers';

    // Disable Pause & Stop
    btnPause.disabled = true;
    btnPause.className = 'px-4 py-2.5 rounded-xl bg-amber-600/20 text-amber-400/50 border border-amber-500/20 font-semibold text-xs transition flex items-center gap-1.5 cursor-not-allowed';
    pauseIcon.className = 'fa-solid fa-pause';
    pauseText.textContent = 'Pause';

    btnStop.disabled = true;
    btnStop.className = 'px-4 py-2.5 rounded-xl bg-red-600/20 text-red-400/50 border border-red-500/20 font-semibold text-xs transition flex items-center gap-1.5 cursor-not-allowed';

    globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400"></span> Ready`;
  }
}

function updateStats() {
  statTotal.textContent = allResults.length;
  statWorking.textContent = allResults.filter(r => r.is_working).length;
  statFailed.textContent = allResults.filter(r => !r.is_working).length;
  
  const adultServers = allResults.filter(r => r.has_adult).length;
  const totalAdultCh = allResults.reduce((sum, r) => sum + (r.adult_channels || 0), 0);
  if (totalAdultCh > 0) {
    statAdult.innerHTML = `${adultServers} <span class="text-xs font-normal text-pink-300">(${totalAdultCh.toLocaleString()} ch)</span>`;
  } else {
    statAdult.textContent = adultServers;
  }
}

let currentFilteredList = [];

function renderTable() {
  currentFilteredList = allResults.filter(r => {
    if (searchQuery) {
      const matchHost = (r.host || '').toLowerCase().includes(searchQuery);
      const matchUser = (r.username || '').toLowerCase().includes(searchQuery);
      if (!matchHost && !matchUser) return false;
    }
    if (currentFilter === 'active') return r.is_working;
    if (currentFilter === 'adult') return r.has_adult;
    if (currentFilter === 'stream_ok') return (r.stream_probe || '').toLowerCase().includes('playable');
    return true;
  });

  if (currentFilteredList.length === 0) {
    resultsTbody.innerHTML = `
      <tr>
        <td colspan="11" class="text-center py-8 text-slate-500">
          No servers match the selected criteria.
        </td>
      </tr>
    `;
    return;
  }

  resultsTbody.innerHTML = currentFilteredList.map((r, idx) => {
    let statusClass = 'bg-slate-800 text-slate-400 border-slate-700';
    let statusIcon = 'fa-circle-question';
    if (r.status_badge === 'active') {
      statusClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
      statusIcon = 'fa-circle-check';
    } else if (r.status_badge === 'expired') {
      statusClass = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
      statusIcon = 'fa-clock';
    } else if (r.status_badge === 'invalid' || r.status_badge === 'offline') {
      statusClass = 'bg-red-500/10 text-red-400 border-red-500/20';
      statusIcon = 'fa-circle-xmark';
    }

    let streamClass = 'text-slate-400';
    if (r.stream_probe_badge === 'green') streamClass = 'text-emerald-400 font-medium';
    else if (r.stream_probe_badge === 'yellow') streamClass = 'text-amber-400';
    else if (r.stream_probe_badge === 'red') streamClass = 'text-red-400';

    let adultBadge = '<span class="text-slate-500 font-mono text-xs">0</span>';
    if (r.adult_channels > 0) {
      adultBadge = `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-pink-500/15 text-pink-400 border border-pink-500/30 font-semibold font-mono text-xs" title="${escapeHtml(r.adult_details)}"><i class="fa-solid fa-venus-mars text-[10px]"></i>${r.adult_channels.toLocaleString()} ch</span>`;
    } else if (r.has_adult) {
      adultBadge = `<span class="px-2 py-0.5 rounded-full bg-pink-500/10 text-pink-400 border border-pink-500/20 text-xs font-medium" title="${escapeHtml(r.adult_details)}">Yes (VOD)</span>`;
    }

    const latencyTag = r.latency_ms > 0 ? `<span class="text-[10px] text-slate-500 font-mono ml-1">(${r.latency_ms}ms)</span>` : '';

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3 px-4 whitespace-nowrap">
          <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${statusClass}">
            <i class="fa-solid ${statusIcon} text-[10px]"></i>
            ${escapeHtml(r.status)}
          </span>
        </td>

        <td class="py-3 px-4 font-mono font-medium text-slate-200">
          <div class="flex items-center">
            ${escapeHtml(r.host)}
            ${latencyTag}
          </div>
        </td>

        <td class="py-3 px-4 font-mono text-slate-300">
          <div class="text-xs font-semibold">${escapeHtml(r.username)}</div>
          <div class="text-[10px] text-slate-500 select-all">${escapeHtml(r.password)}</div>
        </td>

        <td class="py-3 px-4 whitespace-nowrap">
          <span class="font-mono ${r.active_connections >= r.max_connections && r.max_connections > 0 ? 'text-amber-400 font-bold' : 'text-slate-300'}">
            ${r.active_connections} / ${r.max_connections}
          </span>
        </td>

        <td class="py-3 px-4 whitespace-nowrap">
          <div class="text-slate-200 font-medium">${escapeHtml(r.exp_date || 'N/A')}</div>
          <div class="text-[10px] text-slate-500">${escapeHtml(r.exp_countdown || '')}</div>
        </td>

        <td class="py-3 px-4 text-center font-mono ${r.live_channels > 0 ? 'text-slate-200 font-semibold' : 'text-slate-500'}">
          ${r.live_channels.toLocaleString()}
        </td>

        <td class="py-3 px-4 text-center font-mono ${r.movies_vod > 0 ? 'text-slate-200 font-semibold' : 'text-slate-500'}">
          ${r.movies_vod.toLocaleString()}
        </td>

        <td class="py-3 px-4 text-center font-mono ${r.series > 0 ? 'text-slate-200 font-semibold' : 'text-slate-500'}">
          ${r.series.toLocaleString()}
        </td>

        <td class="py-3 px-4 text-center whitespace-nowrap">
          ${adultBadge}
        </td>

        <td class="py-3 px-4 whitespace-nowrap text-xs ${streamClass}">
          <div>${escapeHtml(r.stream_probe || 'N/A')}</div>
          ${r.test_channel_name ? `
            <div class="mt-0.5 text-[11px] font-sans truncate max-w-[160px] text-slate-400 flex items-center gap-1" title="${escapeHtml(r.test_channel_name)}">
              <i class="fa-solid fa-tv text-[9px] text-orange-400"></i>
              <span class="truncate">${escapeHtml(r.test_channel_name)}</span>
            </div>` : ''}
        </td>

        <td class="py-3 px-4 text-right whitespace-nowrap">
          <div class="inline-flex items-center gap-1.5">
            ${r.is_working && (r.vlc_url || r.test_stream_url) ? `
              <a href="/api/play/m3u?url=${encodeURIComponent(r.test_stream_url || '')}&title=${encodeURIComponent(r.test_channel_name || 'BBC News')}" 
                 onclick="onPlayClick('${escapeJs(r.test_stream_url || '')}', '${escapeJs(r.test_channel_name || 'BBC News')}')" 
                 download 
                 class="p-1.5 rounded-lg bg-orange-600/20 hover:bg-orange-600/40 text-orange-400 hover:text-orange-300 border border-orange-500/30 transition flex items-center justify-center w-7 h-7" 
                 title="Play ${escapeHtml(r.test_channel_name || 'BBC News')} in VLC">
                <i class="fa-solid fa-play text-xs"></i>
              </a>
            ` : ''}
            ${r.is_working ? `
              <button onclick="openStreamPlayerModal(${idx})" class="p-1.5 rounded-lg bg-cyan-600/20 hover:bg-cyan-600/40 text-cyan-400 hover:text-cyan-300 border border-cyan-500/30 transition flex items-center justify-center w-7 h-7" title="Preview Stream & Player Details">
                <i class="fa-solid fa-tv text-xs"></i>
              </button>
            ` : ''}
            <button onclick="copyM3U('${escapeJs(r.m3u_url)}', this)" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition flex items-center justify-center w-7 h-7" title="Copy M3U URL">
              <i class="fa-solid fa-link text-xs"></i>
            </button>
            <button onclick="copyXtream('${escapeJs(r.host)}', '${escapeJs(r.username)}', '${escapeJs(r.password)}', this)" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition flex items-center justify-center w-7 h-7" title="Copy Xtream Credentials">
              <i class="fa-solid fa-key text-xs"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// Universal Clipboard function (supports HTTPS, HTTP, and LAN IPs)
window.copyToClipboard = function(text, msg = 'Copied to clipboard!') {
  if (!text) return;

  // Try modern navigator.clipboard if in secure context
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(msg);
    }).catch(() => {
      fallbackCopyText(text, msg);
    });
    return;
  }

  // Universal HTTP LAN fallback using temporary textarea
  fallbackCopyText(text, msg);
};

function fallbackCopyText(text, msg) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.setAttribute('readonly', '');
  textArea.style.position = 'absolute';
  textArea.style.left = '-9999px';
  textArea.style.top = (window.pageYOffset || document.documentElement.scrollTop) + 'px';
  document.body.appendChild(textArea);
  textArea.select();
  textArea.setSelectionRange(0, textArea.value.length);

  try {
    const successful = document.execCommand('copy');
    if (successful) {
      showToast(msg);
    } else {
      prompt('Copy to clipboard manually: Ctrl+C, Enter', text);
    }
  } catch (err) {
    prompt('Copy to clipboard manually: Ctrl+C, Enter', text);
  } finally {
    document.body.removeChild(textArea);
  }
}

// Copy M3U with icon animation
window.copyM3U = function(url, btnElement) {
  window.copyToClipboard(url, 'M3U link copied to clipboard!');
  if (btnElement) {
    const icon = btnElement.querySelector('i');
    if (icon) {
      const original = icon.className;
      icon.className = 'fa-solid fa-check text-emerald-400 text-xs';
      setTimeout(() => { icon.className = original; }, 1500);
    }
  }
};

// Copy Xtream format with icon animation
window.copyXtream = function(host, user, pass, btnElement) {
  const text = `Host: ${host}\nUser: ${user}\nPass: ${pass}`;
  window.copyToClipboard(text, 'Xtream credentials copied!');
  if (btnElement) {
    const icon = btnElement.querySelector('i');
    if (icon) {
      const original = icon.className;
      icon.className = 'fa-solid fa-check text-emerald-400 text-xs';
      setTimeout(() => { icon.className = original; }, 1500);
    }
  }
};

btnCopyWorking.addEventListener('click', () => {
  const working = allResults.filter(r => r.is_working).map(r => r.m3u_url);
  if (working.length === 0) {
    showToast('No active working servers to copy.', 'error');
    return;
  }
  const text = working.join('\n');
  window.copyToClipboard(text, `Copied ${working.length} active M3U URLs!`);
});

btnExportCsv.addEventListener('click', async () => {
  if (allResults.length === 0) {
    showToast('No results to export.', 'error');
    return;
  }
  try {
    const res = await fetch('/api/export/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(allResults)
    });
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `iptv_audit_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('CSV downloaded successfully!');
  } catch (err) {
    showToast('Failed to export CSV', 'error');
  }
});

function showToast(message, type = 'success') {
  const toast = document.getElementById('toast');
  const toastMessage = document.getElementById('toast-message');
  const toastIcon = document.getElementById('toast-icon');

  toastMessage.textContent = message;
  if (type === 'error') {
    toastIcon.className = 'fa-solid fa-circle-exclamation text-red-400';
  } else {
    toastIcon.className = 'fa-solid fa-circle-check text-emerald-400';
  }

  toast.classList.remove('translate-y-20', 'opacity-0');
  toast.classList.add('translate-y-0', 'opacity-100');

  setTimeout(() => {
    toast.classList.add('translate-y-20', 'opacity-0');
    toast.classList.remove('translate-y-0', 'opacity-100');
  }, 2500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeJs(str) {
  if (!str) return '';
  return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ==========================================
// Video Player & VLC Hub Modal Lifecycle
// ==========================================
let activeMpegtsPlayer = null;
let currentPlayingServer = null;
let videoWatchdogTimer = null;

// 1-Click VLC Play button handler
window.onPlayClick = function(streamUrl, channelName) {
  if (streamUrl) {
    window.copyToClipboard(streamUrl, `Opening ${channelName} in VLC! (Stream URL copied for Cmd+N)`);
  }
};

window.openStreamPlayerModal = function(idx) {
  const r = currentFilteredList[idx];
  if (!r) return;
  openStreamPlayerModalByObj(r);
};

window.openStreamPlayerModalByObj = function(r) {
  currentPlayingServer = r;
  const modal = document.getElementById('video-modal');
  if (!modal) return;

  const chName = r.test_channel_name || 'Live Channel';
  document.getElementById('video-modal-title').textContent = chName;
  document.getElementById('video-modal-subtitle').textContent = r.host || '';
  document.getElementById('video-stream-url-field').value = r.test_stream_url || '';

  // Setup direct .m3u download button
  const directM3u = document.getElementById('video-btn-m3u-direct');
  if (r.test_stream_url) {
    directM3u.href = `/api/play/m3u?url=${encodeURIComponent(r.test_stream_url)}&title=${encodeURIComponent(chName)}`;
    directM3u.classList.remove('opacity-50', 'pointer-events-none');
  } else {
    directM3u.classList.add('opacity-50', 'pointer-events-none');
  }

  // Setup CLI command button
  const btnCli = document.getElementById('video-btn-copy-cli');
  if (btnCli) {
    btnCli.onclick = () => {
      const cmd = `open -a VLC "${r.test_stream_url}"`;
      window.copyToClipboard(cmd, 'VLC launch command copied for Mac Terminal!');
    };
  }

  modal.classList.remove('hidden');

  // Start direct client playback with watchdog fallback to VLC
  initLiveVideoPlayer(r.test_stream_url, chName);
};

function initLiveVideoPlayer(streamUrl, chName = 'Live Channel') {
  destroyLiveVideoPlayer();

  const videoElement = document.getElementById('live-video');
  const overlay = document.getElementById('video-loading-overlay');
  const overlayText = document.getElementById('video-loading-text');

  if (!streamUrl) {
    if (overlay) overlay.classList.remove('hidden');
    if (overlayText) overlayText.textContent = 'No playable stream URL available.';
    return;
  }

  // Reset overlay to loading
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.innerHTML = `
      <i class="fa-solid fa-circle-notch fa-spin text-orange-500 text-3xl"></i>
      <p id="video-loading-text" class="text-xs text-slate-300 font-medium">Checking live video stream...</p>
    `;
  }

  const directStreamUrl = streamUrl;

  function showVlcFallback() {
    if (!overlay) return;
    overlay.classList.remove('hidden');
    overlay.innerHTML = `
      <div class="text-center p-4 space-y-2.5 max-w-sm">
        <div class="w-12 h-12 rounded-xl bg-orange-500/20 text-orange-400 mx-auto flex items-center justify-center text-xl">
          <i class="fa-solid fa-traffic-cone"></i>
        </div>
        <div>
          <h4 class="text-sm font-semibold text-white">Play in VLC Media Player</h4>
          <p class="text-xs text-slate-400 mt-1">
            Browser lacks native MPEG-TS decoders. Open directly on your Mac using VLC:
          </p>
        </div>
        <div class="pt-1 flex items-center justify-center gap-2">
          <a href="/api/play/m3u?url=${encodeURIComponent(directStreamUrl)}&title=${encodeURIComponent(chName)}" 
             download 
             onclick="window.copyToClipboard('${escapeJs(directStreamUrl)}')"
             class="px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white font-semibold text-xs flex items-center gap-2 transition shadow-md shadow-orange-600/30">
            <i class="fa-solid fa-download text-xs"></i> Download .m3u for VLC
          </a>
        </div>
      </div>
    `;
  }

  // 3-second watchdog timer: if the browser can't decode the raw TS stream, show the VLC action
  videoWatchdogTimer = setTimeout(() => {
    if (videoElement.paused || videoElement.readyState < 2) {
      showVlcFallback();
    }
  }, 3000);

  videoElement.onplaying = () => {
    if (videoWatchdogTimer) clearTimeout(videoWatchdogTimer);
    if (overlay) overlay.classList.add('hidden');
  };

  // Try direct mpegts.js on client side
  if (window.mpegts && window.mpegts.getFeatureList().mseLivePlayback) {
    try {
      activeMpegtsPlayer = mpegts.createPlayer({
        type: 'mse',
        isLive: true,
        url: directStreamUrl,
      }, {
        enableStashBuffer: false,
        liveBufferLatencyChasing: true,
      });

      activeMpegtsPlayer.attachMediaElement(videoElement);
      activeMpegtsPlayer.load();

      const playPromise = activeMpegtsPlayer.play();
      if (playPromise !== undefined) {
        playPromise.then(() => {
          if (videoWatchdogTimer) clearTimeout(videoWatchdogTimer);
          if (overlay) overlay.classList.add('hidden');
        }).catch(() => {
          videoElement.muted = true;
          activeMpegtsPlayer.play().then(() => {
            if (videoWatchdogTimer) clearTimeout(videoWatchdogTimer);
            if (overlay) overlay.classList.add('hidden');
          }).catch(() => {
            showVlcFallback();
          });
        });
      }

      activeMpegtsPlayer.on(mpegts.Events.ERROR, () => {
        if (videoWatchdogTimer) clearTimeout(videoWatchdogTimer);
        showVlcFallback();
      });

    } catch (e) {
      videoElement.src = directStreamUrl;
      videoElement.play().catch(() => showVlcFallback());
    }
  } else {
    // Safari direct playback
    videoElement.src = directStreamUrl;
    videoElement.play().catch(() => showVlcFallback());
  }
}

function destroyLiveVideoPlayer() {
  if (videoWatchdogTimer) {
    clearTimeout(videoWatchdogTimer);
    videoWatchdogTimer = null;
  }
  const videoElement = document.getElementById('live-video');
  if (activeMpegtsPlayer) {
    try {
      activeMpegtsPlayer.pause();
      activeMpegtsPlayer.unload();
      activeMpegtsPlayer.detachMediaElement();
      activeMpegtsPlayer.destroy();
    } catch (e) {}
    activeMpegtsPlayer = null;
  }
  if (videoElement) {
    videoElement.pause();
    videoElement.removeAttribute('src');
    videoElement.load();
  }
}

window.closeVideoModal = function() {
  destroyLiveVideoPlayer();
  const modal = document.getElementById('video-modal');
  if (modal) modal.classList.add('hidden');
};

// ==========================================
// UHF / Chillio / IPTVX Player Modal
// ==========================================
window.openPlayerModalByIndex = function(idx) {
  const r = currentFilteredList[idx];
  if (!r) return;
  openPlayerModal(r);
};

window.openPlayerModal = function(r) {
  const modal = document.getElementById('player-modal');
  if (!modal) return;

  document.getElementById('modal-host-subtitle').textContent = r.host || '';
  document.getElementById('modal-field-host').value = r.host || '';
  document.getElementById('modal-field-user').value = r.username || '';
  document.getElementById('modal-field-pass').value = r.password || '';
  document.getElementById('modal-field-m3u').value = r.m3u_url || '';

  const testBadge = document.getElementById('modal-test-channel-badge');
  const chName = r.test_channel_name || 'BBC News';
  testBadge.textContent = chName;

  const btnWebPlayer = document.getElementById('modal-btn-web-player');
  const btnVlcM3u = document.getElementById('modal-btn-vlc-m3u');

  if (r.test_stream_url) {
    btnWebPlayer.disabled = false;
    btnWebPlayer.onclick = () => {
      closePlayerModal();
      openStreamPlayerModalByObj(r);
    };

    btnVlcM3u.href = `/api/play/m3u?url=${encodeURIComponent(r.test_stream_url)}&title=${encodeURIComponent(chName)}`;
    btnVlcM3u.classList.remove('opacity-50', 'pointer-events-none');
  } else {
    btnWebPlayer.disabled = true;
    btnWebPlayer.onclick = null;
    btnVlcM3u.removeAttribute('href');
    btnVlcM3u.classList.add('opacity-50', 'pointer-events-none');
  }

  const btnCopyAll = document.getElementById('modal-btn-copy-all');
  btnCopyAll.onclick = () => {
    const text = `Host: ${r.host}\nUsername: ${r.username}\nPassword: ${r.password}\nM3U: ${r.m3u_url}`;
    window.copyToClipboard(text, 'Copied all credentials for UHF/Chillio/IPTVX!');
  };

  modal.classList.remove('hidden');
};

window.closePlayerModal = function() {
  const modal = document.getElementById('player-modal');
  if (modal) modal.classList.add('hidden');
};

window.copyFieldValue = function(inputId, btnElement) {
  const el = document.getElementById(inputId);
  if (!el || !el.value) return;
  window.copyToClipboard(el.value, 'Copied to clipboard!');
  if (btnElement) {
    const icon = btnElement.querySelector('i');
    if (icon) {
      const orig = icon.className;
      icon.className = 'fa-solid fa-check text-emerald-400 text-xs';
      setTimeout(() => { icon.className = orig; }, 1200);
    }
  }
};

// Global escape key and backdrop click handlers
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closePlayerModal();
    closeVideoModal();
  }
});

document.getElementById('player-modal')?.addEventListener('click', (e) => {
  if (e.target.id === 'player-modal') closePlayerModal();
});

document.getElementById('video-modal')?.addEventListener('click', (e) => {
  if (e.target.id === 'video-modal') closeVideoModal();
});
