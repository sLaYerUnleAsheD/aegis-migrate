import { el, empty, clear } from "./dom.js";
import {
  state, money, playReplay, stopReplay, replayStep, restartReplay, setSpeed, emit,
} from "../store.js";

export function renderTimeline(root) {
  const run = state.runs.get(state.route.runId);
  const steps = state.replay.steps || [];
  const i = state.replay.i;

  const controls = el("div", { class: "replay-bar" },
    el("button", {
      class: "primary replay-btn", type: "button",
      onClick: () => { restartReplay(); playReplay(); },
    }, "▶ Replay from cache"),
    el("button", {
      type: "button",
      onClick: () => (state.replay.playing ? (stopReplay(), emit()) : playReplay()),
    }, state.replay.playing ? "Pause" : "Play"),
    el("button", { type: "button", onClick: () => replayStep(1) }, "Step"),
    el("button", { type: "button", "aria-pressed": state.replay.speed === 1 ? "true" : "false", onClick: () => setSpeed(1) }, "1×"),
    el("button", { type: "button", "aria-pressed": state.replay.speed === 2 ? "true" : "false", onClick: () => setSpeed(2) }, "2×"),
    el("button", { type: "button", onClick: () => restartReplay() }, "Restart"),
  );

  const caption = el("p", { class: "replay-caption", role: "note" },
    el("span", { class: "badge-dot" }),
    "Replayed from recorded data: no API call",
  );

  const live = el("ol", { class: "timeline", "aria-live": "polite" });
  if (!run) live.append(empty("Pipeline appears once a run is selected."));
  else {
    steps.forEach((s, idx) => {
      const on = idx === i || (i < 0 && idx === 0 && !state.replay.playing);
      const shown = i < 0 ? true : idx <= i;
      if (!shown && state.replay.playing) return;
      const cls = ["step", on ? "on" : "", s.ok ? "ok" : "", s.bad ? "bad" : ""].filter(Boolean).join(" ");
      const node = el("li", { class: cls },
        el("span", { class: "dot", "aria-hidden": "true" }),
        el("h3", {}, s.title),
        el("p", { class: "facts" }, verifyFacts(s, idx, i)),
      );
      if (s.failure && (i < 0 || idx <= i)) {
        const pre = el("pre", { class: "diff", tabindex: "0" });
        pre.append(diffSpans(s.failure, idx === i));
        node.append(pre);
      }
      if (run.label && s.verify && s.bad) node.append(el("span", { class: "tag fail" }, run.label));
      live.append(node);
    });
    if (state.replay.done || i === steps.length - 1) {
      const good = run.status === "verified";
      const rep = run.repairs_used || 0;
      const msg = good
        ? (rep === 0 ? "✓ Verified on first try" : `✓ Verified after ${rep} repair${rep === 1 ? "" : "s"}`)
        : (run.status === "failed" ? `✗ Did not verify within budget (${rep} repairs attempted)` : `! ${run.status}`);
      live.append(el("div", { class: `verdict ${good ? "ok" : "bad"}` }, msg));
    }
  }

  clear(root);
  root.append(
    el("div", { class: "pane-h" }, el("h2", {}, "Pipeline")),
    controls,
    caption,
    live,
    realPanel(run),
  );
}

function verifyFacts(s, idx, currentIdx) {
  if (s.verify && s.total) {
    const passedVal = (state.replay.playing && idx === currentIdx) ? state.replay.passShown : s.passed;
    return `built ${s.ok || s.passed ? "yes" : "no"} · passed ${passedVal}/${s.total}`;
  }
  return s.facts;
}

function diffSpans(text, typing) {
  const shown = (typing && state.replay.playing) ? text.slice(0, Math.max(state.replay.typed, 25)) : text;
  const frag = document.createDocumentFragment();
  for (const line of shown.split("\n")) {
    const cls = line.startsWith("-") ? "del" : line.startsWith("+") ? "add" : "";
    frag.append(el("span", { class: cls }, line + "\n"));
  }
  return frag;
}

function realPanel(run) {
  const det = el("details", { class: "real" });
  det.append(el("summary", {}, "Run it for real"));
  if (!run) {
    det.append(el("p", { class: "mut" }, "Select a run to copy commands."));
    return det;
  }
  const tier = run.tier || "tier1";
  const replay = `docker run --rm --network none cobol-verify python -m core.replay demo/${run.id} --local`;
  const live = `python -m core.pipeline benchmark/programs/${tier}/${run.program}.cbl --provider meta`;
  det.append(
    el("p", { class: "mut" }, "These run on your machine. The second needs API keys, GnuCOBOL and Docker. This page never calls a model."),
    copyBlock(replay),
    copyBlock(live),
  );
  return det;
}

function copyBlock(cmd) {
  const btn = el("button", {
    type: "button",
    onClick: () => {
      navigator.clipboard?.writeText(cmd);
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = "Copy"; }, 1600);
    },
  }, "Copy");
  return el("div", { class: "copy-row" },
    el("pre", { tabindex: "0" }, cmd),
    btn,
  );
}

export { money };
