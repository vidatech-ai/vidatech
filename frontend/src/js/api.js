// ─── CONFIG & SHARED HELPERS ────────────────────────
// API, token, selectedPkg, sessionInterval declared in main.js

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
