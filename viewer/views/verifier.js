import { el, empty } from "./dom.js";
import { state } from "../store.js";

export function renderVerifier(root) {
  const page = el("div", { class: "page" });
  page.append(el("h1", {}, "Verifier strength"));
  page.append(
    el("p", { class: "reading" }, "Mutation testing found a gap in my tests: rounding versus truncation only showed up in one tax bracket."),
    el("p", { class: "reading" }, "I fixed the hints so every bracket has a record where rounding changes the cents, then re-verified ten translations. None of them changed."),
    el("p", { class: "reading" }, "The table is the raw catch rate on a verified translation. Survivors were triaged by hand; most are equivalent mutants or outside the unsigned full-width input domain."),
  );
  const rows = state.index?.mutation || [];
  if (!rows.length) {
    page.append(empty("No mutation JSON under run/mutation. See python -m core.mutate in the README."));
    root.append(page);
    return;
  }
  const t = el("table");
  t.append(el("tr", {}, ...["program", "mutants", "caught", "survived", "catch rate", "with more inputs"].map((h) => el("th", {}, h))));
  for (const r of rows) {
    t.append(el("tr", {},
      el("td", {}, r.program), el("td", {}, r.mutants), el("td", {}, r.caught), el("td", {}, r.survived),
      el("td", {}, fmtRate(r.catch_rate)), el("td", {}, fmtRate(r.with_more_inputs))));
  }
  page.append(t);
  root.append(page);
}

function fmtRate(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n <= 1 ? `${Math.round(n * 100)}%` : String(v);
}
