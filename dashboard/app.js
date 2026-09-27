/* ==========================================================================
   CelerLite Console — Salesforce Lightning Platform Controller
   Real-time SLDS App, Tab Switching, Sales Path, Einstein AI, Drawer & Modal
   ========================================================================== */

'use strict';

const API = location.host ? '' : 'http://localhost:8000';
let ws = null;
let currentTab = 'executions';
let currentStatusFilter = '';
let currentQueueFilter = '';
let searchQuery = '';
let currentDrawerTask = null;
let currentDrawerTaskId = null;

// Telemetry & State Cache
let executionsList = [];
let throughputChart = null;
let statusDonutChart = null;
let throughputHistory = [];
let autoRefreshTimer = null;

// ==========================================================================
// INITIALIZATION
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
  initCharts();
  loadAllData();
  setupKeyboardShortcuts();

  // Auto-refresh stats every 4 seconds
  setInterval(loadStats, 4000);
});

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // ESC closes drawer or modal
    if (e.key === 'Escape') {
      closeTaskDrawer();
      closeStartTaskModal();
    }
    // Command+K or '/' focuses search
    if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && 
        document.activeElement.tagName !== 'INPUT' && 
        document.activeElement.tagName !== 'TEXTAREA') {
      e.preventDefault();
      const search = document.getElementById('globalSearchInput');
      if (search) search.focus();
    }
  });
}

// ==========================================================================
// WEBSOCKET TELEMETRY
// ==========================================================================

function initWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = location.host || 'localhost:8000';
  const url = `${proto}://${host}/api/v1/ws/events`;

  try {
    ws = new WebSocket(url);

    ws.onopen = () => {
      setConnectionStatus(true);
      console.log('[SLDS WS] Connected to CelerLite event bus');
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event && payload.event !== 'connected') {
          handleIncomingEvent(payload);
        }
      } catch (err) {
        console.warn('[SLDS WS] Event parse error', err);
      }
    };

    ws.onclose = () => {
      setConnectionStatus(false);
      setTimeout(initWebSocket, 3000);
    };

    ws.onerror = () => {
      if (ws) ws.close();
    };
  } catch (err) {
    setConnectionStatus(false);
    setTimeout(initWebSocket, 3000);
  }
}

function setConnectionStatus(connected) {
  const dot = document.getElementById('wsPulseDot');
  const text = document.getElementById('wsStatusText');

  if (connected) {
    if (dot) dot.style.backgroundColor = '#31e87d';
    if (text) text.textContent = 'Connected (Live)';
  } else {
    if (dot) dot.style.backgroundColor = '#ea001e';
    if (text) text.textContent = 'Reconnecting...';
  }
}

function handleIncomingEvent(event) {
  const existingIdx = executionsList.findIndex(t => t.id === event.task_id);
  const nowIso = new Date().toISOString();

  if (existingIdx !== -1) {
    const task = executionsList[existingIdx];
    if (event.event === 'task_started') {
      task.status = 'RUNNING';
      task.worker_id = event.worker_id;
      task.started_at = nowIso;
      updateSalesPath('RUNNING');
    } else if (event.event === 'task_completed') {
      task.status = 'SUCCESS';
      task.completed_at = nowIso;
      task.duration_ms = event.duration_ms;
      updateSalesPath('SUCCESS');
    } else if (event.event === 'task_failed') {
      task.status = 'FAILED';
      task.completed_at = nowIso;
      task.error_message = event.error;
      updateSalesPath('FAILED');
    }
  } else if (event.task_id) {
    const status = event.event === 'task_started' ? 'RUNNING' : (event.event === 'task_completed' ? 'SUCCESS' : 'PENDING');
    executionsList.unshift({
      id: event.task_id,
      task_name: event.task_name || 'celerlite.task',
      status: status,
      queue: event.queue || 'default',
      priority: event.priority ?? 1,
      worker_id: event.worker_id || null,
      created_at: nowIso,
      started_at: event.event === 'task_started' ? nowIso : null,
      completed_at: event.event === 'task_completed' ? nowIso : null,
      duration_ms: event.duration_ms || null,
    });
    updateSalesPath(status);
  }

  if (currentTab === 'executions') {
    renderExecutionsTable();
  }

  loadStats();

  if (currentDrawerTaskId === event.task_id) {
    openTaskDrawer(event.task_id, false);
  }
}

// ==========================================================================
// DATA LOADING & RENDERING
// ==========================================================================

async function loadAllData() {
  await Promise.all([
    loadExecutions(),
    loadStats(),
    loadQueues(),
    loadWorkers(),
    loadDLQ(),
    loadMetrics(),
  ]);
}

async function loadExecutions() {
  try {
    let url = `${API}/api/v1/tasks?limit=100`;
    if (currentStatusFilter) url += `&status=${encodeURIComponent(currentStatusFilter)}`;
    if (currentQueueFilter) url += `&queue=${encodeURIComponent(currentQueueFilter)}`;

    const res = await fetch(url);
    if (res.ok) {
      executionsList = await res.json();
      renderExecutionsTable();
    }
  } catch (err) {
    console.error('Failed to load executions', err);
  }
}

function renderExecutionsTable() {
  const tbody = document.getElementById('executionsTableBody');
  const emptyState = document.getElementById('executionsEmptyState');
  if (!tbody) return;

  let filtered = executionsList;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = filtered.filter(t =>
      (t.id && t.id.toLowerCase().includes(q)) ||
      (t.task_name && t.task_name.toLowerCase().includes(q)) ||
      (t.worker_id && t.worker_id.toLowerCase().includes(q)) ||
      (t.queue && t.queue.toLowerCase().includes(q))
    );
  }

  // Update record count in header meta
  const recordCountMeta = document.getElementById('recordCountMeta');
  if (recordCountMeta) recordCountMeta.textContent = `${filtered.length} items`;

  const paginationSummary = document.getElementById('paginationSummary');
  if (paginationSummary) paginationSummary.textContent = `Showing 1-${filtered.length} of ${filtered.length} records`;

  if (filtered.length === 0) {
    tbody.innerHTML = '';
    if (emptyState) emptyState.style.display = 'flex';
    return;
  }

  if (emptyState) emptyState.style.display = 'none';

  tbody.innerHTML = filtered.map(t => {
    const pill = getStatusPill(t.status);
    const priorityLabel = getPriorityLabel(t.priority);
    const duration = formatDuration(t.duration_ms, t.started_at, t.completed_at);
    const timeFormatted = formatTimeAgo(t.created_at || t.started_at);

    return `
      <tr onclick="handleRowClick('${escapeHtml(t.id)}')">
        <td onclick="event.stopPropagation()"><input type="checkbox" /></td>
        <td><span class="slds-status-pill ${pill.css}">${pill.text}</span></td>
        <td class="task-name-cell">${escapeHtml(t.task_name)}</td>
        <td><a href="javascript:void(0)" class="task-id-code" onclick="event.stopPropagation(); handleRowClick('${escapeHtml(t.id)}')">${escapeHtml(t.id.substring(0, 13))}…</a></td>
        <td><span class="queue-tag">${escapeHtml(t.queue || 'default')}</span></td>
        <td><span class="priority-tag ${priorityLabel.css}">${priorityLabel.text}</span></td>
        <td><span style="font-family: var(--font-mono); font-size: 11.5px; color: var(--slds-text-muted);">${escapeHtml(t.worker_id || '—')}</span></td>
        <td style="text-align: right;"><span class="duration-val">${duration}</span></td>
        <td style="text-align: right;"><span class="time-val">${timeFormatted}</span></td>
      </tr>
    `;
  }).join('');
}

function handleRowClick(taskId) {
  openTaskDrawer(taskId);
  const task = executionsList.find(t => t.id === taskId);
  if (task) {
    updateSalesPath(task.status);
  }
}

// ==========================================================================
// SALESFORCE SALES PATH (CHEVRON TRACKER)
// ==========================================================================

function updateSalesPath(status) {
  const stepScheduled = document.getElementById('pathStepScheduled');
  const stepQueued = document.getElementById('pathStepQueued');
  const stepRunning = document.getElementById('pathStepRunning');
  const stepSuccess = document.getElementById('pathStepSuccess');

  if (!stepScheduled) return;

  // Reset classes
  [stepScheduled, stepQueued, stepRunning, stepSuccess].forEach(s => {
    s.className = 'slds-path-step';
  });

  if (status === 'PENDING') {
    stepScheduled.className = 'slds-path-step step-complete';
    stepQueued.className = 'slds-path-step step-active';
    stepRunning.className = 'slds-path-step step-upcoming';
    stepSuccess.className = 'slds-path-step step-upcoming';
  } else if (status === 'RUNNING') {
    stepScheduled.className = 'slds-path-step step-complete';
    stepQueued.className = 'slds-path-step step-complete';
    stepRunning.className = 'slds-path-step step-active';
    stepSuccess.className = 'slds-path-step step-upcoming';
  } else if (status === 'SUCCESS') {
    stepScheduled.className = 'slds-path-step step-complete';
    stepQueued.className = 'slds-path-step step-complete';
    stepRunning.className = 'slds-path-step step-complete';
    stepSuccess.className = 'slds-path-step step-complete';
  } else if (status === 'FAILED' || status === 'DEAD_LETTERED') {
    stepScheduled.className = 'slds-path-step step-complete';
    stepQueued.className = 'slds-path-step step-complete';
    stepRunning.className = 'slds-path-step step-failed';
    stepSuccess.className = 'slds-path-step step-failed';
  } else {
    stepScheduled.className = 'slds-path-step step-complete';
    stepQueued.className = 'slds-path-step step-complete';
    stepRunning.className = 'slds-path-step step-active';
    stepSuccess.className = 'slds-path-step step-upcoming';
  }
}

// ==========================================================================
// STATS & EINSTEIN AI COPILOT
// ==========================================================================

async function loadStats() {
  try {
    const res = await fetch(`${API}/api/v1/tasks/stats`);
    if (res.ok) {
      const stats = await res.json();
      const completed = stats.SUCCESS || 0;
      const running = stats.RUNNING || 0;
      const failed = stats.FAILED || 0;
      const dlq = stats.DEAD_LETTERED || 0;
      const pending = stats.PENDING || 0;
      const total = completed + running + failed + dlq + pending;
      const tps = (stats.throughput_per_sec || 0.0);

      // Dashboards & Reports Tab KPIs
      const dbKpiTotal = document.getElementById('dbKpiTotal');
      if (dbKpiTotal) dbKpiTotal.textContent = total;

      const rate = total > 0 ? Math.round((completed / (completed + failed + dlq || 1)) * 100) : 100;
      const dbKpiRate = document.getElementById('dbKpiRate');
      if (dbKpiRate) dbKpiRate.textContent = `${rate}%`;

      const dbKpiTps = document.getElementById('dbKpiTps');
      if (dbKpiTps) dbKpiTps.textContent = tps.toFixed(1);

      const dbKpiLatency = document.getElementById('dbKpiLatency');
      if (dbKpiLatency && stats.avg_latency_ms !== undefined) {
        dbKpiLatency.textContent = `${stats.avg_latency_ms}ms`;
      }

      // Einstein Task Intelligence Widget
      const healthScore = Math.max(88, 100 - (failed * 3 + dlq * 5));
      const copilotHealthScore = document.getElementById('copilotHealthScore');
      if (copilotHealthScore) copilotHealthScore.textContent = `${healthScore.toFixed(1)}%`;

      const copilotHealthBar = document.getElementById('copilotHealthBar');
      if (copilotHealthBar) copilotHealthBar.style.width = `${healthScore}%`;

      const copilotTps = document.getElementById('copilotTps');
      if (copilotTps) copilotTps.textContent = `${tps.toFixed(1)} tps`;

      // DLQ Tab Badge
      const tabCountDLQ = document.getElementById('tabCountDLQ');
      if (tabCountDLQ) tabCountDLQ.textContent = dlq;

      // Update Charts
      updateDonutChart({ SUCCESS: completed, RUNNING: running, FAILED: failed, DEAD_LETTERED: dlq });
      recordThroughputSample(tps);
    }
  } catch (err) {
    console.warn('Stats poll error', err);
  }
}

async function loadQueues() {
  try {
    const res = await fetch(`${API}/api/v1/metrics`);
    if (res.ok) {
      const data = await res.json();
      const queues = data.queues || { default: { critical: 0, high: 0, normal: 0, low: 0 } };
      const container = document.getElementById('queuesContainer');
      if (!container) return;

      container.innerHTML = Object.entries(queues).map(([name, prios]) => {
        const total = Object.values(prios).reduce((a, b) => a + b, 0);
        return `
          <div class="queue-card">
            <div class="queue-card-top">
              <span class="queue-card-name">${escapeHtml(name)}</span>
              <span class="slds-status-pill status-success">ACTIVE</span>
            </div>
            <div style="font-size: 11.5px; color: var(--slds-text-muted);">Strict Priority Sub-queues:</div>
            <div class="queue-priority-breakdown">
              <div class="qp-item">
                <span class="qp-label text-rose">CRITICAL</span>
                <span class="qp-val">${prios.critical || 0}</span>
              </div>
              <div class="qp-item">
                <span class="qp-label" style="color: #b86200;">HIGH</span>
                <span class="qp-val">${prios.high || 0}</span>
              </div>
              <div class="qp-item">
                <span class="qp-label">NORMAL</span>
                <span class="qp-val">${prios.normal || 0}</span>
              </div>
              <div class="qp-item">
                <span class="qp-label">LOW</span>
                <span class="qp-val">${prios.low || 0}</span>
              </div>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--slds-text-muted); border-top: 1px solid var(--slds-border); padding-top: 10px;">
              <span>Total Backlog: <b style="color: var(--slds-text-primary); font-family: var(--font-mono);">${total}</b></span>
              <button class="slds-btn slds-btn-neutral slds-btn-xs" onclick="filterByQueue('${escapeHtml(name)}')">View Records →</button>
            </div>
          </div>
        `;
      }).join('');
    }
  } catch (err) {
    console.warn('Queue poll error', err);
  }
}

async function loadWorkers() {
  try {
    const res = await fetch(`${API}/api/v1/workers`);
    if (res.ok) {
      const workers = await res.json();
      const tbody = document.getElementById('workersTableBody');
      if (!tbody) return;

      if (workers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--slds-text-muted); padding: 32px;">No active worker processes detected in fleet.</td></tr>`;
        return;
      }

      tbody.innerHTML = workers.map(w => `
        <tr>
          <td><span class="slds-status-pill ${w.status === 'ONLINE' ? 'status-success' : 'status-failed'}">${w.status}</span></td>
          <td><code style="font-family: var(--font-mono); color: #0176d3; font-weight: 600;">${escapeHtml(w.id)}</code></td>
          <td>${escapeHtml(w.hostname || 'localhost')}</td>
          <td><span style="font-family: var(--font-mono);">${w.pid || 1}</span></td>
          <td style="text-align: right; font-family: var(--font-mono); font-weight: 600;">${w.tasks_processed || 0}</td>
          <td style="text-align: right; font-family: var(--font-mono); color: ${w.tasks_failed > 0 ? 'var(--slds-error)' : 'inherit'};">${w.tasks_failed || 0}</td>
          <td style="text-align: right; font-size: 11.5px; color: var(--slds-text-muted);">${formatTimeAgo(w.last_heartbeat)}</td>
        </tr>
      `).join('');
    }
  } catch (err) {
    console.warn('Worker poll error', err);
  }
}

async function loadDLQ() {
  try {
    const res = await fetch(`${API}/api/v1/dlq?limit=50`);
    if (res.ok) {
      const entries = await res.json();
      const tbody = document.getElementById('dlqTableBody');
      const emptyState = document.getElementById('dlqEmptyState');
      const tabBadge = document.getElementById('tabCountDLQ');

      if (tabBadge) tabBadge.textContent = entries.length;
      if (!tbody) return;

      if (entries.length === 0) {
        tbody.innerHTML = '';
        if (emptyState) emptyState.style.display = 'flex';
        return;
      }

      if (emptyState) emptyState.style.display = 'none';

      tbody.innerHTML = entries.map(e => `
        <tr>
          <td class="task-name-cell">${escapeHtml(e.task_name)}</td>
          <td><span style="color: var(--slds-error); font-size: 12px; font-weight: 500;">${escapeHtml(e.error_message || 'Permanent failure')}</span></td>
          <td style="text-align: center; font-family: var(--font-mono);">${e.retry_count}</td>
          <td><span class="queue-tag">${escapeHtml(e.original_queue)}</span></td>
          <td><span class="time-val">${formatTimeAgo(e.dead_lettered_at)}</span></td>
          <td style="text-align: right;">
            <button class="slds-btn slds-btn-neutral slds-btn-xs" onclick="replayDLQEntry('${escapeHtml(e.id)}')">↺ Replay</button>
            <button class="slds-btn slds-btn-xs" style="color: var(--slds-error);" onclick="deleteDLQEntry('${escapeHtml(e.id)}')">✕</button>
          </td>
        </tr>
      `).join('');
    }
  } catch (err) {
    console.warn('DLQ poll error', err);
  }
}

async function loadMetrics() {
  try {
    const res = await fetch(`${API}/api/v1/metrics`);
    if (res.ok) {
      const data = await res.json();
      if (data.redis) {
        const mode = data.redis.mode || (data.redis.connected ? 'Redis Distributed Broker' : 'InMemoryBroker (Standalone)');
        const brokerEl = document.getElementById('cfgBroker');
        if (brokerEl) brokerEl.textContent = mode;
      }
    }
  } catch (err) {
    console.warn('Metrics poll error', err);
  }
}

// ==========================================================================
// SALESFORCE NAVIGATION (TAB SWITCHING)
// ==========================================================================

function switchTab(tabName) {
  currentTab = tabName;

  // Update nav tabs
  document.querySelectorAll('.slds-nav-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });

  // Update panels
  document.querySelectorAll('.slds-tab-panel').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`tab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
  if (target) target.classList.add('active');

  // Trigger relevant loader
  if (tabName === 'executions') loadExecutions();
  if (tabName === 'queues') loadQueues();
  if (tabName === 'workers') loadWorkers();
  if (tabName === 'dlq') loadDLQ();
  if (tabName === 'dashboards') loadStats();
  if (tabName === 'settings') loadMetrics();
}

function setStatusFilter(status) {
  currentStatusFilter = status;
  loadExecutions();
}

function setQueueFilter(queue) {
  currentQueueFilter = queue;
  loadExecutions();
}

function filterByQueue(queueName) {
  switchTab('executions');
  const sel = document.getElementById('queueFilterSelect');
  if (sel) sel.value = queueName;
  currentQueueFilter = queueName;
  loadExecutions();
}

function handleSearch(val) {
  searchQuery = val.trim();
  renderExecutionsTable();
}

function manualRefresh() {
  loadAllData();
  showToast('Refreshed cluster records', 'info');
}

// ==========================================================================
// SALESFORCE LIGHTNING SLIDE-OVER RECORD DRAWER
// ==========================================================================

async function openTaskDrawer(taskId, openAnimation = true) {
  currentDrawerTaskId = taskId;
  const drawer = document.getElementById('taskDrawer');
  const backdrop = document.getElementById('drawerBackdrop');

  if (openAnimation) {
    if (drawer) drawer.classList.add('open');
    if (backdrop) backdrop.classList.add('open');
  }

  const idEl = document.getElementById('drawerTaskId');
  const nameEl = document.getElementById('drawerTaskName');
  if (idEl) idEl.textContent = taskId;
  if (nameEl) nameEl.textContent = 'Loading record details...';

  try {
    const res = await fetch(`${API}/api/v1/tasks/${taskId}`);
    if (!res.ok) throw new Error('Task record not found');
    const task = await res.json();
    currentDrawerTask = task;

    if (nameEl) nameEl.textContent = task.task_name;
    const badge = document.getElementById('drawerStatusBadge');
    if (badge) {
      const pill = getStatusPill(task.status);
      badge.className = `slds-drawer-badge ${pill.css}`;
      badge.textContent = task.status;
    }

    renderTimelineStepper(task);

    // Input payload
    let parsedArgs = [];
    let parsedKwargs = {};
    try { parsedArgs = JSON.parse(task.args_json || '[]'); } catch (e) {}
    try { parsedKwargs = JSON.parse(task.kwargs_json || '{}'); } catch (e) {}
    const inEl = document.getElementById('drawerInputJson');
    if (inEl) inEl.textContent = JSON.stringify({ args: parsedArgs, kwargs: parsedKwargs }, null, 2);

    // Output payload
    let parsedResult = null;
    try { parsedResult = JSON.parse(task.result_json); } catch (e) { parsedResult = task.result_json; }
    const outEl = document.getElementById('drawerOutputJson');
    if (outEl) outEl.textContent = parsedResult !== null ? JSON.stringify(parsedResult, null, 2) : '(No result yet or pending)';

    // Error tab
    const errTab = document.getElementById('drawerTabError');
    const errMsg = document.getElementById('drawerErrorMessage');
    const errTb = document.getElementById('drawerErrorTraceback');
    if (task.error_message || task.error_traceback) {
      if (errTab) errTab.style.display = 'inline-block';
      if (errMsg) errMsg.textContent = task.error_message || 'Task failed';
      if (errTb) errTb.textContent = task.error_traceback || 'No traceback captured';
    } else {
      if (errTab) errTab.style.display = 'none';
    }

    // Metadata tab
    const qEl = document.getElementById('dmQueue');
    if (qEl) qEl.textContent = task.queue || 'default';
    const prioEl = document.getElementById('dmPriority');
    if (prioEl) prioEl.textContent = `${getPriorityLabel(task.priority).text} (${task.priority})`;
    const wEl = document.getElementById('dmWorker');
    if (wEl) wEl.textContent = task.worker_id || 'Pending assignment';
    const retEl = document.getElementById('dmRetries');
    if (retEl) retEl.textContent = `${task.retry_count || 0} / ${task.max_retries || 3}`;
    const toEl = document.getElementById('dmTimeout');
    if (toEl) toEl.textContent = `${task.timeout || 300}s`;
    const cAt = document.getElementById('dmCreatedAt');
    if (cAt) cAt.textContent = task.created_at || '—';
    const compAt = document.getElementById('dmCompletedAt');
    if (compAt) compAt.textContent = task.completed_at || 'In-flight';

  } catch (err) {
    if (nameEl) nameEl.textContent = 'Record Details Unavailable';
  }
}

function renderTimelineStepper(task) {
  const container = document.getElementById('drawerTimeline');
  if (!container) return;

  const isCompleted = task.status === 'SUCCESS';
  const isFailed = task.status === 'FAILED';
  const isRunning = task.status === 'RUNNING';

  container.innerHTML = `
    <div class="timeline-step">
      <div class="t-icon done">✓</div>
      <div class="t-details">
        <div class="t-title">Task Scheduled & Partitioned</div>
        <div class="t-time">${task.created_at ? new Date(task.created_at).toLocaleTimeString() : '—'}</div>
        <div class="t-desc">Routed into queue partition <code>${escapeHtml(task.queue || 'default')}</code></div>
      </div>
    </div>

    <div class="timeline-step">
      <div class="t-icon ${isRunning ? 'active' : (isCompleted || isFailed ? 'done' : '')}">
        ${isRunning ? '▶' : (isCompleted || isFailed ? '✓' : '○')}
      </div>
      <div class="t-details">
        <div class="t-title">Worker Process Acquired</div>
        <div class="t-time">${task.started_at ? new Date(task.started_at).toLocaleTimeString() : (isRunning ? 'Executing' : 'Queued')}</div>
        <div class="t-desc">Claimed by worker <code>${escapeHtml(task.worker_id || 'worker-pool')}</code> (late ACK enabled)</div>
      </div>
    </div>

    <div class="timeline-step">
      <div class="t-icon ${isCompleted ? 'done' : (isFailed ? 'error' : '')}">
        ${isCompleted ? '✓' : (isFailed ? '✕' : '○')}
      </div>
      <div class="t-details">
        <div class="t-title">${isCompleted ? 'Execution Succeeded' : (isFailed ? 'Execution Failed' : 'Pending Completion')}</div>
        <div class="t-time">${task.completed_at ? new Date(task.completed_at).toLocaleTimeString() : '—'}</div>
        <div class="t-desc">${isCompleted ? 'Result committed and ACK sent' : (isFailed ? (task.error_message || 'Task failed') : 'Executing asynchronous workload')}</div>
      </div>
    </div>
  `;
}

function closeTaskDrawer() {
  const drawer = document.getElementById('taskDrawer');
  const backdrop = document.getElementById('drawerBackdrop');
  if (drawer) drawer.classList.remove('open');
  if (backdrop) backdrop.classList.remove('open');
  currentDrawerTaskId = null;
  currentDrawerTask = null;
}

function switchDrawerTab(tabName) {
  document.querySelectorAll('.drawer-tab-bar .d-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.dtab === tabName);
  });
  document.querySelectorAll('.drawer-body .drawer-tab-content').forEach(c => c.classList.remove('active'));
  const target = document.getElementById(`dtab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
  if (target) target.classList.add('active');
}

function copyCurrentTaskId() {
  if (currentDrawerTaskId) {
    navigator.clipboard.writeText(currentDrawerTaskId);
    showToast('Record ID copied to clipboard', 'info');
  }
}

function copyJsonPayload(elementId) {
  const text = document.getElementById(elementId)?.textContent;
  if (text) {
    navigator.clipboard.writeText(text);
    showToast('JSON payload copied', 'info');
  }
}

async function replayCurrentDrawerTask() {
  if (!currentDrawerTask) return;
  try {
    const res = await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_name: currentDrawerTask.task_name,
        args: JSON.parse(currentDrawerTask.args_json || '[]'),
        kwargs: JSON.parse(currentDrawerTask.kwargs_json || '{}'),
        queue: currentDrawerTask.queue,
        priority: currentDrawerTask.priority,
      }),
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Task re-executed with Record ID: ${data.task_id.substring(0, 8)}…`, 'success');
      closeTaskDrawer();
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to replay task', 'error');
  }
}

async function revokeCurrentDrawerTask() {
  if (!currentDrawerTaskId) return;
  try {
    const res = await fetch(`${API}/api/v1/tasks/${currentDrawerTaskId}/revoke`, { method: 'POST' });
    if (res.ok) {
      showToast(`Task ${currentDrawerTaskId.substring(0, 8)}… revoked`, 'info');
      closeTaskDrawer();
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to revoke task', 'error');
  }
}

// ==========================================================================
// SALESFORCE LIGHTNING "NEW TASK" MODAL
// ==========================================================================

function openStartTaskModal() {
  const modal = document.getElementById('startTaskModalOverlay');
  if (modal) modal.classList.add('open');
}

function closeStartTaskModal() {
  const modal = document.getElementById('startTaskModalOverlay');
  if (modal) modal.classList.remove('open');
}

function applyTaskPreset(preset) {
  if (!preset) return;
  const nameEl = document.getElementById('modalTaskName');
  if (nameEl) nameEl.value = preset;

  const argsEl = document.getElementById('modalTaskArgs');
  const kwargsEl = document.getElementById('modalTaskKwargs');
  const queueEl = document.getElementById('modalTaskQueue');
  const retriesEl = document.getElementById('modalTaskRetries');

  if (preset === 'celerlite.demo.add') {
    if (argsEl) argsEl.value = '[15, 25]';
    if (kwargsEl) kwargsEl.value = '{}';
    if (queueEl) queueEl.value = 'default';
  } else if (preset === 'celerlite.demo.multiply') {
    if (argsEl) argsEl.value = '[7, 8]';
    if (kwargsEl) kwargsEl.value = '{}';
    if (queueEl) queueEl.value = 'default';
  } else if (preset === 'celerlite.demo.send_email') {
    if (argsEl) argsEl.value = '["ceo@salesforce.com", "Quarterly Cloud Report"]';
    if (kwargsEl) kwargsEl.value = '{}';
    if (queueEl) queueEl.value = 'emails';
  } else if (preset === 'celerlite.demo.heavy_computation') {
    if (argsEl) argsEl.value = '[10000]';
    if (kwargsEl) kwargsEl.value = '{}';
    if (queueEl) queueEl.value = 'high_priority';
  } else if (preset === 'celerlite.demo.failing_task') {
    if (argsEl) argsEl.value = '[]';
    if (kwargsEl) kwargsEl.value = '{"reason": "intentional"}';
    if (queueEl) queueEl.value = 'default';
    if (retriesEl) retriesEl.value = '2';
  }
}

async function handleStartTaskSubmit(event) {
  event.preventDefault();
  const btn = document.getElementById('btnSubmitModal');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Saving...';
  }

  try {
    const taskName = document.getElementById('modalTaskName').value.trim();
    const queue = document.getElementById('modalTaskQueue').value;
    const priority = parseInt(document.getElementById('modalTaskPriority').value, 10);
    const args = JSON.parse(document.getElementById('modalTaskArgs').value || '[]');
    const kwargs = JSON.parse(document.getElementById('modalTaskKwargs').value || '{}');
    const maxRetries = parseInt(document.getElementById('modalTaskRetries').value, 10);
    const timeout = parseInt(document.getElementById('modalTaskTimeout').value, 10);

    const res = await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_name: taskName,
        args,
        kwargs,
        queue,
        priority,
        max_retries: maxRetries,
        timeout,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      showToast(`Task created: ${data.task_id.substring(0, 8)}…`, 'success');
      closeStartTaskModal();
      loadExecutions();
    } else {
      showToast('Error creating task record', 'error');
    }
  } catch (err) {
    showToast(`Invalid JSON: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Save & Run Task';
    }
  }
}

async function triggerBatchDemo() {
  showToast('Submitting 10 demonstration tasks...', 'info');
  for (let i = 1; i <= 10; i++) {
    await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_name: i % 2 === 0 ? 'celerlite.demo.add' : 'celerlite.demo.multiply',
        args: [i * 3, i * 7],
        queue: i % 3 === 0 ? 'payments' : 'default',
        priority: i % 4,
      }),
    });
  }
  loadExecutions();
}

// ==========================================================================
// DLQ ACTIONS
// ==========================================================================

async function replayDLQEntry(entryId) {
  try {
    const res = await fetch(`${API}/api/v1/dlq/${entryId}/replay`, { method: 'POST' });
    if (res.ok) {
      showToast('Task re-enqueued for execution', 'success');
      loadDLQ();
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to replay task', 'error');
  }
}

async function deleteDLQEntry(entryId) {
  try {
    const res = await fetch(`${API}/api/v1/dlq/${entryId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('DLQ record purged', 'info');
      loadDLQ();
    }
  } catch (err) {
    showToast('Failed to purge record', 'error');
  }
}

async function replayAllDLQ() {
  try {
    const res = await fetch(`${API}/api/v1/dlq/replay-all`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      showToast(`Replayed ${data.replayed_count} dead-lettered tasks`, 'success');
      loadDLQ();
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to replay DLQ', 'error');
  }
}

// ==========================================================================
// CHARTS (CHART.JS SALESFORCE LIGHT THEME)
// ==========================================================================

function initCharts() {
  // Line Chart: Throughput Velocity
  const throughputCtx = document.getElementById('throughputChart')?.getContext('2d');
  if (throughputCtx) {
    const initialLabels = Array(20).fill('');
    const initialData = Array(20).fill(0);

    throughputChart = new Chart(throughputCtx, {
      type: 'line',
      data: {
        labels: initialLabels,
        datasets: [{
          label: 'Tasks / sec',
          data: initialData,
          borderColor: '#0176d3',
          backgroundColor: 'rgba(1, 118, 211, 0.08)',
          borderWidth: 2.5,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#0176d3',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#032d60',
            titleFont: { family: 'Inter', size: 11 },
            bodyFont: { family: 'JetBrains Mono', size: 12 },
            padding: 8,
          }
        },
        scales: {
          x: { display: false },
          y: {
            beginAtZero: true,
            grid: { color: '#f3f3f3' },
            ticks: {
              color: '#706e6b',
              font: { family: 'JetBrains Mono', size: 10 },
              maxTicksLimit: 5,
            }
          }
        }
      }
    });
  }

  // Donut Chart: Status Distribution
  const donutCtx = document.getElementById('statusDonut')?.getContext('2d');
  if (donutCtx) {
    statusDonutChart = new Chart(donutCtx, {
      type: 'doughnut',
      data: {
        labels: ['Completed', 'Running', 'Failed', 'DLQ'],
        datasets: [{
          data: [1, 0, 0, 0],
          backgroundColor: ['#2e844a', '#0176d3', '#ea001e', '#7f22fe'],
          borderWidth: 2,
          borderColor: '#ffffff',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              color: '#444444',
              font: { family: 'Inter', size: 11 },
              boxWidth: 8,
              padding: 12,
            }
          }
        }
      }
    });
  }
}

function updateDonutChart(counts) {
  if (!statusDonutChart) return;
  const completed = counts.SUCCESS || 0;
  const running = counts.RUNNING || 0;
  const failed = counts.FAILED || 0;
  const dlq = counts.DEAD_LETTERED || 0;

  statusDonutChart.data.datasets[0].data = [completed, running, failed, dlq];
  statusDonutChart.update();
}

function recordThroughputSample(tps) {
  if (!throughputChart) return;
  throughputHistory.push(tps);
  if (throughputHistory.length > 20) throughputHistory.shift();

  throughputChart.data.datasets[0].data = [...throughputHistory];
  throughputChart.update();
}

// ==========================================================================
// HELPERS
// ==========================================================================

function getStatusPill(status) {
  switch (status) {
    case 'SUCCESS': return { text: 'COMPLETED', css: 'status-success' };
    case 'RUNNING': return { text: 'IN-PROGRESS', css: 'status-running' };
    case 'FAILED': return { text: 'FAILED', css: 'status-failed' };
    case 'DEAD_LETTERED': return { text: 'DEAD LETTER', css: 'status-dlq' };
    case 'PENDING': return { text: 'PENDING', css: 'status-pending' };
    case 'REVOKED': return { text: 'REVOKED', css: 'status-failed' };
    default: return { text: status, css: 'status-pending' };
  }
}

function getPriorityLabel(priority) {
  switch (parseInt(priority, 10)) {
    case 3: return { text: 'CRITICAL', css: 'priority-critical' };
    case 2: return { text: 'HIGH', css: 'priority-high' };
    case 1: return { text: 'NORMAL', css: 'priority-normal' };
    case 0: return { text: 'LOW', css: 'priority-low' };
    default: return { text: 'NORMAL', css: 'priority-normal' };
  }
}

function formatDuration(ms, startedAt, completedAt) {
  if (ms !== null && ms !== undefined) {
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }
  if (startedAt && completedAt) {
    const diff = new Date(completedAt).getTime() - new Date(startedAt).getTime();
    if (diff < 1000) return `${diff}ms`;
    return `${(diff / 1000).toFixed(2)}s`;
  }
  return '—';
}

function formatTimeAgo(isoString) {
  if (!isoString) return '—';
  const sec = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `slds-toast toast-${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✓' : (type === 'error' ? '✕' : 'ℹ')}</span>
    <span>${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
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
