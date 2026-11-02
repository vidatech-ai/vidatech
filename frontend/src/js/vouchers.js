// =============================================================================
// VIDATECH WIFI — Admin Vouchers tab
// frontend/src/js/vouchers.js (loaded after main.js and admin.js)
// =============================================================================
(function () {
  var orig = window.showPage;
  window.showPage = function (name, el) {
    orig(name, el);
    if (name === 'vouchers') {
      var t = document.getElementById('pageTitle');
      if (t) t.textContent = 'Vouchers';
      loadVouchersPage();
    }
  };
})();

var vKnown = [], vShown = [], vSelected = [], vCache = [], vLastBatch = [], vFilterVal = 'all';

function vEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function vKey(p) { return String(p).replace(/\D/g, '').slice(-9); }
function vFmt(d) {
  if (!d) return '—';
  var x = new Date(d);
  if (isNaN(x.getTime())) return '—';
  return x.toLocaleString('en-KE', { timeZone: 'Africa/Nairobi', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function vIsSel(p) {
  var k = vKey(p);
  return vSelected.some(function (x) { return vKey(x) === k; });
}
function vSetHours(h) { document.getElementById('vHours').value = h; }

async function loadVouchersPage() {
  vRenderChips();
  vToggleCount();
  vRenderResults();
  vSetFilter(vFilterVal);
  vLoadKnown();
}

// ---------- phone picker ----------
async function vLoadKnown() {
  var res = await api('/api/vouchers/phones');
  vKnown = (res && res.phones) ? res.phones : [];
  vRenderList();
}

function vRenderChips() {
  var box = document.getElementById('vpChips');
  if (!box) return;
  box.innerHTML = vSelected.map(function (p, i) {
    return '<span style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:100px;background:rgba(14,165,233,0.15);color:var(--accent);font-size:12px;font-weight:600">' +
      vEsc(p) + ' <b style="cursor:pointer" onclick="vRemoveSel(' + i + ')">×</b></span>';
  }).join('');
  box.style.display = vSelected.length ? 'flex' : 'none';
  box.style.flexWrap = 'wrap';
  box.style.gap = '6px';
  box.style.marginBottom = '8px';
}

function vRenderList() {
  var box = document.getElementById('vpList');
  if (!box) return;
  var q = (document.getElementById('vpInput').value || '').replace(/\D/g, '');
  vShown = vKnown.filter(function (k) { return !q || String(k.phone).replace(/\D/g, '').indexOf(q) !== -1; });
  document.getElementById('vpCount').textContent = vShown.length + ' saved number(s) shown, ' + vSelected.length + ' selected';
  if (!vShown.length) {
    box.innerHTML = '<div style="padding:14px;color:var(--muted);font-size:13px">No saved numbers match. Type the full number above and press Enter to add it.</div>';
    return;
  }
  box.innerHTML = vShown.map(function (k, i) {
    var on = vIsSel(k.phone);
    return '<div onclick="vToggleKnown(' + i + ')" style="display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;border-bottom:1px solid rgba(128,128,128,.15);background:' + (on ? 'rgba(14,165,233,0.12)' : 'transparent') + '">' +
      '<span style="font-size:16px">' + (on ? '☑' : '☐') + '</span>' +
      '<span style="font-family:monospace">' + vEsc(k.phone) + '</span>' +
      '<span style="margin-left:auto;font-size:11px;color:var(--muted)">' + vFmt(k.last_activity) + '</span></div>';
  }).join('');
}

function vToggleKnown(i) {
  var k = vShown[i];
  if (!k) return;
  if (vIsSel(k.phone)) {
    var key = vKey(k.phone);
    vSelected = vSelected.filter(function (x) { return vKey(x) !== key; });
  } else {
    vSelected.push(k.phone);
  }
  vRenderChips(); vRenderList(); vToggleCount();
}
function vRemoveSel(i) { vSelected.splice(i, 1); vRenderChips(); vRenderList(); vToggleCount(); }
function vSelectShown() {
  vShown.forEach(function (k) { if (!vIsSel(k.phone)) vSelected.push(k.phone); });
  vRenderChips(); vRenderList(); vToggleCount();
}
function vClearSel() { vSelected = []; vRenderChips(); vRenderList(); vToggleCount(); }

function vAddTyped() {
  var inp = document.getElementById('vpInput');
  var msg = document.getElementById('vpMsg');
  msg.textContent = '';
  var raw = (inp.value || '').trim();
  if (!raw) return;
  var digits = raw.replace(/\D/g, '');
  if (digits.length < 9 || digits.length > 13) {
    msg.textContent = 'Type the full phone number to add it, or tick a saved number below.';
    return;
  }
  if (!vIsSel(raw)) vSelected.push(raw);
  inp.value = '';
  vRenderChips(); vRenderList(); vToggleCount();
}

function vToggleCount() {
  var n = vSelected.length;
  var cf = document.getElementById('vCountField');
  if (cf) cf.style.display = n ? 'none' : '';
  var b = document.getElementById('vGenBtn');
  if (b && !b.disabled) b.textContent = n ? 'Generate ' + n + ' voucher' + (n > 1 ? 's' : '') : 'Generate';
}

// ---------- generate ----------
async function vGenerate() {
  var btn = document.getElementById('vGenBtn');
  var msg = document.getElementById('vGenMsg');
  var hours = parseFloat(document.getElementById('vHours').value);
  var devices = parseInt(document.getElementById('vDevices').value, 10);
  var days = parseInt(document.getElementById('vDays').value, 10);
  var count = parseInt(document.getElementById('vCount').value, 10);
  msg.style.color = 'var(--danger)';
  msg.textContent = '';
  if (!(hours > 0)) { msg.textContent = 'Enter how many hours the voucher lasts.'; return; }
  if (!(devices >= 1 && devices <= 20)) { msg.textContent = 'Devices allowed must be between 1 and 20.'; return; }
  if (!(days >= 1 && days <= 365)) { msg.textContent = 'Expiry days must be between 1 and 365.'; return; }
  if (!vSelected.length && !(count >= 1 && count <= 100)) { msg.textContent = 'Number of vouchers must be between 1 and 100.'; return; }
  btn.disabled = true;
  btn.textContent = 'Generating…';
  try {
    var res = await api('/api/vouchers/generate', {
      method: 'POST',
      body: JSON.stringify({
        hours: hours, max_devices: devices, valid_days: days,
        phones: vSelected.slice(), count: vSelected.length ? 1 : count
      })
    });
    if (!res || !res.vouchers) {
      var d = res && res.detail;
      msg.textContent = (typeof d === 'string' ? d : (d ? JSON.stringify(d) : 'Could not generate vouchers.'));
      return;
    }
    vLastBatch = res.vouchers;
    vSelected = [];
    vRenderChips(); vRenderList(); vRenderResults();
    msg.style.color = 'var(--success)';
    msg.textContent = res.vouchers.length + ' voucher(s) generated.';
    vLoadList();
  } catch (e) {
    msg.textContent = 'Network error. Check the voucher list before trying again, so you do not create duplicates.';
  } finally {
    btn.disabled = false;
    vToggleCount();
  }
}

function vRenderResults() {
  var box = document.getElementById('vResults');
  if (!box) return;
  if (!vLastBatch.length) { box.style.display = 'none'; return; }
  box.style.display = '';
  document.getElementById('vResultsBody').innerHTML = vLastBatch.map(function (v) {
    return '<tr><td style="font-family:monospace;font-weight:700;letter-spacing:1px;font-size:15px">' + vEsc(v.code) + '</td>' +
      '<td>' + vEsc(v.locked_phone || 'Any phone') + '</td>' +
      '<td>' + vEsc(v.hours) + ' h</td><td>' + vEsc(v.max_devices) + '</td>' +
      '<td>' + vFmt(v.valid_until) + '</td>' +
      '<td><button type="button" class="btn-primary" style="width:auto;padding:4px 12px;margin-top:0;font-size:11px" onclick="vCopyText(\'' + vEsc(v.code) + '\', this)">Copy</button></td></tr>';
  }).join('');
}

function vCopyAll(btn) {
  var text = vLastBatch.map(function (v) { return (v.locked_phone ? v.locked_phone + ': ' : '') + v.code; }).join('\n');
  vCopyText(text, btn);
}

async function vCopyText(text, btn) {
  var ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch (e) {}
  if (!ok) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      ok = document.execCommand('copy');
      document.body.removeChild(ta);
    } catch (e) {}
  }
  if (btn) {
    var old = btn.textContent;
    btn.textContent = ok ? 'Copied ✓' : 'Copy failed';
    setTimeout(function () { btn.textContent = old; }, 1500);
  }
}

// ---------- list ----------
function vSetFilter(f) {
  vFilterVal = f;
  ['all', 'unused', 'active', 'expired', 'revoked'].forEach(function (k) {
    var b = document.getElementById('vf_' + k);
    if (b) b.style.opacity = (k === f) ? '1' : '0.45';
  });
  vLoadList();
}

async function vLoadList() {
  var tb = document.getElementById('vTable');
  if (!tb) return;
  var res = await api('/api/vouchers/?status=' + encodeURIComponent(vFilterVal));
  if (!res || !res.vouchers) {
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--muted)">Could not load vouchers.</td></tr>';
    return;
  }
  vCache = res.vouchers;
  if (!vCache.length) {
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--muted)">No vouchers here yet.</td></tr>';
    return;
  }
  var cls = { unused: 'badge-info', active: 'badge-success', expired: 'badge-muted', revoked: 'badge-danger' };
  tb.innerHTML = vCache.map(function (v) {
    var who = v.redeemed_phone || v.locked_phone || '—';
    var ends = v.status === 'unused' ? ('use by ' + vFmt(v.valid_until)) : vFmt(v.expires_at);
    var act = '<button type="button" class="btn-primary" style="width:auto;padding:4px 10px;margin-top:0;font-size:11px" onclick="vCopyText(\'' + vEsc(v.code) + '\', this)">Copy</button>';
    if (v.status === 'unused' || v.status === 'active') {
      act += ' <button type="button" class="btn-primary" style="width:auto;padding:4px 10px;margin-top:0;font-size:11px;background:var(--danger)" onclick="vRevoke(\'' + vEsc(v.id) + '\')">Revoke</button>';
    }
    return '<tr><td style="font-family:monospace;font-weight:700;letter-spacing:1px">' + vEsc(v.code) + '</td>' +
      '<td><span class="badge ' + (cls[v.status] || 'badge-muted') + '">' + vEsc(v.status) + '</span></td>' +
      '<td>' + vEsc(v.hours) + ' h</td>' +
      '<td>' + vEsc(v.devices_used) + ' / ' + vEsc(v.max_devices) + '</td>' +
      '<td>' + vEsc(who) + '</td>' +
      '<td>' + vFmt(v.redeemed_at) + '</td>' +
      '<td>' + ends + '</td>' +
      '<td style="white-space:nowrap">' + act + '</td></tr>';
  }).join('');
}

async function vRevoke(id) {
  var v = vCache.find(function (x) { return x.id === id; });
  if (!v) return;
  var extra = v.devices_used ? '\n\n' + v.devices_used + ' device(s) using it will lose internet.' : '';
  if (!confirm('Revoke voucher ' + v.code + '?' + extra)) return;
  var res = await api('/api/vouchers/' + id + '/revoke', { method: 'POST' });
  if (res && res.message) { vLoadList(); }
  else { alert((res && res.detail) || 'Could not revoke this voucher.'); }
}
