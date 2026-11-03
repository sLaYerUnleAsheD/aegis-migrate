export function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const k of kids.flat()) {
    if (k == null || k === false) continue;
    e.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
  return e;
}

export function clear(node) { node.replaceChildren(); return node; }

export function skeleton(n = 4) {
  return el("div", { class: "empty", "aria-busy": "true" }, ...Array.from({ length: n }, () => el("div", { class: "sk" })));
}

export function empty(msg) { return el("p", { class: "empty" }, msg); }
