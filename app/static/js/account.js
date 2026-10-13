// Watchlist + portfolio pages and the "Watch" button on stock pages.
// Everything here talks to the logged-in /api/me/* endpoints. Public pages
// never load this code's data paths unless the visitor is signed in.

const _csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
const _signedIn = () => (document.querySelector('meta[name="signed-in"]') || {}).content === "1";

async function acctApi(path, { method = "GET", body } = {}) {
  const opts = { method, headers: { "X-CSRF-Token": _csrf() }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
  if (res.status === 401) {
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
    throw new Error("Not signed in");
  }
  if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const _esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Nepali-style digit grouping (12,34,567.00), the way Meroshare / TMS show it.
const _rs = (v, d = 2) => v == null || isNaN(v) ? "—"
  : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const _signCls = (v) => v == null || v === 0 ? "" : v > 0 ? "pos" : "neg";
const _signed = (v, d = 2) => v == null ? "—" : `${v > 0 ? "+" : ""}${_rs(v, d)}`;
const _signedPct = (v) => v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`;

// --- model signal badges (lazy, one request per symbol) -----------------------
const _signalCache = {};
async function _loadSignal(ticker) {
  if (!(ticker in _signalCache)) {
    _signalCache[ticker] = fetch(`/api/signal/${encodeURIComponent(ticker)}`)
      .then(r => r.json()).catch(() => ({ signal: null }));
  }
  return _signalCache[ticker];
}
async function _fillSignals(root) {
  const cells = root.querySelectorAll("[data-signal-for]");
  await Promise.all([...cells].map(async (el) => {
    const d = await _loadSignal(el.dataset.signalFor);
    if (!d || !d.signal) { el.innerHTML = `<span class="text-dim">—</span>`; return; }
    const cls = { Buy: "badge-buy", Sell: "badge-sell", Hold: "badge-hold" }[d.signal] || "badge-hold";
    el.innerHTML = `<span class="badge-pill sm ${cls}" title="Confidence ${(d.confidence * 100).toFixed(0)}%">${d.signal}</span>`;
  }));
}

async function _fillTickerOptions() {
  const list = document.getElementById("ticker-options");
  if (!list) return;
  try {
    const rows = await (await fetch("/api/tickers")).json();
    list.innerHTML = rows.map(r => `<option value="${_esc(r.t)}">${_esc(r.n)}</option>`).join("");
  } catch (e) { /* the field still accepts typed symbols */ }
}

// --- watch button on stock pages --------------------------------------------------
async function initWatchButton() {
  const btn = document.getElementById("watch-btn");
  if (!btn) return;
  const ticker = btn.dataset.ticker;
  const paint = (on) => {
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.textContent = on ? "★ Watching" : "☆ Watch";
  };
  let watching = false;
  if (_signedIn()) {
    try { watching = (await acctApi(`/api/me/watchlist/status/${encodeURIComponent(ticker)}`)).watching; } catch (e) { /* keep default */ }
  }
  paint(watching);
  btn.addEventListener("click", async () => {
    if (!_signedIn()) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    btn.disabled = true;
    try {
      const d = watching
        ? await acctApi(`/api/me/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" })
        : await acctApi("/api/me/watchlist", { method: "POST", body: { ticker } });
      watching = d.watching;
      paint(watching);
    } catch (e) {
      btn.title = e.message;
    } finally {
      btn.disabled = false;
    }
  });
}

// --- watchlist page ---------------------------------------------------------------
async function initWatchlistPage() {
  const body = document.getElementById("watchlist-body");
  if (!body) return;
  const msg = document.getElementById("watch-add-msg");
  _fillTickerOptions();

  async function load() {
    try {
      const { items } = await acctApi("/api/me/watchlist");
      if (!items.length) {
        body.innerHTML = `<p class="text-dim mb-0">Nothing here yet. Add a symbol above, or press <strong>☆ Watch</strong> on any stock page.</p>`;
        return;
      }
      body.innerHTML = `<div class="table-responsive"><table class="data-table">
        <thead><tr><th>Symbol</th><th>Company</th><th>Sector</th><th class="num">LTP</th><th class="num">Change</th><th>Signal</th><th></th></tr></thead>
        <tbody>${items.map(r => `<tr>
          <td><a href="/stock/${encodeURIComponent(r.ticker)}">${_esc(r.ticker)}</a></td>
          <td>${_esc(r.name)}</td>
          <td class="text-dim">${_esc(r.sector || "—")}</td>
          <td class="num">${_rs(r.ltp)}</td>
          <td class="num ${_signCls(r.change_pct)}">${r.change_pct == null ? "—" : `${_signed(r.change)} (${_signedPct(r.change_pct)})`}</td>
          <td data-signal-for="${_esc(r.ticker)}"><span class="text-dim">…</span></td>
          <td class="num"><button class="btn-x" data-remove="${_esc(r.ticker)}" title="Remove ${_esc(r.ticker)}" aria-label="Remove ${_esc(r.ticker)}">✕</button></td>
        </tr>`).join("")}</tbody></table></div>`;
      _fillSignals(body);
    } catch (e) {
      body.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
    }
  }

  body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    b.disabled = true;
    try {
      await acctApi(`/api/me/watchlist/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" });
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; b.disabled = false; }
  });

  document.getElementById("watch-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("watch-add-input");
    const ticker = input.value.trim().toUpperCase();
    if (!ticker) return;
    msg.textContent = ""; msg.className = "form-msg";
    try {
      await acctApi("/api/me/watchlist", { method: "POST", body: { ticker } });
      input.value = "";
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; }
  });

  load();
}

// --- portfolio page -------------------------------------------------------------------
let _sectorChart = null;
const _SECTOR_COLORS = ["#2f6fdb", "#16a34a", "#d97706", "#dc2626", "#8b5cf6", "#0891b2", "#db2777",
                        "#65a30d", "#ea580c", "#475569", "#0d9488", "#a16207", "#6366f1"];

function _renderPortfolio(d) {
  const t = d.totals;
  const setTile = (id, text, cls) => {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className = "value " + (cls || "");
  };
  setTile("pf-value", `Rs ${_rs(t.value_ltp)}`);
  setTile("pf-day", _signed(t.day_pl), _signCls(t.day_pl));
  setTile("pf-count", String(t.count));
  document.getElementById("pf-source").textContent = d.market_open === true ? "market open · live"
    : d.market_open === false ? "market closed" : "last close";

  const wrap = document.getElementById("holdings-wrap");
  if (!d.holdings.length) {
    wrap.innerHTML = `<p class="text-dim mb-0">No holdings yet. Use <strong>+ Add holding</strong> to add a scrip and its quantity.</p>`;
  } else {
    wrap.innerHTML = `<table class="data-table holdings-table">
      <thead><tr><th>#</th><th>Scrip</th><th class="num">Balance</th>
        <th class="num">Last closing price</th><th class="num">Value at last close</th><th class="num">LTP</th><th class="num">Value at LTP</th>
        <th class="num">Today</th><th>Signal</th><th></th></tr></thead>
      <tbody>${d.holdings.map((r, i) => `<tr>
        <td class="text-dim">${i + 1}</td>
        <td><a href="/stock/${encodeURIComponent(r.ticker)}" title="${_esc(r.name)}">${_esc(r.ticker)}</a>
            ${r.priced ? "" : `<span class="text-dim" title="No price available for this scrip">*</span>`}</td>
        <td class="num">${r.quantity.toLocaleString("en-IN")}</td>
        <td class="num">${_rs(r.lcp)}</td>
        <td class="num">${_rs(r.value_lcp)}</td>
        <td class="num">${_rs(r.ltp)}</td>
        <td class="num">${_rs(r.value_ltp)}</td>
        <td class="num ${_signCls(r.day_pl)}">${_signed(r.day_pl)}</td>
        <td data-signal-for="${_esc(r.ticker)}"><span class="text-dim">…</span></td>
        <td class="num text-nowrap">
          <button class="btn-link-sm" data-edit="${_esc(r.ticker)}" data-qty="${r.quantity}">Edit</button>
          <button class="btn-x" data-del="${_esc(r.ticker)}" title="Remove ${_esc(r.ticker)}" aria-label="Remove ${_esc(r.ticker)}">✕</button>
        </td>
      </tr>`).join("")}</tbody>
      <tfoot><tr>
        <td></td><td><strong>Total</strong></td><td></td><td></td>
        <td class="num"><strong>${_rs(t.value_lcp)}</strong></td><td></td>
        <td class="num"><strong>${_rs(t.value_ltp)}</strong></td>
        <td class="num ${_signCls(t.day_pl)}"><strong>${_signed(t.day_pl)}</strong></td><td></td><td></td>
      </tr></tfoot></table>`;
    _fillSignals(wrap);
  }

  // sector doughnut + legend
  const legend = document.getElementById("sector-legend");
  const canvas = document.getElementById("sector-chart");
  if (_sectorChart) { _sectorChart.destroy(); _sectorChart = null; }
  if (!d.sectors.length) {
    legend.innerHTML = `<span class="text-dim">Add a holding to see your sector mix.</span>`;
    canvas.style.display = "none";
  } else {
    canvas.style.display = "";
    legend.innerHTML = d.sectors.map((s, i) => `<div class="legend-row">
      <span class="dot" style="background:${_SECTOR_COLORS[i % _SECTOR_COLORS.length]}"></span>
      <span class="grow">${_esc(s.sector)}</span><span class="num">${s.share_pct}%</span></div>`).join("");
    if (window.Chart) {
      _sectorChart = new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: d.sectors.map(s => s.sector),
          datasets: [{ data: d.sectors.map(s => s.value),
                       backgroundColor: d.sectors.map((_, i) => _SECTOR_COLORS[i % _SECTOR_COLORS.length]),
                       borderWidth: 0 }],
        },
        options: { plugins: { legend: { display: false },
                              tooltip: { callbacks: { label: (c) => ` ${c.label}: Rs ${_rs(c.parsed)}` } } },
                   cutout: "62%" },
      });
    }
  }

}

async function initPortfolioPage() {
  const wrap = document.getElementById("holdings-wrap");
  if (!wrap) return;
  _fillTickerOptions();

  async function load() {
    try {
      _renderPortfolio(await acctApi("/api/me/portfolio"));
    } catch (e) {
      wrap.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
    }
  }

  const modalEl = document.getElementById("tx-modal");
  const form = document.getElementById("tx-form");
  const msg = document.getElementById("tx-msg");
  const modal = () => bootstrap.Modal.getOrCreateInstance(modalEl);
  function openModal(prefill = {}) {
    msg.textContent = ""; msg.className = "form-msg";
    form.ticker.value = prefill.ticker || "";
    form.quantity.value = prefill.quantity || "";
    document.getElementById("tx-modal-title").textContent = prefill.quantity ? `Edit ${prefill.ticker}` : "Add holding";
    modal().show();
    setTimeout(() => (prefill.ticker ? form.quantity : form.ticker).focus(), 300);
  }
  document.getElementById("open-tx-modal").addEventListener("click", () => openModal());

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = ""; msg.className = "form-msg";
    const fd = new FormData(form);
    const btn = document.getElementById("tx-submit");
    btn.disabled = true;
    try {
      await acctApi("/api/me/holdings", { method: "POST", body: {
        ticker: String(fd.get("ticker")).trim().toUpperCase(), quantity: fd.get("quantity"),
      } });
      form.quantity.value = ""; form.ticker.value = "";
      modal().hide();
      await load();
    } catch (err) {
      msg.textContent = err.message; msg.className = "form-msg error";
    } finally {
      btn.disabled = false;
      // a disabled button drops focus to <body>, where Esc no longer closes the dialog
      if (document.activeElement === document.body) modalEl.focus();
    }
  });

  wrap.addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-edit]");
    if (ed) { openModal({ ticker: ed.dataset.edit, quantity: ed.dataset.qty }); return; }
    const b = e.target.closest("[data-del]");
    if (!b || !confirm(`Remove ${b.dataset.del} from your portfolio?`)) return;
    b.disabled = true;
    try {
      await acctApi(`/api/me/holdings/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
      await load();
    } catch (err) { alert(err.message); b.disabled = false; }
  });

  const add = new URLSearchParams(location.search).get("add");
  await load();
  if (add) openModal({ ticker: add.toUpperCase() });
}

/* ---- Sign-up / password forms: show-hide toggle, live confirm check, email suggestions ---- */
(function () {
  function addToggle(input) {
    if (input.closest('.pw-wrap')) return;
    var wrap = document.createElement('span');
    wrap.className = 'pw-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle';
    btn.textContent = 'Show';
    btn.setAttribute('aria-label', 'Show password');
    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      btn.setAttribute('aria-pressed', show ? 'true' : 'false');
    });
    wrap.appendChild(btn);
    // never leave a password visible after the form is sent
    if (input.form) input.form.addEventListener('submit', function () {
      input.type = 'password'; btn.textContent = 'Show'; btn.setAttribute('aria-pressed', 'false');
    });
  }

  function wireConfirm(form) {
    var confirm = form.querySelector('input[name=confirm]');
    var pw = form.querySelector('input[name=password], input[name=new_password]');
    if (!confirm || !pw) return;
    var msg = form.querySelector('[data-confirm-msg]');
    if (!msg) {
      msg = document.createElement('small');
      msg.className = 'field-error';
      msg.setAttribute('data-confirm-msg', '');
      msg.textContent = "Passwords don't match.";
      msg.hidden = true;
      confirm.closest('label').appendChild(msg);
    }
    function check() {
      var bad = confirm.value !== '' && confirm.value !== pw.value;
      confirm.classList.toggle('invalid', bad);
      confirm.setAttribute('aria-invalid', bad ? 'true' : 'false');
      msg.hidden = !bad;
    }
    confirm.addEventListener('input', check);
    pw.addEventListener('input', check);
  }

  function init() {
    document.querySelectorAll('input[type=password]').forEach(addToggle);
    document.querySelectorAll('form').forEach(wireConfirm);
    document.querySelectorAll('.suggest-chip').forEach(function (b) {
      b.addEventListener('click', function () {
        var email = document.querySelector('input[name=email]');
        if (!email) return;
        email.value = b.getAttribute('data-email');
        email.classList.remove('invalid');
        var err = email.parentNode.querySelector('.field-error');
        if (err) err.remove();
        email.focus();
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
