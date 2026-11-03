import { el } from "./dom.js";
import { state, closeCompare, setCompareIds, filteredRuns, money, statusIcon, providerName } from "../store.js";

export function renderCompare(root) {
  const { program, ids } = state.compare;
  const candidates = filteredRuns().filter((r) => r.program === program);
  const overlay = el("div", { class: "compare", role: "dialog", "aria-modal": "true", "aria-label": `Compare ${program}` });
  const box = el("div", { class: "box" });
  box.append(el("div", { class: "pane-h" },
    el("h2", {}, `Compare ${program} (up to 3)`),
    el("button", { type: "button", "aria-label": "Close compare dialog", onClick: closeCompare }, "Close")));

  const pick = el("div", { class: "chips" });
  for (const r of candidates) {
    const on = ids.includes(r.id);
    pick.append(el("button", {
      class: "chip", type: "button", "aria-pressed": on ? "true" : "false",
      onClick: () => {
        const next = on ? ids.filter((x) => x !== r.id) : [...ids, r.id].slice(-3);
        setCompareIds(next);
      },
    }, `${providerName(r.provider)} · ${r.effort} · s${r.sample}`));
  }
  box.append(el("p", { class: "mut" }, "Same program, different recorded runs."), pick);

  const cols = el("div", { class: "cols-3" });
  for (const id of ids) {
    const meta = (state.index.runs || []).find((r) => r.id === id);
    const run = state.runs.get(id);
    const cell = el("div", {});
    if (!meta) { cols.append(el("p", { class: "mut" }, id)); continue; }
    const ic = statusIcon(meta);
    cell.append(
      el("h3", {}, `${providerName(meta.provider)} · ${meta.effort}`),
      el("p", {}, el("span", { class: ic.cls }, ic.ch), ` ${meta.status} · sample ${meta.sample}`),
      el("p", { class: "mut" }, `${meta.out_tokens} out tokens · ${money(meta.cost_list_usd)}`),
    );
    if (!run) cell.append(el("div", { class: "sk" }));
    else {
      const n = run.cases || 0;
      const t = el("table");
      t.append(el("tr", {}, el("th", {}, "attempt"), el("th", {}, "built"), el("th", {}, "pass"), el("th", {}, "tokens")));
      for (const a of run.attempts || []) {
        const ok = a.built && n && a.passed_cases === n && !a.failure;
        t.append(el("tr", {}, el("td", {}, String(a.n)), el("td", {}, a.built ? "yes" : "no"),
          el("td", { class: ok ? "ok" : "bad" }, `${a.passed_cases}/${n}`), el("td", {}, String(a.output_tokens ?? ""))));
      }
      cell.append(t);
      const names = Object.keys(run.attempt_go || {});
      const last = names[names.length - 1];
      if (last) cell.append(el("pre", {}, (run.attempt_go[last] || "").slice(0, 4000)));
    }
    cols.append(cell);
  }
  if (ids.length >= 2) {
    const a = state.runs.get(ids[0]), b = state.runs.get(ids[1]);
    if (a && b) box.append(el("h2", {}, "Final Go (run A vs run B)"), goDiff(lastGo(a), lastGo(b)));
  }
  box.append(cols);
  overlay.append(box);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeCompare(); });
  root.append(overlay);
}

function lastGo(run) {
  const names = Object.keys(run.attempt_go || {});
  return run.attempt_go[names[names.length - 1]] || "";
}

function goDiff(a, b) {
  const al = a.split("\n"), bl = b.split("\n");
  const n = Math.max(al.length, bl.length);
  const pre = el("pre", { class: "diff" });
  for (let i = 0; i < Math.min(n, 200); i++) {
    if (al[i] === bl[i]) pre.append((al[i] || "") + "\n");
    else {
      if (al[i] != null) pre.append(el("span", { class: "del" }, "-" + al[i] + "\n"));
      if (bl[i] != null) pre.append(el("span", { class: "add" }, "+" + bl[i] + "\n"));
    }
  }
  return pre;
}
