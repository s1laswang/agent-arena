from __future__ import annotations

import ast
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
INDEX_HTML_PATH = DEMO_DIR / "index.html"
STYLE_CSS_PATH = DEMO_DIR / "style.css"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
DOUBLE_SLASH = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
HTTP_SCHEME = "http:" + DOUBLE_SLASH
HTTPS_SCHEME = "https:" + DOUBLE_SLASH
WS_SCHEME = "ws:" + DOUBLE_SLASH
WSS_SCHEME = "wss:" + DOUBLE_SLASH
CO_AUTHORED_TOKEN = "Co-Authored" + "-By"

REQUIRED_DOM_IDS = (
    "phaser-stage",
    "stage-fallback",
    "case-select",
    "scoreboard-bar",
    "suspect-roster",
    "dossier-card",
    "btn-accuse",
    "btn-hold-fire",
    "evidence-tabs",
    "evidence-list",
    "reveal-panel",
    "provenance-footer",
)

AUXILIARY_DOM_IDS = (
    "dataset-badge",
    "btn-prev-case",
    "btn-next-case",
    "btn-reset-scores",
    "case-tier-badge",
    "case-title",
    "case-company",
    "case-seed-badge",
    "case-day-badge",
    "case-step-badge",
    "case-reward-badge",
    "case-status-pill",
    "btn-highlight-suspects",
    "highlight-summary",
    "dossier-clearance",
    "btn-filter-suspect",
    "evidence-cutoff-note",
    "count-canaries",
    "count-leaks",
    "count-access",
    "count-comms",
    "count-steps",
    "provenance-summary",
    "asset-credits-list",
)

CORE_ORDERED_SCRIPTS = (
    "engine.js",
    "scene.js",
    "game.js",
)

TRACKED_BUNDLE_SCRIPTS = (
    "chatter.js",
    "cases.js",
    "fallback_cases.js",
    "annotations.js",
    "personas.js",
    "evidence_cards.js",
    "assets/manifest.js",
)

VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

FORBIDDEN_CDN_TOKENS = (
    "cdnjs",
    "jsdelivr",
    "unpkg",
    "cloudflare",
    "googleapis",
    "gstatic",
)


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
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

    pytest.skip("no JavaScript runtime available")


class _IndexShellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict[str, Any] = {"tag": "document", "attrs": [], "children": []}
        self._stack: list[dict[str, Any]] = [self.root]
        self.elements: list[tuple[str, list[tuple[str, str]]]] = []
        self.inline_blocks: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_low = tag.lower()
        norm_attrs = [(k.lower(), "" if v is None else v) for k, v in attrs]
        self.elements.append((tag_low, norm_attrs))
        node: dict[str, Any] = {
            "tag": tag_low,
            "attrs": [[k, v] for k, v in norm_attrs],
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag_low not in VOID_HTML_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_low = tag.lower()
        norm_attrs = [(k.lower(), "" if v is None else v) for k, v in attrs]
        self.elements.append((tag_low, norm_attrs))
        node: dict[str, Any] = {
            "tag": tag_low,
            "attrs": [[k, v] for k, v in norm_attrs],
            "children": [],
        }
        self._stack[-1]["children"].append(node)

    def handle_endtag(self, tag: str) -> None:
        tag_low = tag.lower()
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx]["tag"] == tag_low:
                del self._stack[idx:]
                break

    def handle_data(self, data: str) -> None:
        parent_tag = self._stack[-1]["tag"]
        if parent_tag in {"script", "style"} and data.strip():
            self.inline_blocks.append((parent_tag, data))
        if data and data.strip():
            self._stack[-1]["children"].append({"text": data})


def _parse_index_html() -> _IndexShellParser:
    assert INDEX_HTML_PATH.is_file(), f"missing {INDEX_HTML_PATH}"
    parser = _IndexShellParser()
    parser.feed(INDEX_HTML_PATH.read_text(encoding="utf-8"))
    parser.close()
    return parser


def _has_external_url_token(value: str) -> bool:
    low = value.lower()
    if HTTP_SCHEME in low or HTTPS_SCHEME in low or WS_SCHEME in low or WSS_SCHEME in low:
        return True
    if DOUBLE_SLASH in low:
        return True
    return any(tok in low for tok in FORBIDDEN_CDN_TOKENS)


def _extract_script_srcs(parser: _IndexShellParser) -> list[str]:
    srcs: list[str] = []
    for tag, attrs in parser.elements:
        if tag == "script":
            attr_map = dict(attrs)
            assert "src" in attr_map and attr_map["src"].strip(), "every <script> in index.html must use a local src"
            srcs.append(attr_map["src"].strip())
    return srcs


def _synthetic_multi_case_payload() -> dict[str, Any]:
    return {
        "meta": {
            "total_episodes": 60,
            "total_cost_usd": 14.25,
        },
        "cases": [
            {
                "id": "syn-hard-1",
                "title": "Hard Seed 1: Board Valuation Trap",
                "model": "gemini-4-carbon",
                "anchor_level": "high",
                "tier": "hard",
                "seed": 1,
                "company": "Northstar Bio",
                "decision_day": 5,
                "decision_step": 8,
                "value_at_decision": 0.72,
                "true_mole": "e03",
                "suspects": [
                    {
                        "id": "e01",
                        "name": "Aino Salmi",
                        "dept": "Legal",
                        "role": "General Counsel",
                        "clearance": "exec",
                        "eliminated": True,
                        "canary_hits": 0,
                        "after_hours_count": 0,
                        "persona_note": "Maintains strict redline logs during daytime hours.",
                    },
                    {
                        "id": "e02",
                        "name": "Timo Korhonen",
                        "dept": "Infra",
                        "role": "Platform SRE",
                        "clearance": "elevated",
                        "eliminated": False,
                        "canary_hits": 0,
                        "after_hours_count": 2,
                        "persona_note": "Runs scheduled UTC backup rotations at 22:00.",
                    },
                    {
                        "id": "e03",
                        "name": "Noora Laine",
                        "dept": "Strategy",
                        "role": "M&A Lead",
                        "clearance": "exec",
                        "eliminated": False,
                        "canary_hits": 2,
                        "after_hours_count": 1,
                        "persona_note": "Compiled partner valuation annexes before freeze.",
                    },
                ],
                "canaries": [
                    {
                        "canary_id": "can_alpha",
                        "doc_id": "doc_board_mna",
                        "day_planted": 3,
                        "variants": [
                            {"variant": "A", "recipients": ["e03"]},
                            {"variant": "B", "recipients": ["e02"]},
                        ],
                        "leaked_variant": "A",
                    },
                    {
                        "canary_id": "can_future",
                        "doc_id": "doc_post_cutoff",
                        "day_planted": 9,
                        "variants": [{"variant": "Z", "recipients": ["e02"]}],
                        "leaked_variant": None,
                    },
                ],
                "leaks": [
                    {
                        "day": 5,
                        "doc_id": "doc_board_mna",
                        "canary_id": "can_alpha",
                        "leaked_variant": "A",
                        "channel": "trade_press",
                        "summary": "Fingerprinted clause A surfaced verbatim in morning brief.",
                    },
                    {
                        "day": 8,
                        "doc_id": "doc_post_cutoff",
                        "canary_id": "can_future",
                        "leaked_variant": "Z",
                        "channel": "future_wire",
                        "summary": "POST_DECISION_FUTURE_LEAK",
                    },
                ],
                "access_logs": [
                    {
                        "day": 4,
                        "employee": "e02",
                        "doc_id": "doc_infra_audit",
                        "after_hours": True,
                        "action": "read",
                    },
                    {
                        "day": 5,
                        "employee": "e03",
                        "doc_id": "doc_board_mna",
                        "after_hours": True,
                        "action": "export",
                    },
                    {
                        "day": 9,
                        "employee": "e03",
                        "doc_id": "doc_future_secret",
                        "after_hours": True,
                        "action": "POST_DECISION_FUTURE_LOG",
                    },
                ],
                "comms": [
                    {
                        "day": 4,
                        "kind": "slack",
                        "speaker": "e02",
                        "target": "all",
                        "topic": "backup window",
                        "text": "Nightly gateway rotation completed on schedule.",
                    },
                    {
                        "day": 5,
                        "kind": "interview",
                        "speaker": "e03",
                        "target": "investigator",
                        "topic": "annex export",
                        "text": "I exported the valuation tables for steering review.",
                    },
                    {
                        "day": 8,
                        "kind": "slack",
                        "speaker": "e03",
                        "target": "all",
                        "topic": "late spoiler",
                        "text": "POST_DECISION_FUTURE_COMM",
                    },
                ],
                "tool_steps": [
                    {
                        "t": 1,
                        "day": 3,
                        "tool": "plant_canary",
                        "args": {"doc_id": "doc_board_mna"},
                        "summary": "Planted disjoint variants A and B.",
                    },
                    {
                        "t": 6,
                        "day": 5,
                        "tool": "inspect_logs",
                        "args": {"day": 5},
                        "summary": "Verified export event on doc_board_mna.",
                    },
                    {
                        "t": 12,
                        "day": 5,
                        "tool": "accuse",
                        "args": {"employee": "e03"},
                        "summary": "POST_DECISION_FUTURE_STEP",
                    },
                ],
                "solver": {
                    "posterior": {"e01": 0.0, "e02": 0.03, "e03": 0.97},
                    "top_suspect": "e03",
                    "top_prob": 0.97,
                    "break_even_prob": 0.5814,
                    "ev_accuse_top": 0.6684,
                    "ev_hold_fire": 0.60,
                    "recommended_call": "accuse",
                    "final_accused": "e03",
                    "final_day": 5,
                    "final_score": 0.72,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "thinking_level": "minimal",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e02",
                        "accused_day": 3,
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.0042,
                        "thinking_tokens": 96,
                        "run_id": "syn-run-1-min",
                        "failure_tag": "premature_accusation",
                        "analyst_quote": "Chased after-hours SRE noise before canary triggered.",
                        "regret_total": 1.67,
                    },
                    {
                        "thinking_level": "low",
                        "model": "gemini-4-carbon",
                        "call_at_t": "hold_fire",
                        "accused": "e03",
                        "accused_day": 9,
                        "correct": True,
                        "score": 0.44,
                        "cost_usd": 0.0125,
                        "thinking_tokens": 420,
                        "run_id": "syn-run-1-low",
                        "failure_tag": "ignored_delay",
                        "analyst_quote": "Waited four extra days after variant A already isolated e03.",
                        "regret_total": 0.28,
                    },
                    {
                        "thinking_level": "medium",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e03",
                        "accused_day": 5,
                        "correct": True,
                        "score": 0.72,
                        "cost_usd": 0.028,
                        "thinking_tokens": 1450,
                        "run_id": "syn-run-1-med",
                        "failure_tag": None,
                        "analyst_quote": "Matched variant A directly to e03 above break-even.",
                        "regret_total": 0.0,
                    },
                    {
                        "thinking_level": "high",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e03",
                        "accused_day": 5,
                        "correct": True,
                        "score": 0.72,
                        "cost_usd": 0.061,
                        "thinking_tokens": 3900,
                        "run_id": "syn-run-1-high",
                        "failure_tag": None,
                        "analyst_quote": "Confirmed 97.0% posterior cleared 58.1% break-even.",
                        "regret_total": 0.0,
                    },
                    {
                        "thinking_level": "xhigh",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e03",
                        "accused_day": 5,
                        "correct": True,
                        "score": 0.72,
                        "cost_usd": 0.112,
                        "thinking_tokens": 7600,
                        "run_id": "syn-run-1-xhigh",
                        "failure_tag": None,
                        "analyst_quote": "Zero-regret stop at day 5.",
                        "regret_total": 0.0,
                    },
                ],
                "cross_model_carbon": [
                    {
                        "model": "gemini-4-carbon",
                        "thinking_level": "low",
                        "accused": "e03",
                        "accused_day": 9,
                        "cost_usd": 0.0125,
                        "thinking_tokens": 420,
                        "score": 0.44,
                        "correct": True,
                    },
                    {
                        "model": "gemini-4-carbon",
                        "thinking_level": "high",
                        "accused": "e03",
                        "accused_day": 5,
                        "cost_usd": 0.061,
                        "thinking_tokens": 3900,
                        "score": 0.72,
                        "correct": True,
                    },
                ],
            },
            {
                "id": "syn-med-2",
                "title": "Medium Seed 2: Split Variant Ambiguity",
                "model": "gemini-4-carbon",
                "anchor_level": "high",
                "tier": "medium",
                "seed": 2,
                "company": "Helios Assay",
                "decision_day": 4,
                "decision_step": 5,
                "value_at_decision": 0.20,
                "true_mole": "e05",
                "suspects": [
                    {
                        "id": "e04",
                        "name": "Mikko Lahti",
                        "dept": "Assay",
                        "role": "Lead Scientist",
                        "clearance": "restricted",
                        "eliminated": False,
                        "canary_hits": 1,
                        "after_hours_count": 1,
                        "persona_note": "Shared Variant C packet with clinical biostats.",
                    },
                    {
                        "id": "e05",
                        "name": "Sanna Virta",
                        "dept": "Clinical",
                        "role": "Trial Manager",
                        "clearance": "restricted",
                        "eliminated": False,
                        "canary_hits": 1,
                        "after_hours_count": 1,
                        "persona_note": "Reviewed Variant C packet ahead of site call.",
                    },
                    {
                        "id": "e06",
                        "name": "Janne Koski",
                        "dept": "Ops",
                        "role": "Coordinator",
                        "clearance": "standard",
                        "eliminated": True,
                        "canary_hits": 0,
                        "after_hours_count": 0,
                        "persona_note": "Held Variant D which never leaked.",
                    },
                ],
                "canaries": [
                    {
                        "canary_id": "can_beta",
                        "doc_id": "doc_trial_readout",
                        "day_planted": 2,
                        "variants": [
                            {"variant": "C", "recipients": ["e04", "e05"]},
                            {"variant": "D", "recipients": ["e06"]},
                        ],
                        "leaked_variant": "C",
                    }
                ],
                "leaks": [
                    {
                        "day": 4,
                        "doc_id": "doc_trial_readout",
                        "canary_id": "can_beta",
                        "leaked_variant": "C",
                        "channel": "analyst_note",
                        "summary": "Variant C phrase appeared in external note; two holders remain.",
                    }
                ],
                "access_logs": [
                    {
                        "day": 3,
                        "employee": "e04",
                        "doc_id": "doc_trial_readout",
                        "after_hours": True,
                        "action": "read",
                    },
                    {
                        "day": 3,
                        "employee": "e05",
                        "doc_id": "doc_trial_readout",
                        "after_hours": True,
                        "action": "read",
                    },
                ],
                "comms": [
                    {
                        "day": 4,
                        "kind": "hallway",
                        "speaker": "e04",
                        "target": "e05",
                        "topic": "readout tables",
                        "text": "Both teams pulled the same annex yesterday evening.",
                    }
                ],
                "tool_steps": [
                    {
                        "t": 2,
                        "day": 2,
                        "tool": "plant_canary",
                        "args": {"doc_id": "doc_trial_readout"},
                        "summary": "Split C=[e04,e05], D=[e06].",
                    }
                ],
                "solver": {
                    "posterior": {"e04": 0.50, "e05": 0.50, "e06": 0.0},
                    "top_suspect": "e05",
                    "top_prob": 0.50,
                    "break_even_prob": 0.8333,
                    "ev_accuse_top": -0.40,
                    "ev_hold_fire": 0.38,
                    "recommended_call": "hold_fire",
                    "final_accused": "e05",
                    "final_day": 6,
                    "final_score": 0.38,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "thinking_level": "minimal",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e04",
                        "accused_day": 4,
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.0038,
                        "thinking_tokens": 88,
                        "run_id": "syn-run-2-min",
                        "failure_tag": "premature_accusation",
                        "analyst_quote": "Guessed 50-50 coin flip far below 83.3% break-even.",
                        "regret_total": 1.38,
                    },
                    {
                        "thinking_level": "high",
                        "model": "gemini-4-carbon",
                        "call_at_t": "hold_fire",
                        "accused": "e05",
                        "accused_day": 6,
                        "correct": True,
                        "score": 0.38,
                        "cost_usd": 0.054,
                        "thinking_tokens": 3400,
                        "run_id": "syn-run-2-high",
                        "failure_tag": None,
                        "analyst_quote": "Held fire at 50% < 83.3% break-even and planted orthogonal split.",
                        "regret_total": 0.0,
                    },
                ],
            },
            {
                "id": "syn-easy-3",
                "title": "Easy Seed 3: Sprint Briefing Partition",
                "model": "gemini-4-carbon",
                "anchor_level": "high",
                "tier": "easy",
                "seed": 3,
                "company": "Vanguard Labs",
                "decision_day": 3,
                "decision_step": 4,
                "value_at_decision": 0.65,
                "true_mole": "e04",
                "suspects": [
                    {
                        "id": "e01",
                        "name": "Pekka Rinne",
                        "dept": "Product",
                        "role": "PM",
                        "clearance": "standard",
                        "eliminated": False,
                        "canary_hits": 0,
                        "after_hours_count": 3,
                        "persona_note": "Stayed late formatting launch roadmap.",
                    },
                    {
                        "id": "e04",
                        "name": "Elina Ranta",
                        "dept": "Alliances",
                        "role": "Partner Lead",
                        "clearance": "elevated",
                        "eliminated": False,
                        "canary_hits": 1,
                        "after_hours_count": 0,
                        "persona_note": "Held exclusive Variant E partner brief.",
                    },
                ],
                "canaries": [
                    {
                        "canary_id": "can_gamma",
                        "doc_id": "doc_partner_brief",
                        "day_planted": 2,
                        "variants": [
                            {"variant": "E", "recipients": ["e04"]},
                            {"variant": "F", "recipients": ["e01"]},
                        ],
                        "leaked_variant": "E",
                    }
                ],
                "leaks": [
                    {
                        "day": 3,
                        "doc_id": "doc_partner_brief",
                        "canary_id": "can_gamma",
                        "leaked_variant": "E",
                        "channel": "blog_scoop",
                        "summary": "Variant E watermark quoted externally.",
                    }
                ],
                "access_logs": [
                    {
                        "day": 2,
                        "employee": "e04",
                        "doc_id": "doc_partner_brief",
                        "after_hours": False,
                        "action": "download",
                    }
                ],
                "comms": [
                    {
                        "day": 2,
                        "kind": "slack",
                        "speaker": "e01",
                        "target": "all",
                        "topic": "roadmap",
                        "text": "Draft deck stays locked until Thursday.",
                    }
                ],
                "tool_steps": [
                    {
                        "t": 1,
                        "day": 2,
                        "tool": "plant_canary",
                        "args": {"doc_id": "doc_partner_brief"},
                        "summary": "Planted E/F binary split.",
                    }
                ],
                "solver": {
                    "posterior": {"e01": 0.02, "e04": 0.98},
                    "top_suspect": "e04",
                    "top_prob": 0.98,
                    "break_even_prob": 0.6061,
                    "ev_accuse_top": 0.617,
                    "ev_hold_fire": 0.53,
                    "recommended_call": "accuse",
                    "final_accused": "e04",
                    "final_day": 3,
                    "final_score": 0.65,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "thinking_level": "minimal",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e01",
                        "accused_day": 2,
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.0029,
                        "thinking_tokens": 64,
                        "run_id": "syn-run-3-min",
                        "failure_tag": "premature_accusation",
                        "analyst_quote": "Blamed late-shift PM e01 instead of canary holder e04.",
                        "regret_total": 1.65,
                    },
                    {
                        "thinking_level": "high",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e04",
                        "accused_day": 3,
                        "correct": True,
                        "score": 0.65,
                        "cost_usd": 0.041,
                        "thinking_tokens": 2400,
                        "run_id": "syn-run-3-high",
                        "failure_tag": None,
                        "analyst_quote": "Pinned e04 immediately upon Variant E leak.",
                        "regret_total": 0.0,
                    },
                ],
            },
        ],
    }


JS_DOM_CANVAS_SANDBOX = r"""
const fs = require("fs");
const INPUT = JSON.parse(fs.readFileSync(0, "utf8"));
const HASH_CH = String.fromCharCode(35);

const networkViolations = [];
let clockMs = 1000;
let nextRafId = 1;
const rafQueue = new Map();
const createdContexts = [];

function createMockContext2D() {
  const stateStack = [];
  let smoothing = true;
  const ctx = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "10px monospace",
    textAlign: "left",
    globalAlpha: 1,
    webkitImageSmoothingEnabled: true,
    mozImageSmoothingEnabled: true,
    frameCount: 0,
    allTexts: [],
    currentFrameTexts: [],
    fillRects: [],
    strokeRects: [],
    save() {
      stateStack.push({
        fillStyle: this.fillStyle,
        strokeStyle: this.strokeStyle,
        lineWidth: this.lineWidth,
        font: this.font,
        textAlign: this.textAlign,
        globalAlpha: this.globalAlpha
      });
    },
    restore() {
      const prev = stateStack.pop();
      if (prev) {
        this.fillStyle = prev.fillStyle;
        this.strokeStyle = prev.strokeStyle;
        this.lineWidth = prev.lineWidth;
        this.font = prev.font;
        this.textAlign = prev.textAlign;
        this.globalAlpha = prev.globalAlpha;
      }
    },
    fillRect(x, y, w, h) {
      this.fillRects.push({ x, y, w, h, fillStyle: String(this.fillStyle) });
    },
    strokeRect(x, y, w, h) {
      this.strokeRects.push({ x, y, w, h, strokeStyle: String(this.strokeStyle) });
    },
    clearRect() {},
    fillText(txt, x, y) {
      const entry = {
        text: String(txt),
        x: Number(x),
        y: Number(y),
        fillStyle: String(this.fillStyle),
        font: String(this.font)
      };
      this.allTexts.push(entry);
      this.currentFrameTexts.push(entry);
    },
    strokeText(txt, x, y) {
      const entry = {
        text: String(txt),
        x: Number(x),
        y: Number(y),
        fillStyle: String(this.strokeStyle),
        font: String(this.font)
      };
      this.allTexts.push(entry);
      this.currentFrameTexts.push(entry);
    },
    measureText(txt) {
      return { width: String(txt == null ? "" : txt).length * 6 };
    },
    beginPath() {},
    closePath() {},
    moveTo() {},
    lineTo() {},
    arc() {},
    rect() {},
    clip() {},
    fill() {},
    stroke() {},
    drawImage() {},
    translate() {},
    scale() {},
    rotate() {},
    setTransform() {},
    resetCumulativeLog() {
      this.allTexts = [];
    }
  };
  Object.defineProperty(ctx, "imageSmoothingEnabled", {
    get() {
      return smoothing;
    },
    set(v) {
      smoothing = Boolean(v);
      ctx.currentFrameTexts = [];
      ctx.frameCount += 1;
    }
  });
  createdContexts.push(ctx);
  return ctx;
}

function createTextNode(text) {
  return {
    nodeType: 3,
    nodeValue: String(text),
    parentNode: null,
    get textContent() {
      return this.nodeValue;
    },
    set textContent(v) {
      this.nodeValue = String(v == null ? "" : v);
    }
  };
}

function matchesCompoundSelector(node, rawCompound) {
  if (!node || node.nodeType !== 1) {
    return false;
  }
  const s = String(rawCompound || "").trim();
  if (!s) {
    return false;
  }
  let i = 0;
  const n = s.length;
  while (i < n) {
    const ch = s[i];
    if (ch === "[") {
      const closeIdx = s.indexOf("]", i + 1);
      if (closeIdx < 0) {
        return false;
      }
      const inside = s.slice(i + 1, closeIdx).trim();
      const eqIdx = inside.indexOf("=");
      if (eqIdx < 0) {
        if (!node.hasAttribute(inside)) {
          return false;
        }
      } else {
        const attrName = inside.slice(0, eqIdx).trim();
        let attrVal = inside.slice(eqIdx + 1).trim();
        if (
          (attrVal.startsWith('"') && attrVal.endsWith('"')) ||
          (attrVal.startsWith("'") && attrVal.endsWith("'"))
        ) {
          attrVal = attrVal.slice(1, -1);
        }
        if (node.getAttribute(attrName) !== attrVal) {
          return false;
        }
      }
      i = closeIdx + 1;
    } else if (ch === ".") {
      let j = i + 1;
      while (j < n && s[j] !== "." && s[j] !== "[" && s[j] !== HASH_CH) {
        j += 1;
      }
      const cls = s.slice(i + 1, j);
      if (!cls || !node.classList.contains(cls)) {
        return false;
      }
      i = j;
    } else if (ch === HASH_CH) {
      let j = i + 1;
      while (j < n && s[j] !== "." && s[j] !== "[" && s[j] !== HASH_CH) {
        j += 1;
      }
      const wantId = s.slice(i + 1, j);
      if (!wantId || node.id !== wantId) {
        return false;
      }
      i = j;
    } else {
      let j = i;
      while (j < n && s[j] !== "." && s[j] !== "[" && s[j] !== HASH_CH) {
        j += 1;
      }
      const wantTag = s.slice(i, j).toUpperCase();
      if (wantTag && wantTag !== "*" && node.tagName !== wantTag) {
        return false;
      }
      i = j;
    }
  }
  return true;
}

function matchesSelectorList(node, selector) {
  const groups = String(selector || "").split(",");
  for (let g = 0; g < groups.length; g += 1) {
    const tokens = groups[g].trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) {
      continue;
    }
    if (!matchesCompoundSelector(node, tokens[tokens.length - 1])) {
      continue;
    }
    let cur = node.parentNode;
    let ok = true;
    for (let t = tokens.length - 2; t >= 0; t -= 1) {
      while (cur && !matchesCompoundSelector(cur, tokens[t])) {
        cur = cur.parentNode;
      }
      if (!cur) {
        ok = false;
        break;
      }
      cur = cur.parentNode;
    }
    if (ok) {
      return true;
    }
  }
  return false;
}

function createElementNode(tagName) {
  const upperTag = String(tagName || "div").toUpperCase();
  const attrs = new Map();
  const classSet = new Set();
  const listeners = new Map();
  const childNodes = [];
  let selectedFlag = false;
  let canvasCtx = null;

  function syncClassAttrFromSet() {
    const joined = Array.from(classSet).join(" ");
    if (joined) {
      attrs.set("class", joined);
    } else {
      attrs.delete("class");
    }
  }

  function syncClassSetFromString(raw) {
    classSet.clear();
    const parts = String(raw || "").split(/\s+/).filter(Boolean);
    for (const p of parts) {
      classSet.add(p);
    }
    syncClassAttrFromSet();
  }

  const node = {
    nodeType: 1,
    tagName: upperTag,
    parentNode: null,
    style: { cssText: "", cursor: "default" },
    width: upperTag === "CANVAS" ? 300 : 0,
    height: upperTag === "CANVAS" ? 150 : 0,
    get parentElement() {
      return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null;
    },
    get childNodes() {
      return childNodes;
    },
    get children() {
      return childNodes.filter((c) => c.nodeType === 1);
    },
    get firstChild() {
      return childNodes.length > 0 ? childNodes[0] : null;
    },
    get id() {
      return attrs.get("id") || "";
    },
    set id(v) {
      const s = String(v == null ? "" : v);
      if (s) {
        attrs.set("id", s);
      } else {
        attrs.delete("id");
      }
    },
    get className() {
      return Array.from(classSet).join(" ");
    },
    set className(v) {
      syncClassSetFromString(v);
    },
    classList: {
      add(...tokens) {
        for (const tok of tokens) {
          if (tok) {
            classSet.add(String(tok));
          }
        }
        syncClassAttrFromSet();
      },
      remove(...tokens) {
        for (const tok of tokens) {
          classSet.delete(String(tok));
        }
        syncClassAttrFromSet();
      },
      toggle(tok, force) {
        const key = String(tok);
        const shouldAdd = force !== undefined ? Boolean(force) : !classSet.has(key);
        if (shouldAdd) {
          classSet.add(key);
        } else {
          classSet.delete(key);
        }
        syncClassAttrFromSet();
        return shouldAdd;
      },
      contains(tok) {
        return classSet.has(String(tok));
      }
    },
    get hidden() {
      return attrs.has("hidden");
    },
    set hidden(v) {
      if (v) {
        attrs.set("hidden", "");
      } else {
        attrs.delete("hidden");
      }
    },
    get disabled() {
      return attrs.has("disabled");
    },
    set disabled(v) {
      if (v) {
        attrs.set("disabled", "");
      } else {
        attrs.delete("disabled");
      }
    },
    get type() {
      return attrs.get("type") || "";
    },
    set type(v) {
      attrs.set("type", String(v == null ? "" : v));
    },
    get selected() {
      return selectedFlag;
    },
    set selected(v) {
      const flag = Boolean(v);
      selectedFlag = flag;
      if (flag && this.parentNode && this.parentNode.tagName === "SELECT") {
        for (const sib of this.parentNode.children) {
          if (sib !== this && sib.tagName === "OPTION") {
            sib._setSelectedRaw(false);
          }
        }
      }
    },
    _setSelectedRaw(flag) {
      selectedFlag = Boolean(flag);
    },
    get value() {
      if (upperTag === "SELECT") {
        const opts = this.children.filter((c) => c.tagName === "OPTION");
        for (const opt of opts) {
          if (opt.selected) {
            return opt.value;
          }
        }
        return opts.length > 0 ? opts[0].value : "";
      }
      if (upperTag === "OPTION") {
        return attrs.has("value") ? attrs.get("value") : this.textContent;
      }
      return attrs.get("value") || "";
    },
    set value(v) {
      const strVal = String(v == null ? "" : v);
      if (upperTag === "SELECT") {
        const opts = this.children.filter((c) => c.tagName === "OPTION");
        for (const opt of opts) {
          opt._setSelectedRaw(opt.value === strVal);
        }
        return;
      }
      attrs.set("value", strVal);
    },
    get textContent() {
      let out = "";
      for (const ch of childNodes) {
        out += ch.textContent;
      }
      return out;
    },
    set textContent(v) {
      for (const ch of childNodes) {
        ch.parentNode = null;
      }
      childNodes.length = 0;
      const s = v == null ? "" : String(v);
      if (s.length > 0) {
        const tn = createTextNode(s);
        tn.parentNode = this;
        childNodes.push(tn);
      }
    },
    setAttribute(name, value) {
      const k = String(name).toLowerCase();
      const s = String(value == null ? "" : value);
      if (k === "class") {
        syncClassSetFromString(s);
        return;
      }
      if (k === "selected") {
        this.selected = true;
      }
      attrs.set(k, s);
    },
    getAttribute(name) {
      const k = String(name).toLowerCase();
      return attrs.has(k) ? attrs.get(k) : null;
    },
    hasAttribute(name) {
      return attrs.has(String(name).toLowerCase());
    },
    removeAttribute(name) {
      const k = String(name).toLowerCase();
      if (k === "class") {
        syncClassSetFromString("");
        return;
      }
      attrs.delete(k);
    },
    appendChild(child) {
      if (!child) {
        return child;
      }
      if (child.parentNode && typeof child.parentNode.removeChild === "function") {
        child.parentNode.removeChild(child);
      }
      child.parentNode = this;
      childNodes.push(child);
      if (upperTag === "SELECT" && child.tagName === "OPTION" && child.selected) {
        for (const sib of this.children) {
          if (sib !== child && sib.tagName === "OPTION") {
            sib._setSelectedRaw(false);
          }
        }
      }
      return child;
    },
    removeChild(child) {
      const idx = childNodes.indexOf(child);
      if (idx >= 0) {
        childNodes.splice(idx, 1);
        child.parentNode = null;
      }
      return child;
    },
    addEventListener(type, fn) {
      const key = String(type);
      if (!listeners.has(key)) {
        listeners.set(key, []);
      }
      listeners.get(key).push(fn);
    },
    removeEventListener(type, fn) {
      const key = String(type);
      const arr = listeners.get(key);
      if (!arr) {
        return;
      }
      const idx = arr.indexOf(fn);
      if (idx >= 0) {
        arr.splice(idx, 1);
      }
    },
    dispatchEvent(rawEv) {
      const ev = Object.assign(
        {
          type: "click",
          bubbles: true,
          clientX: 0,
          clientY: 0,
          _stopped: false,
          preventDefault() {},
          stopPropagation() {
            this._stopped = true;
          }
        },
        rawEv || {}
      );
      if (!ev.target) {
        ev.target = this;
      }
      let cur = this;
      while (cur) {
        ev.currentTarget = cur;
        const handlers = cur._getListeners ? cur._getListeners(ev.type) : [];
        for (const fn of handlers.slice()) {
          fn.call(cur, ev);
        }
        if (!ev.bubbles || ev._stopped) {
          break;
        }
        cur = cur.parentNode;
      }
      return true;
    },
    _getListeners(type) {
      return listeners.get(String(type)) || [];
    },
    click(coords) {
      if (this.disabled) {
        return;
      }
      const extra = coords && typeof coords === "object" ? coords : {};
      this.dispatchEvent(
        Object.assign({ type: "click", bubbles: true, clientX: 0, clientY: 0 }, extra)
      );
    },
    matches(selector) {
      return matchesSelectorList(this, selector);
    },
    closest(selector) {
      let cur = this;
      while (cur && cur.nodeType === 1) {
        if (matchesSelectorList(cur, selector)) {
          return cur;
        }
        cur = cur.parentNode;
      }
      return null;
    },
    querySelector(selector) {
      const found = this.querySelectorAll(selector);
      return found.length > 0 ? found[0] : null;
    },
    querySelectorAll(selector) {
      const results = [];
      function walk(parent) {
        for (const ch of parent.children) {
          if (matchesSelectorList(ch, selector)) {
            results.push(ch);
          }
          walk(ch);
        }
      }
      walk(this);
      return results;
    },
    scrollIntoView() {},
    getBoundingClientRect() {
      return {
        left: 0,
        top: 0,
        width: this.width || 960,
        height: this.height || 520
      };
    },
    getContext(kind) {
      if (upperTag === "CANVAS" && String(kind) === "2d") {
        if (!canvasCtx) {
          canvasCtx = createMockContext2D();
        }
        return canvasCtx;
      }
      return null;
    }
  };
  return node;
}

function buildDomFromAst(astNode) {
  if (astNode && typeof astNode.text === "string") {
    return createTextNode(astNode.text);
  }
  const elem = createElementNode(astNode.tag || "div");
  const rawAttrs = Array.isArray(astNode.attrs) ? astNode.attrs : [];
  for (const pair of rawAttrs) {
    elem.setAttribute(pair[0], pair[1]);
  }
  const kids = Array.isArray(astNode.children) ? astNode.children : [];
  for (const kid of kids) {
    elem.appendChild(buildDomFromAst(kid));
  }
  return elem;
}

const htmlRootAst =
  (INPUT.domTree.children || []).find((c) => c.tag === "html") || INPUT.domTree;
const documentElement = buildDomFromAst(htmlRootAst);

function findById(rootNode, targetId) {
  if (!rootNode || rootNode.nodeType !== 1) {
    return null;
  }
  if (rootNode.id === targetId) {
    return rootNode;
  }
  for (const ch of rootNode.children) {
    const hit = findById(ch, targetId);
    if (hit) {
      return hit;
    }
  }
  return null;
}

const docListeners = new Map();
const documentObj = {
  readyState: "complete",
  documentElement,
  head: documentElement.querySelector("head"),
  body: documentElement.querySelector("body"),
  createElement(tag) {
    return createElementNode(tag);
  },
  createTextNode(txt) {
    return createTextNode(txt);
  },
  getElementById(id) {
    return findById(documentElement, String(id));
  },
  querySelector(sel) {
    return documentElement.querySelector(sel);
  },
  querySelectorAll(sel) {
    return documentElement.querySelectorAll(sel);
  },
  addEventListener(type, fn) {
    const k = String(type);
    if (!docListeners.has(k)) {
      docListeners.set(k, []);
    }
    docListeners.get(k).push(fn);
  },
  removeEventListener() {}
};

class MockImage {
  constructor() {
    this.complete = false;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
    this.width = 0;
    this.height = 0;
    this.onload = null;
    this.onerror = null;
    this._src = "";
  }
  get src() {
    return this._src;
  }
  set src(val) {
    const s = String(val == null ? "" : val);
    this._src = s;
    const low = s.toLowerCase();
    if (low.includes("http:") || low.includes("https:") || low.startsWith(String.fromCharCode(47, 47))) {
      networkViolations.push("Image:" + s);
      return;
    }
    this.complete = true;
    this.naturalWidth = 32;
    this.naturalHeight = 32;
    this.width = 32;
    this.height = 32;
  }
}

globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.document = documentObj;
globalThis.Image = MockImage;
globalThis.performance = {
  now() {
    clockMs += 16;
    return clockMs;
  }
};
globalThis.requestAnimationFrame = function (cb) {
  const id = nextRafId;
  nextRafId += 1;
  rafQueue.set(id, cb);
  return id;
};
globalThis.cancelAnimationFrame = function (id) {
  rafQueue.delete(id);
};
globalThis.fetch = function (url) {
  networkViolations.push("fetch:" + String(url));
  throw new Error("Airgap violation: fetch disabled");
};
globalThis.XMLHttpRequest = function () {
  networkViolations.push("XMLHttpRequest");
  throw new Error("Airgap violation: XMLHttpRequest disabled");
};
globalThis.WebSocket = function (url) {
  networkViolations.push("WebSocket:" + String(url));
  throw new Error("Airgap violation: WebSocket disabled");
};

if (INPUT.syntheticData) {
  globalThis.OUTTHINK_DATA = INPUT.syntheticData;
}

const loadedScriptPaths = [];
for (const scriptPath of INPUT.scriptPaths) {
  const code = fs.readFileSync(scriptPath, "utf8");
  (0, eval)(code);
  loadedScriptPaths.push(scriptPath);
}

function getPrimaryCanvas() {
  const stage = documentObj.getElementById("phaser-stage");
  return stage ? stage.querySelector("canvas") : null;
}

function getPrimaryCtx() {
  const cv = getPrimaryCanvas();
  return cv ? cv.getContext("2d") : createdContexts[0] || null;
}

function currentFrameTextStrings() {
  const ctx = getPrimaryCtx();
  return ctx ? ctx.currentFrameTexts.map((t) => t.text) : [];
}

function allCanvasTextStrings() {
  const ctx = getPrimaryCtx();
  return ctx ? ctx.allTexts.map((t) => t.text) : [];
}

function readScoreboardSnapshot() {
  const bar = documentObj.getElementById("scoreboard-bar");
  const tiles = bar ? bar.querySelectorAll(".score-tile") : [];
  return tiles.map((tile) => {
    const actor = tile.querySelector(".score-actor");
    const points = tile.querySelector(".score-points");
    const acc = tile.querySelector(".score-acc");
    const pills = tile.querySelectorAll(".pill").map((p) => p.textContent);
    return {
      actor: actor ? actor.textContent : "",
      points: points ? points.textContent : "",
      acc: acc ? acc.textContent : "",
      pills,
      beaten: tile.classList.contains("score-tile-beaten"),
      fullText: tile.textContent
    };
  });
}
"""


def _run_shell_sandbox(
    js_test_body: str,
    *,
    force_synthetic: bool = False,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parser = _parse_index_html()
    script_srcs = _extract_script_srcs(parser)

    script_paths: list[str] = []
    expected_rel_order: list[str] = []
    has_disk_cases = (DEMO_DIR / "cases.js").is_file() or (DEMO_DIR / "fallback_cases.js").is_file()
    for rel_src in script_srcs:
        if force_synthetic and rel_src in {"cases.js", "fallback_cases.js"}:
            continue
        candidate = DEMO_DIR / rel_src
        if candidate.is_file():
            expected_rel_order.append(rel_src)
            script_paths.append(str(candidate))

    synthetic_data = _synthetic_multi_case_payload() if (force_synthetic or not has_disk_cases) else None
    stdin_payload: dict[str, Any] = {
        "domTree": parser.root,
        "scriptPaths": script_paths,
        "syntheticData": synthetic_data,
        "extra": extra_payload or {},
    }

    cmd_prefix, env = _resolve_js_cmd()
    wrapper = (
        JS_DOM_CANVAS_SANDBOX
        + "\nconst RESULT = (() => {\n"
        + js_test_body
        + "\n})();\n"
        + "process.stdout.write(JSON.stringify({ result: RESULT, networkViolations, loadedScriptPaths }));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=env,
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert proc.returncode == 0, (
        f"Shell JS sandbox failed (rc={proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    parsed = json.loads(proc.stdout)
    assert parsed["networkViolations"] == [], f"Airgap runtime violations: {parsed['networkViolations']}"
    loaded_rel = [Path(p).relative_to(DEMO_DIR).as_posix() for p in parsed["loadedScriptPaths"]]
    assert loaded_rel == expected_rel_order
    assert loaded_rel[-3:] == ["engine.js", "scene.js", "game.js"]
    return parsed["result"]


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    in_regex = False
    in_regex_class = False
    prev_sig = "("

    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
                prev_sig = '"'
            i += 1
            continue

        if in_regex:
            if ch == "\\":
                i += 2
                continue
            if ch == "\n":
                in_regex = False
                in_regex_class = False
                line += 1
                i += 1
                continue
            if ch == "[" and not in_regex_class:
                in_regex_class = True
            elif ch == "]" and in_regex_class:
                in_regex_class = False
            elif ch == SLASH and not in_regex_class:
                in_regex = False
                prev_sig = SLASH
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, DOUBLE_SLASH))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
            if prev_sig in " (,=:[!&|?{};+-*%<>^~":
                in_regex = True
                in_regex_class = False
                i += 1
                continue

        prev_sig = ch
        i += 1

    return hits


def _load_protected_rules() -> list[str]:
    assert PROTECTED_PATHS_FILE.is_file()
    rules: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        rules.append(stripped)
    return rules


def _matches_protected_rule(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/"):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def test_index_html_and_style_css_100_percent_airgap() -> None:
    parser = _parse_index_html()
    assert STYLE_CSS_PATH.is_file(), f"missing {STYLE_CSS_PATH}"

    raw_html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    raw_css = STYLE_CSS_PATH.read_text(encoding="utf-8")

    assert not _has_external_url_token(raw_html), "external URL or protocol-relative token found in index.html"
    assert not _has_external_url_token(raw_css), "external URL or protocol-relative token found in style.css"

    DemoResolved = DEMO_DIR.resolve()
    stylesheet_links: list[str] = []

    for tag, attrs in parser.elements:
        for attr_name, attr_val in attrs:
            assert not _has_external_url_token(attr_val), (
                f"airgap violation on <{tag} {attr_name}={attr_val!r}>"
            )
            if tag in {"script", "link", "img"} and attr_name in {"src", "href", "srcset"}:
                cleaned = attr_val.strip()
                assert cleaned, f"empty {attr_name} on <{tag}>"
                assert not cleaned.startswith(SLASH), f"non-relative {attr_name} on <{tag}>: {cleaned}"
                assert ".." not in Path(cleaned).parts, f"parent traversal in <{tag} {attr_name}={cleaned!r}>"
                resolved = (DEMO_DIR / cleaned).resolve()
                assert resolved.is_relative_to(DemoResolved), f"path escapes demo dir: {cleaned}"
                if tag == "link":
                    stylesheet_links.append(cleaned)
                    assert resolved.is_file(), f"linked asset missing on disk: {cleaned}"

    assert "style.css" in stylesheet_links

    for block_tag, block_text in parser.inline_blocks:
        assert not _has_external_url_token(block_text), f"external URL inside inline <{block_tag}>"

    css_urls = re.findall(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)", raw_css, flags=re.IGNORECASE)
    for css_ref in css_urls:
        assert not _has_external_url_token(css_ref), f"external CSS url() reference: {css_ref}"
    assert "@import" not in raw_css.lower(), "external @import forbidden in airgapped style.css"


def test_required_dom_ids_and_exact_local_script_order() -> None:
    parser = _parse_index_html()

    seen_ids: list[str] = []
    elem_by_id: dict[str, tuple[str, dict[str, str]]] = {}
    for tag, attrs in parser.elements:
        attr_map = dict(attrs)
        if "id" in attr_map:
            elem_id = attr_map["id"]
            assert elem_id not in elem_by_id, f"duplicate DOM id in index.html: {elem_id}"
            seen_ids.append(elem_id)
            elem_by_id[elem_id] = (tag, attr_map)

    for req_id in REQUIRED_DOM_IDS:
        assert req_id in elem_by_id, f"missing required DOM id: {req_id}"

    for aux_id in AUXILIARY_DOM_IDS:
        assert aux_id in elem_by_id, f"missing expected shell control DOM id: {aux_id}"

    assert "hidden" in elem_by_id["stage-fallback"][1], "stage-fallback must start hidden in index.html"
    assert "hidden" in elem_by_id["reveal-panel"][1], "reveal-panel must start hidden in index.html"

    tab_values = [
        dict(attrs)["data-tab"]
        for tag, attrs in parser.elements
        if tag == "button" and "data-tab" in dict(attrs)
    ]
    assert tab_values == ["canaries", "leaks", "access", "comms", "steps"]

    script_srcs = _extract_script_srcs(parser)
    assert len(script_srcs) == len(set(script_srcs)), f"duplicate script tags in index.html: {script_srcs}"

    for core_script in CORE_ORDERED_SCRIPTS:
        assert (DEMO_DIR / core_script).is_file(), f"missing core script on disk: {core_script}"
        assert core_script in script_srcs, f"missing core script in index.html: {core_script}"

    engine_idx = script_srcs.index("engine.js")
    scene_idx = script_srcs.index("scene.js")
    game_idx = script_srcs.index("game.js")
    assert engine_idx < scene_idx < game_idx, (
        f"core scripts must load in order engine.js -> scene.js -> game.js, got: {script_srcs}"
    )
    assert game_idx == len(script_srcs) - 1, f"game.js must boot last after all bundles: {script_srcs}"

    assert (DEMO_DIR / "chatter.js").is_file(), "chatter.js must exist on disk"
    for bundle_rel in TRACKED_BUNDLE_SCRIPTS:
        if (DEMO_DIR / bundle_rel).is_file():
            assert bundle_rel in script_srcs, (
                f"present-on-disk bundle {bundle_rel} must be loaded by index.html"
            )
        if bundle_rel in script_srcs:
            assert script_srcs.index(bundle_rel) < engine_idx, (
                f"{bundle_rel} must load before engine.js in index.html, got: {script_srcs}"
            )


@pytest.mark.parametrize("force_synthetic", [False, True])
def test_pre_decision_spoiler_isolation_across_every_case(force_synthetic: bool) -> None:
    res = _run_shell_sandbox(
        r"""
        const caseSelect = document.getElementById("case-select");
        const btnNext = document.getElementById("btn-next-case");
        const revealPanel = document.getElementById("reveal-panel");
        const roster = document.getElementById("suspect-roster");
        const dossier = document.getElementById("dossier-card");
        const stageFallback = document.getElementById("stage-fallback");
        const statusPill = document.getElementById("case-status-pill");
        const evidenceTabs = document.getElementById("evidence-tabs");
        const evidenceList = document.getElementById("evidence-list");
        const stageCanvas = getPrimaryCanvas();

        const optionCount = caseSelect.children.length;
        const perCaseChecks = [];

        for (let idx = 0; idx < optionCount; idx += 1) {
          if (idx > 0) {
            btnNext.click();
          }
          const chips = roster.querySelectorAll(".suspect-chip");
          const suspectInspections = [];
          for (const chip of chips) {
            chip.click();
            suspectInspections.push({
              rosterText: roster.textContent,
              rosterPills: roster.querySelectorAll(".pill").map((p) => p.textContent),
              rosterMoleClassCount: roster.querySelectorAll(".is-mole-revealed").length,
              dossierText: dossier.textContent,
              dossierPills: dossier.querySelectorAll(".pill").map((p) => p.textContent)
            });
          }

          if (stageCanvas) {
            stageCanvas.click({ clientX: 800, clientY: 130 });
          }

          const tabTexts = {};
          for (const tabKey of ["canaries", "leaks", "access", "comms", "steps"]) {
            const tabBtn = evidenceTabs.querySelector(`[data-tab="${tabKey}"]`);
            tabBtn.click();
            tabTexts[tabKey] = evidenceList.textContent;
          }

          const frameTexts = currentFrameTextStrings();
          perCaseChecks.push({
            selectedValue: caseSelect.value,
            statusText: statusPill.textContent,
            revealHidden: revealPanel.hidden,
            revealChildCount: revealPanel.children.length,
            revealText: revealPanel.textContent,
            fallbackHidden: stageFallback.hidden,
            fallbackText: stageFallback.textContent,
            chipCount: chips.length,
            suspectInspections,
            tabTexts,
            hasPodsSealedBanner: frameTexts.includes("STATUS: PODS SEALED"),
            hasLockedPods: frameTexts.includes("[LOCKED]") && frameTexts.includes("SEALED UNTIL CALL"),
            frameHasRightOrWrong: frameTexts.includes("RIGHT") || frameTexts.includes("WRONG"),
            frameHasRevealedBanner: frameTexts.includes("STATUS: CASE REVEALED"),
            frameHasMoleSpotlight: frameTexts.some((t) => t.startsWith("MOLE "))
          });
        }

        const cumulativeCanvasTexts = allCanvasTextStrings();
        return {
          hasEngine: Boolean(window.OutThinkEngine),
          hasScene: Boolean(window.OutThinkScene),
          hasChatter: Boolean(window.OUTTHINK_CHATTER && typeof window.getOutthinkChatter === "function"),
          canvasMounted: Boolean(stageCanvas && stageCanvas.width === 960 && stageCanvas.height === 520),
          optionCount,
          perCaseChecks,
          everDrewRight: cumulativeCanvasTexts.includes("RIGHT"),
          everDrewWrong: cumulativeCanvasTexts.includes("WRONG"),
          everDrewCaseRevealed: cumulativeCanvasTexts.includes("STATUS: CASE REVEALED"),
          everDrewMoleSpotlight: cumulativeCanvasTexts.some((t) => t.startsWith("MOLE "))
        };
        """,
        force_synthetic=force_synthetic,
    )

    assert res["hasEngine"] is True
    assert res["hasScene"] is True
    assert res["hasChatter"] is True
    assert res["canvasMounted"] is True
    assert res["optionCount"] >= (3 if force_synthetic else 1)

    assert res["everDrewRight"] is False
    assert res["everDrewWrong"] is False
    assert res["everDrewCaseRevealed"] is False
    assert res["everDrewMoleSpotlight"] is False

    for idx, check in enumerate(res["perCaseChecks"]):
        assert check["selectedValue"] == str(idx)
        assert check["statusText"] == "AWAITING CALL"
        assert check["revealHidden"] is True
        assert check["revealChildCount"] == 0
        assert check["revealText"] == ""
        assert check["fallbackHidden"] is True
        assert "MOLE" not in check["fallbackText"]
        assert check["chipCount"] >= 2
        assert check["hasPodsSealedBanner"] is True
        assert check["hasLockedPods"] is True
        assert check["frameHasRightOrWrong"] is False
        assert check["frameHasRevealedBanner"] is False
        assert check["frameHasMoleSpotlight"] is False

        for snap in check["suspectInspections"]:
            assert snap["rosterMoleClassCount"] == 0
            assert "MOLE" not in snap["rosterPills"]
            assert "MOLE" not in snap["dossierPills"]
            assert "CONFIRMED MOLE" not in snap["dossierPills"]
            assert re.search(r"\bMOLE\b", snap["rosterText"]) is None
            assert re.search(r"\bMOLE\b", snap["dossierText"]) is None

        if force_synthetic and idx == 0:
            joined_tabs = "\n".join(check["tabTexts"].values())
            assert "POST_DECISION_FUTURE_LEAK" not in joined_tabs
            assert "POST_DECISION_FUTURE_LOG" not in joined_tabs
            assert "POST_DECISION_FUTURE_COMM" not in joined_tabs
            assert "POST_DECISION_FUTURE_STEP" not in joined_tabs
            assert "can_future" not in joined_tabs


def test_interactive_tabs_highlight_filter_and_roster_dossier_transitions() -> None:
    res = _run_shell_sandbox(
        r"""
        const evidenceTabs = document.getElementById("evidence-tabs");
        const evidenceList = document.getElementById("evidence-list");
        const btnHighlight = document.getElementById("btn-highlight-suspects");
        const highlightSummary = document.getElementById("highlight-summary");
        const btnFilter = document.getElementById("btn-filter-suspect");
        const roster = document.getElementById("suspect-roster");
        const dossier = document.getElementById("dossier-card");
        const dossierClearance = document.getElementById("dossier-clearance");
        const btnAccuse = document.getElementById("btn-accuse");
        const stageCanvas = getPrimaryCanvas();

        const tabOrder = ["canaries", "leaks", "access", "comms", "steps"];
        const tabSnapshots = {};
        for (const key of tabOrder) {
          const btn = evidenceTabs.querySelector(`[data-tab="${key}"]`);
          btn.click();
          const activeButtons = evidenceTabs
            .querySelectorAll("[data-tab]")
            .filter((b) => b.classList.contains("is-active") && b.getAttribute("aria-selected") === "true")
            .map((b) => b.getAttribute("data-tab"));
          tabSnapshots[key] = {
            activeButtons,
            cardCount: evidenceList.querySelectorAll(".ev-card").length,
            text: evidenceList.textContent
          };
        }

        stageCanvas.click({ clientX: 520, clientY: 40 });
        const tabAfterCanvasPropClick = evidenceTabs
          .querySelector(".is-active")
          .getAttribute("data-tab");

        const counts = {
          canaries: document.getElementById("count-canaries").textContent,
          leaks: document.getElementById("count-leaks").textContent,
          access: document.getElementById("count-access").textContent,
          comms: document.getElementById("count-comms").textContent,
          steps: document.getElementById("count-steps").textContent
        };

        const highlightBefore = {
          pressed: btnHighlight.getAttribute("aria-pressed"),
          active: btnHighlight.classList.contains("is-active"),
          highlightedChips: roster.querySelectorAll(".is-canary-highlight").length
        };
        btnHighlight.click();
        const highlightOn = {
          pressed: btnHighlight.getAttribute("aria-pressed"),
          active: btnHighlight.classList.contains("is-active"),
          summary: highlightSummary.textContent,
          highlightedIds: roster
            .querySelectorAll(".is-canary-highlight")
            .map((c) => c.textContent)
        };
        btnHighlight.click();
        const highlightOff = {
          pressed: btnHighlight.getAttribute("aria-pressed"),
          active: btnHighlight.classList.contains("is-active"),
          summary: highlightSummary.textContent,
          highlightedChips: roster.querySelectorAll(".is-canary-highlight").length
        };

        const rosterSelections = [];
        const initialChips = roster.querySelectorAll(".suspect-chip");
        for (let i = 0; i < initialChips.length; i += 1) {
          const currentChips = roster.querySelectorAll(".suspect-chip");
          currentChips[i].click();
          const selectedChips = roster
            .querySelectorAll(".suspect-chip")
            .filter((c) => c.classList.contains("is-selected") && c.getAttribute("aria-selected") === "true");
          rosterSelections.push({
            selectedCount: selectedChips.length,
            accuseText: btnAccuse.textContent,
            idName: dossier.querySelector(".dossier-id-name").textContent,
            roleDept: dossier.querySelector(".dossier-role-dept").textContent,
            clearance: dossierClearance.textContent,
            persona: dossier.querySelector(".dossier-persona").textContent,
            dossierText: dossier.textContent,
            canvasFocusDraws: currentFrameTextStrings().filter((t) => t.startsWith("FOCUS: "))
          });
        }

        roster.querySelectorAll(".suspect-chip")[1].click();
        evidenceTabs.querySelector('[data-tab="access"]').click();
        const accessUnfilteredCount = evidenceList.querySelectorAll(".ev-card").length;

        btnFilter.click();
        const filterOnE02 = {
          pressed: btnFilter.getAttribute("aria-pressed"),
          active: btnFilter.classList.contains("is-active"),
          btnText: btnFilter.textContent,
          accessCount: evidenceList.querySelectorAll(".ev-card").length,
          accessText: evidenceList.textContent
        };

        roster.querySelectorAll(".suspect-chip")[0].click();
        const filterOnEliminatedE01 = {
          btnText: btnFilter.textContent,
          accessCardCount: evidenceList.querySelectorAll(".ev-card").length,
          emptyText: evidenceList.textContent
        };

        roster.querySelectorAll(".suspect-chip")[2].click();
        evidenceTabs.querySelector('[data-tab="comms"]').click();
        const filterOnE03Comms = {
          btnText: btnFilter.textContent,
          commsCardCount: evidenceList.querySelectorAll(".ev-card").length,
          commsText: evidenceList.textContent
        };

        btnFilter.click();
        const filterOffComms = {
          pressed: btnFilter.getAttribute("aria-pressed"),
          active: btnFilter.classList.contains("is-active"),
          btnText: btnFilter.textContent,
          commsCardCount: evidenceList.querySelectorAll(".ev-card").length
        };

        return {
          counts,
          tabSnapshots,
          tabAfterCanvasPropClick,
          highlightBefore,
          highlightOn,
          highlightOff,
          rosterSelections,
          accessUnfilteredCount,
          filterOnE02,
          filterOnEliminatedE01,
          filterOnE03Comms,
          filterOffComms
        };
        """,
        force_synthetic=True,
    )

    assert res["counts"] == {
        "canaries": "1",
        "leaks": "1",
        "access": "2",
        "comms": "2",
        "steps": "2",
    }

    tabs = res["tabSnapshots"]
    assert tabs["canaries"]["activeButtons"] == ["canaries"]
    assert tabs["canaries"]["cardCount"] == 1
    assert "can_alpha" in tabs["canaries"]["text"] and "Variant A [LEAKED]" in tabs["canaries"]["text"]

    assert tabs["leaks"]["activeButtons"] == ["leaks"]
    assert tabs["leaks"]["cardCount"] == 1
    assert "Fingerprinted clause A surfaced verbatim" in tabs["leaks"]["text"]

    assert tabs["access"]["activeButtons"] == ["access"]
    assert tabs["access"]["cardCount"] == 2
    assert "AFTER HOURS" in tabs["access"]["text"] and "export doc_board_mna" in tabs["access"]["text"]

    assert tabs["comms"]["activeButtons"] == ["comms"]
    assert tabs["comms"]["cardCount"] == 2
    assert "interview" in tabs["comms"]["text"] and "backup window" in tabs["comms"]["text"]

    assert tabs["steps"]["activeButtons"] == ["steps"]
    assert tabs["steps"]["cardCount"] == 2
    assert "plant_canary" in tabs["steps"]["text"] and "inspect_logs" in tabs["steps"]["text"]

    assert res["tabAfterCanvasPropClick"] == "comms"

    assert res["highlightBefore"] == {"pressed": "false", "active": False, "highlightedChips": 0}
    assert res["highlightOn"]["pressed"] == "true"
    assert res["highlightOn"]["active"] is True
    assert "Highlighting 1 canary-hit suspect(s): e03" in res["highlightOn"]["summary"]
    assert len(res["highlightOn"]["highlightedIds"]) == 1
    assert "e03 Noora Laine" in res["highlightOn"]["highlightedIds"][0]
    assert res["highlightOff"] == {
        "pressed": "false",
        "active": False,
        "summary": "Click a station or suspect badge to inspect dossier",
        "highlightedChips": 0,
    }

    sels = res["rosterSelections"]
    assert len(sels) == 3
    assert sels[0]["selectedCount"] == 1
    assert sels[0]["accuseText"] == "ACCUSE e01 NOW"
    assert sels[0]["idName"] == "e01 - Aino Salmi"
    assert "RULED OUT" in sels[0]["dossierText"]
    assert sels[0]["clearance"] == "Clearance: exec"
    assert sels[0]["canvasFocusDraws"] == ["FOCUS: e01"]

    assert sels[1]["accuseText"] == "ACCUSE e02 NOW"
    assert sels[1]["idName"] == "e02 - Timo Korhonen"
    assert "ACTIVE SUSPECT" in sels[1]["dossierText"]
    assert sels[1]["canvasFocusDraws"] == ["FOCUS: e02"]

    assert sels[2]["accuseText"] == "ACCUSE e03 NOW"
    assert sels[2]["idName"] == "e03 - Noora Laine"
    assert "can_alpha:A" in sels[2]["dossierText"]
    assert "Compiled partner valuation annexes" in sels[2]["persona"]
    assert sels[2]["canvasFocusDraws"] == ["FOCUS: e03"]

    assert res["accessUnfilteredCount"] == 2
    assert res["filterOnE02"]["pressed"] == "true"
    assert res["filterOnE02"]["active"] is True
    assert res["filterOnE02"]["btnText"] == "Filter: e02 Only"
    assert res["filterOnE02"]["accessCount"] == 1
    assert "doc_infra_audit" in res["filterOnE02"]["accessText"]
    assert "doc_board_mna" not in res["filterOnE02"]["accessText"]

    assert res["filterOnEliminatedE01"]["btnText"] == "Filter: e01 Only"
    assert res["filterOnEliminatedE01"]["accessCardCount"] == 0
    assert "No audit access logs for current filter." in res["filterOnEliminatedE01"]["emptyText"]

    assert res["filterOnE03Comms"]["btnText"] == "Filter: e03 Only"
    assert res["filterOnE03Comms"]["commsCardCount"] == 1
    assert "annex export" in res["filterOnE03Comms"]["commsText"]

    assert res["filterOffComms"] == {
        "pressed": "false",
        "active": False,
        "btnText": "Filter: All Staff",
        "commsCardCount": 2,
    }


def test_navigation_accuse_vs_hold_fire_scoreboard_deltas_and_clean_reset() -> None:
    res = _run_shell_sandbox(
        r"""
        const caseSelect = document.getElementById("case-select");
        const btnPrev = document.getElementById("btn-prev-case");
        const btnNext = document.getElementById("btn-next-case");
        const btnReset = document.getElementById("btn-reset-scores");
        const btnAccuse = document.getElementById("btn-accuse");
        const btnHoldFire = document.getElementById("btn-hold-fire");
        const roster = document.getElementById("suspect-roster");
        const dossier = document.getElementById("dossier-card");
        const revealPanel = document.getElementById("reveal-panel");
        const statusPill = document.getElementById("case-status-pill");
        const caseTitle = document.getElementById("case-title");
        const caseCompany = document.getElementById("case-company");
        const caseTier = document.getElementById("case-tier-badge");
        const stageCanvas = getPrimaryCanvas();

        const nav0 = {
          value: caseSelect.value,
          title: caseTitle.textContent,
          company: caseCompany.textContent,
          tier: caseTier.textContent,
          prevDisabled: btnPrev.disabled,
          nextDisabled: btnNext.disabled
        };

        btnNext.click();
        const nav1 = {
          value: caseSelect.value,
          title: caseTitle.textContent,
          company: caseCompany.textContent,
          tier: caseTier.textContent,
          prevDisabled: btnPrev.disabled,
          nextDisabled: btnNext.disabled
        };

        btnNext.click();
        const nav2 = {
          value: caseSelect.value,
          title: caseTitle.textContent,
          company: caseCompany.textContent,
          tier: caseTier.textContent,
          prevDisabled: btnPrev.disabled,
          nextDisabled: btnNext.disabled
        };

        btnPrev.click();
        const navBack1 = {
          value: caseSelect.value,
          title: caseTitle.textContent
        };

        caseSelect.value = "0";
        caseSelect.dispatchEvent({ type: "change", bubbles: true });
        const navJump0 = {
          value: caseSelect.value,
          title: caseTitle.textContent,
          prevDisabled: btnPrev.disabled
        };

        const sbInitial = readScoreboardSnapshot();

        roster.querySelectorAll(".suspect-chip")[2].click();
        btnAccuse.click();
        stageCanvas.click({ clientX: 800, clientY: 130 });

        const afterCase0Accuse = {
          revealHidden: revealPanel.hidden,
          revealText: revealPanel.textContent,
          focusedPodCount: revealPanel.querySelectorAll(".is-pod-focused").length,
          focusedPodKey: revealPanel.querySelector(".is-pod-focused")
            ? revealPanel.querySelector(".is-pod-focused").getAttribute("data-level-key")
            : null,
          carbonStripCount: revealPanel.querySelectorAll(".carbon-strip").length,
          rosterMoleCount: roster.querySelectorAll(".is-mole-revealed").length,
          rosterText: roster.textContent,
          dossierText: dossier.textContent,
          accuseDisabled: btnAccuse.disabled,
          holdDisabled: btnHoldFire.disabled,
          statusText: statusPill.textContent,
          option0Text: caseSelect.children[0].textContent,
          canvasTexts: currentFrameTextStrings(),
          scoreboard: readScoreboardSnapshot()
        };

        btnNext.click();
        const case1PreDecision = {
          revealHidden: revealPanel.hidden,
          revealText: revealPanel.textContent,
          rosterMoleCount: roster.querySelectorAll(".is-mole-revealed").length,
          accuseDisabled: btnAccuse.disabled,
          holdDisabled: btnHoldFire.disabled,
          canvasTexts: currentFrameTextStrings()
        };

        btnHoldFire.click();
        const afterCase1HoldFire = {
          revealHidden: revealPanel.hidden,
          revealText: revealPanel.textContent,
          accuseDisabled: btnAccuse.disabled,
          holdDisabled: btnHoldFire.disabled,
          statusText: statusPill.textContent,
          canvasTexts: currentFrameTextStrings(),
          scoreboard: readScoreboardSnapshot()
        };

        btnNext.click();
        roster.querySelectorAll(".suspect-chip")[0].click();
        btnAccuse.click();
        const afterCase2WrongAccuse = {
          revealHidden: revealPanel.hidden,
          revealText: revealPanel.textContent,
          statusText: statusPill.textContent,
          scoreboard: readScoreboardSnapshot()
        };

        btnReset.click();
        const afterReset = {
          revealHidden: revealPanel.hidden,
          revealChildCount: revealPanel.children.length,
          revealText: revealPanel.textContent,
          rosterMoleCount: roster.querySelectorAll(".is-mole-revealed").length,
          rosterText: roster.textContent,
          dossierText: dossier.textContent,
          accuseDisabled: btnAccuse.disabled,
          holdDisabled: btnHoldFire.disabled,
          statusText: statusPill.textContent,
          doneOptionsCount: caseSelect.children.filter((o) => o.textContent.includes("[DONE]")).length,
          canvasTexts: currentFrameTextStrings(),
          scoreboard: readScoreboardSnapshot()
        };

        return {
          nav0,
          nav1,
          nav2,
          navBack1,
          navJump0,
          sbInitial,
          afterCase0Accuse,
          case1PreDecision,
          afterCase1HoldFire,
          afterCase2WrongAccuse,
          afterReset
        };
        """,
        force_synthetic=True,
    )

    assert res["nav0"] == {
        "value": "0",
        "title": "Hard Seed 1: Board Valuation Trap",
        "company": "Northstar Bio",
        "tier": "HARD",
        "prevDisabled": True,
        "nextDisabled": False,
    }
    assert res["nav1"] == {
        "value": "1",
        "title": "Medium Seed 2: Split Variant Ambiguity",
        "company": "Helios Assay",
        "tier": "MEDIUM",
        "prevDisabled": False,
        "nextDisabled": False,
    }
    assert res["nav2"] == {
        "value": "2",
        "title": "Easy Seed 3: Sprint Briefing Partition",
        "company": "Vanguard Labs",
        "tier": "EASY",
        "prevDisabled": False,
        "nextDisabled": True,
    }
    assert res["navBack1"] == {"value": "1", "title": "Medium Seed 2: Split Variant Ambiguity"}
    assert res["navJump0"] == {
        "value": "0",
        "title": "Hard Seed 1: Board Valuation Trap",
        "prevDisabled": True,
    }

    sb0 = {t["actor"]: t for t in res["sbInitial"]}
    assert list(sb0.keys()) == ["YOU (JUDGE)", "SOLVER", "minimal", "low", "medium", "high", "xhigh"]
    assert sb0["YOU (JUDGE)"]["points"] == "0.00"
    assert sb0["YOU (JUDGE)"]["acc"] == "No calls"
    assert "0/3" in sb0["YOU (JUDGE)"]["pills"]

    c0 = res["afterCase0Accuse"]
    assert c0["revealHidden"] is False
    assert "OPTIMAL ACCUSATION" in c0["revealText"]
    assert "YOUR CALL: ACCUSE e03" in c0["revealText"]
    assert "Score +0.72" in c0["revealText"]
    assert "True Mole: e03 (Noora Laine)" in c0["revealText"]
    assert "Chased after-hours SRE noise before canary triggered." in c0["revealText"]
    assert c0["focusedPodCount"] == 1
    assert c0["focusedPodKey"] == "minimal"
    assert c0["carbonStripCount"] == 1
    assert c0["rosterMoleCount"] == 1
    assert "MOLE" in c0["rosterText"]
    assert "CONFIRMED MOLE" in c0["dossierText"]
    assert c0["accuseDisabled"] is True and c0["holdDisabled"] is True
    assert c0["statusText"] == "OPTIMAL ACCUSATION"
    assert c0["option0Text"].startswith("[DONE] 1.")
    assert "STATUS: CASE REVEALED" in c0["canvasTexts"]
    assert "MOLE e03" in c0["canvasTexts"]
    assert "RIGHT" in c0["canvasTexts"] and "WRONG" in c0["canvasTexts"]

    sb1 = {t["actor"]: t for t in c0["scoreboard"]}
    assert sb1["YOU (JUDGE)"]["points"] == "+0.72"
    assert sb1["YOU (JUDGE)"]["acc"] == "100.0% acc"
    assert "1/3" in sb1["YOU (JUDGE)"]["pills"]
    assert sb1["SOLVER"]["points"] == "+0.72"
    assert sb1["minimal"]["points"] == "-1.00"
    assert sb1["minimal"]["beaten"] is True
    assert "OUT-THOUGHT" in sb1["minimal"]["pills"]
    assert sb1["low"]["points"] == "+0.44"
    assert sb1["low"]["beaten"] is True

    c1_pre = res["case1PreDecision"]
    assert c1_pre["revealHidden"] is True
    assert c1_pre["revealText"] == ""
    assert c1_pre["rosterMoleCount"] == 0
    assert c1_pre["accuseDisabled"] is False and c1_pre["holdDisabled"] is False
    assert "STATUS: PODS SEALED" in c1_pre["canvasTexts"]
    assert "RIGHT" not in c1_pre["canvasTexts"] and "WRONG" not in c1_pre["canvasTexts"]

    c1 = res["afterCase1HoldFire"]
    assert c1["revealHidden"] is False
    assert "OPTIMAL HOLD FIRE" in c1["revealText"]
    assert "YOUR CALL: HOLD FIRE" in c1["revealText"]
    assert "Score +0.38" in c1["revealText"]
    assert "True Mole: e05 (Sanna Virta)" in c1["revealText"]
    assert c1["accuseDisabled"] is True and c1["holdDisabled"] is True
    assert c1["statusText"] == "OPTIMAL HOLD FIRE"
    assert "STATUS: CASE REVEALED" in c1["canvasTexts"]
    assert "MOLE e05" in c1["canvasTexts"]

    sb2 = {t["actor"]: t for t in c1["scoreboard"]}
    assert sb2["YOU (JUDGE)"]["points"] == "+1.10"
    assert sb2["YOU (JUDGE)"]["acc"] == "100.0% acc"
    assert "2/3" in sb2["YOU (JUDGE)"]["pills"]
    assert sb2["SOLVER"]["points"] == "+1.10"

    c2 = res["afterCase2WrongAccuse"]
    assert c2["revealHidden"] is False
    assert "FALSE ACCUSATION (-1.00)" in c2["revealText"]
    assert "Score -1.00" in c2["revealText"]
    assert "True Mole: e04 (Elina Ranta)" in c2["revealText"]
    assert c2["statusText"] == "FALSE ACCUSATION (-1.00)"

    sb3 = {t["actor"]: t for t in c2["scoreboard"]}
    assert sb3["YOU (JUDGE)"]["points"] == "+0.10"
    assert sb3["YOU (JUDGE)"]["acc"] == "66.7% acc"
    assert "3/3" in sb3["YOU (JUDGE)"]["pills"]

    rst = res["afterReset"]
    assert rst["revealHidden"] is True
    assert rst["revealChildCount"] == 0
    assert rst["revealText"] == ""
    assert rst["rosterMoleCount"] == 0
    assert "MOLE" not in rst["rosterText"]
    assert "MOLE" not in rst["dossierText"]
    assert rst["accuseDisabled"] is False and rst["holdDisabled"] is False
    assert rst["statusText"] == "AWAITING CALL"
    assert rst["doneOptionsCount"] == 0
    assert "STATUS: PODS SEALED" in rst["canvasTexts"]
    assert "[LOCKED]" in rst["canvasTexts"]
    assert "RIGHT" not in rst["canvasTexts"] and "WRONG" not in rst["canvasTexts"]

    sb_rst = {t["actor"]: t for t in rst["scoreboard"]}
    assert sb_rst["YOU (JUDGE)"]["points"] == "0.00"
    assert sb_rst["YOU (JUDGE)"]["acc"] == "No calls"
    assert "0/3" in sb_rst["YOU (JUDGE)"]["pills"]
    for lv_key in ("minimal", "low", "medium", "high", "xhigh"):
        assert sb_rst[lv_key]["points"] == "0.00"
        assert sb_rst[lv_key]["acc"] == "$0.0000"
        assert sb_rst[lv_key]["beaten"] is False
        assert "OUT-THOUGHT" not in sb_rst[lv_key]["pills"]


def test_chatter_counterfactual_non_leak_parity_inside_booted_shell() -> None:
    res = _run_shell_sandbox(
        r"""
        const ds = window.OutThinkEngine.loadDataset();
        const parityChecks = ds.cases.map((c) => {
          const outA = window.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            true_mole: "e01",
            mole: "e01",
            suspects: c.suspects
          });
          const outB = window.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            true_mole: "e99",
            mole: "e99",
            suspects: c.suspects
          });
          return {
            equalJson: JSON.stringify(outA) === JSON.stringify(outB),
            chatterLen: outA.chatter.length,
            rumorLen: outA.rumors.length,
            provenanceClean: outA.provenance.all_clean === true && outA.provenance.leaks_detected === 0
          };
        });
        const footerText = document.getElementById("provenance-footer").textContent;
        return { parityChecks, footerText };
        """,
        force_synthetic=True,
    )

    assert len(res["parityChecks"]) == 3
    for item in res["parityChecks"]:
        assert item["equalJson"] is True
        assert item["chatterLen"] >= 1
        assert item["rumorLen"] >= 1
        assert item["provenanceClean"] is True
    assert "0 live API calls in browser" in res["footerText"]
    assert "docs/demo/ASSETS.md" in res["footerText"]


def test_file_hygiene_zero_comments_zero_dashes_zero_coauthor_and_keyless() -> None:
    self_path = Path(__file__).resolve()
    self_src = self_path.read_text(encoding="utf-8")

    assert HASH_CHAR not in self_src, "zero hash characters or comments allowed in this test file"
    assert EM_DASH not in self_src, "em dash forbidden"
    assert EN_DASH not in self_src, "en dash forbidden"
    assert FIG_DASH not in self_src, "figure dash forbidden"
    assert HORIZ_BAR not in self_src, "horizontal bar forbidden"
    assert CO_AUTHORED_TOKEN not in self_src, "co-author trailer forbidden"

    py_comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(self_src).readline) if tok.type == tokenize.COMMENT
    ]
    assert py_comments == []
    assert _find_js_comments(JS_DOM_CANVAS_SANDBOX) == []

    tree = ast.parse(self_src)
    forbidden_modules = {"genai", "google", "openai", "anthropic", "requests", "httpx", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_mod = alias.name.split(".")[0]
                assert top_mod not in forbidden_modules, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_mod = node.module.split(".")[0]
            assert top_mod not in forbidden_modules, f"forbidden import from: {node.module}"

    rules = _load_protected_rules()
    assert not _matches_protected_rule(self_path.relative_to(ROOT).as_posix(), rules)
