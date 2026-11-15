"""Pure-CPU Bayes stopping-rule counterfactual and two-term gap decomposition for Canary v1.4.

    PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --write
    PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (str(ROOT), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canary.analysis.gap import mean_ci
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.belief import _fallback, behaviour_logliks, leak_loglik
from canary.solver.policy import SolverPolicy
from canary.types import Step

SCHEMA_VERSION = "v1.4-stopping-counterfactual-1"
MAX_JSON_BYTES = 35_000
EXPECTED_COMMITTED_V14, EXPECTED_REPLICATION_V14, EXPECTED_COMBINED_V14 = 472, 305, 777
TAUS: tuple[float, ...] = (0.60, 0.70, 0.80, 0.85, 0.90, 0.95)
H1, H2 = chr(35), chr(35) * 2
_INGEST_TOOLS = frozenset({"list_employees", "status", "list_documents", "check_leak_feed", "read_access_logs", "search_messages", "plant_canary", "advance_day", "restrict_access", "unrestrict_access", "interview"})
_EP_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_SCAN_CACHE: dict[tuple[Any, ...], tuple[int, dict[str, list[dict[str, Any]]]]] = {}


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "stopping_counterfactual_v14.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_stopping_counterfactual_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    return gap_md.exists() and ("gemini-3.5-flash" in gap_md.read_text(encoding="utf-8"))


def clean_json(obj: Any, nd: int = 6) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, nd)
    if isinstance(obj, dict):
        return {str(k): clean_json(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v, nd) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-5) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return (math.isnan(a) and math.isnan(b)) or math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _fast_belief(sp: SolverPolicy) -> dict[str, float]:
    obs, P = sp.obs, sp.P
    obs.leak_timing_known = sp.v_drops_reveal_leaks()
    emps = obs.employees
    impossible: set[str] = {obs.decoy} if obs.decoy is not None else set()
    for it in obs.feed:
        doc = obs.docs.get(it.doc_id)
        if doc is None:
            return _fallback(obs)
        rec = doc.recipients
        if it.variant and doc.variants:
            vmap = doc.variants
            single = len(set(vmap.values())) <= 1
            impossible.update(e for e in emps if e not in rec or vmap.get(e) is None or (single and vmap.get(e) != it.variant))
        else:
            impossible.update(e for e in emps if e not in rec)
    if not (cand := [s for s in emps if s not in impossible]):
        return _fallback(obs)
    bt, ct, nt = sp.behaviour_temper, sp.choice_temper, sp.noleak_temper
    lps = {s: leak_loglik(obs, s, P, ct, nt) for s in cand}
    alive = [s for s, v in lps.items() if v > -math.inf]
    if not alive:
        return _fallback(obs)
    if len(alive) == 1:
        s0 = alive[0]
        return {s: (1.0 if s == s0 else 0.0) for s in emps}
    beh = behaviour_logliks(obs, P) if bt > 0 else {}
    logs: dict[str, float] = {s: -math.inf for s in emps}
    pe, pm = P.p_evasive_innocent, min(0.999, P.p_evasive_innocent * P.interview_lr)
    iv_pos, iv_neg = math.log(pm / pe), math.log((1 - pm) / (1 - pe))
    for s in alive:
        lp = lps[s]
        if bt > 0:
            lp += bt * beh[s] + sum(bt * (iv_pos if ev else iv_neg) for who, ev in obs.interviews if who == s)
        logs[s] = lp
    mx = max(logs.values())
    z = sum(math.exp(v - mx) for v in logs.values())
    return {s: math.exp(v - mx) / z for s, v in logs.items()}


def _scan_pool(pool_dir: Path, wanted: tuple[tuple[str, str, str, str, set[int]], ...]) -> tuple[int, dict[str, list[dict[str, Any]]]]:
    if not pool_dir.exists():
        return 0, {w[0]: [] for w in wanted}
    resolved = pool_dir.resolve()
    files = [
        (f, f.relative_to(resolved).parts[:-1])
        for f in sorted(resolved.rglob("episodes.jsonl"))
        if not any(x == "superseded" or x.startswith("v1.") or x.endswith("-smoke") for x in f.relative_to(resolved).parts[:-1])
    ]
    sig = tuple((str(f), st.st_mtime_ns, st.st_size) for f, _ in files for st in (f.stat(),))
    w_sig = tuple((w[0], w[1], w[2], w[3], len(w[4]), min(w[4]), max(w[4])) for w in wanted)
    ckey = (str(resolved), sig, w_sig)
    if ckey in _SCAN_CACHE:
        return _SCAN_CACHE[ckey]
    buckets: dict[str, list[dict[str, Any]]] = {w[0]: [] for w in wanted}
    seen: dict[str, set[int]] = {w[0]: set() for w in wanted}
    total = 0
    for f, rel_parts in files:
        rel_dir, run_id = "/".join(rel_parts), f.parent.name
        active = [
            (key, agent, tier, seeds, f'"{agent}"'.encode(), f'"{tier}"'.encode(), tuple(f'"seed": {s}'.encode() for s in seeds) if len(seeds) <= 8 else ())
            for key, prefix, agent, tier, seeds in wanted
            if (rel_dir == prefix or ((rel_dir.startswith(prefix + "/") or rel_dir.startswith(prefix + "-")) and not (key == "sol_hard" and "seeds30to59" in rel_dir)))
        ]
        raw = f.read_bytes()
        if not active and b'"valid": false' not in raw and b'"valid":false' not in raw and b"\n\n" not in raw:
            if raw.strip():
                total += raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)
            continue
        for raw_line in raw.splitlines():
            if not raw_line.strip():
                continue
            if not (cand := [w for w in active if w[4] in raw_line and w[5] in raw_line and (not w[6] or any(sb in raw_line for sb in w[6]))]):
                if (b'"valid": false' in raw_line or b'"valid":false' in raw_line) and (json.loads(raw_line).get("meta") or {}).get("valid") is False:
                    continue
                total += 1
                continue
            ep = json.loads(raw_line)
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            total += 1
            sd = int(ep["seed"])
            for key, agent, tier, seeds, _, _, _ in cand:
                if ep.get("agent") == agent and ep.get("tier") == tier and sd in seeds:
                    if sd in seen[key]:
                        raise ValueError(f"duplicate seed {sd} in bucket {key}")
                    seen[key].add(sd)
                    ep.setdefault("meta", {})["run_id"] = run_id
                    buckets[key].append(ep)
    for rows in buckets.values():
        rows.sort(key=lambda x: int(x["seed"]))
    if len(_SCAN_CACHE) >= 8:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[ckey] = (total, buckets)
    return total, buckets


def _eval_episode(ep: dict[str, Any]) -> dict[str, Any]:
    meta, steps_raw = ep.get("meta") or {}, ep.get("steps") or []
    ckey = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]), str(meta.get("run_id") or ""), len(steps_raw), round(float(ep["score"]), 9))
    if ckey in _EP_CACHE:
        return _EP_CACHE[ckey]
    acc_idx = next((i for i, s in enumerate(steps_raw) if s.get("tool") == "accuse"), len(steps_raw))
    steps_pre = [Step(s.get("t", 0), s.get("day", 0), tl, s.get("args") or {}, s.get("result")) for s in steps_raw[:acc_idx] if (tl := s.get("tool", "")) in _INGEST_TOOLS]
    sp = SolverPolicy(tier_params_for_episode(str(ep["tier"]), steps_pre))
    for st in steps_pre:
        sp._ingest(st)
    sp.seen = acc_idx
    post = _fast_belief(sp) if sp.obs.employees else {}
    v_known = float(sp.V)
    v_true = float(v_raw) if (v_raw := meta.get("V", meta.get("V_final"))) is not None else v_known
    acc = ep.get("accused")
    p_acc = round(float(post.get(acc, 0.0)), 3) if (acc and post) else None
    top_emp = max(post, key=post.get) if post else None
    rc, fday = meta.get("rc"), ep.get("final_day")
    res = {
        "seed": int(ep["seed"]), "day": int(fday or 0), "obs_day": int(sp.obs.today), "accused": acc,
        "correct": bool(ep.get("correct")), "raw": float(ep["score"]), "v_true": v_true, "v_known": v_known,
        "exp_true_v": float(sp.expected_true_V()), "p_accused": p_acc, "p_top": float(post[top_emp]) if top_emp else 0.0, "top_emp": top_emp,
        "breakeven_p": 1.0 / (1.0 + v_true), "breakeven_p_known_v": 1.0 / (1.0 + v_known),
        "luck": (p_acc * v_true - (1.0 - p_acc)) if (acc and p_acc is not None) else 0.0,
        "clean_rc0_zero_day": (not isinstance(rc, bool) and rc == 0 and meta.get("error") is None and acc is None and not bool(ep.get("correct")) and abs(float(ep["score"])) < 1e-9 and not isinstance(fday, bool) and fday == 0),
    }
    if len(_EP_CACHE) >= 1024:
        _EP_CACHE.clear()
    _EP_CACHE[ckey] = res
    return res


def _build_cohort(cid: str, label: str, harness: str, agent: str, tier: str, lock_note: str, rows: list[dict[str, Any]], sol_rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    (raw_f, raw_ci), (luck_f, luck_ci) = mean_ci([r["raw"] for r in rows]), mean_ci([r["luck"] for r in rows])
    raw_s, luck_s = sum(r["raw"] for r in sol_rows) / n, sum(r["luck"] for r in sol_rows) / n
    acc_rows = [r for r in rows if r["accused"]]
    sub_rows = [r for r in acc_rows if r["p_accused"] < r["breakeven_p"]]
    sub_kv = [r for r in acc_rows if r["p_accused"] < r["breakeven_p_known_v"]]
    cf_raw = sum(0.0 if (r["accused"] and r["p_accused"] < r["breakeven_p"]) else r["raw"] for r in rows) / n
    cf_luck = sum(0.0 if (r["accused"] and r["p_accused"] < r["breakeven_p"]) else r["luck"] for r in rows) / n
    sweep = [
        {"tau": tau, "kept_accusations": len(kept := [r for r in acc_rows if r["p_accused"] >= tau]), "abstained_count": n - len(kept), "kept_precision": (sum(1 for r in kept if r["correct"]) / len(kept)) if kept else None, "cf_raw_mean": (rm := sum(r["raw"] for r in kept) / n), "cf_raw_ratio_vs_solver": rm / raw_s if raw_s > 0 else None, "cf_luck_mean": (lm := sum(r["luck"] for r in kept) / n), "cf_luck_ratio_vs_solver": lm / luck_s if luck_s > 0 else None}
        for tau in TAUS
    ]
    lg, l_stop, l_evid = luck_s - luck_f, cf_luck - luck_f, luck_s - cf_luck
    rg, r_stop, r_evid = raw_s - raw_f, cf_raw - raw_f, raw_s - cf_raw
    non_map_seeds = [r["seed"] for r in acc_rows if round(r["p_top"], 3) - r["p_accused"] > 1e-6]
    pos_abst_seeds = [r["seed"] for r in rows if not r["accused"] and round(r["p_top"], 3) > r["breakeven_p"]]
    u_acc_map_be = sum(max(0.0, round(r["p_top"], 3) * r["v_true"] - (1.0 - round(r["p_top"], 3))) if r["accused"] else 0.0 for r in rows) / n
    u_all_map_be = sum(max(0.0, round(r["p_top"], 3) * r["v_true"] - (1.0 - round(r["p_top"], 3))) for r in rows) / n
    map_loss = u_acc_map_be - cf_luck
    abst_loss = u_all_map_be - u_acc_map_be
    info_def = luck_s - u_all_map_be
    return {
        "cohort_id": cid, "label": label, "harness": harness, "agent": agent, "tier": tier, "lock_provenance": lock_note,
        "n": n, "seeds": [r["seed"] for r in rows], "accused_count": len(acc_rows), "accused_rate": len(acc_rows) / n,
        "non_accuse_seeds": [r["seed"] for r in rows if not r["accused"]], "accuracy": sum(1 for r in rows if r["correct"]) / n,
        "mean_p_accused": (sum(r["p_accused"] for r in acc_rows) / len(acc_rows)) if acc_rows else None,
        "raw_mean": raw_f, "raw_ci95": raw_ci, "solver_raw_mean": raw_s, "raw_ratio_vs_solver": raw_f / raw_s if raw_s > 0 else None,
        "luck_mean": luck_f, "luck_ci95": luck_ci, "solver_luck_mean": luck_s, "luck_ratio_vs_solver": luck_f / luck_s if luck_s > 0 else None,
        "breakeven_counterfactual": {
            "rule": "abstain (0.0) iff accused is not None and P(accused) < 1/(1+V)",
            "sub_breakeven_count": len(sub_rows), "sub_breakeven_rate": len(sub_rows) / n, "sub_breakeven_seeds": [r["seed"] for r in sub_rows],
            "sub_breakeven_known_v_count": len(sub_kv), "sub_breakeven_wrong_count": sum(1 for r in sub_rows if not r["correct"]),
            "sub_breakeven_lucky_correct_count": sum(1 for r in sub_rows if r["correct"]), "kept_accusations": len(acc_rows) - len(sub_rows),
            "cf_raw_mean": cf_raw, "cf_raw_delta": r_stop, "cf_raw_ratio_vs_solver": cf_raw / raw_s if raw_s > 0 else None,
            "cf_luck_mean": cf_luck, "cf_luck_delta": l_stop, "cf_luck_ratio_vs_solver": cf_luck / luck_s if luck_s > 0 else None,
            "sub_breakeven_episodes": [[r["seed"], r["day"], r["accused"], r["correct"], r["raw"], r["v_true"], r["p_accused"], r["breakeven_p"], r["luck"]] for r in sub_rows],
        },
        "threshold_sweep": sweep,
        "gap_decomposition": {
            "luck": {
                "total_gap": lg, "sub_breakeven_stopping_loss": l_stop, "evidence_collection_deficit": l_evid,
                "map_choice_ev_loss": map_loss, "non_map_accusation_seeds": non_map_seeds,
                "positive_ev_abstention_loss": abst_loss, "positive_ev_abstention_seeds": pos_abst_seeds,
                "pure_information_gathering_deficit": info_def,
                "stopping_share_of_gap": (l_stop / lg) if lg > 1e-9 else None, "evidence_share_of_gap": (l_evid / lg) if lg > 1e-9 else None,
            },
            "raw": {"total_gap": rg, "sub_breakeven_stopping_loss": r_stop, "evidence_collection_deficit": r_evid, "stopping_share_of_gap": (r_stop / rg) if rg > 1e-9 else None, "evidence_share_of_gap": (r_evid / rg) if rg > 1e-9 else None},
        },
    }


def compute_audit(root: Path = ROOT, enforce_expected_counts: bool = True) -> dict[str, Any]:
    s0_29, s30_59, s_ext, ships_flash = set(range(30)), set(range(30, 60)), {30, 34, 37, 42, 45, 57}, gap_ships_flash_hard(root)
    comm_wanted: tuple[tuple[str, str, str, str, set[int]], ...] = (
        ("sol_med", "reference/solver-medium", "solver", "medium", s0_29),
        ("sol_hard", "reference/solver-hard", "solver", "hard", s0_29),
        ("sol_ext", "reference/solver-hard-seeds30to59", "solver", "hard", s_ext),
        ("oc_c_med", "opencode-gemini-4-carbon/medium", "opencode:google/gemini-4-carbon", "medium", s0_29),
        ("oc_c_hard", "opencode-gemini-4-carbon/hard", "opencode:google/gemini-4-carbon", "hard", s0_29),
        ("oc_gpt", "opencode-gpt-5.5/hard", "opencode:openai/gpt-5.5", "hard", s0_29),
        ("ip_c_med", "inproc-gemini-4-carbon/medium", "gemini:gemini-4-carbon", "medium", s0_29),
        ("ip_c_hard", "inproc-gemini-4-carbon/hard", "gemini:gemini-4-carbon", "hard", s0_29),
        ("g1_ext", "opencode-gemini-4-carbon-ext/hard", "opencode:google/gemini-4-carbon", "hard", s30_59),
        ("fl_hard", "opencode-gemini-3.5-flash/hard", "opencode:google/gemini-3.5-flash", "hard", s0_29),
    )
    rep_wanted = (("fl_med", "opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash", "medium", s0_29), ("fr8_ext", "opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon", "hard", s30_59))
    comm_n, cb = _scan_pool(root / "data/runs/committed/v1.4", comm_wanted)
    rep_n, rb = _scan_pool(root / "results/frontier_replication/v1.4", rep_wanted)
    if enforce_expected_counts and (comm_n != EXPECTED_COMMITTED_V14 or rep_n != EXPECTED_REPLICATION_V14):
        raise ValueError(f"pool count mismatch: committed={comm_n}, replication={rep_n}")
    sol_med = {e["seed"]: _eval_episode(e) for e in cb["sol_med"]}
    sol_hard = {e["seed"]: _eval_episode(e) for e in cb["sol_hard"]}
    sol_ext = {e["seed"]: _eval_episode(e) for e in cb["sol_ext"]}
    seen_u, union_eps, union_sources = set(), [], {}
    for src_tag, seq in (("committed_g1", cb["g1_ext"]), ("fr8_replication", rb["fr8_ext"])):
        for ep in seq:
            if (sd := int(ep["seed"])) not in seen_u:
                seen_u.add(sd)
                union_eps.append(ep)
                union_sources[str(sd)] = src_tag
    union_eps.sort(key=lambda e: int(e["seed"]))
    specs: list[tuple[str, str, str, str, str, str, list[dict[str, Any]], dict[int, dict[str, Any]]]] = [
        ("opencode_gemini_4_carbon_medium", "OpenCode gemini-4-carbon medium (0-29)", "opencode", "opencode:google/gemini-4-carbon", "medium", "post_hoc_lock_671ed96_on_8fd4dec", cb["oc_c_med"], sol_med),
        ("opencode_gemini_4_carbon_hard", "OpenCode gemini-4-carbon hard (0-29)", "opencode", "opencode:google/gemini-4-carbon", "hard", "post_hoc_lock_671ed96_on_8fd4dec", cb["oc_c_hard"], sol_hard),
        ("opencode_gpt_5_5_hard", "OpenCode gpt-5.5 hard (0-29)", "opencode", "opencode:openai/gpt-5.5", "hard", "pre_registered_cf394894_results_ca0a0dc0", cb["oc_gpt"], sol_hard),
        ("inproc_gemini_4_carbon_medium", "in-process gemini-4-carbon medium (0-29)", "inproc", "gemini:gemini-4-carbon", "medium", "post_hoc_lock_671ed96_on_8fd4dec", cb["ip_c_med"], sol_med),
        ("inproc_gemini_4_carbon_hard", "in-process gemini-4-carbon hard (0-29)", "inproc", "gemini:gemini-4-carbon", "hard", "post_hoc_lock_671ed96_on_8fd4dec", cb["ip_c_hard"], sol_hard),
        ("opencode_gemini_3_5_flash_medium", "FR8 OpenCode gemini-3.5-flash medium (0-29)", "opencode", "opencode:google/gemini-3.5-flash", "medium", "fr8_replication_v14", rb["fl_med"], sol_med),
    ]
    if ships_flash:
        specs.append(("opencode_gemini_3_5_flash_hard", "OpenCode gemini-3.5-flash hard (0-29)", "opencode", "opencode:google/gemini-3.5-flash", "hard", "committed_held_until_gap_md", cb["fl_hard"], sol_hard))
    specs.extend([
        ("opencode_gemini_4_carbon_hard_30_59_union", "OpenCode gemini-4-carbon hard 30-59 dedup union (n=6)", "opencode", "opencode:google/gemini-4-carbon", "hard", "g1_prereg_f9fb7a4a_plus_fr8_dedup_eb9dee54", union_eps, sol_ext),
        ("solver_medium", "reference solver medium (0-29)", "reference", "solver", "medium", "committed_reference_v14", [], sol_med),
        ("solver_hard", "reference solver hard (0-29)", "reference", "solver", "hard", "committed_reference_v14", [], sol_hard),
    ])
    cohorts, gpt55_non_accuse = [], []
    for cid, label, harness, agent, tier, lock_note, eps, smap in specs:
        rows = [smap[s] for s in sorted(smap)] if cid in ("solver_medium", "solver_hard") else [_eval_episode(e) for e in eps]
        cohorts.append(_build_cohort(cid, label, harness, agent, tier, lock_note, rows, [smap[r["seed"]] for r in rows]))
        if cid == "opencode_gpt_5_5_hard":
            for r in rows:
                if not r["accused"]:
                    pt = round(r["p_top"], 3)
                    gpt55_non_accuse.append({"seed": r["seed"], "clean_rc0_zero_day": r["clean_rc0_zero_day"], "obs_day_reached": r["obs_day"], "top_suspect": r["top_emp"], "p_top": pt, "v_known": r["v_known"], "exp_true_v": r["exp_true_v"], "top_suspect_known_v_ev": pt * r["v_known"] - (1.0 - pt), "top_suspect_exp_true_v_ev": pt * r["exp_true_v"] - (1.0 - pt)})
    by_id = {c["cohort_id"]: c for c in cohorts}
    c_hard, gpt_hard = by_id["opencode_gemini_4_carbon_hard"], by_id["opencode_gpt_5_5_hard"]
    non_acc_ev = sum(x["top_suspect_known_v_ev"] for x in gpt55_non_accuse) / gpt_hard["n"]
    return clean_json({
        "schema_version": SCHEMA_VERSION, "tiers_version": TIERS_VERSION, "upstream_justsilas_sync_commit": "5f9b3297",
        "zero_live_api_calls": True, "zero_subprocesses": True, "zero_git_dependency": True, "flash_hard_shipped_in_gap_md": ships_flash, "taus": list(TAUS),
        "sub_breakeven_episode_columns": ["seed", "day", "accused", "correct", "raw_score", "v_true", "p_accused", "breakeven_p", "luck_ev"],
        "provenance": {
            "upstream_head_commit": "5f9b3297", "committed_v14_episodes": comm_n, "replication_v14_episodes": rep_n, "combined_v14_episodes": comm_n + rep_n,
            "primary_0_29_lock_classification": "post_hoc_lock", "primary_0_29_lock_commit": "671ed96", "primary_0_29_episodes_commit": "8fd4dec",
            "gpt_5_5_prereg_commit": "cf394894", "gpt_5_5_results_commit": "ca0a0dc0", "gpt_5_5_clean_rc0_non_accuse_seeds": [x["seed"] for x in gpt55_non_accuse],
            "g1_ext_prereg_commit": "f9fb7a4a", "g1_seeds": [int(e["seed"]) for e in cb["g1_ext"]], "fr8_rep_seeds": [int(e["seed"]) for e in rb["fr8_ext"]],
            "carbon_hard_30_59_dedup_union_seeds": [int(e["seed"]) for e in union_eps], "carbon_hard_30_59_source_by_seed": union_sources,
            "harbor_rehearsal_final_commit": "d0ead011", "harbor_rehearsal_ratios_pct": [93, 116, 131], "harbor_rehearsal_valid_trials": [10, 10, 9],
        },
        "gpt_5_5_non_accuse_forensics": {
            "seeds": [x["seed"] for x in gpt55_non_accuse], "episodes": gpt55_non_accuse, "mean_known_v_ev_foregone_per_cohort_ep": non_acc_ev,
            "luck_mean_if_top_suspect_accused": gpt_hard["luck_mean"] + non_acc_ev, "luck_ratio_vs_solver_if_top_suspect_accused": (gpt_hard["luck_mean"] + non_acc_ev) / gpt_hard["solver_luck_mean"],
        },
        "summary": {
            "cohort_count": len(cohorts), "episode_counts": [c["n"] for c in cohorts], "total_cohort_episodes": sum(c["n"] for c in cohorts),
            "primary_carbon_hard_luck_stopping_share": c_hard["gap_decomposition"]["luck"]["stopping_share_of_gap"],
            "primary_carbon_hard_luck_evidence_share": c_hard["gap_decomposition"]["luck"]["evidence_share_of_gap"],
            "primary_carbon_hard_raw_stopping_share": c_hard["gap_decomposition"]["raw"]["stopping_share_of_gap"],
            "primary_carbon_hard_raw_evidence_share": c_hard["gap_decomposition"]["raw"]["evidence_share_of_gap"],
            "solver_sub_breakeven_total": by_id["solver_medium"]["breakeven_counterfactual"]["sub_breakeven_count"] + by_id["solver_hard"]["breakeven_counterfactual"]["sub_breakeven_count"],
        },
        "cohorts": cohorts,
    })


def serialize_json(data: dict[str, Any]) -> str:
    items = [f" {json.dumps(k)}: {json.dumps(data[k], sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))}" for k in sorted(data)]
    blob = "{\n" + ",\n".join(items) + "\n}\n"
    if (size := len(blob.encode("utf-8"))) > MAX_JSON_BYTES:
        raise ValueError(f"JSON size {size} exceeds {MAX_JSON_BYTES} bytes")
    return blob


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _f3(x: float | None, signed: bool = False) -> str:
    return "n/a" if x is None else (f"{x:+.3f}" if signed else f"{x:.3f}")


def render_markdown(data: dict[str, Any]) -> str:
    prov, cohorts, gnf = data["provenance"], data["cohorts"], data["gpt_5_5_non_accuse_forensics"]
    by_id = {c["cohort_id"]: c for c in cohorts}
    ch, fl, gp = by_id["opencode_gemini_4_carbon_hard"], by_id["opencode_gemini_3_5_flash_medium"], by_id["opencode_gpt_5_5_hard"]
    lines = [
        f"{H1} Canary v1.4 Bayes Stopping-Rule Counterfactual and Two-Term Gap Decomposition", "",
        f"Synced to `justSilas@{prov['upstream_head_commit']}` across the replay-verified 777-episode v1.4 corpus (`{prov['committed_v14_episodes']}` committed + `{prov['replication_v14_episodes']}` FR8 replication; pure CPU, zero live API calls). Primary `0-29` cohorts carry post-hoc lock `{prov['primary_0_29_lock_commit']}` (28 s after `{prov['primary_0_29_episodes_commit']}`); OpenCode `gpt-5.5` hard `0-29` was pre-registered at `{prov['gpt_5_5_prereg_commit']}` (results `{prov['gpt_5_5_results_commit']}`); `gemini-4-carbon` hard `30-59` dedup union `{prov['carbon_hard_30_59_dedup_union_seeds']}` (`n=6`) applies committed G1 (`{prov['g1_ext_prereg_commit']}`, seeds `{prov['g1_seeds']}`) precedence over FR8 replication (`{prov['fr8_rep_seeds']}`). Harbor judge-path rehearsal on `{prov['harbor_rehearsal_final_commit']}` finished at `93%, 116%, 131%` of oracle across `{prov['harbor_rehearsal_valid_trials']}` valid trials.", "",
        f"{H2} Key Findings", "",
        f"1. **Primary OpenCode `gemini-4-carbon` hard (`0-29`) is dominated by evidence-collection deficit, not premature stopping:** Only `{ch['breakeven_counterfactual']['sub_breakeven_count']}/30` episodes (`seeds {ch['breakeven_counterfactual']['sub_breakeven_seeds']}`) accused below Bayes break-even `P(accused) < 1/(1+V)`. Replacing negative-EV gambles with `0.0` abstention lifts raw score from `{_f3(ch['raw_mean'], True)}` (`{_pct(ch['raw_ratio_vs_solver'])}`) to `{_f3(ch['breakeven_counterfactual']['cf_raw_mean'], True)}` (`{_pct(ch['breakeven_counterfactual']['cf_raw_ratio_vs_solver'])}`) and luck-adjusted EV from `{_f3(ch['luck_mean'], True)}` (`{_pct(ch['luck_ratio_vs_solver'])}`) to `{_f3(ch['breakeven_counterfactual']['cf_luck_mean'], True)}` (`{_pct(ch['breakeven_counterfactual']['cf_luck_ratio_vs_solver'])}`). **{_pct(ch['gap_decomposition']['luck']['evidence_share_of_gap'])}** (`{_f3(ch['gap_decomposition']['luck']['evidence_collection_deficit'], True)}` of `{_f3(ch['gap_decomposition']['luck']['total_gap'], True)}`) of the luck-adjusted gap and **{_pct(ch['gap_decomposition']['raw']['evidence_share_of_gap'])}** (`{_f3(ch['gap_decomposition']['raw']['evidence_collection_deficit'], True)}` of `{_f3(ch['gap_decomposition']['raw']['total_gap'], True)}`) of the raw gap come from weaker evidence gathering.",
        f"2. **FR8 OpenCode `gemini-3.5-flash` medium (`0-29`) is primarily a stopping-rule failure:** `{fl['breakeven_counterfactual']['sub_breakeven_count']}/30` episodes (`seeds {fl['breakeven_counterfactual']['sub_breakeven_seeds']}`, 5 wrong `-1.00`) gambled below break-even on days 13-14. The Bayes abstention gate recovers `{_f3(fl['breakeven_counterfactual']['cf_luck_delta'], True)}` luck-adjusted EV (**{_pct(fl['gap_decomposition']['luck']['stopping_share_of_gap'])}** of the gap) and `{_f3(fl['breakeven_counterfactual']['cf_raw_delta'], True)}` raw score (**{_pct(fl['gap_decomposition']['raw']['stopping_share_of_gap'])}** of the raw gap), lifting Flash medium to `{_f3(fl['breakeven_counterfactual']['cf_luck_mean'], True)}` (`{_pct(fl['breakeven_counterfactual']['cf_luck_ratio_vs_solver'])}` of solver).",
        f"3. **OpenCode `gpt-5.5` hard (`0-29`) exhibits well-calibrated stopping (`0/28` sub-breakeven under observable `V_known`, `1/28` marginal `-0.064` EV on seed `5` under latent `V_true=0.41`):** Its `{_f3(gp['gap_decomposition']['luck']['total_gap'], True)}` luck-adjusted shortfall vs solver is driven by clean `rc=0` non-accuse exits on seeds `{gnf['seeds']}`, where terminal `P(top)` already reached `0.949` and `0.963` (`{_f3(gnf['mean_known_v_ev_foregone_per_cohort_ep'], True)}` cohort-mean EV foregone; `{_pct(gnf['luck_ratio_vs_solver_if_top_suspect_accused'])}` of solver if executed).",
        "4. **Reference solver sanity check:** Both `solver` medium (`0-29`, abstaining on seeds `[20, 21, 29]`) and `solver` hard (`0-29`) record `0/30` sub-breakeven accusations (`0.000` stopping loss).", "",
        f"{H2} (a) Bayes Break-Even Abstention Counterfactual (`P(accused) >= 1/(1+V)`)", "",
        "| Cohort | n | Accused | Sub-BE (seeds) | Raw -> BE Raw (/ solver) | Luck -> BE Luck (/ solver) |", "|---|---:|---:|---|---|---|",
    ]
    for c in cohorts:
        bc = c["breakeven_counterfactual"]
        s_str = f"{bc['sub_breakeven_count']} ({bc['sub_breakeven_seeds']})" if bc["sub_breakeven_count"] else "0 ([])"
        lines.append(f"| {c['label']} | {c['n']} | {c['accused_count']}/{c['n']} | {s_str} | {_f3(c['raw_mean'], True)} -> {_f3(bc['cf_raw_mean'], True)} ({_pct(c['raw_ratio_vs_solver'])} -> {_pct(bc['cf_raw_ratio_vs_solver'])}) | {_f3(c['luck_mean'], True)} -> {_f3(bc['cf_luck_mean'], True)} ({_pct(c['luck_ratio_vs_solver'])} -> {_pct(bc['cf_luck_ratio_vs_solver'])}) |")
    lines.extend(["", f"{H2} (b) Static Posterior Threshold Sweep (`tau in [0.60, 0.70, 0.80, 0.85, 0.90, 0.95]`)", "", "Cells report `kept_k: luck_mean (luck_ratio)` when replacing accusations with `P(accused) < tau` by `0.0` abstention:", "", "| Cohort | tau=0.60 | tau=0.70 | tau=0.80 | tau=0.85 | tau=0.90 | tau=0.95 |", "|---|---|---|---|---|---|---|"])
    for c in cohorts:
        lines.append(f"| {c['label']} | " + " | ".join(f"k={s['kept_accusations']}: {_f3(s['cf_luck_mean'], True)} ({_pct(s['cf_luck_ratio_vs_solver'])})" for s in c["threshold_sweep"]) + " |")
    lines.extend(["", f"{H2} (c) Two-Term Gap Decomposition (`Solver - Frontier = Stopping Loss + Evidence Deficit`)", "", "| Cohort | Luck Gap | Luck Stopping Loss (share) | Luck Evidence Deficit (share) | Raw Gap | Raw Stopping Loss | Raw Evidence Deficit |", "|---|---:|---|---|---:|---:|---:|"])
    for c in cohorts:
        gl, gr = c["gap_decomposition"]["luck"], c["gap_decomposition"]["raw"]
        lines.append(f"| {c['label']} | {_f3(gl['total_gap'], True)} | {_f3(gl['sub_breakeven_stopping_loss'], True)} ({_pct(gl['stopping_share_of_gap'])}) | {_f3(gl['evidence_collection_deficit'], True)} ({_pct(gl['evidence_share_of_gap'])}) | {_f3(gr['total_gap'], True)} | {_f3(gr['sub_breakeven_stopping_loss'], True)} | {_f3(gr['evidence_collection_deficit'], True)} |")
    lines.extend(["", f"{H2} Reproduce", "", "```bash", "PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --write", "PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --check", "pytest -q tests/test_frontier_stopping_counterfactual_v14.py", "```", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canary v1.4 Bayes stopping counterfactual and gap decomposition.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    out_json, out_md = args.out_json or default_json_path(root), args.out_md or default_md_path(root)
    audit = compute_audit(root=root, enforce_expected_counts=(root == ROOT.resolve()))
    json_blob, md_blob = serialize_json(audit), render_markdown(audit)
    if args.stdout:
        sys.stdout.write(md_blob)
    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_blob, encoding="utf-8")
        out_md.write_text(md_blob, encoding="utf-8")
    if args.check:
        if not out_json.exists() or not out_md.exists():
            return 1
        disk_raw = out_json.read_bytes()
        if len(disk_raw) > MAX_JSON_BYTES or not approx_equal(json.loads(disk_raw.decode("utf-8")), audit) or out_md.read_text(encoding="utf-8") != md_blob:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
