from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
ENGINE_PATH = DEMO_DIR / "engine.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
BLOCK_COMMENT_CLOSE = STAR + SLASH

TEXT_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".html",
    ".css",
    ".json",
    ".md",
    ".txt",
    ".svg",
}


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


def _run_engine_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    stdin_json = json.dumps(payload if payload is not None else {})
    wrapper = (
        'const fs = require("fs");\n'
        "const Engine = require(process.env.OUTTHINK_ENGINE_PATH);\n"
        'const PAYLOAD = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
        input=stdin_json,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS runtime failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


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
                hits.append((line, LINE_COMMENT))
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


def test_exports_window_binding_and_bootstrap_vs_fallback_selection():
    assert ENGINE_PATH.is_file()
    res = _run_engine_js(
        """
        globalThis.window = {};
        delete require.cache[require.resolve(process.env.OUTTHINK_ENGINE_PATH)];
        const Fresh = require(process.env.OUTTHINK_ENGINE_PATH);
        const boot = Fresh.loadDataset({ data: undefined, fallbackData: undefined });

        globalThis.window.OUTTHINK_FALLBACK_DATA = {
          cases: [{ id: "fb-1", tier: "easy", seed: 12, valueAtDecision: 0.8, trueMole: "e02" }]
        };
        const fromWindowFallback = Fresh.loadDataset();

        globalThis.window.OUTTHINK_DATA = {
          cases: [{ id: "pri-1", tier: "hard", seed: 7, value_at_decision: 0.64, true_mole: "e05" }]
        };
        const fromWindowPrimary = Fresh.loadDataset();

        return {
          sameRef: globalThis.window.OutThinkEngine === Fresh,
          bootFlag: boot.isBootstrapFallback,
          bootSource: boot.source,
          bootCount: boot.cases.length,
          bootMole: boot.cases[0].true_mole,
          fbFlag: fromWindowFallback.isBootstrapFallback,
          fbIsFallback: fromWindowFallback.isFallback,
          fbId: fromWindowFallback.cases[0].id,
          priFlag: fromWindowPrimary.isBootstrapFallback,
          priIsFallback: fromWindowPrimary.isFallback,
          priId: fromWindowPrimary.cases[0].id
        };
        """
    )
    assert res["sameRef"] is True
    assert res["bootFlag"] is True
    assert res["bootSource"] == "bootstrap"
    assert res["bootCount"] == 1
    assert res["bootMole"] == "e03"
    assert res["fbFlag"] is False
    assert res["fbIsFallback"] is True
    assert res["fbId"] == "fb-1"
    assert res["priFlag"] is False
    assert res["priIsFallback"] is False
    assert res["priId"] == "pri-1"


def test_schema_variants_and_canonical_case_normalization():
    payload = {
        "casesWrap": {
            "cases": [
                {
                    "caseId": "camel-hard-5",
                    "headline": "Midnight Readout Leak",
                    "difficulty": "HARD",
                    "worldSeed": 5,
                    "companyName": "Helios Genomics",
                    "decisionDay": 6,
                    "decisionStep": 11,
                    "valueAtDecision": 0.6,
                    "trueMole": "e04",
                    "employees": [
                        {
                            "employeeId": "e01",
                            "fullName": "Sami Virtanen",
                            "department": "Infra",
                            "jobTitle": "SRE",
                            "accessLevel": "elevated",
                            "isEliminated": True,
                        },
                        {
                            "employeeId": "e04",
                            "fullName": "Noora Laine",
                            "department": "Strategy",
                            "jobTitle": "Director",
                            "accessLevel": "exec",
                            "isEliminated": False,
                        },
                    ],
                    "canaryTraps": [
                        {
                            "canaryId": "can_9",
                            "docId": "doc_mna",
                            "dayPlanted": 4,
                            "variants": {"v1": ["e01"], "v2": ["e04"]},
                        }
                    ],
                    "leakEvents": [
                        {
                            "leakedDay": 5,
                            "docId": "doc_mna",
                            "canaryId": "can_9",
                            "leakedVariant": "v2",
                            "outlet": "press_tip",
                            "headline": "Merger terms leaked verbatim.",
                        }
                    ],
                    "accessLogs": [
                        {
                            "day": 5,
                            "employeeId": "e04",
                            "documentId": "doc_mna",
                            "afterHours": True,
                            "event": "download",
                        },
                        {
                            "day": 5,
                            "employeeId": "e04",
                            "documentId": "doc_mna",
                            "afterHours": True,
                            "event": "export",
                        },
                    ],
                    "messages": [
                        {
                            "day": 5,
                            "type": "slack",
                            "from": "e04",
                            "to": "e01",
                            "subject": "board deck",
                            "body": "Send me the latest valuation annex.",
                        }
                    ],
                    "interviews": [
                        {
                            "day": 6,
                            "employee": "e04",
                            "topic": "after-hours export",
                            "response": "I was preparing slides for Monday.",
                        }
                    ],
                    "toolSteps": [
                        {
                            "step": 3,
                            "day": 4,
                            "action": "plant_canary",
                            "arguments": '{"doc_id":"doc_mna"}',
                            "resultSummary": "Planted v1/v2 trap.",
                        }
                    ],
                    "referenceSolver": {
                        "beliefs": {"e01": 0.04, "e04": 0.96},
                        "finalAccused": "e04",
                        "finalDay": 6,
                        "finalScore": 0.6,
                        "correct": True,
                    },
                    "thinkingLevels": {
                        "high": {
                            "callAtT": "accuse",
                            "accused": "e04",
                            "accusedDay": 6,
                            "score": 0.6,
                            "costUsd": 0.024,
                            "thinkingTokens": 3100,
                            "inputTokens": 4200,
                            "outputTokens": 180,
                            "cachedTokens": 3000,
                            "apiCalls": 12,
                            "runId": "run-high-5",
                        },
                        "minimal": {
                            "callAtT": "accuse",
                            "accused": "e01",
                            "accusedDay": 3,
                            "score": -1.0,
                            "costUsd": 0.003,
                            "thinkingTokens": 80,
                            "inputTokens": 1500,
                            "outputTokens": 90,
                            "cachedTokens": 900,
                            "apiCalls": 4,
                            "runId": "run-min-5",
                        },
                    },
                }
            ]
        },
        "scenariosWrap": {"scenarios": [{"id": "sc-1", "tier": "medium", "seed": 2, "true_mole": "e02"}]},
        "decisionPointsWrap": {"decision_points": [{"id": "dp-1", "tier": "easy", "seed": 1, "true_mole": "e01"}]},
        "arrayWrap": [{"id": "arr-1", "tier": "hard", "seed": 9, "true_mole": "e07"}],
    }

    res = _run_engine_js(
        """
        const c1 = Engine.loadDataset({ data: PAYLOAD.casesWrap }).cases[0];
        const c2 = Engine.loadDataset({ data: PAYLOAD.scenariosWrap }).cases[0];
        const c3 = Engine.loadDataset({ data: PAYLOAD.decisionPointsWrap }).cases[0];
        const c4 = Engine.loadDataset({ data: PAYLOAD.arrayWrap }).cases[0];
        return { c1, ids: [c1.id, c2.id, c3.id, c4.id] };
        """,
        payload,
    )

    assert res["ids"] == ["camel-hard-5", "sc-1", "dp-1", "arr-1"]
    c1 = res["c1"]
    expected_keys = {
        "id",
        "title",
        "tier",
        "seed",
        "company",
        "decision_day",
        "decision_step",
        "value_at_decision",
        "suspects",
        "canaries",
        "leaks",
        "access_logs",
        "comms",
        "tool_steps",
        "true_mole",
        "solver",
        "thinking_levels",
    }
    assert set(c1.keys()) == expected_keys
    assert c1["tier"] == "hard" and c1["seed"] == 5 and c1["company"] == "Helios Genomics"
    assert c1["decision_day"] == 6 and c1["decision_step"] == 11
    assert c1["value_at_decision"] == pytest.approx(0.6)
    assert c1["true_mole"] == "e04"

    s_by_id = {s["id"]: s for s in c1["suspects"]}
    assert s_by_id["e01"]["eliminated"] is True and s_by_id["e01"]["canary_hits"] == 0
    assert s_by_id["e04"]["canary_hits"] == 1 and s_by_id["e04"]["after_hours_count"] == 2

    assert c1["canaries"][0]["leaked_variant"] == "v2"
    assert len(c1["comms"]) == 2
    assert c1["comms"][1]["kind"] == "interview"
    assert c1["tool_steps"][0]["args"] == {"doc_id": "doc_mna"}

    slv = c1["solver"]
    assert slv["top_suspect"] == "e04"
    assert slv["top_prob"] == pytest.approx(0.96)
    assert slv["break_even_prob"] == pytest.approx(0.625)
    assert slv["recommended_call"] == "accuse"

    assert [lv["thinking_level"] for lv in c1["thinking_levels"]] == ["minimal", "high"]


def test_annotations_and_personas_merging_precedence():
    payload = {
        "data": {
            "cases": [
                {
                    "id": "case-hard-18",
                    "tier": "hard",
                    "seed": 18,
                    "value_at_decision": 0.46,
                    "true_mole": "e27",
                    "suspects": [
                        {"id": "e27", "name": "Kari Niemi"},
                        {"id": "e29", "name": "Elina Ranta"},
                    ],
                    "thinking_levels": [
                        {"thinking_level": "minimal", "run_id": "run-min-18", "accused": "e29", "score": -1.0},
                        {"thinking_level": "low", "run_id": "run-low-18", "accused": "e29", "score": -1.0},
                        {"thinking_level": "medium", "run_id": "run-med-18", "accused": "e29", "score": -1.0},
                        {"thinking_level": "high", "run_id": "run-high-18", "accused": "e27", "score": 0.46},
                    ],
                }
            ]
        },
        "annotations": {
            "run-min-18": {
                "failure_tag": "run_specific_rush",
                "analyst_quote": "Matched directly by run_id.",
            },
            "hard:18:low": {
                "failure_tag": "below_breakeven_guess",
                "analyst_quote": "Matched by tier:seed:thinking_level.",
            },
            "hard:18": {
                "failure_tag": "world_level_trap",
                "analyst_quote": "Matched by tier:seed fallback.",
            },
            "case-hard-18": {
                "failure_tag": "case_id_fallback_tag",
                "analyst_quote": "Matched by case.id.",
            },
        },
        "personas": {
            "hard:18": {
                "e27": "Quietly hoarding partner term sheets after 22:00.",
                "e29": {"persona_note": "Vocal critic of leadership deadlines in group chat."},
            }
        },
    }

    res = _run_engine_js(
        """
        const ds = Engine.loadDataset(PAYLOAD);
        const c = ds.cases[0];
        const caseOnly = Engine.loadDataset({
          data: {
            cases: [{
              id: "case-only-99",
              tier: "medium",
              seed: 99,
              true_mole: "e01",
              thinking_levels: [{ thinking_level: "xhigh", run_id: "unlisted", accused: "e02", score: -1.0 }]
            }]
          },
          annotations: {
            "case-only-99": { failure_tag: "from_case_id", analyst_quote: "Case-ID quote." }
          },
          personas: [
            { tier: "medium", seed: 99, id: "e01", persona_note: "Array persona note." }
          ]
        }).cases[0];
        return { c, caseOnly };
        """,
        payload,
    )

    c = res["c"]
    by_lv = {lv["thinking_level"]: lv for lv in c["thinking_levels"]}
    assert by_lv["minimal"]["failure_tag"] == "run_specific_rush"
    assert by_lv["minimal"]["analyst_quote"] == "Matched directly by run_id."
    assert by_lv["low"]["failure_tag"] == "below_breakeven_guess"
    assert by_lv["low"]["analyst_quote"] == "Matched by tier:seed:thinking_level."
    assert by_lv["medium"]["failure_tag"] == "world_level_trap"
    assert by_lv["medium"]["analyst_quote"] == "Matched by tier:seed fallback."

    suspects = {s["id"]: s for s in c["suspects"]}
    assert suspects["e27"]["persona_note"] == "Quietly hoarding partner term sheets after 22:00."
    assert suspects["e29"]["persona_note"] == "Vocal critic of leadership deadlines in group chat."

    co = res["caseOnly"]
    assert co["thinking_levels"][0]["failure_tag"] == "from_case_id"
    assert co["thinking_levels"][0]["analyst_quote"] == "Case-ID quote."


def test_break_even_math_and_evaluate_call_matrix():
    res = _run_engine_js(
        """
        const be1 = Engine.computeBreakEvenProb(1.0);
        const be0 = Engine.computeBreakEvenProb(0.0);
        const be025 = Engine.computeBreakEvenProb(0.25);
        const beWithHold = Engine.computeBreakEvenProb(1.0, { ev_hold_fire: 0.2 });

        const pinnedCase = Engine.normalizeCase({
          id: "pinned-1",
          tier: "hard",
          seed: 3,
          value_at_decision: 0.76,
          true_mole: "e05",
          solver: {
            posterior: { e05: 0.99, e02: 0.01 },
            top_suspect: "e05",
            top_prob: 0.99,
            recommended_call: "accuse",
            final_accused: "e05",
            final_score: 0.76,
            correct: true
          },
          thinking_levels: [
            { thinking_level: "low", accused: "e02", correct: false, score: -1.0, cost_usd: 0.004, thinking_tokens: 300 }
          ]
        });

        const ambigCase = Engine.normalizeCase({
          id: "ambig-5",
          tier: "hard",
          seed: 5,
          value_at_decision: 0.16,
          true_mole: "e27",
          solver: {
            posterior: { e27: 0.51, e14: 0.49 },
            top_suspect: "e27",
            top_prob: 0.51,
            break_even_prob: 0.8621,
            ev_accuse_top: -0.4084,
            ev_hold_fire: 0.34,
            recommended_call: "hold_fire",
            final_accused: "e27",
            final_day: 9,
            final_score: 0.34,
            correct: true
          },
          thinking_levels: [
            { thinking_level: "high", accused: "e27", correct: true, score: 0.16, cost_usd: 0.031, thinking_tokens: 4100 }
          ]
        });

        return {
          be1,
          be0,
          be025,
          beWithHold,
          rightAccuse: Engine.evaluateCall(pinnedCase, { action: "accuse", suspectId: "e05" }),
          wrongAccuse: Engine.evaluateCall(pinnedCase, { action: "accuse", suspectId: "e02" }),
          delayedHold: Engine.evaluateCall(pinnedCase, { action: "hold_fire" }),
          optimalHold: Engine.evaluateCall(ambigCase, { action: "hold_fire" }),
          luckyAccuse: Engine.evaluateCall(ambigCase, { action: "accuse", suspectId: "e27" })
        };
        """
    )

    assert res["be1"] == pytest.approx(0.5)
    assert res["be0"] == pytest.approx(1.0)
    assert res["be025"] == pytest.approx(0.8)
    assert res["beWithHold"] == pytest.approx(0.6)

    right = res["rightAccuse"]
    assert right["correct"] is True and right["optimal"] is True
    assert right["score"] == pytest.approx(0.76)
    assert right["suspectId"] == "e05" and right["trueMole"] == "e05"
    assert len(right["levelComparisons"]) == 1

    wrong = res["wrongAccuse"]
    assert wrong["correct"] is False and wrong["optimal"] is False
    assert wrong["score"] == pytest.approx(-1.0)

    delayed = res["delayedHold"]
    assert delayed["correct"] is False and delayed["optimal"] is False
    assert delayed["score"] == pytest.approx(0.64)

    opt_hold = res["optimalHold"]
    assert opt_hold["correct"] is True and opt_hold["optimal"] is True
    assert opt_hold["score"] == pytest.approx(0.34)

    lucky = res["luckyAccuse"]
    assert lucky["correct"] is True and lucky["optimal"] is False
    assert lucky["score"] == pytest.approx(0.16)


def test_scoreboard_aggregation_across_cases_and_cost_totals():
    res = _run_engine_js(
        """
        const ds = Engine.loadDataset({
          data: {
            cases: [
              {
                id: "c1",
                tier: "hard",
                seed: 1,
                value_at_decision: 0.8,
                true_mole: "e01",
                solver: {
                  top_suspect: "e01",
                  top_prob: 0.97,
                  recommended_call: "accuse",
                  final_score: 0.8,
                  correct: true
                },
                thinking_levels: [
                  { thinking_level: "minimal", accused: "e02", correct: false, score: -1.0, cost_usd: 0.0025, thinking_tokens: 100 },
                  { thinking_level: "low", accused: "e02", correct: false, score: -1.0, cost_usd: 0.005, thinking_tokens: 400 },
                  { thinking_level: "medium", accused: "e01", correct: true, score: 0.8, cost_usd: 0.011, thinking_tokens: 1200 },
                  { thinking_level: "high", accused: "e01", correct: true, score: 0.8, cost_usd: 0.025, thinking_tokens: 2800 },
                  { thinking_level: "xhigh", accused: "e01", correct: true, score: 0.8, cost_usd: 0.045, thinking_tokens: 5200 }
                ]
              },
              {
                id: "c2",
                tier: "hard",
                seed: 2,
                value_at_decision: 0.5,
                true_mole: "e04",
                solver: {
                  top_suspect: "e04",
                  top_prob: 0.48,
                  break_even_prob: 0.6667,
                  ev_hold_fire: 0.42,
                  recommended_call: "hold_fire",
                  final_score: 0.42,
                  correct: true
                },
                thinking_levels: [
                  { thinking_level: "minimal", accused: "e03", correct: false, score: -1.0, cost_usd: 0.0025, thinking_tokens: 120 },
                  { thinking_level: "low", accused: "e04", correct: true, score: 0.5, cost_usd: 0.006, thinking_tokens: 450 },
                  { thinking_level: "medium", accused: "e03", correct: false, score: -1.0, cost_usd: 0.012, thinking_tokens: 1300 },
                  { thinking_level: "high", call_at_t: "hold_fire", accused: "e04", correct: true, score: 0.42, cost_usd: 0.027, thinking_tokens: 3000 },
                  { thinking_level: "xhigh", call_at_t: "hold_fire", accused: "e04", correct: true, score: 0.42, cost_usd: 0.05, thinking_tokens: 5800 }
                ]
              },
              {
                id: "c3",
                tier: "hard",
                seed: 3,
                value_at_decision: 0.7,
                true_mole: "e06",
                solver: {
                  top_suspect: "e06",
                  top_prob: 0.96,
                  recommended_call: "accuse",
                  final_score: 0.7,
                  correct: true
                },
                thinking_levels: [
                  { thinking_level: "minimal", accused: "e01", correct: false, score: -1.0, cost_usd: 0.003, thinking_tokens: 90 },
                  { thinking_level: "high", accused: "e06", correct: true, score: 0.7, cost_usd: 0.028, thinking_tokens: 3200 }
                ]
              }
            ]
          }
        });

        const sb = Engine.createScoreboard();
        const r1 = Engine.evaluateCall(ds.cases[0], { action: "accuse", suspectId: "e01" });
        const r2 = Engine.evaluateCall(ds.cases[1], { action: "hold_fire" });
        const r3Wrong = Engine.evaluateCall(ds.cases[2], { action: "accuse", suspectId: "e02" });

        sb.record("c1", r1, ds.cases[0]);
        sb.record("c2", r2, ds.cases[1]);
        sb.record("c3", r3Wrong, ds.cases[2]);

        const summaryAfter3 = sb.getSummary();
        const c2Lookup = sb.getCaseResult("c2");
        const missingLookup = sb.getCaseResult("c999");

        const afterReset = sb.reset();
        return { summaryAfter3, c2Lookup, missingLookup, afterReset };
        """
    )

    s = res["summaryAfter3"]
    assert s["casesPlayed"] == 3
    assert s["judge"]["scoreSum"] == pytest.approx(0.22)
    assert s["judge"]["meanScore"] == pytest.approx(0.0733, abs=1e-4)
    assert s["judge"]["rightCount"] == 2
    assert s["judge"]["optimalCount"] == 2
    assert s["judge"]["costUsd"] == 0

    assert s["solver"]["scoreSum"] == pytest.approx(1.92)
    assert s["solver"]["meanScore"] == pytest.approx(0.64)
    assert s["solver"]["rightCount"] == 3

    by_lv = s["byLevel"]
    assert set(by_lv.keys()) >= {"minimal", "low", "medium", "high", "xhigh"}

    assert by_lv["minimal"]["count"] == 3
    assert by_lv["minimal"]["scoreSum"] == pytest.approx(-3.0)
    assert by_lv["minimal"]["rightCount"] == 0
    assert by_lv["minimal"]["accuracy"] == pytest.approx(0.0)
    assert by_lv["minimal"]["totalCostUsd"] == pytest.approx(0.008)
    assert by_lv["minimal"]["totalThinkingTokens"] == 310
    assert by_lv["minimal"]["judgeOutscoredCount"] == 2

    assert by_lv["high"]["count"] == 3
    assert by_lv["high"]["scoreSum"] == pytest.approx(1.92)
    assert by_lv["high"]["meanScore"] == pytest.approx(0.64)
    assert by_lv["high"]["rightCount"] == 3
    assert by_lv["high"]["accuracy"] == pytest.approx(1.0)
    assert by_lv["high"]["totalCostUsd"] == pytest.approx(0.08)
    assert by_lv["high"]["totalThinkingTokens"] == 9000
    assert by_lv["high"]["judgeOutscoredCount"] == 0

    assert by_lv["medium"]["count"] == 2
    assert by_lv["medium"]["judgeOutscoredCount"] == 1

    assert res["c2Lookup"]["score"] == pytest.approx(0.42)
    assert res["missingLookup"] is None
    assert res["afterReset"]["casesPlayed"] == 0
    assert res["afterReset"]["judge"]["scoreSum"] == 0


def test_extract_annotation_fields_quote_fallback_chain_and_episodes_index():
    payload = {
        "chain": [
            {
                "primary_failure_tag": "ignored_delay",
                "analyst_quote": "Direct analyst quote wins.",
                "quote": "Secondary quote.",
                "quotes": [{"quote": "Q0 quote", "note": "Q0 note"}],
                "tags": {"ignored_delay": {"why": "Tag why"}},
                "worst_regret_step": {"why": "Worst step why"},
            },
            {
                "failure_tag": "premature_accusation",
                "quote": "Plain quote wins second.",
                "quotes": [{"quote": "Q0 quote", "note": "Q0 note"}],
                "tags": {"premature_accusation": {"why": "Tag why"}},
                "worst_regret_step": {"why": "Worst step why"},
            },
            {
                "primary_failure_tag": "premature_accusation",
                "quotes": [{"quote": "t76 d9 accuse(employee=e02) | REGRET 1.419", "note": "Q0 note"}],
                "tags": {"premature_accusation": {"why": "Tag why"}},
                "worst_regret_step": {"why": "Worst step why"},
            },
            {
                "primary_failure_tag": "uninformative_canary",
                "quotes": [{"quote": "", "note": "Single variant contained all remaining suspects."}],
                "tags": {"uninformative_canary": {"why": "Tag why"}},
                "worst_regret_step": {"why": "Worst step why"},
            },
            {
                "primary_failure_tag": "premature_accusation",
                "quotes": [],
                "tags": {
                    "premature_accusation": {
                        "count": 1,
                        "regret": 1.419383,
                        "why": "accused before the evidence was decisive (solver top-suspect belief 0.15 < 0.6)",
                    }
                },
                "worst_regret_step": {"why": "Worst step why"},
            },
            {
                "primary_failure_tag": None,
                "quotes": [],
                "tags": {},
                "worst_regret_step": {
                    "t": 40,
                    "day": 8,
                    "action": "plant_canary",
                    "regret": 0.034917,
                    "why": "planted duplicate canary after suspect pool already narrowed",
                },
            },
        ],
        "annotations": {
            "generated_from_git_sha": "587167429aabe85fdf53786cb78c47b272ea0325",
            "summary": {"total_episodes": 3, "episodes_with_quotes": 3},
            "episodes": {
                "gemini-4-carbon/low/hard/1": {
                    "key": "gemini-4-carbon/low/hard/1",
                    "pipe_key": "gemini-4-carbon|low|hard|1",
                    "model": "gemini-4-carbon",
                    "level": "low",
                    "tier": "hard",
                    "seed": 1,
                    "run_id": "ladder:ladder-v14:gemini-4-carbon/low/hard/1",
                    "ledger_calls_recorded": 153,
                    "regret_total": 0.17008,
                    "primary_failure_tag": "ignored_delay",
                    "quotes": [
                        {
                            "quote": "Day 9 posterior 97.7% already cleared break-even; held fire until day 17.",
                            "source_kind": "episode_step",
                        }
                    ],
                },
                "gemini-3.1-flash-lite/minimal/medium/0": {
                    "key": "gemini-3.1-flash-lite/minimal/medium/0",
                    "pipe_key": "gemini-3.1-flash-lite|minimal|medium|0",
                    "model": "gemini-3.1-flash-lite",
                    "level": "minimal",
                    "tier": "medium",
                    "seed": 0,
                    "run_id": "ladder:ladder-v14:gemini-3.1-flash-lite/minimal/medium/0",
                    "ledger_calls_recorded": 77,
                    "regret_total": 1.463591,
                    "primary_failure_tag": "premature_accusation",
                    "quotes": [],
                    "tags": {},
                    "worst_regret_step": {
                        "t": 76,
                        "day": 9,
                        "action": "accuse",
                        "why": "accused before the evidence was decisive (solver top-suspect belief 0.15 < 0.6)",
                    },
                },
            },
            "by_scenario": {
                "hard/1": {
                    "gemini-4-carbon": {
                        "low": "gemini-4-carbon/low/hard/1",
                        "high": {
                            "primary_failure_tag": None,
                            "ledger_calls_recorded": 99,
                            "regret_total": 0.0,
                            "quotes": [{"note": "Pinned e33 on day 9 right above break-even."}],
                        },
                    }
                },
                "medium/5": [
                    {
                        "model": "gemini-4-argon",
                        "level": "low",
                        "primary_failure_tag": "over_restriction",
                        "quotes": [{"quote": "Restricted canary to 2 suspects too early."}],
                    }
                ],
            },
            "by_run_id": {
                "alias-run-carbon-low": "gemini-4-carbon/low/hard/1",
                "alias-run-inline": {
                    "primary_failure_tag": "no_accusation",
                    "worst_regret_step": {"why": "ran out of horizon without accusing"},
                },
            },
            "by_case": {
                "alias-case-0": {
                    "minimal": "gemini-3.1-flash-lite/minimal/medium/0",
                }
            },
        },
    }

    res = _run_engine_js(
        """
        const chainOut = PAYLOAD.chain.map(item => Engine.extractAnnotationFields(item));
        const idx = Engine.buildAnnotationsIndex(PAYLOAD.annotations);
        const byRun = idx.byRunId["ladder:ladder-v14:gemini-4-carbon/low/hard/1"];
        const bySlash = idx.byKey["gemini-4-carbon/low/hard/1"];
        const byPipe = idx.byKey["gemini-4-carbon|low|hard|1"];
        const byModelTSL = idx.byModelTierSeedLevel["gemini-4-carbon:hard:1:low"];
        const byTSL = idx.byTierSeedLevel["hard:1:low"];
        const byScenInline = idx.byModelTierSeedLevel["gemini-4-carbon:hard:1:high"];
        const byScenArr = idx.byModelTierSeedLevel["gemini-4-argon:medium:5:low"];
        const byAliasRun = idx.byRunId["alias-run-carbon-low"];
        const byAliasInline = idx.byRunId["alias-run-inline"];

        const caseViaAliases = Engine.normalizeCase(
          {
            id: "alias-case-0",
            model: "gemini-3.1-flash-lite",
            tier: "medium",
            seed: 999,
            true_mole: "e05",
            thinking_levels: [
              { thinking_level: "minimal", run_id: "unmatched-id", accused: "e02", score: -1.0 },
              { thinking_level: "low", run_id: "alias-run-carbon-low", accused: "e33", score: 0.29 },
              { thinking_level: "high", run_id: "alias-run-inline", accused: null, score: 0.0 }
            ]
          },
          idx
        );
        return {
          chainOut,
          byRun,
          bySlash,
          byPipe,
          byModelTSL,
          byTSL,
          byScenInline,
          byScenArr,
          byAliasRun,
          byAliasInline,
          caseViaAliases
        };
        """,
        payload,
    )

    chain_out = res["chainOut"]
    assert [x["analyst_quote"] for x in chain_out] == [
        "Direct analyst quote wins.",
        "Plain quote wins second.",
        "t76 d9 accuse(employee=e02) | REGRET 1.419",
        "Single variant contained all remaining suspects.",
        "accused before the evidence was decisive (solver top-suspect belief 0.15 < 0.6)",
        "planted duplicate canary after suspect pool already narrowed",
    ]
    assert chain_out[0]["failure_tag"] == "ignored_delay"
    assert chain_out[1]["failure_tag"] == "premature_accusation"
    assert chain_out[5]["failure_tag"] is None

    for resolved in (res["byRun"], res["bySlash"], res["byPipe"], res["byModelTSL"], res["byTSL"], res["byAliasRun"]):
        assert resolved["failure_tag"] == "ignored_delay"
        assert resolved["analyst_quote"] == "Day 9 posterior 97.7% already cleared break-even; held fire until day 17."
        assert resolved["ledger_calls"] == 153
        assert resolved["regret_total"] == pytest.approx(0.17008)

    assert res["byScenInline"]["analyst_quote"] == "Pinned e33 on day 9 right above break-even."
    assert res["byScenInline"]["ledger_calls"] == 99
    assert res["byScenArr"]["failure_tag"] == "over_restriction"
    assert res["byAliasInline"]["failure_tag"] == "no_accusation"
    assert res["byAliasInline"]["analyst_quote"] == "ran out of horizon without accusing"

    by_lv = {lv["thinking_level"]: lv for lv in res["caseViaAliases"]["thinking_levels"]}
    assert by_lv["minimal"]["failure_tag"] == "premature_accusation"
    assert by_lv["minimal"]["analyst_quote"].startswith("accused before the evidence was decisive")
    assert by_lv["minimal"]["ledger_calls"] == 77
    assert by_lv["low"]["failure_tag"] == "ignored_delay"
    assert by_lv["high"]["failure_tag"] == "no_accusation"


def test_lossless_afac6bbd_cases_and_0b565235_annotations_resolution():
    afac_case_array_levels = {
        "id": "carbon-hard-1",
        "title": "Hard Seed 1: Carbon Ladder Split",
        "model": "gemini-4-carbon",
        "anchor_level": "high",
        "tier": "hard",
        "seed": 1,
        "company": "Northstar Bio",
        "decision_day": 9,
        "decision_step": 44,
        "value_at_decision": 0.71,
        "suspects": [
            {"id": "e10", "name": "Aino Salmi", "dept": "Legal", "role": "Counsel", "eliminated": True, "canary_hits": 0, "after_hours_count": 1, "persona_note": "Tracks external counsel redlines."},
            {"id": "e33", "name": "Mikko Lahti", "dept": "Ops", "role": "Lead", "eliminated": False, "canary_hits": 2, "after_hours_count": 3, "persona_note": "Exports late status packs."},
        ],
        "canaries": [{"canary_id": "c1", "doc_id": "doc_1", "day_planted": 6, "variants": [{"variant": "A", "recipients": ["e33"]}], "leaked_variant": "A"}],
        "leaks": [{"day": 8, "doc_id": "doc_1", "canary_id": "c1", "leaked_variant": "A", "channel": "press", "summary": "Variant A leaked."}],
        "access_logs": [{"day": 8, "employee": "e33", "doc_id": "doc_1", "after_hours": True, "action": "export"}],
        "comms": [{"day": 8, "kind": "chat", "speaker": "e33", "target": "all", "topic": "sync", "text": "Uploading deck."}],
        "tool_steps": [{"t": 1, "day": 6, "tool": "plant_canary", "args": {"doc_id": "doc_1"}, "summary": "Planted c1."}],
        "true_mole": "e33",
        "solver": {
            "posterior": {"e10": 0.023129, "e33": 0.976871},
            "top_suspect": "e33",
            "top_prob": 0.9769,
            "break_even_prob": 0.5848,
            "ev_accuse_top": 0.6705,
            "ev_hold_fire": 0.69,
            "recommended_call": "accuse",
            "final_accused": "e33",
            "final_day": 9,
            "final_score": 0.71,
            "correct": True,
        },
        "thinking_levels": [
            {
                "key": "low",
                "model": "gemini-4-carbon",
                "thinking_level": "low",
                "level": "low",
                "tier": "hard",
                "seed": 1,
                "call_at_t": "hold_fire",
                "accused": "e33",
                "accused_day": 17,
                "end_reason": "accused",
                "correct": True,
                "score": 0.29,
                "cost_usd": 1.050836,
                "thinking_tokens": 467,
                "input_tokens": 2252359,
                "output_tokens": 4227,
                "cached_tokens": 2011033,
                "calls": 103,
                "ledger_calls": 153,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/low/hard/1",
                "failure_tag": "ignored_delay",
                "analyst_quote": "gemini-4-carbon (low) held fire past day 9 despite posterior 97.7% exceeding break-even 58.5%, accusing e33 on day 17 for +0.29.",
                "regret_total": 0.4,
            },
            {
                "key": "high",
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "level": "high",
                "tier": "hard",
                "seed": 1,
                "call_at_t": "accuse",
                "accused": "e33",
                "accused_day": 9,
                "end_reason": "accused",
                "correct": True,
                "score": 0.71,
                "cost_usd": 1.596177,
                "thinking_tokens": 40681,
                "input_tokens": 1120400,
                "output_tokens": 3190,
                "cached_tokens": 980100,
                "calls": 64,
                "ledger_calls": 99,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/high/hard/1",
                "failure_tag": None,
                "analyst_quote": "gemini-4-carbon (high) accused e33 on day 9 at 97.7% posterior for +0.71.",
                "regret_total": 0.0,
            },
        ],
        "cross_model_carbon": [
            {
                "model": "gemini-4-carbon",
                "thinking_level": "low",
                "accused": "e33",
                "accused_day": 17,
                "cost_usd": 1.050836,
                "thinking_tokens": 467,
                "score": 0.29,
                "correct": True,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/low/hard/1",
            },
            {
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "accused": "e33",
                "accused_day": 9,
                "cost_usd": 1.596177,
                "thinking_tokens": 40681,
                "score": 0.71,
                "correct": True,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/high/hard/1",
            },
        ],
        "ladder_matrix": {
            "gemini-3.1-flash-lite": {
                "high": {
                    "score": -1.0,
                    "correct": False,
                    "accused": "e10",
                    "final_day": 6,
                    "end_reason": "accused",
                    "thinking_tokens": 4467,
                    "cost_usd": 0.071437,
                    "run_id": "ladder:ladder-v14:gemini-3.1-flash-lite/high/hard/1",
                }
            },
            "gemini-4-carbon": {
                "low": {
                    "score": 0.29,
                    "correct": True,
                    "accused": "e33",
                    "final_day": 17,
                    "end_reason": "accused",
                    "thinking_tokens": 467,
                    "cost_usd": 1.050836,
                    "run_id": "ladder:ladder-v14:gemini-4-carbon/low/hard/1",
                },
                "high": {
                    "score": 0.71,
                    "correct": True,
                    "accused": "e33",
                    "final_day": 9,
                    "end_reason": "accused",
                    "thinking_tokens": 40681,
                    "cost_usd": 1.596177,
                    "run_id": "ladder:ladder-v14:gemini-4-carbon/high/hard/1",
                },
            },
        },
    }

    afac_case_map_levels_unannotated = {
        "id": "flash-lite-hard-4",
        "title": "Hard Seed 4: Flash-Lite Ladder",
        "model": "gemini-3.1-flash-lite",
        "anchor_level": "minimal",
        "tier": "hard",
        "seed": 4,
        "company": "Helios Bio",
        "decision_day": 6,
        "decision_step": 22,
        "value_at_decision": 0.73,
        "true_mole": "e38",
        "thinking_levels": {
            "minimal": {
                "model": "gemini-3.1-flash-lite",
                "call_at_t": "accuse",
                "accused": "e29",
                "accused_day": 6,
                "correct": False,
                "score": -1.0,
                "cost_usd": 0.0412,
                "thinking_tokens": 0,
                "calls": 34,
                "run_id": "ladder:ladder-v14:gemini-3.1-flash-lite/minimal/hard/4",
            },
            "high": {
                "model": "gemini-3.1-flash-lite",
                "call_at_t": "hold_fire",
                "accused": "e38",
                "accused_day": 11,
                "correct": True,
                "score": 0.73,
                "cost_usd": 0.0891,
                "thinking_tokens": 5120,
                "calls": 39,
                "run_id": "missing-run-id-uses-model-tier-seed-level",
            },
        },
        "cross_model_carbon": [
            {
                "model": "gemini-4-carbon",
                "thinking_level": "high",
                "accused": "e38",
                "accused_day": 9,
                "cost_usd": 1.42,
                "thinking_tokens": 38900,
                "score": 0.73,
                "correct": True,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/high/hard/4",
            }
        ],
        "ladder_matrix": {
            "gemini-3.1-flash-lite": {
                "minimal": {"score": -1.0, "correct": False, "accused": "e29", "final_day": 6}
            }
        },
    }

    real_shaped_annotations = {
        "generated_from_git_sha": "587167429aabe85fdf53786cb78c47b272ea0325",
        "episodes": {
            "gemini-3.1-flash-lite/minimal/hard/4": {
                "key": "gemini-3.1-flash-lite/minimal/hard/4",
                "pipe_key": "gemini-3.1-flash-lite|minimal|hard/4",
                "model": "gemini-3.1-flash-lite",
                "level": "minimal",
                "tier": "hard",
                "seed": 4,
                "run_id": "ladder:ladder-v14:gemini-3.1-flash-lite/minimal/hard/4",
                "ledger_calls_recorded": 50,
                "regret_total": 1.73,
                "primary_failure_tag": "premature_accusation",
                "quotes": [
                    {
                        "quote": "t33 d6 accuse(employee=e29) -> accused e29 | REGRET 1.730 [premature_accusation]",
                        "source_kind": "atlas_v2",
                        "note": "Accused e29 at 15.2% posterior.",
                    }
                ],
            },
            "gemini-3.1-flash-lite/high/hard/4": {
                "key": "gemini-3.1-flash-lite/high/hard/4",
                "pipe_key": "gemini-3.1-flash-lite|high|hard|4",
                "model": "gemini-3.1-flash-lite",
                "level": "high",
                "tier": "hard",
                "seed": 4,
                "run_id": "ladder:ladder-v14:gemini-3.1-flash-lite/high/hard/4",
                "ledger_calls_recorded": 42,
                "regret_total": 0.0,
                "primary_failure_tag": "uninformative_canary",
                "quotes": [],
                "tags": {},
                "worst_regret_step": {
                    "t": 18,
                    "day": 4,
                    "action": "plant_canary",
                    "why": "canary split overlapped prior variant recipients",
                },
            },
            "gemini-4-carbon/low/hard/1": {
                "key": "gemini-4-carbon/low/hard/1",
                "pipe_key": "gemini-4-carbon|low|hard|1",
                "model": "gemini-4-carbon",
                "level": "low",
                "tier": "hard",
                "seed": 1,
                "run_id": "ladder:ladder-v14:gemini-4-carbon/low/hard/1",
                "ledger_calls_recorded": 153,
                "regret_total": 0.17008,
                "primary_failure_tag": None,
                "quotes": [{"quote": "Fallback episode quote for carbon low."}],
            },
        },
        "by_scenario": {
            "hard/4": {
                "gemini-3.1-flash-lite": {
                    "minimal": "gemini-3.1-flash-lite/minimal/hard/4",
                    "high": "gemini-3.1-flash-lite/high/hard/4",
                }
            },
            "hard/1": {
                "gemini-4-carbon": {
                    "low": "gemini-4-carbon/low/hard/1",
                }
            },
        },
    }

    res = _run_engine_js(
        """
        const ds = Engine.loadDataset({
          data: { cases: [PAYLOAD.cArr, PAYLOAD.cMap] },
          annotations: PAYLOAD.ann
        });
        return { cases: ds.cases };
        """,
        {
            "cArr": afac_case_array_levels,
            "cMap": afac_case_map_levels_unannotated,
            "ann": real_shaped_annotations,
        },
    )

    c0, c1 = res["cases"]
    assert c0["model"] == "gemini-4-carbon"
    assert c0["anchor_level"] == "high"
    assert c0["cross_model_carbon"] == afac_case_array_levels["cross_model_carbon"]
    assert c0["ladder_matrix"] == afac_case_array_levels["ladder_matrix"]
    assert c0["solver"]["posterior"]["e33"] == pytest.approx(0.976871)

    c0_lvs = {lv["thinking_level"]: lv for lv in c0["thinking_levels"]}
    assert c0_lvs["low"]["model"] == "gemini-4-carbon"
    assert c0_lvs["low"]["call_at_t"] == "hold_fire"
    assert c0_lvs["low"]["accused_day"] == 17
    assert c0_lvs["low"]["ledger_calls"] == 153
    assert c0_lvs["low"]["regret_total"] == pytest.approx(0.4)
    assert c0_lvs["low"]["failure_tag"] == "ignored_delay"
    assert c0_lvs["low"]["analyst_quote"].startswith("gemini-4-carbon (low) held fire past day 9")

    assert c0_lvs["high"]["call_at_t"] == "accuse"
    assert c0_lvs["high"]["accused_day"] == 9
    assert c0_lvs["high"]["ledger_calls"] == 99
    assert c0_lvs["high"]["regret_total"] == pytest.approx(0.0)
    assert c0_lvs["high"]["failure_tag"] is None

    assert c1["model"] == "gemini-3.1-flash-lite"
    assert c1["anchor_level"] == "minimal"
    assert c1["cross_model_carbon"] == afac_case_map_levels_unannotated["cross_model_carbon"]
    assert c1["ladder_matrix"] == afac_case_map_levels_unannotated["ladder_matrix"]

    c1_lvs = {lv["thinking_level"]: lv for lv in c1["thinking_levels"]}
    assert [lv["thinking_level"] for lv in c1["thinking_levels"]] == ["minimal", "high"]
    assert c1_lvs["minimal"]["model"] == "gemini-3.1-flash-lite"
    assert c1_lvs["minimal"]["call_at_t"] == "accuse"
    assert c1_lvs["minimal"]["accused_day"] == 6
    assert c1_lvs["minimal"]["ledger_calls"] == 50
    assert c1_lvs["minimal"]["regret_total"] == pytest.approx(1.73)
    assert c1_lvs["minimal"]["failure_tag"] == "premature_accusation"
    assert c1_lvs["minimal"]["analyst_quote"].startswith("t33 d6 accuse(employee=e29)")

    assert c1_lvs["high"]["model"] == "gemini-3.1-flash-lite"
    assert c1_lvs["high"]["call_at_t"] == "hold_fire"
    assert c1_lvs["high"]["accused_day"] == 11
    assert c1_lvs["high"]["ledger_calls"] == 42
    assert c1_lvs["high"]["regret_total"] == pytest.approx(0.0)
    assert c1_lvs["high"]["failure_tag"] == "uninformative_canary"
    assert c1_lvs["high"]["analyst_quote"] == "canary split overlapped prior variant recipients"

    live_cases_json = ROOT / "results" / "gemini" / "out_think_gemini.json"
    live_ann_json = ROOT / "results" / "gemini" / "outthink_annotations.json"
    if live_cases_json.is_file():
        raw_live_data = json.loads(live_cases_json.read_text(encoding="utf-8"))
        raw_live_ann = json.loads(live_ann_json.read_text(encoding="utf-8")) if live_ann_json.is_file() else None
        live_res = _run_engine_js(
            """
            const ds = Engine.loadDataset({ data: PAYLOAD.data, annotations: PAYLOAD.ann });
            return { count: ds.count, cases: ds.cases };
            """,
            {"data": raw_live_data, "ann": raw_live_ann},
        )
        assert live_res["count"] == len(raw_live_data["cases"])
        for orig_c, norm_c in zip(raw_live_data["cases"], live_res["cases"]):
            assert norm_c["model"] == orig_c["model"]
            assert norm_c["anchor_level"] == orig_c["anchor_level"]
            assert norm_c["cross_model_carbon"] == orig_c["cross_model_carbon"]
            assert norm_c["ladder_matrix"] == orig_c["ladder_matrix"]
            orig_by_lv = {x["thinking_level"]: x for x in orig_c["thinking_levels"]}
            norm_by_lv = {x["thinking_level"]: x for x in norm_c["thinking_levels"]}
            assert set(orig_by_lv.keys()) == set(norm_by_lv.keys())
            for k, orig_lv in orig_by_lv.items():
                norm_lv = norm_by_lv[k]
                assert norm_lv["model"] == orig_lv["model"]
                assert norm_lv["call_at_t"] == orig_lv["call_at_t"]
                assert norm_lv["accused_day"] == orig_lv["accused_day"]
                assert norm_lv["ledger_calls"] == orig_lv["ledger_calls"]
                assert norm_lv["regret_total"] == pytest.approx(orig_lv["regret_total"])
                if orig_lv.get("failure_tag") is not None:
                    assert norm_lv["failure_tag"] == orig_lv["failure_tag"]
                assert norm_lv["analyst_quote"] == orig_lv["analyst_quote"]


def test_js_comment_scanner_catches_line_and_block_comments():
    clean_sample = (
        'const url = "https://example.org/a/b";\n'
        'const esc = s.replace(/"/g, "&quot;").replace(/\'/g, "&apos;");\n'
        'const ratio = a / b + c / d;\n'
    )
    assert _find_js_comments(clean_sample) == []
    assert _find_js_comments('s.replace(/"/g, "q"); ' + LINE_COMMENT + " trailing\n") == [(1, LINE_COMMENT)]
    assert _find_js_comments("const y = 2;\n" + BLOCK_COMMENT_OPEN + " block " + BLOCK_COMMENT_CLOSE) == [
        (2, BLOCK_COMMENT_OPEN)
    ]


def test_demo_and_test_hygiene_dashes_comments_and_protected_paths():
    assert DEMO_DIR.is_dir()
    demo_files = sorted(p for p in DEMO_DIR.rglob("*") if p.is_file())
    assert ENGINE_PATH in demo_files

    for path in demo_files:
        if path.suffix.lower() in TEXT_SUFFIXES:
            txt = path.read_text(encoding="utf-8")
            assert EM_DASH not in txt, f"em dash found in {path}"
            assert EN_DASH not in txt, f"en dash found in {path}"
        if path.suffix.lower() in {".js", ".mjs", ".cjs"}:
            js_txt = path.read_text(encoding="utf-8")
            assert _find_js_comments(js_txt) == [], f"JS comments found in {path}"

    self_path = Path(__file__).resolve()
    self_src = self_path.read_text(encoding="utf-8")
    assert EM_DASH not in self_src
    assert EN_DASH not in self_src
    assert HASH_CHAR not in self_src
    py_comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(self_src).readline) if tok.type == tokenize.COMMENT
    ]
    assert py_comments == []

    tree = ast.parse(self_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    rules = _load_protected_rules()
    assert rules

    checked_paths = {p.relative_to(ROOT).as_posix() for p in demo_files}
    checked_paths.add(self_path.relative_to(ROOT).as_posix())

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
