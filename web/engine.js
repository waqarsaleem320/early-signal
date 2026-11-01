// Decision engine for the web app. It mirrors src/decision/actions.py, and
// tests/test_web.py fails if the two ever disagree.
export const MIN_SAMPLES = 10;
export const DEFAULTS = { detect: 0.9, donate: 0.25, maxHours: 2.0 };
export const SELF_CHECK_NOTE = "Self-check for decision support, rebuilt from the counts you entered. " +
  "Not an FSIS determination. FSIS uses a count table over a moving 52-week window " +
  "and does not assign a category until it has enough samples. With few samples, " +
  "one positive can move this rebuilt category by a whole step, so treat it as a " +
  "trend, not a status.";
const LETHALITY = "Validated process: 7-log10 Salmonella reduction or equivalent, plus " +
  "stabilization (9 CFR 381.150) and Listeria controls for ready-to-eat " +
  "product (9 CFR 430), under the plant's HACCP plan";
const LEVELS = ["Low", "Elevated", "High"];
const BREADED = "Raw breaded stuffed chicken";

const round = (x, d = 0) => {            // Python rounds halves to even
  const m = 10 ** d, v = x * m, f = Math.floor(v);
  const r = Math.abs(v - f - 0.5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(v);
  return r / m;
};
const py = n => Number.isInteger(n) ? n.toFixed(1) : String(n);
const pct0 = x => `${round(x * 100)}%`;

function review(s) {
  if (s.product !== BREADED || (s.lot_result === "none" && !s.cfu_per_g)) return null;
  let cls = "qualitative", num = null;
  if (s.cfu_per_g) {
    const t = s.cfu_per_g.trim();
    if (["", "NULL", "None", "nan"].includes(t)) cls = "none";
    else if (/^>[0-9]+(\.[0-9]+)?$/.test(t) && parseFloat(t.slice(1)) >= 1) { cls = "quantified"; num = parseFloat(t.slice(1)); }
    else if (t.startsWith("<") || t.startsWith(">")) cls = "censored";
    else if (/^[0-9]+(\.[0-9]+)?$/.test(t)) { cls = "quantified"; num = parseFloat(t); }
    else cls = "none";
  }
  if (cls === "quantified" && num >= 1) return {
    cls, must: true, hold: false,
    text: `Covered product quantified at ${py(num)} CFU/g >= 1.0 CFU/g. Under the modeled ` +
      "framework this would be ADULTERATED and must not enter commerce as-is. Diversion to a " +
      "hazard-eliminating, separately-authorized process (or disposal) would be required." };
  const present = cls === "censored" || (cls === "qualitative" && s.lot_result === "detected");
  if (present) return {
    cls, must: false, hold: true,
    text: "Covered product with Salmonella present but NOT reliably quantified (qualitative screen " +
      "or censored value). The >=1 CFU/g threshold cannot be established, so hold under establishment " +
      "control pending reliable quantitative confirmation before any adulterant determination or " +
      "commerce. (This measurement gap is what rapid validated quantification aims to close.)" };
  return { cls, must: false, hold: false, text: "" };
}

function status(k, n, tenths) {          // standard in tenths of a percent, so the maths is exact
  if (2000 * k <= tenths * n) return 1;
  return 1000 * k <= tenths * n ? 2 : 3;
}

const positives = (c, word) => `${c} ${word} positive${c === 1 ? "" : "s"}`;

export function selfCheck(s, D) {
  const group = D.products[s.product].group, std = D.fsisStandard[group];
  const n = s.plant_samples || 0, k = s.plant_positives || 0;
  if (n === 0) return null;
  const base = { samples: n, positives: k, standard_pct: std, observed_pct: null, status: null,
    published_note: null };
  if (n < 0 || k < 0 || k > n) return { ...base, message: "Positives cannot exceed samples, and neither " +
    "count can be negative. Check the counts; the self-check is not used." };
  if (n < MIN_SAMPLES) return { ...base, message: `${n} samples is too small to rebuild a category ` +
    `(at least ${MIN_SAMPLES} needed). ` + (s.fsis_category == null ? "The national rate is used." :
    `The published FSIS Category ${s.fsis_category} drives the expected rate.`) };
  const t = Math.round(std * 10), st = status(k, n, t), observed = 100 * k / n;
  const target = st === 1 ? Math.floor(t * n / 2000) + 1 :
    st === 2 ? Math.floor(t * n / 1000) + 1 : Math.floor(t * n / 1000);
  const head = (s.product === BREADED ? "No FSIS category exists for this product; chicken parts " +
    "standard used as a stand-in. " : "") +
    `${k} of ${n} samples positive (${observed.toFixed(1)}%) against the ${std}% standard: Category ${st}.`;
  let tail;
  if (target > n) tail = `No change in category is reachable at the same ${n} samples, because it would ` +
    "need more positives than samples.";
  else if (st < 3) tail = `${positives(Math.abs(target - k), "more")} at the same ${n} samples would move ` +
    `the line to Category ${status(target, n, t)}.`;
  else tail = `${positives(Math.abs(target - k), "fewer")} at the same ${n} samples would bring the line ` +
    `to Category ${status(target, n, t)} (at or below the standard).`;
  const note = s.fsis_category != null && s.fsis_category !== st ? `Your last 52 weeks of samples read ` +
    `Category ${st}; the published FSIS Category ${s.fsis_category} drives the expected rate, so the risk ` +
    `shown may be ${st > s.fsis_category ? "lower" : "higher"} than your own samples suggest.` : null;
  return { ...base, observed_pct: observed, status: st, message: `${head} ${tail}`, published_note: note };
}

export function expectedRate(s, D) {
  const group = D.products[s.product].group, low = group.toLowerCase();
  const national = [D.rates[group], `national ${low} rate`];
  if (s.fsis_category != null) {
    const r = D.published[`${group}|${s.fsis_category}`];
    return r != null ? [r, `published Category ${s.fsis_category} ${low} lines, the following year`] : national;
  }
  const c = selfCheck(s, D);
  if (c && c.status) {
    const r = D.forward[`${group}|${c.status}`];
    if (r != null) return [r, `Category ${c.status} ${low} lines, the following year, using the status ` +
      "rebuilt from your plant's last 52 weeks of samples"];
  }
  return national;
}

export function riskLevel(s, D) {
  const [rate, basis] = expectedRate(s, D), pct = 100 * rate;
  const std = D.fsisStandard[D.products[s.product].group];
  let step = Number(pct > std / 2) + Number(pct > std);
  const why = [`Expected positivity ${pct.toFixed(1)}% (${basis}); FSIS standard ${std}%`];
  const c = selfCheck(s, D);
  if (s.fsis_category && c && c.status && c.status > s.fsis_category) {
    step += 1;
    why.push(`Your own samples read Category ${c.status}, worse than the published ` +
      `Category ${s.fsis_category} (up one level)`);
  }
  if (s.lot_result === "detected") { step += 1; why.push("Lot screen detected Salmonella (up one level)"); }
  if (s.customer_limit) { step += 1; why.push("A buyer's specification applies (up one level)"); }
  const rv = review(s);
  if (s.hours_above_40f >= s.max_hours_above_40f) {
    step = 2;
    why.push(`Product at ${s.max_hours_above_40f} hours or more above 40°F (High)`);
  }
  if (rv && rv.must) { step = 2; why.push("Covered product measured at or above 1 CFU/g (High)"); }
  else if (rv && rv.hold) { step = 2; why.push("Covered product screened positive, hold for a quantified result (High)"); }
  else if (rv && (rv.cls === "quantified" || rv.cls === "censored")) {
    step += 1; why.push("Salmonella counted in a covered product, below 1 CFU/g (up one level)");
  } else if (s.cfu_per_g && rv && rv.cls === "none") why.push("The CFU/g value could not be read. Enter a number");
  return { level: LEVELS[Math.min(step, 2)], pct: round(pct, 1), why };
}

export function compareActions(s, D, detect = DEFAULTS.detect, donate = DEFAULTS.donate) {
  const P = D.products[s.product];
  const base = expectedRate(s, D)[0] / D.rates["Chicken parts"];
  const cooked = s.lot_lb * 453.592 * P.yield_pct / 100;
  const servings = cooked / 85, protein = cooked * P.protein_g_100g / 100 / 1000;
  const rv = review(s), inLimit = s.hours_above_40f < s.max_hours_above_40f;
  const adulterated = !!(rv && rv.must), hold = !!(rv && rv.hold);
  const blocked = !inLimit || adulterated || hold, line = !!s.has_cooked_line;
  const row = (action, remaining, kept, need, feasible, note) => ({
    action, feasible, exposure_index: round(base * remaining, 2), servings_kept: round(servings * kept),
    protein_kg: round(protein * kept, 1), servings_to_need: feasible ? round(servings * need) : 0,
    food_lost_pct: round(100 * (1 - kept), 1), note });
  return [
    row("Release raw under normal HACCP", 1, 1, 0, !blocked, "Normal route. Raw poultry is cooked by the end user."),
    row("Release raw, add verification", 1, 1, 0, !blocked, "More sampling and intervention checks. Exposure effect not estimated."),
    row("Hold and test, cook any positives", 1 - detect, 1, 0, inLimit && !adulterated && (line || hold),
      `About 2 days of shelf life used (assumed). Assumes the test finds ${pct0(detect)} of positive lots. ` +
      "A large lot is more likely to contain Salmonella than one sample suggests."),
    row("Redirect to validated cooked line", 0, 1, 0, line && inLimit, LETHALITY),
    row("Redirect to cooked line, donate part", 0, 1, donate, line && inLimit,
      `${pct0(donate)} donated after a validated cook. ${LETHALITY}`),
    row("Discard or render", 0, 0, 0, true, "Last resort. No food kept."),
  ];
}

export function recommend(s, D) {
  const level = riskLevel(s, D).level, rv = review(s);
  if (s.hours_above_40f >= s.max_hours_above_40f) return ["Discard or render",
    `Product exceeded the ${s.max_hours_above_40f}-hour limit above 40°F. Two hours is FSIS consumer guidance; ` +
    "the critical limit in the plant's HACCP plan (9 CFR 417.2) governs. Cooking kills Salmonella, but it does " +
    "not address toxins from other bacteria or lost HACCP control. The plant's process authority makes the final call."];
  if (rv && rv.must) return [s.has_cooked_line ? "Redirect to validated cooked line" : "Discard or render", rv.text];
  if (rv && rv.hold) return ["Hold and test, cook any positives", rv.text];
  if (level === "High") return s.has_cooked_line ?
    ["Redirect to cooked line, donate part", "High risk and a cooked line is available."] :
    ["Release raw, add verification", "High risk, but this plant has no cooked line. Raw poultry is generally " +
      "not adulterated, so verify and consider a co-packer."];
  if (level === "Elevated") return ["Release raw, add verification", "Elevated risk. See the reasons below."];
  return ["Release raw under normal HACCP", "Low risk."];
}

export function donationTargets(state, D, servings) {
  const rows = D.need[state] || [], total = rows.reduce((a, r) => a + r.people_low_income, 0);
  return rows.map(r => ({ ...r, servings: round(r.people_low_income / total * servings) }));
}
