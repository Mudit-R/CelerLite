/* CelerLite Dashboard — Real-time JavaScript */
'use strict';

const API = location.host ? '' : 'http://localhost:8000';  // Same origin or localhost fallback
let ws = null;
let throughputHistory = [];
let statusDonutChart = null;
let throughputChart = null;
let feedRows = [];
const MAX_FEED_ROWS = 50;

// ===== CLOCK =====
function updateClock() {
  const clockEl = document.getElementById('clock');
  if (!clockEl) return;
  const now = new Date();
  clockEl.textContent =
    now.toLocaleTimeString('en-IN', { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// ===== WEBSOCKET =====
function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const host = location.host || 'localhost:8000';
  const url = `${proto}://${host}/api/v1/ws/events`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    setWsStatus(true);
    console.log('[WS] Connected');
  };

  ws.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      if (event.event !== 'connected') {
        addFeedRow(event);
      }
    } catch (err) { /* ignore */ }
  };

  ws.onclose = () => {
    setWsStatus(false);
    console.log('[WS] Disconnected. Reconnecting in 3s...');
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => ws.close();
}

function setWsStatus(connected) {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  dot.className = 'status-dot ' + (connected ? 'connected' : 'disconnected');
  text.textContent = connected ? 'Live' : 'Reconnecting…';
}

// ===== LIVE FEED =====
const EVENT_COLORS = {
  task_submitted:     'status-PENDING',
  task_started:       'status-RUNNING',
  task_completed:     'status-SUCCESS',
  task_failed:        'status-FAILED',
  task_retried:       'status-RETRYING',
  task_dead_lettered: 'status-DEAD_LETTERED',
  task_revoked:       'status-REVOKED',
};

function addFeedRow(event) {
  const tbody = document.getElementById('feedBody');
  const row = document.createElement('tr');
  row.className = 'feed-row-new';

  const time = new Date(event.timestamp || Date.now()).toLocaleTimeString('en-IN', { hour12: false });
  const taskId = event.task_id ? event.task_id.slice(0, 8) + '…' : '—';
  const duration = event.duration_ms ? `${event.duration_ms.toFixed(1)}ms` : '—';
  const badgeClass = EVENT_COLORS[event.event] || 'status-PENDING';
  const eventLabel = (event.event || '').replace('task_', '').toUpperCase().replace('_', ' ');

  row.innerHTML = `
    <td class="task-id-short">${time}</td>
    <td class="task-name">${event.task_name || '—'}</td>
    <td><span class="status-badge ${badgeClass}">${eventLabel}</span></td>
    <td class="task-id-short">${taskId}</td>
    <td class="task-id-short">${event.worker_id || '—'}</td>
    <td class="duration">${duration}</td>
    <td class="task-id-short">${event.queue || '—'}</td>
  `;

  tbody.insertBefore(row, tbody.firstChild);
  feedRows.push(row);

  if (feedRows.length > MAX_FEED_ROWS) {
    const old = feedRows.shift();
    old.remove();
  }
}

function clearFeed() {
  document.getElementById('feedBody').innerHTML = '';
  feedRows = [];
}

// ===== CHARTS INIT =====
function initCharts() {
  // Donut chart
  const donutCtx = document.getElementById('statusDonut').getContext('2d');
  statusDonutChart = new Chart(donutCtx, {
    type: 'doughnut',
    data: {
      labels: ['Pending', 'Running', 'Success', 'Failed', 'Retrying', 'DLQ'],
      datasets: [{
        data: [0, 0, 0, 0, 0, 0],
        backgroundColor: [
          'rgba(148,163,184,0.7)',
          'rgba(59,130,246,0.8)',
          'rgba(16,185,129,0.8)',
          'rgba(239,68,68,0.8)',
          'rgba(245,158,11,0.8)',
          'rgba(127,29,29,0.7)',
        ],
        borderWidth: 0,
        hoverOffset: 6,
      }],
    },
    options: {
      cutout: '72%',
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      animation: { duration: 500 },
    },
  });

  // Throughput line chart
  const labels = Array.from({ length: 60 }, (_, i) => i === 0 ? 'now' : `-${60-i}s`).reverse();
  const tpCtx = document.getElementById('throughputChart').getContext('2d');
  throughputChart = new Chart(tpCtx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'tasks/sec',
        data: Array(60).fill(null),
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59,130,246,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        x: {
          display: false,
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(99,120,255,0.08)' },
          ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 } },
        },
      },
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      animation: { duration: 300 },
    },
  });
}

function updateDonut(counts) {
  if (!statusDonutChart) return;
  const vals = [
    counts.PENDING || 0,
    counts.RUNNING || 0,
    counts.SUCCESS || 0,
    counts.FAILED || 0,
    counts.RETRYING || 0,
    counts.DEAD_LETTERED || 0,
  ];
  statusDonutChart.data.datasets[0].data = vals;
  statusDonutChart.update();

  const total = vals.reduce((a, b) => a + b, 0);
  document.getElementById('donutTotal').textContent = total.toLocaleString();

  // Legend
  const labels = ['Pending', 'Running', 'Success', 'Failed', 'Retrying', 'DLQ'];
  const colors = ['#94a3b8', '#3b82f6', '#10b981', '#ef4444', '#f59e0b', '#7f1d1d'];
  const legend = document.getElementById('donutLegend');
  legend.innerHTML = labels.map((l, i) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${colors[i]}"></div>${l}: ${vals[i].toLocaleString()}</div>`
  ).join('');
}

function updateThroughput(tps) {
  if (!throughputChart) return;
  const data = throughputChart.data.datasets[0].data;
  data.push(tps);
  if (data.length > 60) data.shift();
  throughputChart.update();
}

// ===== API POLLING =====
async function fetchMetrics() {
  try {
    const res = await fetch(`${API}/api/v1/metrics`);
    if (!res.ok) return;
    const data = await res.json();

    // KPI cards
    const taskData = data.tasks || {};
    animateNumber('kpiCompletedVal', taskData.completed_total || 0);
    document.getElementById('kpiThroughputVal').textContent =
      (taskData.throughput_per_sec || 0).toFixed(1);
    const w = data.workers || {};
    document.getElementById('kpiWorkersVal').textContent =
      `${w.active || 0}/${w.total || 0}`;
    document.getElementById('kpiWorkersSub').textContent = `of ${w.total || 0} total`;

    const dlqCount = (taskData.by_status || {}).DEAD_LETTERED || 0;
    document.getElementById('kpiDLQVal').textContent = dlqCount;
    const dlqCard = document.getElementById('kpiDLQ');
    dlqCard.style.borderColor = dlqCount > 0 ? 'rgba(239,68,68,0.4)' : '';

    // Donut
    updateDonut(taskData.by_status || {});

    // Throughput chart
    updateThroughput(taskData.throughput_per_sec || 0);

    // Latency
    document.getElementById('latP99').textContent =
      `${(taskData.p99_latency_ms || 0).toFixed(1)}ms`;
    document.getElementById('latAvg').textContent =
      `${(taskData.avg_latency_ms || 0).toFixed(1)}ms`;

    // Uptime
    document.getElementById('uptimeDisplay').textContent =
      `Uptime: ${formatUptime(data.uptime_seconds || 0)}`;

  } catch (e) { /* Redis or API not yet ready */ }
}

async function loadWorkers() {
  try {
    const res = await fetch(`${API}/api/v1/workers`);
    if (!res.ok) return;
    const workers = await res.json();
    const tbody = document.getElementById('workersBody');
    tbody.innerHTML = workers.length === 0
      ? '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:1rem">No workers registered</td></tr>'
      : workers.map(w => {
          const statusClass = w.status === 'ONLINE' ? 'worker-status-online' :
                             (w.status === 'DEAD' ? 'worker-status-dead' : 'worker-status-idle');
          const hb = w.last_heartbeat
            ? new Date(w.last_heartbeat).toLocaleTimeString('en-IN', { hour12: false })
            : '—';
          return `<tr>
            <td class="task-name">${w.worker_id || '—'}</td>
            <td class="task-id-short">${w.pid || '—'}</td>
            <td class="${statusClass}">${w.status || '—'}</td>
            <td class="task-id-short">${w.current_task_id ? w.current_task_id.slice(0,8)+'…' : '—'}</td>
            <td class="task-id-short">${parseInt(w.tasks_processed || 0).toLocaleString()}</td>
            <td class="task-id-short">${parseInt(w.tasks_failed || 0).toLocaleString()}</td>
            <td class="task-id-short">${hb}</td>
          </tr>`;
        }).join('');
  } catch (e) {}
}

async function loadDLQ() {
  try {
    const res = await fetch(`${API}/api/v1/dlq`);
    if (!res.ok) return;
    const entries = await res.json();

    const empty = document.getElementById('dlqEmpty');
    const table = document.getElementById('dlqTable');
    const tbody = document.getElementById('dlqBody');

    if (entries.length === 0) {
      empty.style.display = 'block';
      table.style.display = 'none';
    } else {
      empty.style.display = 'none';
      table.style.display = 'table';
      tbody.innerHTML = entries.map(e => {
        const dt = e.dead_lettered_at
          ? new Date(e.dead_lettered_at).toLocaleString('en-IN')
          : '—';
        const err = (e.error_message || '').substring(0, 60) + (e.error_message?.length > 60 ? '…' : '');
        return `<tr>
          <td class="task-name">${e.task_name}</td>
          <td class="task-id-short" title="${e.error_message || ''}">${err}</td>
          <td class="task-id-short">${e.retry_count}</td>
          <td class="task-id-short">${e.original_queue}</td>
          <td class="task-id-short">${dt}</td>
          <td><button class="btn-replay" onclick="replayEntry('${e.id}')">↺ Replay</button></td>
        </tr>`;
      }).join('');
    }
  } catch (e) {}
}

async function replayEntry(entryId) {
  try {
    const res = await fetch(`${API}/api/v1/dlq/${entryId}/replay`, { method: 'POST' });
    if (res.ok) {
      await loadDLQ();
    }
  } catch (e) {}
}

async function replayAll() {
  try {
    const res = await fetch(`${API}/api/v1/dlq/replay-all`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      alert(`Replayed ${data.replayed_count} tasks`);
      await loadDLQ();
    }
  } catch (e) {}
}

// ===== TASK SUBMIT =====
async function submitTask(event) {
  event.preventDefault();
  const resultEl = document.getElementById('submitResult');

  const body = {
    task_name: document.getElementById('taskName').value.trim(),
    queue: document.getElementById('taskQueue').value.trim(),
    priority: parseInt(document.getElementById('taskPriority').value),
    args: JSON.parse(document.getElementById('taskArgs').value || '[]'),
    kwargs: JSON.parse(document.getElementById('taskKwargs').value || '{}'),
  };

  try {
    const res = await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      resultEl.className = 'submit-result success';
      resultEl.textContent = `✓ Task submitted: ${data.task_id}`;
    } else {
      resultEl.className = 'submit-result error';
      resultEl.textContent = `✗ Error: ${JSON.stringify(data)}`;
    }
    setTimeout(() => { resultEl.style.display = 'none'; }, 4000);
  } catch (e) {
    resultEl.className = 'submit-result error';
    resultEl.textContent = `✗ Network error: ${e.message}`;
  }
}

// ===== HELPERS =====
function formatUptime(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds/60)}m ${seconds%60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

const animCounters = {};
function animateNumber(id, target) {
  const el = document.getElementById(id);
  const current = animCounters[id] || 0;
  if (current === target) return;
  const step = Math.ceil((target - current) / 8);
  animCounters[id] = Math.min(current + step, target);
  el.textContent = animCounters[id].toLocaleString();
  if (animCounters[id] < target) {
    requestAnimationFrame(() => animateNumber(id, target));
  }
}

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  connectWebSocket();

  // Poll metrics every 2 seconds
  fetchMetrics();
  setInterval(fetchMetrics, 2000);

  // Poll workers every 5 seconds
  loadWorkers();
  setInterval(loadWorkers, 5000);

  // Poll DLQ every 10 seconds
  loadDLQ();
  setInterval(loadDLQ, 10000);
});
