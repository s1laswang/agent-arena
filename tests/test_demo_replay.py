from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_demo_replay as B

OWNED_FILES: tuple[str, ...] = (
    "scripts/build_demo_replay.py",
    "docs/demo/replay.html",
    "tests/test_demo_replay.py",
)


def _extract_embedded_payload(html: str) -> dict:
    m = re.search(
        r'<script id="canary-replay-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert m is not None
    return json.loads(m.group(1))


def _find_node_binary() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    candidate = Path("/home/silas/tools/node/bin/node")
    if candidate.is_file():
        return str(candidate)
    return None


def test_owned_files_exist_ascii_no_comments_no_em_dashes():
    for rel in OWNED_FILES:
        fp = ROOT / rel
        assert fp.is_file(), f"missing owned file: {rel}"
        text = fp.read_text(encoding="utf-8")
        assert all(ord(ch) < 128 for ch in text), f"non-ASCII character in {rel}"
        assert chr(8212) not in text, f"em dash in {rel}"
        assert chr(8211) not in text, f"en dash in {rel}"
        if rel.endswith(".py"):
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
            comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
            assert comments == [], f"code comments found in {rel}: {comments[:3]}"


def test_replay_html_offline_size_and_xss_hygiene():
    html_path = ROOT / "docs/demo/replay.html"
    raw_bytes = html_path.read_bytes()
    assert 40_000 < len(raw_bytes) < 2_000_000

    html = raw_bytes.decode("utf-8")
    errs = B.validate_html_hygiene(html)
    assert errs == []

    assert re.search(r"<script\b[^>]*\bsrc\s*=", html, flags=re.IGNORECASE) is None
    assert re.search(r"<link\b[^>]*\bhref\s*=", html, flags=re.IGNORECASE) is None
    assert "@import" not in html.lower()
    for banned in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "http:",
        "https:",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "<!--",
        "/*",
        "//",
    ):
        assert banned not in html


def test_deterministic_build_and_cli_check(tmp_path):
    assert B.main(["--root", str(ROOT), "--check"]) == 0
    rebuilt_path = tmp_path / "replay.html"
    assert B.main(["--root", str(ROOT), "--out", str(rebuilt_path)]) == 0
    committed_bytes = (ROOT / "docs/demo/replay.html").read_bytes()
    assert rebuilt_path.read_bytes() == committed_bytes


def test_locked_gap_headline_only():
    html = (ROOT / "docs/demo/replay.html").read_text(encoding="utf-8")
    payload = _extract_embedded_payload(html)
    hl = payload["headline"]

    assert hl["source"] == "docs/reports/gap.md"
    assert hl["tiers_version"] == "v1.4"
    assert hl["n"] == 30
    assert hl["seeds"] == "0-29"
    assert hl["hard_opencode"]["luck_adjusted"] == "72% [52%, 91%]"
    assert hl["hard_opencode"]["raw"] == "65% [24%, 98%]"
    assert hl["medium_opencode"]["luck_adjusted"] == "101% [85%, 119%]"
    assert hl["medium_opencode"]["raw"] == "111% [99%, 127%]"
    assert hl["hard_inprocess"]["luck_adjusted"] == "84% [65%, 106%]"
    assert hl["hard_inprocess"]["raw"] == "95% [62%, 140%]"

    assert "72% [52%, 91%]" in html
    assert "65% [24%, 98%]" in html
    assert "n=30" in html
    assert "60% [1, 103]" not in html


def test_seed6_caught_vs_inproc_fooled_forensics():
    html = (ROOT / "docs/demo/replay.html").read_text(encoding="utf-8")
    payload = _extract_embedded_payload(html)
    c6 = payload["cases"]["6"]

    assert c6["seed"] == 6
    assert c6["tier"] == "hard"
    assert c6["true_mole"] == "e34"
    assert c6["true_mole_profile"]["name"] == "Sofia Niemi"
    assert c6["decoy"] == "e20"
    assert c6["fooled_accused"] == "e18"
    assert c6["max_day"] == 15
    assert len(c6["employees"]) == 40

    runs = {r["key"]: r for r in c6["runs"]}
    assert list(runs.keys()) == ["opencode", "solver", "inproc"]

    oc = runs["opencode"]
    assert oc["agent"] == "opencode:google/gemini-4-carbon"
    assert oc["score"] == pytest.approx(0.73)
    assert oc["final_day"] == 6
    assert oc["tool_calls"] == 57
    assert oc["accused"] == "e34"
    assert oc["correct"] is True
    assert oc["canaries_planted_count"] == 7
    assert oc["interviews_count"] == 25
    assert oc["replay_verified"] is True
    assert oc["days"][-1]["p_mole"] > 0.99

    sp = runs["solver"]
    assert sp["agent"] == "solver"
    assert sp["score"] == pytest.approx(0.71)
    assert sp["final_day"] == 6
    assert sp["tool_calls"] == 52
    assert sp["accused"] == "e34"
    assert sp["correct"] is True
    assert sp["canaries_planted_count"] == 9
    assert sp["interviews_count"] == 0
    assert sp["replay_verified"] is True
    assert sp["days"][-1]["p_mole"] > 0.99

    ip = runs["inproc"]
    assert ip["agent"] == "gemini:gemini-4-carbon"
    assert ip["score"] == pytest.approx(-1.00)
    assert ip["final_day"] == 15
    assert ip["tool_calls"] == 151
    assert ip["accused"] == "e18"
    assert ip["correct"] is False
    assert ip["canaries_planted_count"] == 10
    assert ip["interviews_count"] == 85
    assert ip["replay_verified"] is True
    flips = [lk for lk in ip["leaks_surfaced"] if lk["is_noisy_flip"]]
    assert len(flips) == 1
    assert flips[0]["doc_id"] == "c4-2"
    assert flips[0]["surfaced_day"] == 7
    assert flips[0]["mole_variant"] == "Y"
    assert flips[0]["reported_variant"] == "Z"


def test_seed26_fooled_vs_solver_forensics():
    html = (ROOT / "docs/demo/replay.html").read_text(encoding="utf-8")
    payload = _extract_embedded_payload(html)
    c26 = payload["cases"]["26"]

    assert c26["seed"] == 26
    assert c26["tier"] == "hard"
    assert c26["true_mole"] == "e08"
    assert c26["true_mole_profile"]["name"] == "Nea Nieminen"
    assert c26["decoy"] == "e38"
    assert c26["fooled_accused"] == "e04"
    assert c26["fooled_accused_profile"]["name"] == "Lauri Laitinen"
    assert c26["max_day"] == 10
    assert c26["after_hours_d1_9"]["e04"] == 3
    assert len(c26["employees"]) == 40

    runs = {r["key"]: r for r in c26["runs"]}
    assert list(runs.keys()) == ["opencode", "solver"]

    oc = runs["opencode"]
    assert oc["agent"] == "opencode:google/gemini-4-carbon"
    assert oc["score"] == pytest.approx(-1.00)
    assert oc["final_day"] == 10
    assert oc["tool_calls"] == 91
    assert oc["accused"] == "e04"
    assert oc["correct"] is False
    assert oc["canaries_planted_count"] == 8
    assert oc["canaries_days_1_to_3"] == 0
    assert oc["interviews_count"] == 43
    assert oc["replay_verified"] is True
    assert "uniquely identified" in oc["rationale"].lower()

    d9 = next(d for d in oc["days"] if d["day"] == 9)
    d10 = next(d for d in oc["days"] if d["day"] == 10)
    assert d9["p_mole_2dp"] == pytest.approx(0.48)
    assert d10["p_mole_2dp"] == pytest.approx(0.03)
    assert d10["p_accused_final"] == pytest.approx(0.950444, abs=1e-3)

    flips = [lk for lk in oc["leaks_surfaced"] if lk["is_noisy_flip"]]
    assert len(flips) == 1
    assert flips[0]["doc_id"] == "c6-2"
    assert flips[0]["surfaced_day"] == 10
    assert flips[0]["mole_variant"] == "S3"
    assert flips[0]["reported_variant"] == "S1"

    sp = runs["solver"]
    assert sp["agent"] == "solver"
    assert sp["score"] == pytest.approx(0.69)
    assert sp["final_day"] == 7
    assert sp["tool_calls"] == 60
    assert sp["accused"] == "e08"
    assert sp["correct"] is True
    assert sp["canaries_planted_count"] == 11
    assert sp["canaries_days_1_to_3"] == 6
    assert sp["interviews_count"] == 0
    assert sp["replay_verified"] is True
    assert sp["days"][-1]["p_mole_2dp"] == pytest.approx(0.97)


def test_browser_dom_runtime_scrubber_and_xss_guard():
    node_bin = _find_node_binary()
    if node_bin is None:
        pytest.skip("node binary not installed on this machine")

    js_harness = """
const fs = require("fs");
const vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const jsonMatch = html.match(/<script id="canary-replay-data" type="application\\/json">([\\s\\S]*?)<\\/script>/);
if (!jsonMatch) throw new Error("Missing embedded JSON");
const scriptMatches = [...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)];
if (scriptMatches.length !== 1) throw new Error("Expected single inline script");

function makeEl(tag) {
  return {
    tagName: tag.toUpperCase(),
    className: "",
    style: {},
    attrs: {},
    children: [],
    listeners: {},
    _text: "",
    value: "",
    disabled: false,
    get firstChild() { return this.children[0] || null; },
    get textContent() {
      if (this.children.length === 0) return this._text;
      return this._text + this.children.map(c => c.textContent).join("");
    },
    set textContent(v) { this.children = []; this._text = String(v); },
    set innerHTML(_) { throw new Error("XSS innerHTML forbidden"); },
    set outerHTML(_) { throw new Error("XSS outerHTML forbidden"); },
    insertAdjacentHTML() { throw new Error("XSS insertAdjacentHTML forbidden"); },
    appendChild(child) {
      if (child.tagName === "FRAGMENT") {
        for (const c of child.children) this.children.push(c);
        child.children = [];
      } else {
        this.children.push(child);
      }
      return child;
    },
    removeChild(child) {
      const idx = this.children.indexOf(child);
      if (idx >= 0) this.children.splice(idx, 1);
    },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] || null; },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    getBoundingClientRect() { return { left: 0, width: 480, height: 150 }; },
    getContext() {
      return {
        setTransform() {}, clearRect() {}, fillRect() {}, beginPath() {},
        moveTo() {}, lineTo() {}, stroke() {}, fillText() {}, setLineDash() {},
        arc() {}, fill() {}
      };
    }
  };
}

const appRoot = makeEl("div");
const dataEl = makeEl("script");
dataEl.textContent = jsonMatch[1];
const winListeners = {};

const sandbox = {
  window: {
    devicePixelRatio: 2,
    matchMedia: () => ({ matches: false }),
    setInterval: () => 1,
    clearInterval: () => {},
    addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); }
  },
  document: {
    getElementById: (id) => id === "app" ? appRoot : (id === "canary-replay-data" ? dataEl : null),
    createElement: (tag) => makeEl(tag),
    createDocumentFragment: () => makeEl("fragment"),
    write: () => { throw new Error("XSS document.write forbidden"); }
  },
  fetch: () => { throw new Error("Network fetch forbidden"); },
  Number, String, Math, JSON
};

vm.runInNewContext(scriptMatches[0][1], sandbox);

const fireKey = (key) => {
  for (const fn of (winListeners.keydown || [])) {
    fn({ key, preventDefault() {}, target: { tagName: "BODY" } });
  }
};

const s6Text = appRoot.textContent;
if (!s6Text.includes("72% [52%, 91%]") || !s6Text.includes("65% [24%, 98%]")) throw new Error("Missing headline on Seed 6");
if (!s6Text.includes("+0.73") || !s6Text.includes("+0.71") || !s6Text.includes("-1.00")) throw new Error("Missing Seed 6 scores");
for (let i = 0; i < 15; i += 1) fireKey("ArrowRight");
for (let i = 0; i < 15; i += 1) fireKey("ArrowLeft");

fireKey("2");
const s26Text = appRoot.textContent;
if (!s26Text.includes("e08") || !s26Text.includes("e04") || !s26Text.includes("+0.69")) throw new Error("Missing Seed 26 facts");
if (!s26Text.includes("5% FLIP")) throw new Error("Missing 5% FLIP badge");
for (let i = 0; i < 10; i += 1) fireKey("ArrowLeft");
for (let i = 0; i < 10; i += 1) fireKey("ArrowRight");
"""
    proc = subprocess.run(
        [node_bin, "-e", js_harness, str(ROOT / "docs/demo/replay.html")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
