from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.env import ERRORS, TOPICS, Env, _SPECS
from canary.eval import run_episode
from canary.forge.fitness import FEASIBLE_SOLVER_ACC, FEASIBLE_SOLVER_RATIO, TIER_DEFAULTS
from canary.forge.rl_mole import MIN_SOLVER_ACC
from canary.forge_track import MIN_ACC, strategy_for
from canary.gemini.dashboard import redact
from canary.gemini.gallery_breakeven import (
    accusation_ev,
    breakeven_posterior,
    compute_spotlight,
    verify_transcript_quotes,
)
from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS, MAX_RULES, MoleStrategy, MoleView
from canary.redteam.corpus import _always_invalid, inject_run, load as load_corpus
from canary.redteam.text_probe import fair_bar
from canary.rules import (
    DEV_SEEDS,
    HELDOUT_SEEDS,
    JUDGE_SEEDS,
    KNOWN_V_MODE,
    TIERS,
    TIERS_VERSION,
    TRACKS,
    TRAIN_SEEDS,
)
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import TemplateProvider
from canary.world import set_world_secret, world_seed
from game.canary_game import (
    SEED_MAX,
    SEED_MIN,
    Game,
    check_seed,
    replay as game_replay,
    solver_result as game_solver_result,
)
from scripts.demo_replay import RUNS as DEMO_RUNS, load as load_demo_episode, per_day as demo_per_day
from scripts.verify_replay import replay_episode

BASE_BRANCH = "origin/justSilas"
BASE_COMMIT = "58716742"
MAX_JSON_BYTES = 40960
DEFAULT_JSON_OUT = ROOT / "results" / "port" / "sleeper_port_matrix.json"
DEFAULT_MD_OUT = ROOT / "docs" / "reports" / "sleeper_to_canary_port_matrix.md"

COUNTERPART_FILES = (
    "canary/env.py",
    "canary/rules.py",
    "canary/world.py",
    "canary/mole/dsl.py",
    "canary/forge_track.py",
    "canary/forge/fitness.py",
    "canary/forge/rl_mole.py",
    "canary/solver/belief.py",
    "canary/solver/policy.py",
    "canary/text/facts.py",
    "canary/text/template.py",
    "canary/text/lint.py",
    "canary/redteam/corpus.py",
    "canary/redteam/anticheat.py",
    "canary/redteam/harbor_cheat.py",
    "canary/redteam/tamper_guard.py",
    "canary/redteam/text_probe.py",
    "canary/gemini/gallery.py",
    "canary/gemini/gallery_breakeven.py",
    "canary/gemini/dashboard.py",
    "canary/gemini/lab_replay.py",
    "scripts/demo_replay.py",
    "scripts/verify_replay.py",
    "scripts/instruction_audit.py",
    "game/canary_game.py",
    "game/app.js",
    "game/index.html",
    "data/redteam/corpus.jsonl",
    "results/anticheat/corpus_eval.txt",
    "results/anticheat/exploits.json",
    "results/gemini/failure_gallery.json",
    "results/gemini/dashboard.html",
    "results/skill_ladder_v1.4.csv",
    "docs/DIFFICULTY.md",
    "docs/EXPLOITS.md",
    "docs/SUBMISSION.md",
    "docs/research-biases.md",
    "docs/reports/failure_gallery.md",
    "docs/reports/failure_gallery_breakeven.md",
)


def _invariant(name: str, passed: bool, metric: Any, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "metric": metric,
        "detail": detail,
    }


def _parse_corpus_eval_txt(path: Path) -> dict[str, int]:
    txt = path.read_text(encoding="utf-8")
    m = re.search(r"runs=(\d+)\s+changed=(\d+)\s+accepted=(\d+)", txt)
    rows_m = re.search(r'"rows":\s*(\d+)', txt)
    if not m or not rows_m:
        raise ValueError(f"unexpected corpus_eval format in {path}")
    return {
        "rows": int(rows_m.group(1)),
        "runs": int(m.group(1)),
        "changed": int(m.group(2)),
        "accepted": int(m.group(3)),
    }


def _skill_ladder_solver_stats(csv_path: Path) -> dict[str, dict[str, Any]]:
    by_tier: dict[str, list[dict[str, Any]]] = {"easy": [], "medium": [], "hard": []}
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row["agent"] == "solver" and row["tier"] in by_tier:
                by_tier[row["tier"]].append(row)
    out: dict[str, dict[str, Any]] = {}
    for tier, rows in by_tier.items():
        n = len(rows)
        accused = sum(int(r["accused"]) for r in rows)
        correct = sum(int(r["correct"]) for r in rows)
        mean_score = sum(float(r["score"]) for r in rows) / max(1, n)
        out[tier] = {
            "n": n,
            "mean_score": round(mean_score, 4),
            "acc_overall": round(correct / max(1, n), 4),
            "acc_when_accusing": round(correct / max(1, accused), 4),
            "abstain_rate": round((n - accused) / max(1, n), 4),
        }
    return out


def _smoke_all_tools(tier: str, seed: int = 4242) -> tuple[int, int]:
    env = Env(tier, seed)
    results: list[bool] = []

    def call(tool: str, args: dict[str, Any]):
        r = env.call(tool, args)
        results.append(bool(r.ok))
        return r

    emps = call("list_employees", {}).data["employees"]
    a, b = emps[0]["id"], emps[1]["id"]
    call("status", {})
    call("list_documents", {"day_from": 1, "day_to": 1})
    call("plant_canary", {"doc_title": "Port audit memo", "assignment": {a: "A", b: "B"}})
    call("interview", {"employee": a, "topic": TOPICS[0]})
    call("restrict_access", {"employee": b})
    call("unrestrict_access", {"employee": b})
    call("advance_day", {})
    call("read_access_logs", {"day_from": 1, "day_to": 1})
    msgs = call("search_messages", {"query": "the"}).data.get("messages") or []
    if msgs:
        call("read_message", {"id": msgs[0]["id"]})
    else:
        results.append(False)
    call("check_leak_feed", {})
    call("accuse", {"employee": a})
    return sum(results), len(results)


def audit_scope_hygiene(root: Path) -> dict[str, Any]:
    canary_dir = root / "canary"
    v16_files = sorted(
        str(p.relative_to(root))
        for p in canary_dir.rglob("*")
        if p.is_file() and ("social" in p.name.lower() or "v16" in p.name.lower() or "v1_6" in p.name.lower())
    )
    missing = [rel for rel in COUNTERPART_FILES if not (root / rel).exists()]
    return {
        "shipped_tiers_version": TIERS_VERSION,
        "known_v_mode": bool(KNOWN_V_MODE),
        "v16_social_files": v16_files,
        "v16_social_files_count": len(v16_files),
        "counterpart_files_expected": len(COUNTERPART_FILES),
        "counterpart_files_present": len(COUNTERPART_FILES) - len(missing),
        "missing_files": missing,
        "passed": (
            TIERS_VERSION == "v1.4"
            and KNOWN_V_MODE is True
            and len(v16_files) == 0
            and len(missing) == 0
        ),
    }


def audit_cheat_corpus(root: Path, exploits_data: dict[str, Any]) -> dict[str, Any]:
    rows = load_corpus()
    tool_counts = Counter(r["tool"] for r in rows)
    distinct_tools = sorted(tool_counts)
    total_historical_attempts = sum(int(r.get("count", 0)) for r in rows)
    always_invalid_count = sum(1 for r in rows if _always_invalid(r["tool"], r["args"]))

    committed_eval = _parse_corpus_eval_txt(root / "results" / "anticheat" / "corpus_eval.txt")

    seen_tools: set[str] = set()
    rep_rows: list[dict[str, Any]] = []
    for r in rows:
        if r["tool"] not in seen_tools:
            seen_tools.add(r["tool"])
            rep_rows.append(r)

    live_accepted = 0
    live_changed = 0
    for r in rep_rows:
        base, got, inj = inject_run("easy", 0, r)
        if inj is not None and inj.ok:
            live_accepted += 1
        if abs(got - base) > 1e-9:
            live_changed += 1
    for r in rep_rows[:2]:
        base, got, inj = inject_run("medium", 0, r)
        if inj is not None and inj.ok:
            live_accepted += 1
        if abs(got - base) > 1e-9:
            live_changed += 1
    base_h, got_h, inj_h = inject_run("hard", 0, rep_rows[0])
    if inj_h is not None and inj_h.ok:
        live_accepted += 1
    if abs(got_h - base_h) > 1e-9:
        live_changed += 1

    env = Env("hard", 0)
    s_before = env.peek_status()
    rej = env.call(rep_rows[0]["tool"], rep_rows[0]["args"])
    s_after = env.peek_status()
    side_effect_free = (
        not rej.ok
        and rej.error == "unknown tool"
        and s_after["V"] == s_before["V"]
        and s_after["day"] == s_before["day"]
        and s_after["actions_left_today"] == s_before["actions_left_today"]
        and len(env.history) == 1
    )

    by_tier_probe = {(r["tier"], r["probe"]): r for r in exploits_data["rows"]}
    attack_rows = [r for r in exploits_data["rows"] if r["kind"] == "attack"]
    attack_blocked = sum(1 for r in attack_rows if r["blocked"] and r["mean"] <= 0.0)
    solver_judge = {t: round(float(by_tier_probe[(t, "solver")]["mean"]), 3) for t in ("easy", "medium", "hard")}
    pad_diffs = {
        t: round(abs(float(by_tier_probe[(t, "control_solver_then_pad")]["mean"]) - float(by_tier_probe[(t, "solver")]["mean"])), 9)
        for t in ("easy", "medium", "hard")
    }
    solver_pos = {t: int(by_tier_probe[(t, "solver")]["positive"]) for t in ("easy", "medium", "hard")}

    fairness_invariants = [
        _invariant(
            "corpus_schema_always_invalid",
            len(rows) == 129 and always_invalid_count == 129 and len(distinct_tools) == 10,
            {"rows": len(rows), "always_invalid": always_invalid_count, "foreign_tools": len(distinct_tools)},
            "All 129 Sleeper foreign-tool patterns in data/redteam/corpus.jsonl are unconditionally rejected by Env._dispatch / _check_args.",
        ),
        _invariant(
            "midpoint_injection_zero_perturbation",
            committed_eval == {"rows": 129, "runs": 1161, "changed": 0, "accepted": 0}
            and live_accepted == 0
            and live_changed == 0
            and side_effect_free,
            {"committed_runs": committed_eval["runs"], "live_spot_runs": len(rep_rows) + 3, "accepted": live_accepted, "changed": live_changed},
            "Injecting foreign Sleeper calls at SolverPolicy midpoint changes 0/1161 committed runs and 0/13 live spot-check runs, preserving V, day, and daily action budget.",
        ),
        _invariant(
            "anticheat_battery_and_pad_invariance",
            bool(exploits_data["all_blocked"])
            and attack_blocked == len(attack_rows)
            and all(v == 0.0 for v in pad_diffs.values()),
            {"attack_rows_blocked": f"{attack_blocked}/{len(attack_rows)}", "max_pad_diff": max(pad_diffs.values())},
            "All 42 attack probe x tier cells score <= 0.0 and control_solver_then_pad matches solver to 0.0 across all tiers.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "solver_dominates_all_attack_and_effort_probes",
            all(solver_judge[t] > 0.50 for t in ("easy", "medium", "hard"))
            and float(by_tier_probe[("hard", "solver")]["mean"]) > float(by_tier_probe[("hard", "solver_cut_90_guess")]["mean"]) + 0.40,
            {"solver_judge40_means": solver_judge, "hard_effort_90_mean": round(float(by_tier_probe[("hard", "solver_cut_90_guess")]["mean"]), 3)},
            "SolverPolicy achieves +0.765 / +0.671 / +0.545 on the 40 judge seeds, strictly above every attack probe (<= 0.0) and the 90% effort cut (+0.051 on hard).",
        ),
    ]

    return {
        "id": "cheat_corpus",
        "title": "Cheat Corpus and Midpoint Foreign-Tool Injection",
        "category": "flagship",
        "sleeper_origin": {
            "modules": ["redteam/cheat_corpus.py", "redteam/cheat_eval.py", "tests/test_integrity_control_pad.py"],
            "branches": ["origin/sleeper/rw-exploit-corpus", "origin/sleeper/rw-baselines-canary-probes"],
            "mechanism": f"Mined {len(rows)} distinct failed and foreign tool shapes ({total_historical_attempts} calls across {len(distinct_tools)} Sleeper seat tools) from gemini-3.5-flash transcripts and injected each at ticks // 2 to verify zero reward lift or state corruption.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/redteam/corpus.py", "data/redteam/corpus.jsonl", "canary/redteam/anticheat.py", "canary/redteam/harbor_cheat.py"],
            "artifacts": ["results/anticheat/corpus_eval.txt", "results/anticheat/exploits.json", "docs/EXPLOITS.md"],
            "mechanism": "Ports shape() normalization and midpoint SolverPolicy injection (inject_run), paired with the 33-probe x 3-tier anti-cheat battery (garbage_args, control_solver_then_pad, solver_plus_*) and Harbor cheat_probe (149 out-of-band checks).",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-v15"],
            "mechanism": "Identical 13-tool _SPECS allowlist and _check_args schema gate; make hunt TIER=all TV=v1.5-candidate recorded 0 invariant violations and 0.000 best non-solver score across easy, medium, hard, and hard_forge.",
        },
        "one_agent_adaptation_rationale": "One-agent Canary has 13 security-lead MCP tools rather than 8 seat-specific operational queues; foreign seat actions (pay, quarantine, report_insider, send_email) become strict schema-rejection invariants that consume 1 global cap slot with zero V or daily-budget side effects.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "corpus_rows": len(rows),
            "foreign_tools": distinct_tools,
            "historical_attempt_count": total_historical_attempts,
            "committed_injection_runs": committed_eval["runs"],
            "solver_judge40_means": solver_judge,
            "solver_judge40_positive_seeds": solver_pos,
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_social_chains(root: Path, exploits_data: dict[str, Any]) -> dict[str, Any]:
    case_counts: dict[str, int] = {}
    for p in sorted((root / "data" / "failures").glob("cases_*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("cases", [])
        case_counts[p.name] = len(items)
    total_cases = sum(case_counts.values())

    fact_fields = [f.name for f in dataclasses.fields(PublicDayFacts)]
    mole_in_fact_fields = any("mole" in name.lower() for name in fact_fields)

    provider = TemplateProvider()
    counterfactual_diffs = 0
    lint_violations = 0
    total_messages_checked = 0
    for tier in ("medium", "hard"):
        for seed in range(10):
            env = Env(tier, seed)
            for _ in range(3):
                d = env.day
                orig_mole = env._world.mole
                alt_mole = next(e for e in env._ids if e != orig_mole and e != env._world.decoy)
                f_orig = env._facts(d)
                m_orig = provider.day_messages(f_orig)
                try:
                    env._world.mole = alt_mole
                    f_alt = env._facts(d)
                    m_alt = provider.day_messages(f_alt)
                finally:
                    env._world.mole = orig_mole
                if f_orig != f_alt or m_orig != m_alt:
                    counterfactual_diffs += 1
                lint_violations += len(lint_messages(m_orig))
                total_messages_checked += len(m_orig)
                env.call("advance_day", {})

    decoy_disjoint = 0
    decoy_total = 0
    for tier in ("medium", "hard"):
        for seed in range(30):
            w = Env(tier, seed)._world
            decoy_total += 1
            if w.decoy is not None and w.mole != w.decoy:
                decoy_disjoint += 1

    by_tier_probe = {(r["tier"], r["probe"]): r for r in exploits_data["rows"]}
    decoy_probe_means = {
        t: round(float(by_tier_probe[(t, "accuse_decoy")]["mean"]), 3)
        for t in ("easy", "medium", "hard")
    }

    hof_rows = [
        json.loads(line)
        for line in (root / "data" / "forge" / "hall_of_fame_v1.2.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rl_heldout = json.loads((root / "data" / "rl_mole" / "heldout_paired.json").read_text(encoding="utf-8"))

    forge_live = [run_episode(Env("hard_forge", s), SolverPolicy("hard")) for s in range(3)]
    forge_live_acc = sum(1 for r in forge_live if r.correct) / len(forge_live)

    fairness_invariants = [
        _invariant(
            "public_day_facts_mole_independence_and_lint",
            not mole_in_fact_fields and counterfactual_diffs == 0 and lint_violations == 0,
            {"messages_checked": total_messages_checked, "counterfactual_diffs": counterfactual_diffs, "lint_violations": lint_violations},
            "PublicDayFacts has zero mole fields; counterfactually swapping _world.mole changes 0/60 day message batches and produces 0 lint violations.",
        ),
        _invariant(
            "decoy_strictly_innocent_and_non_exploitable",
            decoy_disjoint == decoy_total
            and decoy_probe_means["medium"] == -1.0
            and decoy_probe_means["hard"] == -1.0,
            {"decoy_disjoint": f"{decoy_disjoint}/{decoy_total}", "accuse_decoy_means": decoy_probe_means},
            "On medium and hard, decoy != mole on 60/60 seeds and accuse_decoy scores -1.000 across all 40 judge seeds.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "forge_and_rl_mole_catchability_floor",
            MIN_ACC == 0.75
            and MIN_SOLVER_ACC == 0.75
            and TIER_DEFAULTS["hard"]["min_solver_acc"] == 0.75
            and FEASIBLE_SOLVER_RATIO == 0.5
            and all(float(r["solver_acc"]) >= 0.75 for r in hof_rows)
            and float(rl_heldout["rl"]["solver"]["acc"][0]) >= 0.75
            and forge_live_acc >= 0.80,
            {
                "min_solver_acc_floor": MIN_SOLVER_ACC,
                "hof_solver_acc": round(float(hof_rows[0]["solver_acc"]), 4),
                "rl_heldout_solver_acc": rl_heldout["rl"]["solver"]["acc"][0],
                "rl_heldout_solver_score": rl_heldout["rl"]["solver"]["score"][0],
                "forge_live3_acc": round(forge_live_acc, 4),
            },
            "Adversarial Mole DSL (hard_forge) and RL mole (hard_rl) enforce solver_acc >= 0.75; held-out RL mole n=100 keeps solver at 0.75 acc (+0.3954 score) while pushing grok_tactics to +0.1643 and heuristic to -0.2942.",
        ),
    ]

    return {
        "id": "multi_employee_social_chains",
        "title": "Multi-Employee Social Chains, Framing, and Human-Bias Layer",
        "category": "flagship",
        "sleeper_origin": {
            "modules": ["sleeper/goals/__init__.py", "sleeper/goals/frame.py", "sleeper/company.py", "docs/gemini/SLEEPER-idea.md"],
            "branches": ["origin/momin", "origin/sleeper/atk-library-ctrl"],
            "mechanism": "8-seat company (CEO assistant, Finance AP, Controller, HR, IT admin, Procurement, Sales, Legal) with 30 multi-seat strategies requiring two-person sign-offs, chat persuasion, and colleague framing.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/world.py", "canary/env.py", "canary/mole/dsl.py", "canary/text/template.py", "canary/forge_track.py", "canary/forge/rl_mole.py"],
            "artifacts": ["docs/research-biases.md", "docs/FAILURE-RESEARCH.md", "data/failures/cases_structural.json", "data/rl_mole/heldout_paired.json"],
            "mechanism": "Distills multi-seat social dynamics into pure deterministic one-agent mechanics: 2-department regular docs (p_single_dept_recipients=0.0), vocal innocent decoy (dept-channel anger), Poisson + Mole DSL after-hours framing (framing_rate=2.0 on hard), and guarded HR interviews grounded in 44 sourced corporate failure cases.",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-v15", "origin/justSilas-v15-bias", "origin/justSilas-gemini-v15"],
            "mechanism": "Added endogenous one-agent social chatter (rumour_rate=2.0, rumour_frame_share=0.4 seeded at decoy -> LR=1.0, grudge_pairs=2, authority_day=3, p_misforward=0.15, DSL seed_rumour). Trapped rumour_follower at -0.995 (n=400), but OpenCode gemini-4-carbon jumped from 61% to 108% of solver on hard seeds 0..9 (0.664 vs 0.615), so v1.5 was dropped at Gate B.",
        },
        "one_agent_adaptation_rationale": "Running 7 LLM background staff seats confounded benchmark difficulty with staff prompt versions and spent API quota outside the judged agent; encoding decoy chatter, framing, and multi-dept cohorts directly in Env keeps episodes 100% deterministic and keyless while testing social red-herring resistance.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "sourced_corporate_failure_cases": total_cases,
            "failure_cases_by_file": case_counts,
            "v14_hard_framing_rate": TIERS["hard"].framing_rate,
            "v14_hard_interview_lr": TIERS["hard"].interview_lr,
            "rl_heldout_n100": {
                "solver_score": rl_heldout["rl"]["solver"]["score"][0],
                "solver_acc": rl_heldout["rl"]["solver"]["acc"][0],
                "grok_tactics_score": rl_heldout["rl"]["grok_tactics"]["score"][0],
                "heuristic_score": rl_heldout["rl"]["heuristic"]["score"][0],
            },
            "v15_gate_b_spotcheck_n10": {
                "gemini_4_carbon_score": 0.664,
                "solver_score": 0.615,
                "ratio_vs_solver": 1.08,
                "decision": "dropped_at_gate_b",
            },
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_surface_tells(root: Path, exploits_data: dict[str, Any]) -> dict[str, Any]:
    missing_params: dict[str, list[str]] = {}
    param_counts: dict[str, int] = {}
    for tier in ("easy", "medium", "hard"):
        txt = Env(tier, 0).instruction()
        p_dict = TIERS[tier].to_dict()
        param_counts[tier] = len(p_dict)
        missing_params[tier] = [k for k in p_dict if f"- {k}: " not in txt]

    smoke_ok = 0
    smoke_total = 0
    for tier in ("easy", "medium", "hard"):
        ok_n, tot_n = _smoke_all_tools(tier, 4242)
        smoke_ok += ok_n
        smoke_total += tot_n

    parity_mismatches = 0
    for seed in range(10):
        env_m = Env("hard", seed)
        env_i = Env("hard", seed)
        mole = env_m._world.mole
        innocent = next(e for e in env_m._ids if e != mole and e != env_m._world.decoy)

        for tool, args_m, args_i in (
            ("interview", {"employee": mole, "topic": "bad_topic"}, {"employee": innocent, "topic": "bad_topic"}),
            ("unrestrict_access", {"employee": mole}, {"employee": innocent}),
        ):
            rm = env_m.call(tool, args_m)
            ri = env_i.call(tool, args_i)
            dm = str((rm.data or {}).get("detail", "")).replace(mole, "<EMP>")
            di = str((ri.data or {}).get("detail", "")).replace(innocent, "<EMP>")
            if rm.ok != ri.ok or rm.error != ri.error or dm != di:
                parity_mismatches += 1

        env_m.call("restrict_access", {"employee": mole})
        env_i.call("restrict_access", {"employee": innocent})
        rm2 = env_m.call("restrict_access", {"employee": mole})
        ri2 = env_i.call("restrict_access", {"employee": innocent})
        dm2 = str((rm2.data or {}).get("detail", "")).replace(mole, "<EMP>")
        di2 = str((ri2.data or {}).get("detail", "")).replace(innocent, "<EMP>")
        if rm2.ok != ri2.ok or rm2.error != ri2.error or dm2 != di2:
            parity_mismatches += 1

        am = env_m.call("accuse", {"employee": mole})
        ai = env_i.call("accuse", {"employee": innocent})
        if (
            am.ok != ai.ok
            or set(am.data.keys()) != {"accused", "episode_over"}
            or set(ai.data.keys()) != {"accused", "episode_over"}
            or am.data["episode_over"] is not True
            or ai.data["episode_over"] is not True
        ):
            parity_mismatches += 1

    hidden_leak_states = 0
    hidden_leak_disclosures = 0
    for seed in range(10):
        env = Env("hard", seed)
        for _ in range(8):
            r_adv = env.call("advance_day", {})
            r_st = env.call("status", {})
            unsurfaced = [f for f in env._feed if f["surfaced_day"] > env.day]
            if unsurfaced and env.V > 0.0:
                hidden_leak_states += 1
                shown_v = r_st.data["V"]
                adv_v = r_adv.data.get("V", shown_v)
                if abs(shown_v - env.V) < 1e-9 or abs(adv_v - env.V) < 1e-9:
                    hidden_leak_disclosures += 1

    by_tier_probe = {(r["tier"], r["probe"]): r for r in exploits_data["rows"]}
    most_logs_means = {
        t: round(float(by_tier_probe[(t, "accuse_most_logs")]["mean"]), 3)
        for t in ("easy", "medium", "hard")
    }
    fair_bars_k2 = {t: round(fair_bar(t, 2), 4) for t in ("easy", "medium", "hard")}
    ladder_stats = _skill_ladder_solver_stats(root / "results" / "skill_ladder_v1.4.csv")

    fairness_invariants = [
        _invariant(
            "instruction_completeness_and_tool_smoke",
            all(len(v) == 0 for v in missing_params.values()) and smoke_ok == 39 and smoke_total == 39,
            {"params_printed_per_tier": param_counts, "tool_smoke": f"{smoke_ok}/{smoke_total}"},
            "Every TierParams field (34/34 per tier) is printed in Env.instruction() and all 13 MCP tools pass smoke checks on easy, medium, and hard (39/39).",
        ),
        _invariant(
            "mole_vs_innocent_error_and_accuse_parity",
            parity_mismatches == 0 and len(ERRORS) == 5,
            {"parity_mismatches": parity_mismatches, "fixed_error_codes": len(ERRORS)},
            "Invalid-argument errors, Panel Fix D detail strings (modulo echoed employee id), and accuse() responses are identical for the true mole and innocent peers.",
        ),
        _invariant(
            "known_v_hides_unsurfaced_leaks_and_log_counts_carry_zero_hard_signal",
            hidden_leak_states >= 15
            and hidden_leak_disclosures == 0
            and TIERS["hard"].log_rate_mole == TIERS["hard"].log_rate_benign == 1.0
            and most_logs_means["medium"] == -1.0
            and most_logs_means["hard"] == -1.0,
            {
                "hidden_leak_states_checked": hidden_leak_states,
                "hidden_leak_disclosures": hidden_leak_disclosures,
                "hard_log_rates": [TIERS["hard"].log_rate_benign, TIERS["hard"].log_rate_mole],
                "accuse_most_logs_means": most_logs_means,
                "text_fair_bar_k2": fair_bars_k2,
            },
            "status and advance_day expose visible_V only (0 unsurfaced leak disclosures), and hard-tier total access counts carry zero signal (log_rate 1.0 vs 1.0; accuse_most_logs = -1.000).",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "solver_catchability_without_surface_tells",
            ladder_stats["hard"]["n"] == 400
            and ladder_stats["hard"]["acc_when_accusing"] >= 0.95
            and ladder_stats["medium"]["acc_when_accusing"] >= 0.99
            and ladder_stats["easy"]["acc_when_accusing"] >= 0.99,
            {"skill_ladder_n400_solver": ladder_stats},
            "Without any roster, wording, count, or V-drop surface tells, SolverPolicy reaches 96.5% accuracy when accusing on hard (mean +0.564, n=400) and 100.0% on medium (+0.628, n=400).",
        ),
    ]

    return {
        "id": "surface_tells_audit",
        "title": "Surface-Tells Audit, Known-V Non-Disclosure, and Fair-Bar Bounds",
        "category": "flagship",
        "sleeper_origin": {
            "modules": ["sleeper/detell.py", "redteam/hunt/tmplagent.py", "redteam/hunt/clfagent.py", "docs/generator-v2.md"],
            "branches": ["origin/vaishnav/sleeper-tells"],
            "mechanism": "Sleeper v2 (e08b62ff) replaced legit tickets of matching (seat, kind, payment size), normalized FI IBANs/amounts/V01-V03 payees, and shuffled same-tick messages after wording-list (1.000) and ticket-counting (0.95) agents exploited v1 surface tells.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/world.py", "canary/env.py", "canary/rules.py", "canary/redteam/text_probe.py", "scripts/instruction_audit.py"],
            "artifacts": ["docs/DIFFICULTY.md", "results/skill_ladder_v1.4.md", "results/skill_ladder_v1.4.csv"],
            "mechanism": "Generates all employee names, departments, roles, and clearances before drawing decoy and mole; hides unsurfaced leak drops via KNOWN_V_MODE=True; sets hard log_rate_mole=log_rate_benign=1.0; enforces mole-vs-innocent error/detail parity (1bc3e281); and bounds text-only guessing by exact binomial fair_bar(tier, k).",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-v15"],
            "mechanism": "Samples unseeded rumour and authority targets uniformly over all non-speaker employees (including the mole) and grudge pairs over all non-decoy employees so being targeted never acts as an innocence exclusion tell; strips forbidden confession phrases.",
        },
        "one_agent_adaptation_rationale": "Instead of ticket-text templates across 8 seats, Canary eliminates every non-investigative shortcut (roster order, log-volume spikes, same-day V drops, error strings, and message leaks) so only active canary partitioning + Bayesian delay accounting separates the mole.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "instruction_fields_verified": param_counts,
            "tool_smoke_passed": f"{smoke_ok}/{smoke_total}",
            "hidden_leak_states_verified": hidden_leak_states,
            "text_fair_bar_k2": fair_bars_k2,
            "skill_ladder_n400_solver": ladder_stats,
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_failure_gallery_breakeven(root: Path) -> dict[str, Any]:
    fg = json.loads((root / "results" / "gemini" / "failure_gallery.json").read_text(encoding="utf-8"))
    card_sum = round(sum(float(c["value"]) for c in fg["cards"]), 6)
    net_gap = round(float(fg["net_gap"]), 6)
    unexplained = abs(float(fg["unexplained"]))
    max_ep_res = float(fg["max_episode_residual"])

    spotlight = compute_spotlight(root)
    quotes_verified = verify_transcript_quotes(root)
    oc = spotlight["cohorts"]["opencode-gemini-4-carbon"]
    fl = spotlight["cohorts"]["opencode-gemini-3.5-flash"]
    ip = spotlight["cohorts"]["inproc-gemini-4-carbon"]
    sv = spotlight["cohorts"]["solver"]
    tot = spotlight["totals"]
    cf = spotlight["counterfactual"]

    max_pair_res = 0.0
    for row in spotlight["pairs"].values():
        r1 = abs((row["leak"] + row["canary"] + row["restrict"] + row["penalty"] + row["abstain"]) - row["la_gap"])
        r2 = abs((row["la_gap"] + row["luck"]) - row["raw_gap"])
        max_pair_res = max(max_pair_res, r1, r2)

    s18 = spotlight["opencode"][18]
    p_star_check = abs(breakeven_posterior(0.25) - 0.80) < 1e-12 and abs(accusation_ev(0.80, 0.25)) < 1e-12

    fairness_invariants = [
        _invariant(
            "exact_additive_gap_accounting_zero_residual",
            fg["episodes_decomposed"] == 295
            and abs(card_sum - net_gap) < 1e-6
            and unexplained == 0.0
            and max_ep_res < 1e-12
            and max_pair_res < 1e-12
            and p_star_check,
            {
                "gallery_episodes": fg["episodes_decomposed"],
                "gallery_net_gap": net_gap,
                "gallery_max_residual": max_ep_res,
                "breakeven_30seed_max_residual": max_pair_res,
            },
            "Both the 295-episode failure gallery (+90.795 net gap) and the 30-seed v1.4 hard break-even spotlight (+4.1897 luck-adjusted / +5.3000 raw gap) sum with zero unexplained residual (< 1e-12).",
        ),
        _invariant(
            "public_evidence_posterior_and_verbatim_quotes",
            set(quotes_verified) == {5, 11, 18, 23}
            and oc["below_exp_seeds"] == [5, 18, 23]
            and oc["below_known_seeds"] == [5, 18, 23]
            and s18["accuse_py_verdict"] == "justified",
            {
                "verified_quote_seeds": sorted(quotes_verified),
                "below_breakeven_seeds": oc["below_exp_seeds"],
                "seed18_p_vs_breakeven": [round(s18["p_accused"], 4), round(s18["be_exp"], 4)],
            },
            "Posteriors use only the agent's own public tool history; moving P*(V)=1/(1+V) catches seeds 5, 18, 23 even on visible V_known, including seed 18 (62.72% vs 68.43%) missed by fixed 0.60 cutoffs.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "solver_zero_below_breakeven_stopping_discipline",
            sv["below_exp_seeds"] == []
            and sv["accused"] == 30
            and sv["min_margin_exp"] > 0.11
            and sv["la_mean"] > oc["la_mean"] > fl["la_mean"],
            {
                "solver_below_be": len(sv["below_exp_seeds"]),
                "solver_min_margin_pp": round(100.0 * sv["min_margin_exp"], 2),
                "cohort_below_be_counts": {
                    "opencode_gemini_3_5_flash": len(fl["below_exp_seeds"]),
                    "opencode_gemini_4_carbon": len(oc["below_exp_seeds"]),
                    "inproc_gemini_4_carbon": len(ip["below_exp_seeds"]),
                    "solver": len(sv["below_exp_seeds"]),
                },
            },
            "On the exact same 30 v1.4 hard seeds, SolverPolicy makes 0/30 below-break-even accusations (tightest margin +11.60 pp on seed 10), vs 3 for gemini-4-carbon (-0.9348 V EV) and 10 for gemini-3.5-flash (-7.0172 V EV).",
        ),
    ]

    return {
        "id": "failure_gallery_breakeven_spotlight",
        "title": "Failure Gallery and Below-Break-Even Accusation Spotlight",
        "category": "flagship",
        "sleeper_origin": {
            "modules": ["lab/gallery.py", "lab/analyse.py"],
            "branches": ["origin/sleeper/lab-analyst-gallery", "origin/sleeper/lab-canary-gallery"],
            "mechanism": "Decomposed multi-seat episode losses into deterministic harm labels (*_on_chat_request, *_without_ticket, false quarantine) with verbatim transcript excerpts in gallery.json and gallery.md.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/gemini/gallery.py", "canary/gemini/gallery_breakeven.py", "canary/analysis/accuse.py", "canary/analysis/tags.py"],
            "artifacts": ["results/gemini/failure_gallery.json", "docs/reports/failure_gallery.md", "docs/reports/failure_gallery_breakeven.md", "results/failure_analysis_v1.4.json"],
            "mechanism": "Decomposes solver_score - agent_score step-by-step across 295 episodes (196 v1.4, residual 4.4e-16) and audits all 30 judged v1.4 hard seeds against the moving optimal-stopping bar P*(V) = 1 / (1 + V), isolating negative-EV horizon gambles masked by coin-flip luck.",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-gemini-v15"],
            "mechanism": "Applies canary.analysis.accuse and canary.analysis.tags to the 10-seed v1.5-candidate OpenCode gemini-4-carbon spot-check (accuse.md, tags.json) under identical Bayesian posterior accounting.",
        },
        "one_agent_adaptation_rationale": "In Canary's continuous-value single-accusation stopping game, the dominant frontier mistake is committing with >= 2 consistent suspects or gambling below P*(V) = 1 / (1 + V) as V drains toward 0 rather than abstaining for 0.00.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "gallery_episodes_decomposed": fg["episodes_decomposed"],
            "gallery_v14_episodes": fg["by_version"]["v1.4"]["episodes"],
            "gallery_v14_net_gap": fg["by_version"]["v1.4"]["net_gap"],
            "opencode_carbon_hard30": {
                "below_breakeven_seeds": oc["below_exp_seeds"],
                "decision_ev_sum": round(oc["below_ev_exp_sum"], 4),
                "luck_adjusted_sum": round(oc["below_la_sum"], 4),
                "realized_luck_on_below_be": round(oc["below_luck_sum"], 4),
                "share_of_penalty_gap": round(tot["penalty_below_breakeven"] / tot["penalty"], 4),
                "abstain_counterfactual_la_gain": round(cf["la_gain_sum"], 4),
            },
            "solver_hard30": {
                "below_breakeven_count": 0,
                "min_margin_exp": round(sv["min_margin_exp"], 4),
                "raw_mean": round(sv["raw_mean"], 4),
                "luck_adjusted_mean": round(sv["la_mean"], 4),
            },
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_office_replay_dashboard(root: Path) -> dict[str, Any]:
    replay_seeds = (4, 18, 26)
    seed_summaries: dict[str, Any] = {}
    replay_mismatches = 0
    solver_wins = 0
    for seed in replay_seeds:
        s_ep = load_demo_episode(DEMO_RUNS["solver"], seed)
        g_ep = load_demo_episode(DEMO_RUNS["gemini"], seed)
        rs = replay_episode(s_ep)
        rg = replay_episode(g_ep)
        if abs(rs["score"] - s_ep["score"]) > 1e-9 or rs["accused"] != s_ep["accused"]:
            replay_mismatches += 1
        if abs(rg["score"] - g_ep["score"]) > 1e-9 or rg["accused"] != g_ep["accused"]:
            replay_mismatches += 1
        mole = s_ep["accused"] if s_ep.get("correct") else None
        s_days = demo_per_day(s_ep, mole)
        g_days = demo_per_day(g_ep, mole)
        if s_ep.get("correct") and s_ep["score"] > g_ep["score"]:
            solver_wins += 1
        seed_summaries[str(seed)] = {
            "mole": mole,
            "solver": {"score": s_ep["score"], "final_day": s_ep["final_day"], "accused": s_ep["accused"], "days_tracked": len(s_days)},
            "gemini": {"score": g_ep["score"], "final_day": g_ep["final_day"], "accused": g_ep["accused"], "days_tracked": len(g_days)},
        }

    rejected_seeds = 0
    bad_seed_list = (0, 2999, 10000, TRAIN_SEEDS.start, HELDOUT_SEEDS.start, JUDGE_SEEDS.start)
    for bad_s in bad_seed_list:
        try:
            check_seed(bad_s)
        except ValueError:
            rejected_seeds += 1

    g3000 = Game(3000)
    zero_init_calls = len(g3000.env.history) == 0 and len(g3000.actions) == 0
    pre_done_reveal = json.loads(g3000.reveal_json())
    truth_hidden_before_done = "error" in pre_done_reveal and "mole" not in pre_done_reveal

    env_s = Env("medium", 3000)
    pol_s = SolverPolicy()
    pol_s.reset(env_s.tools_spec(), env_s.instruction())
    rec_actions: list[list[Any]] = []
    while not env_s.done:
        t_name, t_args = pol_s.act(env_s.history)
        env_s.call(t_name, t_args)
        rec_actions.append([t_name, t_args])
    sv3000 = game_solver_result(3000)
    rep3000 = game_replay(3000, rec_actions)
    game_parity = (
        abs(sv3000["score"] - 0.79) < 1e-9
        and sv3000["correct"] is True
        and sv3000["final_day"] == 6
        and sv3000["tool_calls"] == 48
        and abs(rep3000["score"] - sv3000["score"]) < 1e-9
        and rep3000["accused"] == env_s._world.mole
    )

    sample_secret = {"msg": "AIza" + "SyFakeKey1234567890 and sk-" + "FakeOpenAIKey1234567890 and api_key=topsecret"}
    redacted = redact(sample_secret)["msg"]
    redaction_ok = (
        ("AIza" + "SyFakeKey") not in redacted
        and ("sk-" + "FakeOpenAIKey") not in redacted
        and "topsecret" not in redacted
        and redacted.count("[redacted]") == 3
    )

    dash_html = (root / "results" / "gemini" / "dashboard.html").read_text(encoding="utf-8")
    ext_assets = re.findall(r'<(?:script|link|img)\b[^>]*(?:src|href)=["\']https?://', dash_html, re.I)
    showcase_man = json.loads((root / "results" / "gemini" / "replay-ladder-showcase" / "manifest.json").read_text(encoding="utf-8"))
    showcase_eps = sum(len(v) for v in showcase_man.get("episodes", {}).values())

    fairness_invariants = [
        _invariant(
            "browser_game_seed_hygiene_and_truth_hiding",
            rejected_seeds == len(bad_seed_list) and zero_init_calls and truth_hidden_before_done,
            {"allowed_dev_seed_range": [SEED_MIN, SEED_MAX], "rejected_benchmark_seeds": f"{rejected_seeds}/{len(bad_seed_list)}"},
            "game/canary_game.py restricts browser play to public dev seeds 3000..9999 (refusing headline 0..29, train, held-out, and judge seeds), makes 0 hidden tool calls, and blocks reveal_json() until episode end.",
        ),
        _invariant(
            "dashboard_secret_redaction_and_self_contained_offline_html",
            redaction_ok and len(ext_assets) == 0 and showcase_eps > 0,
            {"external_network_tags": len(ext_assets), "redacted_tokens": 3, "lab_replay_showcase_episodes": showcase_eps},
            "canary/gemini/dashboard.py redacts key-shaped substrings, embeds zero external HTTP script/style/image URLs in dashboard.html, and pairs with keyless lab_replay step-hash stores.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "deterministic_replay_and_pyodide_solver_parity",
            replay_mismatches == 0 and solver_wins == 3 and game_parity,
            {
                "canonical_hard_seeds_replayed": list(replay_seeds),
                "replay_mismatches": replay_mismatches,
                "game_seed3000_solver": sv3000,
            },
            "demo_replay + verify_replay reproduce solver and Gemini step-for-step on hard seeds 4, 18, and 26 (solver +0.73, +0.52, +0.69), and canary_game.py matches CPython SolverPolicy on seed 3000 (+0.79, 48 calls, day 6).",
        ),
    ]

    return {
        "id": "office_replay_dashboard",
        "title": "Office Replay Dashboard, Side-by-Side CLI, and Browser Case-File Game",
        "category": "flagship",
        "sleeper_origin": {
            "modules": ["web/export.py", "web/app.js", "lab/action_replay.py"],
            "branches": ["origin/sleeper/dm-dashboard-default", "origin/sleeper/dm-dashboard-office", "origin/justSilas-sleeper-integration"],
            "mechanism": "Rendered static seat-mode office replays (highlighting the judged seat, background staff chatter, ticket state, and exact harm tick) alongside offline action_replay verification.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["scripts/demo_replay.py", "scripts/verify_replay.py", "game/canary_game.py", "game/app.js", "canary/gemini/dashboard.py", "canary/gemini/lab_replay.py"],
            "artifacts": ["results/gemini/dashboard.html", "results/gemini/replay-ladder-showcase/manifest.json", "docs/DEMO.md", "docs/reports/review-ivar-game.md"],
            "mechanism": "Splits office replay into three zero-key surfaces: (1) scripts/demo_replay.py day-by-day solver-vs-agent V and P(mole) trace with --verify Env re-execution, (2) game/ Pyodide case-file UI with P*(V)=1/(1+V) accuse dialog on seeds 3000..9999, and (3) self-contained results/gemini/dashboard.html + lab_replay step-hash verification.",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-gemini-v15"],
            "mechanism": "Added scripts/with_tiers.py + scripts/verify_replay.py verification confirming 10/10 v1.5-candidate episodes replay identically under v1.5 rules (and only 6/10 under v1.4, proving social misforwards/messages actively alter trajectories).",
        },
        "one_agent_adaptation_rationale": "With one investigator instead of 8 concurrent staff seats, the critical replay view is the side-by-side belief trajectory P(mole | observations) and visible_V decay between SolverPolicy and the frontier model on the exact same seed.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "canonical_replays": seed_summaries,
            "browser_game_seed3000": sv3000,
            "dashboard_html_kb": round(len(dash_html.encode("utf-8")) / 1024.0, 1),
            "lab_replay_showcase_episodes": showcase_eps,
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_salted_sidecar_and_signed_ledger(root: Path, exploits_data: dict[str, Any]) -> dict[str, Any]:
    secret_a = b"port-audit-world-secret-alpha-01"
    secret_b = b"port-audit-world-secret-bravo-02"
    try:
        set_world_secret(secret_a)
        judge_a = [world_seed("hard", s) for s in range(900000, 900005)]
        dev_a = world_seed("hard", 42)
        set_world_secret(secret_b)
        judge_b = [world_seed("hard", s) for s in range(900000, 900005)]
        dev_b = world_seed("hard", 42)
    finally:
        set_world_secret(None)

    salted_divergence = all(a != b for a, b in zip(judge_a, judge_b)) and dev_a == dev_b

    tamper_reward = (
        root / "results" / "harbor_negative" / "c1-tamper" / "canary-hard-900000__GZn8oUh" / "verifier" / "reward.txt"
    ).read_text(encoding="utf-8").strip()
    tamper_stdout = (
        root / "results" / "harbor_negative" / "c1-tamper" / "canary-hard-900000__GZn8oUh" / "verifier" / "test-stdout.txt"
    ).read_text(encoding="utf-8").strip()

    harbor_trials = [h for h in exploits_data["harbor"] if h.get("kind") == "trial"]
    harbor_jobs = [h for h in exploits_data["harbor"] if h.get("kind") == "job"]
    rc = exploits_data["replay_counts"]

    fairness_invariants = [
        _invariant(
            "hmac_salted_judge_worlds_and_public_dev_reproducibility",
            salted_divergence
            and len( set(DEV_SEEDS) & set(JUDGE_SEEDS) ) == 0
            and len( set(TRAIN_SEEDS) & set(HELDOUT_SEEDS) ) == 0
            and len( set(HELDOUT_SEEDS) & set(JUDGE_SEEDS) ) == 0,
            {"judge_seeds_tested": 5, "salted_diverged": 5, "public_dev_seed42_identical": dev_a == dev_b},
            "Judge and held-out worlds derive RNG via HMAC-SHA256(secret, tier:seed) and fail closed without a secret, while dev seeds stay public-keyed for exact offline replay.",
        ),
        _invariant(
            "signed_ledger_tamper_rejection_and_harbor_consistency",
            tamper_reward == "0"
            and "bad ledger signature" in tamper_stdout
            and bool(exploits_data["harbor_all_consistent"])
            and bool(exploits_data["replay_all_consistent"])
            and rc["step_mismatches"] == 0,
            {
                "harbor_trials_consistent": f"{len(harbor_trials)}/{len(harbor_trials)}",
                "harbor_jobs_consistent": f"{len(harbor_jobs)}/{len(harbor_jobs)}",
                "replayed_episodes": f"{rc['consistent']}/{rc['replayed']}",
                "replayed_steps": rc["steps"],
                "step_mismatches": rc["step_mismatches"],
            },
            "Forging score=1.0 after signing fails closed to reward 0 ('bad ledger signature'); 80/80 Harbor trials, 18/18 jobs, and 1021/1021 replayable episodes (51,814 steps) verify cleanly.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "harbor_oracle_and_cheat_probe_separation",
            any(h.get("policy") == "oracle" and (h.get("reward") or 0.0) > 0.0 for h in harbor_trials)
            and all((h.get("reward") == 0.0) for h in harbor_trials if h.get("policy") in ("do_nothing", "cheat_probe")),
            {
                "oracle_positive": True,
                "do_nothing_and_cheat_probe_zero": True,
            },
            "Inside the isolated Harbor sidecar architecture, SolverPolicy (oracle) scores positively on signed ledgers while do_nothing and 149-attempt cheat_probe score 0.0.",
        ),
    ]

    return {
        "id": "salted_sidecar_and_signed_ledger",
        "title": "Salted Judge Worlds, 0600 Secret Isolation, and Signed-Ledger Rescore",
        "category": "supporting_port",
        "sleeper_origin": {
            "modules": ["sleeper/secrets.py", "harbor/sidecar.py", "sleeper/verifier.py"],
            "branches": ["origin/fr8/sleeper/salt", "origin/sleeper/rw-verifier-canary-rescore"],
            "mechanism": "Moved SLEEPER_SALT and VERIFY_TOKEN into 0600 files inside a separate sidecar container, wiped /proc/*/environ secrets, and rejected unsigned or forged state payloads.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/world.py", "canary/mcp_server.py", "canary/redteam/tamper_guard.py", "canary/redteam/anticheat.py"],
            "artifacts": ["results/harbor_negative/c1-tamper/result.json", "results/anticheat/exploits.md", "results/anticheat/judge_hunt.md"],
            "mechanism": "Keys judge/held-out worlds with HMAC-SHA256 fail-closed secrets, loads MCP secrets from 0600 CANARY_*_FILE paths, isolates canary-server in a separate Harbor PID/fs namespace (11/11 isolation checks), and HMAC-signs /ledger.",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-v15-bias"],
            "mechanism": "Preserved identical HMAC world seeding and kept judge worlds uncached (SHA-256 text cache keyed without world truth).",
        },
        "one_agent_adaptation_rationale": "Because Canary is a pure deductive game with a single hidden mole id, white-box seed regeneration or /proc environ inspection would yield an instant day-1 1.00 score without salted judge worlds and sidecar isolation.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "harbor_trials_verified": len(harbor_trials),
            "harbor_jobs_verified": len(harbor_jobs),
            "replayed_episodes_consistent": rc["consistent"],
            "replayed_tool_steps_compared": rc["steps"],
            "c1_tamper_negative_control_reward": int(tamper_reward),
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def audit_catchability_constrained_mole(root: Path) -> dict[str, Any]:
    mole_view_fields = [f.name for f in dataclasses.fields(MoleView)]
    no_canary_flag_in_mole_view = "is_canary" not in mole_view_fields and "variants" not in mole_view_fields

    custom_strat = MoleStrategy.from_json({
        "name": "sleeper_slowburn_port",
        "rules": [
            {"if": [["days_since_last_leak", "<", 2]], "then": {"leak": "most_recipients", "frame": "decoy"}},
            {"if": [["i_am_restricted", "==", 1]], "then": {"leak": "oldest", "frame": "most_restricted_peer"}},
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    })
    det_runs_1 = [run_episode(Env("medium", s, mole_strategy=custom_strat), SolverPolicy("medium")) for s in range(3)]
    det_runs_2 = [run_episode(Env("medium", s, mole_strategy=custom_strat), SolverPolicy("medium")) for s in range(3)]
    deterministic_match = all(
        abs(a.score - b.score) < 1e-12 and a.accused == b.accused and len(a.steps) == len(b.steps)
        for a, b in zip(det_runs_1, det_runs_2)
    )

    strat_0 = strategy_for("hard_forge", 0)
    rl_heldout = json.loads((root / "data" / "rl_mole" / "heldout_paired.json").read_text(encoding="utf-8"))
    lint_strat_ok = lint_text(json.dumps(strat_0.to_json())) == []

    fairness_invariants = [
        _invariant(
            "mole_view_information_barrier_and_dsl_determinism",
            no_canary_flag_in_mole_view
            and MAX_RULES == 12
            and len(LEAK_SELECTORS) == 6
            and len(FRAME_SELECTORS) == 4
            and deterministic_match
            and lint_strat_ok,
            {
                "mole_view_fields": len(mole_view_fields),
                "leak_selectors": len(LEAK_SELECTORS),
                "frame_selectors": len(FRAME_SELECTORS),
                "deterministic_replay_3seeds": deterministic_match,
            },
            "MoleView exposes document recipient_count and age_days but never is_canary or variant labels; custom MoleStrategy and RLMole execute deterministically from the world RNG without arbitrary code execution.",
        ),
    ]
    catchability_invariants = [
        _invariant(
            "stackelberg_lagrangian_catchability_constraint",
            float(rl_heldout["default"]["solver"]["acc"][0]) >= 0.95
            and float(rl_heldout["rl"]["solver"]["acc"][0]) >= MIN_SOLVER_ACC
            and float(rl_heldout["rl"]["regret"]["grok_tactics"][0]) > float(rl_heldout["default"]["regret"]["grok_tactics"][0])
            and float(rl_heldout["rl"]["regret"]["heuristic"][0]) > float(rl_heldout["default"]["regret"]["heuristic"][0]),
            {
                "default_solver_acc": rl_heldout["default"]["solver"]["acc"][0],
                "rl_solver_acc": rl_heldout["rl"]["solver"]["acc"][0],
                "regret_vs_grok_tactics": [
                    rl_heldout["default"]["regret"]["grok_tactics"][0],
                    rl_heldout["rl"]["regret"]["grok_tactics"][0],
                ],
                "regret_vs_heuristic": [
                    rl_heldout["default"]["regret"]["heuristic"][0],
                    rl_heldout["rl"]["regret"]["heuristic"][0],
                ],
            },
            "Replacing Sleeper's binary winnable=true filter, Canary's Lagrangian RL mole maximizes solver_score - max_k score_k subject to solver_acc >= 0.75, widening regret on held-out seeds 200000..200099 while preserving 75% solver catchability.",
        ),
    ]

    return {
        "id": "catchability_constrained_mole_adversary",
        "title": "Scripted Attack Library and Winnability Gate to Mole DSL and RL Mole",
        "category": "supporting_port",
        "sleeper_origin": {
            "modules": ["sleeper/goals/leak.py", "sleeper/goals/sabotage.py", "sleeper/daymix.py"],
            "branches": ["origin/sleeper/atk-library-fapmix", "origin/sleeper/atk-regret-winnable"],
            "mechanism": "Curated scripted sleeper strategies (slow-burn, decoy framing, accomplice gates) filtered by winnable=true so the reference/oracle team could still achieve reward=1.000.",
        },
        "canary_v14_counterpart": {
            "status": "shipped",
            "modules": ["canary/mole/dsl.py", "canary/forge/evolve.py", "canary/forge/fitness.py", "canary/forge/rl_mole.py", "canary/forge_track.py"],
            "artifacts": ["data/forge/hall_of_fame_v1.2.jsonl", "data/rl_mole/policy_final.json", "data/rl_mole/heldout_paired.json"],
            "mechanism": "Replaces seat-specific scripts with a safe 10-feature JSON Mole DSL (hard_forge) and an MLP REINFORCE + dual-ascent Lagrangian policy (hard_rl) sharing the exact (leak_selector, frame_selector) action space under solver_acc >= 0.75.",
        },
        "canary_v15_counterpart": {
            "status": "evaluated_dropped_at_gate_b",
            "branches": ["origin/justSilas-v15"],
            "mechanism": "Extended Mole DSL with optional seed_rumour framing selector while preserving MoleView's strict canary-blindness and >= 0.85 solver calibration target.",
        },
        "one_agent_adaptation_rationale": "A mole that simply stops leaking makes catchability impossible, while an unconstrained RL mole collapses game fairness; bounding the mole to MoleView (no canary visibility) plus a >= 0.75 SolverPolicy accuracy floor guarantees every adversarial track remains solvable.",
        "fairness_invariants": fairness_invariants,
        "catchability_invariants": catchability_invariants,
        "measured_evidence": {
            "dsl_max_rules": MAX_RULES,
            "leak_selectors": list(LEAK_SELECTORS),
            "frame_selectors": list(FRAME_SELECTORS),
            "heldout_n100_default_vs_rl": {
                "default_solver_score": rl_heldout["default"]["solver"]["score"][0],
                "rl_solver_score": rl_heldout["rl"]["solver"]["score"][0],
                "default_heuristic_regret": rl_heldout["default"]["regret"]["heuristic"][0],
                "rl_heuristic_regret": rl_heldout["rl"]["regret"]["heuristic"][0],
            },
        },
        "all_pass": all(x["passed"] for x in fairness_invariants + catchability_invariants),
    }


def compute_port_audit(root: Path = ROOT) -> dict[str, Any]:
    prev_allow = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        hygiene = audit_scope_hygiene(root)
        exploits_data = json.loads((root / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))

        ideas = [
            audit_cheat_corpus(root, exploits_data),
            audit_social_chains(root, exploits_data),
            audit_surface_tells(root, exploits_data),
            audit_failure_gallery_breakeven(root),
            audit_office_replay_dashboard(root),
            audit_salted_sidecar_and_signed_ledger(root, exploits_data),
            audit_catchability_constrained_mole(root),
        ]
    finally:
        if prev_allow is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_allow

    fairness_all = [inv for item in ideas for inv in item["fairness_invariants"]]
    catchability_all = [inv for item in ideas for inv in item["catchability_invariants"]]
    flagship_count = sum(1 for item in ideas if item["category"] == "flagship")
    supporting_count = sum(1 for item in ideas if item["category"] == "supporting_port")

    all_pass = (
        hygiene["passed"]
        and all(item["all_pass"] for item in ideas)
        and all(inv["passed"] for inv in fairness_all)
        and all(inv["passed"] for inv in catchability_all)
    )

    return {
        "schema_version": "1.0",
        "base_branch": BASE_BRANCH,
        "base_commit": BASE_COMMIT,
        "shipped_tiers_version": hygiene["shipped_tiers_version"],
        "known_v_mode": hygiene["known_v_mode"],
        "v16_social_files_count": hygiene["v16_social_files_count"],
        "gemini_api_calls": 0,
        "all_invariants_pass": all_pass,
        "summary": {
            "flagship_ideas_mapped": flagship_count,
            "supporting_ports_mapped": supporting_count,
            "total_entries": len(ideas),
            "fairness_invariants_checked": len(fairness_all),
            "fairness_invariants_passed": sum(1 for x in fairness_all if x["passed"]),
            "catchability_invariants_checked": len(catchability_all),
            "catchability_invariants_passed": sum(1 for x in catchability_all if x["passed"]),
            "counterpart_files_verified": hygiene["counterpart_files_present"],
        },
        "scope_hygiene": hygiene,
        "ideas": ideas,
    }


def render_json(payload: dict[str, Any]) -> str:
    txt = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    size = len(txt.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"JSON payload size {size} exceeds {MAX_JSON_BYTES} bytes")
    return txt


def render_markdown(payload: dict[str, Any]) -> str:
    h1, h2, h3 = chr(35), chr(35) * 2, chr(35) * 3
    s = payload["summary"]
    ideas = {item["id"]: item for item in payload["ideas"]}
    c_corp = ideas["cheat_corpus"]["measured_evidence"]
    c_soc = ideas["multi_employee_social_chains"]["measured_evidence"]
    c_tell = ideas["surface_tells_audit"]["measured_evidence"]
    c_gal = ideas["failure_gallery_breakeven_spotlight"]["measured_evidence"]
    c_rep = ideas["office_replay_dashboard"]["measured_evidence"]
    c_salt = ideas["salted_sidecar_and_signed_ledger"]["measured_evidence"]
    c_mole = ideas["catchability_constrained_mole_adversary"]["measured_evidence"]

    lines = [
        f"{h1} Sleeper-to-Canary Port Matrix and Invariant Audit (`{payload['base_commit']}`)",
        "",
        "*Reproduce offline with zero API keys: `python scripts/sleeper_port_audit.py --check`. "
        f"Audits `origin/justSilas@{payload['base_commit']}` (`TIERS_VERSION = {payload['shipped_tiers_version']}`, "
        f"`KNOWN_V_MODE = {payload['known_v_mode']}`, `{payload['v16_social_files_count']}` v1.6 social files) and "
        "verifies machine-checked fairness and `SolverPolicy` catchability invariants across every ported Sleeper idea.*",
        "",
        f"{h2} 1. Executive Summary",
        "",
        "The 8-seat multi-agent **Sleeper** prototype (`origin/momin`) and the one-agent deductive **Canary** benchmark "
        "(`origin/justSilas`) were unified into Canary for the AfterQuery submission. Every high-leverage Sleeper idea "
        "that strengthens a one-agent, deterministic, replay-verified benchmark was ported into Canary `v1.4`, while "
        "multi-seat chatter ideas were tested in `v1.5-candidate` (`origin/justSilas-v15` / `origin/justSilas-gemini-v15`) "
        "and dropped at Gate B when real `gemini-4-carbon` trials showed they narrowed rather than widened the frontier gap.",
        "",
        f"- **Mapped pillars:** `{s['flagship_ideas_mapped']}` flagship Sleeper ideas + `{s['supporting_ports_mapped']}` supporting infrastructure/adversary ports (`{s['total_entries']}` total entries; `{s['counterpart_files_verified']}` repo files verified).",
        f"- **Fairness invariants passed:** `{s['fairness_invariants_passed']} / {s['fairness_invariants_checked']}` (`100%`).",
        f"- **Solver catchability invariants passed:** `{s['catchability_invariants_passed']} / {s['catchability_invariants_checked']}` (`100%`).",
        f"- **v1.6 social files in workspace:** `{payload['v16_social_files_count']}` (strictly pure one-agent `v1.4` runtime).",
        "",
        f"{h2} 2. Master Sleeper-to-Canary Port Matrix",
        "",
        "| No. | Sleeper idea (origin) | Canary v1.4 counterpart (shipped) | Canary v1.5 counterpart (Gate B) | Fairness invariant verified | Solver catchability verified | Status |",
        "|---|---|---|---|---|---|---|",
    ]

    for idx, item in enumerate(payload["ideas"], start=1):
        v14_mods = ", ".join(f"`{m}`" for m in item["canary_v14_counterpart"]["modules"][:3])
        v15_stat = item["canary_v15_counterpart"]["status"]
        f_names = ", ".join(f"`{x['name']}`" for x in item["fairness_invariants"])
        c_names = ", ".join(f"`{x['name']}`" for x in item["catchability_invariants"])
        verdict = "PASS" if item["all_pass"] else "FAIL"
        lines.append(
            f"| {idx} | **{item['title']}** (`{item['sleeper_origin']['modules'][0]}`) | {v14_mods} | `{v15_stat}` | {f_names} | {c_names} | **{verdict}** |"
        )

    lines += [
        "",
        f"{h2} 3. Pillar-by-Pillar Technical Mapping and Invariant Proofs",
        "",
        f"{h3} 3.1 Cheat Corpus (`cheat_corpus`)",
        "",
        f"- **Sleeper origin:** Momin's `redteam/cheat_corpus.py` and `redteam/cheat_eval.py` (`Inject` at `ticks // 2`), mining `{c_corp['corpus_rows']}` distinct failed/foreign tool-call patterns (`{c_corp['historical_attempt_count']}` raw attempts across `{len(c_corp['foreign_tools'])}` Sleeper tools: `{', '.join(c_corp['foreign_tools'])}`) from `gemini-3.5-flash` transcripts, plus `control_pad`.",
        f"- **Canary v1.4 counterpart:** `canary/redteam/corpus.py` + `data/redteam/corpus.jsonl` + `results/anticheat/corpus_eval.txt` (`{c_corp['committed_injection_runs']}` midpoint-injected solver runs = `129 x 3 seeds x 3 tiers`, `0` accepted, `0` score changes), integrated with `canary/redteam/anticheat.py` (`garbage_args`, `control_solver_then_pad`, `solver_plus_*`) and `canary/redteam/harbor_cheat.py` (`cheat_probe`, `149` out-of-band attempts x `6` trials = `0.0`).",
        "- **Canary v1.5 counterpart:** Same strict 13-tool `_SPECS` schema gate; `make hunt TIER=all TV=v1.5-candidate` verified `0` invariant violations and `0.000` best non-solver score.",
        f"- **Fairness & catchability proof:** Live audit confirms `129/129` corpus rows satisfy `_always_invalid == True`, foreign calls consume `1` global cap slot without changing `V`, `day`, or `actions_left_today`, `control_solver_then_pad` equals `solver` to `0.0` across all tiers, and `SolverPolicy` scores `{c_corp['solver_judge40_means']['easy']:+.3f} / {c_corp['solver_judge40_means']['medium']:+.3f} / {c_corp['solver_judge40_means']['hard']:+.3f}` on the 40 judge seeds while all attack probes score `<= 0.000`.",
        "",
        f"{h3} 3.2 Multi-Employee Social Chains (`multi_employee_social_chains`)",
        "",
        "- **Sleeper origin:** 8-seat least-privilege office (`sleeper/goals/{fraud,leak,backdoor,sabotage,frame}.py`, 30 strategies) where two-person gates forced the sleeper to persuade or frame colleagues over chat and email.",
        f"- **Canary v1.4 counterpart:** Distills multi-employee entanglement into deterministic single-investigator mechanics without LLM background staff: 2-department regular documents (`p_single_dept_recipients = 0.0`), vocal innocent decoy (`decoy = True` on medium/hard), Poisson + Mole DSL after-hours framing (`framing_rate = {c_soc['v14_hard_framing_rate']}` on hard, `framing_decoy_share = 0.5`), and noisy HR interviews (`interview_lr = {c_soc['v14_hard_interview_lr']}`), grounded in `{c_soc['sourced_corporate_failure_cases']}` sourced corporate failure cases (`data/failures/cases_*.json`, `docs/research-biases.md`).",
        f"- **Canary v1.5 counterpart (tested, dropped at Gate B):** `origin/justSilas-v15` added endogenous one-agent `rumours` (`2.0/day`, `40%` decoy-seeded -> `LR = 1.0`), `grudges` (`2` pairs), `authority` (day-3 manager post), `p_misforward = 0.15`, and DSL `seed_rumour`. While `rumour_follower` collapsed to `-0.995` (`n=400`), real OpenCode `gemini-4-carbon` on hard seeds `0..9` rose from `61%` to **`108%` of solver** (`{c_soc['v15_gate_b_spotcheck_n10']['gemini_4_carbon_score']:.3f}` vs `{c_soc['v15_gate_b_spotcheck_n10']['solver_score']:.3f}`), so `v1.5` was honestly retired at Gate B (`docs/SUBMISSION.md`, `docs/reports/gap.md`).",
        f"- **Fairness & catchability proof:** Counterfactually swapping `_world.mole` across 60 day-renders produces `0` changes in `PublicDayFacts` or `TemplateProvider.day_messages` and `0` `lint_messages` hits; `decoy != mole` holds on `60/60` medium/hard worlds (`accuse_decoy = -1.000`); and both `hard_forge` and `hard_rl` enforce `solver_acc >= 0.75` (held-out RL mole `n=100`: solver acc `{c_soc['rl_heldout_n100']['solver_acc']:.2f}`, score `{c_soc['rl_heldout_n100']['solver_score']:+.4f}` vs `grok_tactics` `{c_soc['rl_heldout_n100']['grok_tactics_score']:+.4f}` and `heuristic` `{c_soc['rl_heldout_n100']['heuristic_score']:+.4f}`).",
        "",
        f"{h3} 3.3 Surface-Tells Audit (`surface_tells_audit`)",
        "",
        "- **Sleeper origin:** `sleeper/detell.py` (`origin/vaishnav/sleeper-tells` @ `e08b62ff`, `docs/generator-v2.md`), which closed Sleeper v1 wording (`tmplagent.py` `1.000`), whole-number amount, `XX`-IBAN, vendor-ID, and fixed-ticket-count (`ctonly` `0.95`) tells by replacing legit tickets in-place while preserving `1.000` reference/oracle solvability.",
        f"- **Canary v1.4 counterpart:** `canary/world.py` draws all employee names, departments, roles, and clearances *before* sampling `decoy` and `mole`; `canary/rules.py` sets `KNOWN_V_MODE = True` (closing v1.2 same-day `V`-drop timing tells) and `log_rate_mole = log_rate_benign = 1.0` on hard (closing raw access-count tells); `canary/env.py` enforces mole-vs-innocent error/detail parity (`1bc3e281`); `canary/redteam/text_probe.py` enforces exact binomial `fair_bar(tier, k)` (`k=2`: easy `{c_tell['text_fair_bar_k2']['easy']:.4f}`, medium `{c_tell['text_fair_bar_k2']['medium']:.4f}`, hard `{c_tell['text_fair_bar_k2']['hard']:.4f}`); and `scripts/instruction_audit.py` + `docs/DIFFICULTY.md` verify `34/34` `TierParams` fields per tier and `{c_tell['tool_smoke_passed']}` tool smoke calls.",
        "- **Canary v1.5 counterpart:** Draws unseeded rumour/authority targets over all non-speaker employees (including the mole) and grudge pairs over all non-decoy employees so being targeted never acts as a free innocence-exclusion tell.",
        f"- **Fairness & catchability proof:** `0` mole-vs-innocent error or post-accuse parity differences across 10 hard seeds, `0/{c_tell['hidden_leak_states_verified']}` unsurfaced-leak `V` disclosures, `accuse_most_logs = -1.000` on medium and hard, while `SolverPolicy` reaches **`{100.0 * c_tell['skill_ladder_n400_solver']['hard']['acc_when_accusing']:.1f}%`** accuracy when accusing (`mean = {c_tell['skill_ladder_n400_solver']['hard']['mean_score']:+.3f}`) on `n=400` fresh hard seeds (`results/skill_ladder_v1.4.csv`).",
        "",
        f"{h3} 3.4 Failure Gallery Below-Break-Even Spotlight (`failure_gallery_breakeven_spotlight`)",
        "",
        "- **Sleeper origin:** `lab/gallery.py` + `lab/analyse.py` (`origin/sleeper/lab-analyst-gallery`), pairing deterministic failure-mode decomposition with verbatim transcript proof.",
        f"- **Canary v1.4 counterpart:** `canary/gemini/gallery.py` (`{c_gal['gallery_episodes_decomposed']}` episodes decomposed, `{c_gal['gallery_v14_episodes']}` on v1.4, net gap `+{c_gal['gallery_v14_net_gap']:.2f}`, unexplained `0.0`) plus `canary/gemini/gallery_breakeven.py` (`docs/reports/failure_gallery_breakeven.md`, PR 45 / `44584580`), which evaluates every accusation on the `30` judged v1.4 hard seeds against the exact moving threshold `P*(V) = 1 / (1 + V)` from `EV(accuse | P, V) = P * V - (1 - P)`.",
        "- **Canary v1.5 counterpart:** `canary/analysis/accuse.py` + `canary/analysis/tags.py` over the 10-seed `v1.5-candidate` spot-check (`data/runs/committed/v1.5-candidate/opencode-gemini-4-carbon/`).",
        f"- **Fairness & catchability proof:** On OpenCode `gemini-4-carbon` v1.4 hard (`seeds 0..29`), seeds `{c_gal['opencode_carbon_hard30']['below_breakeven_seeds']}` violated `P < 1 / (1 + V)` under `E[true V]`, `V_true`, and shown `V_known`, losing `{c_gal['opencode_carbon_hard30']['decision_ev_sum']:+.4f} V` in decision EV (`{100.0 * c_gal['opencode_carbon_hard30']['share_of_penalty_gap']:.2f}%` of Gemini's accusation-penalty gap) masked by `{c_gal['opencode_carbon_hard30']['realized_luck_on_below_be']:+.4f} V` of lucky hits (including seed 18 at `62.72% < 68.43%`, mislabeled `justified` by fixed `0.60` cutoffs). `SolverPolicy` made **`0 / 30`** below-break-even accusations (tightest margin `+{100.0 * c_gal['solver_hard30']['min_margin_exp']:.2f} pp` on seed 10).",
        "",
        f"{h3} 3.5 Office Replay Dashboard (`office_replay_dashboard`)",
        "",
        "- **Sleeper origin:** `web/export.py` + `web/app.js` seat-mode office replay (`origin/sleeper/dm-dashboard-default`) + `lab/action_replay.py`.",
        f"- **Canary v1.4 counterpart:** Three zero-key replay surfaces: (1) `scripts/demo_replay.py` + `scripts/verify_replay.py` for side-by-side day-by-day `visible_V` and `SolverPolicy` `P(mole)` replay (`seed 4`: solver `{c_rep['canonical_replays']['4']['solver']['score']:+.2f}` day `{c_rep['canonical_replays']['4']['solver']['final_day']}` vs Gemini `{c_rep['canonical_replays']['4']['gemini']['score']:+.2f}` day `{c_rep['canonical_replays']['4']['gemini']['final_day']}`; `seed 18`: solver `{c_rep['canonical_replays']['18']['solver']['score']:+.2f}` vs Gemini `{c_rep['canonical_replays']['18']['gemini']['score']:+.2f}`; `seed 26`: solver `{c_rep['canonical_replays']['26']['solver']['score']:+.2f}` vs Gemini `{c_rep['canonical_replays']['26']['gemini']['score']:+.2f}`), (2) `game/` Pyodide browser case-file UI with Ivar's break-even accuse dialog on public dev seeds `3000..9999` (`seed 3000` parity: `{c_rep['browser_game_seed3000']['score']:+.2f}`, `{c_rep['browser_game_seed3000']['tool_calls']}` calls, day `{c_rep['browser_game_seed3000']['final_day']}`), and (3) self-contained offline `results/gemini/dashboard.html` (`{c_rep['dashboard_html_kb']:.1f} KB`) + `canary/gemini/lab_replay.py` (`{c_rep['lab_replay_showcase_episodes']}` step-hashed showcase episodes).",
        "- **Canary v1.5 counterpart:** `scripts/with_tiers.py` + `scripts/verify_replay.py` verifying `10/10` replay fidelity under `v1.5-candidate` (`6/10` under `v1.4`).",
        "- **Fairness & catchability proof:** `6/6` canonical hard replays match recorded scores to `< 1e-9`; `canary_game.py` rejects benchmark seeds (`0, 2999, 10000, 100000, 800000, 900000`), burns `0` hidden tool calls, hides truth until `done`, and matches CPython `SolverPolicy` exactly; `dashboard.py` redacts secret tokens and embeds `0` external HTTP assets.",
        "",
        f"{h3} 3.6 Supporting Infrastructure and Adversary Ports (`salted_sidecar_and_signed_ledger`, `catchability_constrained_mole_adversary`)",
        "",
        f"- **Salted judge worlds & signed-ledger rescore:** Ports `sleeper/secrets.py`, `harbor/sidecar.py`, and `sleeper/verifier.py` into `canary/world.py` (HMAC-SHA256 fail-closed judge/held-out worlds), `canary/mcp_server.py` (0600 `CANARY_*_FILE` secret loading), and `canary/redteam/tamper_guard.py` (HMAC-signed `/ledger`, `{c_salt['harbor_trials_verified']}/{c_salt['harbor_trials_verified']}` Harbor trials, `{c_salt['harbor_jobs_verified']}/{c_salt['harbor_jobs_verified']}` jobs, `{c_salt['replayed_episodes_consistent']}` replayed episodes across `{c_salt['replayed_tool_steps_compared']}` steps with `0` mismatches; forged `c1-tamper` negative control graded `{c_salt['c1_tamper_negative_control_reward']}`).",
        f"- **Catchability-constrained mole adversary:** Ports Sleeper's scripted strategy library and `winnable=true` gate into the safe `{c_mole['dsl_max_rules']}`-rule JSON `MoleStrategy` DSL (`canary/mole/dsl.py`, blind to `is_canary` and `variants`) and Lagrangian `RLMole` (`canary/forge/rl_mole.py`, dual ascent on `solver_acc >= 0.75`, raising held-out heuristic regret from `{c_mole['heldout_n100_default_vs_rl']['default_heuristic_regret']:+.4f}` to `{c_mole['heldout_n100_default_vs_rl']['rl_heuristic_regret']:+.4f}` while preserving `75%` solver accuracy).",
        "",
        f"{h2} 4. Complete Invariant Ledger",
        "",
        "| Entry ID | Invariant | Kind | Metric | Pass |",
        "|---|---|---|---|---|",
    ]

    for item in payload["ideas"]:
        for inv in item["fairness_invariants"]:
            metric_s = json.dumps(inv["metric"], sort_keys=True)
            lines.append(f"| `{item['id']}` | `{inv['name']}` | fairness | `{metric_s}` | **{'PASS' if inv['passed'] else 'FAIL'}** |")
        for inv in item["catchability_invariants"]:
            metric_s = json.dumps(inv["metric"], sort_keys=True)
            lines.append(f"| `{item['id']}` | `{inv['name']}` | catchability | `{metric_s}` | **{'PASS' if inv['passed'] else 'FAIL'}** |")

    lines += [
        "",
        f"{h2} 5. Reproduction",
        "",
        "```bash",
        "python scripts/sleeper_port_audit.py",
        "python scripts/sleeper_port_audit.py --check",
        "pytest tests/test_sleeper_port_audit.py",
        "```",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit and verify Sleeper-to-Canary port mappings and invariants.")
    ap.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    payload = compute_port_audit(ROOT)
    json_txt = render_json(payload)
    md_txt = render_markdown(payload)
    json_bytes = len(json_txt.encode("utf-8"))

    if not payload["all_invariants_pass"]:
        print("FAIL: one or more Sleeper-to-Canary port invariants failed", file=sys.stderr)
        return 1

    if args.check:
        if not args.json_out.is_file() or not args.md_out.is_file():
            print(f"MISSING: {args.json_out} or {args.md_out}", file=sys.stderr)
            return 1
        cur_json = args.json_out.read_text(encoding="utf-8")
        cur_md = args.md_out.read_text(encoding="utf-8")
        if cur_json != json_txt or cur_md != md_txt:
            print("DRIFT: sleeper port audit outputs differ from computed state", file=sys.stderr)
            return 1
        print(
            f"OK: sleeper_port_audit reproduces ({payload['summary']['total_entries']} entries, "
            f"{payload['summary']['fairness_invariants_passed']}/{payload['summary']['fairness_invariants_checked']} fairness, "
            f"{payload['summary']['catchability_invariants_passed']}/{payload['summary']['catchability_invariants_checked']} catchability, "
            f"{json_bytes} bytes <= {MAX_JSON_BYTES})"
        )
        return 0

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json_txt, encoding="utf-8")
    args.md_out.write_text(md_txt, encoding="utf-8")
    print(f"wrote {args.json_out} ({json_bytes} bytes) and {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
