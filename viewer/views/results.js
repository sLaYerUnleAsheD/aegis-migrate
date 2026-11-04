import { el, empty } from "./dom.js";
import { state, money, providerName } from "../store.js";

export function renderResults(root) {
  const page = el("div", { class: "page" });
  page.append(el("h1", {}, "Results matrix"));
  const matrix = state.index?.matrix || [];
  const overall = state.index?.overall || [];
  if (!matrix.length) {
    page.append(empty("No matrix in index.json. Run python -m core.build_viewer --data-dir viewer/data"));
    root.append(page);
    return;
  }
  const providers = [...new Set(matrix.map((m) => m.provider))].sort();
  const effortOrder = { default: 0, low: 1, medium: 2, high: 3 };
  const efforts = [...new Set(matrix.map((m) => String(m.effort)))].sort(
    (a, b) => (effortOrder[a] ?? 9) - (effortOrder[b] ?? 9)
  );
  const lookup = new Map(matrix.map((m) => [`${m.provider}\0${m.effort}`, m]));

  page.append(el("p", { class: "reading" }, "Each cell is one serving stack × reasoning effort. Empty combinations are a dash — they were not run. Colour follows first-try pass rate among completed (non-API-error) runs."));

  const t = el("table");
  t.append(el("tr", {}, el("th", {}, "provider \\ effort"), ...efforts.map((e) => el("th", {}, e))));
  for (const p of providers) {
    const tr = el("tr", {}, el("th", {}, providerName(p)));
    for (const e of efforts) {
      const m = lookup.get(`${p}\0${e}`);
      if (!m) { tr.append(el("td", { class: "mut" }, "—")); continue; }
      const pct = m.first_try_pct;
      const bg = heat(pct);
      tr.append(el("td", { class: "heat", style: bg ? `background:${bg}` : "" },
        el("div", {}, `first ${m.first_try_pct ?? "—"}% (${m.first_try})`),
        el("div", {}, `verified ${m.verified_pct ?? "—"}% (${m.verified})`),
        el("div", { class: "mut" }, `${money(m.cost_per_verified_usd)} / verified`),
      ));
    }
    t.append(tr);
  }
  page.append(t);
  page.append(el("p", { class: "reading" }, readingMatrix(matrix)));

  page.append(el("h2", {}, "Pooled: first try vs after repair"));
  const bars = el("div", { class: "bars" });
  for (const o of overall) {
    bars.append(bar(providerName(o.provider) + " first try", o.first_try_rate, o.first_try, "var(--warn)"));
    bars.append(bar(providerName(o.provider) + " after repair", o.verified_rate, o.verified, "var(--ok)"));
  }
  page.append(bars);
  const readingGroup = el("div", { class: "reading-list" });
  for (const line of readingOverall(overall)) {
    readingGroup.append(el("p", { class: "reading" }, line));
  }
  page.append(readingGroup);

  const byTier = tierBreak();
  if (byTier.length) {
    page.append(el("h2", {}, "By COBOL tier"));
    const tb = el("table");
    tb.append(el("tr", {}, ...["tier", "runs", "first try", "verified"].map((h) => el("th", {}, h))));
    for (const r of byTier) tb.append(el("tr", {}, el("td", {}, r.tier), el("td", {}, r.n), el("td", {}, r.first), el("td", {}, r.ver)));
    page.append(tb);
    page.append(el("p", { class: "reading" }, "Tiers describe COBOL features. They do not reliably rank what the models miss: programs without numeric-edited output tend to pass first time."));
  }
  root.append(page);
}

function heat(pct) {
  if (pct == null) return "";
  const t = Math.max(0, Math.min(100, pct)) / 100;
  return `color-mix(in srgb, var(--heat-hi) ${Math.round(t * 100)}%, var(--heat-lo))`;
}

function bar(label, rate, count, color) {
  const w = Math.round((rate || 0) * 100);
  return el("div", { class: "hbar" },
    el("span", {}, label),
    el("div", { class: "track" }, el("i", { style: `width:${w}%;background:${color}` })),
    el("span", { class: "mut" }, `${w}% ${count ? "(" + count + ")" : ""}`),
  );
}

function readingMatrix(matrix) {
  const sorted = [...matrix].filter((m) => m.first_try_pct != null).sort((a, b) => b.first_try_pct - a.first_try_pct);
  if (!sorted.length) return "";
  const best = sorted[0], worst = sorted[sorted.length - 1];
  return `${providerName(best.provider)} at effort ${best.effort} had the highest first-try rate (${best.first_try}). ${providerName(worst.provider)} at ${worst.effort} was lowest (${worst.first_try}). Verification is the second number in each cell.`;
}

function readingOverall(overall) {
  if (!overall.length) return [];
  return overall.map((o) => {
    const gap = (o.verified_rate ?? 0) - (o.first_try_rate ?? 0);
    return `${providerName(o.provider)}: first try ${o.first_try}, after repair ${o.verified}. Repair closed ${Math.round(gap * 100)} points. List cost per verified program ${money(o.cost_per_verified_usd)}.`;
  });
}

function tierBreak() {
  const runs = state.index?.runs || [];
  const g = {};
  for (const r of runs) {
    const t = r.tier || "unknown";
    (g[t] ||= []).push(r);
  }
  return Object.keys(g).sort().map((tier) => {
    const rs = g[tier].filter((r) => r.status === "verified" || r.status === "failed");
    const n = rs.length, ft = rs.filter((r) => r.first_try).length, v = rs.filter((r) => r.status === "verified").length;
    return { tier, n: g[tier].length, first: n ? `${Math.round(100 * ft / n)}% (${ft}/${n})` : "—", ver: n ? `${Math.round(100 * v / n)}% (${v}/${n})` : "—" };
  });
}
