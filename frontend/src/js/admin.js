// ─── DASHBOARD ──────────────────────────────────────


setInterval(() => {
  if (document.getElementById('page-dashboard')?.classList.contains('active')) {
    loadRouterStatus();
    loadDashboard();
  }
  if (document.getElementById('page-sessions')?.classList.contains('active')) {
    loadSessions();
  }
}, 30000);



// ─── SESSIONS ───────────────────────────────────────




// ─── USERS ──────────────────────────────────────────




// ─── DEVICES — paid vs unpaid cross-reference ───────














// ─── PACKAGES ADMIN — full CRUD ─────────────────────












// ─── PAYMENTS ───────────────────────────────────────


// ─── SETTLEMENTS ───────────────────────────────────
async function loadSettlementsTable() {
  await api('/api/reports/settlements/sync', { method: 'POST' });
  const data = await api('/api/payments/settlements');
  if (!data) return;
  const tbody = document.getElementById('settlementsTable');
  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--muted)">No settlements yet.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(s => `
    <tr>
      <td style="color:var(--success);font-weight:600">KES ${s.amount_kes}</td>
      <td>${statusBadge(s.status)}</td>
      <td style="font-size:12px;color:var(--muted)">${new Date(s.settled_at).toLocaleString()}</td>
      <td class="mono" style="font-size:11px">${s.paystack_settlement_id}</td>
    </tr>`).join('');
}

// ─── SECURITY ───────────────────────────────────────


// ─── AUDIT ──────────────────────────────────────────


// ─── HELPERS ────────────────────────────────────────








// Close modal on overlay click
document.getElementById('packageModal').addEventListener('click', function(e) {
  if (e.target === this) closePackageModal();
});





// Auto-login if token exists
if (token) {
  showAdmin();
}
