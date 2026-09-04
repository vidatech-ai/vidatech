// ─── PORTAL — PACKAGE SELECTION ─────────────────────
// MAC is no longer read from the URL (nodogsplash splashpage substitution
// doesn't work reliably). Instead we ask the router directly via a CGI
// endpoint that reads /proc/net/arp for the requesting client's IP.
const ROUTER_MAC_ENDPOINT = 'http://192.168.2.1/cgi-bin/getmac';

let selectedPkg = { id: '', name: '', hours: 0, speed: '', price: 0 };
let sessionInterval = null;

let _clientMac = null;
let _macLookupFailed = false;

async function fetchClientMac(retries = 5, delayMs = 1500, disableBtn = false) {
  const payBtn = document.getElementById('payBtn');
  if (payBtn && disableBtn) payBtn.disabled = true;

  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(ROUTER_MAC_ENDPOINT, { cache: 'no-store' });
      const data = await res.json();
      if (data.mac) {
        _clientMac = data.mac.toLowerCase();
        _macLookupFailed = false;
        if (payBtn && disableBtn) payBtn.disabled = false;
        return;
      }
    } catch (e) {
      // router unreachable this attempt — retry
    }
    // ARP entry may not exist yet right after association; wait and retry
    await new Promise(r => setTimeout(r, delayMs));
  }

  // All retries exhausted — do not silently fall back to a dummy MAC.
  _clientMac = null;
  _macLookupFailed = true;
  if (payBtn) {
    payBtn.disabled = false;
    payBtn.textContent = 'Pay with M-Pesa';
  }
  console.error('Could not resolve client MAC from router after retries.');
}
fetchClientMac(5, 1500, false).then(async () => {
  if (!_clientMac) return;
  try {
    const res = await fetch(`${API}/api/sessions/check/${_clientMac}`);
    const data = await res.json();
    if (data.allowed) {
      selectedPkg = {
        id: '',
        name: data.package || 'Active Plan',
        hours: 0,
        speed: '',
        price: 0,
      };
      const phone = '';
      showActiveSession(phone, data);
    }
  } catch(e) {}
});

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
      setTimeout(() => scrollToPay(), 300);
    });
  });
}
initPortalPackages();

// Optionally load packages from API to overwrite static cards
async function loadPortalPackages() {
  try {
    const res = await fetch(`${API}/api/packages/?active_only=true`);
    if (!res.ok) return; // fall back to static
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
    // Select first
    const first = grid.querySelector('.pkg-big');
    if (first) first.click();
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

  const btn = document.getElementById('payBtn');
  btn.disabled = true;
  document.getElementById('progressWrap').classList.add('show');
  setProgress(5, 'Identifying your device…');

  if (!_clientMac) {
    await fetchClientMac(3, 1000);
    if (!_clientMac) {
      document.getElementById('progressWrap').classList.remove('show');
      btn.disabled = false;
      alert('Could not identify your device on the network. Please reconnect to WiFi and try again.');
      return;
    }
  }

  setProgress(10, 'Connecting to payment server…');

  try {
    const res = await fetch(`${API}/api/payments/initiate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, package_id: selectedPkg.id, mac_address: _clientMac }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Payment failed.');

    setProgress(40, 'M-Pesa prompt sent to your phone — enter your PIN now…');

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
      setProgress(40 + Math.min(attempts * 2, 40), attempts < 6
        ? 'Waiting for M-Pesa confirmation…'
        : 'Still waiting — please enter your PIN if you haven\'t…'
      );
      try {
        const sr = await fetch(`${API}/api/payments/status/${paymentId}`);
        const sd = await sr.json();
        if (sd.status === 'confirmed') {
          clearInterval(poll);
          setProgress(90, 'Payment confirmed! Activating your session…');
          // Wait 10s for agent to auth the device
          let countdown = 15;
          const activating = setInterval(() => {
            countdown--;
            setProgress(90 + Math.round((15 - countdown) * (10/15)), `Activating internet access… ${countdown}s`);
            if (countdown <= 0) {
              clearInterval(activating);
              setProgress(100, 'You are connected!');
              setTimeout(() => showActiveSession(phone, sd), 500);
            }
          }, 1000);
        } else if (sd.status === 'failed') {
          clearInterval(poll);
          document.getElementById('progressWrap').classList.remove('show');
          btn.disabled = false;
          alert('Payment failed. Please try again.');
        }
      } catch(e) {}
    }, 5000);

  } catch(e) {
    document.getElementById('progressWrap').classList.remove('show');
    btn.disabled = false;
    alert(e.message);
  }
}

function showActiveSession(phone, data) {
  document.getElementById('payFormWrap').style.display = 'none';
  document.getElementById('progressWrap').classList.remove('show');
  document.getElementById('sessionActive').classList.add('show');
  document.getElementById('stateConnected').style.display = 'block';
  document.getElementById('stateExpired').style.display = 'none';
  document.getElementById('sessionPkg').textContent = selectedPkg.name;
  document.getElementById('sessionSpeed').textContent = selectedPkg.speed;
  document.getElementById('sessionPhone').textContent = phone.replace(/(\d{4})(\d{3})(\d{3})/, '$1 $2 $3');

  const paidAt = new Date();
  // Add 10s buffer — agent needs up to 30s but we already waited 10s above
  const expires = new Date(Date.now() + selectedPkg.hours * 3600000 + 3000);
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

    // Warn client 2 minutes before expiry
    if (rem < 120000 && rem > 119000) {
      document.getElementById('sessionExpires').textContent =
        '⚠️ Less than 2 minutes remaining — buy again soon!';
    }
  }, 1000);
}

async function reconnectSession() {
  const phone = document.getElementById('sessionPhone').textContent.replace(/\s/g,'');
  try {
    const res = await fetch(`${API}/api/sessions/reconnect-by-phone?phone=${encodeURIComponent(phone)}`);
    const data = await res.json();
    if (data.allowed) {
      showActiveSession(phone, data);
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
  document.getElementById('portalView').style.display = 'none';
  if (token) { showAdmin(); }
  else { document.getElementById('loginView').style.display = 'flex'; }
}
function backToPortal() {
  document.getElementById('loginView').style.display = 'none';
  document.getElementById('portalView').style.display = 'flex';
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
  document.getElementById('adminView').classList.remove('show');
  document.getElementById('portalView').style.display = 'flex';
}

function showAdmin() {
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