// Alerts page. Relies on account.js (acctApi, _esc, _wirePicker, _resolveSymbol).
async function initAlertsPage() {
  const list = document.getElementById("alert-list");
  if (!list) return;
  const form = document.getElementById("alert-form");
  const msg = document.getElementById("alert-msg");
  const kindSel = document.getElementById("alert-kind");
  const valueWrap = document.getElementById("alert-value-wrap");
  const valueInput = document.getElementById("alert-threshold");
  const catWrap = document.getElementById("alert-cat-wrap");
  const catSel = document.getElementById("alert-category");
  let kinds = [];

  _wirePicker("alert-ticker", "alert-ticker-results", (row) => { form.ticker.value = row.t; kindSel.focus(); });

  function syncKind() {
    const k = kinds.find((x) => x.kind === kindSel.value);
    if (!k) return;
    valueWrap.hidden = !k.needs_value;
    document.getElementById("alert-value-label").textContent =
      k.unit === "Rs" ? "Price (Rs)" : k.unit === "%" ? "Percent" : k.unit === "x" ? "Times average" : "Level";
    valueInput.value = k.default == null ? "" : k.default;
    valueInput.required = k.needs_value;
    catWrap.hidden = k.kind !== "announcement";
  }
  kindSel.addEventListener("change", syncKind);

  async function load() {
    try {
      const d = await acctApi("/api/me/alerts");
      if (!kinds.length) {
        kinds = d.kinds;
        kindSel.innerHTML = kinds.map((k) => `<option value="${_esc(k.kind)}">${_esc(k.label)}</option>`).join("");
        catSel.innerHTML += d.categories.map((c) => `<option value="${_esc(c)}">${_esc(c.replace(/_/g, " "))}</option>`).join("");
        syncKind();
      }
      document.getElementById("alert-email").textContent = d.email;
      document.getElementById("alert-count").textContent = `${d.alerts.length} of ${d.max}`;
      if (!d.alerts.length) {
        list.innerHTML = `<p class="text-dim mb-0">No alerts yet. Add one above, for example <em>NABIL closes at or above a price</em>.</p>`;
        return;
      }
      list.innerHTML = `<div class="table-scroll"><table class="data-table an-table"><thead><tr><th>Stock</th><th>Alert when</th>
        <th>Status</th><th>Last alert</th><th></th></tr></thead><tbody>
        ${d.alerts.map((a) => `<tr>
          <td><a href="/stock/${encodeURIComponent(a.ticker)}">${_esc(a.ticker)}</a></td>
          <td>${_esc(a.description)}</td>
          <td>${!a.active ? `<span class="text-dim">Paused</span>`
              : a.met_now ? `<span title="It is true now, so you will be emailed after it stops being true and becomes true again">Met now, waiting to re-arm</span>`
              : `<span>Watching</span>`}</td>
          <td class="text-dim">${a.last_fired ? `${_esc(a.last_fired)}` : "Never"}</td>
          <td class="num text-nowrap">
            <button class="btn-link-sm" data-toggle="${a.id}" data-active="${a.active ? 1 : 0}">${a.active ? "Pause" : "Resume"}</button>
            <button class="btn-x" data-del="${a.id}" title="Delete alert" aria-label="Delete alert for ${_esc(a.ticker)}">✕</button>
          </td></tr>`).join("")}</tbody></table></div>`;
    } catch (e) {
      list.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = ""; msg.className = "form-msg";
    const btn = document.getElementById("alert-submit");
    btn.disabled = true;
    try {
      const ticker = await _resolveSymbol(form.ticker.value);
      if (!ticker) throw new Error("Pick a stock first.");
      await acctApi("/api/me/alerts", { method: "POST", body: {
        ticker, kind: kindSel.value, threshold: valueInput.value, category: catSel.value } });
      form.ticker.value = "";
      msg.textContent = "Alert added."; msg.className = "form-msg ok";
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; }
    btn.disabled = false;
  });

  list.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-toggle]");
    const d = e.target.closest("[data-del]");
    try {
      if (t) {
        await acctApi(`/api/me/alerts/${t.dataset.toggle}`, { method: "PATCH", body: { active: t.dataset.active !== "1" } });
      } else if (d && confirm("Delete this alert?")) {
        await acctApi(`/api/me/alerts/${d.dataset.del}`, { method: "DELETE" });
      } else return;
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; }
  });

  load();
}
