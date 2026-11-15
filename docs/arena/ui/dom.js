let fallbackDocument = null;

export function setDocument(doc) {
  fallbackDocument = doc || null;
}

function resolveDocument(attrs) {
  if (attrs && typeof attrs === "object") {
    if (attrs.document) return attrs.document;
    if (attrs.ownerDocument) return attrs.ownerDocument;
  }
  if (fallbackDocument) return fallbackDocument;
  if (typeof globalThis !== "undefined" && globalThis.document) {
    return globalThis.document;
  }
  throw new Error("No document available for DOM construction");
}

function isDomNode(value) {
  if (!value || typeof value !== "object") return false;
  if (typeof globalThis !== "undefined" && typeof globalThis.Node === "function") {
    if (value instanceof globalThis.Node) return true;
  }
  return (
    typeof value.nodeType === "number" ||
    typeof value.tagName === "string" ||
    typeof value.appendChild === "function"
  );
}

function toDataAttrName(key) {
  return "data-" + String(key).replace(/[A-Z]/g, (ch) => "-" + ch.toLowerCase());
}

function createSafeTextNode(doc, text) {
  const str = String(text);
  if (doc && typeof doc.createTextNode === "function") {
    return doc.createTextNode(str);
  }
  return { nodeType: 3, textContent: str, nodeValue: str, data: str };
}

function appendChildNode(parent, childNode) {
  if (typeof parent.appendChild === "function") {
    parent.appendChild(childNode);
    return;
  }
  if (typeof parent.append === "function") {
    parent.append(childNode);
    return;
  }
  if (Array.isArray(parent.childNodes)) {
    parent.childNodes.push(childNode);
  }
  if (Array.isArray(parent.children) && childNode && childNode.nodeType === 1) {
    parent.children.push(childNode);
  }
}

function appendChildren(doc, parent, items) {
  for (const item of items) {
    if (item === null || item === undefined || item === false || item === true) {
      continue;
    }
    if (Array.isArray(item)) {
      appendChildren(doc, parent, item);
      continue;
    }
    if (isDomNode(item)) {
      appendChildNode(parent, item);
    } else {
      appendChildNode(parent, createSafeTextNode(doc, item));
    }
  }
}

export function el(tag, attrs, ...children) {
  const doc = resolveDocument(attrs);
  const node = doc.createElement(String(tag));
  if (attrs && typeof attrs === "object") {
    for (const [key, val] of Object.entries(attrs)) {
      if (key === "document" || key === "ownerDocument") continue;
      if (val === null || val === undefined) continue;

      if (key.startsWith("on") && key.length > 2 && typeof val === "function") {
        const eventName = key.slice(2).toLowerCase();
        if (typeof node.addEventListener === "function") {
          node.addEventListener(eventName, val);
        } else {
          node["on" + eventName] = val;
        }
        continue;
      }

      if (key.startsWith("aria-")) {
        if (typeof node.setAttribute === "function") {
          node.setAttribute(key, String(val));
        }
        continue;
      }

      if (val === false) continue;

      if (key === "class" || key === "className") {
        const cls = Array.isArray(val) ? val.filter(Boolean).join(" ") : String(val);
        if (typeof node.setAttribute === "function") {
          node.setAttribute("class", cls);
        }
        if (typeof node.className === "string" || !("className" in node)) {
          node.className = cls;
        }
        continue;
      }

      if (key === "dataset" && typeof val === "object") {
        for (const [dk, dv] of Object.entries(val)) {
          if (dv === null || dv === undefined || dv === false) continue;
          const strVal = String(dv);
          if (node.dataset && typeof node.dataset === "object") {
            node.dataset[dk] = strVal;
          }
          if (typeof node.setAttribute === "function") {
            node.setAttribute(toDataAttrName(dk), strVal);
          }
        }
        continue;
      }

      if (key === "style") {
        if (typeof val === "string") {
          if (typeof node.setAttribute === "function") {
            node.setAttribute("style", val);
          }
          if (node.style && typeof node.style === "object" && "cssText" in node.style) {
            node.style.cssText = val;
          }
        } else if (typeof val === "object" && node.style && typeof node.style === "object") {
          Object.assign(node.style, val);
        }
        continue;
      }

      if (val === true) {
        if (typeof node.setAttribute === "function") {
          node.setAttribute(key, "");
        }
        if (key in node) {
          try {
            node[key] = true;
          } catch (_) {}
        }
        continue;
      }

      if (typeof node.setAttribute === "function") {
        node.setAttribute(key, String(val));
      }
      if (key === "value" && "value" in node) {
        node.value = String(val);
      }
    }
  }
  appendChildren(doc, node, children);
  return node;
}

export function clear(node) {
  if (!node) return node;
  if (typeof node.replaceChildren === "function") {
    node.replaceChildren();
    return node;
  }
  while (node.firstChild && typeof node.removeChild === "function") {
    node.removeChild(node.firstChild);
  }
  if (Array.isArray(node.children)) {
    node.children.length = 0;
  }
  if (Array.isArray(node.childNodes)) {
    node.childNodes.length = 0;
  }
  if ("textContent" in node) {
    node.textContent = "";
  }
  return node;
}

export function pad2(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "00";
  const sign = num < 0 ? "-" : "";
  return sign + String(Math.trunc(Math.abs(num))).padStart(2, "0");
}

export function fmtScore(x) {
  const num = Number(x);
  if (!Number.isFinite(num)) return "0.00";
  const rounded = Math.round(num * 100) / 100;
  if (rounded === 0) return "0.00";
  const sign = rounded > 0 ? "+" : "-";
  return sign + Math.abs(rounded).toFixed(2);
}

export const MODE_DEFS = [
  {
    id: "duel",
    label: "Duel vs Gemini",
    badge: "v1.4 hard",
    desc: "Head to head vs committed gemini-4-carbon transcript + live solver on the same seed",
  },
  {
    id: "solver",
    label: "Beat the Solver",
    badge: "public seeds",
    desc: "Race the Bayesian canary-trap solver on the same world",
  },
  {
    id: "mole",
    label: "Be the Mole",
    badge: "role swap",
    desc: "Pick what to leak and when while the Bayesian solver hunts you",
  },
  {
    id: "living",
    label: "Living Office",
    badge: "v1.6 preview",
    desc: "Cached office chatter, rumours, and grudges across days (preview)",
  },
];

for (const mode of MODE_DEFS) {
  Object.defineProperty(MODE_DEFS, mode.id, {
    value: mode,
    enumerable: false,
    configurable: false,
    writable: false,
  });
}

export const TOOL_GROUPS = ["Investigate", "Trap", "Contain", "Clock", "Decide"];

export const TOOL_DEFS = {
  status: {
    code: "STA",
    name: "Status",
    group: "Clock",
    costed: false,
    desc: "Current day, visible company value V, actions and tool calls left, restrictions, and canaries planted.",
  },
  list_employees: {
    code: "EMP",
    name: "Staff list",
    group: "Investigate",
    costed: false,
    desc: "List all employees: id, name, department, role, and clearance level.",
  },
  list_documents: {
    code: "DOC",
    name: "Documents",
    group: "Investigate",
    costed: false,
    desc: "List published sensitive documents and canaries in an inclusive day range with recipients.",
  },
  read_access_logs: {
    code: "LOG",
    name: "Access logs",
    group: "Investigate",
    costed: true,
    desc: "Sensitive-doc access logs for closed days in an inclusive range; after-hours opens are marked [AH].",
  },
  search_messages: {
    code: "MSG",
    name: "Messages",
    group: "Investigate",
    costed: true,
    desc: "Case-insensitive substring search over internal message subjects and bodies (max 20 results).",
  },
  read_message: {
    code: "RD",
    name: "Read message",
    group: "Investigate",
    costed: true,
    desc: "Read one full internal message by id.",
  },
  interview: {
    code: "INT",
    name: "Interview",
    group: "Investigate",
    costed: true,
    desc: "Interview one employee on a topic; anyone can be evasive, the mole more often.",
  },
  plant_canary: {
    code: "CAN",
    name: "Canary",
    group: "Trap",
    costed: true,
    desc: "Plant a canary trap document today mapping employee ids to variant labels A, B, or C.",
  },
  check_leak_feed: {
    code: "FED",
    name: "Leak feed",
    group: "Trap",
    costed: true,
    desc: "Check leaked documents that have surfaced so far, including recovered canary variant labels.",
  },
  restrict_access: {
    code: "RST",
    name: "Restrict",
    group: "Contain",
    costed: true,
    desc: "Stop one employee from receiving new documents or canaries at a daily value cost.",
  },
  unrestrict_access: {
    code: "UNR",
    name: "Unrestrict",
    group: "Contain",
    costed: true,
    desc: "Lift an active access restriction on one employee.",
  },
  advance_day: {
    code: "DAY",
    name: "End day",
    group: "Clock",
    costed: false,
    desc: "Close the current day and advance to the next; overnight the mole may leak.",
  },
  accuse: {
    code: "ACC",
    name: "Accuse",
    group: "Decide",
    costed: false,
    desc: "Accuse one employee of being the mole and end the episode: true V if right, -1.00 if wrong.",
  },
};

export const DEFAULT_DUEL_SEEDS = [6, 26];
