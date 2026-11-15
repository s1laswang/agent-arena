from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS

ROOT = Path(__file__).resolve().parents[2]
REL_JSON = Path("results") / "gemini" / "out_think_gemini.json"
REL_CASES_JS = Path("demo") / "out-think-gemini" / "cases.js"
REL_DOC = Path("docs") / "demo" / "CASEBOOK.md"

THINKING_LEVEL_ORDER: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")

ALLOWED_PRE_DECISION_TOOLS: frozenset[str] = frozenset(
    {
        "status",
        "list_employees",
        "list_documents",
        "read_access_logs",
        "search_messages",
        "read_message",
        "interview",
        "plant_canary",
        "check_leak_feed",
        "restrict_access",
        "unrestrict_access",
        "advance_day",
    }
)

EXPECTED_VERDICT_LABELS: tuple[str, ...] = (
    "CAUTIOUS HOLD FIRE",
    "FALSE ACCUSATION (-1.00)",
    "LUCKY GUESS (BELOW BREAK-EVEN)",
    "OPTIMAL ACCUSATION",
    "OPTIMAL HOLD FIRE",
    "OVER-CAUTIOUS DELAY",
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
H1 = HASH_CHAR
H2 = HASH_CHAR * 2
H3 = HASH_CHAR * 3
FORBIDDEN_NET = "fetch" + "("

CASES_JS_DATA_RE = re.compile(r"^\s*var\s+data\s*=\s*(\{.*\});\s*$", re.MULTILINE)


def round4(val: float) -> float:
    return math.floor((float(val) * 10000.0) + 0.5) / 10000.0


def round6(val: float) -> float:
    return math.floor((float(val) * 1000000.0) + 0.5) / 1000000.0


def fmt_signed(val: float, decimals: int = 2) -> str:
    rounded = round(float(val), decimals)
    if abs(rounded) < 0.5 * (10 ** (-decimals)):
        rounded = 0.0
    sign = "+" if rounded >= 0.0 else "-"
    return f"{sign}{abs(rounded):.{decimals}f}"


def fmt_mean_ladder(val: float) -> str:
    txt = f"{abs(float(val)):.4f}".rstrip("0")
    if txt.endswith("."):
        txt += "0"
    sign = "+" if float(val) >= 0.0 else "-"
    return f"{sign}{txt}"


def extract_cases_js_payload(js_text: str) -> dict[str, Any]:
    for token in (
        "window.OUTTHINK_DATA = data;",
        "window.OUTTHINK_CASES = data.cases;",
        "module.exports = data;",
    ):
        if token not in js_text:
            raise ValueError(f"cases.js missing expected export token: {token}")
    match = CASES_JS_DATA_RE.search(js_text)
    if match is None:
        raise ValueError("cases.js missing 'var data = {...};' assignment")
    parsed = json.loads(match.group(1))
    if not isinstance(parsed, dict):
        raise ValueError("cases.js payload must decode to a JSON object")
    return parsed


def evaluate_judge_call(
    case_obj: dict[str, Any],
    action: str,
    suspect_id: str | None = None,
) -> dict[str, Any]:
    slv = case_obj.get("solver") or {}
    val = float(case_obj["value_at_decision"])
    mole = str(case_obj["true_mole"])
    top_prob = float(slv.get("top_prob") or 0.0)
    be_prob = float(
        slv.get("break_even_prob")
        if slv.get("break_even_prob") is not None
        else (1.0 / (1.0 + val) if val > 0.0 else 1.0)
    )
    rec = str(slv.get("recommended_call") or "hold_fire")
    norm_action = "accuse" if action == "accuse" else "hold_fire"
    norm_suspect = str(suspect_id) if suspect_id is not None else None

    if norm_action == "accuse":
        correct = bool(norm_suspect is not None and norm_suspect == mole)
        optimal = bool(correct and (rec != "hold_fire" or top_prob >= be_prob))
        score = round4(val) if correct else -1.0
        if correct and optimal:
            verdict = "OPTIMAL ACCUSATION"
        elif correct:
            verdict = "LUCKY GUESS (BELOW BREAK-EVEN)"
        else:
            verdict = "FALSE ACCUSATION (-1.00)"
        return {
            "action": "accuse",
            "suspect_id": norm_suspect,
            "correct": correct,
            "optimal": optimal,
            "score": score,
            "verdict_label": verdict,
            "true_mole": mole,
        }

    correct = bool(rec == "hold_fire" or top_prob < 0.95)
    optimal = bool(rec == "hold_fire")
    if top_prob >= 0.98 and rec != "hold_fire":
        score = round4(max(0.0, val - 0.12))
        verdict = "OVER-CAUTIOUS DELAY"
    else:
        raw_hold = (
            slv["ev_hold_fire"]
            if slv.get("ev_hold_fire") is not None
            else slv.get("final_score", 0.0)
        )
        score = round4(float(raw_hold))
        verdict = "OPTIMAL HOLD FIRE" if optimal else "CAUTIOUS HOLD FIRE"
    return {
        "action": "hold_fire",
        "suspect_id": None,
        "correct": correct,
        "optimal": optimal,
        "score": score,
        "verdict_label": verdict,
        "true_mole": mole,
    }


def summarize_records(records: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    by_level: dict[str, dict[str, Any]] = {
        lv: {
            "thinking_level": lv,
            "count": 0,
            "score_sum": 0.0,
            "mean_score": 0.0,
            "right_count": 0,
            "accuracy": 0.0,
            "total_cost_usd": 0.0,
            "total_thinking_tokens": 0,
            "judge_outscored_count": 0,
        }
        for lv in THINKING_LEVEL_ORDER
    }

    judge_score_sum = 0.0
    judge_right = 0
    judge_optimal = 0
    solver_score_sum = 0.0
    solver_right = 0

    for case_obj, eval_res in records:
        j_score = float(eval_res["score"])
        judge_score_sum += j_score
        if eval_res["correct"]:
            judge_right += 1
        if eval_res["optimal"]:
            judge_optimal += 1

        slv = case_obj.get("solver") or {}
        solver_score_sum += float(slv.get("final_score") or 0.0)
        if slv.get("correct"):
            solver_right += 1

        for lv_entry in case_obj.get("thinking_levels") or []:
            lv_key = str(lv_entry["thinking_level"])
            bucket = by_level[lv_key]
            lv_score = float(lv_entry["score"])
            bucket["count"] += 1
            bucket["score_sum"] += lv_score
            if lv_entry.get("correct"):
                bucket["right_count"] += 1
            bucket["total_cost_usd"] += float(lv_entry["cost_usd"])
            bucket["total_thinking_tokens"] += int(lv_entry["thinking_tokens"])
            if j_score > lv_score:
                bucket["judge_outscored_count"] += 1

    n = len(records)
    for lv_key in THINKING_LEVEL_ORDER:
        b = by_level[lv_key]
        cnt = int(b["count"])
        b["score_sum"] = round4(b["score_sum"])
        b["mean_score"] = round4(b["score_sum"] / cnt) if cnt > 0 else 0.0
        b["accuracy"] = round4(b["right_count"] / cnt) if cnt > 0 else 0.0
        b["total_cost_usd"] = round6(b["total_cost_usd"])
        b["total_thinking_tokens"] = int(b["total_thinking_tokens"])

    return {
        "cases_played": n,
        "judge": {
            "score_sum": round4(judge_score_sum),
            "mean_score": round4(judge_score_sum / n) if n > 0 else 0.0,
            "right_count": judge_right,
            "optimal_count": judge_optimal,
            "accuracy": round4(judge_right / n) if n > 0 else 0.0,
            "optimal_rate": round4(judge_optimal / n) if n > 0 else 0.0,
            "cost_usd": 0.0,
        },
        "solver": {
            "score_sum": round4(solver_score_sum),
            "mean_score": round4(solver_score_sum / n) if n > 0 else 0.0,
            "right_count": solver_right,
            "optimal_count": solver_right,
            "accuracy": round4(solver_right / n) if n > 0 else 0.0,
            "optimal_rate": round4(solver_right / n) if n > 0 else 0.0,
            "cost_usd": 0.0,
        },
        "by_level": by_level,
    }


def validate_casebook_sources(
    json_payload: dict[str, Any],
    js_payload: dict[str, Any],
    raw_json_text: str,
    raw_js_text: str,
) -> list[str]:
    errors: list[str] = []

    for label, txt in (("out_think_gemini.json", raw_json_text), ("cases.js", raw_js_text)):
        if EM_DASH in txt or EN_DASH in txt:
            errors.append(f"{label} contains forbidden em/en dash character")
        if FORBIDDEN_NET in txt:
            errors.append(f"{label} contains forbidden network call token")

    if json_payload != js_payload:
        errors.append("out_think_gemini.json and demo/out-think-gemini/cases.js payloads differ")

    meta = json_payload.get("meta")
    cases = json_payload.get("cases")
    if not isinstance(meta, dict):
        errors.append("missing meta object in out_think_gemini.json")
        return errors
    if not isinstance(cases, list) or len(cases) != 12:
        errors.append(f"expected exactly 12 playable cases, got {len(cases) if isinstance(cases, list) else 'non-list'}")
        return errors

    if meta.get("tiers_version") != "v1.4":
        errors.append(f"expected tiers_version 'v1.4', got {meta.get('tiers_version')!r}")
    if meta.get("isBootstrapFallback") is not False:
        errors.append("isBootstrapFallback must be False")
    if int(meta.get("total_episodes") or 0) != 550:
        errors.append(f"expected 550 total_episodes, got {meta.get('total_episodes')!r}")
    if abs(float(meta.get("total_cost_usd") or 0.0) - 262.7061) > 1e-4:
        errors.append(f"expected $262.7061 total_cost_usd, got {meta.get('total_cost_usd')!r}")
    if int(meta.get("case_count") or 0) != len(cases):
        errors.append("meta.case_count mismatch with len(cases)")

    seen_ids: set[str] = set()
    hold_cnt = 0
    accuse_cnt = 0
    level_cnt = 0
    levels_seen: set[str] = set()

    for c in cases:
        cid = str(c.get("id") or "")
        if not cid or cid in seen_ids:
            errors.append(f"invalid or duplicate case_id {cid!r}")
        seen_ids.add(cid)

        seed = int(c.get("seed", -1))
        if seed in HELDOUT_SEEDS or seed in JUDGE_SEEDS or not (0 <= seed < 10_000):
            errors.append(f"{cid}: seed {seed} violates public-seed isolation")

        d_day = int(c.get("decision_day") or 0)
        d_step = int(c.get("decision_step") or 0)
        v_d = float(c.get("value_at_decision") or 0.0)
        if d_day < 1 or d_step < 1 or d_step != len(c.get("tool_steps") or []):
            errors.append(f"{cid}: invalid decision_day/decision_step vs tool_steps")
        if not (0.0 < v_d <= 1.0):
            errors.append(f"{cid}: value_at_decision {v_d} outside (0, 1]")

        suspect_ids = [str(s["id"]) for s in (c.get("suspects") or [])]
        if str(c.get("true_mole") or "") not in suspect_ids:
            errors.append(f"{cid}: true_mole not in suspects")

        for st_idx, st in enumerate(c.get("tool_steps") or []):
            if int(st.get("t", -1)) != st_idx or int(st.get("day", 0)) > d_day:
                errors.append(f"{cid}: pre-decision tool_step[{st_idx}] out of bounds")
            if str(st.get("tool") or "") not in ALLOWED_PRE_DECISION_TOOLS:
                errors.append(f"{cid}: disallowed pre-decision tool {st.get('tool')!r}")

        slv = c.get("solver") or {}
        post = slv.get("posterior") or {}
        p_sum = sum(float(v) for v in post.values())
        if abs(p_sum - 1.0) > 1e-3:
            errors.append(f"{cid}: posterior sum {p_sum:.6f} != 1.0")
        expected_be = round4(1.0 / (1.0 + v_d))
        if abs(float(slv.get("break_even_prob") or 0.0) - expected_be) > 1e-3:
            errors.append(f"{cid}: break_even_prob mismatch vs 1/(1+V_d)")

        top_prob = float(slv.get("top_prob") or 0.0)
        be_prob = float(slv.get("break_even_prob") or 0.0)
        rec = str(slv.get("recommended_call") or "")
        if rec == "accuse":
            accuse_cnt += 1
            if top_prob < be_prob:
                errors.append(f"{cid}: accuse recommended with top_prob < break_even_prob")
        elif rec == "hold_fire":
            hold_cnt += 1
            if top_prob >= be_prob:
                errors.append(f"{cid}: hold_fire recommended with top_prob >= break_even_prob")
        else:
            errors.append(f"{cid}: invalid recommended_call {rec!r}")

        t_levels = c.get("thinking_levels") or []
        if len(t_levels) < 2:
            errors.append(f"{cid}: fewer than 2 thinking_levels")
        for lv in t_levels:
            level_cnt += 1
            lv_name = str(lv.get("thinking_level") or "")
            levels_seen.add(lv_name)
            if not lv.get("run_id"):
                errors.append(f"{cid}/{lv_name}: missing run_id")
            if int(lv.get("ledger_calls") or 0) <= 0 or float(lv.get("cost_usd") or 0.0) <= 0.0:
                errors.append(f"{cid}/{lv_name}: non-positive ledger_calls or cost_usd")
            if not lv.get("correct") and not lv.get("failure_tag"):
                errors.append(f"{cid}/{lv_name}: incorrect trajectory missing failure_tag")

        cmc = c.get("cross_model_carbon") or []
        if not isinstance(cmc, list) or len(cmc) < 1:
            errors.append(f"{cid}: missing cross_model_carbon reference")

    if hold_cnt != int(meta.get("hold_fire_cases") or 0) or accuse_cnt != int(meta.get("accuse_cases") or 0):
        errors.append("hold_fire_cases / accuse_cases count mismatch with case solver recommendations")
    if level_cnt != int(meta.get("level_run_count") or 0) or level_cnt != 39:
        errors.append(f"expected 39 paired thinking_level trajectories, got {level_cnt}")
    if set(THINKING_LEVEL_ORDER) != levels_seen:
        errors.append(f"thinking_levels missing coverage: got {sorted(levels_seen)}")

    return errors


def build_casebook_report(root: Path = ROOT) -> dict[str, Any]:
    root_dir = root.resolve()
    json_path = root_dir / REL_JSON
    js_path = root_dir / REL_CASES_JS

    if not json_path.is_file():
        raise FileNotFoundError(f"missing required dataset JSON: {json_path}")
    if not js_path.is_file():
        raise FileNotFoundError(f"missing required browser bundle: {js_path}")

    raw_json_text = json_path.read_text(encoding="utf-8")
    raw_js_text = js_path.read_text(encoding="utf-8")
    json_payload = json.loads(raw_json_text)
    js_payload = extract_cases_js_payload(raw_js_text)

    errors = validate_casebook_sources(json_payload, js_payload, raw_json_text, raw_js_text)
    meta = json_payload["meta"]
    raw_cases = json_payload["cases"]

    strategy_records: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        "optimal_judge": [],
        "always_hold_fire": [],
        "always_accuse_mole": [],
        "opposite_of_solver": [],
        "wrong_accusation": [],
    }
    verdicts_seen: set[str] = set()
    case_rows: list[dict[str, Any]] = []

    total_level_cost = 0.0
    total_level_thinking_tokens = 0
    total_level_ledger_calls = 0
    carbon_case_count = 0
    carbon_run_count = 0
    ladder_matrix_cells = 0

    for c in raw_cases:
        slv = c["solver"]
        rec = str(slv["recommended_call"])
        mole = str(c["true_mole"])
        suspect_ids = [str(s["id"]) for s in c["suspects"]]
        wrong_id = next(sid for sid in suspect_ids if sid != mole)

        opt_call = ("accuse", mole) if rec == "accuse" else ("hold_fire", None)
        opp_call = ("hold_fire", None) if rec == "accuse" else ("accuse", str(slv["top_suspect"]))

        calls_by_strategy = {
            "optimal_judge": opt_call,
            "always_hold_fire": ("hold_fire", None),
            "always_accuse_mole": ("accuse", mole),
            "opposite_of_solver": opp_call,
            "wrong_accusation": ("accuse", wrong_id),
        }

        per_strategy_eval: dict[str, dict[str, Any]] = {}
        for skey, (act, sid) in calls_by_strategy.items():
            ev_res = evaluate_judge_call(c, act, sid)
            verdicts_seen.add(str(ev_res["verdict_label"]))
            strategy_records[skey].append((c, ev_res))
            per_strategy_eval[skey] = ev_res

        lv_rows: list[dict[str, Any]] = []
        for lv in c["thinking_levels"]:
            total_level_cost += float(lv["cost_usd"])
            total_level_thinking_tokens += int(lv["thinking_tokens"])
            total_level_ledger_calls += int(lv["ledger_calls"])
            lv_rows.append(
                {
                    "thinking_level": str(lv["thinking_level"]),
                    "model": str(lv["model"]),
                    "call_at_t": str(lv["call_at_t"]),
                    "accused": lv["accused"],
                    "accused_day": lv["accused_day"],
                    "end_reason": str(lv["end_reason"]),
                    "correct": bool(lv["correct"]),
                    "score": round4(float(lv["score"])),
                    "regret_total": round4(float(lv["regret_total"])),
                    "thinking_tokens": int(lv["thinking_tokens"]),
                    "input_tokens": int(lv["input_tokens"]),
                    "output_tokens": int(lv["output_tokens"]),
                    "cached_tokens": int(lv["cached_tokens"]),
                    "calls": int(lv["calls"]),
                    "ledger_calls": int(lv["ledger_calls"]),
                    "cost_usd": round6(float(lv["cost_usd"])),
                    "failure_tag": lv.get("failure_tag"),
                    "run_id": str(lv["run_id"]),
                }
            )

        cmc_list = c.get("cross_model_carbon") or []
        if cmc_list:
            carbon_case_count += 1
        carbon_rows: list[dict[str, Any]] = []
        for cmc in cmc_list:
            carbon_run_count += 1
            carbon_rows.append(
                {
                    "model": str(cmc["model"]),
                    "thinking_level": str(cmc["thinking_level"]),
                    "accused": cmc.get("accused"),
                    "accused_day": cmc.get("accused_day"),
                    "correct": bool(cmc["correct"]),
                    "score": round4(float(cmc["score"])),
                    "thinking_tokens": int(cmc["thinking_tokens"]),
                    "cost_usd": round6(float(cmc["cost_usd"])),
                    "run_id": str(cmc["run_id"]),
                }
            )

        lmat = c.get("ladder_matrix") or {}
        for m_cells in lmat.values():
            if isinstance(m_cells, dict):
                ladder_matrix_cells += len(m_cells)

        opt_eval = per_strategy_eval["optimal_judge"]
        case_rows.append(
            {
                "case_id": str(c["id"]),
                "title": str(c["title"]),
                "company": str(c["company"]),
                "model": str(c["model"]),
                "anchor_level": str(c["anchor_level"]),
                "tier": str(c["tier"]),
                "seed": int(c["seed"]),
                "world": f"{c['tier']}:{c['seed']}",
                "decision_day": int(c["decision_day"]),
                "decision_step": int(c["decision_step"]),
                "value_at_decision": round4(float(c["value_at_decision"])),
                "break_even_prob": round4(float(slv["break_even_prob"])),
                "true_mole": mole,
                "top_suspect": str(slv["top_suspect"]),
                "top_prob": round4(float(slv["top_prob"])),
                "recommended_call": rec,
                "ev_accuse_top": round4(float(slv["ev_accuse_top"])),
                "ev_hold_fire": round4(float(slv["ev_hold_fire"])),
                "optimal_judge_ev": round4(float(opt_eval["score"])),
                "optimal_judge_verdict": str(opt_eval["verdict_label"]),
                "solver_ev": round4(float(slv["final_score"])),
                "solver_final_accused": slv.get("final_accused"),
                "solver_final_day": int(slv["final_day"]),
                "solver_correct": bool(slv["correct"]),
                "evidence_counts": {
                    "suspects": len(c["suspects"]),
                    "canaries": len(c["canaries"]),
                    "leaks": len(c["leaks"]),
                    "access_logs": len(c["access_logs"]),
                    "comms": len(c["comms"]),
                    "tool_steps": len(c["tool_steps"]),
                },
                "thinking_levels": lv_rows,
                "cross_model_carbon": carbon_rows,
            }
        )

    summaries = {skey: summarize_records(recs) for skey, recs in strategy_records.items()}
    opt_summary = summaries["optimal_judge"]
    by_level = opt_summary["by_level"]

    mean_chain = [float(by_level[lv]["mean_score"]) for lv in THINKING_LEVEL_ORDER]
    is_monotonic = all(mean_chain[i] < mean_chain[i + 1] for i in range(len(mean_chain) - 1))
    if not is_monotonic:
        errors.append(f"thinking_level mean_score ladder is not strictly monotonic: {mean_chain}")
    if tuple(sorted(verdicts_seen)) != EXPECTED_VERDICT_LABELS:
        errors.append(f"verdict label coverage mismatch: {sorted(verdicts_seen)}")

    solver_stats = opt_summary["solver"]
    strategy_table = [
        {
            "id": "optimal_judge",
            "label": "Optimal Judge",
            **opt_summary["judge"],
        },
        {
            "id": "bayesian_solver",
            "label": "Bayesian Solver",
            **solver_stats,
        },
        {
            "id": "always_hold_fire",
            "label": "Always-Hold-Fire",
            **summaries["always_hold_fire"]["judge"],
        },
        {
            "id": "always_accuse_mole",
            "label": "Oracle Mole-Now (Hindsight)",
            **summaries["always_accuse_mole"]["judge"],
        },
        {
            "id": "opposite_of_solver",
            "label": "Opposite-of-Solver",
            **summaries["opposite_of_solver"]["judge"],
        },
        {
            "id": "wrong_accusation",
            "label": "Wrong-Accusation",
            **summaries["wrong_accusation"]["judge"],
        },
    ]

    ladder_progression = " -> ".join(
        f"{lv} {fmt_mean_ladder(by_level[lv]['mean_score'])}" for lv in THINKING_LEVEL_ORDER
    )

    unique_worlds = sorted({f"{c['tier']}:{c['seed']}" for c in raw_cases})
    ladder_rows = [by_level[lv] for lv in THINKING_LEVEL_ORDER]

    return {
        "verified": len(errors) == 0,
        "errors": errors,
        "provenance": {
            "title": "Out-Think Gemini: Casebook and Scoreboard Provenance",
            "tiers_version": str(meta["tiers_version"]),
            "source_json": REL_JSON.as_posix(),
            "source_js": REL_CASES_JS.as_posix(),
            "source_doc": REL_DOC.as_posix(),
            "source_episodes": str(meta["source_episodes"]),
            "source_ledger": str(meta["source_ledger"]),
            "source_solver": str(meta["source_solver"]),
            "json_js_identical": json_payload == js_payload,
            "is_bootstrap_fallback": bool(meta["isBootstrapFallback"]),
            "total_episodes": int(meta["total_episodes"]),
            "ladder_corpus_episodes": int(meta["ladder_corpus_episodes"]),
            "ledger_unique_runs": int(meta["ledger_unique_runs"]),
            "corpus_cost_usd": round4(float(meta["total_cost_usd"])),
            "case_count": len(case_rows),
            "unique_world_count": len(unique_worlds),
            "unique_worlds": unique_worlds,
            "hold_fire_cases": int(meta["hold_fire_cases"]),
            "accuse_cases": int(meta["accuse_cases"]),
            "models": list(meta["models"]),
            "thinking_levels": list(THINKING_LEVEL_ORDER),
            "level_run_count": sum(len(c["thinking_levels"]) for c in case_rows),
            "level_total_thinking_tokens": total_level_thinking_tokens,
            "level_total_ledger_calls": total_level_ledger_calls,
            "level_total_cost_usd": round6(total_level_cost),
            "cross_model_carbon_case_count": carbon_case_count,
            "cross_model_carbon_run_count": carbon_run_count,
            "ladder_matrix_cell_count": ladder_matrix_cells,
        },
        "benchmarks": {
            "cases_played": len(case_rows),
            "verdicts_seen": sorted(verdicts_seen),
            "strategies": strategy_table,
            "strategies_by_id": {row["id"]: row for row in strategy_table},
            "thinking_ladder": ladder_rows,
            "thinking_ladder_by_level": by_level,
            "monotonic_mean_score": is_monotonic,
            "ladder_progression": ladder_progression,
        },
        "cases": case_rows,
    }


def render_casebook_markdown(report: dict[str, Any]) -> str:
    prov = report["provenance"]
    bench = report["benchmarks"]
    cases = report["cases"]

    models_csv = ", ".join(f"`{m}`" for m in prov["models"])
    worlds_csv = ", ".join(f"`{w}`" for w in prov["unique_worlds"])

    lines: list[str] = [
        f"{H1} Out-Think Gemini: Casebook and Scoreboard Provenance",
        "",
        (
            f"Deterministic, zero-API-call provenance and scoreboard reference for **Out-Think Gemini** "
            f"(`{prov['source_json']}` and `{prov['source_js']}`, `tiers_version = {prov['tiers_version']}`). "
            f"All **{prov['case_count']} playable decision snapshots** come from **{prov['total_episodes']} recorded "
            f"ladder episodes** (`{prov['ledger_unique_runs']}` unique ledger runs, **${prov['corpus_cost_usd']:.4f}** "
            f"verified API spend in `{prov['source_episodes']}` and `{prov['source_ledger']}`), paired against the "
            f"exact Bayesian `SolverPolicy` reference (`{prov['source_solver']}`). Across the {prov['case_count']} "
            f"cases, the bundle ships **{prov['level_run_count']} paired `thinking_level` trajectories** across "
            f"`minimal`, `low`, `medium`, `high`, and `xhigh` (**{prov['level_total_thinking_tokens']:,}** thinking "
            f"tokens, **{prov['level_total_ledger_calls']:,}** ledger calls, **${prov['level_total_cost_usd']:.6f}** "
            f"direct trajectory spend) plus **{prov['cross_model_carbon_case_count']} `cross_model_carbon` case "
            f"comparisons** ({prov['cross_model_carbon_run_count']} `gemini-4-carbon` runs)."
        ),
        "",
        f"{H2} 1. Corpus and Bundle Provenance Summary",
        "",
        "| Provenance Field | Verified Value |",
        "| --- | --- |",
        f"| Canonical JSON Artifact | `{prov['source_json']}` |",
        f"| Browser UMD Bundle | `{prov['source_js']}` (`json_js_identical = {prov['json_js_identical']}`, `isBootstrapFallback = {prov['is_bootstrap_fallback']}`) |",
        f"| Source Ladder Episodes | `{prov['source_episodes']}` (**{prov['total_episodes']}** valid recorded episodes) |",
        f"| Source Cost Ledger | `{prov['source_ledger']}` (**{prov['ledger_unique_runs']}** unique ledger runs, **${prov['corpus_cost_usd']:.4f}** total spend) |",
        f"| Reference Solver Corpus | `{prov['source_solver']}` (`tiers_version = {prov['tiers_version']}`) |",
        f"| Playable Decision Cases | **{prov['case_count']}** (`{prov['hold_fire_cases']}` `hold_fire`, `{prov['accuse_cases']}` `accuse`; 6 `hard`, 6 `medium`) |",
        f"| Public World Seeds ({prov['unique_world_count']} unique) | {worlds_csv} (0 overlap with `HELDOUT_SEEDS` or `JUDGE_SEEDS`) |",
        f"| Anchor Gemini Models ({len(prov['models'])}) | {models_csv} |",
        f"| Paired `thinking_level` Runs | **{prov['level_run_count']}** across `minimal` (4), `low` (12), `medium` (10), `high` (11), `xhigh` (2) |",
        f"| Paired Trajectory Token & Cost Totals | **{prov['level_total_thinking_tokens']:,}** thinking tokens, **{prov['level_total_ledger_calls']:,}** ledger calls, **${prov['level_total_cost_usd']:.6f}** |",
        f"| `cross_model_carbon` Comparisons | **{prov['cross_model_carbon_case_count']}/12** cases covered (**{prov['cross_model_carbon_run_count']}** `gemini-4-carbon` runs) |",
        f"| Embedded `ladder_matrix` Cells | **{prov['ladder_matrix_cell_count']}** cross-model / cross-level cells on the same `(tier, seed)` worlds |",
        "",
        f"{H2} 2. Aggregate Scoreboard Benchmarks and Thinking Ladder",
        "",
        f"{H3} 2.1 Judge and Reference Policy Scoreboard ({bench['cases_played']} Cases)",
        "",
        "| Benchmark Policy | Total Score | Mean Score | Right Calls | Accuracy | Optimal Calls | Optimal Rate | Compute Spend |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    n_cases = int(bench["cases_played"])
    for srow in bench["strategies"]:
        lines.append(
            f"| **{srow['label']}** | `{fmt_signed(srow['score_sum'], 2)}` | `{fmt_signed(srow['mean_score'], 4)}` "
            f"| `{srow['right_count']}/{n_cases}` | `{srow['accuracy'] * 100.0:.1f}%` "
            f"| `{srow['optimal_count']}/{n_cases}` | `{srow['optimal_rate'] * 100.0:.1f}%` "
            f"| `${srow['cost_usd']:.2f}` |"
        )

    lines.extend(
        [
            "",
            (
                "- **Optimal Judge (`+7.80`, `12/12` optimal, `$0`) vs Bayesian Solver (`+7.90`, `12/12`):** "
                "Optimal Judge acts from each anchor model's frozen pre-accusation state at `(decision_day, decision_step)` "
                "(earning `V_d` on the 4 `accuse` cases `+0.71 + 0.73 + 0.50 + 0.82 = +2.76` and `ev_hold_fire` on the 8 "
                "`hold_fire` cases `+5.04`, summing to `+7.80`). Full-episode `SolverPolicy` designs its own canary splits "
                "from `t = 0` (`+7.90` across the 12 case worlds, isolating `hard:1` by day 7 for `+0.69` rather than day 14 "
                "`V_d = 0.50` on `flash35-hard-1`)."
            ),
            (
                "- **Always-Hold-Fire (`+7.42`) vs Optimal Judge (`+7.80`):** Holding fire when `top_prob >= 0.98` incurs "
                "the `-0.12` `OVER-CAUTIOUS DELAY` penalty on `carbon-medium-4`, `flash35-hard-1`, and `argon-medium-6` "
                "(`-0.36` combined) plus `-0.02` continuation decay on `carbon-hard-1` (`+0.69` vs `+0.71`)."
            ),
            (
                "- **Opposite-of-Solver (`-2.49`) and Wrong-Accusation (`-12.00`):** Inverting `SolverPolicy` delays all 4 "
                "pinned accusations and gambles below break-even on all 8 `hold_fire` cases (`2/12` lucky hits on "
                "`flash38-hard-7` and `argon-hard-18` where `top_suspect == true_mole`, `6/12` `-1.00` false accusations, "
                "`0/12` optimal). Accusing a non-mole suspect on every case scores `-1.00 * 12 = -12.00`."
            ),
            "",
            f"{H3} 2.2 Monotonic Gemini `thinking_level` Ladder (39 Paired Trajectories)",
            "",
            f"Monotonic Gemini `thinking_level` mean score progression: **`{bench['ladder_progression']}`**.",
            "",
            "| `thinking_level` | Runs (`n`) | Total Score | Mean Score | Right Calls | Accuracy | Thinking Tokens | Total Cost (USD) | Optimal Judge Outscored |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    tot_n = 0
    tot_score = 0.0
    tot_right = 0
    tot_tok = 0
    tot_cost = 0.0
    tot_outscored = 0
    for lrow in bench["thinking_ladder"]:
        cnt = int(lrow["count"])
        tot_n += cnt
        tot_score += float(lrow["score_sum"])
        tot_right += int(lrow["right_count"])
        tot_tok += int(lrow["total_thinking_tokens"])
        tot_cost += float(lrow["total_cost_usd"])
        tot_outscored += int(lrow["judge_outscored_count"])
        lines.append(
            f"| `{lrow['thinking_level']}` | {cnt} | `{fmt_signed(lrow['score_sum'], 2)}` "
            f"| `{fmt_mean_ladder(lrow['mean_score'])}` (`{fmt_signed(lrow['mean_score'], 4)}`) "
            f"| `{lrow['right_count']}/{cnt}` | `{lrow['accuracy'] * 100.0:.2f}%` "
            f"| {lrow['total_thinking_tokens']:,} | `${lrow['total_cost_usd']:.6f}` "
            f"| `{lrow['judge_outscored_count']}/{cnt}` |"
        )

    tot_acc = (tot_right / tot_n * 100.0) if tot_n > 0 else 0.0
    tot_mean = (tot_score / tot_n) if tot_n > 0 else 0.0
    lines.append(
        f"| **Combined (`all 5 levels`)** | **{tot_n}** | **`{fmt_signed(tot_score, 2)}`** "
        f"| **`{fmt_signed(tot_mean, 4)}`** | **`{tot_right}/{tot_n}`** | **`{tot_acc:.2f}%`** "
        f"| **{tot_tok:,}** | **`${tot_cost:.6f}`** | **`{tot_outscored}/{tot_n}`** |"
    )

    lines.extend(
        [
            "",
            f"{H2} 3. Playable 12-Case Decision Threshold and EV Master Table",
            "",
            "| `case_id` | `model` | `tier` | `seed` | `decision_day` | `decision_step` | `value_at_decision` (`V_d`) | `break_even_prob` (`1/(1+V_d)`) | `SolverPolicy` `top_prob` (`top_suspect`) | `recommended_call` | `EV(accuse_top)` | Optimal Judge EV | Solver EV | Per-Level Scores / Thinking Tokens / Costs |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )

    for c in cases:
        lv_parts = [
            f"`{lv['thinking_level']}`: {fmt_signed(lv['score'], 2)} ({lv['thinking_tokens']:,}t, ${lv['cost_usd']:.4f})"
            for lv in c["thinking_levels"]
        ]
        lv_summary = "; ".join(lv_parts)
        lines.append(
            f"| `{c['case_id']}` | `{c['model']}` | `{c['tier']}` | {c['seed']} "
            f"| {c['decision_day']} | {c['decision_step']} "
            f"| `{c['value_at_decision']:.2f}` | `{c['break_even_prob']:.4f}` "
            f"| `{c['top_prob']:.4f}` (`{c['top_suspect']}`) | `{c['recommended_call']}` "
            f"| `{fmt_signed(c['ev_accuse_top'], 4)}` | `{fmt_signed(c['optimal_judge_ev'], 2)}` "
            f"| `{fmt_signed(c['solver_ev'], 2)}` | {lv_summary} |"
        )

    lines.extend(
        [
            "",
            f"{H2} 4. Per-Level Trajectory Provenance Table (All 39 Paired Runs)",
            "",
            "| `case_id` | `model` | `thinking_level` | `call_at_t` | Accused (Day) | Correct | Score | Regret | Thinking Tokens | In / Out / Cached Tokens | Ledger Calls | Cost (USD) | Failure Tag | `run_id` |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |",
        ]
    )

    for c in cases:
        for lv in c["thinking_levels"]:
            acc_txt = (
                f"`{lv['accused']}` (d{lv['accused_day']})"
                if lv["accused"] is not None
                else f"`none` ({lv['end_reason']})"
            )
            tag_txt = f"`{lv['failure_tag']}`" if lv["failure_tag"] else "`none`"
            io_txt = f"{lv['input_tokens']:,} / {lv['output_tokens']:,} / {lv['cached_tokens']:,}"
            lines.append(
                f"| `{c['case_id']}` | `{lv['model']}` | `{lv['thinking_level']}` | `{lv['call_at_t']}` "
                f"| {acc_txt} | `{'yes' if lv['correct'] else 'no'}` | `{fmt_signed(lv['score'], 2)}` "
                f"| `{lv['regret_total']:.2f}` | {lv['thinking_tokens']:,} | {io_txt} "
                f"| {lv['ledger_calls']} | `${lv['cost_usd']:.6f}` | {tag_txt} | `{lv['run_id']}` |"
            )

    lines.extend(
        [
            "",
            f"{H2} 5. Cross-Model `gemini-4-carbon` Reference Strips (12 Cases, 23 Runs)",
            "",
            "| `case_id` | World | Anchor Model | Carbon Level | Accused (Day) | Correct | Score | Thinking Tokens | Cost (USD) | `run_id` |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )

    for c in cases:
        for cmc in c["cross_model_carbon"]:
            c_acc = (
                f"`{cmc['accused']}` (d{cmc['accused_day']})"
                if cmc["accused"] is not None
                else "`none` (horizon)"
            )
            lines.append(
                f"| `{c['case_id']}` | `{c['world']}` | `{c['model']}` | `{cmc['thinking_level']}` "
                f"| {c_acc} | `{'yes' if cmc['correct'] else 'no'}` | `{fmt_signed(cmc['score'], 2)}` "
                f"| {cmc['thinking_tokens']:,} | `${cmc['cost_usd']:.6f}` | `{cmc['run_id']}` |"
            )

    lines.extend(
        [
            "",
            f"{H2} 6. Deterministic Stopping Equations and Keyless Verification",
            "",
            "- **Break-even accusation threshold:** Accusing suspect `s` at value `V_d` yields `+V_d` if `s == true_mole` and `-1.00` otherwise, so `EV(accuse s) = p(s) * V_d - (1 - p(s)) >= 0` if and only if `p(s) >= 1 / (1 + V_d)`.",
            "- **Six deterministic UI / VM verdict labels (`demo/out-think-gemini/engine.js`):** `OPTIMAL ACCUSATION`, `OPTIMAL HOLD FIRE`, `CAUTIOUS HOLD FIRE`, `OVER-CAUTIOUS DELAY`, `LUCKY GUESS (BELOW BREAK-EVEN)`, and `FALSE ACCUSATION (-1.00)`.",
            "- **Keyless regeneration and drift check (0 API calls):**",
            "  - `GEMINI_API_KEY=\"\" GOOGLE_API_KEY=\"\" PYTHONPATH=. python -m canary.gemini.outthink --check`",
            "  - `GEMINI_API_KEY=\"\" GOOGLE_API_KEY=\"\" PYTHONPATH=. python -m canary.gemini.outthink_casebook --write-doc`",
            "  - `GEMINI_API_KEY=\"\" GOOGLE_API_KEY=\"\" PYTHONPATH=. python -m canary.gemini.outthink_casebook --check`",
            "  - `GEMINI_API_KEY=\"\" GOOGLE_API_KEY=\"\" PYTHONPATH=. python -m canary.gemini.outthink_casebook --json`",
            "",
        ]
    )

    return "\n".join(lines)


def resolve_doc_path(root_dir: Path, raw_arg: str) -> Path:
    if not raw_arg:
        return root_dir / REL_DOC
    cand = Path(raw_arg)
    return cand if cand.is_absolute() else (root_dir / cand)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canary.gemini.outthink_casebook")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-doc", nargs="?", const="", default=None)
    parser.add_argument("--check", nargs="?", const="", default=None)
    args = parser.parse_args(argv)

    root_dir = args.root.resolve()
    try:
        report = build_casebook_report(root_dir)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    if not report["verified"]:
        for err in report["errors"]:
            sys.stderr.write(f"ERROR: {err}\n")
        if args.json:
            sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=True) + "\n")
        return 1

    expected_md = render_casebook_markdown(report)
    expected_json_str = json.dumps(report, indent=2, ensure_ascii=True) + "\n"

    for label, txt in (("markdown", expected_md), ("json", expected_json_str)):
        if EM_DASH in txt or EN_DASH in txt:
            sys.stderr.write(f"ERROR: forbidden dash character in generated {label}\n")
            return 1
        if FORBIDDEN_NET in txt:
            sys.stderr.write(f"ERROR: forbidden network token in generated {label}\n")
            return 1

    if args.write_doc is not None:
        doc_out = resolve_doc_path(root_dir, args.write_doc)
        doc_out.parent.mkdir(parents=True, exist_ok=True)
        doc_out.write_text(expected_md, encoding="utf-8")

    if args.check is not None:
        doc_check = resolve_doc_path(root_dir, args.check)
        if not doc_check.is_file():
            sys.stderr.write(f"ERROR: missing casebook doc {doc_check}\n")
            return 1
        actual_md = doc_check.read_text(encoding="utf-8")
        if EM_DASH in actual_md or EN_DASH in actual_md:
            sys.stderr.write(f"ERROR: forbidden dash character in {doc_check}\n")
            return 1
        if actual_md != expected_md:
            sys.stderr.write(f"ERROR: {doc_check} is out of date with deterministic casebook build\n")
            return 1
        if args.json:
            sys.stdout.write(expected_json_str)
        else:
            prov = report["provenance"]
            sys.stdout.write(
                f"OK: {prov['case_count']} cases, {prov['level_run_count']} ladder runs, "
                f"and {doc_check} verified.\n"
            )
        return 0

    if args.json:
        sys.stdout.write(expected_json_str)
        return 0

    if args.write_doc is not None:
        doc_out = resolve_doc_path(root_dir, args.write_doc)
        sys.stdout.write(
            f"Wrote {doc_out} ({report['provenance']['case_count']} cases, "
            f"{report['provenance']['level_run_count']} ladder runs).\n"
        )
        return 0

    sys.stdout.write(expected_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
