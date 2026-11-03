import { el } from "./dom.js";
import { state } from "../store.js";

export function renderAbout(root) {
  const page = el("div", { class: "page" });
  const n = state.index?.runs?.length ?? 0;
  page.append(
    el("h1", {}, "About this viewer"),
    el("p", {}, "Aegis Migrate translates batch COBOL to Go and proves equivalence by running both programs on the same generated inputs. This page is a ", el("strong", {}, "static explorer of recorded runs"), ", not a live migration service."),
    el("p", {}, el("strong", {}, "Replayed from recorded data: no API call."), " The Replay button animates JSON that was written by python -m core.build_viewer. Your browser never talks to Meta, Modal, or Baseten."),
    el("p", {}, `${n} runs are in this snapshot (generated ${state.index?.generated || "unknown"}). First load is only index.json; COBOL and Go are fetched when you select a sample.`),
    el("h2", {}, "How to read a run"),
    el("p", {}, "✓ first translation matched the COBOL oracle. ↻ matched after repair. ✗ still differed after the repair budget. ! is an API/token-cap error, not a wrong translation."),
    el("h2", {}, "Run it yourself"),
    el("p", {}, "The collapsible panel on every run copies a Docker replay command and a live pipeline command. The live command needs keys, GnuCOBOL, and Docker. This site does not."),
    el("p", {}, el("a", { href: "https://github.com/sLaYerUnleAsheD/aegis-migrate" }, "Source repository")),
  );
  root.append(page);
}
