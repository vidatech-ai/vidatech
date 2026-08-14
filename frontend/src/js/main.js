// ─── CONFIG & SHARED HELPERS ────────────────────────
const API = 'https://vidatech-wifi.onrender.com';
let token = localStorage.getItem('vt_token');
let selectedPkg = { id: null, name: '', hours: 0, speed: '', price: 0 };
let sessionInterval = null;

const ROUTER_MAC_ENDPOINT = 'http://192.168.2.1/cgi-bin/getmac';  // same URL, fetch changes below
let _clientMac = null;
let _macLookupFailed = false;

async function fetchClientMac(retries = 5, delayMs = 1500) {
  const payBtn = document.getElementById('payBtn');
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${API}/api/devices/my-mac`, { cache: 'no-store' });
      const data = await res.json();
      if (data.mac_address) {
        _clientMac = data.mac_address.toLowerCase();
        _macLookupFailed = false;
        if (payBtn) payBtn.disabled = false;
        return;
      }
    } catch (e) {}
    await new Promise(r => setTimeout(r, delayMs));
  }
  _clientMac = null;
  _macLookupFailed = false;
  if (payBtn) payBtn.disabled = false;
  console.error('Could not resolve client MAC from router after retries.');
}
fetchClientMac().then(async () => {
  if (_clientMac) {
    try {
      const res = await fetch(`${API}/api/sessions/check/${_clientMac}`);
      const data = await res.json();
      if (data.allowed) {
        const tokRes = await fetch(`http://192.168.2.1/cgi-bin/getmac`, { cache: 'no-store' });
        const tokData = await tokRes.json();
        const tok = tokData.token;
        if (tok) {
          await fetch(`http://192.168.2.1:2050/nodogsplash_auth/?tok=${tok}`, { cache: 'no-store' });
        }
        showActiveSession('', data);
      }
    } catch(e) {}
  }
});
let allDevices = [];
let activeMacs = new Set();

function authHeaders() {
  return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function api(path, opts) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders(), ...opts });
  if (r.status === 401) { doLogout(); return null; }
  if (r.status === 204) return {};
  return r.json();
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
// ─── PORTAL — PACKAGE SELECTION ─────────────────────
function initPortalPackages() {
  document.querySelectorAll('.pkg-big').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.pkg-big').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      selectedPkg = {
        id: card.dataset.id,
        name: card.querySelector('.pkg-big-name').textContent,
        hours: parseInt(card.dataset.hours),
        speed: card.dataset.speed,
        price: parseInt(card.dataset.price),
      };
      document.getElementById('selectedPkgLabel').textContent = selectedPkg.name;
      document.getElementById('selectedPkgPrice').textContent = 'KES ' + selectedPkg.price;
      // Scroll to payment section
      document.getElementById('paySection').scrollIntoView({ behavior: 'smooth' });
    });
  });
}
initPortalPackages();

// Optionally load packages from API to overwrite static cards
async function loadPortalPackages() {
  try {
    const res = await fetch(`${API}/api/packages/?active_only=true`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.length) return;

    const icons = ['⚡','🌅','📆','🚀','🌟','💎'];
    const grid = document.getElementById('portalPackagesGrid');
    grid.innerHTML = data.map((p, i) => {
      const dl = Math.round(p.download_kbps / 128);
      const ul = Math.round(p.upload_kbps / 128);
      const dur = p.duration_hours < 24
        ? p.duration_hours + (p.duration_hours === 1 ? ' hr' : ' hrs')
        : Math.round(p.duration_hours / 24) + ' days';
      return `
        <div class="pkg-big ${i===1?'popular':''}" data-id="${p.id}" data-hours="${p.duration_hours}" data-price="${p.price_kes}" data-name="${p.name}" data-speed="${dl} Mbps">
          ${i===1 ? '<div class="pkg-popular-badge">Most Popular</div>' : ''}
          <div class="pkg-big-icon">${icons[i] || '📶'}</div>
          <div class="pkg-big-name">${p.name}</div>
          <div class="pkg-big-price">KES ${p.price_kes} <sub>/ ${dur}</sub></div>
          <div class="pkg-big-duration">${p.description || ''}</div>
          <ul class="pkg-big-features">
            <li>${dl} Mbps download</li>
            <li>${ul} Mbps upload</li>
            <li>${p.max_devices} device${p.max_devices > 1 ? 's' : ''}</li>
          </ul>
          <div class="pkg-selected-check">✓</div>
        </div>`;
    }).join('');
    initPortalPackages();
  } catch(e) { /* keep static fallback */ }
}
loadPortalPackages();

function scrollToPackages() {
  document.getElementById('packagesSection').scrollIntoView({ behavior: 'smooth' });
}
function scrollToPay() {
  document.getElementById('paySection').scrollIntoView({ behavior: 'smooth' });
}

// ─── PAYMENT ────────────────────────────────────────
function setProgress(pct, text) {
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressText').textContent = text;
}

async function handlePayment() {
  const phone = document.getElementById('phoneInput').value.trim();
  if (!phone) { alert('Enter your M-Pesa number.'); return; }
  if (!selectedPkg.id) { alert('Select a package first.'); return; }

  if (!_clientMac) {
    await fetchClientMac(3, 1000);
    if (!_clientMac) {
      alert('Could not identify your device on the network. Please reconnect to WiFi and try again.');
      return;
    }
  }

  const btn = document.getElementById('payBtn');
  btn.disabled = true;
  document.getElementById('progressWrap').classList.add('show');
  setProgress(20, 'Initiating payment…');

  try {
    let data;
    try {
      const res = await fetch(`${API}/api/payments/initiate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, package_id: selectedPkg.id, mac_address: _clientMac }),
      });
      data = await res.json();
      if (res.status >= 400) throw new Error(data.detail || 'Payment failed.');
    } catch(fetchErr) {
      if (fetchErr.message && fetchErr.message !== 'Failed to fetch') throw fetchErr;
      // Render woke up and processed the request even if fetch timed out
      // Continue to polling — STK push was sent
      data = { payment_id: null };
    }

    setProgress(60, 'M-Pesa prompt sent — enter your PIN…');

    if (!data.payment_id) {
      // We don't have a payment_id — poll by phone+package instead
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        if (attempts > 24) {
          clearInterval(poll);
          document.getElementById('progressWrap').classList.remove('show');
          btn.disabled = false;
          return;
        }
        try {
          const sr = await fetch(`${API}/api/payments/status/latest?phone=${encodeURIComponent(phone)}`);
          const sd = await sr.json();
          if (sd.status === 'confirmed') {
            clearInterval(poll);
            setProgress(100, 'Payment confirmed!');
            try {
              const tokRes = await fetch('http://192.168.2.1/cgi-bin/getmac', { cache: 'no-store' });
              const tokData = await tokRes.json();
              const tok = tokData.token;
              if (tok) await fetch(`http://192.168.2.1/cgi-bin/auth?tok=${tok}`, { cache: 'no-store' });
            } catch(e) {}
            setTimeout(() => showActiveSession(phone, sd), 800);
          }
        } catch(e) {}
      }, 5000);
      return;
    }

    const paymentId = data.payment_id;
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      if (attempts > 24) {
        clearInterval(poll);
        document.getElementById('progressWrap').classList.remove('show');
        btn.disabled = false;
        alert('Payment timed out. Please try again.');
        return;
      }
      try {
        const sr = await fetch(`${API}/api/payments/status/${paymentId}`);
        const sd = await sr.json();
        if (sd.status === 'confirmed') {
          clearInterval(poll);
          setProgress(100, 'Payment confirmed!');
          try {
            const tokRes = await fetch(`http://192.168.2.1/cgi-bin/getmac`, { cache: 'no-store' });
            const tokData = await tokRes.json();
            const tok = tokData.token;
            if (tok) {
              await fetch(`http://192.168.2.1:2050/nodogsplash_auth/?tok=${tok}`, { cache: 'no-store' });
            }
          } catch(e) {}
          setTimeout(() => showActiveSession(phone, sd), 800);
        } else if (sd.status === 'failed') {
          clearInterval(poll);
          document.getElementById('progressWrap').classList.remove('show');
          btn.disabled = false;
          alert('Payment failed. Please try again.');
        }
      } catch(e) { /* ignore polling errors */ }
    }, 5000);

  } catch(e) {
    document.getElementById('progressWrap').classList.remove('show');
    btn.disabled = false;
    alert(e.message);
  }
}

function showActiveSession(phone, data) {
  document.getElementById('payFormWrap').style.display = 'none';
  document.getElementById('sessionActive').classList.add('show');
  document.getElementById('stateConnected').style.display = 'block';
  document.getElementById('stateExpired').style.display = 'none';
  document.getElementById('sessionPkg').textContent = selectedPkg.name;
  document.getElementById('sessionSpeed').textContent = selectedPkg.speed;
  document.getElementById('sessionPhone').textContent = phone.replace(/(\d{4})(\d{3})(\d{3})/, '$1 $2 $3');

  const paidAt = new Date();
  const expires = new Date(Date.now() + selectedPkg.hours * 3600000);
  document.getElementById('sessionExpires').textContent = 'Expires ' + expires.toLocaleString();

  if (sessionInterval) clearInterval(sessionInterval);
  sessionInterval = setInterval(() => {
    const rem = expires - Date.now();
    if (rem <= 0) {
      clearInterval(sessionInterval);
      document.getElementById('stateConnected').style.display = 'none';
      document.getElementById('stateExpired').style.display = 'block';
      document.getElementById('expiredDetails').innerHTML =
        `Paid at: <strong>${paidAt.toLocaleString()}</strong><br>Expired at: <strong>${expires.toLocaleString()}</strong>`;
      return;
    }
    const h = Math.floor(rem / 3600000).toString().padStart(2,'0');
    const m = Math.floor((rem % 3600000) / 60000).toString().padStart(2,'0');
    const s = Math.floor((rem % 60000) / 1000).toString().padStart(2,'0');
    document.getElementById('sessionTimer').textContent = `${h}:${m}:${s}`;
  }, 1000);
}

async function reconnectSession() {
  const phone = document.getElementById('sessionPhone').textContent.replace(/\s/g,'');
  try {
    const res = await fetch(`${API}/api/sessions/active?phone=${phone}`);
    const data = await res.json();
    if (data && data.length > 0) {
      alert('You are already connected!');
    } else {
      document.getElementById('stateConnected').style.display = 'none';
      document.getElementById('stateExpired').style.display = 'block';
      document.getElementById('expiredDetails').innerHTML = 'No active session found for this device.';
    }
  } catch(e) {
    alert('Could not check session. Please try again.');
  }
}

function buyAgain() {
  document.getElementById('sessionActive').classList.remove('show');
  document.getElementById('stateExpired').style.display = 'none';
  document.getElementById('payFormWrap').style.display = 'block';
  scrollToPackages();
}

// ─── NAV ────────────────────────────────────────────
function switchToAdmin() {
  window.location.href = 'admin.html';
}
function backToPortal() {
  window.location.href = 'index.html';
}

async function doLogin() {
  const phone = document.getElementById('adminPhone').value.trim();
  const password = document.getElementById('adminPassword').value;
  const errEl = document.getElementById('loginError');
  errEl.classList.remove('show');
  try {
    const res = await fetch(`${API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed.');
    token = data.access_token;
    localStorage.setItem('vt_token', token);
    document.getElementById('loginView').style.display = 'none';
    showAdmin();
  } catch(e) {
    errEl.textContent = e.message;
    errEl.classList.add('show');
  }
}

function doLogout() {
  localStorage.removeItem('vt_token');
  token = null;
  window.location.href = 'index.html';
}

function showAdmin() {
  document.getElementById('loginView').style.display = 'none';
  document.getElementById('adminView').classList.add('show');
  loadDashboard();
  startClock();
}

function showPage(name, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  if (el) el.classList.add('active');
  const titles = {
    dashboard:'Dashboard', sessions:'Live Sessions', users:'Subscribers',
    devices:'All Devices', packages:'Packages', payments:'Payments',
    reports:'Analytics', security:'Security Events', audit:'Audit Log', settings:'Settings',
  };
  document.getElementById('pageTitle').textContent = titles[name] || name;
  const loaders = {
    sessions: loadSessions, users: loadUsers, devices: loadDevices,
    packages: loadPackages, payments: loadPaymentsTable,
    security: loadSecurity, audit: loadAudit,
  };
  if (loaders[name]) loaders[name]();
}

function authHeaders() {
  return { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function api(path, opts) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders(), ...opts });
  if (r.status === 401) { doLogout(); return null; }
  if (r.status === 204) return {};
  return r.json();
}

// ─── DASHBOARD ──────────────────────────────────────
async function loadDashboard() {
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
      : `<button class="action-btn danger" onclick="blockDevice('${d.id}')">Block</button>`;

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

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('show');
}

// Close modal on overlay click
const _pkgModal = document.getElementById('packageModal');
if (_pkgModal) _pkgModal.addEventListener('click', function(e) {
  if (e.target === this) closePackageModal();
});

let checkTimerInterval = null;

async function checkMySession() {
  document.getElementById('checkResult').style.display = 'none';
  document.getElementById('checkActive').style.display = 'none';
  document.getElementById('checkExpired').style.display = 'none';
  document.getElementById('checkNotFound').style.display = 'none';

  try {
    let data = null;
    if (_clientMac) {
      const res = await fetch(`${API}/api/sessions/check/${_clientMac}`);
      data = await res.json();
    }

    if (!data || !data.allowed) {
      const phone = prompt('Enter your M-Pesa number to reconnect (e.g. 0712345678):');
      if (!phone) {
        document.getElementById('checkResult').style.display = 'block';
        document.getElementById('checkNotFound').style.display = 'block';
        return;
      }
      const res2 = await fetch(`${API}/api/sessions/reconnect-by-phone?phone=${encodeURIComponent(phone.trim())}`);
      data = await res2.json();
      if (data.allowed) {
        try {
          const tokRes = await fetch('http://192.168.2.1/cgi-bin/getmac', { cache: 'no-store' });
          const tokData = await tokRes.json();
          const tok = tokData.token;
          if (tok) await fetch(`http://192.168.2.1:2050/nodogsplash_auth/?tok=${tok}`, { cache: 'no-store' });
        } catch(e) {}
      } else if (data.reason === 'all_slots_in_use') {
        alert(data.message);
        return;
      }
    }

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
    } else if (data.reason === 'expired' || data.reason === 'session_expired') {
      document.getElementById('checkExpired').style.display = 'block';
      document.getElementById('checkExpiredDetails').innerHTML =
        `Package: <strong>${data.package ?? '—'}</strong><br>Session has expired.`;
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
