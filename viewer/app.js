import { state, subscribe, boot, parseHash, setPage, ensureRun, openProgramPath, closeCompare } from "./store.js";
import { clear } from "./views/dom.js";
import { renderExplorer } from "./views/explorer.js";
import { renderResults } from "./views/results.js";
import { renderFailures } from "./views/failures.js";
import { renderVerifier } from "./views/verifier.js";
import { renderAbout } from "./views/about.js";

const main = document.getElementById("main");

function syncNav() {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    a.setAttribute("aria-current", a.dataset.nav === state.route.page ? "page" : "false");
  });
}

function render() {
  syncNav();
  const page = state.route.page;
  if (page === "results") { clear(main); renderResults(main); }
  else if (page === "failures") { clear(main); renderFailures(main); }
  else if (page === "verifier") { clear(main); renderVerifier(main); }
  else if (page === "about") { clear(main); renderAbout(main); }
  else { renderExplorer(main); }
}

subscribe(render);

window.addEventListener("hashchange", async () => {
  const next = parseHash();
  const needRun = next.page === "explorer" && next.runId && !state.runs.has(next.runId);
  const switchRun = next.runId && next.runId !== state.route.runId;
  state.route = next;
  if (needRun || switchRun) {
    const meta = (state.index?.runs || []).find((r) => r.id === next.runId);
    openProgramPath(meta);
    await ensureRun(next.runId, { reset: switchRun });
  } else {
    render();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.compare.open) closeCompare();
});

document.querySelectorAll("[data-nav]").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    setPage(a.dataset.nav);
  });
});

boot();
