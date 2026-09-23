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
  const res = await api('/api/payments/settlements');
  if (!res) return;
  const summary = res.summary || {};
  const data = res.settlements || [];
  const summaryEl = document.getElementById('settlementsSummary');
  if (summaryEl) {
    summaryEl.innerHTML = `
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px">
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 18px">
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Total Received</div>
          <div style="font-size:20px;font-weight:700;color:#fff">KES ${(summary.total_received_kes||0).toLocaleString()}</div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 18px">
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Paystack Fees</div>
          <div style="font-size:20px;font-weight:700;color:#facc15">KES ${(summary.total_fees_kes||0).toLocaleString()}</div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 18px">
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Settled to Account</div>
          <div style="font-size:20px;font-weight:700;color:var(--success)">KES ${(summary.total_settled_kes||0).toLocaleString()}</div>
        </div>
        <div style="flex:1;min-width:140px;background:rgba(255,255,255,0.04);border-radius:10px;padding:14px 18px">
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Pending Payout</div>
          <div style="font-size:20px;font-weight:700;color:#f97316">KES ${(summary.pending_kes||0).toLocaleString()}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);text-align:right;margin-bottom:8px">As of ${summary.as_of||'—'} (Kakamega time)</div>`;
  }
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
