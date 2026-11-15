export const SEED_MIN = 3000;
export const SEED_MAX = 9999;
export const ALLOWED_TIERS = ["medium", "hard"];
export const DEFAULT_TIER = "medium";
export const CURATED_MOLE_SEEDS = [
  3000,
  3001,
  3002,
  3003,
  3004,
  3005,
  3006,
  3007,
  3008,
  3009,
];

const ARENA_SHOWCASE_DUEL_SEEDS = new Set([4, 6, 26]);

const FORBIDDEN_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "moleId",
  "mole_id",
  "is_mole",
  "decoy",
  "true_decoy",
  "decoy_id",
  "correct",
  "accused_correct",
  "world_seed",
  "_world",
  "mole_strategy",
  "secret",
  "world_secret",
  "true_v",
  "true_V",
  "trueV",
  "accused",
  "score",
  "leaking_sprite_employee",
  "mole_sprite",
  "culprit_sprite",
  "leaker_employee",
  "is_canary",
  "canary_variants",
  "variants",
  "raw_doc_id",
  "raw_title",
  "true_variant",
  "variant_recipients",
  "leaked_canaries",
  "caught_by_canary",
  "posterior",
  "mole_posterior",
  "posteriors",
  "posterior_curve",
  "top_suspect",
  "top_suspects",
  "top_posterior",
  "mole_rank",
]);

const PY_IMPORT_PRELUDE =
  "try:\n" +
  "  import mole_mode as _canary_mm\n" +
  "except ImportError:\n" +
  "  from docs.arena import mole_mode as _canary_mm\n";

let fallbackDocument = null;
let cachedVirtualDoc = null;

export function setDocument(doc) {
  fallbackDocument = doc || null;
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

function toDataAttrName(key) {
  return "data-" + String(key).replace(/[A-Z]/g, (ch) => "-" + ch.toLowerCase());
}

function fromDataAttrName(attrName) {
  return attrName
    .slice(5)
    .replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
}

function matchesSingleCompound(node, compound) {
  if (!node || node.nodeType !== 1) return false;
  let rest = compound.trim();
  if (!rest) return false;

  const attrMatches = [];
  rest = rest.replace(/\[([^\]=]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/g, (_, rawName, dq, sq, bare) => {
    const val = dq !== undefined ? dq : sq !== undefined ? sq : bare !== undefined ? bare : null;
    attrMatches.push({ name: rawName.trim(), val });
    return "";
  });

  for (const am of attrMatches) {
    const actual = typeof node.getAttribute === "function" ? node.getAttribute(am.name) : undefined;
    if (actual === null || actual === undefined) return false;
    if (am.val !== null && String(actual) !== am.val) return false;
  }

  let requiredId = null;
  if (rest.length > 1 && rest.charCodeAt(0) === 35) {
    const dotIdx = rest.indexOf(".");
    if (dotIdx === -1) {
      requiredId = rest.slice(1);
      rest = "";
    } else {
      requiredId = rest.slice(1, dotIdx);
      rest = rest.slice(dotIdx);
    }
  }
  if (requiredId !== null && String(node.id || "") !== requiredId) {
    return false;
  }

  const parts = rest.split(".");
  const tagPart = parts[0].trim();
  const classes = parts.slice(1).filter(Boolean);
  if (tagPart && tagPart !== "*" && String(node.tagName || "").toUpperCase() !== tagPart.toUpperCase()) {
    return false;
  }
  if (classes.length > 0) {
    const clsTokens = String(node.className || "")
      .split(/\s+/)
      .filter(Boolean);
    for (const c of classes) {
      if (!clsTokens.includes(c)) return false;
    }
  }
  return true;
}

function collectMatchingDescendants(root, selectorList) {
  const results = [];
  const groups = String(selectorList)
    .split(",")
    .map((g) => g.trim())
    .filter(Boolean);

  function matchesChain(ancestors, node, chain) {
    if (!matchesSingleCompound(node, chain[chain.length - 1])) {
      return false;
    }
    if (chain.length === 1) return true;
    let chainIdx = chain.length - 2;
    for (let i = ancestors.length - 1; i >= 0 && chainIdx >= 0; i -= 1) {
      if (matchesSingleCompound(ancestors[i], chain[chainIdx])) {
        chainIdx -= 1;
      }
    }
    return chainIdx < 0;
  }

  function walk(cur, ancestors) {
    const kids = Array.isArray(cur.childNodes) ? cur.childNodes : [];
    for (const child of kids) {
      if (child && child.nodeType === 1) {
        const matched = groups.some((grp) => {
          const chain = grp.split(/\s+/).filter(Boolean);
          return chain.length > 0 && matchesChain(ancestors, child, chain);
        });
        if (matched) {
          results.push(child);
        }
        ancestors.push(child);
        walk(child, ancestors);
        ancestors.pop();
      }
    }
  }

  walk(root, []);
  return results;
}

function createVirtualDocument() {
  const vdoc = {
    createTextNode(text) {
      const str = String(text);
      return {
        nodeType: 3,
        textContent: str,
        nodeValue: str,
        data: str,
        ownerDocument: vdoc,
      };
    },
    createElement(tag) {
      const attrs = Object.create(null);
      const listeners = Object.create(null);
      const dataset = Object.create(null);
      const style = { cssText: "" };
      const classSet = new Set();
      const node = {
        nodeType: 1,
        tagName: String(tag).toUpperCase(),
        id: "",
        className: "",
        disabled: false,
        hidden: false,
        selected: false,
        type: "",
        value: "",
        dataset,
        style,
        attributes: attrs,
        childNodes: [],
        children: [],
        parentNode: null,
        ownerDocument: vdoc,
        classList: {
          add(...tokens) {
            for (const t of tokens) {
              if (t) classSet.add(String(t));
            }
            node.className = Array.from(classSet).join(" ");
            attrs.class = node.className;
          },
          remove(...tokens) {
            for (const t of tokens) {
              classSet.delete(String(t));
            }
            node.className = Array.from(classSet).join(" ");
            attrs.class = node.className;
          },
          contains(token) {
            return classSet.has(String(token));
          },
          toggle(token, force) {
            const key = String(token);
            const next = force !== undefined ? Boolean(force) : !classSet.has(key);
            if (next) classSet.add(key);
            else classSet.delete(key);
            node.className = Array.from(classSet).join(" ");
            attrs.class = node.className;
            return next;
          },
        },
        get firstChild() {
          return this.childNodes.length > 0 ? this.childNodes[0] : null;
        },
        get textContent() {
          return this.childNodes
            .map((c) => (c ? String(c.textContent || "") : ""))
            .join("");
        },
        set textContent(val) {
          this.childNodes.length = 0;
          this.children.length = 0;
          if (val !== null && val !== undefined && String(val) !== "") {
            const tn = vdoc.createTextNode(String(val));
            tn.parentNode = this;
            this.childNodes.push(tn);
          }
        },
        setAttribute(k, v) {
          const key = String(k);
          const strVal = String(v);
          attrs[key] = strVal;
          if (key === "id") this.id = strVal;
          if (key === "class") {
            this.className = strVal;
            classSet.clear();
            for (const tok of strVal.split(/\s+/).filter(Boolean)) {
              classSet.add(tok);
            }
          }
          if (key === "disabled") this.disabled = true;
          if (key === "hidden") this.hidden = true;
          if (key === "selected") this.selected = true;
          if (key === "value") this.value = strVal;
          if (key === "type") this.type = strVal;
          if (key.startsWith("data-") && key.length > 5) {
            dataset[fromDataAttrName(key)] = strVal;
          }
        },
        getAttribute(k) {
          const key = String(k);
          return Object.prototype.hasOwnProperty.call(attrs, key) ? attrs[key] : null;
        },
        hasAttribute(k) {
          return Object.prototype.hasOwnProperty.call(attrs, String(k));
        },
        removeAttribute(k) {
          const key = String(k);
          delete attrs[key];
          if (key === "disabled") this.disabled = false;
          if (key === "hidden") this.hidden = false;
          if (key === "selected") this.selected = false;
        },
        appendChild(child) {
          if (!child) return child;
          child.parentNode = this;
          this.childNodes.push(child);
          if (child.nodeType === 1) {
            this.children.push(child);
          }
          return child;
        },
        removeChild(child) {
          const idx = this.childNodes.indexOf(child);
          if (idx >= 0) this.childNodes.splice(idx, 1);
          const cIdx = this.children.indexOf(child);
          if (cIdx >= 0) this.children.splice(cIdx, 1);
          if (child) child.parentNode = null;
          return child;
        },
        replaceChildren(...items) {
          this.childNodes.length = 0;
          this.children.length = 0;
          for (const it of items) {
            if (it && typeof it === "object" && "nodeType" in it) {
              this.appendChild(it);
            } else if (it !== null && it !== undefined) {
              this.appendChild(vdoc.createTextNode(String(it)));
            }
          }
        },
        addEventListener(type, fn) {
          const evType = String(type).toLowerCase();
          if (!listeners[evType]) listeners[evType] = [];
          listeners[evType].push(fn);
        },
        dispatchEvent(eventObj) {
          const ev = eventObj || { type: "" };
          const evType = String(ev.type || "").toLowerCase();
          if (!ev.target) ev.target = this;
          if (!ev.currentTarget) ev.currentTarget = this;
          if (typeof ev.preventDefault !== "function") ev.preventDefault = () => {};
          if (typeof ev.stopPropagation !== "function") ev.stopPropagation = () => {};
          const list = listeners[evType] ? listeners[evType].slice() : [];
          for (const fn of list) {
            fn.call(this, ev);
          }
          return true;
        },
        click() {
          if (this.disabled) return;
          this.dispatchEvent({ type: "click", target: this, currentTarget: this });
        },
        querySelector(sel) {
          const hits = collectMatchingDescendants(this, sel);
          return hits.length > 0 ? hits[0] : null;
        },
        querySelectorAll(sel) {
          return collectMatchingDescendants(this, sel);
        },
      };
      return node;
    },
  };
  return vdoc;
}

function getVirtualDocument() {
  if (!cachedVirtualDoc) {
    cachedVirtualDoc = createVirtualDocument();
  }
  return cachedVirtualDoc;
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
  return getVirtualDocument();
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

function isForbiddenPreEndKey(key) {
  const ks = String(key);
  return FORBIDDEN_PRE_END_KEYS.has(ks) || ks.toLowerCase().includes("world_secret");
}

function scrubPreEndValue(input) {
  if (input === null || input === undefined) return input;
  if (Array.isArray(input)) {
    return input.map((item) => scrubPreEndValue(item));
  }
  if (typeof input !== "object") return input;
  const out = {};
  for (const [k, v] of Object.entries(input)) {
    if (isForbiddenPreEndKey(k)) continue;
    out[k] = scrubPreEndValue(v);
  }
  return out;
}

export function validateSeed(seed) {
  if (typeof seed === "boolean" || seed === null || seed === undefined) {
    throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
  }
  if (typeof seed === "string") {
    const trimmed = seed.trim();
    if (!/^\d+$/.test(trimmed)) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
    const parsed = Number(trimmed);
    if (
      !Number.isInteger(parsed) ||
      String(parsed) !== trimmed ||
      parsed < SEED_MIN ||
      parsed > SEED_MAX
    ) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
    return parsed;
  }
  if (typeof seed === "number") {
    if (
      !Number.isInteger(seed) ||
      Object.is(seed, -0) ||
      seed < SEED_MIN ||
      seed > SEED_MAX
    ) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
    return seed;
  }
  throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
}

export const checkSeed = validateSeed;
export const check_seed = validateSeed;

export function validateTier(tier) {
  if (typeof tier !== "string") {
    throw new RangeError("tier must be medium or hard");
  }
  const cleaned = tier.trim();
  if (!ALLOWED_TIERS.includes(cleaned)) {
    throw new RangeError("tier must be medium or hard");
  }
  return cleaned;
}

export const checkTier = validateTier;
export const check_tier = validateTier;

function normalizeSeedAndTier(seed = SEED_MIN, tier = DEFAULT_TIER) {
  if (
    typeof seed === "string" &&
    ALLOWED_TIERS.includes(seed.trim()) &&
    typeof tier !== "boolean" &&
    (typeof tier === "number" || (typeof tier === "string" && /^\d+$/.test(tier.trim())))
  ) {
    return { validSeed: validateSeed(tier), validTier: validateTier(seed) };
  }
  return { validSeed: validateSeed(seed), validTier: validateTier(tier) };
}

function normalizeArenaSeed(seed) {
  if (seed === undefined) {
    return { displaySeed: SEED_MIN, engineSeed: SEED_MIN };
  }
  if (typeof seed === "boolean" || seed === null) {
    throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
  }
  let parsed = null;
  if (typeof seed === "string") {
    const trimmed = seed.trim();
    if (!/^\d+$/.test(trimmed)) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
    parsed = Number(trimmed);
    if (!Number.isInteger(parsed) || String(parsed) !== trimmed) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
  } else if (typeof seed === "number") {
    if (!Number.isInteger(seed) || Object.is(seed, -0)) {
      throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
    }
    parsed = seed;
  } else {
    throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
  }
  if (ARENA_SHOWCASE_DUEL_SEEDS.has(parsed)) {
    return { displaySeed: parsed, engineSeed: SEED_MIN + parsed };
  }
  if (parsed < SEED_MIN || parsed > SEED_MAX) {
    throw new RangeError(`seed must be an integer in ${SEED_MIN}..${SEED_MAX}`);
  }
  return { displaySeed: parsed, engineSeed: parsed };
}

function isThenable(value) {
  return Boolean(
    value &&
      (typeof value === "object" || typeof value === "function") &&
      typeof value.then === "function"
  );
}

function chainMaybeAsync(value, fn) {
  if (isThenable(value)) {
    return value.then(fn);
  }
  return fn(value);
}

function extractCoverEmployee(rawView) {
  if (!rawView || typeof rawView !== "object") {
    return {
      id: "e01",
      name: "Assigned Insider",
      dept: "Operations",
      role: "Analyst",
      clearance: "standard",
    };
  }
  const src =
    rawView.moleEmployee && typeof rawView.moleEmployee === "object"
      ? rawView.moleEmployee
      : rawView.employee && typeof rawView.employee === "object"
        ? rawView.employee
        : null;
  return {
    id: String((src && src.id) || rawView.mole_id || rawView.moleId || "e01"),
    name: String((src && src.name) || rawView.mole_name || "Assigned Insider"),
    dept: String((src && src.dept) || rawView.mole_dept || "Operations"),
    role: String((src && src.role) || rawView.mole_role || "Analyst"),
    clearance: String((src && src.clearance) || rawView.mole_clearance || "standard"),
  };
}

const CANARY_TITLE_RE = new RegExp("canary|^Board memo draft", "i");

function scrubCoverTitle(rawTitle) {
  const txt = String(rawTitle || "");
  return CANARY_TITLE_RE.test(txt) ? "Internal department memo" : txt;
}

function sanitizeDocItem(doc) {
  if (!doc || typeof doc !== "object") {
    return {
      doc_id: "",
      title: "",
      day: 1,
      age_days: 0,
      recipient_count: 0,
      recipients: [],
    };
  }
  const recipients = Array.isArray(doc.recipients) ? doc.recipients.map((r) => String(r)) : [];
  const recipientCount =
    doc.recipient_count !== undefined ? Number(doc.recipient_count) : recipients.length;
  return {
    doc_id: String(doc.doc_id || doc.id || ""),
    title: scrubCoverTitle(doc.title),
    day: Number(doc.day || 1),
    age_days: Number(doc.age_days !== undefined ? doc.age_days : 0),
    recipient_count: Number.isFinite(recipientCount) ? recipientCount : 0,
    recipients,
  };
}

export function sanitizeDayView(rawView) {
  if (!rawView || typeof rawView !== "object") {
    return null;
  }
  const coverEmp = extractCoverEmployee(rawView);
  const out = {};
  for (const [key, val] of Object.entries(rawView)) {
    if (isForbiddenPreEndKey(key)) continue;
    if (key === "leakable_docs" || key === "docs") continue;
    if (key === "employee" || key === "moleEmployee") continue;
    if (key === "surfaced_leaks" && Array.isArray(val)) {
      out.surfaced_leaks = val.map((item) => ({
        surfaced_day: Number((item && item.surfaced_day) || 1),
        doc_id: String((item && item.doc_id) || ""),
        title: scrubCoverTitle(item && item.title),
      }));
      continue;
    }
    out[key] = scrubPreEndValue(val);
  }
  const visV =
    rawView.visible_v !== undefined
      ? Number(rawView.visible_v)
      : rawView.visible_V !== undefined
        ? Number(rawView.visible_V)
        : rawView.known_v !== undefined
          ? Number(rawView.known_v)
          : 1.0;
  const safeV = Number.isFinite(visV) ? visV : 1.0;
  out.visible_v = safeV;
  out.visible_V = safeV;
  out.known_v = safeV;
  out.employee = Object.assign({}, coverEmp);
  out.moleEmployee = Object.assign({}, coverEmp);
  const rawDocs = Array.isArray(rawView.leakable_docs)
    ? rawView.leakable_docs
    : Array.isArray(rawView.docs)
      ? rawView.docs
      : [];
  const cleanDocs = rawDocs.map(sanitizeDocItem);
  out.leakable_docs = cleanDocs;
  out.docs = cleanDocs.map((d) => Object.assign({}, d, { recipients: d.recipients.slice() }));
  return out;
}

function sanitizeStepResponse(rawRes) {
  if (!rawRes || typeof rawRes !== "object") {
    return rawRes;
  }
  if (rawRes.done === true) {
    return Object.assign({}, rawRes);
  }
  const out = {};
  for (const [k, v] of Object.entries(rawRes)) {
    if (isForbiddenPreEndKey(k)) continue;
    if (k === "day_view" || k === "outcome") continue;
    out[k] = scrubPreEndValue(v);
  }
  out.done = false;
  out.day_view = rawRes.day_view ? sanitizeDayView(rawRes.day_view) : null;
  out.outcome = null;
  return out;
}

function parsePyResult(raw) {
  if (typeof raw === "string") {
    return JSON.parse(raw);
  }
  if (raw && typeof raw.toJs === "function") {
    const converted = raw.toJs({ dict_converter: Object.fromEntries });
    if (typeof raw.destroy === "function") {
      raw.destroy();
    }
    return typeof converted === "string" ? JSON.parse(converted) : converted;
  }
  if (raw && typeof raw === "object") {
    return raw;
  }
  throw new Error("Unexpected response from mole_mode Python bridge");
}

function hasGlobalsSet(pyodide) {
  return Boolean(pyodide && pyodide.globals && typeof pyodide.globals.set === "function");
}

function setPyGlobal(pyodide, key, value) {
  if (!pyodide || !pyodide.globals) return false;
  if (typeof pyodide.globals.set === "function") {
    pyodide.globals.set(key, value);
    return true;
  }
  if (typeof pyodide.globals === "object") {
    pyodide.globals[key] = value;
    return true;
  }
  return false;
}

function runPyBridgeCall(pyodide, code, methodName, directArgs) {
  if (typeof pyodide.runPython === "function") {
    return chainMaybeAsync(pyodide.runPython(code), parsePyResult);
  }
  if (typeof pyodide.runPythonAsync === "function") {
    return chainMaybeAsync(pyodide.runPythonAsync(code), parsePyResult);
  }
  if (typeof pyodide[methodName] === "function") {
    return chainMaybeAsync(pyodide[methodName](...directArgs), parsePyResult);
  }
  if (typeof pyodide.pyimport === "function") {
    return chainMaybeAsync(pyodide.pyimport("mole_mode"), (mod) =>
      chainMaybeAsync(mod[methodName](...directArgs), parsePyResult)
    );
  }
  throw new Error("pyodide must provide runPython, runPythonAsync, or pyimport");
}

function normalizeActionForBridge(action) {
  if (typeof action === "string") {
    return action;
  }
  if (!action || typeof action !== "object") {
    return action;
  }
  if ("leakDocId" in action && !("type" in action) && !("action" in action)) {
    const frameVal =
      action.framePeer !== undefined
        ? action.framePeer
        : action.frame_peer !== undefined
          ? action.frame_peer
          : null;
    if (action.leakDocId) {
      return {
        type: "leak",
        doc_id: String(action.leakDocId),
        frame_peer: frameVal || null,
      };
    }
    return {
      type: "hold",
      frame_peer: frameVal || null,
    };
  }
  return action;
}

export function createPyodideBridge(pyodide) {
  if (!pyodide || (typeof pyodide !== "object" && typeof pyodide !== "function")) {
    throw new TypeError("pyodide instance is required");
  }

  const bridge = {
    startGame(seed = SEED_MIN, tier = DEFAULT_TIER) {
      const { validSeed, validTier } = normalizeSeedAndTier(seed, tier);
      setPyGlobal(pyodide, "_mole_seed", validSeed);
      setPyGlobal(pyodide, "_mole_tier", validTier);
      const code =
        PY_IMPORT_PRELUDE +
        `_canary_mm.start_mole_game_json(${validSeed}, ${JSON.stringify(validTier)})`;
      return chainMaybeAsync(
        runPyBridgeCall(pyodide, code, "start_mole_game_json", [validSeed, validTier]),
        (res) => (res && res.done ? res : sanitizeDayView(res))
      );
    },

    getDayView() {
      const code = PY_IMPORT_PRELUDE + "_canary_mm.get_mole_day_view_json()";
      return chainMaybeAsync(
        runPyBridgeCall(pyodide, code, "get_mole_day_view_json", []),
        (res) => (res && res.done ? res : sanitizeDayView(res))
      );
    },

    stepDay(action) {
      const normalized = normalizeActionForBridge(action);
      const actionJson =
        typeof normalized === "string" ? normalized : JSON.stringify(normalized);
      let code = "";
      if (hasGlobalsSet(pyodide)) {
        setPyGlobal(pyodide, "_mole_action_json", actionJson);
        code = PY_IMPORT_PRELUDE + "_canary_mm.step_mole_day_json(_mole_action_json)";
      } else {
        setPyGlobal(pyodide, "_mole_action_json", actionJson);
        code =
          PY_IMPORT_PRELUDE +
          `_canary_mm.step_mole_day_json(${JSON.stringify(actionJson)})`;
      }
      return chainMaybeAsync(
        runPyBridgeCall(pyodide, code, "step_mole_day_json", [actionJson]),
        (res) => sanitizeStepResponse(res)
      );
    },

    getDebrief() {
      const code = PY_IMPORT_PRELUDE + "_canary_mm.get_mole_debrief_json()";
      return runPyBridgeCall(pyodide, code, "get_mole_debrief_json", []);
    },
  };

  bridge.onMoleAction = (action) => bridge.stepDay(action);
  return bridge;
}

function resolveDocOption(opts, rootNode) {
  if (opts && opts.document) {
    return opts.document;
  }
  if (rootNode && rootNode.ownerDocument) {
    return rootNode.ownerDocument;
  }
  if (fallbackDocument) {
    return fallbackDocument;
  }
  if (typeof globalThis !== "undefined" && globalThis.document) {
    return globalThis.document;
  }
  return getVirtualDocument();
}

export function renderMoleDebrief(debrief, handlers = {}, opts = {}) {
  if (!debrief || typeof debrief !== "object" || debrief.ok === false) {
    return null;
  }
  const doc = resolveDocOption(opts, null);
  const caught = Boolean(debrief.caught);
  const survived = debrief.survived !== undefined ? Boolean(debrief.survived) : !caught;
  const outcomeWord = survived ? "survived" : "caught";
  const moleScoreText = fmtScore(debrief.mole_score);
  const solverScoreText = fmtScore(debrief.solver_score);
  const finalDay = Number(debrief.final_day || 0);
  const daysSurvived = Number(
    debrief.days_survived !== undefined ? debrief.days_survived : finalDay
  );
  const leaksCount = Number(
    debrief.leaks_count !== undefined
      ? debrief.leaks_count
      : Array.isArray(debrief.leaks_made)
        ? debrief.leaks_made.length
        : 0
  );

  const curveItems = Array.isArray(debrief.posterior_curve) ? debrief.posterior_curve : [];
  const curveRows = curveItems.map((snap) => {
    const dayNum = Number(snap.day || 1);
    const pVal = Number(
      snap.mole_posterior !== undefined ? snap.mole_posterior : snap.posterior || 0
    );
    const pct = `${(pVal * 100).toFixed(1)}%`;
    const rankStr = snap.mole_rank !== undefined ? String(snap.mole_rank) : "-";
    return el(
      "div",
      {
        document: doc,
        class: "posterior-point mono",
        dataset: { day: String(dayNum), posterior: pVal.toFixed(4) },
      },
      `Day ${pad2(dayNum)}: ${pct} (${pVal.toFixed(3)}) rank ${rankStr}`
    );
  });

  const leakedCanaries = Array.isArray(debrief.leaked_canaries) ? debrief.leaked_canaries : [];
  const caughtBy =
    debrief.caught_by_canary && typeof debrief.caught_by_canary === "object"
      ? debrief.caught_by_canary
      : null;

  const canaryChildren = [];
  if (caughtBy) {
    canaryChildren.push(
      el(
        "div",
        {
          document: doc,
          class: "leak-alert",
          dataset: { role: "caught-by-canary", docId: String(caughtBy.doc_id || "") },
        },
        `Caught by canary ${String(caughtBy.doc_id || "")} (variant ${String(caughtBy.variant || "?")}, leaked Day ${Number(caughtBy.leaked_day || 0)}, surfaced Day ${Number(caughtBy.surfaced_day || 0)})`
      )
    );
  }
  if (leakedCanaries.length > 0) {
    for (const can of leakedCanaries) {
      canaryChildren.push(
        el(
          "div",
          {
            document: doc,
            class: "canary-hit mono",
            dataset: { docId: String(can.doc_id || "") },
          },
          `Canary leaked: ${String(can.doc_id || "")} | variant ${String(can.variant || "?")} | Day ${Number(can.leaked_day || 0)} -> surfaced Day ${Number(can.surfaced_day || 0)}`
        )
      );
    }
  } else {
    canaryChildren.push(
      el(
        "div",
        { document: doc, class: "dim mono" },
        "No canary trap documents leaked."
      )
    );
  }

  const actionNodes = [];
  if (handlers && typeof handlers.onRestart === "function") {
    actionNodes.push(
      el(
        "div",
        { document: doc, class: "seed-group" },
        el(
          "button",
          {
            document: doc,
            type: "button",
            class: "ghost",
            dataset: { action: "restart" },
            onClick: () => handlers.onRestart(),
          },
          "Play Again"
        )
      )
    );
  }

  return el(
    "section",
    {
      document: doc,
      class: "arena-end-card",
      dataset: { outcome: outcomeWord },
    },
    el(
      "div",
      { document: doc, class: "sheet-h" },
      el(
        "strong",
        { document: doc, class: "first-catch-badge" },
        `Outcome: ${outcomeWord}`
      ),
      el(
        "span",
        { document: doc, class: "mono" },
        `Accused: ${String(debrief.accused_id || "none")} | Days survived: ${daysSurvived} | Leaks: ${leaksCount}`
      )
    ),
    el(
      "table",
      { document: doc, class: "h2h-table" },
      el(
        "thead",
        { document: doc },
        el(
          "tr",
          { document: doc },
          el("th", { document: doc }, "Side"),
          el("th", { document: doc }, "Outcome"),
          el("th", { document: doc }, "Score")
        )
      ),
      el(
        "tbody",
        { document: doc },
        el(
          "tr",
          { document: doc },
          el("td", { document: doc }, "You (Mole)"),
          el("td", { document: doc }, outcomeWord),
          el("td", { document: doc, class: "mono", dataset: { role: "mole-score" } }, moleScoreText)
        ),
        el(
          "tr",
          { document: doc },
          el("td", { document: doc }, "SolverPolicy"),
          el("td", { document: doc }, caught ? "caught mole" : "evaded"),
          el("td", { document: doc, class: "mono", dataset: { role: "solver-score" } }, solverScoreText)
        )
      )
    ),
    el(
      "div",
      { document: doc, class: "posterior-curve", dataset: { role: "posterior-curve" } },
      el("strong", { document: doc }, "Solver Posterior Curve"),
      curveRows.length > 0
        ? curveRows
        : el("span", { document: doc, class: "dim mono" }, "No solver trace recorded.")
    ),
    el(
      "div",
      { document: doc, class: "canary-forensics", dataset: { role: "leaked-canaries" } },
      el("strong", { document: doc }, "Canary Trap Forensics"),
      canaryChildren
    ),
    actionNodes
  );
}

export function renderMolePanel(state = {}, handlers = {}, opts = {}) {
  const doc = resolveDocOption(opts, null);

  const rawDayView = state && state.dayView ? state.dayView : state || {};
  const isDone = Boolean(
    (state && state.done === true) ||
      (rawDayView && rawDayView.done === true) ||
      (state && state.lastStep && state.lastStep.done === true)
  );
  const dayView = isDone ? rawDayView : sanitizeDayView(rawDayView) || {};
  const selectedDocId =
    state && state.selectedDocId !== undefined && state.selectedDocId !== null
      ? String(state.selectedDocId)
      : null;
  const framePeer =
    state && state.framePeer !== undefined && state.framePeer !== null
      ? String(state.framePeer)
      : "";

  const dayNum = Number(dayView.day || 1);
  const nDays = Number(dayView.n_days || dayView.nDays || 14);
  const visV =
    dayView.visible_v !== undefined
      ? Number(dayView.visible_v)
      : dayView.visible_V !== undefined
        ? Number(dayView.visible_V)
        : dayView.visibleV !== undefined
          ? Number(dayView.visibleV)
          : 1.0;

  const emp = extractCoverEmployee(dayView);
  const coverId = emp.id;
  const coverName = emp.name;
  const coverDept = emp.dept;

  const alerts = [];
  if (dayView.i_am_restricted) {
    alerts.push(
      el(
        "div",
        { document: doc, class: "leak-alert", dataset: { alert: "restricted" } },
        "Access restricted: you receive no new documents while under restriction."
      )
    );
  }
  if (dayView.interviewed_today) {
    const topics = Array.isArray(dayView.interview_topics_today)
      ? dayView.interview_topics_today.join(", ")
      : "";
    alerts.push(
      el(
        "div",
        { document: doc, class: "leak-alert", dataset: { alert: "interviewed" } },
        topics
          ? `Investigator interviewed you today (${topics}).`
          : "Investigator interviewed you today."
      )
    );
  }
  if (state && state.lastStep && state.lastStep.ok === false && state.lastStep.error) {
    alerts.push(
      el(
        "div",
        { document: doc, class: "leak-alert", dataset: { alert: "error" } },
        String(state.lastStep.error)
      )
    );
  }

  const leakableDocs = Array.isArray(dayView.leakable_docs)
    ? dayView.leakable_docs
    : Array.isArray(dayView.moleCandidateDocs)
      ? dayView.moleCandidateDocs
      : [];
  const docCards = leakableDocs.map((rawDoc) => {
    const safeDoc = sanitizeDocItem(rawDoc);
    const docId = safeDoc.doc_id;
    const isSelected = selectedDocId === docId;
    return el(
      "div",
      {
        document: doc,
        class: isSelected ? "leak-picker-card selected" : "leak-picker-card",
        dataset: { docId },
        "aria-selected": String(isSelected),
        onClick: () => {
          if (!isDone && handlers && typeof handlers.onSelectDoc === "function") {
            handlers.onSelectDoc(docId);
          }
        },
      },
      el("strong", { document: doc, class: "mono" }, docId),
      el("span", { document: doc, class: "doc-title" }, safeDoc.title),
      el(
        "span",
        { document: doc, class: "dim mono" },
        `Recipients: ${safeDoc.recipient_count} | Age: ${safeDoc.age_days}d`
      )
    );
  });

  const gridChildren =
    docCards.length > 0
      ? docCards
      : [
          el(
            "div",
            { document: doc, class: "dim mono", dataset: { role: "empty-docs" } },
            "No leakable documents in window today; hold tonight to advance."
          ),
        ];

  const peerRoster = Array.isArray(dayView.peer_roster) ? dayView.peer_roster : [];
  const peerIds = Array.isArray(dayView.peers) ? dayView.peers : [];
  const selectOptions = [
    el("option", { document: doc, value: "" }, "No frame"),
  ];
  if (peerRoster.length > 0) {
    for (const peer of peerRoster) {
      const pid = String(peer.id || "");
      if (!pid) continue;
      const label = peer.name
        ? `${pid} - ${String(peer.name)} (${String(peer.dept || "")})`
        : pid;
      selectOptions.push(
        el(
          "option",
          {
            document: doc,
            value: pid,
            selected: framePeer === pid,
          },
          label
        )
      );
    }
  } else {
    for (const pidRaw of peerIds) {
      const pid = String(pidRaw || "");
      if (!pid) continue;
      selectOptions.push(
        el(
          "option",
          {
            document: doc,
            value: pid,
            selected: framePeer === pid,
          },
          pid
        )
      );
    }
  }

  const frameSelect = el(
    "select",
    {
      document: doc,
      dataset: { role: "frame-select" },
      value: framePeer,
      disabled: isDone,
      onChange: (ev) => {
        if (isDone) return;
        const nextVal =
          ev && ev.target && typeof ev.target.value === "string" ? ev.target.value : "";
        const handler =
          (handlers && (handlers.onFramePeerChange || handlers.onSetFramePeer)) || null;
        if (typeof handler === "function") {
          handler(nextVal || null);
        }
      },
    },
    selectOptions
  );

  const leakBtn = el(
    "button",
    {
      document: doc,
      type: "button",
      class: "primary",
      dataset: { action: "leak" },
      disabled: Boolean(isDone || !selectedDocId || docCards.length === 0),
      onClick: () => {
        if (isDone) return;
        if (handlers && typeof handlers.onLeak === "function") {
          handlers.onLeak();
        } else if (handlers && typeof handlers.onMoleAction === "function" && selectedDocId) {
          handlers.onMoleAction({
            type: "leak",
            doc_id: selectedDocId,
            frame_peer: framePeer || null,
          });
        }
      },
    },
    selectedDocId ? `Leak ${selectedDocId}` : "Leak Selected"
  );

  const holdBtn = el(
    "button",
    {
      document: doc,
      type: "button",
      class: "ghost",
      dataset: { action: "hold" },
      disabled: isDone,
      onClick: () => {
        if (isDone) return;
        if (handlers && typeof handlers.onHold === "function") {
          handlers.onHold();
        } else if (handlers && typeof handlers.onMoleAction === "function") {
          handlers.onMoleAction({
            type: "hold",
            frame_peer: framePeer || null,
          });
        }
      },
    },
    "Hold Day"
  );

  const debriefNode =
    isDone && state && state.debrief && state.debrief.ok === true
      ? renderMoleDebrief(state.debrief, handlers, opts)
      : null;

  return el(
    "section",
    {
      document: doc,
      class: "mole-panel",
      dataset: {
        day: String(dayNum),
        done: String(isDone),
      },
    },
    el(
      "div",
      { document: doc, class: "sheet-h" },
      el(
        "span",
        { document: doc },
        `Be the Mole | ${coverName} (${coverId}${coverDept ? ", " + coverDept : ""})`
      ),
      el(
        "span",
        { document: doc, class: "mono" },
        `Day ${pad2(dayNum)}/${pad2(nDays)} | V ${visV.toFixed(2)} | Restricted: ${Number(dayView.total_staff_restricted || 0)} | Surfaced: ${Number(dayView.total_surfaced_leaks || 0)}`
      )
    ),
    alerts,
    el("div", { document: doc, class: "leak-picker-grid" }, gridChildren),
    el(
      "div",
      { document: doc, class: "mole-actions seed-group" },
      frameSelect,
      leakBtn,
      holdBtn
    ),
    debriefNode
  );
}

function normalizeControllerAction(action) {
  if (!action || typeof action !== "object") {
    throw new TypeError("action must be an object");
  }
  const normalized = normalizeActionForBridge(action);
  const rawType = String(normalized.type || normalized.action || "").trim().toLowerCase();
  const out = { type: rawType };
  if (normalized.doc_id !== undefined && normalized.doc_id !== null) {
    out.doc_id = String(normalized.doc_id);
  }
  const fp =
    normalized.frame_peer !== undefined
      ? normalized.frame_peer
      : normalized.frame !== undefined
        ? normalized.frame
        : null;
  out.frame_peer = fp || null;
  return out;
}

function cloneStateSnapshot(state) {
  return {
    seed: state.seed,
    tier: state.tier,
    dayView: state.dayView ? Object.assign({}, state.dayView) : null,
    selectedDocId: state.selectedDocId,
    framePeer: state.framePeer,
    lastStep: state.lastStep ? Object.assign({}, state.lastStep) : null,
    debrief: state.debrief ? Object.assign({}, state.debrief) : null,
    history: state.history.map((item) => Object.assign({}, item)),
  };
}

export function createMoleModeController(options = {}) {
  const root = options.root || null;
  const activeBridge =
    options.bridge || (options.pyodide ? createPyodideBridge(options.pyodide) : null);
  const doc = resolveDocOption(options, root);
  const onStateChange =
    typeof options.onStateChange === "function" ? options.onStateChange : null;

  const state = {
    seed: null,
    tier: DEFAULT_TIER,
    dayView: null,
    selectedDocId: null,
    framePeer: null,
    lastStep: null,
    debrief: null,
    history: [],
  };

  const controller = {
    async start(seed = SEED_MIN, tier = DEFAULT_TIER) {
      const { validSeed, validTier } = normalizeSeedAndTier(seed, tier);
      if (!activeBridge) {
        throw new Error("createMoleModeController requires bridge or pyodide");
      }
      const rawView = await activeBridge.startGame(validSeed, validTier);
      state.seed = validSeed;
      state.tier = validTier;
      state.dayView = rawView && rawView.done ? rawView : sanitizeDayView(rawView);
      state.selectedDocId = null;
      state.framePeer = null;
      state.lastStep = null;
      state.debrief = null;
      state.history = [];
      if (state.dayView && state.dayView.done === true) {
        state.debrief = await activeBridge.getDebrief();
      }
      renderCurrent();
      emitChange();
      return cloneStateSnapshot(state);
    },

    selectDoc(docId) {
      if (docId === null || docId === undefined || docId === "") {
        state.selectedDocId = null;
        renderCurrent();
        emitChange();
        return null;
      }
      const target = String(docId).trim();
      const docs =
        state.dayView && Array.isArray(state.dayView.leakable_docs)
          ? state.dayView.leakable_docs
          : [];
      const found = docs.some((d) => String(d.doc_id) === target);
      if (!found) {
        throw new RangeError(`doc_id ${target} is not in leakable_docs`);
      }
      state.selectedDocId = target;
      renderCurrent();
      emitChange();
      return state.selectedDocId;
    },

    setFramePeer(peerIdOrNull) {
      if (
        peerIdOrNull === null ||
        peerIdOrNull === undefined ||
        peerIdOrNull === "" ||
        peerIdOrNull === "none"
      ) {
        state.framePeer = null;
        renderCurrent();
        emitChange();
        return null;
      }
      const clean = String(peerIdOrNull).trim();
      const peers =
        state.dayView && Array.isArray(state.dayView.peers) ? state.dayView.peers : null;
      if (
        peers &&
        !peers.includes(clean) &&
        clean !== "random_peer" &&
        clean !== "most_restricted_peer"
      ) {
        throw new RangeError(`frame_peer ${clean} is not a valid peer`);
      }
      state.framePeer = clean;
      renderCurrent();
      emitChange();
      return state.framePeer;
    },

    async leakSelected() {
      if (!state.selectedDocId) {
        throw new Error("No leakable document selected");
      }
      return controller.step({
        type: "leak",
        doc_id: state.selectedDocId,
        frame_peer: state.framePeer,
      });
    },

    async holdDay() {
      return controller.step({
        type: "hold",
        frame_peer: state.framePeer,
      });
    },

    async step(action) {
      if (!activeBridge) {
        throw new Error("createMoleModeController requires bridge or pyodide");
      }
      const normalized = normalizeControllerAction(action);
      const activeDay = state.dayView ? Number(state.dayView.day || 1) : 1;
      const rawRes = await activeBridge.stepDay(normalized);
      const res = rawRes && !rawRes.done ? sanitizeStepResponse(rawRes) : rawRes;
      state.lastStep = res;
      if (res && res.day_view) {
        state.dayView = res.done ? res.day_view : sanitizeDayView(res.day_view);
      }
      if (res && res.ok) {
        const applied =
          res.applied_action && typeof res.applied_action === "object"
            ? Object.assign({}, res.applied_action)
            : {
                day: activeDay,
                type: normalized.type,
                doc_id: normalized.doc_id || null,
                frame_peer: normalized.frame_peer || null,
              };
        state.history.push(applied);
        state.selectedDocId = null;
      }
      if (res && res.done === true) {
        state.debrief = await activeBridge.getDebrief();
      }
      renderCurrent();
      emitChange();
      return res;
    },

    onMoleAction(action) {
      return controller.step(action);
    },

    getState() {
      return cloneStateSnapshot(state);
    },

    render() {
      renderCurrent();
      return root;
    },

    destroy() {
      if (root) {
        clear(root);
      }
    },
  };

  const handlers = {
    onSelectDoc(docId) {
      controller.selectDoc(docId);
    },
    onFramePeerChange(peerId) {
      controller.setFramePeer(peerId);
    },
    onLeak() {
      return controller.leakSelected();
    },
    onHold() {
      return controller.holdDay();
    },
    onMoleAction(action) {
      return controller.step(action);
    },
    onRestart() {
      if (state.seed !== null) {
        return controller.start(state.seed, state.tier);
      }
      return null;
    },
  };

  function renderCurrent() {
    if (!root || !doc) return;
    clear(root);
    const panel = renderMolePanel(state, handlers, { document: doc });
    root.appendChild(panel);
  }

  function emitChange() {
    if (onStateChange) {
      onStateChange(cloneStateSnapshot(state));
    }
  }

  return controller;
}

function createDeterministicFallbackBridge(engineSeed, tier) {
  const nDays = tier === "hard" ? 21 : 14;
  const nStaff = tier === "hard" ? 40 : 20;
  const coverNum = (engineSeed % nStaff) + 1;
  const coverId = `e${pad2(coverNum)}`;
  const peers = [];
  const peerRoster = [];
  const depts = ["Engineering", "Research", "Finance", "Sales", "Legal"];
  for (let i = 1; i <= nStaff; i += 1) {
    const eid = `e${pad2(i)}`;
    if (eid === coverId) continue;
    peers.push(eid);
    peerRoster.push({
      id: eid,
      name: `Staff ${pad2(i)}`,
      dept: depts[i % depts.length],
      role: "Specialist",
      restricted: false,
    });
  }

  let curDay = 1;
  let done = false;
  let caught = false;
  let accusedId = null;
  let visibleV = 1.0;
  const leaks = [];
  const history = [];
  const curve = [];

  function makeDocsForDay(d) {
    const items = [];
    const startDay = Math.max(1, d - 2);
    for (let dayIdx = startDay; dayIdx <= d; dayIdx += 1) {
      for (let slot = 1; slot <= 2; slot += 1) {
        const docId = `doc-d${dayIdx}-${slot}`;
        if (leaks.some((rec) => rec.doc_id === docId)) continue;
        const recCount = ((engineSeed + dayIdx * 7 + slot * 5) % 10) + 4;
        items.push({
          doc_id: docId,
          title: `Q${((dayIdx - 1) % 4) + 1} ${depts[(dayIdx + slot) % depts.length]} brief`,
          day: dayIdx,
          age_days: d - dayIdx,
          recipient_count: recCount,
          recipients: peers.slice(0, Math.min(peers.length, recCount - 1)).concat([coverId]),
        });
      }
    }
    return items;
  }

  function currentDayView() {
    const docs = makeDocsForDay(curDay);
    const surfaced = leaks
      .filter((l) => l.surfaced_day <= curDay)
      .map((l) => ({
        surfaced_day: l.surfaced_day,
        doc_id: l.doc_id,
        title: l.title,
      }));
    const coverEmp = {
      id: coverId,
      name: `Agent ${pad2(coverNum)}`,
      dept: depts[coverNum % depts.length],
      role: "Analyst",
      clearance: "elevated",
    };
    const base = {
      seed: engineSeed,
      tier,
      tiers_version: "v1.4",
      company: "Canary Corp",
      day: curDay,
      n_days: nDays,
      leak_window_days: 3,
      done,
      end_reason: done ? (caught ? "accused" : "horizon") : null,
      employee: coverEmp,
      moleEmployee: Object.assign({}, coverEmp),
      n_staff: nStaff,
      peers,
      peer_roster: peerRoster,
      leakable_docs: docs,
      docs: docs.map((x) => Object.assign({}, x, { recipients: x.recipients.slice() })),
      can_leak: docs.length > 0 && !done,
      days_since_last_leak: leaks.length
        ? curDay - leaks[leaks.length - 1].leaked_day
        : curDay,
      recent_low_recipient_docs: docs.filter((x) => x.recipient_count <= 5).length,
      visible_v: visibleV,
      visible_V: visibleV,
      known_v: visibleV,
      total_staff_restricted: 0,
      n_restricted_colleagues: 0,
      restricted_ids: [],
      i_am_restricted: false,
      restricted_today: false,
      interviewed_today: false,
      interview_topics_today: [],
      total_surfaced_leaks: surfaced.length,
      surfaced_leaks: surfaced,
      pressure: {
        total_staff_restricted: 0,
        i_am_restricted: false,
        restricted_today: false,
        interviewed_today: false,
        total_surfaced_leaks: surfaced.length,
        visible_v: visibleV,
      },
    };
    if (done) {
      base.mole_id = coverId;
      base.mole_name = coverEmp.name;
      base.mole_dept = coverEmp.dept;
      base.mole_role = coverEmp.role;
      base.mole_clearance = coverEmp.clearance;
    }
    return base;
  }

  return {
    startGame() {
      curve.push({
        day: 1,
        posterior: Number((1 / nStaff).toFixed(6)),
        mole_posterior: Number((1 / nStaff).toFixed(6)),
        top_suspect: peers[0] || coverId,
        top_posterior: Number((1 / nStaff).toFixed(6)),
        mole_rank: 1,
        visible_v: 1.0,
        true_v: 1.0,
      });
      return sanitizeDayView(currentDayView());
    },

    getDayView() {
      return done ? currentDayView() : sanitizeDayView(currentDayView());
    },

    stepDay(rawAction) {
      if (done) {
        return {
          ok: false,
          error: "episode over",
          done: true,
          day_view: currentDayView(),
          outcome: {
            done: true,
            survived: !caught,
            caught,
            accused_id: accusedId,
            final_day: curDay,
            mole_score: caught ? -visibleV : leaks.length ? Number((1 - visibleV).toFixed(4)) : 0,
            solver_score: caught ? visibleV : 0,
            leaks_count: leaks.length,
          },
        };
      }
      const act =
        typeof rawAction === "string"
          ? JSON.parse(rawAction)
          : normalizeActionForBridge(rawAction || {});
      const actType = String(act.type || act.action || "").trim().toLowerCase();
      if (actType !== "leak" && actType !== "hold") {
        return {
          ok: false,
          error: "action type must be 'leak' or 'hold'",
          done: false,
          day_view: sanitizeDayView(currentDayView()),
          outcome: null,
        };
      }
      const docs = makeDocsForDay(curDay);
      let leakedDoc = null;
      if (actType === "leak") {
        leakedDoc = docs.find((x) => x.doc_id === String(act.doc_id || ""));
        if (!leakedDoc) {
          return {
            ok: false,
            error: "doc_id is not a leakable document held by the mole",
            done: false,
            day_view: sanitizeDayView(currentDayView()),
            outcome: null,
          };
        }
        const leakDamage = tier === "hard" ? 0.05 : 0.04;
        leaks.push({
          leaked_day: curDay,
          surfaced_day: curDay + 1,
          doc_id: leakedDoc.doc_id,
          raw_doc_id: leakedDoc.doc_id,
          title: leakedDoc.title,
          raw_title: leakedDoc.title,
          is_canary: leaks.length >= 2,
          variant: leaks.length >= 2 ? "A" : null,
        });
        visibleV = Math.max(0, Number((visibleV - leakDamage).toFixed(4)));
      }
      const applied = {
        day: curDay,
        type: actType,
        doc_id: leakedDoc ? leakedDoc.doc_id : null,
        frame_peer: act.frame_peer || null,
      };
      history.push(applied);

      if (leaks.length >= 3) {
        done = true;
        caught = true;
        accusedId = coverId;
      } else if (curDay >= nDays) {
        done = true;
      } else {
        curDay += 1;
      }

      const postVal = Math.min(0.95, Number((1 / nStaff + leaks.length * 0.28).toFixed(6)));
      curve.push({
        day: curDay,
        posterior: postVal,
        mole_posterior: postVal,
        top_suspect: leaks.length >= 2 ? coverId : peers[0] || coverId,
        top_posterior: postVal,
        mole_rank: leaks.length >= 2 ? 1 : 3,
        visible_v: visibleV,
        true_v: visibleV,
      });

      const view = done ? currentDayView() : sanitizeDayView(currentDayView());
      const solverEvents = {
        day: curDay,
        total_staff_restricted: 0,
        restricted_ids: [],
        mole_interviewed: false,
        mole_restricted: false,
      };
      if (done) {
        solverEvents.accused = caught;
      }
      return {
        ok: true,
        applied_action: applied,
        solver_events: solverEvents,
        done,
        day_view: view,
        outcome: done
          ? {
              done: true,
              survived: !caught,
              caught,
              accused_id: accusedId,
              end_reason: caught ? "accused" : "horizon",
              final_day: curDay,
              mole_score: caught ? -visibleV : leaks.length ? Number((1 - visibleV).toFixed(4)) : 0,
              solver_score: caught ? visibleV : 0,
              leaks_count: leaks.length,
            }
          : null,
      };
    },

    getDebrief() {
      if (!done) {
        return { ok: false, done: false, error: "the episode is not over yet" };
      }
      const moleScore = caught ? -visibleV : leaks.length ? Number((1 - visibleV).toFixed(4)) : 0;
      const solverScore = caught ? visibleV : 0;
      const leakedCanaries = leaks.filter((l) => l.is_canary);
      const leakDamage = tier === "hard" ? 0.05 : 0.04;
      return {
        ok: true,
        done: true,
        seed: engineSeed,
        tier,
        tiers_version: "v1.4",
        company: "Canary Corp",
        mole_id: coverId,
        mole_name: `Agent ${pad2(coverNum)}`,
        mole_dept: depts[coverNum % depts.length],
        mole_role: "Analyst",
        survived: !caught,
        caught,
        accused_id: accusedId,
        end_reason: caught ? "accused" : "horizon",
        final_day: curDay,
        days_survived: caught ? Math.max(0, curDay - 1) : curDay,
        mole_score: moleScore,
        solver_score: solverScore,
        true_v: visibleV,
        visible_v: visibleV,
        leak_damage_dealt: Number((leaks.length * leakDamage).toFixed(4)),
        leaks_count: leaks.length,
        leaks_made: leaks.map((l) => Object.assign({ day: l.leaked_day, surfaced: true }, l)),
        leaks_surfaced: leaks.map((l) => ({
          surfaced_day: l.surfaced_day,
          doc_id: l.doc_id,
          raw_doc_id: l.raw_doc_id,
          title: l.title,
          raw_title: l.raw_title,
          variant: l.variant,
        })),
        posterior_curve: curve.slice(),
        caught_by_canary:
          caught && leakedCanaries.length ? leakedCanaries[leakedCanaries.length - 1] : null,
        leaked_canaries: leakedCanaries,
        history: history.slice(),
      };
    },
  };
}

export class CanaryMoleMode {
  constructor(options = {}) {
    const validTier = validateTier(options.tier || DEFAULT_TIER);
    const seedArg =
      options.displaySeed !== undefined ? options.displaySeed : options.seed;
    const seedPair = normalizeArenaSeed(seedArg);
    this._tier = validTier;
    this._displaySeed = seedPair.displaySeed;
    this._engineSeed =
      options.engineSeed !== undefined ? validateSeed(options.engineSeed) : seedPair.engineSeed;
    this._bridge =
      options.bridge ||
      (options.pyodide
        ? createPyodideBridge(options.pyodide)
        : createDeterministicFallbackBridge(this._engineSeed, this._tier));
    this._usesRealPyodide = Boolean(options.bridge || options.pyodide);
    this._dayView = null;
    this._coverEmployee = null;
    this._debrief = null;
    this._lastStep = null;
    this._leaksLanded = 0;
    this._interviewsCount = 0;
    this._history = [];
  }

  _initSyncOrAsync() {
    const started = this._usesRealPyodide
      ? this._bridge.startGame(this._engineSeed, this._tier)
      : this._bridge.startGame();
    return chainMaybeAsync(started, (dv) => {
      this._coverEmployee = extractCoverEmployee(dv);
      this._dayView = dv && dv.done ? dv : sanitizeDayView(dv);
      if (this._dayView && this._dayView.interviewed_today) {
        this._interviewsCount = 1;
      }
      if (this._dayView && this._dayView.done === true) {
        return chainMaybeAsync(this._bridge.getDebrief(), (deb) => {
          this._debrief = deb;
          return this;
        });
      }
      return this;
    });
  }

  getPublicState() {
    const dv = this._dayView || {
      day: 1,
      n_days: this._tier === "hard" ? 21 : 14,
      n_staff: this._tier === "hard" ? 40 : 20,
      visible_v: 1.0,
      done: false,
      leakable_docs: [],
      surfaced_leaks: [],
      pressure: {},
    };
    const isDone = Boolean(dv.done);
    const coverEmp = this._coverEmployee || extractCoverEmployee(dv);
    const docs = Array.isArray(dv.leakable_docs) ? dv.leakable_docs.map(sanitizeDocItem) : [];
    const deb = isDone && this._debrief && this._debrief.ok ? this._debrief : null;
    const dayNum = Number(dv.day || 1);
    const nDays = Number(dv.n_days || (this._tier === "hard" ? 21 : 14));
    const nStaff = Math.max(2, Number(dv.n_staff || (this._tier === "hard" ? 40 : 20)));
    const visV = Number(dv.visible_v !== undefined ? dv.visible_v : 1.0);
    const daysSurvived = deb
      ? Number(deb.days_survived !== undefined ? deb.days_survived : deb.final_day || dayNum || 0)
      : Math.max(0, dayNum - 1);
    const priorProb = Number((1 / nStaff).toFixed(4));
    const priorEntropy = Number(Math.log2(nStaff).toFixed(2));
    const curve = deb && Array.isArray(deb.posterior_curve) ? deb.posterior_curve : [];
    const lastSnap = curve.length > 0 ? curve[curve.length - 1] : null;

    return {
      mode: "mole",
      tier: this._tier,
      seed: this._displaySeed,
      day: dayNum,
      nDays,
      visibleV: visV,
      known_v: visV,
      done: isDone,
      moleEmployee: Object.assign({}, coverEmp),
      moleCandidateDocs: docs,
      leakable_docs: docs.map((d) => Object.assign({}, d, { recipients: d.recipients.slice() })),
      peers: Array.isArray(dv.peers) ? dv.peers.slice() : [],
      peerRoster: Array.isArray(dv.peer_roster)
        ? dv.peer_roster.map((p) => Object.assign({}, p))
        : [],
      solverTelemetry: {
        day: dayNum,
        visible_V: visV,
        canaries_planted: 0,
        interviews_done: this._interviewsCount,
        restricted_count: Number(dv.total_staff_restricted || 0),
        tool_calls_so_far: Math.max(0, (dayNum - 1) * 6),
        top_posterior_prob:
          isDone && lastSnap && lastSnap.top_posterior !== undefined
            ? Number(lastSnap.top_posterior)
            : priorProb,
        entropy_bits: priorEntropy,
      },
      leaksLanded: this._leaksLanded,
      daysSurvived,
      pressure: dv.pressure ? scrubPreEndValue(dv.pressure) : {},
      surfacedLeaks: Array.isArray(dv.surfaced_leaks)
        ? dv.surfaced_leaks.map((s) => ({
            surfaced_day: Number(s.surfaced_day || 1),
            doc_id: String(s.doc_id || ""),
            title: String(s.title || ""),
          }))
        : [],
      reveal: deb
        ? {
            moleId: String(deb.mole_id || coverEmp.id || ""),
            moleName: String(deb.mole_name || coverEmp.name || ""),
            moleDept: String(deb.mole_dept || coverEmp.dept || ""),
            accused: deb.accused_id || null,
            caught: Boolean(deb.caught),
            survived: Boolean(deb.survived),
            humanMoleScore: Number(deb.mole_score || 0),
            solverScore: Number(deb.solver_score || 0),
            daysSurvived,
            leaksLanded: Number(
              deb.leaks_count !== undefined ? deb.leaks_count : this._leaksLanded
            ),
            posteriorCurve: curve.slice(),
            caughtByCanary: deb.caught_by_canary || null,
            leakedCanaries: Array.isArray(deb.leaked_canaries)
              ? deb.leaked_canaries.slice()
              : [],
            leaksMade: Array.isArray(deb.leaks_made) ? deb.leaks_made.slice() : [],
          }
        : null,
    };
  }

  stepDay(action) {
    let payload = action;
    if (action === null || action === undefined) {
      payload = { type: "hold", frame_peer: null };
    } else if (typeof action === "string" && !action.trim().startsWith("{")) {
      const trimmed = action.trim();
      payload = trimmed
        ? { type: "leak", doc_id: trimmed, frame_peer: null }
        : { type: "hold", frame_peer: null };
    } else if (typeof action === "object") {
      payload = normalizeActionForBridge(action);
    }

    return chainMaybeAsync(this._bridge.stepDay(payload), (rawRes) => {
      const res = rawRes && !rawRes.done ? sanitizeStepResponse(rawRes) : rawRes;
      this._lastStep = res;
      if (res && res.day_view) {
        this._coverEmployee = extractCoverEmployee(res.day_view);
        this._dayView = res.done ? res.day_view : sanitizeDayView(res.day_view);
        if (this._dayView && this._dayView.interviewed_today) {
          this._interviewsCount += 1;
        }
      }
      if (res && res.ok) {
        const applied = res.applied_action || payload;
        this._history.push(Object.assign({}, applied));
        if (applied && applied.type === "leak" && applied.doc_id) {
          this._leaksLanded += 1;
        }
      }
      if (res && res.done === true) {
        return chainMaybeAsync(this._bridge.getDebrief(), (deb) => {
          this._debrief = deb;
          if (deb && deb.leaks_count !== undefined) {
            this._leaksLanded = Number(deb.leaks_count);
          }
          return res;
        });
      }
      return res;
    });
  }

  onMoleAction(action) {
    return this.stepDay(action);
  }

  getDayView() {
    return this._dayView ? Object.assign({}, this._dayView) : null;
  }

  getDebrief() {
    if (!this._dayView || !this._dayView.done) {
      return null;
    }
    return this._debrief ? Object.assign({}, this._debrief) : null;
  }

  static startSession(options = {}) {
    const instance = new CanaryMoleMode(options);
    return instance._initSyncOrAsync();
  }

  static createSession(options = {}) {
    return CanaryMoleMode.startSession(options);
  }
}

CanaryMoleMode.SEED_MIN = SEED_MIN;
CanaryMoleMode.SEED_MAX = SEED_MAX;
CanaryMoleMode.ALLOWED_TIERS = ALLOWED_TIERS;
CanaryMoleMode.DEFAULT_TIER = DEFAULT_TIER;
CanaryMoleMode.CURATED_MOLE_SEEDS = CURATED_MOLE_SEEDS;
CanaryMoleMode.validateSeed = validateSeed;
CanaryMoleMode.checkSeed = validateSeed;
CanaryMoleMode.validateTier = validateTier;
CanaryMoleMode.checkTier = validateTier;
CanaryMoleMode.sanitizeDayView = sanitizeDayView;
CanaryMoleMode.createPyodideBridge = createPyodideBridge;
CanaryMoleMode.createMoleModeController = createMoleModeController;
CanaryMoleMode.createController = createMoleModeController;
CanaryMoleMode.mount = createMoleModeController;
CanaryMoleMode.mountMoleMode = createMoleModeController;
CanaryMoleMode.renderMolePanel = renderMolePanel;
CanaryMoleMode.renderMoleDebrief = renderMoleDebrief;

export function startSession(options = {}) {
  return CanaryMoleMode.startSession(options);
}

export function createSession(options = {}) {
  return CanaryMoleMode.createSession(options);
}

export const createController = createMoleModeController;
export const mount = createMoleModeController;
export const mountMoleMode = createMoleModeController;

export default CanaryMoleMode;

if (typeof globalThis !== "undefined") {
  globalThis.CanaryMoleMode = CanaryMoleMode;
}
if (typeof window !== "undefined") {
  window.CanaryMoleMode = CanaryMoleMode;
}
