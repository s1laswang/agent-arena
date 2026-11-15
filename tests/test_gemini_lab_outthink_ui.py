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
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        "const Engine = require(process.env.OUTTHINK_ENGINE_PATH);\n"
        "const PAYLOAD = JSON.parse(process.env.OUTTHINK_TEST_PAYLOAD);\n"
        "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
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

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked_paths.add(entry)

    base_proc = subprocess.run(
        ["git", "merge-base", "origin/justSilas", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if base_proc.returncode == 0 and base_proc.stdout.strip():
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_proc.stdout.strip()}..HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_proc.returncode == 0:
            for rel in diff_proc.stdout.splitlines():
                if rel.strip():
                    checked_paths.add(rel.strip())

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
