/* ==========================================================================
   CelerLite CRM — Salesforce Lightning Enterprise Platform Controller
   Full CRM State Management, Leads, Kanban Pipeline, Accounts, Contacts,
   Activity Timelines, AI Automations & CelerLite Engine Telemetry
   ========================================================================== */

'use strict';

const API = location.host ? '' : 'http://localhost:8000';
let currentTab = 'crm-home';
let currentSearch = '';
let pipelineChart = null;
let dealDonutChart = null;

// Telemetry & Cache
let crmStats = {};
let leadsList = [];
let dealsList = [];
let accountsList = [];
let contactsList = [];
let activitiesList = [];
let engineTasksList = [];

// ==========================================================================
// INITIALIZATION
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
  setupKeyboardShortcuts();
  initDefaultCloseDate();
  loadAllCRMData();

  // Auto-refresh CRM stats every 5 seconds
  setInterval(loadCRMStats, 5000);
});

function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // ESC closes drawer or any open modal
    if (e.key === 'Escape') {
      closeDetailDrawer();
      document.querySelectorAll('.slds-modal-backdrop.open').forEach(m => m.classList.remove('open'));
    }
    // Ctrl+K or '/' focuses search
    if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) &&
        document.activeElement.tagName !== 'INPUT' &&
        document.activeElement.tagName !== 'TEXTAREA') {
      e.preventDefault();
      const search = document.getElementById('globalSearchInput');
      if (search) search.focus();
    }
  });
}

function initDefaultCloseDate() {
  const closeDateInput = document.getElementById('dealCloseDate');
  if (closeDateInput) {
    const d = new Date();
    d.setDate(d.getDate() + 30);
    closeDateInput.value = d.toISOString().split('T')[0];
  }
}

// ==========================================================================
// TAB SWITCHING
// ==========================================================================

function switchTab(tabId) {
  currentTab = tabId;

  // Update Nav Items
  document.querySelectorAll('.slds-nav-item').forEach(item => {
    item.classList.toggle('active', item.getAttribute('data-tab') === tabId);
  });

  // Update Views
  document.querySelectorAll('.tab-view').forEach(view => {
    view.classList.toggle('active', view.id === `tab-${tabId}`);
  });

  // Re-render corresponding data
  if (tabId === 'crm-home') {
    renderHomeView();
  } else if (tabId === 'leads') {
    renderLeadsTable();
  } else if (tabId === 'deals') {
    renderKanbanBoard();
  } else if (tabId === 'accounts') {
    renderAccountsTable();
  } else if (tabId === 'contacts') {
    renderContactsTable();
  } else if (tabId === 'activities') {
    renderActivitiesTimeline();
  } else if (tabId === 'engine') {
    loadEngineTasks();
  }
}

// ==========================================================================
// DATA FETCHING & STATE MANAGEMENT
// ==========================================================================

async function loadAllCRMData() {
  await Promise.all([
    loadCRMStats(),
    loadLeads(),
    loadDeals(),
    loadAccounts(),
    loadContacts(),
    loadActivities(),
    loadEngineTasks(),
  ]);
}

async function refreshCRMData() {
  await loadAllCRMData();
  showToast('CRM data refreshed from database.', 'success');
}

async function loadCRMStats() {
  try {
    const res = await fetch(`${API}/api/v1/crm/stats`);
    if (!res.ok) return;
    crmStats = await res.json();
    updateKPICards();
    if (currentTab === 'crm-home') {
      initOrUpdateCharts();
    }
  } catch (err) {
    console.warn('Failed to load CRM stats', err);
  }
}

async function loadLeads() {
  try {
    const res = await fetch(`${API}/api/v1/crm/leads?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    leadsList = data.leads || [];
    const countEl = document.getElementById('navLeadsCount');
    if (countEl) countEl.textContent = leadsList.length;
    if (currentTab === 'leads') renderLeadsTable();
  } catch (err) {
    console.warn('Failed to load leads', err);
  }
}

async function loadDeals() {
  try {
    const res = await fetch(`${API}/api/v1/crm/deals?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    dealsList = data.deals || [];
    const countEl = document.getElementById('navDealsCount');
    if (countEl) countEl.textContent = dealsList.length;
    if (currentTab === 'deals') renderKanbanBoard();
    if (currentTab === 'crm-home') renderHomeTopDeals();
  } catch (err) {
    console.warn('Failed to load deals', err);
  }
}

async function loadAccounts() {
  try {
    const res = await fetch(`${API}/api/v1/crm/accounts?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    accountsList = data.accounts || [];
    if (currentTab === 'accounts') renderAccountsTable();
  } catch (err) {
    console.warn('Failed to load accounts', err);
  }
}

async function loadContacts() {
  try {
    const res = await fetch(`${API}/api/v1/crm/contacts?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    contactsList = data.contacts || [];
    if (currentTab === 'contacts') renderContactsTable();
  } catch (err) {
    console.warn('Failed to load contacts', err);
  }
}

async function loadActivities() {
  try {
    const res = await fetch(`${API}/api/v1/crm/activities?limit=100`);
    if (!res.ok) return;
    const data = await res.json();
    activitiesList = data.activities || [];
    if (currentTab === 'activities') renderActivitiesTimeline();
  } catch (err) {
    console.warn('Failed to load activities', err);
  }
}

async function loadEngineTasks() {
  try {
    const res = await fetch(`${API}/api/v1/tasks?limit=50`);
    if (!res.ok) return;
    const data = await res.json();
    engineTasksList = Array.isArray(data) ? data : (data.tasks || []);
    
    const countEl = document.getElementById('engineTotalTasks');
    if (countEl) countEl.textContent = engineTasksList.length;

    const tbody = document.getElementById('engineTasksTableBody');
    if (!tbody) return;

    if (engineTasksList.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No background tasks enqueued yet.</td></tr>';
      return;
    }

    tbody.innerHTML = engineTasksList.slice(0, 15).map(t => `
      <tr>
        <td class="font-mono">${(t.id || '').substring(0, 8)}...</td>
        <td class="font-semibold text-brand">${t.task_name}</td>
        <td><span class="badge-neutral">${t.queue || 'default'}</span></td>
        <td>P${t.priority ?? 1}</td>
        <td><span class="badge-status status-${(t.status || 'PENDING').toLowerCase()}">${t.status}</span></td>
        <td class="text-muted">${t.worker_id || 'unassigned'}</td>
        <td class="text-muted text-xs">${formatDateTime(t.created_at)}</td>
      </tr>
    `).join('');
  } catch (err) {
    console.warn('Failed to load engine tasks', err);
  }
}

// ==========================================================================
// RENDERING VIEWS
// ==========================================================================

function updateKPICards() {
  const pVal = document.getElementById('kpiPipelineValue');
  const cVal = document.getElementById('kpiClosedWonValue');
  const wRate = document.getElementById('kpiWinRate');
  const tLeads = document.getElementById('kpiTotalLeads');
  const tAccs = document.getElementById('kpiTotalAccounts');

  if (pVal) pVal.textContent = `$${(crmStats.total_pipeline || 0).toLocaleString()}`;
  if (cVal) cVal.textContent = `$${(crmStats.closed_won || 0).toLocaleString()}`;
  if (wRate) wRate.textContent = `${crmStats.win_rate_percent || 0}%`;
  if (tLeads) tLeads.textContent = crmStats.total_leads || leadsList.length;
  if (tAccs) tAccs.textContent = crmStats.total_accounts || accountsList.length;
}

function renderHomeView() {
  updateKPICards();
  initOrUpdateCharts();
  renderHomeTopDeals();
}

function renderHomeTopDeals() {
  const tbody = document.getElementById('homeTopDealsTableBody');
  if (!tbody) return;

  const topDeals = [...dealsList].sort((a, b) => (b.amount || 0) - (a.amount || 0)).slice(0, 5);

  if (topDeals.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted">No opportunities found.</td></tr>';
    return;
  }

  tbody.innerHTML = topDeals.map(d => `
    <tr>
      <td class="font-semibold text-brand cursor-pointer" onclick="openDealDetailDrawer('${d.id}')">${d.name}</td>
      <td>${d.account_name}</td>
      <td><span class="badge-status ${d.stage === 'Closed Won' ? 'status-closed-won' : 'status-working'}">${d.stage}</span></td>
      <td class="font-bold">$${(d.amount || 0).toLocaleString()}</td>
      <td><span class="kanban-card-prob">${d.probability}%</span></td>
      <td class="text-muted">${d.close_date || ''}</td>
      <td>${d.owner || 'Alex Chen'}</td>
      <td>
        <button class="slds-btn slds-btn-neutral slds-btn-sm" onclick="openDealDetailDrawer('${d.id}')">View</button>
      </td>
    </tr>
  `).join('');
}

function initOrUpdateCharts() {
  const stageCanvas = document.getElementById('pipelineStageChart');
  const donutCanvas = document.getElementById('dealDonutChart');

  if (!stageCanvas || !donutCanvas) return;

  const stages = [
    'Prospecting',
    'Qualification',
    'Needs Analysis',
    'Proposal/Price Quote',
    'Negotiation',
    'Closed Won',
  ];

  const stageValues = stages.map(st => {
    return dealsList.filter(d => d.stage === st).reduce((sum, d) => sum + (d.amount || 0), 0);
  });

  const stageCounts = stages.map(st => {
    return dealsList.filter(d => d.stage === st).length;
  });

  // 1. Stage Funnel Horizontal Bar Chart
  if (pipelineChart) {
    pipelineChart.data.datasets[0].data = stageValues;
    pipelineChart.update();
  } else {
    pipelineChart = new Chart(stageCanvas, {
      type: 'bar',
      data: {
        labels: ['Prospecting', 'Qual.', 'Needs Analysis', 'Proposal', 'Negotiation', 'Won'],
        datasets: [{
          label: 'Pipeline ($)',
          data: stageValues,
          backgroundColor: ['#93c5fd', '#60a5fa', '#3b82f6', '#2563eb', '#1d4ed8', '#16a34a'],
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => `Value: $${ctx.raw.toLocaleString()}`
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: (v) => `$${(v/1000)}k`
            }
          }
        }
      }
    });
  }

  // 2. Deal Count Donut Chart
  if (dealDonutChart) {
    dealDonutChart.data.datasets[0].data = stageCounts;
    dealDonutChart.update();
  } else {
    dealDonutChart = new Chart(donutCanvas, {
      type: 'doughnut',
      data: {
        labels: ['Prospecting', 'Qualification', 'Needs Analysis', 'Proposal', 'Negotiation', 'Won'],
        datasets: [{
          data: stageCounts,
          backgroundColor: ['#93c5fd', '#60a5fa', '#3b82f6', '#2563eb', '#1d4ed8', '#16a34a'],
          borderWidth: 2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'right',
            labels: { boxWidth: 12, font: { size: 11 } }
          }
        }
      }
    });
  }
}

// ==========================================================================
// LEADS TABLE
// ==========================================================================

function filterLeadsByStatus(status) {
  renderLeadsTable(status);
}

function renderLeadsTable(filterStatus = '') {
  const tbody = document.getElementById('leadsTableBody');
  if (!tbody) return;

  let filtered = leadsList;
  if (filterStatus) {
    filtered = filtered.filter(l => l.status === filterStatus);
  }
  if (currentSearch) {
    const q = currentSearch.toLowerCase();
    filtered = filtered.filter(l =>
      (l.first_name || '').toLowerCase().includes(q) ||
      (l.last_name || '').toLowerCase().includes(q) ||
      (l.company || '').toLowerCase().includes(q) ||
      (l.email || '').toLowerCase().includes(q)
    );
  }

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="text-center py-4 text-muted">No matching leads found.</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map(l => {
    const scoreClass = l.score >= 80 ? 'score-high' : (l.score >= 65 ? 'score-mid' : 'score-low');
    const statusClass = `status-${(l.status || 'new').toLowerCase()}`;

    return `
      <tr>
        <td class="font-semibold text-brand cursor-pointer" onclick="openLeadDetailDrawer('${l.id}')">
          ${l.first_name} ${l.last_name}
        </td>
        <td class="font-medium">${l.company}</td>
        <td class="text-muted">${l.title || '—'}</td>
        <td><span class="badge-status ${statusClass}">${l.status}</span></td>
        <td><span class="score-badge ${scoreClass}">${l.score}</span></td>
        <td><span class="badge-neutral">${l.lead_source}</span></td>
        <td>${l.annual_revenue ? '$' + Number(l.annual_revenue).toLocaleString() : '—'}</td>
        <td class="text-muted">${l.owner}</td>
        <td>
          <div class="slds-action-btn-group">
            <button class="slds-btn slds-btn-neutral slds-btn-sm" onclick="convertLead('${l.id}')" title="Convert to Deal">Convert</button>
            <button class="slds-btn slds-btn-neutral slds-btn-sm text-red" onclick="deleteLead('${l.id}')" title="Delete">✕</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// ==========================================================================
// OPPORTUNITIES KANBAN PIPELINE
// ==========================================================================

const KANBAN_STAGES = [
  'Prospecting',
  'Qualification',
  'Needs Analysis',
  'Proposal/Price Quote',
  'Negotiation',
  'Closed Won',
];

function renderKanbanBoard() {
  KANBAN_STAGES.forEach(stage => {
    const stageKey = stage.replace(/[^a-zA-Z]/g, '');
    const container = document.getElementById(`cards-${stageKey}`);
    const countEl = document.getElementById(`count-${stageKey}`);
    const sumEl = document.getElementById(`sum-${stageKey}`);

    if (!container) return;

    const dealsInStage = dealsList.filter(d => d.stage === stage);
    const sumAmount = dealsInStage.reduce((sum, d) => sum + (d.amount || 0), 0);

    if (countEl) countEl.textContent = `${dealsInStage.length} Deals`;
    if (sumEl) sumEl.textContent = `$${sumAmount.toLocaleString()}`;

    if (dealsInStage.length === 0) {
      container.innerHTML = '<div class="text-muted text-xs text-center py-4">No opportunities</div>';
      return;
    }

    container.innerHTML = dealsInStage.map(d => `
      <div class="kanban-card" onclick="openDealDetailDrawer('${d.id}')">
        <div class="kanban-card-title">${d.name}</div>
        <div class="kanban-card-account">${d.account_name}</div>
        <div class="kanban-card-meta">
          <span class="kanban-card-amount">$${Number(d.amount).toLocaleString()}</span>
          <span class="kanban-card-prob">${d.probability}% prob</span>
        </div>
        <div class="kanban-card-footer">
          <span>📅 ${d.close_date}</span>
          <span>👤 ${d.owner}</span>
        </div>
      </div>
    `).join('');
  });
}

// ==========================================================================
// ACCOUNTS & CONTACTS TABLES
// ==========================================================================

function renderAccountsTable() {
  const tbody = document.getElementById('accountsTableBody');
  if (!tbody) return;

  if (accountsList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-4 text-muted">No accounts registered yet.</td></tr>';
    return;
  }

  tbody.innerHTML = accountsList.map(a => `
    <tr>
      <td class="font-semibold text-brand">${a.name}</td>
      <td><span class="badge-neutral">${a.industry}</span></td>
      <td><span class="badge-status status-new">${a.tier}</span></td>
      <td class="font-bold">$${Number(a.annual_revenue || 0).toLocaleString()}</td>
      <td>${a.employees} employees</td>
      <td>${a.billing_city ? `${a.billing_city}, ${a.billing_country || ''}` : '—'}</td>
      <td><a href="${a.website || '#'}" target="_blank" class="text-brand">${a.website || '—'}</a></td>
      <td class="text-muted">${a.phone || '—'}</td>
    </tr>
  `).join('');
}

function renderContactsTable() {
  const tbody = document.getElementById('contactsTableBody');
  if (!tbody) return;

  if (contactsList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">No contacts registered yet.</td></tr>';
    return;
  }

  tbody.innerHTML = contactsList.map(c => `
    <tr>
      <td class="font-semibold text-brand">${c.first_name} ${c.last_name}</td>
      <td class="font-medium">${c.account_name || '—'}</td>
      <td>${c.title || '—'}</td>
      <td><span class="badge-neutral">${c.department || 'General'}</span></td>
      <td><a href="mailto:${c.email}" class="text-brand">${c.email}</a></td>
      <td class="text-muted">${c.phone || '—'}</td>
      <td>${c.is_primary ? '<span class="badge-status status-qualified">Primary</span>' : '—'}</td>
    </tr>
  `).join('');
}

// ==========================================================================
// ACTIVITY TIMELINE
// ==========================================================================

function renderActivitiesTimeline() {
  const container = document.getElementById('activityTimelineContainer');
  if (!container) return;

  if (activitiesList.length === 0) {
    container.innerHTML = '<div class="text-muted text-center py-6">No recorded activity history. Log a call or task above.</div>';
    return;
  }

  container.innerHTML = activitiesList.map(a => {
    const iconClass = `icon-${(a.type || 'task').toLowerCase()}`;
    const iconEmoji = a.type === 'Call' ? '📞' : (a.type === 'Meeting' ? '🤝' : (a.type === 'Email' ? '✉️' : '📋'));

    return `
      <div class="timeline-item">
        <div class="timeline-icon ${iconClass}">${iconEmoji}</div>
        <div class="timeline-content">
          <div class="d-flex justify-between align-center">
            <div class="timeline-subject">${a.subject}</div>
            <button class="slds-btn slds-btn-neutral slds-btn-sm" onclick="toggleActivityStatus('${a.id}')">
              ${a.status === 'Completed' ? '✓ Completed' : 'Mark Done'}
            </button>
          </div>
          <div class="timeline-meta">
            ${a.type} • Related to <strong>${a.entity_name || 'Account'}</strong> • Due: ${a.due_date || 'None'}
          </div>
          ${a.description ? `<div class="timeline-desc">${a.description}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

async function toggleActivityStatus(actId) {
  try {
    const res = await fetch(`${API}/api/v1/crm/activities/${actId}/toggle`, { method: 'PUT' });
    if (res.ok) {
      showToast('Activity status updated', 'success');
      loadActivities();
    }
  } catch (err) {
    showToast('Failed to update activity', 'error');
  }
}

// ==========================================================================
// RECORD DETAIL DRAWER (OPPORTUNITY & LEAD)
// ==========================================================================

function openDealDetailDrawer(dealId) {
  const deal = dealsList.find(d => d.id === dealId);
  if (!deal) return;

  const overline = document.getElementById('drawerOverline');
  const title = document.getElementById('drawerTitle');
  const body = document.getElementById('drawerBody');
  const footer = document.getElementById('drawerFooter');
  const path = document.getElementById('drawerSalesPath');

  if (overline) overline.textContent = `Opportunity • ${deal.account_name}`;
  if (title) title.textContent = deal.name;

  // Highlight sales path
  if (path) {
    path.style.display = 'flex';
    const steps = path.querySelectorAll('.path-step');
    let past = true;
    steps.forEach(s => {
      const stepName = s.getAttribute('data-step');
      s.className = 'path-step';
      if (stepName === deal.stage) {
        s.classList.add('active');
        past = false;
      } else if (past) {
        s.classList.add('completed');
      }
      s.onclick = () => advanceDealStage(deal.id, stepName);
    });
  }

  if (body) {
    body.innerHTML = `
      <div class="drawer-field-grid">
        <div class="drawer-field">
          <label>Deal Amount</label>
          <div class="drawer-val-bold">$${Number(deal.amount).toLocaleString()}</div>
        </div>
        <div class="drawer-field">
          <label>Win Probability</label>
          <div class="drawer-val">${deal.probability}%</div>
        </div>
        <div class="drawer-field">
          <label>Target Close Date</label>
          <div class="drawer-val">${deal.close_date}</div>
        </div>
        <div class="drawer-field">
          <label>Opportunity Owner</label>
          <div class="drawer-val">${deal.owner}</div>
        </div>
        <div class="drawer-field">
          <label>Deal Type</label>
          <div class="drawer-val">${deal.deal_type}</div>
        </div>
        <div class="drawer-field">
          <label>Next Step</label>
          <div class="drawer-val text-brand">${deal.next_step || 'None assigned'}</div>
        </div>
      </div>
      <div class="mt-4">
        <h4 class="font-bold text-sm mb-2">Stage Progression</h4>
        <p class="text-xs text-muted">Click any chevron stage above to advance or update this opportunity's status in the live pipeline.</p>
      </div>
    `;
  }

  if (footer) {
    footer.innerHTML = `
      <button class="slds-btn slds-btn-neutral" onclick="closeDetailDrawer()">Close</button>
      <button class="slds-btn slds-btn-brand text-red" onclick="deleteDeal('${deal.id}')">Delete Opportunity</button>
    `;
  }

  document.getElementById('detailDrawerBackdrop')?.classList.add('open');
  document.getElementById('recordDrawer')?.classList.add('open');
}

function openLeadDetailDrawer(leadId) {
  const lead = leadsList.find(l => l.id === leadId);
  if (!lead) return;

  const overline = document.getElementById('drawerOverline');
  const title = document.getElementById('drawerTitle');
  const body = document.getElementById('drawerBody');
  const footer = document.getElementById('drawerFooter');
  const path = document.getElementById('drawerSalesPath');

  if (overline) overline.textContent = `Lead Profile • ${lead.company}`;
  if (title) title.textContent = `${lead.first_name} ${lead.last_name}`;
  if (path) path.style.display = 'none';

  if (body) {
    body.innerHTML = `
      <div class="drawer-field-grid">
        <div class="drawer-field">
          <label>Company</label>
          <div class="drawer-val-bold">${lead.company}</div>
        </div>
        <div class="drawer-field">
          <label>Lead Score</label>
          <div class="drawer-val"><span class="score-badge score-high">${lead.score}</span></div>
        </div>
        <div class="drawer-field">
          <label>Job Title</label>
          <div class="drawer-val">${lead.title || '—'}</div>
        </div>
        <div class="drawer-field">
          <label>Email</label>
          <div class="drawer-val"><a href="mailto:${lead.email}" class="text-brand">${lead.email}</a></div>
        </div>
        <div class="drawer-field">
          <label>Phone</label>
          <div class="drawer-val">${lead.phone || '—'}</div>
        </div>
        <div class="drawer-field">
          <label>Lead Source</label>
          <div class="drawer-val">${lead.lead_source}</div>
        </div>
      </div>
      <div class="mt-4">
        <label class="font-bold text-xs">Discovery Notes</label>
        <div class="timeline-desc mt-1">${lead.notes || 'No notes added.'}</div>
      </div>
    `;
  }

  if (footer) {
    footer.innerHTML = `
      <button class="slds-btn slds-btn-neutral" onclick="closeDetailDrawer()">Close</button>
      <button class="slds-btn slds-btn-brand" onclick="convertLead('${lead.id}')">Convert to Opportunity</button>
    `;
  }

  document.getElementById('detailDrawerBackdrop')?.classList.add('open');
  document.getElementById('recordDrawer')?.classList.add('open');
}

function closeDetailDrawer() {
  document.getElementById('detailDrawerBackdrop')?.classList.remove('open');
  document.getElementById('recordDrawer')?.classList.remove('open');
}

async function advanceDealStage(dealId, newStage) {
  const probMap = {
    'Prospecting': 20,
    'Qualification': 40,
    'Needs Analysis': 50,
    'Proposal/Price Quote': 75,
    'Negotiation': 90,
    'Closed Won': 100,
  };
  try {
    const res = await fetch(`${API}/api/v1/crm/deals/${dealId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage: newStage, probability: probMap[newStage] || 50 }),
    });
    if (res.ok) {
      showToast(`Opportunity advanced to ${newStage}`, 'success');
      await loadDeals();
      await loadCRMStats();
      openDealDetailDrawer(dealId);
    }
  } catch (err) {
    showToast('Failed to update deal stage', 'error');
  }
}

// ==========================================================================
// ACTIONS & MODAL HANDLERS
// ==========================================================================

function openModal(modalId) {
  document.getElementById(modalId)?.classList.add('open');
}

function closeModal(modalId) {
  document.getElementById(modalId)?.classList.remove('open');
}

function openNewLeadModal() { openModal('modalNewLead'); }
function openNewDealModal() { openModal('modalNewDeal'); }
function openNewAccountModal() { openModal('modalNewAccount'); }
function openNewContactModal() { openModal('modalNewContact'); }
function openLogActivityModal() { openModal('modalLogActivity'); }
function openAutomationModal() { openModal('modalAutomation'); }
function openStartTaskModal() { openModal('modalStartTask'); }

function updateDealProbabilityPreset(stage) {
  const probMap = {
    'Prospecting': 20,
    'Qualification': 40,
    'Needs Analysis': 50,
    'Proposal/Price Quote': 75,
    'Negotiation': 90,
    'Closed Won': 100,
  };
  const dealProb = probMap[stage] || 20;
}

async function handleCreateLead(e) {
  e.preventDefault();
  const payload = {
    first_name: document.getElementById('leadFirstName').value,
    last_name: document.getElementById('leadLastName').value,
    company: document.getElementById('leadCompany').value,
    title: document.getElementById('leadTitle').value,
    email: document.getElementById('leadEmail').value,
    phone: document.getElementById('leadPhone').value,
    status: document.getElementById('leadStatus').value,
    lead_source: document.getElementById('leadSource').value,
    annual_revenue: document.getElementById('leadRevenue').value ? parseInt(document.getElementById('leadRevenue').value) : null,
    score: parseInt(document.getElementById('leadScore').value || '70'),
    notes: document.getElementById('leadNotes').value,
  };

  try {
    const res = await fetch(`${API}/api/v1/crm/leads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Lead created successfully', 'success');
      closeModal('modalNewLead');
      document.getElementById('formNewLead').reset();
      await loadLeads();
      await loadCRMStats();
    }
  } catch (err) {
    showToast('Failed to create lead', 'error');
  }
}

async function handleCreateDeal(e) {
  e.preventDefault();
  const stage = document.getElementById('dealStage').value;
  const probMap = {
    'Prospecting': 20,
    'Qualification': 40,
    'Needs Analysis': 50,
    'Proposal/Price Quote': 75,
    'Negotiation': 90,
    'Closed Won': 100,
  };

  const payload = {
    name: document.getElementById('dealName').value,
    account_name: document.getElementById('dealAccountName').value,
    stage: stage,
    amount: parseInt(document.getElementById('dealAmount').value),
    probability: probMap[stage] || 50,
    close_date: document.getElementById('dealCloseDate').value,
    deal_type: document.getElementById('dealType').value,
    owner: document.getElementById('dealOwner').value,
    next_step: document.getElementById('dealNextStep').value,
  };

  try {
    const res = await fetch(`${API}/api/v1/crm/deals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Opportunity created', 'success');
      closeModal('modalNewDeal');
      document.getElementById('formNewDeal').reset();
      await loadDeals();
      await loadCRMStats();
    }
  } catch (err) {
    showToast('Failed to create opportunity', 'error');
  }
}

async function handleCreateAccount(e) {
  e.preventDefault();
  const payload = {
    name: document.getElementById('accName').value,
    industry: document.getElementById('accIndustry').value,
    tier: document.getElementById('accTier').value,
    annual_revenue: parseInt(document.getElementById('accRevenue').value || '1000000'),
    employees: parseInt(document.getElementById('accEmployees').value || '50'),
    billing_city: document.getElementById('accCity').value,
    website: document.getElementById('accWebsite').value,
  };

  try {
    const res = await fetch(`${API}/api/v1/crm/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Corporate account saved', 'success');
      closeModal('modalNewAccount');
      document.getElementById('formNewAccount').reset();
      await loadAccounts();
      await loadCRMStats();
    }
  } catch (err) {
    showToast('Failed to save account', 'error');
  }
}

async function handleCreateContact(e) {
  e.preventDefault();
  const payload = {
    first_name: document.getElementById('cntFirstName').value,
    last_name: document.getElementById('cntLastName').value,
    account_name: document.getElementById('cntAccountName').value,
    title: document.getElementById('cntTitle').value,
    email: document.getElementById('cntEmail').value,
    phone: document.getElementById('cntPhone').value,
  };

  try {
    const res = await fetch(`${API}/api/v1/crm/contacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Contact created', 'success');
      closeModal('modalNewContact');
      document.getElementById('formNewContact').reset();
      await loadContacts();
    }
  } catch (err) {
    showToast('Failed to create contact', 'error');
  }
}

async function handleCreateActivity(e) {
  e.preventDefault();
  const payload = {
    type: document.getElementById('actType').value,
    entity_type: 'general',
    entity_id: 'gen-001',
    entity_name: document.getElementById('actEntityName').value,
    subject: document.getElementById('actSubject').value,
    due_date: document.getElementById('actDueDate').value,
    description: document.getElementById('actDescription').value,
  };

  try {
    const res = await fetch(`${API}/api/v1/crm/activities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Activity logged', 'success');
      closeModal('modalLogActivity');
      document.getElementById('formLogActivity').reset();
      await loadActivities();
    }
  } catch (err) {
    showToast('Failed to log activity', 'error');
  }
}

async function convertLead(leadId) {
  try {
    const res = await fetch(`${API}/api/v1/crm/leads/${leadId}/convert`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      showToast(`Lead converted to Opportunity: ${data.deal.name}`, 'success');
      closeDetailDrawer();
      await loadLeads();
      await loadDeals();
      await loadCRMStats();
      switchTab('deals');
    }
  } catch (err) {
    showToast('Failed to convert lead', 'error');
  }
}

async function deleteLead(leadId) {
  if (!confirm('Are you sure you want to remove this lead?')) return;
  try {
    const res = await fetch(`${API}/api/v1/crm/leads/${leadId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Lead deleted', 'success');
      closeDetailDrawer();
      await loadLeads();
      await loadCRMStats();
    }
  } catch (err) {
    showToast('Failed to delete lead', 'error');
  }
}

async function deleteDeal(dealId) {
  if (!confirm('Are you sure you want to delete this opportunity?')) return;
  try {
    const res = await fetch(`${API}/api/v1/crm/deals/${dealId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Opportunity removed', 'success');
      closeDetailDrawer();
      await loadDeals();
      await loadCRMStats();
    }
  } catch (err) {
    showToast('Failed to delete deal', 'error');
  }
}

async function triggerAutomationAction(actionName) {
  try {
    const res = await fetch(`${API}/api/v1/crm/automate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: actionName }),
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`CelerLite Job Queued: ${data.task_name} (ID: ${data.task_id.substring(0,8)})`, 'success');
      closeModal('modalAutomation');
      await loadEngineTasks();
    }
  } catch (err) {
    showToast('Failed to trigger background automation', 'error');
  }
}

async function handleStartTask(e) {
  e.preventDefault();
  const payload = {
    task_name: document.getElementById('modalTaskName').value,
    queue: document.getElementById('modalTaskQueue').value,
    priority: parseInt(document.getElementById('modalTaskPriority').value),
    args: ['manual_trigger'],
  };

  try {
    const res = await fetch(`${API}/api/v1/tasks/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const data = await res.json();
      showToast(`Task enqueued: ${data.task_id.substring(0,8)}`, 'success');
      closeModal('modalStartTask');
      await loadEngineTasks();
    }
  } catch (err) {
    showToast('Failed to submit task', 'error');
  }
}

function handleGlobalSearch(val) {
  currentSearch = val;
  if (currentTab === 'leads') {
    renderLeadsTable();
  } else if (currentTab === 'deals') {
    renderKanbanBoard();
  }
}

// ==========================================================================
// TOAST NOTIFICATIONS & HELPERS
// ==========================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `slds-toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function formatDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return isoString;
  }
}
