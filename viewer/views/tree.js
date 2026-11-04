import { el, empty, clear } from "./dom.js";
import {
  state, filteredRuns, statusIcon, toggleFilter, setQuery, toggleTree, selectRun, openCompare, providerName,
} from "../store.js";

const STATUSES = [
  ["first", "First try"],
  ["repair", "After repair"],
  ["failed", "Never verified"],
  ["error", "API error"],
];

export function renderTree(root) {
  const runs = filteredRuns();
  const idx = state.index || { runs: [], programs: [] };
  const providers = [...new Set(idx.runs.map((r) => r.provider))].sort();
  const efforts = [...new Set(idx.runs.map((r) => String(r.effort)))].sort();

  let filters = root.querySelector(".filters");
  let search = root.querySelector(".search");
  let tree = root.querySelector(".tree");

  if (!filters) {
    clear(root);
    filters = el("div", { class: "filters", role: "group", "aria-label": "Filters" });
    search = el("input", {
      class: "search", type: "search", placeholder: "Search program or label",
      value: state.filters.q, "aria-label": "Search program or label",
      onInput: (ev) => setQuery(ev.target.value),
    });
    tree = el("div", { class: "tree", role: "tree", "aria-label": "Runs by program" });
    root.append(
      el("div", { class: "pane-h" }, el("h2", {}, "Directory")),
      filters, search, tree,
    );
  }

  // Update filter chips
  clear(filters);
  for (const p of providers) filters.append(chip("provider", p, providerName(p)));
  for (const e of efforts) filters.append(chip("effort", e, `effort ${e}`));
  for (const [k, lab] of STATUSES) filters.append(chip("status", k, lab));

  // Sync search input if not active
  if (document.activeElement !== search && search.value !== state.filters.q) {
    search.value = state.filters.q;
  }

  // Update tree contents
  clear(tree);
  if (!runs.length) {
    tree.append(empty(idx.runs.length ? "No runs match these filters." : "No recorded runs in data/index.json."));
  } else {
    const byTier = group(runs, (r) => r.tier || "unknown");
    const tierOrder = ["tier1", "tier2", "tier3", ...Object.keys(byTier).filter((t) => !/^tier[123]$/.test(t)).sort()];
    for (const tier of tierOrder) {
      if (!byTier[tier]) continue;
      tree.append(tierNode(tier, byTier[tier]));
    }
  }
}

function chip(kind, value, label) {
  const on = state.filters[kind].has(value);
  return el("button", {
    class: "chip", type: "button", "aria-pressed": on ? "true" : "false",
    onClick: () => toggleFilter(kind, value),
  }, label);
}

function tierNode(tier, runs) {
  const key = tier;
  const wrap = details(key, true, el("span", {}, tier, el("span", { class: "mut" }, ` · ${runs.length}`)));
  const byProg = group(runs, (r) => r.program);
  for (const prog of Object.keys(byProg).sort()) wrap.append(programNode(tier, prog, byProg[prog]));
  return wrap;
}

function programNode(tier, prog, runs) {
  const key = `${tier}/${prog}`;
  const n = runs.length, ok = runs.filter((r) => r.status === "verified").length;
  const bar = el("span", { class: "bar-mini", title: `${ok}/${n} verified` }, el("i", { style: `width:${n ? (100 * ok) / n : 0}%` }));
  const head = el("span", { style: "display:flex;align-items:center;gap:.4rem;width:100%" },
    el("span", {}, prog), bar,
    el("button", { class: "chip", type: "button", onClick: (e) => { e.preventDefault(); e.stopPropagation(); openCompare(prog); } }, "Compare"),
  );
  const wrap = details(key, false, head);
  const byPe = group(runs, (r) => `${r.provider} · ${r.effort}`);
  for (const pe of Object.keys(byPe).sort()) wrap.append(peNode(tier, prog, pe, byPe[pe]));
  return wrap;
}

function peNode(tier, prog, pe, runs) {
  const key = `${tier}/${prog}/${pe.replace(" · ", "·")}`;
  const wrap = details(key, false, el("span", { class: "mut" }, pe));
  for (const r of runs.sort((a, b) => a.sample - b.sample)) {
    const ic = statusIcon(r);
    const btn = el("button", {
      class: "tree-row", type: "button", role: "treeitem",
      "aria-current": r.id === state.route.runId ? "true" : null,
      title: ic.title,
      onClick: () => selectRun(r.id, state.route.pane || "cobol"),
    },
      el("span", { class: `ico ${ic.cls}` }, ic.ch),
      el("span", { class: "sample-label" }, `sample ${r.sample}`),
    );
    wrap.append(btn);
  }
  return wrap;
}

function details(key, defaultOpen, summaryKids) {
  const open = key in state.treeOpen ? state.treeOpen[key] : defaultOpen;
  const d = el("details", { open: open || undefined });
  d.append(el("summary", {}, summaryKids));
  d.addEventListener("toggle", () => toggleTree(key, d.open));
  return d;
}

function group(arr, fn) {
  const o = {};
  for (const x of arr) (o[fn(x)] ||= []).push(x);
  return o;
}
