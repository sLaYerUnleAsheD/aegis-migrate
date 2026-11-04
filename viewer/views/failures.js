import { el, empty } from "./dom.js";
import { state, selectRun, setPage, providerName } from "../store.js";

export function renderFailures(root) {
  const page = el("div", { class: "page" });
  page.append(el("h1", {}, "First-attempt failures"));
  const counts = state.index?.failure_counts || {};
  const groups = groupCounts(counts);
  if (!groups.length) {
    page.append(empty("No failure_counts in index.json."));
    root.append(page);
    return;
  }
  page.append(el("p", { class: "reading" }, "Bars are grouped by the label prefix before the colon (compile, runtime, library semantics, COBOL formatting, …). Click a bar, then a run, to open it on the Output tab."));

  const max = Math.max(...groups.map((g) => g.n));
  const bars = el("div", { class: "bars" });
  for (const g of groups) {
    const on = (state.route.failGroup || groups[0].prefix) === g.prefix;
    bars.append(el("div", { class: "hbar" },
      el("button", {
        type: "button",
        "aria-pressed": on ? "true" : "false",
        style: on ? "font-weight:700;color:var(--accent)" : "",
        onClick: () => setPage("failures", { failGroup: g.prefix }),
      }, g.prefix),
      el("div", { class: "track" }, el("i", { style: `width:${(100 * g.n) / max}%;background:${on ? "var(--bad)" : "var(--accent)"}` })),
      el("span", { class: "mut" }, String(g.n)),
    ));
  }
  page.append(bars);

  const prefix = state.route.failGroup || groups[0].prefix;
  const labels = Object.keys(counts).filter((l) => (l.split(":")[0] || l) === prefix);
  const runs = (state.index.runs || []).filter((r) => labels.includes(r.label));
  page.append(el("h2", {}, `${prefix} (${runs.length} runs)`));
  if (!runs.length) page.append(empty("No runs carry this label."));
  const list = el("div", { style: "display:flex;flex-direction:column;gap:.25rem;" });
  for (const r of runs) {
    list.append(el("button", {
      class: "tree-row", type: "button",
      onClick: () => selectRun(r.id, "output"),
    },
      el("span", { class: "ico bad" }, "✗"),
      el("span", { style: "font-weight:600" }, `${providerName(r.provider)} · ${r.program} · sample ${r.sample}`),
      el("span", { class: "mut" }, `— ${r.label}`),
    ));
  }
  page.append(list);
  root.append(page);
}

function groupCounts(counts) {
  const g = {};
  for (const [label, n] of Object.entries(counts)) {
    const prefix = (label.split(":")[0] || label).trim();
    g[prefix] = (g[prefix] || 0) + n;
  }
  return Object.entries(g).map(([prefix, n]) => ({ prefix, n })).sort((a, b) => b.n - a.n);
}
