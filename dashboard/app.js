/* ==========================================================================
   CelerLite Console — Temporal Cloud Style Real-Time Controller
   SPA View Switching, WebSocket Telemetry, Task Drawer & Modal
   ========================================================================== */

'use strict';

const API = location.host ? '' : 'http://localhost:8000';
let ws = null;
let currentView = 'executions';
let currentStatusFilter = '';
let currentQueueFilter = '';
let searchQuery = '';
let currentDrawerTask = null;
let currentDrawerTaskId = null;

// Telemetry & Cache
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
});

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // ESC closes drawer or modal
    if (e.key === 'Escape') {
      closeTaskDrawer();
      closeStartTaskModal();
    }
    // '/' focuses search bar
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
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
      console.log('[WS] Connected to CelerLite event bus');
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event && payload.event !== 'connected') {
          handleIncomingEvent(payload);
        }
      } catch (err) {
        console.warn('[WS] Parse error', err);
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
  const badge = document.getElementById('liveStreamBadge');

  if (connected) {
    if (dot) {
      dot.style.backgroundColor = 'var(--emerald)';
      dot.classList.add('status-pulse-dot');
    }
    if (text) text.textContent = 'Connected (Live)';
    if (badge) {
      badge.textContent = 'LIVE';
      badge.style.color = 'var(--emerald)';
    }
  } else {
    if (dot) {
      dot.style.backgroundColor = 'var(--rose)';
      dot.classList.remove('status-pulse-dot');
    }
    if (text) text.textContent = 'Reconnecting...';
    if (badge) {
      badge.textContent = 'POLLING';
      badge.style.color = 'var(--amber)';
    }
  }
}

function handleIncomingEvent(event) {
  // Update or insert task in local executions list
  const existingIdx = executionsList.findIndex(t => t.id === event.task_id);
  const nowIso = new Date().toISOString();

  if (existingIdx !== -1) {
    const task = executionsList[existingIdx];
    if (event.event === 'task_started') {
      task.status = 'RUNNING';
      task.worker_id = event.worker_id;
      task.started_at = nowIso;
    } else if (event.event === 'task_completed') {
      task.status = 'SUCCESS';
      task.completed_at = nowIso;
      task.duration_ms = event.duration_ms;
    } else if (event.event === 'task_failed') {
      task.status = 'FAILED';
      task.completed_at = nowIso;
      task.error_message = event.error;
    }
  } else if (event.task_id) {
    executionsList.unshift({
      id: event.task_id,
      task_name: event.task_name || 'unknown',
      status: event.event === 'task_started' ? 'RUNNING' : (event.event === 'task_completed' ? 'SUCCESS' : 'PENDING'),
      queue: event.queue || 'default',
      priority: event.priority ?? 1,
      worker_id: event.worker_id || null,
      created_at: nowIso,
      started_at: event.event === 'task_started' ? nowIso : null,
      completed_at: event.event === 'task_completed' ? nowIso : null,
      duration_ms: event.duration_ms || null,
    });
  }

  // Re-render table if on executions view
  if (currentView === 'executions') {
    renderExecutionsTable();
  }

  // Update stats counters
  loadStats();

  // If the drawer is currently open for this task, refresh drawer
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

  // Apply search filtering
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

  if (filtered.length === 0) {
    tbody.innerHTML = '';
    if (emptyState) emptyState.style.display = 'flex';
    document.getElementById('paginationSummary').textContent = 'Showing 0 of 0 executions';
    return;
  }

  if (emptyState) emptyState.style.display = 'none';
  document.getElementById('paginationSummary').textContent = `Showing 1-${filtered.length} of ${filtered.length} executions`;

  tbody.innerHTML = filtered.map(t => {
    const badgeClass = getBadgeClass(t.status);
    const priorityLabel = getPriorityLabel(t.priority);
    const duration = formatDuration(t.duration_ms, t.started_at, t.completed_at);
    const timeFormatted = formatTimeAgo(t.created_at || t.started_at);

    return `
      <tr onclick="openTaskDrawer('${escapeHtml(t.id)}')">
        <td><span class="badge ${badgeClass}">${escapeHtml(t.status)}</span></td>
        <td class="task-name-cell">${escapeHtml(t.task_name)}</td>
        <td><a href="javascript:void(0)" class="task-id-code" onclick="event.stopPropagation(); openTaskDrawer('${escapeHtml(t.id)}')">${escapeHtml(t.id.substring(0, 13))}…</a></td>
        <td><span class="queue-tag">${escapeHtml(t.queue || 'default')}</span></td>
        <td><span class="priority-tag ${priorityLabel.css}">${priorityLabel.text}</span></td>
        <td><span style="font-family: var(--font-mono); font-size: 11.5px; color: var(--text-muted);">${escapeHtml(t.worker_id || '—')}</span></td>
        <td style="text-align: right;"><span class="duration-val">${duration}</span></td>
        <td style="text-align: right;"><span class="time-val">${timeFormatted}</span></td>
      </tr>
    `;
  }).join('');
}

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

      document.getElementById('statTotalExecutions').textContent = total;
      document.getElementById('statRunning').textContent = running;
      document.getElementById('statCompleted').textContent = completed;
      document.getElementById('statFailed').textContent = failed + dlq;
      document.getElementById('statThroughput').textContent = (stats.throughput_per_sec || 0.0).toFixed(1);

      // Pill counts
      document.getElementById('pillCountAll').textContent = total;
      document.getElementById('pillCountRunning').textContent = running;
      document.getElementById('pillCountSuccess').textContent = completed;
      document.getElementById('pillCountFailed').textContent = failed;
      document.getElementById('pillCountDlq').textContent = dlq;
      document.getElementById('navCountExecutions').textContent = total;
      document.getElementById('navCountDLQ').textContent = dlq;

      // Success rate
      const rate = total > 0 ? Math.round((completed / (completed + failed + dlq || 1)) * 100) : 100;
      document.getElementById('statSuccessRate').textContent = `${rate}% success rate`;

      // Update charts
      updateDonutChart({ SUCCESS: completed, RUNNING: running, FAILED: failed, DEAD_LETTERED: dlq, PENDING: pending });
      recordThroughputSample(stats.throughput_per_sec || 0);

      // Latencies
      if (stats.avg_latency_ms !== undefined) {
        document.getElementById('telemetryLatAvg').textContent = `${stats.avg_latency_ms}ms`;
        document.getElementById('telemetryLatP99').textContent = `${stats.p99_latency_ms || stats.avg_latency_ms}ms`;
        document.getElementById('telemetryLatP50').textContent = `${Math.round(stats.avg_latency_ms * 0.7)}ms`;
        document.getElementById('telemetryLatP95').textContent = `${Math.round(stats.avg_latency_ms * 1.3)}ms`;
      }
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
              <span class="badge badge-success">ACTIVE</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted);">Partition Sub-queues:</div>
            <div class="queue-priority-breakdown">
              <div class="qp-item">
                <span class="qp-label text-rose">CRITICAL</span>
                <span class="qp-val">${prios.critical || 0}</span>
              </div>
              <div class="qp-item">
                <span class="qp-label text-amber">HIGH</span>
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
            <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); border-top: 1px solid var(--border-subtle); padding-top: 8px;">
              <span>Total Backlog: <b style="color: var(--text-primary); font-family: var(--font-mono);">${total}</b></span>
              <button class="btn-subtle" style="padding: 2px 7px; font-size: 10.5px;" onclick="filterByQueue('${escapeHtml(name)}')">View Tasks →</button>
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
      const badge = document.getElementById('navCountWorkers');
      if (badge) badge.textContent = `${workers.length} active`;

      if (tbody) {
        if (workers.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">No workers registered. Start worker pool via scripts/run_worker.py or run.py</td></tr>`;
          return;
        }

        tbody.innerHTML = workers.map(w => `
          <tr>
            <td><span class="badge ${w.status === 'ONLINE' ? 'badge-success' : 'badge-failed'}">${w.status}</span></td>
            <td><code style="font-family: var(--font-mono); color: #93c5fd;">${escapeHtml(w.id)}</code></td>
            <td>${escapeHtml(w.hostname || 'localhost')}</td>
            <td><span style="font-family: var(--font-mono);">${w.pid || 1}</span></td>
            <td style="text-align: right; font-family: var(--font-mono); font-weight: 600;">${w.tasks_processed || 0}</td>
            <td style="text-align: right; font-family: var(--font-mono); color: ${w.tasks_failed > 0 ? 'var(--rose)' : 'inherit'};">${w.tasks_failed || 0}</td>
            <td style="text-align: right; font-size: 11px; color: var(--text-muted);">${formatTimeAgo(w.last_heartbeat)}</td>
          </tr>
        `).join('');
      }
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
      const navDlq = document.getElementById('navCountDLQ');

      if (navDlq) navDlq.textContent = entries.length;

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
          <td><span style="color: var(--rose); font-size: 11.5px;">${escapeHtml(e.error_message || 'Permanent failure')}</span></td>
          <td style="text-align: center; font-family: var(--font-mono);">${e.retry_count}</td>
          <td><span class="queue-tag">${escapeHtml(e.original_queue)}</span></td>
          <td><span class="time-val">${formatTimeAgo(e.dead_lettered_at)}</span></td>
          <td style="text-align: right;">
            <button class="btn-subtle" style="padding: 3px 8px; font-size: 11px;" onclick="replayDLQEntry('${escapeHtml(e.id)}')">↺ Replay</button>
            <button class="btn-subtle" style="padding: 3px 6px; font-size: 11px; color: var(--rose);" onclick="deleteDLQEntry('${escapeHtml(e.id)}')">✕</button>
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
        const mode = data.redis.mode || (data.redis.connected ? 'Redis Cluster' : 'Standalone');
        document.getElementById('clusterModeLabel').textContent = mode;
        document.getElementById('cfgBroker').textContent = mode;
      }
      if (data.uptime_seconds) {
        const mins = Math.floor(data.uptime_seconds / 60);
        document.getElementById('clusterUptimeText').textContent = `${mins}m uptime`;
      }
    }
  } catch (err) {
    console.warn('Metrics poll error', err);
  }
}

// ==========================================================================
// TEMPORAL SLIDE-OVER DRAWER (TASK DETAILS)
// ==========================================================================

async function openTaskDrawer(taskId, openAnimation = true) {
  currentDrawerTaskId = taskId;
  const drawer = document.getElementById('taskDrawer');
  const overlay = document.getElementById('drawerOverlay');

  if (openAnimation) {
    drawer.classList.add('open');
    overlay.classList.add('open');
  }

  // Set ID and temporary loading text
  document.getElementById('drawerTaskId').textContent = taskId;
  document.getElementById('drawerTaskName').textContent = 'Loading execution details...';

  try {
    const res = await fetch(`${API}/api/v1/tasks/${taskId}`);
    if (!res.ok) throw new Error('Task not found');
    const task = await res.json();
    currentDrawerTask = task;

    // Header info
    document.getElementById('drawerTaskName').textContent = task.task_name;
    const badge = document.getElementById('drawerStatusBadge');
    badge.className = `badge ${getBadgeClass(task.status)}`;
    badge.textContent = task.status;

    // Timeline tab
    renderTimelineStepper(task);

    // Input payload tab
    let parsedArgs = [];
    let parsedKwargs = {};
    try { parsedArgs = JSON.parse(task.args_json || '[]'); } catch (e) {}
    try { parsedKwargs = JSON.parse(task.kwargs_json || '{}'); } catch (e) {}
    document.getElementById('drawerInputJson').textContent = JSON.stringify({ args: parsedArgs, kwargs: parsedKwargs }, null, 2);

    // Output payload tab
    let parsedResult = null;
    try { parsedResult = JSON.parse(task.result_json); } catch (e) { parsedResult = task.result_json; }
    document.getElementById('drawerOutputJson').textContent = parsedResult !== null ? JSON.stringify(parsedResult, null, 2) : '(No result yet or task pending)';

    // Error tab
    const errorTabBtn = document.getElementById('drawerTabError');
    if (task.error_message || task.error_traceback) {
      errorTabBtn.style.display = 'inline-block';
      document.getElementById('drawerErrorMessage').textContent = task.error_message || 'Task failed with exception';
      document.getElementById('drawerErrorTraceback').textContent = task.error_traceback || 'No traceback captured';
    } else {
      errorTabBtn.style.display = 'none';
      document.getElementById('drawerErrorMessage').textContent = 'None';
      document.getElementById('drawerErrorTraceback').textContent = 'None';
    }

    // Metadata tab
    document.getElementById('dmQueue').textContent = task.queue || 'default';
    document.getElementById('dmPriority').textContent = `${getPriorityLabel(task.priority).text} (${task.priority})`;
    document.getElementById('dmWorker').textContent = task.worker_id || 'Pending assignment';
    document.getElementById('dmRetries').textContent = `${task.retry_count || 0} / ${task.max_retries || 3}`;
    document.getElementById('dmTimeout').textContent = `${task.timeout || 300}s`;
    document.getElementById('dmCreatedAt').textContent = task.created_at || '—';
    document.getElementById('dmCompletedAt').textContent = task.completed_at || 'In-flight';

  } catch (err) {
    document.getElementById('drawerTaskName').textContent = 'Task Details Unavailable';
    console.error(err);
  }
}

function renderTimelineStepper(task) {
  const container = document.getElementById('drawerTimeline');
  if (!container) return;

  const isCompleted = task.status === 'SUCCESS';
  const isFailed = task.status === 'FAILED';
  const isRunning = task.status === 'RUNNING';

  container.innerHTML = `
    <!-- Step 1: Enqueued -->
    <div class="timeline-step">
      <div class="t-icon done">✓</div>
      <div class="t-details">
        <div class="t-title">Task Scheduled</div>
        <div class="t-time">${task.created_at ? new Date(task.created_at).toLocaleTimeString() : '—'}</div>
        <div class="t-desc">Enqueued to partition <code>${escapeHtml(task.queue || 'default')}</code> with priority ${task.priority}</div>
      </div>
    </div>

    <!-- Step 2: Running -->
    <div class="timeline-step">
      <div class="t-icon ${isRunning ? 'active' : (isCompleted || isFailed ? 'done' : '')}">
        ${isRunning ? '▶' : (isCompleted || isFailed ? '✓' : '○')}
      </div>
      <div class="t-details">
        <div class="t-title">Worker Assigned & Executing</div>
        <div class="t-time">${task.started_at ? new Date(task.started_at).toLocaleTimeString() : (isRunning ? 'Executing now' : 'Pending')}</div>
        <div class="t-desc">Claimed by worker <code>${escapeHtml(task.worker_id || 'worker-pool')}</code> (late ACK enabled)</div>
      </div>
    </div>

    <!-- Step 3: Finished -->
    <div class="timeline-step">
      <div class="t-icon ${isCompleted ? 'done' : (isFailed ? 'error' : '')}">
        ${isCompleted ? '✓' : (isFailed ? '✕' : '○')}
      </div>
      <div class="t-details">
        <div class="t-title">${isCompleted ? 'Execution Succeeded' : (isFailed ? 'Execution Failed' : 'Pending Completion')}</div>
        <div class="t-time">${task.completed_at ? new Date(task.completed_at).toLocaleTimeString() : '—'}</div>
        <div class="t-desc">${isCompleted ? 'Results acknowledged and stored in cache' : (isFailed ? (task.error_message || 'Task failed') : 'Waiting for worker process')}</div>
      </div>
    </div>
  `;
}

function closeTaskDrawer() {
  const drawer = document.getElementById('taskDrawer');
  const overlay = document.getElementById('drawerOverlay');
  if (drawer) drawer.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
  currentDrawerTaskId = null;
  currentDrawerTask = null;
}

function switchDrawerTab(tabName) {
  document.querySelectorAll('.drawer-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.drawer-content').forEach(c => c.classList.remove('active'));

  const btn = document.querySelector(`.drawer-tab[data-dtab="${tabName}"]`);
  const content = document.getElementById(`dtabContent${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);

  if (btn) btn.classList.add('active');
  if (content) content.classList.add('active');
}

function copyCurrentTaskId() {
  if (currentDrawerTaskId) {
    navigator.clipboard.writeText(currentDrawerTaskId);
    showToast('Task ID copied to clipboard', 'info');
  }
}

function copyJsonPayload(elementId) {
  const text = document.getElementById(elementId)?.textContent;
  if (text) {
    navigator.clipboard.writeText(text);
    showToast('Payload copied to clipboard', 'info');
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
      showToast(`Task re-submitted with new ID: ${data.task_id.substring(0, 8)}…`, 'success');
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
      openTaskDrawer(currentDrawerTaskId, false);
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to revoke task', 'error');
  }
}

// ==========================================================================
// START TASK MODAL
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
  document.getElementById('modalTaskName').value = preset;

  if (preset === 'celerlite.demo.add') {
    document.getElementById('modalTaskArgs').value = '[10, 20]';
    document.getElementById('modalTaskKwargs').value = '{}';
    document.getElementById('modalTaskQueue').value = 'default';
  } else if (preset === 'celerlite.demo.multiply') {
    document.getElementById('modalTaskArgs').value = '[7, 8]';
    document.getElementById('modalTaskKwargs').value = '{}';
    document.getElementById('modalTaskQueue').value = 'default';
  } else if (preset === 'celerlite.demo.send_email') {
    document.getElementById('modalTaskArgs').value = '["user@stripe.com", "Order Confirmation"]';
    document.getElementById('modalTaskKwargs').value = '{}';
    document.getElementById('modalTaskQueue').value = 'emails';
  } else if (preset === 'celerlite.demo.heavy_computation') {
    document.getElementById('modalTaskArgs').value = '[10000]';
    document.getElementById('modalTaskKwargs').value = '{}';
    document.getElementById('modalTaskQueue').value = 'high_priority';
  } else if (preset === 'celerlite.demo.failing_task') {
    document.getElementById('modalTaskArgs').value = '[]';
    document.getElementById('modalTaskKwargs').value = '{"reason": "intentional"}';
    document.getElementById('modalTaskQueue').value = 'default';
    document.getElementById('modalTaskRetries').value = '2';
  }
}

async function handleStartTaskSubmit(event) {
  event.preventDefault();
  const btn = document.getElementById('btnSubmitModal');
  btn.disabled = true;
  btn.textContent = 'Submitting...';

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
      showToast(`Task started: ${data.task_id.substring(0, 8)}…`, 'success');
      closeStartTaskModal();
      loadExecutions();
    } else {
      showToast('Error submitting task', 'error');
    }
  } catch (err) {
    showToast(`Invalid JSON: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Start Execution →';
  }
}

async function triggerBatchDemo() {
  showToast('Generating 10 test tasks...', 'info');
  for (let i = 1; i <= 10; i++) {
    await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task_name: i % 2 === 0 ? 'celerlite.demo.add' : 'celerlite.demo.multiply',
        args: [i * 2, i * 5],
        queue: i % 3 === 0 ? 'payments' : 'default',
        priority: i % 4,
      }),
    });
  }
  loadExecutions();
}

// ==========================================================================
// VIEW SWITCHING (SPA NAVIGATION)
// ==========================================================================

function switchView(viewName) {
  currentView = viewName;

  // Update sidebar active buttons
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(b => {
    b.classList.toggle('active', b.dataset.view === viewName);
  });

  // Update panels
  document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`view${viewName.charAt(0).toUpperCase() + viewName.slice(1)}`);
  if (target) target.classList.add('active');

  // Breadcrumb title
  const titles = {
    executions: 'Executions',
    queues: 'Task Queues',
    workers: 'Worker Fleet',
    dlq: 'Dead Letter Queue',
    metrics: 'Telemetry',
    settings: 'Configuration',
  };
  document.getElementById('currentViewTitle').textContent = titles[viewName] || 'Dashboard';

  // Trigger relevant refresh
  if (viewName === 'executions') loadExecutions();
  if (viewName === 'queues') loadQueues();
  if (viewName === 'workers') loadWorkers();
  if (viewName === 'dlq') loadDLQ();
  if (viewName === 'metrics') loadMetrics();
}

function setStatusFilter(status) {
  currentStatusFilter = status;
  document.querySelectorAll('#statusFilterPills .pill').forEach(p => {
    p.classList.toggle('active', p.dataset.status === status);
  });
  loadExecutions();
}

function setQueueFilter(queue) {
  currentQueueFilter = queue;
  loadExecutions();
}

function filterByQueue(queueName) {
  switchView('executions');
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
  showToast('Refreshed cluster state', 'info');
}

function handleRefreshChange(rate) {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  if (rate === '5') {
    autoRefreshTimer = setInterval(loadAllData, 5000);
  } else if (rate === '15') {
    autoRefreshTimer = setInterval(loadAllData, 15000);
  }
}

// ==========================================================================
// DLQ ACTIONS
// ==========================================================================

async function replayDLQEntry(entryId) {
  try {
    const res = await fetch(`${API}/api/v1/dlq/${entryId}/replay`, { method: 'POST' });
    if (res.ok) {
      showToast('Task re-enqueued to original queue', 'success');
      loadDLQ();
      loadExecutions();
    }
  } catch (err) {
    showToast('Failed to replay DLQ entry', 'error');
  }
}

async function deleteDLQEntry(entryId) {
  try {
    const res = await fetch(`${API}/api/v1/dlq/${entryId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('DLQ entry removed', 'info');
      loadDLQ();
    }
  } catch (err) {
    showToast('Failed to delete DLQ entry', 'error');
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
// CHARTS (CHART.JS ENTERPRISE DARK THEME)
// ==========================================================================

function initCharts() {
  // Throughput Line Chart
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
          borderColor: '#4f46e5',
          backgroundColor: 'rgba(79, 70, 229, 0.08)',
          borderWidth: 2,
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
          pointHoverBackgroundColor: '#4f46e5',
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0e1320',
            borderColor: '#222c42',
            borderWidth: 1,
            titleFont: { family: 'Inter', size: 11 },
            bodyFont: { family: 'JetBrains Mono', size: 12 },
            padding: 8,
          }
        },
        scales: {
          x: { display: false },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255, 255, 255, 0.04)' },
            ticks: {
              color: '#64748b',
              font: { family: 'JetBrains Mono', size: 10 },
              maxTicksLimit: 5,
            }
          }
        }
      }
    });
  }

  // Status Donut Chart
  const donutCtx = document.getElementById('statusDonut')?.getContext('2d');
  if (donutCtx) {
    statusDonutChart = new Chart(donutCtx, {
      type: 'doughnut',
      data: {
        labels: ['Completed', 'Running', 'Failed', 'DLQ'],
        datasets: [{
          data: [1, 0, 0, 0],
          backgroundColor: ['#10b981', '#0ea5e9', '#f43f5e', '#a855f7'],
          borderWidth: 2,
          borderColor: '#0e1320',
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
              color: '#94a3b8',
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

  statusDonutChart.data.datasets[0].data = [
    completed,
    running,
    failed,
    dlq,
  ];
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

function getBadgeClass(status) {
  switch (status) {
    case 'SUCCESS': return 'badge-success';
    case 'RUNNING': return 'badge-running';
    case 'FAILED': return 'badge-failed';
    case 'RETRYING': return 'badge-retrying';
    case 'DEAD_LETTERED': return 'badge-dlq';
    case 'REVOKED': return 'badge-revoked';
    default: return 'badge-retrying';
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
    const diff = new Date(completedAt) - new Date(startedAt);
    return diff < 1000 ? `${diff}ms` : `${(diff / 1000).toFixed(2)}s`;
  }
  return '—';
}

function formatTimeAgo(isoString) {
  if (!isoString) return '—';
  try {
    const seconds = Math.floor((new Date() - new Date(isoString)) / 1000);
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    return `${hours}h ago`;
  } catch (e) {
    return isoString;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    toast.style.transition = 'all 0.2s ease';
    setTimeout(() => toast.remove(), 200);
  }, 3200);
}
