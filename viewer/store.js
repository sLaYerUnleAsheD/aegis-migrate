const TREE_KEY = "aegis-tree";
const DATA = new URL("data/", import.meta.url);

const listeners = new Set();

export const state = {
  index: null,
  indexError: "",
  programs: new Map(),
  runs: new Map(),
  loading: { run: false, program: false, index: true },
  errors: { run: "", program: "" },
  route: { page: "explorer", runId: "", pane: "cobol", failGroup: "" },
  filters: { provider: new Set(), effort: new Set(), status: new Set(), q: "" },
  treeOpen: loadTree(),
  goAttempt: null,
  replay: idleReplay(),
  compare: { open: false, program: "", ids: [] },
};

function idleReplay() {
  return { playing: false, i: -1, speed: 1, steps: [], typed: 0, passShown: 0, done: false };
}

function loadTree() {
  try { return JSON.parse(localStorage.getItem(TREE_KEY) || "{}"); } catch { return {}; }
}
function saveTree() { try { localStorage.setItem(TREE_KEY, JSON.stringify(state.treeOpen)); } catch {} }
export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function emit() { listeners.forEach((fn) => fn(state)); }

export function money(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `$${Number(n).toFixed(3)}`;
}
export function pctCount(num, den) {
  if (!den) return "—";
  return `${Math.round((100 * num) / den)}% (${num}/${den})`;
}

export function parseHash() {
  const h = (location.hash || "#/explorer").replace(/^#/, "");
  const parts = h.split("/").filter(Boolean);
  const page = parts[0] || "explorer";
  const route = { page, runId: "", pane: "cobol", failGroup: "" };
  if (page === "explorer") {
    route.runId = decodeURIComponent(parts[1] || "");
    route.pane = parts[2] || "cobol";
  } else if (page === "failures") {
    route.failGroup = decodeURIComponent(parts[1] || "");
  }
  return route;
}

export function setHash(route) {
  let h = `#/${route.page}`;
  if (route.page === "explorer" && route.runId) {
    h += `/${encodeURIComponent(route.runId)}`;
    if (route.pane) h += `/${route.pane}`;
  } else if (route.page === "failures" && route.failGroup) {
    h += `/${encodeURIComponent(route.failGroup)}`;
  }
  if (location.hash !== h) history.replaceState(null, "", h);
}

export async function fetchJson(rel) {
  const res = await fetch(new URL(rel, DATA));
  if (!res.ok) throw new Error(`${rel} (${res.status})`);
  return res.json();
}

export async function loadIndex() {
  state.loading.index = true;
  state.indexError = "";
  emit();
  try {
    state.index = await fetchJson("index.json");
  } catch (e) {
    state.indexError = String(e.message || e);
    state.index = { programs: [], runs: [], summary: [], overall: [], matrix: [], mutation: [], failure_counts: {} };
  }
  state.loading.index = false;
  emit();
}

export async function selectRun(id, pane) {
  const switchRun = id !== state.route.runId;
  state.route.page = "explorer";
  state.route.runId = id;
  if (pane) state.route.pane = pane;
  setHash(state.route);
  await ensureRun(id, { reset: switchRun });
}

export async function ensureRun(id, { reset = false } = {}) {
  if (!id) return;
  const switching = reset || state.route.runId !== id || !state.runs.has(id);
  if (!state.runs.has(id)) {
    state.loading.run = true;
    state.errors.run = "";
    emit();
    try {
      const run = await fetchJson(`runs/${encodeURIComponent(id)}.json`);
      state.runs.set(id, run);
    } catch (e) {
      state.errors.run = String(e.message || e);
    }
    state.loading.run = false;
  }
  const run = state.runs.get(id);
  if (run?.program) await ensureProgram(run.program);
  if (switching) {
    const keys = Object.keys(run?.attempt_go || {});
    state.goAttempt = keys.length ? keys[keys.length - 1] : null;
    stopReplay(true);
    state.replay.steps = pipelineSteps(run, state.programs.get(run?.program));
  }
  emit();
}

export async function ensureProgram(name) {
  if (!name || state.programs.has(name)) return;
  state.loading.program = true;
  state.errors.program = "";
  emit();
  try {
    state.programs.set(name, await fetchJson(`programs/${encodeURIComponent(name)}.json`));
  } catch (e) {
    state.errors.program = String(e.message || e);
  }
  state.loading.program = false;
  emit();
}

export function setPane(pane) {
  state.route.pane = pane;
  setHash(state.route);
  emit();
}

export function setPage(page, extra) {
  stopReplay(true);
  state.route = { page, runId: extra?.runId || state.route.runId, pane: extra?.pane || "cobol", failGroup: extra?.failGroup || "" };
  setHash(state.route);
  emit();
}

export function toggleFilter(kind, value) {
  const set = state.filters[kind];
  if (set.has(value)) set.delete(value); else set.add(value);
  emit();
}
export function setQuery(q) { state.filters.q = q; emit(); }

export function toggleTree(key, open) {
  state.treeOpen[key] = open;
  saveTree();
}

export function openProgramPath(run) {
  if (!run) return;
  const t = run.tier || "unknown";
  state.treeOpen[t] = true;
  state.treeOpen[`${t}/${run.program}`] = true;
  state.treeOpen[`${t}/${run.program}/${run.provider}·${run.effort}`] = true;
  saveTree();
}

export function statusIcon(run) {
  if (run.status === "llm_error" || run.status === "budget_exceeded") return { ch: "!", cls: "warn", title: run.status };
  if (run.status === "verified" && run.first_try) return { ch: "✓", cls: "ok", title: "verified first try" };
  if (run.status === "verified") return { ch: `↻ ${run.repairs || 1}`, cls: "ok", title: `verified after ${run.repairs} repair${run.repairs === 1 ? "" : "s"}` };
  return { ch: "✗", cls: "bad", title: "never verified" };
}

export function filteredRuns() {
  const { provider, effort, status, q } = state.filters;
  const qq = q.trim().toLowerCase();
  return (state.index?.runs || []).filter((r) => {
    if (provider.size && !provider.has(r.provider)) return false;
    if (effort.size && !effort.has(String(r.effort))) return false;
    if (status.size) {
      const key = statusKey(r);
      if (!status.has(key)) return false;
    }
    if (qq && !(`${r.program} ${r.label} ${r.id}`.toLowerCase().includes(qq))) return false;
    return true;
  });
}

export function statusKey(r) {
  if (r.status === "llm_error" || r.status === "budget_exceeded") return "error";
  if (r.status === "verified" && r.first_try) return "first";
  if (r.status === "verified") return "repair";
  return "failed";
}

export function parseDiff(failure) {
  const exp = [], act = [];
  if (!failure) return { exp: "", act: "", raw: "" };
  for (const line of failure.split("\n")) {
    if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) continue;
    if (line.startsWith("-")) exp.push(line.slice(1));
    else if (line.startsWith("+")) act.push(line.slice(1));
  }
  return { exp: exp.join("\n"), act: act.join("\n"), raw: failure };
}

export function pipelineSteps(run, program) {
  if (!run) return [];
  const n = run.cases ?? 0;
  const risks = (program?.risks || run.risk_features || []).join(", ") || "none flagged";
  const steps = [
    { id: "analyze", title: "Analyze", facts: `risks: ${risks}` },
    { id: "inputs", title: `Generate inputs (${n} files)`, facts: n ? `${n} test files from the record layout` : "no cases recorded" },
    { id: "cobol", title: "Run COBOL (golden)", facts: "GnuCOBOL oracle outputs captured" },
  ];
  const atts = run.attempts || [];
  if (!atts.length) {
    if (run.status === "llm_error" || run.status === "budget_exceeded") {
      steps.push({ id: "err", title: run.status, facts: run.detail || "no attempts", bad: true });
    }
  }
  for (const a of atts) {
    const cost = money(a.list_cost_usd);
    steps.push({
      id: `t-${a.n}`, title: a.n === 0 ? "Translate" : `Repair ${a.n}`, attempt: a.n,
      facts: `${a.output_tokens ?? 0} output tokens · ${cost} list`,
    });
    const passed = a.passed_cases ?? 0;
    const ok = a.built && n && passed === n && !a.failure;
    steps.push({
      id: `v-${a.n}`, title: "Verify", attempt: a.n, verify: true,
      facts: `built ${a.built ? "yes" : "no"} · passed ${passed}/${n}`,
      passed, total: n, failure: a.failure || "", ok, bad: !ok,
    });
  }
  const good = run.status === "verified";
  steps.push({
    id: "result", title: "Result", result: true, ok: good, bad: !good,
    facts: `${run.status}${run.detail ? " — " + run.detail : ""} · ${money(run.total_list_cost_usd)} list`,
  });
  return steps;
}

let replayTimer = 0;
let replaySubTimer = 0;

export function stopReplay(reset) {
  clearTimeout(replayTimer);
  clearInterval(replaySubTimer);
  state.replay.playing = false;
  if (reset) {
    const steps = state.replay.steps;
    state.replay = idleReplay();
    state.replay.steps = steps;
  }
}

export function setSpeed(n) { state.replay.speed = n; emit(); }

export function replayStep(delta) {
  const { steps } = state.replay;
  if (!steps.length) return;
  stopReplay();
  let i = state.replay.i + delta;
  if (state.replay.i < 0 && delta > 0) i = 0;
  i = Math.max(-1, Math.min(steps.length - 1, i));
  applyReplayIndex(i, true);
}

export function restartReplay() {
  stopReplay();
  applyReplayIndex(-1, true);
}

export function playReplay() {
  const { steps } = state.replay;
  if (!steps.length) return;
  stopReplay();
  let startIdx = 0;
  if (state.replay.done || state.replay.i >= steps.length - 1) {
    startIdx = 0;
    applyReplayIndex(-1, true);
  } else if (state.replay.i < 0) {
    startIdx = 0;
  } else {
    startIdx = state.replay.i + 1;
    if (startIdx >= steps.length) startIdx = 0;
  }
  state.replay.playing = true;
  emit();

  const runStep = (idx) => {
    if (!state.replay.playing) return;
    if (idx >= steps.length) {
      state.replay.playing = false;
      state.replay.done = true;
      emit();
      return;
    }
    const step = steps[idx];
    applyReplayIndex(idx, false);

    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ms = reduce ? 120 : (state.replay.speed === 2 ? 450 : 750);

    if (step.verify && !reduce) {
      state.replay.passShown = 0;
      state.replay.typed = 0;
      emit();

      const targetPassed = step.passed ?? 0;
      const targetTyped = step.failure ? Math.min(step.failure.length, 300) : 0;
      const ticks = 10;
      const tickInterval = Math.max(25, Math.floor((ms - 100) / ticks));
      let tickCount = 0;

      clearInterval(replaySubTimer);
      replaySubTimer = setInterval(() => {
        tickCount++;
        const progress = Math.min(1, tickCount / ticks);
        state.replay.passShown = Math.round(targetPassed * progress);
        state.replay.typed = Math.round(targetTyped * progress);
        emit();
        if (tickCount >= ticks) {
          clearInterval(replaySubTimer);
        }
      }, tickInterval);
    } else {
      state.replay.passShown = step.passed ?? 0;
      state.replay.typed = step.failure ? step.failure.length : 0;
      emit();
    }

    replayTimer = setTimeout(() => {
      clearInterval(replaySubTimer);
      state.replay.passShown = step.passed ?? 0;
      state.replay.typed = step.failure ? step.failure.length : 0;
      emit();
      runStep(idx + 1);
    }, ms);
  };

  replayTimer = setTimeout(() => runStep(startIdx), 60);
}

function applyReplayIndex(i, instant = false) {
  state.replay.i = i;
  state.replay.done = i === state.replay.steps.length - 1;
  const step = i >= 0 ? state.replay.steps[i] : null;
  if (step) {
    if (step.id === "analyze" || step.id === "cobol") {
      state.route.pane = "cobol";
    } else if (step.attempt != null && !step.verify) {
      const name = `attempt_${step.attempt}.go`;
      const run = state.runs.get(state.route.runId);
      if (run?.attempt_go?.[name]) state.goAttempt = name;
      state.route.pane = "go";
    } else if (step.verify) {
      const name = `attempt_${step.attempt}.go`;
      const run = state.runs.get(state.route.runId);
      if (run?.attempt_go?.[name]) state.goAttempt = name;
      state.route.pane = "output";
    } else if (step.result) {
      state.route.pane = "output";
    }
    setHash(state.route);
  }
  if (instant) {
    state.replay.typed = step?.failure ? step.failure.length : 0;
    state.replay.passShown = step?.passed ?? 0;
  }
  emit();
}

export function setGoAttempt(name) { state.goAttempt = name; emit(); }

export function openCompare(program) {
  const ids = filteredRuns().filter((r) => r.program === program).slice(0, 3).map((r) => r.id);
  state.compare = { open: true, program, ids };
  emit();
  ids.forEach((id) => ensureRun(id));
}
export function setCompareIds(ids) {
  state.compare.ids = ids.slice(0, 3);
  emit();
  ids.forEach((id) => ensureRun(id));
}
export function closeCompare() { state.compare.open = false; emit(); }

export function providerName(p) {
  return ({
    meta: "Meta Spark 1.3",
    modal: "Spark Open on Modal",
    baseten: "Spark Open on Baseten",
  })[p] || p;
}

export async function boot() {
  state.route = parseHash();
  await loadIndex();
  state.route = parseHash();
  if (state.route.page === "explorer" && state.route.runId) {
    const meta = (state.index.runs || []).find((r) => r.id === state.route.runId);
    openProgramPath(meta);
    await ensureRun(state.route.runId);
  }
  emit();
}
