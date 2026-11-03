import { el, empty, skeleton, clear } from "./dom.js";
import { state, setPane, setGoAttempt, parseDiff } from "../store.js";

const PANES = ["cobol", "go", "output", "layout"];

export function renderWorkbench(root) {
  const id = state.route.runId;
  const run = state.runs.get(id);
  const prog = run ? state.programs.get(run.program) : null;
  const pane = PANES.includes(state.route.pane) ? state.route.pane : "cobol";

  const tabs = el("div", { class: "work-tabs", role: "tablist", "aria-label": "Workbench" });
  for (const p of PANES) {
    tabs.append(el("a", {
      href: `#/explorer/${encodeURIComponent(id || "")}/${p}`,
      "aria-current": pane === p ? "page" : null,
      onClick: (e) => { e.preventDefault(); setPane(p); },
    }, p.toUpperCase()));
  }

  const body = el("div", { class: "work", role: "tabpanel" });
  if (!id) {
    body.append(
      el("div", { class: "wb-empty" },
        el("h3", {}, "Select a run to inspect"),
        el("p", { class: "mut" }, "Choose any translation run from the directory on the left to inspect its COBOL source, Go translation attempts, and byte-for-byte verification diffs."),
        el("div", { class: "chips" },
          el("span", { class: "tag ok" }, "✓ Verified first try"),
          el("span", { class: "tag" }, "↻ Repaired in loop"),
          el("span", { class: "tag fail" }, "✗ Diverged"),
        ),
      )
    );
  }
  else if (state.loading.run || state.loading.program) body.append(skeleton(6));
  else if (state.errors.run) body.append(empty(`Could not load this run: ${state.errors.run}`));
  else if (!run) body.append(empty("Missing run file."));
  else if (pane === "cobol") body.append(cobolView(prog, run));
  else if (pane === "go") body.append(goView(run));
  else if (pane === "output") body.append(outputView(run, prog));
  else body.append(layoutView(prog));

  clear(root);
  root.append(
    el("div", { class: "pane-h" },
      el("h2", {}, run ? `${run.program} · ${run.provider} · s${run.sample}` : "Workbench")),
    tabs, body,
  );
}

function cobolView(prog, run) {
  if (state.errors.program) return empty(`Could not load program JSON: ${state.errors.program}`);
  if (!prog) return empty("No COBOL source in viewer/data/programs.");
  const box = el("div", { class: "cobol-view" });
  const pre = el("pre", { class: "code cobol-pre", tabindex: "0" });

  const rawCobol = prog.cobol || "(empty)";
  const lines = rawCobol.split("\n");
  const lineEls = [];
  const paraMap = new Map();

  lines.forEach((lineText, idx) => {
    const lineEl = el("span", { class: "cobol-line", "data-line": idx + 1 }, lineText + "\n");
    lineEls.push(lineEl);
    pre.append(lineEl);
  });

  for (const p of prog.paragraphs || []) {
    const normName = p.name.trim();
    const esc = normName.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
    const regex = new RegExp(`^(\\d{6}\\s+)?\\s*${esc}(\\.|\\s|$)`, "i");
    let foundIdx = lines.findIndex((l) => regex.test(l));
    if (foundIdx === -1) {
      foundIdx = lines.findIndex((l) => l.toUpperCase().includes(normName.toUpperCase()));
    }
    if (foundIdx !== -1) {
      paraMap.set(normName, lineEls[foundIdx]);
    }
  }

  const chips = el("div", { class: "chips" });
  for (const p of prog.paragraphs || []) {
    const calls = (p.performs || []).join(" → ");
    const chipBtn = el("button", {
      class: "tag chip-jump", type: "button",
      title: calls ? `PERFORM ${calls}` : "Click to jump to paragraph",
      onClick: () => {
        const targetEl = paraMap.get(p.name);
        if (targetEl) {
          targetEl.scrollIntoView?.({ behavior: "smooth", block: "center" });
          pre.querySelectorAll(".para-flash").forEach((el) => el.classList.remove("para-flash"));
          void targetEl.offsetWidth;
          targetEl.classList.add("para-flash");
        } else {
          pre.scrollIntoView?.({ behavior: "smooth", block: "start" });
        }
      },
    }, p.name + (calls ? ` → ${calls}` : ""));
    chips.append(chipBtn);
  }

  const risks = el("div", { class: "chips" });
  for (const r of prog.risks || run.risk_features || []) risks.append(el("span", { class: "tag" }, r));
  if (!risks.childNodes.length) risks.append(el("span", { class: "tag" }, "no risk features"));

  box.append(
    el("p", { class: "mut" }, "Paragraphs / call graph (click to jump)"), chips,
    el("p", { class: "mut" }, "Risk features"), risks,
    pre,
  );
  return box;
}

function goView(run) {
  const names = Object.keys(run.attempt_go || {});
  if (!names.length) return empty("No Go attempts were saved for this run.");
  const cur = names.includes(state.goAttempt) ? state.goAttempt : names[names.length - 1];
  const bar = el("div", { class: "subtabs" });
  const sel = el("select", { "aria-label": "Attempt", onChange: (e) => setGoAttempt(e.target.value) });
  for (const n of names) {
    const o = el("option", { value: n }, n.replace(".go", "").replace("_", " "));
    if (n === cur) o.selected = true;
    sel.append(o);
  }

  const copyBtn = el("button", {
    type: "button",
    onClick: () => {
      navigator.clipboard?.writeText(run.attempt_go[cur] || "");
      copyBtn.textContent = "Copied!";
      setTimeout(() => { copyBtn.textContent = "Copy"; }, 1600);
    },
  }, "Copy");

  bar.append(sel, copyBtn);
  return el("div", {}, bar, el("pre", { class: "code", tabindex: "0" }, run.attempt_go[cur] || ""));
}

function outputView(run, prog) {
  const step = replayStep();
  const atts = run.attempts || [];
  if (run.status === "llm_error" || run.status === "budget_exceeded") {
    return el("div", {},
      el("p", { class: "bad" }, run.status),
      el("p", {}, run.detail || "The model call failed before a translation was saved."),
      el("p", { class: "mut" }, `Billed list cost ${moneySafe(run)}`),
    );
  }
  if (!atts.length) return empty("This run has no attempts.");

  // Determine which attempt to show
  let activeAtt = null;
  if (step && step.attempt != null) {
    activeAtt = atts.find((a) => a.n === step.attempt) || atts[0];
  } else if (state.goAttempt) {
    const num = parseInt(state.goAttempt.replace(/\D+/g, ""), 10);
    activeAtt = atts.find((a) => a.n === num) || atts[atts.length - 1];
  } else {
    activeAtt = atts[atts.length - 1];
  }

  const box = el("div", {});

  // If multiple attempts, show attempt picker buttons
  if (atts.length > 1) {
    const picker = el("div", { class: "subtabs", role: "group", "aria-label": "Select attempt output" });
    for (const a of atts) {
      const isSelected = a.n === activeAtt.n;
      const ok = a.built && a.passed_cases === run.cases && !a.failure;
      const lab = `Attempt ${a.n} (${ok ? "verified" : "failed"})`;
      picker.append(el("button", {
        type: "button",
        "aria-pressed": isSelected ? "true" : "false",
        class: isSelected ? "chip-active" : "",
        onClick: () => setGoAttempt(`attempt_${a.n}.go`),
      }, lab));
    }
    box.append(picker);
  }

  const fail = (step && step.attempt === activeAtt.n && step.failure) || activeAtt.failure || "";
  const isOk = activeAtt.built && run.cases && activeAtt.passed_cases === run.cases && !fail;

  if (fail && !fail.includes("stdout_diff")) {
    box.append(
      el("p", { class: "bad" }, `Attempt ${activeAtt.n} failed: compile / runtime error`),
      el("pre", { class: "diff", tabindex: "0" }, fail),
    );
    return box;
  }

  // Find golden output either from current diff, program golden_stdout, or another attempt
  const { exp, act, raw } = parseDiff(fail);
  let golden = exp || prog?.golden_stdout || "";
  if (!golden) {
    for (const a of atts) {
      if (a.failure && a.failure.includes("stdout_diff")) {
        golden = parseDiff(a.failure).exp;
        if (golden) break;
      }
    }
  }

  if (isOk) {
    const matchText = golden || "(output match verified by oracle)";
    box.append(
      el("p", { class: "ok", style: "font-weight:600;margin:.4rem 0 .6rem;" },
        `✓ Attempt ${activeAtt.n} passed: Go output matched COBOL byte-for-byte on all ${run.cases} test cases.`),
      el("div", { class: "out-grid" },
        col("Golden COBOL (oracle)", vis(matchText)),
        col("Go output (100% byte match)", vis(matchText))),
    );
    return box;
  }

  if (!exp && !act) {
    box.append(el("pre", { class: "diff", tabindex: "0" }, raw || "(no output recorded)"));
    return box;
  }

  const typingActive = (state.replay.playing || state.replay.i >= 0) && step?.attempt === activeAtt.n;
  const typed = typingActive ? sliceTyped(exp, act) : { e: exp, a: act };

  box.append(
    el("p", { class: "bad", style: "font-weight:600;margin:.4rem 0 .6rem;" },
      `✗ Attempt ${activeAtt.n} output mismatch (${activeAtt.passed_cases}/${run.cases} passed). Differing characters highlighted:`),
    el("div", { class: "out-grid" },
      col("Golden COBOL (expected)", highlight(typed.e, typed.a, "exp")),
      col("Go output (actual)", highlight(typed.e, typed.a, "act")),
    ),
  );
  return box;
}

function replayStep() {
  const { steps, i } = state.replay;
  return i >= 0 ? steps[i] : null;
}

function col(title, node) {
  return el("div", { class: "out-col" }, el("p", { class: "mut out-title" }, title), el("pre", { class: "diff", tabindex: "0" }, node));
}

function vis(s) { return (s || "").replace(/ /g, "·"); }

function sliceTyped(exp, act) {
  const n = state.replay.typed || 0;
  return { e: (exp || "").slice(0, Math.max(n, exp.length)), a: (act || "").slice(0, n) };
}

function highlight(exp, act, which) {
  const a = vis(which === "exp" ? exp : act);
  const b = vis(which === "exp" ? act : exp);
  const frag = document.createDocumentFragment();
  const al = a.split("\n"), bl = b.split("\n");
  const n = Math.max(al.length, bl.length);
  for (let i = 0; i < n; i++) {
    const x = al[i] || "", y = bl[i] || "";
    const len = Math.max(x.length, y.length);
    for (let j = 0; j < len; j++) {
      const ch = x[j] ?? "";
      if (ch && ch !== (y[j] ?? "")) frag.append(el("span", { class: "hl" }, ch));
      else frag.append(ch);
    }
    if (i < n - 1) frag.append("\n");
  }
  return frag;
}

function layoutView(prog) {
  if (!prog) return empty("Program JSON not loaded.");
  const rows = prog.layout || [];
  if (!rows.length) return empty("No FILE record layout (this program may be incomplete in the fixture).");
  const t = el("table");
  t.append(el("tr", {}, ...["Name", "Offset", "Size", "PIC", "Category"].map((h) => el("th", {}, h))));
  for (const r of rows) {
    t.append(el("tr", {}, el("td", {}, r.name), el("td", {}, r.offset), el("td", {}, r.size),
      el("td", { class: "mut code-font" }, r.pic), el("td", {}, r.category)));
  }
  return t;
}

function moneySafe(run) {
  const n = run.total_list_cost_usd ?? run.total_cost_usd;
  if (n == null) return "—";
  return `$${Number(n).toFixed(3)}`;
}
