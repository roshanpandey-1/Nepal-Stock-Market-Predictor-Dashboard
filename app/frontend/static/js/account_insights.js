// Rule-based checks on the signed-in user's own portfolio and watchlist.
// Relies on the helpers in account.js (_esc, _signedPct, _signCls, acctApi) which load first.

function _piFlags(flags, empty) {
  const watch = (flags || []).filter((f) => f.level !== "info");
  const info = (flags || []).filter((f) => f.level === "info");
  if (!watch.length && !info.length) return empty ? `<span class="text-dim">${_esc(empty)}</span>` : "";
  const li = (f, cls) => `<li class="${cls}">${_esc(f.text)}<span class="an-rule">Rule: ${_esc(f.rule)}</span></li>`;
  return `<ul class="an-obs caut pi-flags">${watch.map((f) => li(f, "")).join("")}${info.map((f) => li(f, "pi-info")).join("")}</ul>`;
}

function _piTile(label, value, sub, cls) {
  return `<div class="col-6 col-lg"><div class="stat-tile sm"><div class="label">${_esc(label)}</div>
    <div class="value ${cls || ""}">${value}</div>${sub ? `<div class="hint">${sub}</div>` : ""}</div></div>`;
}

const _pct = (v) => v == null ? "—" : `${v}%`;

function _renderPortfolioInsights(box, d) {
  if (d.empty) { box.innerHTML = `<p class="text-dim mb-0">Add a holding to see checks on your portfolio.</p>`; return; }
  const c = d.concentration, r = d.risk;
  let html = `<p class="an-asof">As of the ${_esc(d.as_of || "latest")} session. ${_esc(d.basis)}</p>`;

  html += `<h4 class="pi-h">How spread out is it?</h4>`;
  if (c) {
    html += `<div class="row g-2 mb-2">
      ${_piTile("Largest holding", `${_esc(c.largest.ticker)} <small>${_pct(c.largest.share_pct)}</small>`)}
      ${_piTile("Top 3 holdings", _pct(c.top3_pct))}
      ${_piTile("Effective holdings", c.effective_holdings == null ? "—" : String(c.effective_holdings), `of ${c.holdings} held`)}
      ${_piTile("Biggest sector", c.sectors.length ? `${_esc(c.sectors[0].sector)} <small>${_pct(c.sectors[0].share_pct)}</small>` : "—")}
    </div>`;
    html += _piFlags(c.flags, "No concentration flags under the rules below.");
    html += `<p class="an-note text-dim">${_esc(c.note)} Flags fire when one stock is over 25% of the portfolio, the top three are over 60% (with 5+ holdings), one sector is over 40%, or you hold fewer than 5 stocks.</p>`;
  } else {
    html += `<p class="text-dim">Not enough priced holdings to measure this.</p>`;
  }

  html += `<h4 class="pi-h">How bumpy has it been?</h4>`;
  if (r) {
    const vs = (mine, med) => med == null ? "" : `median tracked stock ${_esc(_signedPct(med))}`;
    html += `<div class="row g-2 mb-2">
      ${_piTile("Volatility (yearly)", _pct(r.volatility_pct), `from ${r.sessions} sessions`)}
      ${_piTile("Worst fall", _pct(r.max_drawdown_pct), "peak to trough", "neg")}
      ${_piTile("1 month", r.ret_1m == null ? "—" : _esc(_signedPct(r.ret_1m)), vs(r.ret_1m, r.median_stock_1m), _signCls(r.ret_1m))}
      ${_piTile("3 months", r.ret_3m == null ? "—" : _esc(_signedPct(r.ret_3m)), vs(r.ret_3m, r.median_stock_3m), _signCls(r.ret_3m))}
    </div>`;
    if (r.variance_share && r.variance_share.length) {
      html += `<div class="table-scroll"><table class="data-table an-table"><thead><tr><th>Holding</th>
        <th class="num">Share of value</th><th class="num">Share of day-to-day swings</th></tr></thead><tbody>
        ${r.variance_share.map((v) => `<tr><td><a href="/stock/${encodeURIComponent(v.ticker)}">${_esc(v.ticker)}</a></td>
          <td class="num">${_pct(v.weight_pct)}</td><td class="num">${_pct(v.risk_share_pct)}</td></tr>`).join("")}
        </tbody></table></div>`;
    }
    if (r.missing && r.missing.length) html += `<p class="an-note text-dim">No price history for: ${_esc(r.missing.join(", "))} (left out).</p>`;
    html += `<p class="an-note text-dim">${_esc(r.note)}</p>`;
  } else {
    html += `<p class="text-dim">Needs at least 60 sessions of price history for your holdings.</p>`;
  }

  html += `<h4 class="pi-h">Each holding</h4><div class="table-scroll"><table class="data-table an-table">
    <thead><tr><th>Stock</th><th>Trend</th><th class="num">RSI</th><th class="num">1 month</th><th>Worth a look</th></tr></thead><tbody>
    ${d.holdings.map((h) => `<tr><td><a href="/stock/${encodeURIComponent(h.ticker)}" title="${_esc(h.name || "")}">${_esc(h.ticker)}</a></td>
      <td>${_esc(h.trend || "—")}</td><td class="num">${h.rsi_14 == null ? "—" : h.rsi_14}</td>
      <td class="num ${_signCls(h.ret_1m)}">${h.ret_1m == null ? "—" : _esc(_signedPct(h.ret_1m))}</td>
      <td>${_piFlags(h.flags, "Nothing flagged.")}</td></tr>`).join("")}</tbody></table></div>`;
  html += `<p class="an-disclaimer">${_esc(d.disclaimer)}</p>`;
  box.innerHTML = html;
}

async function initPortfolioInsights() {
  const box = document.getElementById("pf-insights");
  if (!box) return;
  let busy = false;
  async function load() {
    if (busy) return;
    busy = true;
    try { _renderPortfolioInsights(box, await acctApi("/api/me/portfolio/insights")); }
    catch (e) { box.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`; }
    busy = false;
  }
  // The holdings table re-renders after every change (and while the market is open); refresh the checks
  // only when the set of holdings or their quantities change, not on every price refresh.
  let last = null;
  document.addEventListener("portfolio:loaded", (e) => {
    const key = JSON.stringify((e.detail || []).map((h) => [h.ticker, h.quantity]));
    if (key !== last) { last = key; load(); }
  });
}

function _renderWatchlistInsights(box, d) {
  if (d.empty) { box.innerHTML = ""; return; }
  const s = d.summary;
  let html = `<h3>Watchlist check</h3><p class="an-asof">As of the ${_esc(d.as_of || "latest")} session. ${_esc(d.basis)}</p>`;
  const bits = [];
  if (s.biggest_gain) bits.push(`Biggest gain: <strong>${_esc(s.biggest_gain.ticker)}</strong> ${_esc(_signedPct(s.biggest_gain.change_pct))}`);
  if (s.biggest_fall) bits.push(`Biggest fall: <strong>${_esc(s.biggest_fall.ticker)}</strong> ${_esc(_signedPct(s.biggest_fall.change_pct))}`);
  bits.push(`${s.with_flags} of ${s.count} have something worth a look`);
  html += `<p class="mb-2">${bits.join(" · ")}</p>`;
  html += `<div class="table-scroll"><table class="data-table an-table"><thead><tr><th>Stock</th><th class="num">Last session</th>
    <th class="num">1 week</th><th class="num">1 month</th><th>Trend</th><th class="num">RSI</th><th class="num">Volume vs avg</th>
    </tr></thead><tbody>
    ${d.rows.map((r) => r.missing
      ? `<tr><td>${_esc(r.ticker)}</td><td colspan="6" class="text-dim">No price data for this symbol.</td></tr>`
      : `<tr><td><a href="/stock/${encodeURIComponent(r.ticker)}" title="${_esc(r.name || "")}">${_esc(r.ticker)}</a>
          ${r.traded_on_market_date ? "" : `<span class="text-dim" title="Did not trade in the latest session">*</span>`}
          <div class="text-dim" style="font-size:.74rem;">${_esc(r.sector || "")}</div></td>
        <td class="num ${_signCls(r.change_pct)}">${r.change_pct == null ? "—" : _esc(_signedPct(r.change_pct))}</td>
        <td class="num ${_signCls(r.ret_1w)}">${r.ret_1w == null ? "—" : _esc(_signedPct(r.ret_1w))}</td>
        <td class="num ${_signCls(r.ret_1m)}">${r.ret_1m == null ? "—" : _esc(_signedPct(r.ret_1m))}</td>
        <td>${_esc(r.trend || "—")}</td><td class="num">${r.rsi_14 == null ? "—" : r.rsi_14}</td>
        <td class="num">${r.relative_volume == null ? "—" : `${r.relative_volume}x`}</td></tr>
      <tr class="pi-detail"><td></td><td colspan="6"><div class="pi-detail-grid">
        <div><div class="pi-sub">Worth a look</div>${_piFlags(r.flags, "Nothing flagged.")}</div>
        <div><div class="pi-sub">Recent headlines (14 days)</div>${r.recent_news.length ? `<ul class="pi-news">${r.recent_news.map((n) => `<li><a href="${_esc(n.url)}" target="_blank" rel="noopener noreferrer">${_esc(n.title)}</a>
            <span class="an-rule">${_esc(n.date)} · ${_esc(n.category_label || "")}</span></li>`).join("")}</ul>` : `<span class="text-dim">None</span>`}</div>
      </div></td></tr>`).join("")}
    </tbody></table></div>
    <p class="an-note text-dim">* did not trade in the latest session. Checks are fixed rules on end-of-day data; headlines are matched to a company by name from ShareSansar and some may be missed. Not a recommendation to buy or sell.</p>`;
  box.innerHTML = html;
}

async function initWatchlistInsights() {
  const box = document.getElementById("wl-insights");
  if (!box) return;
  let last = null, busy = false;
  document.addEventListener("watchlist:loaded", async (e) => {
    const key = JSON.stringify((e.detail || []).map((h) => h.ticker));
    if (key === last || busy) return;
    last = key; busy = true;
    try { _renderWatchlistInsights(box, await acctApi("/api/me/watchlist/insights")); }
    catch (err) { box.innerHTML = `<p class="text-dim mb-0">${_esc(err.message)}</p>`; }
    busy = false;
  });
}
