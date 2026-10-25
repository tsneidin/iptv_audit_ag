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

// DOM Elements
const inputStrings = document.getElementById('input-strings');
const btnSample = document.getElementById('btn-sample');
const btnClear = document.getElementById('btn-clear');
const btnAudit = document.getElementById('btn-audit');
const btnIcon = document.getElementById('btn-icon');
const btnText = document.getElementById('btn-text');
const optProbe = document.getElementById('opt-probe-stream');
const optConcurrency = document.getElementById('opt-concurrency');

const progressContainer = document.getElementById('progress-container');
const progressStatus = document.getElementById('progress-status');
const progressCount = document.getElementById('progress-count');
const progressBar = document.getElementById('progress-bar');

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

// Audit trigger
btnAudit.addEventListener('click', async () => {
  const text = inputStrings.value.trim();
  if (!text) {
    showToast('Please paste at least one string or URL first.', 'error');
    return;
  }
  if (isAuditing) return;

  startAudit(text);
});

async function startAudit(text) {
  isAuditing = true;
  setAuditButtonState(true);
  allResults = [];
  resultsTbody.innerHTML = '';
  
  emptyState.classList.add('hidden');
  progressContainer.classList.remove('hidden');
  statsSection.classList.remove('hidden');
  toolbarSection.classList.remove('hidden');
  resultsCard.classList.remove('hidden');

  updateStats();
  progressBar.style.width = '5%';
  progressStatus.textContent = 'Contacting server...';
  progressCount.textContent = '0%';

  try {
    const response = await fetch('/api/audit/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_text: text,
        probe_stream: optProbe.checked,
        concurrency: parseInt(optConcurrency.value) || 8
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
      buffer = lines.pop(); // keep last incomplete chunk

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
    showToast(`Audit failed: ${err.message}`, 'error');
    progressStatus.textContent = `Error: ${err.message}`;
  } finally {
    isAuditing = false;
    setAuditButtonState(false);
  }
}

function handleSSEEvent(event) {
  if (event.type === 'status' || event.type === 'warning') {
    progressStatus.textContent = event.message;
  } else if (event.type === 'extracted_urls') {
    progressStatus.textContent = event.message;
    progressBar.style.width = '15%';
  } else if (event.type === 'parsed_servers') {
    progressStatus.textContent = event.message;
    progressBar.style.width = '25%';
  } else if (event.type === 'server_result') {
    const data = event.data;
    allResults.push(data);
    updateStats();

    if (data.total && data.completed) {
      const pct = Math.round((data.completed / data.total) * 100);
      progressBar.style.width = `${Math.max(25, pct)}%`;
      progressCount.textContent = `${pct}%`;
      progressStatus.textContent = `Audited ${data.completed} of ${data.total} servers...`;
    }

    renderTable();
  } else if (event.type === 'audit_complete') {
    progressBar.style.width = '100%';
    progressCount.textContent = '100%';
    progressStatus.textContent = `Finished! ${allResults.length} servers audited.`;
    showToast('Audit complete!', 'success');
  } else if (event.type === 'error') {
    progressStatus.textContent = event.message;
    showToast(event.message, 'error');
  }
}

function setAuditButtonState(active) {
  if (active) {
    btnAudit.disabled = true;
    btnIcon.className = 'fa-solid fa-spinner fa-spin';
    btnText.textContent = 'Auditing...';
    globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-orange-400 animate-ping"></span> Auditing...`;
  } else {
    btnAudit.disabled = false;
    btnIcon.className = 'fa-solid fa-play';
    btnText.textContent = 'Audit Servers';
    globalBadge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400"></span> Ready`;
  }
}

function updateStats() {
  statTotal.textContent = allResults.length;
  statWorking.textContent = allResults.filter(r => r.is_working).length;
  statFailed.textContent = allResults.filter(r => !r.is_working).length;
  statAdult.textContent = allResults.filter(r => r.has_adult).length;
}

function renderTable() {
  let filtered = allResults.filter(r => {
    // Search query
    if (searchQuery) {
      const matchHost = (r.host || '').toLowerCase().includes(searchQuery);
      const matchUser = (r.username || '').toLowerCase().includes(searchQuery);
      if (!matchHost && !matchUser) return false;
    }
    // Filter tags
    if (currentFilter === 'active') return r.is_working;
    if (currentFilter === 'adult') return r.has_adult;
    if (currentFilter === 'stream_ok') return (r.stream_probe || '').toLowerCase().includes('playable');
    return true;
  });

  if (filtered.length === 0) {
    resultsTbody.innerHTML = `
      <tr>
        <td colspan="11" class="text-center py-8 text-slate-500">
          No servers match the selected criteria.
        </td>
      </tr>
    `;
    return;
  }

  resultsTbody.innerHTML = filtered.map(r => {
    // Status Badge
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

    // Stream Probe Badge
    let streamClass = 'text-slate-400';
    if (r.stream_probe_badge === 'green') streamClass = 'text-emerald-400 font-medium';
    else if (r.stream_probe_badge === 'yellow') streamClass = 'text-amber-400';
    else if (r.stream_probe_badge === 'red') streamClass = 'text-red-400';

    // Adult Badge
    const adultBadge = r.has_adult 
      ? `<span class="px-2 py-0.5 rounded-full bg-pink-500/10 text-pink-400 border border-pink-500/20 font-medium" title="${escapeHtml(r.adult_details)}"><i class="fa-solid fa-venus-mars mr-1"></i>Yes</span>`
      : `<span class="text-slate-500">None</span>`;

    // Latency
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
          ${escapeHtml(r.stream_probe || 'N/A')}
        </td>

        <td class="py-3 px-4 text-right whitespace-nowrap">
          <div class="inline-flex items-center gap-1.5">
            <button onclick="copyToClipboard('${escapeJs(r.m3u_url)}', 'M3U link copied!')" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition" title="Copy M3U URL">
              <i class="fa-solid fa-link text-xs"></i>
            </button>
            <button onclick="copyXtream('${escapeJs(r.host)}', '${escapeJs(r.username)}', '${escapeJs(r.password)}')" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition" title="Copy Xtream Credentials">
              <i class="fa-solid fa-key text-xs"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// Copy single M3U or text
window.copyToClipboard = function(text, msg = 'Copied to clipboard!') {
  navigator.clipboard.writeText(text).then(() => {
    showToast(msg);
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
};

// Copy Xtream format
window.copyXtream = function(host, user, pass) {
  const jsonStr = `Server: ${host}\nUsername: ${user}\nPassword: ${pass}`;
  window.copyToClipboard(jsonStr, 'Xtream credentials copied!');
};

// Copy all working M3Us
btnCopyWorking.addEventListener('click', () => {
  const working = allResults.filter(r => r.is_working).map(r => r.m3u_url);
  if (working.length === 0) {
    showToast('No active working servers to copy.', 'error');
    return;
  }
  const text = working.join('\n');
  navigator.clipboard.writeText(text).then(() => {
    showToast(`Copied ${working.length} active M3U URLs!`);
  });
});

// Export CSV
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

// Toast system
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
  }, 3000);
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
