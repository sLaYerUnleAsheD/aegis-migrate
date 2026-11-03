import { el, clear } from "./dom.js";
import { renderTree } from "./tree.js";
import { renderWorkbench } from "./workbench.js";
import { renderTimeline } from "./timeline.js";
import { renderCompare } from "./compare.js";
import { state } from "../store.js";

export function renderExplorer(root) {
  let shell = root.querySelector(".explorer");
  if (!shell) {
    clear(root);
    shell = el("div", { class: "explorer" });
    const left = el("section", { class: "pane pane-tree", "aria-label": "Directory tree" });
    const mid = el("section", { class: "pane pane-work", "aria-label": "Workbench" });
    const right = el("section", { class: "pane pane-time", "aria-label": "Pipeline timeline" });
    shell.append(left, mid, right);
    root.append(shell);
  }
  const left = shell.querySelector(".pane-tree");
  const mid = shell.querySelector(".pane-work");
  const right = shell.querySelector(".pane-time");

  renderTree(left);
  renderWorkbench(mid);
  renderTimeline(right);

  const existingDialog = document.querySelector(".compare");
  if (state.compare.open) {
    if (!existingDialog) renderCompare(document.body);
  } else {
    existingDialog?.remove();
  }
}
