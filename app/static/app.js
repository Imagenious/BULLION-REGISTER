// Bullion Register — small progressive enhancements. Every calculation is done by the server.
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  async function postForm(url, form) {
    const res = await fetch(url, { method: "POST", body: new FormData(form), headers: { "X-CSRFToken": csrf }, credentials: "same-origin" });
    if (!res.ok) throw new Error(res.status);
    return res.text();
  }

  // Confirmation on destructive forms
  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset && e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Karat shortcut selects fill a purity box
  document.querySelectorAll("[data-purity-target]").forEach((sel) => {
    sel.addEventListener("change", () => {
      const box = document.getElementById(sel.dataset.purityTarget);
      if (!box) return;
      box.value = sel.value || "";
      if (!sel.value) box.focus();
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });

  // ---------------- old-gold item rows: fine = net × purity %, value = fine × buying rate
  const inr = (n) => "₹" + Math.round(n).toLocaleString("en-IN");
  const g3 = (n) => n.toLocaleString("en-IN", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  const num = (v) => { const n = parseFloat(v); return isFinite(n) ? n : 0; };

  function goldTotals(box) {
    let net = 0, fine = 0, value = 0, count = 0;
    box.querySelectorAll("[data-row]").forEach((row) => {
      const [desc, netEl, purEl, rateEl] = row.querySelectorAll("input");
      let pur = num(purEl.value); if (pur > 100) pur /= 10;          // 700 ‰ = 70 %
      const n = num(netEl.value), f = Math.round(n * pur / 100 * 1000) / 1000, v = f * num(rateEl.value);
      row.querySelector("[data-fine]").textContent = n && pur ? g3(f) : "—";
      row.querySelector("[data-value]").textContent = n && pur && num(rateEl.value) ? inr(v) : "—";
      if (n && pur) { net += n; fine += f; value += v; count += 1; }
    });
    box.querySelector('[data-t="net"]').textContent = g3(net);
    box.querySelector('[data-t="fine"]').textContent = g3(fine);
    box.querySelector('[data-t="value"]').textContent = inr(value);
    box.querySelector("[data-count]").textContent = count;
  }
  // Fill buying-rate cells the user hasn't typed in.
  function setGoldRate(box, rate) {
    box.dataset.defaultRate = rate || "";
    box.querySelectorAll('input[name$="item_rate"]').forEach((el) => { if (!el.dataset.touched) el.value = rate || ""; });
    goldTotals(box);
  }
  document.querySelectorAll("[data-gold-items]").forEach((box) => {
    const tbody = box.querySelector("tbody");
    box.addEventListener("input", (e) => {
      if (e.isTrusted && e.target.name && e.target.name.endsWith("item_rate")) e.target.dataset.touched = "1";
      goldTotals(box);
    });
    box.querySelector("[data-add-item]").addEventListener("click", () => {
      const row = tbody.querySelector("[data-row]").cloneNode(true);
      row.querySelectorAll("input").forEach((el) => { el.value = el.name.endsWith("item_rate") ? (box.dataset.defaultRate || "") : ""; delete el.dataset.touched; });
      tbody.appendChild(row);
      row.querySelector("input").focus();
      goldTotals(box);
    });
    box.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove-item]");
      if (!btn) return;
      const rows = tbody.querySelectorAll("[data-row]");
      const row = btn.closest("[data-row]");
      if (rows.length > 1) row.remove();
      else row.querySelectorAll("input").forEach((el) => { if (!el.name.endsWith("item_rate")) el.value = ""; });
      goldTotals(box);
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    goldTotals(box);
  });

  // ---------------- order form: live working from the server
  const of = document.getElementById("order-form");
  if (of) {
    const body = document.getElementById("calc-body");
    const touch = JSON.parse(of.dataset.touch || "{}");
    const touched = new Set();
    const setIf = (id, val) => {
      const el = document.getElementById(id);
      if (!el || touched.has(id) || val === undefined || el.value === String(val)) return false;
      el.value = val;
      return true;
    };

    function syncMode() {
      const mode = of.querySelector('input[name="c_mode"]:checked')?.value || "touch";
      of.querySelectorAll("[data-mode]").forEach((el) => { el.hidden = el.dataset.mode !== mode; });
    }
    function syncBook() {
      const cb = document.getElementById("book_adv"), f = document.getElementById("book-fields");
      if (cb && f) f.hidden = !cb.checked;
    }
    const refresh = debounce(async () => {
      try {
        body.innerHTML = await postForm(of.dataset.preview, of);
        const s = document.getElementById("sugg");
        if (s) {
          // Fill suggestions the user hasn't typed over; re-run once so the working includes them.
          const changed = [setIf("adv_cash", s.dataset.cash || ""), setIf("book_amt", s.dataset.book || ""),
                           setIf("book_rate", s.dataset.rate || "")].some(Boolean);
          if (changed) refresh();
        }
      } catch (err) { /* keep the last working on a network hiccup */ }
    }, 250);

    of.addEventListener("input", (e) => {
      if (e.isTrusted && e.target.id) touched.add(e.target.id);
      if (e.target.id === "rate24") of.querySelectorAll("[data-gold-items]").forEach((b) => setGoldRate(b, e.target.value));
      if (e.target.id === "adv_cash") { touched.delete("book_amt"); }
      refresh();
    });
    of.addEventListener("change", (e) => {
      if (e.target.id === "karat" && touch[e.target.value]) {
        document.getElementById("c_touch").value = touch[e.target.value].c;
        document.getElementById("k_touch").value = touch[e.target.value].k;
      }
      if (e.target.name === "c_mode") syncMode();
      if (e.target.id === "book_adv") syncBook();
      refresh();
    });
    document.getElementById("btn-sugg")?.addEventListener("click", () => {
      touched.delete("adv_cash"); touched.delete("book_amt");
      const s = document.getElementById("sugg");
      if (s) { document.getElementById("adv_cash").value = s.dataset.cash || ""; }
      refresh();
    });
    syncMode(); syncBook(); refresh();
  }

  // ---------------- dashboard: record an advance
  const qf = document.getElementById("quick-form");
  if (qf) {
    const hint = document.getElementById("q-hint");
    function syncKind() {
      const kind = qf.querySelector('input[name="kind"]:checked')?.value || "cash";
      qf.querySelectorAll("[data-for]").forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(kind); });
      if (kind === "cash") document.getElementById("q-rate-f").hidden = !document.getElementById("q-booknow").checked;
    }
    const preview = debounce(async () => {
      try { hint.textContent = await postForm(qf.dataset.preview, qf); } catch (err) { /* ignore */ }
    }, 250);
    const orderSel = document.getElementById("q-order");
    const syncOrderRate = () => {
      const rate = orderSel.selectedOptions[0]?.dataset.rate || "";
      qf.querySelectorAll("[data-gold-items]").forEach((b) => setGoldRate(b, rate));
    };
    orderSel.addEventListener("change", syncOrderRate);
    syncOrderRate();
    qf.addEventListener("change", () => { syncKind(); preview(); });
    qf.addEventListener("input", preview);
    syncKind();
    if (document.getElementById("q-order").value) preview();
  }
})();
