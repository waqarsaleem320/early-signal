// Interface only. Every decision comes from engine.js.
import * as E from "./engine.js?v=__V__";

const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const num = n => Math.round(n).toLocaleString("en-US");
const LEVEL = { Low: "var(--good)", Elevated: "var(--warn)", High: "var(--bad)" };
const CAT = ["var(--good)", "var(--warn)", "var(--bad)"];
const TILES = { AK: [0, 0], ME: [0, 11], WI: [1, 6], VT: [1, 10], NH: [1, 11], WA: [2, 1], ID: [2, 2], MT: [2, 3], ND: [2, 4],
  MN: [2, 5], IL: [2, 6], MI: [2, 7], NY: [2, 9], MA: [2, 10], OR: [3, 1], NV: [3, 2], WY: [3, 3], SD: [3, 4], IA: [3, 5],
  IN: [3, 6], OH: [3, 7], PA: [3, 8], NJ: [3, 9], CT: [3, 10], RI: [3, 11], CA: [4, 1], UT: [4, 2], CO: [4, 3], NE: [4, 4],
  MO: [4, 5], KY: [4, 6], WV: [4, 7], VA: [4, 8], MD: [4, 9], DE: [4, 10], AZ: [5, 2], NM: [5, 3], KS: [5, 4], AR: [5, 5],
  TN: [5, 6], NC: [5, 7], SC: [5, 8], DC: [5, 9], OK: [6, 4], LA: [6, 5], MS: [6, 6], AL: [6, 7], GA: [6, 8], HI: [7, 0],
  TX: [7, 4], FL: [7, 9] };

const D = await (await fetch("data.json?v=__V__")).json();
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
  ui.active = null;
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
  b.onclick = () => { openCase(i); };
  $("examples").append(b);
});

function openCase(i) {
  const sc = Object.values(D.scenarios)[i];
  ui.s = { ...blank, ...sc, cfu_per_g: sc.cfu_per_g || "" };
  ui.active = i;
  fillForm();
  select("why");
  scrollTo({ top: 0, behavior: "smooth" });
}

/* Count-up, in answer to a change the person made */
function count(el, to, fmt) {
  const from = Number(el.dataset.v ?? to), t0 = performance.now();
  el.dataset.v = to;
  if (from === to || matchMedia("(prefers-reduced-motion:reduce)").matches) { el.textContent = fmt(to); return; }
  setTimeout(() => { if (Number(el.dataset.v) === to) el.textContent = fmt(to); }, 360);  // final value even if frames are throttled
  (function step(t) {
    const p = Math.min((t - t0) / 320, 1), e = 1 - (1 - p) ** 3;
    el.textContent = fmt(from + (to - from) * e);
    if (p < 1 && Number(el.dataset.v) === to) requestAnimationFrame(step);
  })(t0);
}

let lastPick = "";
function render() {
  const s = { ...ui.s, cfu_per_g: ui.s.cfu_per_g || null, max_hours_above_40f: ui.s.max_hours_above_40f > 0 ? ui.s.max_hours_above_40f : E.DEFAULTS.maxHours };
  const P = D.products[s.product], std = D.fsisStandard[P.group];
  const risk = E.riskLevel(s, D), [pick, reason] = E.recommend(s, D);
  const table = E.compareActions(s, D, ui.detect, ui.donate), chosen = table.find(r => r.action === pick);
  const check = E.selfCheck(s, D), own = check && check.status ? check.observed_pct : null;

  $("cfuField").hidden = s.product !== "Raw breaded stuffed chicken";
  $("assumeNote").hidden = !!s.has_cooked_line;
  document.querySelectorAll(".chip[title]").forEach((b, i) => { b.classList.toggle("on", i === ui.active); b.setAttribute("aria-pressed", i === ui.active); });
  $("donateOut").textContent = `${Math.round(ui.donate * 100)}%`;
  $("detectOut").textContent = `${Math.round(ui.detect * 100)}%`;

  const tag = $("tag");
  tag.style.setProperty("--level", LEVEL[risk.level]);
  $("level").textContent = `${risk.level} risk`;
  $("action").textContent = pick;
  $("reason").textContent = reason + (s.lot_result === "detected" && s.customer_limit && pick.startsWith("Release") ? " " + SPEC : "");
  if (pick !== lastPick) { tag.classList.remove("changed"); void tag.offsetWidth; tag.classList.add("changed"); lastPick = pick; }

  const top = Math.max(std * 2, risk.pct * 1.12, (own || 0) * 1.12), x = v => 100 * v / top;
  $("z1").style.width = `${x(std / 2)}%`; $("z2").style.width = `${x(std / 2)}%`; $("z3").style.width = `${100 - x(std)}%`;
  $("pin").style.left = `${x(risk.pct)}%`;
  $("pinOwn").hidden = own == null; $("ownLabel").hidden = own == null;
  if (own != null) { $("pinOwn").style.left = `${x(own)}%`; $("ownLabel").textContent = `Blue marker: your samples, ${own.toFixed(1)}%`; }
  $("tickHalf").style.left = `${x(std / 2)}%`; $("tickHalf").textContent = `Half ${std / 2}%`;
  $("tickStd").style.left = `${x(std)}%`; $("tickStd").textContent = `${s.product === "Raw breaded stuffed chicken" ? "Chicken parts standard, stand-in" : "FSIS standard"} ${std}%`;
  // The interval comes from the same table as the rate, so it only shows for category-based rates.
  const iv = interval(s, check, P.group);
  $("range").hidden = !iv;
  if (iv) { $("range").style.left = `${x(iv.ci_low)}%`; $("range").style.width = `${x(iv.ci_high - iv.ci_low)}%`; }
  const near = iv && [std / 2, std].some(c => iv.ci_low <= c && c <= iv.ci_high);
  $("readout").innerHTML = `<b>${risk.pct.toFixed(1)}%</b> expected positive next year` +
    (iv ? `, 95% range ${iv.ci_low.toFixed(1)} to ${iv.ci_high.toFixed(1)}` : "") +
    (near ? ` <span class="near">Borderline</span>` : "");
  $("gauge").setAttribute("aria-label", `Expected positivity ${risk.pct} percent, FSIS standard ${std} percent`);
  $("printmeta").textContent = `${s.product}, ${num(s.lot_lb)} lb, ${D.stateNames[s.state]}. ` +
    `FSIS category: ${s.fsis_category ?? "none"}. Lot screen: ${s.lot_result === "none" ? "none" : s.lot_result}` +
    `${s.cfu_per_g ? `, ${s.cfu_per_g} CFU/g` : ""}. Hours above 40°F: ${s.hours_above_40f} (limit ${s.max_hours_above_40f}). ` +
    `Printed ${new Date().toLocaleDateString("en-US")}. Decision support, not a regulatory determination. Reviewed by: ____________`;

  count($("oExp"), chosen.exposure_index, v => v.toFixed(2));
  count($("oServ"), chosen.servings_kept, num);
  count($("oNeed"), chosen.servings_to_need, num);
  $("oProt").textContent = `${num(chosen.protein_kg)} kg protein`;
  $("oNeedNote").textContent = chosen.servings_to_need ? `${Math.round(ui.donate * 100)}% of the lot after a validated cook` : "This action sends none";

  $("oNeed").parentElement.classList.toggle("zero", !chosen.servings_to_need);
  $("mini").style.setProperty("--level", LEVEL[risk.level]);
  $("mini").innerHTML = `<b>${esc(risk.level)} risk</b> ${esc(pick)}`;

  ui.ctx = { s, P, risk, pick, table, check };
  $("panel").innerHTML = PANELS[ui.tab]();
}

function interval(s, check, group) {
  const cat = s.fsis_category ?? (check && check.status), rows = s.fsis_category != null ? D.evidence.published : D.evidence.forward;
  return cat ? rows.find(r => r.product_group === group && r.category === cat && r.ci_high > r.ci_low) : null;
}

function stateCard(k) {
  const L = D.live[k];
  if (!L) return `<p class="note">No forecast for this state.</p>`;
  const storm = D.storms[`${k}|${Number(L.period.slice(-2))}`] ?? 0;
  return `<dl class="facts"><dt>Expected cases</dt><dd>${Math.round(L.expected_cases)}</dd><dt>80% range</dt><dd>${Math.round(L.low_80)} to ${Math.round(L.high_80)}</dd>
    <dt>Three-year average</dt><dd>${Math.round(L.baseline_3y)}</dd><dt>Status</dt><dd>${L.alert ? "Above alert level" : "Within alert level"}</dd>
    <dt>Storm months</dt><dd>${storm} of 12 years</dd></dl>`;
}

const SPEC = "This lot screened positive and a buyer's specification applies, so check the specification before shipping.";

function nextSteps(pick, s) {
  const cooked = ["Confirm this product is covered by a validated cooked process in your HACCP plan.",
    "Meet the 7-log10 lethality and stabilization requirements (9 CFR 381.150), or a validated equivalent.",
    "Apply Listeria controls to ready-to-eat product (9 CFR 430)."];
  const steps = {
    "Release raw under normal HACCP": ["Release under normal HACCP controls and keep your records.", "Recheck your FSIS category when the next posting appears."],
    "Release raw, add verification": ["Check that interventions on this line are running within their limits.", "Add verification sampling and record the results.",
      "Enter your recent FSIS counts in the self-check to see how close the line is to the next category."],
    "Hold and test, cook any positives": ["Hold the lot under establishment control.", "Get a quantified result before any release decision.",
      "Send positives to a validated cooked process or another authorized route. One sample does not clear a large lot."],
    "Redirect to validated cooked line": cooked,
    "Redirect to cooked line, donate part": [...cooked, "Confirm capacity and cold chain with the receiving food organization."],
    "Discard or render": ["Hold the lot and document the deviation in your HACCP records.", "Have your process authority confirm the disposition.", "Follow your plan for disposal or rendering."],
  }[pick];
  if (s.lot_result === "detected" && s.customer_limit && pick.startsWith("Release")) steps.unshift(SPEC);
  if (pick === "Release raw, add verification" && !s.has_cooked_line) steps.push("If risk stays high, ask a co-packer about a validated cook.");
  return steps;
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
    const todo = nextSteps(ui.ctx.pick, s).map(t => `<li>${esc(t)}</li>`).join("");
    const notes = [];
    if (s.lot_result === "negative") notes.push("A negative screen does not clear a lot, so it does not lower the risk level.");
    if (!(s.lot_lb > 0)) notes.push("Enter a lot size to see servings and protein.");
    if (s.has_cooked_line === false && ui.ctx.pick.startsWith("Release")) notes.push("Turn on Validated cooked line to compare redirect and donation options.");
    const noteHtml = notes.map(n => `<p class="alert">${esc(n)}</p>`).join("");
    return `<div class="grid2"><div class="plate"><h3>Next steps</h3><ol class="steps">${todo}</ol>
      <p class="note">For review by a qualified person. This tool authorizes nothing.</p></div>
      <div class="plate"><h3>What drove this</h3><ul class="reasons">${
      risk.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>${noteHtml}
      <p class="note">Salmonella-positive raw poultry is generally not adulterated. The exception is the narrow
      2024 determination for raw breaded stuffed chicken, where FSIS <a href="https://www.federalregister.gov/d/2025-21737">delayed verification sampling</a>.</p></div>
      ${self}<div class="plate"><h3>${esc(D.stateNames[s.state])}, ${esc(L.period)}</h3>
      <p>About <b>${Math.round(L.expected_cases)}</b> poultry-associated human cases expected (80% range
      ${Math.round(L.low_80)} to ${Math.round(L.high_80)}; three-year average ${Math.round(L.baseline_3y)}),
      ${L.alert ? "above" : "within"} the alert level. Heat, flood or tropical events in this month:
      ${storm ?? 0} of 12 years.</p><p class="note">State figures are context. They do not change the risk level.</p></div></div>`;
  },
  compare() {
    const { table, pick, P } = ui.ctx;
    const mE = Math.max(...table.map(r => r.exposure_index), .01), mS = Math.max(...table.map(r => r.servings_kept), 1);
    const bar = (v, m, t, l) => `<span class="bar" data-l="${l}"><i style="width:${Math.round(70 * v / m)}px"></i>${t}</span>`;
    return `<p class="lead">Every option on the same outcomes. Select a row for its conditions.</p>
      <div class="opthead"><span>Option</span><span>Exposure index</span><span>Servings kept</span><span>To high-need counties</span><span>Food lost</span></div>` +
      [...table].sort((a, b) => (b.feasible || b.action === pick) - (a.feasible || a.action === pick)).map(r => `<details class="opt ${r.action === pick ? "pick" : r.feasible ? "" : "no"}"><summary>
        <span class="name">${esc(r.action)}${r.feasible ? "" : " (not possible here)"}</span>
        ${bar(r.exposure_index, mE, r.exposure_index.toFixed(2), "Exposure index")}${bar(r.servings_kept, mS, num(r.servings_kept), "Servings kept")}
        <span data-l="To high-need counties">${num(r.servings_to_need)}</span><span data-l="Food lost">${Math.round(r.food_lost_pct)}%</span></summary><p>${esc(r.note)}</p></details>`).join("") +
      `<p class="note">Exposure index: national chicken parts sold raw = 1.0, scaled by what lines in your FSIS category
      measured the following year. It is relative, not a count of illnesses. ${esc(P.note)}</p>`;
  },
  donate() {
    const { s, table } = ui.ctx, donated = Math.max(...table.map(r => r.servings_to_need));
    const rows = E.donationTargets(s.state, D, donated);
    return `<p class="lead">${donated ? `${num(donated)} servings could reach the highest-need counties in ${esc(D.stateNames[s.state])}.`
      : `Highest-need counties in ${esc(D.stateNames[s.state])}. Turn on a validated cooked line to plan a donation.`}</p>` +
      rows.map(r => `<div class="county${donated ? "" : " plan"}"><div><b>${esc(r.county)}</b>
        <small>${r.food_insecure_pct != null ? `${r.food_insecure_pct}% of adults food insecure` : "No CDC estimate here"}</small></div>
        <div><small>Need score ${r.need_score.toFixed(2)}</small><div class="needbar"><i style="width:${r.need_score * 100}%"></i></div></div>
        ${donated ? `<div><b>${num(r.servings)}</b><small>servings</small></div>` : ""}
        <div>${r.food_orgs ? `${r.food_orgs} food org${r.food_orgs > 1 ? "s" : ""} listed<small>Largest: ${esc(r.largest_food_org)}</small>`
          : `<span class="gap">No food org listed</span><small>Find a local partner first</small>`}</div></div>`).join("") +
      `<p class="note">Need combines CDC food insecurity (modeled, not in every state), CDC Social Vulnerability Index and USDA
      low-income, low-access share. Food organizations come from the IRS list, which misses many church pantries, so confirm
      capacity directly. Donated cooked product needs Listeria controls (9 CFR 430) and cold chain to the food bank.</p>`;
  },
  map() {
    const states = Object.keys(D.live), alerts = states.filter(k => D.live[k].alert).sort((a, b) => D.live[b].outlook_ratio - D.live[a].outlook_ratio);
    const tile = k => {
      const L = D.live[k], [r, c] = TILES[k] || [];
      if (!L || r == null) return "";
      const t = Math.min(Math.max((L.outlook_ratio - .6) / 1, 0), 1), dark = t > .55;
      return `<button type="button" class="tile${L.alert ? " hot" : ""}${k === ui.s.state ? " here" : ""}" data-state="${k}" style="grid-row:${r + 1};grid-column:${c + 1};background:color-mix(in srgb,#14506A ${Math.round(t * 100)}%,#E3EFF3);color:${dark ? "#fff" : "#12343B"}"
        aria-label="${esc(D.stateNames[k])}: about ${Math.round(L.expected_cases)} cases, ratio ${L.outlook_ratio}${L.alert ? ", above alert level" : ""}" data-tip="${esc(D.stateNames[k])}: about ${Math.round(L.expected_cases)} cases, ${L.outlook_ratio} times the three-year average">${k}</button>`;
    };
    const list = alerts.length ? alerts.map(k => `<li><button type="button" class="link" data-state="${k}">${esc(D.stateNames[k])}</button><span>${D.live[k].outlook_ratio}x, about ${Math.round(D.live[k].expected_cases)} cases</span></li>`).join("")
      : `<li>No state is above the alert level.</li>`;
    const period = D.live[states[0]].period;
    return `<h2>Poultry-associated human cases, ${esc(period)}</h2>
      <p class="lead">Forecast cases against the same month over three years. Select a state to set it as the plant's state.</p>
      <div class="mapwrap"><div class="plate"><div class="tiles">${states.concat().sort().map(tile).join("")}</div>
        <div class="legend"><span>Below average</span><i></i><span>Above average</span><b>Red outline: above alert level</b></div></div>
        <div class="plate"><h3>${esc(D.stateNames[ui.s.state])}</h3>${stateCard(ui.s.state)}<h3 class="gap2">Alerts (${alerts.length})</h3><ul class="alerts">${list}</ul>
        <p class="note">Context only. These do not change the risk level, because alert precision fell to ${(D.evidence.alertYears.at(-1).precision * 100).toFixed(1)}% in 2026. An alert is not an outbreak.</p></div></div>`;
  },
  cases() {
    const rows = Object.entries(D.scenarios).map(([name, sc], i) => {
      const s = { ...blank, ...sc, cfu_per_g: sc.cfu_per_g || null };
      const r = E.riskLevel(s, D), [pick] = E.recommend(s, D), t = E.compareActions(s, D), c = t.find(x => x.action === pick);
      return `<article class="case" style="--level:${LEVEL[r.level]}"><div class="lvl">${r.level} risk</div>
        <h3>${esc(name.replace(/^\d+\. /, ""))}</h3><p class="act">${esc(pick)}</p>
        <dl><dt>Expected positivity</dt><dd>${r.pct.toFixed(1)}%</dd><dt>Exposure, raw to chosen</dt><dd>${t[0].exposure_index.toFixed(2)} to ${c.exposure_index.toFixed(2)}</dd>
        <dt>Servings kept</dt><dd>${num(c.servings_kept)}</dd><dt>To high-need counties</dt><dd>${num(c.servings_to_need)}</dd></dl>
        <button type="button" class="chip" data-case="${i}">Open this case</button></article>`;
    }).join("");
    return `<p class="lead">Four illustrative lots, each scored on safety and food. Rates, yields and nutrition are measured.</p><div class="cases">${rows}</div>`;
  },
  evidence() {
    const e = D.evidence, t = e.publishedTest, g = e.alert.find(a => a.split === "test_2024_on");
    const mae = e.accuracy.filter(a => a.model === "m0").map(a => a.gain_vs_best_baseline_pct);
    const high = e.persistence.find(p => p.high), low = e.persistence.find(p => !p.high);
    return `<h2>A plant's FSIS category predicts its next year</h2>
      <p class="lead">Share of FSIS routine samples positive after a line received each published category. Hover or focus a bar for counts.</p>
      <div class="plate">${chart(e.published.filter(r => r.product_group !== "Turkey carcass"), ui.ctx.P.group, ui.ctx.s.fsis_category)}</div>
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

function chart(rows, mine, cat) {
  const groups = [...new Set(rows.map(r => r.product_group))].sort((a, b) => (b === mine) - (a === mine)), W = 250, H = 240, base = H - 26, top = 34;
  const max = Math.ceil(Math.max(...rows.map(r => r.ci_high)) / 10) * 10, y = v => base - (base - top) * v / max;
  return `<div class="charts">` + groups.map(g => {
    const rs = rows.filter(r => r.product_group === g), std = rs[0].fsis_standard_pct, bw = 46;
    const bars = rs.map((r, j) => {
      const cx = 48 + j * 77, v = r.pct_positive_next_year;
      const tip = `${esc(g)}, Category ${r.category}: ${v}% positive. ${r.plants} plants, ${num(r.samples)} samples`;
      return `<g class="b" data-tip="${tip}" tabindex="0" role="img" aria-label="${tip}"><rect x="${cx - bw / 2}" y="${y(v)}" width="${bw}" height="${base - y(v)}" rx="3" fill="${CAT[r.category - 1]}" fill-opacity="${g === mine && cat && cat !== r.category ? .3 : 1}"/>
        <path d="M${cx} ${y(r.ci_low)}V${y(r.ci_high)}M${cx - 4} ${y(r.ci_low)}h8M${cx - 4} ${y(r.ci_high)}h8" stroke="#12343B" fill="none"/>
        <text x="${cx}" y="${y(r.ci_high) - 6}" text-anchor="middle" font-size="14" font-weight="600">${Math.round(v)}%</text>
        <text x="${cx}" y="${base + 18}" text-anchor="middle" font-size="13">Cat ${r.category}</text></g>`;
    }).join("");
    return `<figure class="${g === mine ? "mine" : ""}"><figcaption>${esc(g)}${g === mine ? ` <em>Your lot</em>` : ""}<small>FSIS standard ${std}%, dotted line</small></figcaption>
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
    if (on) { $("ink").style.left = `${b.offsetLeft}px`; $("ink").style.width = `${b.offsetWidth}px`; $("panel").setAttribute("aria-label", b.textContent); if (focus) b.focus(); }
  });
  render();
}
const tabs = [...document.querySelectorAll(".tabs button")];
tabs.forEach((b, i) => {
  b.setAttribute("aria-controls", "panel");
  b.onclick = () => select(b.dataset.t);
  b.onkeydown = e => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (d) select(tabs[(i + d + tabs.length) % tabs.length].dataset.t, true);
  };
});

$("panel").addEventListener("click", e => {
  const st = e.target.closest?.("[data-state]"), cs = e.target.closest?.("[data-case]");
  if (st) { ui.s.state = st.dataset.state; ui.active = null; $("tip").hidden = true; fillForm(); render(); $("panel").querySelector(`.tile[data-state="${st.dataset.state}"]`)?.focus(); }
  if (cs) openCase(Number(cs.dataset.case));
});

$("panel").addEventListener("mousemove", e => {
  const g = e.target.closest?.(".b,.tile"), tip = $("tip");
  tip.hidden = !g;
  if (g) { tip.textContent = g.dataset.tip; tip.style.left = `${e.clientX + 12}px`; tip.style.top = `${e.clientY + 12}px`; }
});
$("panel").addEventListener("mouseleave", () => $("tip").hidden = true);
$("panel").addEventListener("focusin", e => {
  const g = e.target.closest?.(".b,.tile"), tip = $("tip");
  if (!g) return;
  const r = g.getBoundingClientRect();
  tip.textContent = g.dataset.tip; tip.hidden = false; tip.style.left = `${r.left}px`; tip.style.top = `${r.bottom + 6}px`;
});
$("panel").addEventListener("focusout", () => $("tip").hidden = true);
function moveInk() {
  const b = document.querySelector('.tabs button[aria-selected="true"]');
  if (b) { $("ink").style.left = `${b.offsetLeft}px`; $("ink").style.width = `${b.offsetWidth}px`; }
}
addEventListener("resize", moveInk);

new IntersectionObserver(([e]) => { $("mini").hidden = e.isIntersecting; }).observe(document.querySelector(".hero"));

fillForm();
await document.fonts?.ready;
select("why");
