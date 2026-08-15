// ─── DASHBOARD ──────────────────────────────────────
async function loadRouterStatus() {
  const data = await api('/api/devices/router-status');
  if (!data) return;
  const tbody = document.getElementById('routerClientsTable');
  const clients = data.clients ? Object.values(data.clients) : [];
  if (!clients.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">No clients connected.</td></tr>';
    return;
  }
  tbody.innerHTML = clients.map(c => `
    <tr>
      <td class="mono">${c.mac ?? '—'}</td>
      <td class="mono">${c.ip ?? '—'}</td>
      <td><span class="badge ${c.state === 'Authenticated' ? 'badge-success' : 'badge-warning'}">${c.state ?? '—'}</span></td>
      <td>${((c.downloaded ?? 0) / 1024).toFixed(1)} MB</td>
      <td>${((c.uploaded ?? 0) / 1024).toFixed(1)} MB</td>
      <td class="mono" style="font-size:11px">${c.token ?? '—'}</td>
      <td>
        ${c.state === 'Authenticated'
          ? `<button class="action-btn danger" onclick="deauthClient('${c.mac}')">Deauth</button>`
          : `<button class="action-btn" onclick="grantAccess('${c.mac}')">Auth</button>`
        }
      </td>
    </tr>`).join('');
}

setInterval(() => {
  if (document.getElementById('page-dashboard')?.classList.contains('active')) {
    loadRouterStatus();
    loadDashboard();
  }
  if (document.getElementById('page-sessions')?.classList.contains('active')) {
    loadSessions();
  }
}, 30000);

async function loadDashboard() {
  loadRouterStatus();
  const data = await api('/api/reports/dashboard');
  if (!data) return;
  document.getElementById('statActive').textContent = data.active_sessions ?? 0;
  document.getElementById('statToday').textContent = 'KES ' + (data.revenue?.today_kes ?? 0).toLocaleString();
  document.getElementById('statMonth').textContent = 'KES ' + (data.revenue?.month_kes ?? 0).toLocaleString();
  document.getElementById('statAlerts').textContent = data.security_alerts?.length ?? 0;
  document.getElementById('alertBadge').textContent = data.security_alerts?.length ?? 0;

  const tbody = document.getElementById('recentPaymentsTable');
  if (!data.recent_payments?.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--muted)">No payments yet.</td></tr>';
  } else {
    tbody.innerHTML = data.recent_payments.map(p => `
      <tr>
        <td class="mono">${p.phone}</td>
        <td>${p.packages?.name ?? '—'}</td>
        <td style="color:var(--success);font-weight:600">KES ${p.amount_kes}</td>
        <td>${statusBadge(p.status)}</td>
      </tr>`).join('');
  }

  const alertsEl = document.getElementById('alertsList');
  if (data.security_alerts?.length) {
    alertsEl.innerHTML = data.security_alerts.slice(0,5).map(a => `
      <div class="alert-item">
        <div class="alert-dot ${a.severity ?? 'info'}"></div>
        <div class="alert-body">
          <div class="alert-title">${a.description}</div>
          <div class="alert-meta">${a.source_ip ?? ''} · ${timeAgo(a.created_at)}</div>
        </div>
      </div>`).join('');
  } else {
    alertsEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--muted);font-size:13px">No active alerts.</div>';
  }

  const pkgEl = document.getElementById('pkgPopularity');
  if (data.package_popularity?.length) {
    pkgEl.innerHTML = data.package_popularity.map(p => `
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:14px">
        <div style="font-size:12px;color:var(--muted);margin-bottom:4px">${p.name}</div>
        <div style="font-size:22px;font-weight:700;font-family:var(--font-head);color:var(--accent)">${p.sales}</div>
        <div style="font-size:11px;color:var(--muted)">sales</div>
      </div>`).join('');
  }
}

// ─── SESSIONS ───────────────────────────────────────
async function loadSessions() {
  const data = await api('/api/sessions/active');
  if (!data) return;
  document.getElementById('sessionsCount').textContent = data.length + ' active';
  const tbody = document.getElementById('sessionsTable');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">No active sessions.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(s => `
    <tr>
      <td class="mono">${s.mac_address}</td>
      <td class="mono">${s.ip_address ?? '—'}</td>
      <td>${s.full_name ?? s.phone ?? '—'}</td>
      <td>${s.package_name ?? '—'}</td>
      <td class="mono" style="font-size:12px">${new Date(s.expires_at).toLocaleString()}</td>
      <td><button class="action-btn danger" onclick="terminateSession('${s.session_id}')">Terminate</button></td>
    </tr>`).join('');
}

async function terminateSession(id) {
  if (!confirm('Terminate this session?')) return;
  await api(`/api/sessions/${id}/terminate`, { method: 'POST' });
  loadSessions();
}

// ─── USERS ──────────────────────────────────────────
async function loadUsers() {
  const data = await api('/api/users/');
  if (!data) return;
  const tbody = document.getElementById('usersTable');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted)">No subscribers yet.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(u => `
    <tr>
      <td>${u.full_name ?? '—'}</td>
      <td class="mono">${u.phone}</td>
      <td>${statusBadge(u.status)}</td>
      <td style="font-size:12px;color:var(--muted)">${u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Never'}</td>
      <td><button class="action-btn danger" onclick="suspendUser('${u.id}')">Suspend</button></td>
    </tr>`).join('');
}

async function suspendUser(id) {
  if (!confirm('Suspend this user?')) return;
  await api(`/api/users/${id}/suspend`, { method: 'POST' });
  loadUsers();
}

// ─── DEVICES — paid vs unpaid cross-reference ───────
async function loadDevices() {
  const tbody = document.getElementById('devicesTable');
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--muted)">Loading…</td></tr>';

  // Fetch devices and active sessions in parallel
  const [devData, sessData] = await Promise.all([
    api('/api/devices/'),
    api('/api/sessions/active'),
  ]);

  if (!devData) return;

  // Build set of MACs that have a paid active session
  activeMacs = new Set();
  const sessionByMac = {};
  if (sessData) {
    sessData.forEach(s => {
      if (s.mac_address) {
        activeMacs.add(s.mac_address.toLowerCase());
        sessionByMac[s.mac_address.toLowerCase()] = s;
      }
    });
  }

  const tenMinutesAgo = new Date(Date.now() - 10 * 60 * 1000);

  allDevices = devData
    .filter(d => d.last_seen_at && new Date(d.last_seen_at) > tenMinutesAgo)
    .map(d => ({
      ...d,
      _paid: activeMacs.has((d.mac_address || '').toLowerCase()),
      _session: sessionByMac[(d.mac_address || '').toLowerCase()] || null,
    }));

  const paid   = allDevices.filter(d => d._paid && d.status !== 'blocked').length;
  const unpaid = allDevices.filter(d => !d._paid && d.status !== 'blocked').length;

  document.getElementById('devTotal').textContent  = allDevices.length;
  document.getElementById('devPaid').textContent   = paid;
  document.getElementById('devUnpaid').textContent = unpaid;

  renderDevices(allDevices);
}

function renderDevices(list) {
  const tbody = document.getElementById('devicesTable');
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:32px;color:var(--muted)">No devices found.</td></tr>';
    return;
  }

  tbody.innerHTML = list.map(d => {
    const mac     = d.mac_address ?? '—';
    const host    = d.hostname ?? '—';
    const ip      = d.ip_address ?? '—';
    const seen    = d.last_seen_at ? timeAgo(d.last_seen_at) : '—';
    const owner   = d.users?.full_name ?? d.users?.phone ?? '—';
    const blocked = d.status === 'blocked';
    const pkgName = d._session?.package_name ?? '—';

    let payBadge, payLabel;
    if (blocked) {
      payBadge = 'badge-danger';
      payLabel = '🚫 Blocked';
    } else if (d._paid) {
      payBadge = 'badge-success';
      payLabel = '✅ Paid';
    } else {
      payBadge = 'badge-warning';
      payLabel = '⚠️ Not Paid';
    }

    const actionBtn = blocked
      ? `<button class="action-btn" onclick="allowDevice('${d.id}')">Unblock</button>`
      : `<div style="display:flex;gap:6px">
           <button class="action-btn danger" onclick="blockDevice('${d.id}')">Block</button>
           ${!d._paid ? `<button class="action-btn" onclick="grantAccess('${d.mac_address}')">Grant</button>` : ''}
         </div>`;

    return `
      <tr>
        <td class="mono">${mac}</td>
        <td style="color:var(--text)">${host}</td>
        <td class="mono">${ip}</td>
        <td><span class="badge ${payBadge}">${payLabel}</span></td>
        <td>${owner}</td>
        <td style="font-size:12px;color:var(--subtle)">${pkgName}</td>
        <td style="font-size:12px;color:var(--muted)">${seen}</td>
        <td>${actionBtn}</td>
      </tr>`;
  }).join('');
}

function filterDevices(filter, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  let list;
  if (filter === 'all')     list = allDevices;
  else if (filter === 'paid')   list = allDevices.filter(d => d._paid && d.status !== 'blocked');
  else if (filter === 'unpaid') list = allDevices.filter(d => !d._paid && d.status !== 'blocked');
  else if (filter === 'blocked') list = allDevices.filter(d => d.status === 'blocked');
  renderDevices(list);
}

async function deauthClient(mac) {
  if (!confirm(`Deauth ${mac}?`)) return;
  const result = await api(`/api/sessions/${encodeURIComponent(mac)}/deauth`, { method: 'POST' });
  if (result) { alert('Device deauthed.'); loadRouterStatus(); }
}

async function grantAccess(mac) {
  const minutes = prompt('Grant access for how many minutes?', '60');
  if (!minutes) return;
  const result = await api(`/api/sessions/grant/${mac}`, {
    method: 'POST',
    body: JSON.stringify({ minutes: parseInt(minutes) }),
  });
  if (result) {
    alert(`Access granted for ${minutes} minutes.`);
    loadDevices();
  }
}

async function blockDevice(id) {
  if (!confirm('Block this device?')) return;
  await api(`/api/devices/${id}/block`, { method: 'POST' });
  loadDevices();
}

async function allowDevice(id) {
  await api(`/api/devices/${id}/allow`, { method: 'POST' });
  loadDevices();
}

// ─── PACKAGES ADMIN — full CRUD ─────────────────────
let packagesCache = [];

async function loadPackages() {
  const data = await api('/api/packages/?active_only=false');
  if (!data) return;
  packagesCache = data;
  const tbody = document.getElementById('packagesTable');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--muted)">No packages yet. Create one above.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(p => {
    const dl  = Math.round(p.download_kbps / 128);
    const ul  = Math.round(p.upload_kbps / 128);
    const dur = p.duration_hours < 24
      ? p.duration_hours + (p.duration_hours === 1 ? ' hr' : ' hrs')
      : Math.round(p.duration_hours / 24) + ' days';
    return `
      <tr>
        <td style="font-weight:600;color:var(--text)">${p.name}</td>
        <td style="color:var(--success);font-weight:700">KES ${p.price_kes}</td>
        <td>${dur}</td>
        <td class="mono">${dl} Mbps</td>
        <td class="mono">${ul} Mbps</td>
        <td>${p.max_devices}</td>
        <td>${statusBadge(p.status)}</td>
        <td style="display:flex;gap:6px">
          <button class="action-btn" onclick="openPackageModal('${p.id}')">Edit</button>
          <button class="action-btn danger" onclick="deletePackage('${p.id}')">Remove</button>
        </td>
      </tr>`;
  }).join('');
}

function openPackageModal(packageId) {
  document.getElementById('editingPackageId').value = packageId || '';

  if (packageId) {
    const p = packagesCache.find(x => x.id === packageId);
    if (!p) return;
    document.getElementById('modalTitle').textContent = 'Edit Package';
    document.getElementById('modalSub').textContent   = 'Update the package details below.';
    document.getElementById('pkgName').value        = p.name;
    document.getElementById('pkgDescription').value = p.description || '';
    document.getElementById('pkgPrice').value       = p.price_kes;
    document.getElementById('pkgDuration').value    = p.duration_hours;
    document.getElementById('pkgDownload').value    = p.download_kbps;
    document.getElementById('pkgUpload').value      = p.upload_kbps;
    document.getElementById('pkgMaxDevices').value  = p.max_devices;
  } else {
    document.getElementById('modalTitle').textContent = 'New Package';
    document.getElementById('modalSub').textContent   = 'Fill in the details below to create a new package.';
    ['pkgName','pkgDescription','pkgPrice','pkgDuration','pkgDownload','pkgUpload','pkgMaxDevices']
      .forEach(id => document.getElementById(id).value = '');
  }

  document.getElementById('packageModal').classList.add('show');
}

function closePackageModal() {
  document.getElementById('packageModal').classList.remove('show');
}

async function savePackage() {
  const id   = document.getElementById('editingPackageId').value;
  const name = document.getElementById('pkgName').value.trim();
  const desc = document.getElementById('pkgDescription').value.trim();
  const price   = parseFloat(document.getElementById('pkgPrice').value);
  const hours   = parseInt(document.getElementById('pkgDuration').value);
  const dl      = parseInt(document.getElementById('pkgDownload').value);
  const ul      = parseInt(document.getElementById('pkgUpload').value);
  const devices = parseInt(document.getElementById('pkgMaxDevices').value);

  if (!name)          { alert('Package name is required.'); return; }
  if (isNaN(price) || price <= 0) { alert('Enter a valid price.'); return; }
  if (isNaN(hours) || hours <= 0) { alert('Enter a valid duration.'); return; }
  if (isNaN(dl) || dl <= 0)       { alert('Enter a valid download speed.'); return; }
  if (isNaN(ul) || ul <= 0)       { alert('Enter a valid upload speed.'); return; }

  const body = {
    name,
    description: desc || null,
    price_kes: price,
    duration_hours: hours,
    download_kbps: dl,
    upload_kbps: ul,
    max_devices: isNaN(devices) ? 1 : devices,
  };

  let result;
  if (id) {
    result = await api(`/api/packages/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  } else {
    result = await api('/api/packages/', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  if (result) {
    closePackageModal();
    loadPackages();
  }
}

async function deletePackage(id) {
  if (!confirm('Remove this package? It will be soft-deleted and hidden from customers.')) return;
  await api(`/api/packages/${id}`, { method: 'DELETE' });
  loadPackages();
}

// ─── PAYMENTS ───────────────────────────────────────
async function loadPaymentsTable() {
  const data = await api('/api/payments/');
  if (!data) return;
  const tbody = document.getElementById('paymentsTable');
  tbody.innerHTML = data.map(p => `
    <tr>
      <td class="mono">${p.phone}</td>
      <td>${p.packages?.name ?? '—'}</td>
      <td style="color:var(--success);font-weight:600">KES ${p.amount_kes}</td>
      <td class="mono" style="font-size:11px">${p.mpesa_transaction_code ?? '—'}</td>
      <td style="font-size:12px;color:var(--muted)">${new Date(p.created_at).toLocaleString()}</td>
      <td>${statusBadge(p.status)}</td>
    </tr>`).join('');
}

// ─── SECURITY ───────────────────────────────────────
async function loadSecurity() {
  const data = await api('/api/reports/security?resolved=false');
  if (!data) return;
  const tbody = document.getElementById('securityTable');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">No active alerts.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(e => `
    <tr>
      <td>${severityBadge(e.severity)}</td>
      <td style="font-weight:500;color:var(--text)">${(e.event_type || '').replace(/_/g,' ')}</td>
      <td style="font-size:12px">${e.description}</td>
      <td class="mono">${e.source_ip ?? '—'}</td>
      <td style="font-size:12px;color:var(--muted)">${new Date(e.created_at).toLocaleString()}</td>
      <td><span class="badge ${e.is_resolved ? 'badge-success':'badge-warning'}">${e.is_resolved ? 'Resolved':'Open'}</span></td>
    </tr>`).join('');
}

// ─── AUDIT ──────────────────────────────────────────
async function loadAudit() {
  const data = await api('/api/reports/audit?limit=50');
  if (!data) return;
  const tbody = document.getElementById('auditTable');
  tbody.innerHTML = data.map(e => `
    <tr>
      <td><span class="badge badge-info">${e.action}</span></td>
      <td style="font-size:12px">${e.description}</td>
      <td class="mono" style="font-size:11px">${e.actor_role ?? 'system'}</td>
      <td class="mono" style="font-size:11px">${e.ip_address ?? '—'}</td>
      <td style="font-size:12px;color:var(--muted)">${new Date(e.created_at).toLocaleString()}</td>
    </tr>`).join('');
}

// ─── HELPERS ────────────────────────────────────────
function statusBadge(s) {
  const map = {
    active:'badge-success', confirmed:'badge-success', allowed:'badge-success',
    pending:'badge-warning', suspended:'badge-warning', unknown:'badge-warning',
    blocked:'badge-danger', failed:'badge-danger', inactive:'badge-muted',
    expired:'badge-danger', terminated:'badge-danger',
  };
  return `<span class="badge ${map[s] || 'badge-info'}">${s}</span>`;
}

function severityBadge(s) {
  const map = { critical:'badge-danger', warning:'badge-warning', info:'badge-info' };
  return `<span class="badge ${map[s] || 'badge-info'}">${s}</span>`;
}

function timeAgo(iso) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return Math.floor(hrs / 24) + 'd ago';
}

function startClock() {
  const el = document.getElementById('topbarTime');
  const tick = () => el.textContent = new Date().toLocaleTimeString();
  tick();
  setInterval(tick, 1000);
}

// Close modal on overlay click
document.getElementById('packageModal').addEventListener('click', function(e) {
  if (e.target === this) closePackageModal();
});

let checkTimerInterval = null;

async function checkMySession() {
  document.getElementById('checkResult').style.display = 'none';
  document.getElementById('checkActive').style.display = 'none';
  document.getElementById('checkExpired').style.display = 'none';
  document.getElementById('checkNotFound').style.display = 'none';

  try {
    const macRes = await fetch(`${API}/api/devices/my-mac`);
    const macData = await macRes.json();
    const mac = macData.mac_address;

    if (!mac) {
      document.getElementById('checkResult').style.display = 'block';
      document.getElementById('checkNotFound').style.display = 'block';
      return;
    }

    const res = await fetch(`${API}/api/sessions/check/${mac}`);
    const data = await res.json();
    document.getElementById('checkResult').style.display = 'block';

    if (data.allowed) {
      const expires = new Date(data.expires_at);
      document.getElementById('checkActive').style.display = 'block';
      document.getElementById('checkPkg').textContent = data.package ?? '—';
      document.getElementById('checkExpires').textContent = 'Expires ' + expires.toLocaleString();
      if (checkTimerInterval) clearInterval(checkTimerInterval);
      checkTimerInterval = setInterval(() => {
        const rem = expires - Date.now();
        if (rem <= 0) { clearInterval(checkTimerInterval); document.getElementById('checkTimer').textContent = '00:00:00'; return; }
        const h = Math.floor(rem / 3600000).toString().padStart(2,'0');
        const m = Math.floor((rem % 3600000) / 60000).toString().padStart(2,'0');
        const s = Math.floor((rem % 60000) / 1000).toString().padStart(2,'0');
        document.getElementById('checkTimer').textContent = `${h}:${m}:${s}`;
      }, 1000);

    } else if (data.reason === 'expired') {
      document.getElementById('checkExpired').style.display = 'block';
      document.getElementById('checkExpiredDetails').innerHTML =
        `Paid at: <strong>${new Date(data.paid_at).toLocaleString()}</strong><br>
         Expired at: <strong>${new Date(data.expired_at).toLocaleString()}</strong><br>
         Package: <strong>${data.package}</strong>`;
    } else {
      document.getElementById('checkNotFound').style.display = 'block';
    }

  } catch(e) {
    alert('Could not check session. Please try again.');
  }
}

// Auto-login if token exists
if (token) {
  showAdmin();
}
