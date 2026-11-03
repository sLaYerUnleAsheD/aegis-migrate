import { el } from "./dom.js";
import { state } from "../store.js";

export function renderAbout(root) {
  const page = el("div", { class: "page about-page" });
  const n = state.index?.runs?.length ?? 0;
  page.append(
    el("div", { class: "about-hero" },
      el("h1", {}, "Aegis Migrate"),
      el("p", { class: "about-lead" }, "COBOL → Go migration that proves itself."),
      el("blockquote", { class: "quote-box" },
        "Agents can write the Go. Nobody can trust it without evidence. This is the evidence layer."
      ),
    ),
    el("div", { class: "about-grid" },
      el("div", { class: "about-card" },
        el("h2", {}, "Why this exists"),
        el("p", {}, "An LLM will happily translate COBOL, and the result reads correctly. But COBOL has silent behaviors that look innocent and are not: implied decimal points, ROUNDED versus truncation, zero-suppressed edited fields, and branch scope terminators. Reading code does not find that. Running both programs and comparing outputs byte-for-byte does."),
      ),
      el("div", { class: "about-card" },
        el("h2", {}, "Autonomous Repair Loop"),
        el("p", {}, "When the Go translation output differs from the GnuCOBOL golden oracle output, the diff is fed back into the model to repair the code in an isolated Docker sandbox. The loop repeats up to a retry cap, closing the gap from raw single-shot drafts to 100% verified equivalence."),
      ),
      el("div", { class: "about-card" },
        el("h2", {}, "Static Evidence Explorer"),
        el("p", {}, `This site is an offline-ready static explorer of ${n} runs. The Replay button animates captured execution traces. Your browser never talks to Meta, Modal, or Baseten: every replay is strictly from data with zero API calls.`),
      ),
      el("div", { class: "about-card" },
        el("h2", {}, "Run It Locally"),
        el("p", {}, "Every run includes copy-paste commands for Docker reproduction on your own machine. Test oracle execution, mutate translations, and verify equivalence offline."),
        el("p", {}, el("a", { class: "about-link", href: "https://github.com/sLaYerUnleAsheD/aegis-migrate", target: "_blank", rel: "noopener" }, "→ GitHub Repository")),
      ),
    ),
  );
  root.append(page);
}
