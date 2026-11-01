// Interface only. Every decision comes from engine.js.
import * as E from "./engine.js";

const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const num = n => Math.round(n).toLocaleString("en-US");
const LEVEL = { Low: "var(--good)", Elevated: "var(--warn)", High: "var(--bad)" };
const CAT = ["var(--good)", "var(--warn)", "var(--bad)"];

const D = await (await fetch("data.json")).json();
const blank = { state: "MO", month: 7, product: "Ground chicken", lot_lb: 10000, fsis_category: 1,
  has_cooked_line: false, customer_limit: false, lot_result: "none", cfu_per_g: "", hours_above_40f: 0,
  max_hours_above_40f: E.DEFAULTS.maxHours, plant_samples: 0, plant_positives: 0 };
const ui = { s: { ...blank }, detect: E.DEFAULTS.detect, donate: E.DEFAULTS.donate, tab: "why" };

/* Form */
$("state").innerHTML = Object.entries(D.stateNames).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
$("product").innerHTML = Object.keys(D.products).map(p => `<option>${esc(p)}</option>`).join("");
const radios = (id, key, opts) => $(id).insertAdjacentHTML("beforeend", "<div>" + opts.map(([v, t]) =>
  `<label><input type="radio" name="${key}" value="${v}"><span>${t}</span></label>`).join("") + "</div>");
radios("cat", "fsis_category", [["", "None"], [1, "1"], [2, "2"], [3, "3"]]);
radios("screen", "lot_result", [["none", "No screen"], ["negative", "Negative"], ["detected", "Detected"]]);

function fillForm() {
  document.querySelectorAll("[data-k]").forEach(el => {
    const v = ui.s[el.dataset.k];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? "";
  });
  document.querySelectorAll("#cat input").forEach(r => r.checked = r.value === String(ui.s.fsis_category ?? ""));
  document.querySelectorAll("#screen input").forEach(r => r.checked = r.value === ui.s.lot_result);
  $("donate").value = ui.donate * 100; $("detect").value = ui.detect * 100;
}

$("lot").addEventListener("input", e => {
  const el = e.target, k = el.dataset.k;
  if (k) ui.s[k] = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
  if (el.name === "fsis_category") ui.s.fsis_category = el.value ? Number(el.value) : null;
  if (el.name === "lot_result") ui.s.lot_result = el.value;
  if (el.id === "donate") ui.donate = el.value / 100;
  if (el.id === "detect") ui.detect = el.value / 100;
  render();
});
$("lot").addEventListener("submit", e => e.preventDefault());
$("print")?.addEventListener("click", () => window.print());

const SHORT = ["Category 3 ground chicken", "Category 1 breast", "Stuffed chicken over 1 CFU/g", "Storm outage"];
Object.entries(D.scenarios).forEach(([name, sc], i) => {
  const b = document.createElement("button");
  b.className = "chip"; b.type = "button"; b.textContent = SHORT[i]; b.title = name;
  b.onclick = () => { ui.s = { ...blank, ...sc, cfu_per_g: sc.cfu_per_g || "" }; fillForm(); render(); };
  $("examples").append(b);
});

/* Count-up, in answer to a change the person made */
function count(el, to, fmt) {
  const from = Number(el.dataset.v ?? to), t0 = performance.now();
  el.dataset.v = to;
  if (from === to || matchMedia("(prefers-reduced-motion:reduce)").matches) { el.textContent = fmt(to); return; }
  (function step(t) {
    const p = Math.min((t - t0) / 320, 1), e = 1 - (1 - p) ** 3;
    el.textContent = fmt(from + (to - from) * e);
    if (p < 1 && Number(el.dataset.v) === to) requestAnimationFrame(step);
  })(t0);
}

let lastPick = "";
function render() {
  const s = { ...ui.s, cfu_per_g: ui.s.cfu_per_g || null };
  const P = D.products[s.product], std = D.fsisStandard[P.group];
  const risk = E.riskLevel(s, D), [pick, reason] = E.recommend(s, D);
  const table = E.compareActions(s, D, ui.detect, ui.donate), chosen = table.find(r => r.action === pick);
  const check = E.selfCheck(s, D), own = check && check.status ? check.observed_pct : null;

  $("cfuField").hidden = s.product !== "Raw breaded stuffed chicken";
  $("donateOut").textContent = `${Math.round(ui.donate * 100)}%`;
  $("detectOut").textContent = `${Math.round(ui.detect * 100)}%`;

  const tag = $("tag");
  tag.style.setProperty("--level", LEVEL[risk.level]);
  $("level").textContent = `${risk.level} risk`;
  $("action").textContent = pick;
  $("reason").textContent = reason;
  if (pick !== lastPick) { tag.classList.remove("changed"); void tag.offsetWidth; tag.classList.add("changed"); lastPick = pick; }

  const top = Math.max(std * 2, risk.pct * 1.12, (own || 0) * 1.12), x = v => 100 * v / top;
  $("z1").style.width = `${x(std / 2)}%`; $("z2").style.width = `${x(std / 2)}%`; $("z3").style.width = `${100 - x(std)}%`;
  $("pin").style.left = `${x(risk.pct)}%`;
  $("pinOwn").hidden = own == null; $("ownLabel").hidden = own == null;
  if (own != null) { $("pinOwn").style.left = `${x(own)}%`; $("ownLabel").textContent = `Blue marker: your samples, ${own.toFixed(1)}%`; }
  $("tickHalf").style.left = `${x(std / 2)}%`; $("tickHalf").textContent = `Half ${std / 2}%`;
  $("tickStd").style.left = `${x(std)}%`; $("tickStd").textContent = `FSIS standard ${std}%`;
  $("readout").innerHTML = `<b>${risk.pct.toFixed(1)}%</b> expected positive next year`;
  $("gauge").setAttribute("aria-label", `Expected positivity ${risk.pct} percent, FSIS standard ${std} percent`);
  $("printmeta").textContent = `${s.product}, ${num(s.lot_lb)} lb, ${D.stateNames[s.state]}. Printed ` +
    `${new Date().toLocaleDateString("en-US")}. Decision support, not a regulatory determination. Reviewed by: ____________`;

  count($("oExp"), chosen.exposure_index, v => v.toFixed(2));
  count($("oServ"), chosen.servings_kept, num);
  count($("oNeed"), chosen.servings_to_need, num);
  $("oProt").textContent = `${num(chosen.protein_kg)} kg protein`;
  $("oNeedNote").textContent = chosen.servings_to_need ? `${Math.round(ui.donate * 100)}% of the lot after a validated cook` : "This action sends none";

  ui.ctx = { s, P, risk, pick, table, check };
  $("panel").innerHTML = PANELS[ui.tab]();
}

/* Tabs */
const PANELS = {
  why() {
    const { s, risk, check } = ui.ctx, L = D.live[s.state], month = Number(L.period.slice(-2));
    const storm = D.storms[`${s.state}|${month}`];
    let self = "";
    if (check) {
      self = `<div class="plate"><h3>Your plant's self-check</h3><p>${esc(check.message)}</p>` +
        (check.published_note ? `<p class="alert">${esc(check.published_note)}</p>` : "") +
        `<p class="note">${esc(E.SELF_CHECK_NOTE)}</p></div>`;
    }
    return `<div class="grid2"><div class="plate"><h3>What drove this</h3><ul class="reasons">${
      risk.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <p class="note">Salmonella-positive raw poultry is generally not adulterated. The exception is the narrow
      2024 determination for raw breaded stuffed chicken, where FSIS verification sampling is delayed.</p></div>
      ${self}<div class="plate"><h3>${esc(D.stateNames[s.state])}, ${esc(L.period)}</h3>
      <p>About <b>${Math.round(L.expected_cases)}</b> poultry-associated human cases expected (80% range
      ${Math.round(L.low_80)} to ${Math.round(L.high_80)}; three-year average ${Math.round(L.baseline_3y)}),
      ${L.alert ? "above" : "within"} the alert level. Heat, flood or tropical events in this month:
      ${storm ?? 0} of 12 years.</p><p class="note">State figures are context. They do not change the risk level.</p></div></div>`;
  },
  compare() {
    const { table, pick, P } = ui.ctx;
    const mE = Math.max(...table.map(r => r.exposure_index), .01), mS = Math.max(...table.map(r => r.servings_kept), 1);
    const bar = (v, m, t) => `<span class="bar"><i style="width:${Math.round(70 * v / m)}px"></i>${t}</span>`;
    return `<p class="lead">Every option on the same outcomes. Select a row for its conditions.</p>
      <div class="opthead"><span>Option</span><span>Exposure index</span><span>Servings kept</span><span>To high-need counties</span><span>Food lost</span></div>` +
      table.map(r => `<details class="opt ${r.action === pick ? "pick" : r.feasible ? "" : "no"}"><summary>
        <span class="name">${esc(r.action)}${r.feasible ? "" : " (not possible here)"}</span>
        ${bar(r.exposure_index, mE, r.exposure_index.toFixed(2))}${bar(r.servings_kept, mS, num(r.servings_kept))}
        <span>${num(r.servings_to_need)}</span><span>${Math.round(r.food_lost_pct)}%</span></summary><p>${esc(r.note)}</p></details>`).join("") +
      `<p class="note">Exposure index: national chicken parts sold raw = 1.0, scaled by what lines in your FSIS category
      measured the following year. It is relative, not a count of illnesses. ${esc(P.note)}</p>`;
  },
  donate() {
    const { s, table } = ui.ctx, donated = Math.max(...table.map(r => r.servings_to_need));
    const rows = E.donationTargets(s.state, D, donated);
    return `<p class="lead">${donated ? `${num(donated)} servings could reach the highest-need counties in ${esc(D.stateNames[s.state])}.`
      : `Highest-need counties in ${esc(D.stateNames[s.state])}. Turn on a validated cooked line to plan a donation.`}</p>` +
      rows.map(r => `<div class="county"><div><b>${esc(r.county)}</b>
        <small>${r.food_insecure_pct != null ? `${r.food_insecure_pct}% of adults food insecure` : "No CDC estimate here"}</small></div>
        <div><small>Need score ${r.need_score.toFixed(2)}</small><div class="needbar"><i style="width:${r.need_score * 100}%"></i></div></div>
        <div><b>${num(r.servings)}</b><small>servings</small></div>
        <div>${r.food_orgs ? `${r.food_orgs} food org${r.food_orgs > 1 ? "s" : ""} listed<small>Largest: ${esc(r.largest_food_org)}</small>`
          : `<span class="gap">No food org listed</span><small>Find a local partner first</small>`}</div></div>`).join("") +
      `<p class="note">Need combines CDC food insecurity (modeled, not in every state), CDC Social Vulnerability Index and USDA
      low-income, low-access share. Food organizations come from the IRS list, which misses many church pantries, so confirm
      capacity directly. Donated cooked product needs Listeria controls (9 CFR 430) and cold chain to the food bank.</p>`;
  },
  evidence() {
    const e = D.evidence, t = e.publishedTest, g = e.alert.find(a => a.split === "test_2024_on");
    const mae = e.accuracy.filter(a => a.model === "m0").map(a => a.gain_vs_best_baseline_pct);
    const high = e.persistence.find(p => p.high), low = e.persistence.find(p => !p.high);
    return `<h2>A plant's FSIS category predicts its next year</h2>
      <p class="lead">Share of FSIS routine samples positive after a line received each published category. Hover or focus a bar for counts.</p>
      <div class="plate">${chart(e.published.filter(r => r.product_group !== "Turkey carcass"))}</div>
      <p class="note">Four archived FSIS postings, 2022 to 2025, scored on the samples that followed each one. Whiskers show 95% intervals
      that resample plants. Few Category 1 and 2 ground lines qualify, so those rates are less certain.</p>
      <div class="stats">
        <div><b>${t.improvement_pct}% better</b><span>than product alone on ${num(t.test_samples)} held-out samples (Brier score, 95% CI ${t.improvement_ci[0]} to ${t.improvement_ci[1]})</span></div>
        <div><b>${(high.share_high_next * 100).toFixed(1)}%</b><span>of high plant quarters repeat next quarter, against ${(low.share_high_next * 100).toFixed(1)}% of others</span></div>
        <div><b>${Math.min(...mae)} to ${Math.max(...mae)}%</b><span>lower error than fair baselines for the three-month state case forecast</span></div>
      </div>
      <div class="grid2"><div class="plate"><h3>What did not hold up</h3>
        <p>Adding FSIS, weather and storm data did not improve the state case forecast.</p>
        <p>The state alert beat its base rate overall (${(g.precision * 100).toFixed(1)}% vs ${(g.surge_rate * 100).toFixed(1)}%), then failed in 2026.
        We do not know why, so it does not affect the risk level.</p></div>
        <div class="plate"><h3>Alert precision by year</h3>${e.alertYears.map(y => `<div class="yr"><span>${y.year}</span>
          <div class="needbar"><i style="width:${y.precision * 100}%"></i></div><span>${(y.precision * 100).toFixed(1)}%</span></div>`).join("")}
          <p class="note">Threshold set on 2022-2023 and applied unchanged from 2024. Retrospective test on the latest data.</p></div></div>`;
  },
};

function chart(rows) {
  const groups = [...new Set(rows.map(r => r.product_group))], W = 250, H = 240, base = H - 26, top = 34;
  const max = Math.ceil(Math.max(...rows.map(r => r.ci_high)) / 10) * 10, y = v => base - (base - top) * v / max;
  return `<div class="charts">` + groups.map(g => {
    const rs = rows.filter(r => r.product_group === g), std = rs[0].fsis_standard_pct, bw = 46;
    const bars = rs.map((r, j) => {
      const cx = 48 + j * 77, v = r.pct_positive_next_year;
      const tip = `${esc(g)}, Category ${r.category}: ${v}% positive. ${r.plants} plants, ${num(r.samples)} samples`;
      return `<g class="b" data-tip="${tip}" tabindex="0" aria-label="${tip}"><rect x="${cx - bw / 2}" y="${y(v)}" width="${bw}" height="${base - y(v)}" rx="3" fill="${CAT[r.category - 1]}"/>
        <path d="M${cx} ${y(r.ci_low)}V${y(r.ci_high)}M${cx - 4} ${y(r.ci_low)}h8M${cx - 4} ${y(r.ci_high)}h8" stroke="#12343B" fill="none"/>
        <text x="${cx}" y="${y(r.ci_high) - 6}" text-anchor="middle" font-size="14" font-weight="600">${Math.round(v)}%</text>
        <text x="${cx}" y="${base + 18}" text-anchor="middle" font-size="13">Cat ${r.category}</text></g>`;
    }).join("");
    return `<figure><figcaption>${esc(g)}<small>FSIS standard ${std}%, dotted line</small></figcaption>
      <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(g)} next-year positivity by FSIS category">
      <line x1="6" x2="${W - 6}" y1="${base}" y2="${base}" stroke="#D3DDE0"/>${bars}
      <line x1="6" x2="${W - 6}" y1="${y(std)}" y2="${y(std)}" stroke="#12343B" stroke-dasharray="3 4"/></svg></figure>`;
  }).join("") + `</div>`;
}

function select(tab, focus) {
  ui.tab = tab;
  document.querySelectorAll(".tabs button").forEach(b => {
    const on = b.dataset.t === tab;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    if (on) { $("ink").style.left = `${b.offsetLeft}px`; $("ink").style.width = `${b.offsetWidth}px`; if (focus) b.focus(); }
  });
  render();
}
const tabs = [...document.querySelectorAll(".tabs button")];
tabs.forEach((b, i) => {
  b.onclick = () => select(b.dataset.t);
  b.onkeydown = e => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (d) select(tabs[(i + d + tabs.length) % tabs.length].dataset.t, true);
  };
});

$("panel").addEventListener("mousemove", e => {
  const g = e.target.closest?.(".b"), tip = $("tip");
  tip.hidden = !g;
  if (g) { tip.textContent = g.dataset.tip; tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 12}px`; }
});
$("panel").addEventListener("mouseleave", () => $("tip").hidden = true);
addEventListener("resize", () => select(ui.tab));

fillForm();
await document.fonts?.ready;
select("why");
