from __future__ import annotations

import ast
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
REVEAL_CARD_JS = DEMO_DIR / "reveal_card.js"
ANNOTATIONS_JS = DEMO_DIR / "annotations.js"
ANNOTATIONS_JSON = ROOT / "results" / "gemini" / "outthink_annotations.json"
PROTECTED_PATHS_TXT = ROOT / ".github" / "protected-paths.txt"

HASH_CHAR = chr(35)
SINGLE_QUOTE_ENTITY = "&" + HASH_CHAR + "39;"
UNICODE_DASH_CODEPOINTS = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
    0xFE58,
    0xFE63,
    0xFF0D,
)
UNICODE_DASHES = tuple(chr(cp) for cp in UNICODE_DASH_CODEPOINTS)
LINE_COMMENT_TOKEN = chr(47) + chr(47)
BLOCK_COMMENT_TOKEN = chr(47) + chr(42)


class _RevealHTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self._stack: list[tuple[str, dict[str, str | None], list[str]]] = []
        self.completed: list[tuple[str, dict[str, str | None], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        self.tags.append((tag, attr_map))
        self._stack.append((tag, attr_map, []))

    def handle_data(self, data: str) -> None:
        for entry in self._stack:
            entry[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self._stack) - 1, -1, -1):
            open_tag, attr_map, chunks = self._stack[idx]
            if open_tag == tag:
                self._stack.pop(idx)
                self.completed.append((open_tag, attr_map, "".join(chunks)))
                break


def _assert_no_unicode_dashes(text: str, label: str) -> None:
    for dash in UNICODE_DASHES:
        assert dash not in text, f"unicode dash U+{ord(dash):04X} found in {label}"


def _resolve_js_runtime() -> tuple[list[str], dict[str, str]] | None:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env

    opencode_candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ]
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env

    return None


def _run_js(script_body: str, payload: dict | list | None = None) -> dict:
    resolved = _resolve_js_runtime()
    if resolved is None:
        pytest.skip("no JavaScript runtime available on host")
    cmd_prefix, base_env = resolved
    env = dict(base_env)
    env["OUTTHINK_REVEAL_CARD_PATH"] = str(REVEAL_CARD_JS)
    env["OUTTHINK_ANNOTATIONS_JS_PATH"] = str(ANNOTATIONS_JS)
    env["OUTTHINK_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        "const PAYLOAD = JSON.parse(process.env.OUTTHINK_PAYLOAD);\n"
        "const result = (() => {\n"
        + script_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(result));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS execution failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_reveal_card_js_and_test_file_hygiene() -> None:
    assert REVEAL_CARD_JS.is_file()
    js_src = REVEAL_CARD_JS.read_text(encoding="utf-8")
    assert len(js_src) > 500
    _assert_no_unicode_dashes(js_src, "reveal_card.js")
    assert LINE_COMMENT_TOKEN not in js_src
    assert BLOCK_COMMENT_TOKEN not in js_src
    assert "http:" not in js_src.lower()
    assert "https:" not in js_src.lower()
    assert "cdn." not in js_src.lower()

    assert "OutthinkRevealCard" in js_src
    assert "OutThinkRevealCard" in js_src
    assert "module.exports" in js_src
    assert "OUTTHINK_ANNOTATIONS" in js_src
    assert "getOutthinkAnnotation" in js_src
    assert "getOutthinkFailureMode" in js_src
    assert "OUTTHINK_FAILURE_MODES" in js_src
    assert "levelComparisons" in js_src
    assert "toFixed(4)" in js_src
    assert "<details" in js_src
    assert "<summary" in js_src
    for level in ("minimal", "low", "medium", "high"):
        assert f'"{level}"' in js_src
    for tag in (
        "premature_accusation",
        "uninformative_canary",
        "ignored_delay",
        "over_restriction",
    ):
        assert f'"{tag}"' in js_src
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", SINGLE_QUOTE_ENTITY):
        assert entity in js_src

    py_path = Path(__file__).resolve()
    py_src = py_path.read_text(encoding="utf-8")
    _assert_no_unicode_dashes(py_src, "test_outthink_reveal_card.py")
    assert HASH_CHAR not in py_src
    comment_tokens = [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(py_src).readline)
        if tok.type == tokenize.COMMENT
    ]
    assert comment_tokens == []

    tree = ast.parse(py_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    if PROTECTED_PATHS_TXT.is_file():
        prefixes = [
            line.strip()
            for line in PROTECTED_PATHS_TXT.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith(HASH_CHAR)
        ]
        owned_rel = ("demo/out-think-gemini/reveal_card.js", "tests/test_outthink_reveal_card.py")
        for rel in owned_rel:
            for pref in prefixes:
                if pref.endswith("/"):
                    assert not rel.startswith(pref)
                else:
                    assert rel != pref


def test_html_escaping_blocks_xss_across_all_fields() -> None:
    xss_vector = "<script>alert(\"xss\" & '1')</script><img src=x onerror='boom()'>"
    quote_vector = "Thought: p(e05) > 0.60 & p(e02) < 0.15 \"confirmed\" via 'c4' <raw>"
    source_vector = "results/gemini/evil_<tag>&\"quote\"_'single'.json"

    out = _run_js(
        """
        globalThis.window = globalThis;
        window.OUTTHINK_ANNOTATIONS = {};
        const key = PAYLOAD.model + "/minimal/" + PAYLOAD.tier + "/" + PAYLOAD.seed;
        window.OUTTHINK_ANNOTATIONS[key] = {
          accused: PAYLOAD.xss,
          correct: false,
          score: -1,
          cost_usd: 0.01234,
          tokens: { thinking: 42 },
          primary_failure_tag: PAYLOAD.xss,
          quotes: [
            {
              quote: PAYLOAD.quote,
              source_file: PAYLOAD.source,
              source_kind: "transcript",
              note: PAYLOAD.xss
            }
          ]
        };
        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        return {
          escapedDirect: Reveal.escapeHtml(PAYLOAD.xss),
          html: Reveal.renderHTML(PAYLOAD.tier, PAYLOAD.seed, PAYLOAD.model, PAYLOAD.xss, {
            trueMole: PAYLOAD.xss
          })
        };
        """,
        {
            "tier": "hard",
            "seed": "7",
            "model": "gemini-3.5-flash",
            "xss": xss_vector,
            "quote": quote_vector,
            "source": source_vector,
        },
    )

    escaped_direct = out["escapedDirect"]
    assert "<script>" not in escaped_direct
    assert "<img" not in escaped_direct
    assert "&lt;script&gt;" in escaped_direct
    assert "&amp;" in escaped_direct
    assert "&quot;xss&quot;" in escaped_direct
    assert SINGLE_QUOTE_ENTITY + "1" + SINGLE_QUOTE_ENTITY in escaped_direct

    html = out["html"]
    _assert_no_unicode_dashes(html, "rendered XSS test HTML")
    assert "<script" not in html.lower()
    assert "<img" not in html.lower()
    assert "onerror='boom()'" not in html.lower()

    inspector = _RevealHTMLInspector()
    inspector.feed(html)
    tag_names = {t for t, _ in inspector.tags}
    assert "script" not in tag_names
    assert "img" not in tag_names
    for _, attrs in inspector.tags:
        for attr_name in attrs:
            assert not attr_name.lower().startswith("on")

    blockquotes = [txt for tag, _, txt in inspector.completed if tag == "blockquote"]
    assert quote_vector in blockquotes

    cites = [
        attrs.get("data-source-file")
        for tag, attrs, _ in inspector.completed
        if tag == "cite"
    ]
    assert source_vector in cites


def test_ladder_table_cost_tokens_tags_and_verbatim_quotes() -> None:
    verbatim_quotes = {
        "minimal": "Fast hunch: e02 accessed d1-2 late at night; accusing immediately.",
        "low": "Planted canary c2 with all 11 suspects in variant A1 -> zero split.",
        "medium": "Mole e05 was already at 0.99 on day 5, waited 4 extra days unnecessarily.",
        "high": "Cross-referenced c1..c6: e05 uniquely received every leaked variant (p=0.984).",
    }
    sources = {
        "minimal": "results/gemini/v2/atlas.json",
        "low": "results/gemini/ladder_episodes.jsonl.gz",
        "medium": "data/runs/committed/v1.4/inproc-gemini-3.5-flash/hard/transcripts/12.json",
        "high": "results/gemini/replay-ladder-showcase/ab/abcdef.json.gz",
    }

    annotations = {
        "gemini-3.5-flash/minimal/hard/12": {
            "accused": "e02",
            "correct": False,
            "score": -1.0,
            "solver_score": 0.78,
            "cost_usd": 0.06488565,
            "tokens": {"thinking": 0, "thinking_is_estimate": False},
            "primary_failure_tag": "premature_accusation",
            "quotes": [
                {
                    "quote": verbatim_quotes["minimal"],
                    "source_file": sources["minimal"],
                    "source_kind": "atlas_v2",
                    "t": 14,
                    "day": 3,
                }
            ],
        },
        "gemini-3.5-flash/low/hard/12": {
            "accused": "e09",
            "correct": False,
            "score": -1.0,
            "cost_usd": 0.12,
            "tokens": {"thinking": 640, "thinking_is_estimate": False},
            "primary_failure_tag": "uninformative_canary",
            "highlighted_tags": {
                "over_restriction": {"present": True, "count": 1}
            },
            "quotes": [
                {
                    "quote": verbatim_quotes["low"],
                    "source_file": sources["low"],
                    "source_kind": "episode_step",
                    "t": 31,
                    "day": 5,
                }
            ],
        },
        "gemini-3.5-flash/medium/hard/12": {
            "accused": "e05",
            "correct": True,
            "score": 0.54,
            "cost_usd": 0.0,
            "tokens": {"thinking": 12450, "thinking_is_estimate": False},
            "primary_failure_tag": "ignored_delay",
            "quotes": [
                {
                    "quote": verbatim_quotes["medium"],
                    "source_file": sources["medium"],
                    "source_kind": "transcript",
                    "t": 88,
                    "day": 9,
                }
            ],
        },
        "gemini-3.5-flash/high/hard/12": {
            "accused": "e05",
            "correct": True,
            "score": 0.82,
            "cost_usd": 1.7918068,
            "tokens": {"thinking": 48302, "thinking_is_estimate": True},
            "primary_failure_tag": "over_restriction",
            "quotes": [
                {
                    "quote": "{\"tool\":\"accuse\"}",
                    "source_file": "results/gemini/ladder_episodes.jsonl.gz",
                    "source_kind": "episode_step",
                    "t": 52,
                },
                {
                    "quote": verbatim_quotes["high"],
                    "source_file": sources["high"],
                    "source_kind": "replay_showcase",
                    "t": 52,
                },
            ],
        },
    }

    out = _run_js(
        """
        globalThis.window = globalThis;
        window.OUTTHINK_ANNOTATIONS = PAYLOAD.annotations;
        delete window.getOutthinkAnnotation;
        delete window.getOutthinkFailureMode;
        delete window.OUTTHINK_FAILURE_MODES;
        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const rightHtml = Reveal.render("hard", 12, "gemini:gemini-3.5-flash", "e05");
        const wrongHtml = Reveal.render("hard", 12, "gemini-3.5-flash", {
          action: "accuse",
          suspectId: "e02",
          score: -1.0,
          verdictLabel: "FALSE ACCUSATION (-1.00)"
        });
        const holdHtml = Reveal.render("hard", 12, "gemini-3.5-flash", {
          action: "hold_fire",
          score: 0.45
        });
        const vm = Reveal.buildModel("hard", 12, "gemini-3.5-flash", "e05");
        return {
          hasGlobal: Boolean(window.OutthinkRevealCard),
          rightHtml,
          wrongHtml,
          holdHtml,
          vm
        };
        """,
        {"annotations": annotations},
    )

    assert out["hasGlobal"] is True
    vm = out["vm"]
    assert vm["trueMole"] == "e05"
    assert vm["solverScore"] == pytest.approx(0.78)
    assert [r["level"] for r in vm["rows"]] == ["minimal", "low", "medium", "high"]
    assert vm["rows"][3]["quotes"][0]["quote"] == verbatim_quotes["high"]

    html = out["rightHtml"]
    _assert_no_unicode_dashes(html, "ladder HTML")
    assert "Thinking Ladder Reveal Panel" in html
    assert "Accused e05" in html
    assert 'data-true-mole="e05"' in html

    for expected_cost in ("$0.0649", "$0.1200", "$0.0000", "$1.7918"):
        assert expected_cost in html

    assert 'data-thinking-tokens="0"' in html
    assert 'data-thinking-tokens="640"' in html
    assert 'data-thinking-tokens="12450"' in html
    assert "12,450" in html
    assert 'data-thinking-tokens="48302"' in html
    assert "48,302 (est.)" in html

    for tag in (
        "premature_accusation",
        "uninformative_canary",
        "ignored_delay",
        "over_restriction",
    ):
        assert f'data-failure-tag="{tag}"' in html

    inspector = _RevealHTMLInspector()
    inspector.feed(html)

    details_count = sum(1 for t, _ in inspector.tags if t == "details")
    summary_count = sum(1 for t, _ in inspector.tags if t == "summary")
    assert details_count == 4
    assert summary_count == 4

    blockquotes = [txt for t, _, txt in inspector.completed if t == "blockquote"]
    for quote_text in verbatim_quotes.values():
        assert quote_text in blockquotes

    cite_files = {
        attrs.get("data-source-file")
        for t, attrs, _ in inspector.completed
        if t == "cite"
    }
    for src_file in sources.values():
        assert src_file in cite_files

    outcomes = [
        (attrs.get("data-outcome"), txt)
        for t, attrs, txt in inspector.completed
        if t == "span" and "data-outcome" in attrs
    ]
    assert outcomes[0] == ("right", "RIGHT")
    assert outcomes[1:] == [
        ("wrong", "WRONG"),
        ("wrong", "WRONG"),
        ("right", "RIGHT"),
        ("right", "RIGHT"),
    ]

    wrong_html = out["wrongHtml"]
    assert "Accused e02" in wrong_html
    assert "FALSE ACCUSATION (-1.00)" in wrong_html

    hold_html = out["holdHtml"]
    assert "Hold Fire" in hold_html
    assert "HOLD FIRE" in hold_html


def test_get_outthink_annotation_hook_and_dom_mounting() -> None:
    out = _run_js(
        """
        globalThis.window = globalThis;
        delete window.OUTTHINK_ANNOTATIONS;
        delete window.getOutthinkFailureMode;
        delete window.OUTTHINK_FAILURE_MODES;
        const calls = [];
        window.getOutthinkAnnotation = function (model, level, tier, seed) {
          calls.push([model, level, tier, seed]);
          if (level === "low") {
            return {
              accused: "e07",
              correct: false,
              score: -1.0,
              cost_usd: 0.25,
              thinking_tokens: 512,
              primary_failure_tag: "premature_accusation",
              verbatim_quote: "Accused e07 on noisy log correlation.",
              source_file: "results/gemini/custom_low.json"
            };
          }
          if (level === "high") {
            return {
              accused: "e03",
              correct: true,
              score: 0.91,
              cost_usd: 0.87519,
              thinking_tokens: 9100,
              primary_failure_tag: null,
              verbatim_quote: "Canary c3 isolated e03 uniquely.",
              source_file: "results/gemini/custom_high.json"
            };
          }
          return null;
        };

        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const createdEls = [];
        const mockDoc = {
          createElement: function (tag) {
            const attrs = {};
            const el = {
              nodeType: 1,
              tagName: String(tag).toUpperCase(),
              className: "",
              innerHTML: "",
              attrs: attrs,
              setAttribute: function (k, v) { attrs[k] = String(v); }
            };
            createdEls.push(el);
            return el;
          }
        };
        const container = { nodeType: 1, innerHTML: "" };
        const domEl = Reveal.renderDOM({
          tier: "medium",
          seed: 4,
          model: "gemini-4-carbon",
          judgeChoice: "e03",
          document: mockDoc,
          container: container
        });
        const headlessEl = Reveal.renderDOM("medium", 4, "gemini-4-carbon", "e03");
        const mountTarget = { innerHTML: "" };
        Reveal.mount(mountTarget, "medium", 4, "gemini-4-carbon", "e03");

        return {
          calls: calls.slice(0, 4),
          domTag: domEl.tagName,
          domAttrs: domEl.attrs,
          domInnerLen: domEl.innerHTML.length,
          containerLen: container.innerHTML.length,
          headlessOuter: headlessEl.outerHTML,
          mountedHtml: mountTarget.innerHTML
        };
        """
    )

    assert out["calls"] == [
        ["gemini-4-carbon", "minimal", "medium", "4"],
        ["gemini-4-carbon", "low", "medium", "4"],
        ["gemini-4-carbon", "medium", "medium", "4"],
        ["gemini-4-carbon", "high", "medium", "4"],
    ]
    assert out["domTag"] == "SECTION"
    assert out["domAttrs"] == {
        "data-model": "gemini-4-carbon",
        "data-tier": "medium",
        "data-seed": "4",
    }
    assert out["domInnerLen"] > 200
    assert out["containerLen"] > 200
    assert out["headlessOuter"] == out["mountedHtml"]
    assert "$0.2500" in out["mountedHtml"]
    assert "$0.8752" in out["mountedHtml"]
    assert 'data-level="minimal" data-available="false"' in out["mountedHtml"]
    assert 'data-level="high" data-available="true"' in out["mountedHtml"]
    assert "Canary c3 isolated e03 uniquely." in out["mountedHtml"]
    assert "results/gemini/custom_high.json" in out["mountedHtml"]


def test_engine_reveal_state_standalone_and_graceful_degradation() -> None:
    em_dash = chr(0x2014)
    eval_res = {
        "caseId": "medium-8",
        "action": "hold_fire",
        "suspectId": None,
        "correct": True,
        "optimal": True,
        "score": 0.88,
        "verdictLabel": "OPTIMAL HOLD FIRE",
        "explanation": f"Held fire at 34.8% {em_dash} below 61.7% break-even.",
        "trueMole": "e02",
        "solver": {
            "posterior": {"e02": 0.3096, "e09": 0.3419, "e17": 0.3485},
            "top_suspect": "e17",
            "top_prob": 0.3485,
            "break_even_prob": 0.6173,
            "ev_accuse_top": -0.4355,
            "ev_hold_fire": 0.88,
            "recommended_call": "hold_fire",
            "final_accused": "e02",
            "final_day": 5,
            "final_score": 0.88,
            "correct": True,
        },
        "levelComparisons": [
            {
                "key": "minimal",
                "model": "gemini-3.5-flash",
                "thinking_level": "minimal",
                "call_at_t": "accuse",
                "accused": "e02",
                "accused_day": 3,
                "end_reason": "accused",
                "correct": True,
                "score": 0.9,
                "cost_usd": 0.043159,
                "thinking_tokens": 0,
                "run_id": "ladder:ladder-v14:gemini-3.5-flash/minimal/medium/8",
                "failure_tag": None,
                "analyst_quote": "Isolated e02 early on day 3.",
            },
            {
                "key": "low",
                "model": "gemini-3.5-flash",
                "thinking_level": "low",
                "call_at_t": "accuse",
                "accused": "e09",
                "accused_day": 14,
                "end_reason": "accused",
                "correct": False,
                "score": -1.0,
                "cost_usd": 0.488473,
                "thinking_tokens": 11325,
                "run_id": "ladder:ladder-v14:gemini-3.5-flash/low/medium/8",
                "failure_tag": "premature_accusation",
                "analyst_quote": "Gambled on e09 below break-even certainty.",
                "regret_total": 1.88,
            },
            {
                "key": "medium",
                "model": "gemini-3.5-flash",
                "thinking_level": "medium",
                "call_at_t": "accuse",
                "accused": "e02",
                "accused_day": 3,
                "end_reason": "accused",
                "correct": True,
                "score": 0.9,
                "cost_usd": 0.121611,
                "thinking_tokens": 11235,
                "run_id": "ladder:ladder-v14:gemini-3.5-flash/medium/medium/8",
                "failure_tag": None,
                "analyst_quote": "Pinned e02 on day 3.",
            },
            {
                "key": "high",
                "model": "gemini-3.5-flash",
                "thinking_level": "high",
                "call_at_t": "accuse",
                "accused": "e02",
                "accused_day": 3,
                "end_reason": "accused",
                "correct": True,
                "score": 0.9,
                "cost_usd": 0.16251,
                "thinking_tokens": 12615,
                "run_id": "ladder:ladder-v14:gemini-3.5-flash/high/medium/8",
                "failure_tag": None,
                "analyst_quote": "Confirmed e02 via canary overlap.",
            },
        ],
    }
    case_obj = {
        "id": "medium-8",
        "title": f"Sales Leak Case {em_dash} Seed 8",
        "tier": "medium",
        "seed": 8,
        "decision_day": 14,
        "decision_step": 82,
        "value_at_decision": 0.62,
        "true_mole": "e02",
        "suspects": [{"id": "e02", "name": "Nea"}],
        "thinking_levels": eval_res["levelComparisons"],
        "cross_model_carbon": [
            {
                "model": "gemini-4-carbon",
                "thinking_level": "low",
                "accused": "e02",
                "accused_day": 4,
                "cost_usd": 0.138997,
                "thinking_tokens": 0,
                "score": 0.85,
                "correct": True,
            },
            {
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "accused": "e02",
                "accused_day": 4,
                "cost_usd": 0.502651,
                "thinking_tokens": 23083,
                "score": 0.85,
                "correct": True,
            },
        ],
        "ladder_matrix": {
            "gemini-4-carbon": {
                "low": {
                    "score": 0.85,
                    "correct": True,
                    "accused": "e02",
                    "final_day": 4,
                    "thinking_tokens": 0,
                    "cost_usd": 0.138997,
                },
                "high": {
                    "score": 0.85,
                    "correct": True,
                    "accused": "e02",
                    "final_day": 4,
                    "thinking_tokens": 23083,
                    "cost_usd": 0.502651,
                },
            }
        },
    }

    out = _run_js(
        """
        globalThis.window = globalThis;
        delete window.getOutthinkAnnotation;
        delete window.OUTTHINK_ANNOTATIONS;
        delete window.getOutthinkFailureMode;
        delete window.OUTTHINK_FAILURE_MODES;
        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);

        const standaloneVm = Reveal.buildModel(PAYLOAD.evalRes);
        const standaloneHtml = Reveal.render(PAYLOAD.evalRes);
        const pairedHtml = Reveal.render(PAYLOAD.evalRes, PAYLOAD.caseObj, {
          focusedPodLevel: "low"
        });
        const caseFirstHtml = Reveal.render(PAYLOAD.caseObj, PAYLOAD.evalRes);
        const mountContainer = { nodeType: 1, innerHTML: "" };
        Reveal.render(mountContainer, PAYLOAD.evalRes, PAYLOAD.caseObj);
        const carbonVm = Reveal.buildModel(PAYLOAD.evalRes, PAYLOAD.caseObj, {
          model: "gemini-4-carbon"
        });

        window.getOutthinkAnnotation = function () {
          throw new Error("broken global annotation hook");
        };
        window.getOutthinkFailureMode = function () {
          throw new Error("broken global failure mode hook");
        };
        const resilientHtml = Reveal.render(PAYLOAD.evalRes, PAYLOAD.caseObj);

        return {
          standaloneVm,
          standaloneHtml,
          pairedHtml,
          caseFirstHtml,
          mountedHtml: mountContainer.innerHTML,
          carbonVm,
          resilientHtml
        };
        """,
        {"evalRes": eval_res, "caseObj": case_obj},
    )

    vm = out["standaloneVm"]
    assert vm["tier"] == "medium"
    assert vm["seed"] == "8"
    assert vm["model"] == "gemini-3.5-flash"
    assert vm["trueMole"] == "e02"
    assert vm["solverScore"] == pytest.approx(0.88)
    assert vm["judge"]["action"] == "hold_fire"
    assert vm["judge"]["optimal"] is True
    assert vm["judge"]["verdictLabel"] == "OPTIMAL HOLD FIRE"
    assert vm["rows"][1]["primaryFailureTag"] == "premature_accusation"
    assert vm["rows"][1]["failureMode"]["decision"] == "commit_timing"
    assert vm["rows"][1]["failureMode"]["enriched"] is False
    assert vm["rows"][1]["regretTotal"] == pytest.approx(1.88)

    for label, html_doc in (
        ("standaloneHtml", out["standaloneHtml"]),
        ("pairedHtml", out["pairedHtml"]),
        ("caseFirstHtml", out["caseFirstHtml"]),
        ("resilientHtml", out["resilientHtml"]),
    ):
        _assert_no_unicode_dashes(html_doc, label)
        inspector = _RevealHTMLInspector()
        inspector.feed(html_doc)
        assert sum(1 for t, _ in inspector.tags if t == "details") == 4

    assert out["caseFirstHtml"] == out["mountedHtml"]
    assert "Sales Leak Case - Seed 8" in out["pairedHtml"]
    assert "OPTIMAL HOLD FIRE" in out["pairedHtml"]
    assert "Bayesian Solver:" in out["pairedHtml"]
    assert "HOLD FIRE" in out["pairedHtml"]
    assert "61.7%" in out["pairedHtml"]
    assert "Regret 1.88" in out["pairedHtml"]
    assert "Same World on gemini-4-carbon:" in out["pairedHtml"]
    assert 'class="outthink-ladder-row is-pod-focused" data-level-key="low"' in out["pairedHtml"]
    assert "$0.4885" in out["pairedHtml"]
    assert "11,325" in out["pairedHtml"]
    assert "(d14)" in out["pairedHtml"]

    carbon_rows = {r["level"]: r for r in out["carbonVm"]["rows"]}
    assert out["carbonVm"]["model"] == "gemini-4-carbon"
    assert carbon_rows["minimal"]["available"] is False
    assert carbon_rows["low"]["available"] is True
    assert carbon_rows["low"]["score"] == pytest.approx(0.85)
    assert carbon_rows["high"]["thinkingTokens"] == 23083


def test_failure_mode_enrichment_and_xss_safety() -> None:
    em_dash = chr(0x2014)
    xss = "<script>evil()</script><img src=1 onerror=bad()>"

    out = _run_js(
        """
        globalThis.window = globalThis;
        delete window.OUTTHINK_ANNOTATIONS;
        const modeCalls = [];
        window.getOutthinkAnnotation = function (model, level) {
          if (level === "minimal") {
            return {
              accused: "e04",
              correct: false,
              score: -1.0,
              cost_usd: 0.05,
              thinking_tokens: 0,
              primary_failure_tag: "premature_accusation",
              verbatim_quote: "Accusing e04 immediately.",
              source_file: "results/gemini/v2/atlas.json"
            };
          }
          if (level === "low") {
            return {
              accused: "e04",
              correct: false,
              score: -1.0,
              cost_usd: 0.09,
              thinking_tokens: 400,
              primary_failure_tag: "custom_xss_mode",
              verbatim_quote: "Testing xss failure mode.",
              source_file: "results/gemini/v2/atlas.json"
            };
          }
          return null;
        };

        window.getOutthinkFailureMode = function (tag) {
          modeCalls.push(tag);
          if (tag === "premature_accusation") {
            return {
              id: "premature_accusation",
              name: "Premature Accusation" + PAYLOAD.dash + "Early Commit",
              description: "Commits before posterior p clears break-even p*.",
              decision: "commit_timing",
              mechanism: "Treats noisy after-hours spike as conclusive proof.",
              solver_would: "Hold fire and plant a 3-way split canary."
            };
          }
          if (tag === "custom_xss_mode") {
            return {
              id: PAYLOAD.xss,
              name: PAYLOAD.xss,
              description: PAYLOAD.xss,
              decision: PAYLOAD.xss,
              mechanism: PAYLOAD.xss,
              solver_would: PAYLOAD.xss
            };
          }
          return null;
        };

        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const fnVm = Reveal.buildModel("hard", 2, "gemini-3.5-flash", "e11");
        const fnHtml = Reveal.renderHTML("hard", 2, "gemini-3.5-flash", "e11");

        delete window.getOutthinkFailureMode;
        window.OUTTHINK_FAILURE_MODES = {
          modes: [
            {
              id: "premature_accusation",
              name: "Taxonomy Premature Commit",
              description: "Triggered accusation below solver threshold.",
              decision: "commit_timing",
              solver_would: "Continue canary partitioning."
            }
          ]
        };
        const storeHtml = Reveal.renderHTML("hard", 2, "gemini-3.5-flash", "e11");

        return { modeCalls, fnVm, fnHtml, storeHtml };
        """,
        {"dash": f" {em_dash} ", "xss": xss},
    )

    assert "premature_accusation" in out["modeCalls"]
    assert "custom_xss_mode" in out["modeCalls"]

    fn_vm = out["fnVm"]
    fm0 = fn_vm["rows"][0]["failureMode"]
    assert fm0["enriched"] is True
    assert fm0["name"] == "Premature Accusation - Early Commit"
    assert fm0["decision"] == "commit_timing"
    assert fm0["solverWould"] == "Hold fire and plant a 3-way split canary."
    assert len(fn_vm["failureModesSummary"]) == 2

    fn_html = out["fnHtml"]
    _assert_no_unicode_dashes(fn_html, "failure mode enriched HTML")
    assert "<script" not in fn_html.lower()
    assert "<img" not in fn_html.lower()
    assert "Premature Accusation - Early Commit" in fn_html
    assert "Mechanism: Treats noisy after-hours spike as conclusive proof." in fn_html
    assert "Solver instead: Hold fire and plant a 3-way split canary." in fn_html
    assert 'data-failure-decision="commit_timing"' in fn_html

    inspector = _RevealHTMLInspector()
    inspector.feed(fn_html)
    for _, attrs in inspector.tags:
        for attr_name in attrs:
            assert not attr_name.lower().startswith("on")

    store_html = out["storeHtml"]
    _assert_no_unicode_dashes(store_html, "OUTTHINK_FAILURE_MODES fallback HTML")
    assert "Taxonomy Premature Commit" in store_html
    assert "Solver instead: Continue canary partitioning." in store_html


def test_real_annotations_bundle_smoke_when_present() -> None:
    if not ANNOTATIONS_JS.is_file() or not ANNOTATIONS_JSON.is_file():
        pytest.skip("annotations bundle not on this branch")

    raw_bundle = json.loads(ANNOTATIONS_JSON.read_text(encoding="utf-8"))
    expected_ep = raw_bundle["episodes"]["gemini-3.5-flash/high/medium/0"]
    expected_quote = expected_ep["quotes"][0]["quote"]
    expected_cost = f"${expected_ep['cost_usd']:.4f}"

    out = _run_js(
        """
        globalThis.window = globalThis;
        require(process.env.OUTTHINK_ANNOTATIONS_JS_PATH);
        window.getOutthinkFailureMode = function (tag) {
          return {
            id: tag,
            name: "Mode " + tag,
            description: "Catalog entry for " + tag,
            decision: "commit_timing"
          };
        };
        const Reveal = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const html = Reveal.render("medium", 0, "gemini-3.5-flash", "e05");
        const vm = Reveal.buildModel("medium", 0, "gemini-3.5-flash", "e05");

        const engineState = {
          caseId: "medium-0",
          action: "accuse",
          suspectId: "e05",
          correct: true,
          optimal: true,
          score: 0.74,
          verdictLabel: "OPTIMAL ACCUSATION",
          trueMole: "e05",
          solver: { final_score: 0.74, recommended_call: "accuse", top_suspect: "e05", top_prob: 0.96, break_even_prob: 0.58 },
          levelComparisons: [
            {
              key: "high",
              model: "gemini-3.5-flash",
              thinking_level: "high",
              accused: expectedAccused(),
              accused_day: 6,
              correct: true,
              score: 0.85,
              cost_usd: 0,
              thinking_tokens: 0,
              run_id: "ladder:ladder-v14:gemini-3.5-flash/high/medium/0",
              analyst_quote: "Engine summary sentence for high."
            }
          ]
        };
        function expectedAccused() { return "e05"; }
        const mergedHtml = Reveal.render(engineState);
        const mergedVm = Reveal.buildModel(engineState);
        return { html, vm, mergedHtml, mergedVm };
        """
    )

    _assert_no_unicode_dashes(out["html"], "real annotations rendered HTML")
    _assert_no_unicode_dashes(out["mergedHtml"], "merged engine + real annotations HTML")
    assert out["vm"]["trueMole"] == "e05"
    assert expected_cost in out["html"]
    assert expected_cost in out["mergedHtml"]

    inspector = _RevealHTMLInspector()
    inspector.feed(out["html"])
    blockquotes = [txt for t, _, txt in inspector.completed if t == "blockquote"]
    assert expected_quote in blockquotes

    merged_inspector = _RevealHTMLInspector()
    merged_inspector.feed(out["mergedHtml"])
    merged_quotes = [txt for t, _, txt in merged_inspector.completed if t == "blockquote"]
    assert expected_quote in merged_quotes
    assert "Engine summary sentence for high." in merged_quotes


def test_browser_and_node_without_window_exports_outthink_reveal_card() -> None:
    out = _run_js(
        """
        delete globalThis.window;
        delete globalThis.OutThinkRevealCard;
        delete globalThis.OutthinkRevealCard;
        delete require.cache[require.resolve(process.env.OUTTHINK_REVEAL_CARD_PATH)];
        const nodeMod = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const nodeHtml = nodeMod.render("hard", 1, "gemini-4-carbon", "e33", {
          trueMole: "e33"
        });
        const nodeHasGlobal = Boolean(globalThis.OutThinkRevealCard && globalThis.OutthinkRevealCard);

        globalThis.window = {};
        delete require.cache[require.resolve(process.env.OUTTHINK_REVEAL_CARD_PATH)];
        const browserMod = require(process.env.OUTTHINK_REVEAL_CARD_PATH);
        const winCard = globalThis.window.OutThinkRevealCard;
        const winAlias = globalThis.window.OutthinkRevealCard;
        const winHtml = winCard.render("hard", 1, "gemini-4-carbon", "e33", {
          trueMole: "e33"
        });

        return {
          nodeHasGlobal,
          nodeHtml,
          hasWinOutThink: Boolean(winCard),
          sameExport: winCard === browserMod && winCard === winAlias,
          methods: Object.keys(winCard).sort(),
          winHtml
        };
        """
    )

    assert out["nodeHasGlobal"] is True
    assert out["hasWinOutThink"] is True
    assert out["sameExport"] is True
    assert out["nodeHtml"] == out["winHtml"]
    _assert_no_unicode_dashes(out["winHtml"], "window.OutThinkRevealCard HTML")
    for fn_name in ("buildModel", "escapeHtml", "mount", "render", "renderDOM", "renderHTML"):
        assert fn_name in out["methods"]

