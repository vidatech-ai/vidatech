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
    const at = summary.alltime || {};
    const mo = summary.this_month || {};
    const fmt = n => 'KES ' + (n||0).toLocaleString('en-KE', {minimumFractionDigits:2, maximumFractionDigits:2});
    summaryEl.innerHTML = `
      <div style="margin-bottom:20px">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">📊 Since Day One</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px">
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #6366f1">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">TOTAL RECEIVED</div>
            <div style="font-size:17px;font-weight:700;color:#fff">${fmt(at.total_received_kes)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">from all clients</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #facc15">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">PAYSTACK FEES ~1.5%</div>
            <div style="font-size:17px;font-weight:700;color:#facc15">${fmt(at.total_fees_kes)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">deducted by Paystack</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #22c55e">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">SETTLED TO ACCOUNT</div>
            <div style="font-size:17px;font-weight:700;color:#22c55e">${fmt(at.total_settled_kes)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">paid to your till</div>
          </div>
          <div style="background:rgba(248,113,113,0.08);border-radius:10px;padding:12px 16px;border-left:3px solid #f87171">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">PENDING ALL TIME</div>
            <div style="font-size:17px;font-weight:700;color:#f87171">${fmt(at.pending_kes)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">yet to hit your account</div>
          </div>
        </div>
      </div>
      <div style="margin-bottom:14px">
        <div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px">📅 ${mo.label||'This Month'}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px">
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #6366f1">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">RECEIVED THIS MONTH</div>
            <div style="font-size:17px;font-weight:700;color:#fff">${fmt(mo.total_received_kes)}</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #facc15">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">FEES THIS MONTH</div>
            <div style="font-size:17px;font-weight:700;color:#facc15">${fmt(mo.total_fees_kes)}</div>
          </div>
          <div style="background:rgba(255,255,255,0.05);border-radius:10px;padding:12px 16px;border-left:3px solid #22c55e">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">SETTLED THIS MONTH</div>
            <div style="font-size:17px;font-weight:700;color:#22c55e">${fmt(mo.total_settled_kes)}</div>
          </div>
          <div style="background:rgba(248,113,113,0.08);border-radius:10px;padding:12px 16px;border-left:3px solid #f87171">
            <div style="font-size:10px;color:var(--muted);margin-bottom:4px">PENDING THIS MONTH</div>
            <div style="font-size:17px;font-weight:700;color:#f87171">${fmt(mo.pending_kes)}</div>
            <div style="font-size:10px;color:#f87171;margin-top:2px">💸 not yet settled</div>
          </div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);text-align:right">🕐 As of ${summary.as_of||'—'} (Kakamega time)</div>`;
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
      <td style="font-size:12px;color:var(--muted)">${s.settled_at ? new Date(s.settled_at).toLocaleString('en-KE', {timeZone:'Africa/Nairobi'}) : '—'}</td>
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
