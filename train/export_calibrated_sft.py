from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS as RULE_TIERS, TRAIN_SEEDS
from canary.solver import SolverPolicy
from train.render import assistant_msg, render_episode

TIERS: tuple[str, ...] = ("easy", "medium", "hard")
SPLIT_RANGES: dict[str, tuple[int, int]] = {
    "train": (100_000, 190_000),
    "val": (190_000, 200_000),
}


def assert_train_seed(seed: int, split: str | None = None) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in DEV_SEEDS or 0 <= seed < 10_000:
        raise ValueError(f"seed {seed} is in DEV_SEEDS [0, 10000)")
    if 10_000 <= seed < 70_000:
        raise ValueError(f"seed {seed} is in fresh/dev range [10000, 70000)")
    if 70_000 <= seed < 100_000:
        raise ValueError(f"seed {seed} is in reserved range [70000, 100000)")
    if seed in HELDOUT_SEEDS or 800_000 <= seed < 900_000:
        raise ValueError(f"seed {seed} is in HELDOUT_SEEDS")
    if seed in JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"seed {seed} is in JUDGE_SEEDS (900000+)")
    if seed not in TRAIN_SEEDS or not (100_000 <= seed < 200_000):
        raise ValueError(f"seed {seed} is outside TRAIN_SEEDS [100000, 200000)")
    if split is not None:
        if split not in SPLIT_RANGES:
            raise ValueError(f"unknown split {split!r}")
        lo, hi = SPLIT_RANGES[split]
        if not (lo <= seed < hi):
            raise ValueError(f"seed {seed} is outside {split} split [{lo}, {hi})")
    return seed


def validate_train_seeds(seeds: list[int] | tuple[int, ...], split: str | None = None) -> list[int]:
    out = [assert_train_seed(s, split=split) for s in seeds]
    seed_set = set(out)
    if seed_set & set(DEV_SEEDS):
        raise ValueError("seeds overlap DEV_SEEDS")
    if seed_set & set(HELDOUT_SEEDS):
        raise ValueError("seeds overlap HELDOUT_SEEDS")
    if seed_set & set(JUDGE_SEEDS):
        raise ValueError("seeds overlap JUDGE_SEEDS")
    if any(70_000 <= s < 100_000 for s in seed_set):
        raise ValueError("seeds overlap [70000, 100000)")
    return out


def split_seeds(split: str, n: int, offset: int = 0) -> list[int]:
    if split not in SPLIT_RANGES:
        raise ValueError(f"unknown split {split!r}")
    if n < 0 or offset < 0:
        raise ValueError(f"n and offset must be non-negative, got n={n}, offset={offset}")
    lo, hi = SPLIT_RANGES[split]
    if lo + offset + n > hi:
        raise ValueError(f"{split}: offset+n exceeds split range [{lo}, {hi})")
    seeds = list(range(lo + offset, lo + offset + n))
    return validate_train_seeds(seeds, split=split)


def belief_snapshot(pol: SolverPolicy, n_employees: int) -> dict[str, Any]:
    if pol.obs.employees:
        post = pol.belief()
    else:
        n_emp = max(1, int(n_employees))
        post = {f"e{i:02d}": 1.0 / n_emp for i in range(n_emp)}
    ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
    top_emp, top_p = ranked[0][0], float(ranked[0][1])
    if len(ranked) > 1:
        runner_up_emp, runner_up_p = ranked[1][0], float(ranked[1][1])
    else:
        runner_up_emp, runner_up_p = top_emp, 0.0
    entropy = -sum(p * math.log(p) for p in post.values() if p > 0.0)
    known_v = max(0.0, float(pol.V))
    breakeven_p = 1.0 / (1.0 + known_v)
    ev_accuse = top_p * known_v - (1.0 - top_p)
    return {
        "top_emp": top_emp,
        "top_p": top_p,
        "runner_up_emp": runner_up_emp,
        "runner_up_p": runner_up_p,
        "entropy": entropy,
        "known_v": known_v,
        "breakeven_p": breakeven_p,
        "ev_accuse": ev_accuse,
    }


def _round_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_emp": snap["top_emp"],
        "top_p": round(snap["top_p"], 8),
        "runner_up_emp": snap["runner_up_emp"],
        "runner_up_p": round(snap["runner_up_p"], 8),
        "entropy": round(snap["entropy"], 8),
        "known_v": round(snap["known_v"], 8),
        "breakeven_p": round(snap["breakeven_p"], 8),
        "ev_accuse": round(snap["ev_accuse"], 8),
    }


def run_annotated_rollout(tier: str, seed: int) -> dict[str, Any]:
    assert_train_seed(seed)
    env = Env(tier=tier, seed=seed)
    pol = SolverPolicy()
    tools_spec = env.tools_spec()
    instruction = env.instruction()
    pol.reset(tools_spec, instruction)
    step_posteriors: list[dict[str, Any]] = []
    max_iters = env.p.tool_call_cap + 16
    for _ in range(max_iters):
        if env.done:
            break
        for prev in env.history[pol.seen:]:
            pol._ingest(prev)
        pol.seen = len(env.history)
        snap = belief_snapshot(pol, env.p.n_employees)
        t = len(env.history)
        day_now = env.day
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
        step_posteriors.append({
            "t": t,
            "day": day_now,
            "tool": tool,
            "args": dict(args),
            **_round_snapshot(snap),
        })
    ep = env.result(pol.name)
    rec = render_episode(ep, instruction, tools_spec)
    last = step_posteriors[-1]
    rec["step_posteriors"] = step_posteriors
    rec["augmented_abstention"] = False
    rec["n_days"] = env.p.n_days
    rec["final_top_p"] = last["top_p"]
    rec["final_breakeven_p"] = last["breakeven_p"]
    rec["final_known_v"] = last["known_v"]
    rec["final_ev_accuse"] = last["ev_accuse"]
    return rec


def _try_censored_rollout(
    tier: str,
    seed: int,
    d_cut: int,
    censor_logs: bool = False,
    censor_feed_after: int | None = None,
) -> dict[str, Any] | None:
    env = Env(tier=tier, seed=seed)
    pol = SolverPolicy()
    tools_spec = env.tools_spec()
    instruction = env.instruction()
    pol.reset(tools_spec, instruction)
    step_posteriors: list[dict[str, Any]] = []
    max_iters = env.p.tool_call_cap * 3
    for _ in range(max_iters):
        if env.done:
            break
        for prev in env.history[pol.seen:]:
            pol._ingest(prev)
        pol.seen = len(env.history)
        snap = belief_snapshot(pol, env.p.n_employees)
        tool, args = pol.act(list(env.history))
        if tool == "plant_canary" and env.day > d_cut:
            continue
        if censor_logs and tool == "read_access_logs" and env.day > d_cut:
            continue
        if censor_feed_after is not None and tool == "check_leak_feed" and env.day > censor_feed_after:
            continue
        if tool == "accuse":
            if snap["top_p"] >= snap["breakeven_p"] - 1e-4:
                return None
            tool, args = "advance_day", {}
        t = len(env.history)
        day_now = env.day
        env.call(tool, args)
        step_posteriors.append({
            "t": t,
            "day": day_now,
            "tool": tool,
            "args": dict(args),
            **_round_snapshot(snap),
        })
    ep = env.result(pol.name)
    if ep.end_reason != "horizon" or ep.score != 0.0 or ep.correct or ep.final_day != env.p.n_days:
        return None
    final_day_steps = [s for s in step_posteriors if s["day"] == ep.final_day]
    if not final_day_steps or any(s["top_p"] >= s["breakeven_p"] - 1e-4 for s in final_day_steps):
        return None
    rec = render_episode(ep, instruction, tools_spec)
    last = step_posteriors[-1]
    rec["step_posteriors"] = step_posteriors
    rec["augmented_abstention"] = True
    rec["censor_d_cut"] = d_cut
    rec["n_days"] = env.p.n_days
    rec["final_top_p"] = last["top_p"]
    rec["final_breakeven_p"] = last["breakeven_p"]
    rec["final_known_v"] = last["known_v"]
    rec["final_ev_accuse"] = last["ev_accuse"]
    return rec


def run_censored_abstention_rollout(tier: str, seed: int, d_cut: int | None = None) -> dict[str, Any]:
    assert_train_seed(seed)
    if d_cut is not None:
        schedules: list[tuple[int, bool, int | None]] = [
            (d_cut, False, None),
            (d_cut, True, None),
            (d_cut, True, max(1, d_cut)),
        ]
    else:
        schedules = [
            (2, False, None),
            (1, False, None),
            (0, False, None),
            (0, True, None),
            (0, True, 1),
        ]
    for cut_day, censor_logs, censor_feed_after in schedules:
        rec = _try_censored_rollout(tier, seed, cut_day, censor_logs, censor_feed_after)
        if rec is not None:
            return rec
    raise RuntimeError(f"unable to construct censored horizon abstention for {tier} seed={seed}")


def is_calibrated_record(rec: dict[str, Any]) -> bool:
    end_reason = rec.get("end_reason")
    top_p = float(rec.get("final_top_p", 0.0))
    breakeven_p = float(rec.get("final_breakeven_p", 1.0))
    if end_reason == "accused":
        return bool(rec.get("correct")) and top_p >= breakeven_p - 1e-6
    if end_reason == "horizon":
        return float(rec.get("score", -1.0)) == 0.0 and not bool(rec.get("correct")) and top_p < breakeven_p
    return False


def export_dpo_pairs(
    rec: dict[str, Any],
    max_early_low_posterior: int = 3,
    max_late_low_posterior: int = 8,
) -> list[dict[str, Any]]:
    seed = assert_train_seed(int(rec["seed"]))
    tier = str(rec["tier"])
    tools = rec["tools"]
    msgs = rec["messages"]
    step_posteriors = rec["step_posteriors"]
    n_days = int(rec.get("n_days") or RULE_TIERS[tier].n_days)
    if len(msgs) != 2 + 2 * len(step_posteriors):
        raise ValueError("messages length does not match step_posteriors length")

    pairs: list[dict[str, Any]] = []
    late_cands: list[dict[str, Any]] = []
    early_cands: list[dict[str, Any]] = []
    for st in step_posteriors:
        if st["tool"] in ("plant_canary", "advance_day") and st["top_p"] < st["breakeven_p"] - 0.10:
            if st["day"] >= n_days - 3:
                late_cands.append(st)
            else:
                early_cands.append(st)

    selected_low: list[dict[str, Any]] = late_cands[-max_late_low_posterior:] if max_late_low_posterior > 0 else []
    if len(selected_low) < max_early_low_posterior and early_cands:
        ranked_early = sorted(early_cands, key=lambda s: (-s["day"], -s["top_p"], s["t"]))
        need = max_early_low_posterior - len(selected_low)
        selected_low.extend(ranked_early[:need])
    selected_low.sort(key=lambda s: s["t"])

    for st in selected_low:
        t = int(st["t"])
        chosen = msgs[2 + 2 * t]
        rejected = assistant_msg("accuse", {"employee": st["top_emp"]})
        ev_acc = st["top_p"] * st["known_v"] - (1.0 - st["top_p"])
        margin_ev = round(0.0 - ev_acc, 8)
        if margin_ev > 0.0 and chosen != rejected:
            pairs.append({
                "tier": tier,
                "seed": seed,
                "step_idx": t,
                "messages": msgs[:2 + 2 * t],
                "tools": tools,
                "chosen": chosen,
                "rejected": rejected,
                "margin_ev": margin_ev,
            })

    for st in step_posteriors:
        if st["tool"] == "accuse" and bool(rec.get("correct")) and st["top_p"] >= st["breakeven_p"] + 0.15:
            t = int(st["t"])
            chosen = assistant_msg("accuse", {"employee": st["top_emp"]})
            ev_top = st["top_p"] * st["known_v"] - (1.0 - st["top_p"])
            if st["runner_up_emp"] != st["top_emp"]:
                rejected_ru = assistant_msg("accuse", {"employee": st["runner_up_emp"]})
                ev_ru = st["runner_up_p"] * st["known_v"] - (1.0 - st["runner_up_p"])
                margin_ru = round(ev_top - ev_ru, 8)
                if margin_ru > 0.0 and chosen != rejected_ru:
                    pairs.append({
                        "tier": tier,
                        "seed": seed,
                        "step_idx": t,
                        "messages": msgs[:2 + 2 * t],
                        "tools": tools,
                        "chosen": chosen,
                        "rejected": rejected_ru,
                        "margin_ev": margin_ru,
                    })
            rejected_stall = assistant_msg("status", {})
            margin_stall = round(ev_top, 8)
            if margin_stall > 0.0 and chosen != rejected_stall:
                pairs.append({
                    "tier": tier,
                    "seed": seed,
                    "step_idx": t,
                    "messages": msgs[:2 + 2 * t],
                    "tools": tools,
                    "chosen": chosen,
                    "rejected": rejected_stall,
                    "margin_ev": margin_stall,
                })
    return pairs


def _play_natural_job(job: tuple[str, int]) -> dict[str, Any]:
    tier, seed = job
    return run_annotated_rollout(tier, seed)


def _play_augmented_job(job: tuple[str, int]) -> dict[str, Any]:
    tier, seed = job
    return run_censored_abstention_rollout(tier, seed)


def _mean_or_none(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def export(
    split: str,
    tiers: list[str],
    n: int,
    out: str,
    seed_offset: int = 0,
    augment_abstentions: int = 0,
    abstain_oversample: int = 2,
    dpo: bool = False,
    workers: int = 1,
    keep_calibrated: bool = True,
) -> dict[str, Any]:
    if augment_abstentions < 0:
        raise ValueError("augment_abstentions must be >= 0")
    if abstain_oversample < 1:
        raise ValueError("abstain_oversample must be >= 1")
    if workers < 1:
        raise ValueError("workers must be >= 1")

    seeds = split_seeds(split, n, seed_offset)
    aug_seeds = split_seeds(split, augment_abstentions, seed_offset) if augment_abstentions > 0 else []
    eff_oversample = abstain_oversample if split == "train" else 1
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    files: list[str] = []
    tier_stats: dict[str, Any] = {}
    all_accuse_top_p: list[float] = []
    all_abstain_top_p: list[float] = []
    tot_correct = 0
    tot_nat_abstain = 0
    tot_aug_abstain = 0
    tot_rejected_wrong = 0
    tot_sft_written = 0
    tot_dpo_pairs = 0

    for tier in tiers:
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}")
        nat_jobs = [(tier, s) for s in seeds]
        if workers > 1 and len(nat_jobs) > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                nat_recs = list(ex.map(_play_natural_job, nat_jobs))
        else:
            nat_recs = [_play_natural_job(j) for j in nat_jobs]

        if keep_calibrated:
            kept_nat = [r for r in nat_recs if is_calibrated_record(r)]
        else:
            kept_nat = list(nat_recs)

        rejected_wrong = sum(
            1 for r in nat_recs if r["end_reason"] == "accused" and not bool(r["correct"])
        )
        correct_recs = [r for r in kept_nat if r["end_reason"] == "accused" and bool(r["correct"])]
        nat_abstain_recs = [r for r in kept_nat if r["end_reason"] != "accused"]

        aug_jobs = [(tier, s) for s in aug_seeds]
        if workers > 1 and len(aug_jobs) > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                aug_recs = list(ex.map(_play_augmented_job, aug_jobs))
        else:
            aug_recs = [_play_augmented_job(j) for j in aug_jobs]

        sft_to_write: list[dict[str, Any]] = []
        for r in correct_recs:
            rc = copy.copy(r)
            rc["oversample_replica"] = 0
            sft_to_write.append(rc)
        for r in nat_abstain_recs + aug_recs:
            for rep in range(eff_oversample):
                rc = copy.copy(r)
                rc["oversample_replica"] = rep
                sft_to_write.append(rc)

        sft_name = f"sft-{split}-{tier}.jsonl"
        sft_path = os.path.join(out, sft_name)
        with open(sft_path, "w", encoding="utf-8") as fh:
            for r in sft_to_write:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")
        files.append(sft_name)

        dpo_list: list[dict[str, Any]] = []
        if dpo:
            for r in kept_nat + aug_recs:
                dpo_list.extend(export_dpo_pairs(r))
            dpo_name = f"dpo-{split}-{tier}.jsonl"
            dpo_path = os.path.join(out, dpo_name)
            with open(dpo_path, "w", encoding="utf-8") as fh:
                for p in dpo_list:
                    fh.write(json.dumps(p, separators=(",", ":")) + "\n")
            files.append(dpo_name)

        tier_accuse_p = [float(r["final_top_p"]) for r in correct_recs]
        tier_abstain_p = [float(r["final_top_p"]) for r in (nat_abstain_recs + aug_recs)]
        all_accuse_top_p.extend(tier_accuse_p)
        all_abstain_top_p.extend(tier_abstain_p)

        tot_correct += len(correct_recs)
        tot_nat_abstain += len(nat_abstain_recs)
        tot_aug_abstain += len(aug_recs)
        tot_rejected_wrong += rejected_wrong
        tot_sft_written += len(sft_to_write)
        tot_dpo_pairs += len(dpo_list)

        tier_stats[tier] = {
            "natural_episodes": len(nat_recs),
            "correct_accusations": len(correct_recs),
            "natural_abstentions": len(nat_abstain_recs),
            "augmented_abstentions": len(aug_recs),
            "rejected_wrong_accusations": rejected_wrong,
            "sft_unique_episodes": len(correct_recs) + len(nat_abstain_recs) + len(aug_recs),
            "abstain_oversample": eff_oversample,
            "sft_records_written": len(sft_to_write),
            "dpo_pairs": len(dpo_list),
            "mean_top_p_at_accuse": _mean_or_none(tier_accuse_p),
            "mean_top_p_at_abstain": _mean_or_none(tier_abstain_p),
            "mean_breakeven_p_at_accuse": _mean_or_none([float(r["final_breakeven_p"]) for r in correct_recs]),
            "mean_breakeven_p_at_abstain": _mean_or_none(
                [float(r["final_breakeven_p"]) for r in (nat_abstain_recs + aug_recs)]
            ),
            "mean_score_natural": round(sum(float(r["score"]) for r in nat_recs) / max(len(nat_recs), 1), 6),
        }

    manifest = {
        "split": split,
        "seed_offset": seed_offset,
        "keep_calibrated": keep_calibrated,
        "abstain_oversample": eff_oversample,
        "augment_abstentions_per_tier": augment_abstentions,
        "dpo_enabled": bool(dpo),
        "correct_accusations": tot_correct,
        "natural_abstentions": tot_nat_abstain,
        "augmented_abstentions": tot_aug_abstain,
        "rejected_wrong_accusations": tot_rejected_wrong,
        "sft_records_written": tot_sft_written,
        "dpo_pairs": tot_dpo_pairs,
        "mean_top_p_at_accuse": _mean_or_none(all_accuse_top_p),
        "mean_top_p_at_abstain": _mean_or_none(all_abstain_top_p),
        "tiers": tier_stats,
        "files": files,
        "seconds": round(time.time() - t0, 2),
    }
    manifest_path = os.path.join(out, f"{split}-calibrated-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=list(SPLIT_RANGES), default="train")
    ap.add_argument("--tier", choices=[*TIERS, "all"], default="all")
    ap.add_argument("--n", type=int, required=True, help="episodes per tier")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--augment-abstentions", type=int, default=0)
    ap.add_argument("--abstain-oversample", type=int, default=2)
    ap.add_argument("--dpo", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args(argv)
    tiers = list(TIERS) if a.tier == "all" else [a.tier]
    manifest = export(
        split=a.split,
        tiers=tiers,
        n=a.n,
        out=a.out,
        seed_offset=a.seed_offset,
        augment_abstentions=a.augment_abstentions,
        abstain_oversample=a.abstain_oversample,
        dpo=a.dpo,
        workers=a.workers,
    )
    print(json.dumps(manifest))
    return manifest


if __name__ == "__main__":
    main()
