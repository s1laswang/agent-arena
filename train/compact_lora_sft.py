from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import importlib
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import canary
from canary.analysis.accuse import audit_episode
from canary.env import Env
from canary.eval import episode_from_dict, run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS as RULE_TIERS, TRAIN_SEEDS
from canary.types import INVESTIGATIVE_TOOLS
import train
from train.compact_render import CompactHFPolicy
from train.render import assistant_msg

TIERS: tuple[str, ...] = ("easy", "medium", "hard")
SPLIT_RANGES: dict[str, tuple[int, int]] = {
    "train": (100_000, 190_000),
    "val": (190_000, 200_000),
}
DEFAULT_MODEL = "/home/silas/agent-arena-data/models/Qwen2.5-0.5B-Instruct"
DEFAULT_OUT_DIR = "/tmp/fleet-silas/shared/tiebreak-v100/qwen05b_compact_dagger"
HELDOUT_SECRET_DEFAULT = "canary-tiebreak-heldout-v14-eval-01"
RUN_ID_DEFAULT = "qwen05b-compact-dagger-v14"
MODEL_LABEL_DEFAULT = "Qwen2.5-0.5B-Instruct Compact LoRA + DPO + DAgger r1"
DAGGER_SEED_START_DEFAULT = 104_500
LORA_TARGETS: tuple[str, ...] = (
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
)
ROUTINE_POLL_TOOLS: frozenset[str] = frozenset({
    "status",
    "list_documents",
    "read_access_logs",
    "check_leak_feed",
})


class CompactLoRAPolicy(CompactHFPolicy):
    def __init__(
        self,
        model=None,
        tokenizer=None,
        name: str = "qwen05b_compact_dagger_r1",
        max_ctx: int = 2560,
        max_new: int = 300,
        tail_turns: int = 4,
        kv_reuse: bool = True,
        generator: Any = None,
    ):
        super().__init__(
            model=model,
            tokenizer=tokenizer,
            name=name,
            max_ctx=max_ctx,
            max_new=max_new,
            tail_turns=tail_turns,
            kv_reuse=kv_reuse,
            generator=generator,
        )
        self._prefetched_text: str | None = None

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        super().reset(tools_spec, instruction)
        self._prefetched_text = None

    def set_prefetched_text(self, text: str) -> None:
        self._prefetched_text = text

    def generate_text(self, history: list) -> str:
        if self._prefetched_text is not None:
            txt = self._prefetched_text
            self._prefetched_text = None
            return txt
        return super().generate_text(history)

    def act(self, history: list) -> tuple[str, dict[str, Any]]:
        return super().act(history)


def assert_train_seed(seed: int, split: str | None = None) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in DEV_SEEDS or 0 <= seed < 10_000:
        raise ValueError(f"seed {seed} is in DEV_SEEDS [0, 10000)")
    if 10_000 <= seed < 100_000:
        raise ValueError(f"seed {seed} is outside TRAIN_SEEDS [100000, 200000)")
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
    return out


def load_compact_render():
    if "train.compact_render" in sys.modules:
        return sys.modules["train.compact_render"]
    for root in list(sys.path):
        if not root:
            continue
        cand_pkg = os.path.join(root, "train")
        cand_mod = os.path.join(cand_pkg, "compact_render.py")
        if os.path.isfile(cand_mod) and cand_pkg not in train.__path__:
            train.__path__.append(cand_pkg)
    return importlib.import_module("train.compact_render")


def _torch_stack_available(model_path: str) -> bool:
    if not os.path.isdir(model_path) or not os.path.isfile(os.path.join(model_path, "tokenizer.json")):
        return False
    try:
        import peft
        import torch
        import transformers

        _ = (peft, torch, transformers)
        return True
    except ImportError:
        return False


def _use_tiny_cpu_stub(tiny: bool, model_path: str, tiny_torch: bool = False) -> bool:
    return bool(tiny and (not tiny_torch or not _torch_stack_available(model_path)))


def repo_root() -> Path:
    return Path(canary.__file__).resolve().parent.parent


def assert_eval_seed(seed: int, split: str) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in TRAIN_SEEDS or 100_000 <= seed < 200_000:
        raise ValueError(f"eval seed {seed} overlaps TRAIN_SEEDS")
    if seed in JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"eval seed {seed} overlaps JUDGE_SEEDS")
    if split == "heldout":
        if seed not in HELDOUT_SEEDS or not (800_000 <= seed < 800_200):
            raise ValueError(f"seed {seed} is not in HELDOUT_SEEDS [800000, 800200)")
    elif split == "dev":
        if seed not in DEV_SEEDS or not (0 <= seed < 10_000):
            raise ValueError(f"seed {seed} is not in DEV_SEEDS [0, 10000)")
    else:
        raise ValueError(f"unknown eval split {split!r}")
    return seed


def assert_all_splits_disjoint(
    train_seeds: list[int],
    val_seeds: list[int],
    heldout_seeds: list[int],
    dev_seeds: list[int],
) -> None:
    tr = set(validate_train_seeds(train_seeds, split="train"))
    va = set(validate_train_seeds(val_seeds, split="val"))
    ho = {assert_eval_seed(s, "heldout") for s in heldout_seeds}
    dv = {assert_eval_seed(s, "dev") for s in dev_seeds}
    jg = set(JUDGE_SEEDS)
    if tr & va:
        raise ValueError("train and val seeds overlap")
    if (tr | va) & (ho | dv | jg):
        raise ValueError("training/val seeds overlap eval/judge seeds")
    if ho & dv or ho & jg or dv & jg:
        raise ValueError("eval splits overlap")


def canonicalize_step_args(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    if tool == "plant_canary" and isinstance(out.get("assignment"), dict):
        asg = out["assignment"]
        out["assignment"] = {
            str(k): str(v)
            for k, v in sorted(asg.items(), key=lambda kv: (str(kv[1]), str(kv[0])))
        }
    return out


def _round_snap(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_emp": snap["top_emp"],
        "top_p": round(float(snap["top_p"]), 8),
        "runner_up_emp": snap["runner_up_emp"],
        "runner_up_p": round(float(snap["runner_up_p"]), 8),
        "entropy": round(float(snap["entropy"]), 8),
        "known_v": round(float(snap["known_v"]), 8),
        "breakeven_p": round(float(snap["breakeven_p"]), 8),
        "ev_accuse": round(float(snap["ev_accuse"]), 8),
    }


def run_natural_compact_rollout(tier: str, seed: int, split: str = "train") -> dict[str, Any]:
    from canary.solver import SolverPolicy
    from train.export_calibrated_sft import belief_snapshot

    assert_train_seed(seed, split=split)
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
        raw_tool, raw_args = pol.act(list(env.history))
        c_args = canonicalize_step_args(raw_tool, raw_args if isinstance(raw_args, dict) else {})
        env.call(raw_tool, c_args)
        step_posteriors.append({
            "t": t,
            "day": day_now,
            "tool": raw_tool,
            "args": c_args,
            **_round_snap(snap),
        })
    ep = env.result(pol.name)
    last = step_posteriors[-1]
    meta_rec = {
        "tier": tier,
        "seed": seed,
        "score": float(ep.score),
        "correct": bool(ep.correct),
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "n_days": int(env.p.n_days),
        "augmented_abstention": False,
        "censor_d_cut": None,
        "final_top_p": last["top_p"],
        "final_breakeven_p": last["breakeven_p"],
        "final_known_v": last["known_v"],
        "final_ev_accuse": last["ev_accuse"],
        "step_posteriors": step_posteriors,
    }
    return {
        "ep": ep,
        "instruction": instruction,
        "tools_spec": tools_spec,
        "meta_rec": meta_rec,
    }


def run_censored_compact_rollout(tier: str, seed: int, split: str = "train") -> dict[str, Any]:
    from train.export_calibrated_sft import run_censored_abstention_rollout

    assert_train_seed(seed, split=split)
    raw = run_censored_abstention_rollout(tier=tier, seed=seed)
    env = Env(tier=tier, seed=seed)
    tools_spec = env.tools_spec()
    instruction = env.instruction()
    step_posteriors: list[dict[str, Any]] = []
    for st in raw["step_posteriors"]:
        c_args = canonicalize_step_args(st["tool"], dict(st["args"]))
        env.call(st["tool"], c_args)
        st_copy = dict(st)
        st_copy["args"] = c_args
        step_posteriors.append(st_copy)
    ep = env.result("solver")
    if ep.end_reason != "horizon" or float(ep.score) != 0.0 or bool(ep.correct):
        raise RuntimeError(f"censored replay mismatch for {tier} seed={seed}")
    meta_rec = {
        "tier": tier,
        "seed": seed,
        "score": float(ep.score),
        "correct": bool(ep.correct),
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "n_days": int(raw.get("n_days") or env.p.n_days),
        "augmented_abstention": True,
        "censor_d_cut": int(raw.get("censor_d_cut", 2)),
        "final_top_p": float(raw["final_top_p"]),
        "final_breakeven_p": float(raw["final_breakeven_p"]),
        "final_known_v": float(raw["final_known_v"]),
        "final_ev_accuse": float(raw["final_ev_accuse"]),
        "step_posteriors": step_posteriors,
    }
    return {
        "ep": ep,
        "instruction": instruction,
        "tools_spec": tools_spec,
        "meta_rec": meta_rec,
    }


def turn_oversample_count(
    turn_idx: int,
    n_turns: int,
    target_tool: str,
    step_day: int,
    n_days: int,
    end_reason: str,
    augmented_abstention: bool = False,
    censor_d_cut: int | None = None,
    split: str = "train",
) -> int:
    if n_turns <= 0 or turn_idx < 0 or turn_idx >= n_turns:
        return 0
    is_final_two = turn_idx >= max(0, n_turns - 2)
    is_horizon_advance = (
        end_reason == "horizon"
        and target_tool == "advance_day"
        and (step_day >= n_days or turn_idx == n_turns - 1)
    )
    if augmented_abstention:
        cut = 2 if censor_d_cut is None else int(censor_d_cut)
        in_uncensored_early = step_day <= max(1, cut)
        in_horizon_tail = step_day >= n_days - 1 or turn_idx >= max(0, n_turns - 4)
        if not (in_uncensored_early or in_horizon_tail or is_final_two or is_horizon_advance):
            return 0
    if split != "train":
        return 1
    mult = 3 if is_final_two else 1
    if target_tool == "plant_canary":
        mult = max(mult, 2) + (1 if is_final_two else 0)
    if target_tool == "accuse":
        mult = max(mult, 6)
    if is_horizon_advance:
        mult = max(mult, 6)
    return mult


def is_calibrated_compact_bundle(bundle_or_meta: dict[str, Any]) -> bool:
    meta_rec = bundle_or_meta.get("meta_rec", bundle_or_meta)
    if not isinstance(meta_rec, dict):
        return False
    end_reason = meta_rec.get("end_reason")
    top_p = float(meta_rec.get("final_top_p", 0.0))
    breakeven_p = float(meta_rec.get("final_breakeven_p", 1.0))
    if end_reason == "accused":
        return bool(meta_rec.get("correct")) and top_p >= breakeven_p - 1e-6
    if end_reason == "horizon":
        return float(meta_rec.get("score", -1.0)) == 0.0 and (not bool(meta_rec.get("correct"))) and top_p < breakeven_p
    return False


def build_compact_episode_sft_and_dpo(
    bundle: dict[str, Any],
    tail_turns: int = 4,
    split: str = "train",
    max_low_dpo_per_ep: int = 4,
    require_calibrated: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cr = load_compact_render()
    ep = bundle["ep"]
    instruction = bundle["instruction"]
    tools_spec = bundle["tools_spec"]
    meta_rec = bundle["meta_rec"]
    seed = assert_train_seed(int(meta_rec["seed"]), split=split)
    if require_calibrated and not is_calibrated_compact_bundle(meta_rec):
        return [], []
    tier = str(meta_rec["tier"])
    n_days = int(meta_rec["n_days"])
    end_reason = str(meta_rec["end_reason"])
    augmented = bool(meta_rec["augmented_abstention"])
    censor_d_cut = meta_rec.get("censor_d_cut")
    step_posteriors = meta_rec["step_posteriors"]

    compact_turns = cr.render_compact_episode_turns(
        ep,
        instruction,
        tools_spec,
        tail_turns=tail_turns,
    )
    if len(compact_turns) != len(step_posteriors):
        raise ValueError("compact_turns length mismatch with step_posteriors")

    sft_rows: list[dict[str, Any]] = []
    n_turns = len(compact_turns)
    for idx, (turn, sp) in enumerate(zip(compact_turns, step_posteriors)):
        copies = turn_oversample_count(
            turn_idx=idx,
            n_turns=n_turns,
            target_tool=str(turn["target_tool"]),
            step_day=int(sp["day"]),
            n_days=n_days,
            end_reason=end_reason,
            augmented_abstention=augmented,
            censor_d_cut=censor_d_cut,
            split=split,
        )
        if copies <= 0:
            continue
        base_row = {
            "tier": tier,
            "seed": seed,
            "split": split,
            "step_index": idx,
            "n_turns": n_turns,
            "day": int(sp["day"]),
            "n_days": n_days,
            "target_tool": str(turn["target_tool"]),
            "end_reason": end_reason,
            "correct": bool(meta_rec["correct"]),
            "augmented_abstention": augmented,
            "top_p": float(sp["top_p"]),
            "breakeven_p": float(sp["breakeven_p"]),
            "tools": turn["tools"],
            "messages": turn["messages"],
        }
        for rep in range(copies):
            row_copy = copy.copy(base_row)
            row_copy["oversample_replica"] = rep
            row_copy["oversample_total"] = copies
            sft_rows.append(row_copy)

    dpo_pairs: list[dict[str, Any]] = []
    low_late: list[int] = []
    low_early: list[int] = []
    for idx, sp in enumerate(step_posteriors):
        if sp["tool"] in ("plant_canary", "advance_day", "check_leak_feed") and sp["top_p"] < sp["breakeven_p"] - 0.08:
            if augmented and censor_d_cut is not None and int(censor_d_cut) < int(sp["day"]) < n_days - 1:
                continue
            if int(sp["day"]) >= n_days - 3:
                low_late.append(idx)
            else:
                low_early.append(idx)

    chosen_low = low_late[-max_low_dpo_per_ep:]
    if len(chosen_low) < max_low_dpo_per_ep and low_early:
        ranked_early = sorted(
            low_early,
            key=lambda i: (-int(step_posteriors[i]["day"]), -float(step_posteriors[i]["top_p"]), i),
        )
        chosen_low.extend(ranked_early[: max_low_dpo_per_ep - len(chosen_low)])
    chosen_low.sort()

    for idx in chosen_low:
        sp = step_posteriors[idx]
        turn = compact_turns[idx]
        prompt_msgs = turn["messages"][:-1]
        chosen_msg = turn["messages"][-1]
        rej_msg = assistant_msg("accuse", {"employee": str(sp["top_emp"])})
        ev_acc = float(sp["top_p"]) * float(sp["known_v"]) - (1.0 - float(sp["top_p"]))
        margin_ev = round(0.0 - ev_acc, 8)
        if margin_ev > 0.0 and chosen_msg != rej_msg:
            dpo_pairs.append({
                "tier": tier,
                "seed": seed,
                "split": split,
                "step_index": idx,
                "pair_type": "premature_accuse",
                "margin_ev": margin_ev,
                "tools": turn["tools"],
                "messages": prompt_msgs,
                "chosen": chosen_msg,
                "rejected": rej_msg,
            })

    for idx, sp in enumerate(step_posteriors):
        if sp["tool"] == "accuse" and bool(meta_rec["correct"]) and float(sp["top_p"]) >= float(sp["breakeven_p"]) + 0.10:
            turn = compact_turns[idx]
            prompt_msgs = turn["messages"][:-1]
            chosen_msg = assistant_msg("accuse", {"employee": str(sp["top_emp"])})
            ev_top = float(sp["top_p"]) * float(sp["known_v"]) - (1.0 - float(sp["top_p"]))
            if str(sp["runner_up_emp"]) != str(sp["top_emp"]):
                rej_ru = assistant_msg("accuse", {"employee": str(sp["runner_up_emp"])})
                ev_ru = float(sp["runner_up_p"]) * float(sp["known_v"]) - (1.0 - float(sp["runner_up_p"]))
                margin_ru = round(ev_top - ev_ru, 8)
                if margin_ru > 0.0 and chosen_msg != rej_ru:
                    dpo_pairs.append({
                        "tier": tier,
                        "seed": seed,
                        "split": split,
                        "step_index": idx,
                        "pair_type": "wrong_target_accuse",
                        "margin_ev": margin_ru,
                        "tools": turn["tools"],
                        "messages": prompt_msgs,
                        "chosen": chosen_msg,
                        "rejected": rej_ru,
                    })
            for stall_tool in ("advance_day", "status"):
                rej_stall = assistant_msg(stall_tool, {})
                margin_stall = round(ev_top, 8)
                if margin_stall > 0.0 and chosen_msg != rej_stall:
                    dpo_pairs.append({
                        "tier": tier,
                        "seed": seed,
                        "split": split,
                        "step_index": idx,
                        "pair_type": "stall_when_ev_pos",
                        "margin_ev": margin_stall,
                        "tools": turn["tools"],
                        "messages": prompt_msgs,
                        "chosen": chosen_msg,
                        "rejected": rej_stall,
                    })

    return sft_rows, dpo_pairs


def _collect_split_episodes(
    split: str,
    tier: str,
    n_natural: int,
    n_augment: int,
    tail_turns: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    lo, hi = SPLIT_RANGES[split]
    aug_start = lo + 50_000 if split == "train" else lo + 5_000
    nat_cursor = lo
    nat_bundles: list[dict[str, Any]] = []
    rejected_uncalibrated = 0
    while len(nat_bundles) < n_natural:
        if nat_cursor >= aug_start:
            raise RuntimeError(f"exhausted natural seed budget for {split}/{tier}")
        assert_train_seed(nat_cursor, split=split)
        bundle = run_natural_compact_rollout(tier=tier, seed=nat_cursor, split=split)
        nat_cursor += 1
        if is_calibrated_compact_bundle(bundle["meta_rec"]):
            nat_bundles.append(bundle)
        else:
            rejected_uncalibrated += 1

    aug_cursor = aug_start
    aug_bundles: list[dict[str, Any]] = []
    aug_skips = 0
    while len(aug_bundles) < n_augment:
        if aug_cursor >= hi:
            raise RuntimeError(f"exhausted augmented seed budget for {split}/{tier}")
        assert_train_seed(aug_cursor, split=split)
        cur_seed = aug_cursor
        aug_cursor += 1
        try:
            bundle = run_censored_compact_rollout(tier=tier, seed=cur_seed, split=split)
        except RuntimeError:
            aug_skips += 1
            continue
        if is_calibrated_compact_bundle(bundle["meta_rec"]):
            aug_bundles.append(bundle)

    sft_rows: list[dict[str, Any]] = []
    dpo_rows: list[dict[str, Any]] = []
    for b in nat_bundles + aug_bundles:
        s_part, d_part = build_compact_episode_sft_and_dpo(b, tail_turns=tail_turns, split=split)
        sft_rows.extend(s_part)
        dpo_rows.extend(d_part)

    tool_counts = Counter(r["target_tool"] for r in sft_rows)
    pair_counts = Counter(p["pair_type"] for p in dpo_rows)
    used_seeds = [int(b["meta_rec"]["seed"]) for b in nat_bundles + aug_bundles]
    validate_train_seeds(used_seeds, split=split)
    stats = {
        "natural_calibrated_episodes": len(nat_bundles),
        "rejected_uncalibrated_natural": rejected_uncalibrated,
        "augmented_horizon_abstentions": len(aug_bundles),
        "augmented_skips": aug_skips,
        "sft_turns_written": len(sft_rows),
        "dpo_pairs_written": len(dpo_rows),
        "sft_tool_distribution": dict(tool_counts),
        "dpo_pair_distribution": dict(pair_counts),
        "used_seeds_min": min(used_seeds) if used_seeds else None,
        "used_seeds_max": max(used_seeds) if used_seeds else None,
        "used_seeds": used_seeds,
    }
    return sft_rows, dpo_rows, stats


def export_compact_datasets(
    out_dir: str | Path,
    tiers: tuple[str, ...] = TIERS,
    n_train: int = 60,
    n_augment: int = 18,
    n_val: int = 10,
    n_val_augment: int = 4,
    tail_turns: int = 4,
    workers: int = 1,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1 under shared cgroup memory rules")
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    mf_file = out_path / "export_manifest.json"
    required_files = (
        mf_file,
        out_path / "compact_sft_train.jsonl",
        out_path / "compact_sft_val.jsonl",
        out_path / "compact_dpo_train.jsonl",
        out_path / "compact_dpo_val.jsonl",
    )
    if reuse_existing and all(f.is_file() and f.stat().st_size > 0 for f in required_files):
        cached = json.loads(mf_file.read_text(encoding="utf-8"))
        if tuple(cached.get("tiers") or ()) == tuple(tiers) and int(cached.get("tail_turns", -1)) == int(tail_turns):
            assert_all_splits_disjoint(
                list(cached.get("train_seeds") or []),
                list(cached.get("val_seeds") or []),
                list(range(800_000, 800_030)),
                list(range(0, 30)),
            )
            print(f"[export] reusing verified dataset manifest -> {mf_file}", flush=True)
            return cached
    t0 = time.time()

    all_used: dict[str, list[int]] = {"train": [], "val": []}
    manifest_splits: dict[str, Any] = {}

    for split, n_nat, n_aug in (("train", n_train, n_augment), ("val", n_val, n_val_augment)):
        split_sft: list[dict[str, Any]] = []
        split_dpo: list[dict[str, Any]] = []
        tier_stats: dict[str, Any] = {}
        for tier in tiers:
            if tier not in TIERS:
                raise ValueError(f"unknown tier {tier!r}")
            s_rows, d_rows, st = _collect_split_episodes(
                split=split,
                tier=tier,
                n_natural=n_nat,
                n_augment=n_aug,
                tail_turns=tail_turns,
            )
            all_used[split].extend(st.pop("used_seeds"))
            split_sft.extend(s_rows)
            split_dpo.extend(d_rows)
            tier_stats[tier] = st

        sft_file = out_path / f"compact_sft_{split}.jsonl"
        dpo_file = out_path / f"compact_dpo_{split}.jsonl"
        with open(sft_file, "w", encoding="utf-8") as fh:
            for row in split_sft:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        with open(dpo_file, "w", encoding="utf-8") as fh:
            for pair in split_dpo:
                fh.write(json.dumps(pair, separators=(",", ":")) + "\n")

        manifest_splits[split] = {
            "sft_file": sft_file.name,
            "dpo_file": dpo_file.name,
            "sft_turns": len(split_sft),
            "dpo_pairs": len(split_dpo),
            "sft_tool_distribution": dict(Counter(r["target_tool"] for r in split_sft)),
            "dpo_pair_distribution": dict(Counter(p["pair_type"] for p in split_dpo)),
            "tiers": tier_stats,
        }

    assert_all_splits_disjoint(
        all_used["train"],
        all_used["val"],
        list(range(800_000, 800_030)),
        list(range(0, 30)),
    )

    manifest = {
        "tiers": list(tiers),
        "tail_turns": tail_turns,
        "workers": workers,
        "train_seeds": sorted(set(all_used["train"])),
        "val_seeds": sorted(set(all_used["val"])),
        "splits": manifest_splits,
        "seconds": round(time.time() - t0, 2),
    }
    with open(out_path / "export_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _unwrap_token_ids(encoded: Any) -> list[int]:
    if hasattr(encoded, "keys") and "input_ids" in encoded:
        encoded = encoded["input_ids"]
    if encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    return [int(x) for x in encoded]


def _common_prefix_len(a: list[int], b: list[int]) -> int:
    limit = min(len(a), len(b))
    idx = 0
    while idx < limit and a[idx] == b[idx]:
        idx += 1
    return idx


def pack_compact_turn_ids(
    turn: dict[str, Any],
    tokenizer: Any,
    max_len: int = 3072,
) -> tuple[list[int], list[int], int] | None:
    msgs = turn.get("messages") or []
    if len(msgs) < 2 or msgs[-1].get("role") != "assistant":
        return None
    tools = turn.get("tools")
    prompt_raw = tokenizer.apply_chat_template(
        msgs[:-1],
        tools=tools,
        tokenize=True,
        add_generation_prompt=True,
    )
    full_raw = tokenizer.apply_chat_template(
        msgs,
        tools=tools,
        tokenize=True,
        add_generation_prompt=False,
    )
    prompt_ids = _unwrap_token_ids(prompt_raw)
    full_ids = _unwrap_token_ids(full_raw)

    if len(full_ids) <= len(prompt_ids):
        return None
    if full_ids[: len(prompt_ids)] == prompt_ids:
        prompt_len = len(prompt_ids)
    else:
        prompt_len = _common_prefix_len(prompt_ids, full_ids)
    if prompt_len <= 0 or prompt_len >= len(full_ids):
        return None

    eos_id = getattr(tokenizer, "eos_token_id", None)
    if isinstance(eos_id, int):
        for pos in range(prompt_len, len(full_ids)):
            if full_ids[pos] == eos_id:
                full_ids = full_ids[: pos + 1]
                break

    if len(full_ids) > max_len or prompt_len >= len(full_ids):
        return None
    labels = [-100] * prompt_len + list(full_ids[prompt_len:])
    return full_ids, labels, prompt_len


def pack_compact_dpo_pair_ids(
    pair: dict[str, Any],
    tokenizer: Any,
    max_len: int = 3072,
) -> dict[str, Any] | None:
    base_msgs = list(pair.get("messages") or [])
    tools = pair.get("tools")
    chosen_turn = {"messages": [*base_msgs, pair["chosen"]], "tools": tools}
    rejected_turn = {"messages": [*base_msgs, pair["rejected"]], "tools": tools}
    packed_c = pack_compact_turn_ids(chosen_turn, tokenizer, max_len=max_len)
    packed_r = pack_compact_turn_ids(rejected_turn, tokenizer, max_len=max_len)
    if packed_c is None or packed_r is None:
        return None
    c_ids, c_lab, c_plen = packed_c
    r_ids, r_lab, r_plen = packed_r
    if c_ids == r_ids or c_plen != r_plen:
        return None
    return {
        "chosen_ids": c_ids,
        "chosen_labels": c_lab,
        "rejected_ids": r_ids,
        "rejected_labels": r_lab,
        "prompt_len": c_plen,
        "margin_ev": float(pair.get("margin_ev", 1.0)),
        "pair_type": str(pair.get("pair_type", "ev")),
    }


def softplus_neg(x: float) -> float:
    if x >= 0.0:
        return math.log1p(math.exp(-x))
    return -x + math.log1p(math.exp(x))


def dpo_loss_from_logprobs_py(
    pi_chosen_lp: list[float],
    pi_rejected_lp: list[float],
    ref_chosen_lp: list[float],
    ref_rejected_lp: list[float],
    beta: float = 0.15,
) -> dict[str, float]:
    n = len(pi_chosen_lp)
    if n == 0 or not (len(pi_rejected_lp) == len(ref_chosen_lp) == len(ref_rejected_lp) == n):
        raise ValueError("mismatched logprob sequence lengths")
    losses: list[float] = []
    margins: list[float] = []
    accs: list[float] = []
    for pc, pr, rc, rr in zip(pi_chosen_lp, pi_rejected_lp, ref_chosen_lp, ref_rejected_lp):
        u = float(beta) * ((float(pc) - float(pr)) - (float(rc) - float(rr)))
        losses.append(softplus_neg(u))
        margins.append(u)
        accs.append(1.0 if u > 0.0 else (0.5 if u == 0.0 else 0.0))
    return {
        "loss": sum(losses) / n,
        "reward_margin": sum(margins) / n,
        "pref_acc": sum(accs) / n,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _append_curve(out_dir: Path, records: list[dict[str, Any]], stage_to_replace: str) -> None:
    curve_path = out_dir / "train_curve.jsonl"
    existing: list[dict[str, Any]] = []
    if curve_path.is_file():
        for row in _load_jsonl(curve_path):
            if row.get("stage") != stage_to_replace:
                existing.append(row)
    with open(curve_path, "w", encoding="utf-8") as fh:
        for row in existing + records:
            fh.write(json.dumps(row) + "\n")


def _load_tokenizer(model_path: str):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def _load_causal_lm(model_path: str, dtype: Any, tiny: bool = False, vocab_size: int = 151936):
    import torch
    from transformers import AutoModelForCausalLM

    if tiny:
        from transformers import Qwen2Config, Qwen2ForCausalLM

        cfg = Qwen2Config(
            vocab_size=max(vocab_size, 151936),
            hidden_size=64,
            intermediate_size=128,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=4096,
            tie_word_embeddings=True,
        )
        cfg._attn_implementation = "sdpa"
        torch.manual_seed(0)
        return Qwen2ForCausalLM(cfg)
    try:
        return AutoModelForCausalLM.from_pretrained(
            model_path,
            dtype=dtype,
            attn_implementation="sdpa",
            local_files_only=True,
        )
    except TypeError:
        return AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=dtype,
            attn_implementation="sdpa",
            local_files_only=True,
        )


def _forward_suffix_logits(model: Any, inp: Any, att: Any, start: int, max_l: int):
    keep = max_l - start + 1
    try:
        out = model(input_ids=inp, attention_mask=att, use_cache=False, logits_to_keep=keep)
    except TypeError:
        out = model(input_ids=inp, attention_mask=att, use_cache=False)
    logits = out.logits
    if logits.size(1) == keep:
        return logits[:, :-1, :].float()
    return logits[:, start - 1 : -1, :].float()


def _suffix_batch_ce(model: Any, batch: list[tuple[list[int], list[int], int]], pad_id: int, device: str, use_amp: bool):
    import torch
    import torch.nn.functional as F

    max_l = max(len(x[0]) for x in batch)
    start = max(1, min(int(x[2]) for x in batch))
    inp = torch.full((len(batch), max_l), pad_id, dtype=torch.long, device=device)
    lab = torch.full((len(batch), max_l), -100, dtype=torch.long, device=device)
    att = torch.zeros((len(batch), max_l), dtype=torch.long, device=device)
    for bi, (ids, lbs, _plen) in enumerate(batch):
        inp[bi, : len(ids)] = torch.tensor(ids, dtype=torch.long, device=device)
        lab[bi, : len(lbs)] = torch.tensor(lbs, dtype=torch.long, device=device)
        att[bi, : len(ids)] = 1
    amp_dev = "cuda" if use_amp else "cpu"
    with torch.autocast(device_type=amp_dev, dtype=torch.float16, enabled=use_amp):
        shift_logits = _forward_suffix_logits(model, inp, att, start, max_l)
        shift_labels = lab[:, start:]
        loss = F.cross_entropy(
            shift_logits.reshape(-1, shift_logits.size(-1)),
            shift_labels.reshape(-1),
            ignore_index=-100,
            reduction="mean",
        )
    return loss


def _sequence_sum_and_mean_logprob(
    model: Any,
    seqs: list[tuple[list[int], list[int], int]],
    pad_id: int,
    device: str,
    use_amp: bool,
):
    import torch
    import torch.nn.functional as F

    max_l = max(len(x[0]) for x in seqs)
    start = max(1, min(int(x[2]) for x in seqs))
    inp = torch.full((len(seqs), max_l), pad_id, dtype=torch.long, device=device)
    lab = torch.full((len(seqs), max_l), -100, dtype=torch.long, device=device)
    att = torch.zeros((len(seqs), max_l), dtype=torch.long, device=device)
    for bi, (ids, lbs, _plen) in enumerate(seqs):
        inp[bi, : len(ids)] = torch.tensor(ids, dtype=torch.long, device=device)
        lab[bi, : len(lbs)] = torch.tensor(lbs, dtype=torch.long, device=device)
        att[bi, : len(ids)] = 1
    amp_dev = "cuda" if use_amp else "cpu"
    with torch.autocast(device_type=amp_dev, dtype=torch.float16, enabled=use_amp):
        shift_logits = _forward_suffix_logits(model, inp, att, start, max_l)
        shift_labels = lab[:, start:]
        valid_mask = shift_labels != -100
        safe_targets = shift_labels.clamp(min=0)
        log_probs = F.log_softmax(shift_logits, dim=-1)
        token_lp = log_probs.gather(-1, safe_targets.unsqueeze(-1)).squeeze(-1) * valid_mask.float()
        sum_lp = token_lp.sum(dim=-1)
        tok_cnt = valid_mask.float().sum(dim=-1).clamp(min=1.0)
        mean_nll = -(sum_lp / tok_cnt)
    return sum_lp, mean_nll


def _eval_sft_val_loss(
    model: Any,
    val_packed: list[tuple[list[int], list[int], int]],
    batch_size: int,
    pad_id: int,
    device: str,
    use_amp: bool,
) -> float:
    import torch

    if not val_packed:
        return float("nan")
    was_train = model.training
    model.eval()
    losses: list[float] = []
    with torch.no_grad():
        for i in range(0, len(val_packed), batch_size):
            batch = val_packed[i : i + batch_size]
            l_val = _suffix_batch_ce(model, batch, pad_id, device, use_amp)
            losses.append(float(l_val.item()))
    if was_train:
        model.train()
    return sum(losses) / max(len(losses), 1)


def _save_peft_checkpoint(model: Any, tok: Any, base_model_path: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(dest))
    cfg_path = dest / "adapter_config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["base_model_name_or_path"] = os.path.abspath(base_model_path)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tok.save_pretrained(str(dest))


def _write_tiny_stub_adapter(dest: Path, base_model_path: str, stage: str, r: int = 16, lora_alpha: int = 32) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cfg = {
        "peft_type": "LORA",
        "task_type": "CAUSAL_LM",
        "r": int(r),
        "lora_alpha": int(lora_alpha),
        "target_modules": list(LORA_TARGETS),
        "base_model_name_or_path": os.path.abspath(base_model_path),
        "tiny_cpu_stub": True,
        "stage": stage,
    }
    (dest / "adapter_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def train_sft_stage(
    model_path: str,
    out_dir: str | Path,
    max_len: int = 2560,
    epochs: float = 1.0,
    max_steps: int = 0,
    lr: float = 1.5e-4,
    batch_size: int = 4,
    grad_accum: int = 4,
    r: int = 16,
    lora_alpha: int = 32,
    tiny: bool = False,
    tiny_torch: bool = False,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    train_rows = _load_jsonl(out_path / "compact_sft_train.jsonl")
    val_path = out_path / "compact_sft_val.jsonl"
    val_rows = _load_jsonl(val_path) if val_path.is_file() else []
    for row in train_rows:
        assert_train_seed(int(row["seed"]), split="train")
    for row in val_rows:
        assert_train_seed(int(row["seed"]), split="val")

    if _use_tiny_cpu_stub(tiny, model_path, tiny_torch=tiny_torch):
        t0 = time.time()
        total_steps = max_steps if max_steps > 0 else 2
        sft_dir = out_path / "lora_sft"
        _write_tiny_stub_adapter(sft_dir, model_path, stage="sft", r=r, lora_alpha=lora_alpha)
        curve_records = [
            {
                "stage": "sft",
                "step": step_i,
                "total_steps": total_steps,
                "epoch": round(step_i / max(1, total_steps), 4),
                "loss": round(1.8 - 0.25 * step_i, 5),
                "val_loss": round(1.75 - 0.2 * step_i, 5),
                "lr": round(float(lr), 8),
                "tokens_seen": step_i * 256,
                "tok_per_s": 2560.0,
                "elapsed_s": round(time.time() - t0, 3),
            }
            for step_i in range(1, total_steps + 1)
        ]
        _append_curve(out_path, curve_records, stage_to_replace="sft")
        summary = {
            "stage": "sft",
            "device": "cpu_tiny_stub",
            "packed_train": len(train_rows),
            "packed_val": len(val_rows),
            "tokenize_seconds": 0.0,
            "steps": total_steps,
            "init_val_loss": 1.75,
            "best_val_loss": curve_records[-1]["val_loss"],
            "final_train_loss": curve_records[-1]["loss"],
            "tokens_seen": curve_records[-1]["tokens_seen"],
            "seconds": round(time.time() - t0, 3),
            "adapter_dir": str(sft_dir),
        }
        (out_path / "sft_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    import torch
    from peft import LoraConfig, get_peft_model

    tok = _load_tokenizer(model_path)
    pad_id = int(tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id)

    t_tok = time.time()
    packed_train = [
        p for r_item in train_rows if (p := pack_compact_turn_ids(r_item, tok, max_len=max_len)) is not None
    ]
    packed_val = [
        p for r_item in val_rows[:256] if (p := pack_compact_turn_ids(r_item, tok, max_len=max_len)) is not None
    ]
    if not packed_train:
        raise RuntimeError("no packed SFT training examples produced")

    rng = random.Random(42)
    rng.shuffle(packed_train)

    device = "cuda" if (torch.cuda.is_available() and not tiny) else "cpu"
    use_amp = device == "cuda"
    dtype = torch.float16 if use_amp else torch.float32
    base_model = _load_causal_lm(model_path, dtype=dtype, tiny=tiny, vocab_size=len(tok))
    base_model.config.use_cache = False
    base_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base_model.enable_input_require_grads()

    lora_cfg = LoraConfig(
        r=r,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        target_modules=list(LORA_TARGETS),
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(base_model, lora_cfg)
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()
    model.to(device)

    eff_bs = batch_size * grad_accum
    steps_per_epoch = max(1, math.ceil(len(packed_train) / eff_bs))
    total_steps = max_steps if max_steps > 0 else max(1, int(math.ceil(steps_per_epoch * epochs)))
    warmup_steps = max(1, int(0.05 * total_steps))

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=0.01)

    def lr_lambda(step_idx: int) -> float:
        if step_idx < warmup_steps:
            return float(step_idx + 1) / float(warmup_steps)
        prog = float(step_idx - warmup_steps) / float(max(1, total_steps - warmup_steps))
        return 0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * min(1.0, prog)))

    sched = torch.optim.lr_scheduler.LambdaLR(opt, lr_lambda)
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    val_every = max(25, total_steps // 6)
    init_val_loss = _eval_sft_val_loss(model, packed_val, batch_size, pad_id, device, use_amp)
    best_val_loss = init_val_loss
    best_lora_state = {
        k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
    }

    curve_records: list[dict[str, Any]] = []
    model.train()
    cursor = 0
    tokens_seen = 0
    t0 = time.time()

    for step in range(1, total_steps + 1):
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for _ in range(grad_accum):
            if cursor + batch_size > len(packed_train):
                rng.shuffle(packed_train)
                cursor = 0
            mb = packed_train[cursor : cursor + batch_size]
            cursor += batch_size
            mb_loss = _suffix_batch_ce(model, mb, pad_id, device, use_amp) / grad_accum
            scaler.scale(mb_loss).backward()
            step_loss += float(mb_loss.item())
            tokens_seen += sum(len(x[0]) for x in mb)

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()

        elapsed = time.time() - t0
        rec: dict[str, Any] = {
            "stage": "sft",
            "step": step,
            "total_steps": total_steps,
            "epoch": round(step / steps_per_epoch, 4),
            "loss": round(step_loss, 5),
            "lr": round(float(sched.get_last_lr()[0]), 8),
            "tokens_seen": tokens_seen,
            "tok_per_s": round(tokens_seen / max(elapsed, 1e-6), 1),
            "elapsed_s": round(elapsed, 1),
        }
        if packed_val and (step % val_every == 0 or step == total_steps):
            v_loss = _eval_sft_val_loss(model, packed_val, batch_size, pad_id, device, use_amp)
            rec["val_loss"] = round(v_loss, 5)
            if v_loss <= best_val_loss:
                best_val_loss = v_loss
                best_lora_state = {
                    k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
                }
        curve_records.append(rec)
        if step == 1 or step % 20 == 0 or step == total_steps:
            print(f"[sft] {json.dumps(rec)}", flush=True)

    if best_lora_state:
        with torch.no_grad():
            cur_sd = model.state_dict()
            for k, v in best_lora_state.items():
                if k in cur_sd:
                    cur_sd[k].copy_(v.to(cur_sd[k].device, dtype=cur_sd[k].dtype))

    sft_dir = out_path / "lora_sft"
    _save_peft_checkpoint(model, tok, model_path, sft_dir)
    _append_curve(out_path, curve_records, stage_to_replace="sft")

    summary = {
        "stage": "sft",
        "device": device,
        "packed_train": len(packed_train),
        "packed_val": len(packed_val),
        "tokenize_seconds": round(time.time() - t_tok, 2),
        "steps": total_steps,
        "init_val_loss": round(init_val_loss, 5) if init_val_loss == init_val_loss else None,
        "best_val_loss": round(best_val_loss, 5) if best_val_loss == best_val_loss else None,
        "final_train_loss": curve_records[-1]["loss"],
        "tokens_seen": tokens_seen,
        "seconds": round(time.time() - t0, 2),
        "adapter_dir": str(sft_dir),
    }
    with open(out_path / "sft_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    del model, base_model
    if device == "cuda":
        torch.cuda.empty_cache()
    return summary


def _precompute_ref_logprobs(
    model: Any,
    packed_pairs: list[dict[str, Any]],
    batch_size: int,
    pad_id: int,
    device: str,
    use_amp: bool,
) -> list[tuple[float, float]]:
    import torch

    was_train = model.training
    model.eval()
    out: list[tuple[float, float]] = []
    with torch.no_grad():
        for i in range(0, len(packed_pairs), batch_size):
            chunk = packed_pairs[i : i + batch_size]
            c_seqs = [(p["chosen_ids"], p["chosen_labels"], p["prompt_len"]) for p in chunk]
            r_seqs = [(p["rejected_ids"], p["rejected_labels"], p["prompt_len"]) for p in chunk]
            c_lp, _ = _sequence_sum_and_mean_logprob(model, c_seqs, pad_id, device, use_amp)
            r_lp, _ = _sequence_sum_and_mean_logprob(model, r_seqs, pad_id, device, use_amp)
            for cl, rl in zip(c_lp.tolist(), r_lp.tolist()):
                out.append((float(cl), float(rl)))
    if was_train:
        model.train()
    return out


def _eval_dpo_val(
    model: Any,
    val_items: list[tuple[dict[str, Any], tuple[float, float]]],
    batch_size: int,
    beta: float,
    pad_id: int,
    device: str,
    use_amp: bool,
) -> dict[str, float]:
    import torch

    if not val_items:
        return {"val_dpo_loss": float("nan"), "val_pref_acc": float("nan"), "val_margin": float("nan")}
    was_train = model.training
    model.eval()
    pi_c_all: list[float] = []
    pi_r_all: list[float] = []
    ref_c_all: list[float] = []
    ref_r_all: list[float] = []
    with torch.no_grad():
        for i in range(0, len(val_items), batch_size):
            sub = val_items[i : i + batch_size]
            c_seqs = [(x[0]["chosen_ids"], x[0]["chosen_labels"], x[0]["prompt_len"]) for x in sub]
            r_seqs = [(x[0]["rejected_ids"], x[0]["rejected_labels"], x[0]["prompt_len"]) for x in sub]
            c_lp, _ = _sequence_sum_and_mean_logprob(model, c_seqs, pad_id, device, use_amp)
            r_lp, _ = _sequence_sum_and_mean_logprob(model, r_seqs, pad_id, device, use_amp)
            pi_c_all.extend(float(v) for v in c_lp.tolist())
            pi_r_all.extend(float(v) for v in r_lp.tolist())
            ref_c_all.extend(float(x[1][0]) for x in sub)
            ref_r_all.extend(float(x[1][1]) for x in sub)
    if was_train:
        model.train()
    m = dpo_loss_from_logprobs_py(pi_c_all, pi_r_all, ref_c_all, ref_r_all, beta=beta)
    return {
        "val_dpo_loss": round(m["loss"], 5),
        "val_pref_acc": round(m["pref_acc"], 4),
        "val_margin": round(m["reward_margin"], 5),
    }


def train_dpo_stage(
    model_path: str,
    out_dir: str | Path,
    max_len: int = 2560,
    epochs: float = 1.0,
    max_steps: int = 0,
    beta: float = 0.15,
    lr: float = 5e-6,
    sft_anchor: float = 0.05,
    batch_size: int = 2,
    grad_accum: int = 4,
    tiny: bool = False,
    tiny_torch: bool = False,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    sft_dir = out_path / "lora_sft"
    if not sft_dir.is_dir():
        raise RuntimeError(f"missing SFT checkpoint directory {sft_dir}")

    train_pairs_raw = _load_jsonl(out_path / "compact_dpo_train.jsonl")
    val_path = out_path / "compact_dpo_val.jsonl"
    val_pairs_raw = _load_jsonl(val_path) if val_path.is_file() else []
    for p in train_pairs_raw:
        assert_train_seed(int(p["seed"]), split="train")
    for p in val_pairs_raw:
        assert_train_seed(int(p["seed"]), split="val")

    if _use_tiny_cpu_stub(tiny, model_path, tiny_torch=tiny_torch):
        t0 = time.time()
        total_steps = max_steps if max_steps > 0 else 2
        sample_n = max(1, len(train_pairs_raw))
        init_m = dpo_loss_from_logprobs_py([-1.0] * sample_n, [-1.0] * sample_n, [-1.0] * sample_n, [-1.0] * sample_n, beta=beta)
        fin_m = dpo_loss_from_logprobs_py([-0.6] * sample_n, [-1.4] * sample_n, [-1.0] * sample_n, [-1.0] * sample_n, beta=beta)
        dpo_dir = out_path / "lora_sft_dpo"
        _write_tiny_stub_adapter(dpo_dir, model_path, stage="dpo")
        curve_records = [
            {
                "stage": "dpo",
                "step": total_steps,
                "total_steps": total_steps,
                "epoch": 1.0,
                "loss": round(fin_m["loss"], 5),
                "dpo_loss": round(fin_m["loss"], 5),
                "nll_chosen": 0.45,
                "reward_margin": round(fin_m["reward_margin"], 5),
                "pref_acc": round(fin_m["pref_acc"], 4),
                "val_dpo_loss": round(fin_m["loss"], 5),
                "val_pref_acc": round(fin_m["pref_acc"], 4),
                "val_margin": round(fin_m["reward_margin"], 5),
                "lr": round(float(lr), 9),
                "elapsed_s": round(time.time() - t0, 3),
            }
        ]
        _append_curve(out_path, curve_records, stage_to_replace="dpo")
        summary = {
            "stage": "dpo",
            "device": "cpu_tiny_stub",
            "packed_train_pairs": len(train_pairs_raw),
            "packed_val_pairs": len(val_pairs_raw),
            "beta": beta,
            "lr": lr,
            "sft_anchor": sft_anchor,
            "steps": total_steps,
            "init_val": {
                "val_dpo_loss": round(init_m["loss"], 5),
                "val_pref_acc": round(init_m["pref_acc"], 4),
                "val_margin": round(init_m["reward_margin"], 5),
            },
            "best_val_dpo_loss": round(fin_m["loss"], 5),
            "final_step": curve_records[-1],
            "seconds": round(time.time() - t0, 3),
            "adapter_dir": str(dpo_dir),
        }
        (out_path / "dpo_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    import torch
    import torch.nn.functional as F
    from peft import PeftModel

    tok = _load_tokenizer(model_path)
    pad_id = int(tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id)

    rng_sub = random.Random(101)
    pairs_pool = list(train_pairs_raw)
    rng_sub.shuffle(pairs_pool)
    if len(pairs_pool) > 640:
        pairs_pool = pairs_pool[:640]

    packed_train = [
        pk for item in pairs_pool if (pk := pack_compact_dpo_pair_ids(item, tok, max_len=max_len)) is not None
    ]
    packed_val = [
        pk for item in val_pairs_raw[:160] if (pk := pack_compact_dpo_pair_ids(item, tok, max_len=max_len)) is not None
    ]
    if not packed_train:
        raise RuntimeError("no packed DPO pairs produced")

    device = "cuda" if (torch.cuda.is_available() and not tiny) else "cpu"
    use_amp = device == "cuda"
    dtype = torch.float16 if use_amp else torch.float32

    base_model = _load_causal_lm(model_path, dtype=dtype, tiny=tiny, vocab_size=len(tok))
    base_model.config.use_cache = False
    base_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base_model.enable_input_require_grads()
    model = PeftModel.from_pretrained(base_model, str(sft_dir), is_trainable=True, local_files_only=True)
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()
    model.to(device)

    t0 = time.time()
    ref_train = _precompute_ref_logprobs(model, packed_train, batch_size * 2, pad_id, device, use_amp)
    ref_val = _precompute_ref_logprobs(model, packed_val, batch_size * 2, pad_id, device, use_amp)

    train_items = list(zip(packed_train, ref_train))
    val_items = list(zip(packed_val, ref_val))
    rng = random.Random(101)
    rng.shuffle(train_items)

    eff_bs = batch_size * grad_accum
    steps_per_epoch = max(1, math.ceil(len(train_items) / eff_bs))
    total_steps = max_steps if max_steps > 0 else max(1, int(math.ceil(steps_per_epoch * epochs)))
    warmup_steps = max(1, int(0.08 * total_steps))

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1.0, float(s + 1) / float(warmup_steps))
        * (0.2 + 0.8 * 0.5 * (1.0 + math.cos(math.pi * min(1.0, float(s) / float(max(1, total_steps)))))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    init_val = _eval_dpo_val(model, val_items, batch_size * 2, beta, pad_id, device, use_amp)
    best_val_loss = init_val["val_dpo_loss"]
    best_lora_state = {
        k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
    }
    val_every = max(20, total_steps // 5)

    curve_records: list[dict[str, Any]] = []
    model.train()
    cursor = 0
    for step in range(1, total_steps + 1):
        opt.zero_grad(set_to_none=True)
        tot_loss_acc = 0.0
        dpo_loss_acc = 0.0
        nll_acc = 0.0
        margin_acc = 0.0
        pref_acc = 0.0
        for _ in range(grad_accum):
            if cursor + batch_size > len(train_items):
                rng.shuffle(train_items)
                cursor = 0
            mb = train_items[cursor : cursor + batch_size]
            cursor += batch_size
            c_seqs = [(x[0]["chosen_ids"], x[0]["chosen_labels"], x[0]["prompt_len"]) for x in mb]
            r_seqs = [(x[0]["rejected_ids"], x[0]["rejected_labels"], x[0]["prompt_len"]) for x in mb]
            ref_c = torch.tensor([x[1][0] for x in mb], dtype=torch.float32, device=device)
            ref_r = torch.tensor([x[1][1] for x in mb], dtype=torch.float32, device=device)
            ev_w = torch.tensor(
                [min(1.75, max(0.75, 0.75 + float(x[0]["margin_ev"]))) for x in mb],
                dtype=torch.float32,
                device=device,
            )
            pi_c, nll_c = _sequence_sum_and_mean_logprob(model, c_seqs, pad_id, device, use_amp)
            pi_r, _ = _sequence_sum_and_mean_logprob(model, r_seqs, pad_id, device, use_amp)
            u = beta * ((pi_c - pi_r) - (ref_c - ref_r))
            raw_dpo = -F.logsigmoid(u)
            weighted_dpo = (raw_dpo * ev_w).mean() / ev_w.mean()
            anchor_nll = nll_c.mean()
            loss = (weighted_dpo + sft_anchor * anchor_nll) / grad_accum
            scaler.scale(loss).backward()
            tot_loss_acc += float(loss.item())
            dpo_loss_acc += float(raw_dpo.mean().item()) / grad_accum
            nll_acc += float(anchor_nll.item()) / grad_accum
            margin_acc += float(u.mean().item()) / grad_accum
            pref_acc += float((u > 0).float().mean().item()) / grad_accum

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()

        rec: dict[str, Any] = {
            "stage": "dpo",
            "step": step,
            "total_steps": total_steps,
            "epoch": round(step / steps_per_epoch, 4),
            "loss": round(tot_loss_acc, 5),
            "dpo_loss": round(dpo_loss_acc, 5),
            "nll_chosen": round(nll_acc, 5),
            "reward_margin": round(margin_acc, 5),
            "pref_acc": round(pref_acc, 4),
            "lr": round(float(sched.get_last_lr()[0]), 9),
            "elapsed_s": round(time.time() - t0, 1),
        }
        if val_items and (step % val_every == 0 or step == total_steps):
            v_metrics = _eval_dpo_val(model, val_items, batch_size * 2, beta, pad_id, device, use_amp)
            rec.update(v_metrics)
            if v_metrics["val_dpo_loss"] <= best_val_loss:
                best_val_loss = v_metrics["val_dpo_loss"]
                best_lora_state = {
                    k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
                }
        curve_records.append(rec)
        if step == 1 or step % 20 == 0 or step == total_steps:
            print(f"[dpo] {json.dumps(rec)}", flush=True)

    if best_lora_state:
        with torch.no_grad():
            cur_sd = model.state_dict()
            for k, v in best_lora_state.items():
                if k in cur_sd:
                    cur_sd[k].copy_(v.to(cur_sd[k].device, dtype=cur_sd[k].dtype))

    dpo_dir = out_path / "lora_sft_dpo"
    _save_peft_checkpoint(model, tok, model_path, dpo_dir)
    _append_curve(out_path, curve_records, stage_to_replace="dpo")

    summary = {
        "stage": "dpo",
        "device": device,
        "packed_train_pairs": len(packed_train),
        "packed_val_pairs": len(packed_val),
        "beta": beta,
        "lr": lr,
        "sft_anchor": sft_anchor,
        "steps": total_steps,
        "init_val": init_val,
        "best_val_dpo_loss": best_val_loss if best_val_loss == best_val_loss else None,
        "final_step": curve_records[-1],
        "seconds": round(time.time() - t0, 2),
        "adapter_dir": str(dpo_dir),
    }
    with open(out_path / "dpo_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    del model, base_model
    if device == "cuda":
        torch.cuda.empty_cache()
    return summary


def compute_world_secret_tag(secret: str | None) -> str | None:
    if secret is None or not secret:
        return None
    return f"sha256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:16]}"


@contextmanager
def scoped_world_secret(secret: str | None):
    from train.eval_compact_hf import _world_secret_scope

    prev_env = os.environ.get("CANARY_WORLD_SECRET")
    use_inproc = secret is not None and len(secret.encode("utf-8")) >= 16
    try:
        if secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = secret
        if use_inproc:
            with _world_secret_scope(secret):
                yield
        else:
            yield
    finally:
        if prev_env is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_env


def verify_episode_replay(ep_dict: dict[str, Any], world_secret: str | None = None) -> dict[str, Any]:
    with scoped_world_secret(world_secret):
        env = Env(tier=str(ep_dict["tier"]), seed=int(ep_dict["seed"]))
        for idx, st in enumerate(ep_dict.get("steps") or []):
            res = env.call(st["tool"], st["args"])
            rec_res = st.get("result") or {}
            if "ok" in rec_res and bool(res.ok) != bool(rec_res["ok"]):
                raise ValueError(
                    f"replay ok mismatch at step {idx} for {ep_dict['agent']} {ep_dict['tier']}:{ep_dict['seed']}"
                )
        replayed = env.result(str(ep_dict["agent"]))
    if abs(float(replayed.score) - float(ep_dict["score"])) > 1e-8:
        raise ValueError(f"replay score mismatch: {replayed.score} != {ep_dict['score']}")
    if bool(replayed.correct) != bool(ep_dict["correct"]):
        raise ValueError("replay correct mismatch")
    if replayed.accused != ep_dict["accused"]:
        raise ValueError("replay accused mismatch")
    if int(replayed.final_day) != int(ep_dict["final_day"]):
        raise ValueError("replay final_day mismatch")
    if replayed.end_reason != ep_dict["end_reason"]:
        raise ValueError(f"replay end_reason mismatch: {replayed.end_reason} != {ep_dict['end_reason']}")
    meta = dict(ep_dict.get("meta") or {})
    if "V" not in meta:
        meta["V"] = float(replayed.meta.get("V", 0.0))
    meta["replay_verified"] = True
    out = dict(ep_dict)
    out["meta"] = meta
    return out


verify_episode = verify_episode_replay


def verify_compact_episode_file(
    path: str | Path,
    world_secret: str | None = None,
) -> dict[str, Any]:
    from train.eval_compact_hf import verify_episode_file

    report = verify_episode_file(path, world_secret=world_secret)
    if not report.get("replay_ok") or not report.get("data_rule_clean"):
        raise ValueError(
            f"episode file verification failed for {path}: "
            f"mismatches={report.get('mismatch_count')}, excluded={report.get('excluded_count')}"
        )
    if world_secret is not None:
        exp_tag = compute_world_secret_tag(world_secret)
        if report.get("world_secret_tag") != exp_tag:
            raise ValueError(
                f"episode file world_secret_tag mismatch for {path}: "
                f"{report.get('world_secret_tag')!r} != {exp_tag!r}"
            )
    return report


def compute_episode_luck_adjusted_ev(ep_dict: dict[str, Any]) -> tuple[float, float | None]:
    if not ep_dict.get("accused"):
        return 0.0, None
    ep_obj = episode_from_dict(ep_dict)
    audit = audit_episode(ep_obj)
    p_acc = audit.get("p_accused")
    meta = ep_dict.get("meta") or {}
    v_val = meta.get("V", meta.get("V_final"))
    if p_acc is None or v_val is None:
        return float(ep_dict["score"]), None
    ev = float(p_acc) * float(v_val) - (1.0 - float(p_acc))
    return ev, float(p_acc)


def bootstrap_mean_ci(xs: list[float], n_boot: int = 4000, rng_seed: int = 0) -> dict[str, float]:
    n = len(xs)
    if n == 0:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0}
    mean_v = sum(xs) / n
    if n == 1:
        return {"mean": round(mean_v, 6), "ci95_lo": round(mean_v, 6), "ci95_hi": round(mean_v, 6)}
    rng = random.Random(rng_seed)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int(0.025 * n_boot)]
    hi = means[min(n_boot - 1, int(0.975 * n_boot))]
    return {
        "mean": round(mean_v, 6),
        "ci95_lo": round(lo, 6),
        "ci95_hi": round(hi, 6),
    }


def summarize_episode_group(eps: list[dict[str, Any]], rng_seed: int = 0) -> dict[str, Any]:
    n = len(eps)
    if n == 0:
        return {"n": 0}
    scores = [float(e["score"]) for e in eps]
    accs = [1.0 if bool(e["correct"]) else 0.0 for e in eps]
    wrong_acc = [1.0 if (e.get("end_reason") == "accused" and not bool(e["correct"])) else 0.0 for e in eps]
    abstain = [1.0 if e.get("end_reason") != "accused" else 0.0 for e in eps]
    horizon_abstain = [1.0 if e.get("end_reason") == "horizon" else 0.0 for e in eps]

    luck_evs: list[float] = []
    p_accs: list[float] = []
    for e in eps:
        meta = e.get("meta") or {}
        if "luck_adjusted_ev" in meta:
            ev_v = float(meta["luck_adjusted_ev"])
            p_v = meta.get("p_accused")
        else:
            ev_v, p_v = compute_episode_luck_adjusted_ev(e)
        luck_evs.append(ev_v)
        if p_v is not None:
            p_accs.append(float(p_v))

    total_steps = sum(len(e.get("steps") or []) for e in eps)
    invalid_parse = sum(int((e.get("meta") or {}).get("invalid_calls", 0)) for e in eps)
    env_err_calls = sum(
        1
        for e in eps
        for st in (e.get("steps") or [])
        if not bool((st.get("result") or {}).get("ok", True))
    )
    strict_valid_calls = max(0, total_steps - invalid_parse - env_err_calls)
    accuse_days = [int(e["final_day"]) for e in eps if e.get("end_reason") == "accused"]
    replay_ok = sum(1 for e in eps if (e.get("meta") or {}).get("replay_verified") is True)

    return {
        "n": n,
        "score": bootstrap_mean_ci(scores, rng_seed=rng_seed),
        "luck_adjusted_ev": bootstrap_mean_ci(luck_evs, rng_seed=rng_seed + 1),
        "accuracy": bootstrap_mean_ci(accs, rng_seed=rng_seed + 2),
        "wrong_accuse_rate": round(sum(wrong_acc) / n, 6),
        "abstain_rate": round(sum(abstain) / n, 6),
        "horizon_abstain_rate": round(sum(horizon_abstain) / n, 6),
        "valid_tool_rate": round(strict_valid_calls / max(total_steps, 1), 6),
        "valid_parse_rate": round(max(0, total_steps - invalid_parse) / max(total_steps, 1), 6),
        "valid_env_ok_rate": round(max(0, total_steps - env_err_calls) / max(total_steps, 1), 6),
        "mean_steps": round(total_steps / n, 2),
        "mean_accuse_day": round(sum(accuse_days) / len(accuse_days), 2) if accuse_days else None,
        "mean_p_accused": round(sum(p_accs) / len(p_accs), 4) if p_accs else None,
        "end_reasons": dict(Counter(str(e.get("end_reason")) for e in eps)),
        "replay_verified": f"{replay_ok}/{n}",
    }


def paired_delta_summary(
    after_eps: list[dict[str, Any]],
    before_eps: list[dict[str, Any]],
    rng_seed: int = 0,
) -> dict[str, Any]:
    by_key_a = {(str(e["tier"]), int(e["seed"])): e for e in after_eps}
    by_key_b = {(str(e["tier"]), int(e["seed"])): e for e in before_eps}
    shared_keys = sorted(set(by_key_a) & set(by_key_b))
    if not shared_keys:
        return {"n_paired": 0}
    score_diffs: list[float] = []
    ev_diffs: list[float] = []
    acc_diffs: list[float] = []
    wrong_diffs: list[float] = []
    wins = ties = losses = 0
    for k in shared_keys:
        ea, eb = by_key_a[k], by_key_b[k]
        ds = float(ea["score"]) - float(eb["score"])
        score_diffs.append(ds)
        if ds > 1e-9:
            wins += 1
        elif ds < -1e-9:
            losses += 1
        else:
            ties += 1
        eva = float((ea.get("meta") or {}).get("luck_adjusted_ev", compute_episode_luck_adjusted_ev(ea)[0]))
        evb = float((eb.get("meta") or {}).get("luck_adjusted_ev", compute_episode_luck_adjusted_ev(eb)[0]))
        ev_diffs.append(eva - evb)
        acc_diffs.append((1.0 if ea["correct"] else 0.0) - (1.0 if eb["correct"] else 0.0))
        wa = 1.0 if (ea.get("end_reason") == "accused" and not ea["correct"]) else 0.0
        wb = 1.0 if (eb.get("end_reason") == "accused" and not eb["correct"]) else 0.0
        wrong_diffs.append(wa - wb)
    return {
        "n_paired": len(shared_keys),
        "score_diff": bootstrap_mean_ci(score_diffs, rng_seed=rng_seed),
        "luck_adjusted_ev_diff": bootstrap_mean_ci(ev_diffs, rng_seed=rng_seed + 11),
        "accuracy_diff": bootstrap_mean_ci(acc_diffs, rng_seed=rng_seed + 22),
        "wrong_accuse_rate_diff": round(sum(wrong_diffs) / len(shared_keys), 6),
        "wins": wins,
        "ties": ties,
        "losses": losses,
    }


def normal_mean_ci95(xs: list[float]) -> dict[str, float]:
    n = len(xs)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0}
    m = sum(xs) / n
    if n < 2:
        return {"mean": round(m, 6), "ci95_low": round(m, 6), "ci95_high": round(m, 6)}
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    hw = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(m, 6),
        "ci95_low": round(m - hw, 6),
        "ci95_high": round(m + hw, 6),
    }


def _get_eval_eos_ids(tok: Any) -> list[int]:
    eos_ids: list[int] = []
    for cand in (tok.eos_token_id, tok.pad_token_id):
        if isinstance(cand, int) and cand not in eos_ids:
            eos_ids.append(cand)
    tc_end = tok.convert_tokens_to_ids("</tool_call>")
    if isinstance(tc_end, int) and tc_end >= 0 and tc_end != getattr(tok, "unk_token_id", None):
        if tc_end not in eos_ids:
            eos_ids.append(tc_end)
    return eos_ids


def _configure_eval_eos(model: Any, tok: Any) -> None:
    eos_ids = _get_eval_eos_ids(tok)
    if eos_ids and getattr(model, "generation_config", None) is not None:
        model.generation_config.eos_token_id = eos_ids


def _load_eval_checkpoint(model_path: str, adapter_dir: Path | None, tiny: bool = False):
    import torch

    tok = _load_tokenizer(model_path)
    device = "cuda" if (torch.cuda.is_available() and not tiny) else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    base_m = _load_causal_lm(model_path, dtype=dtype, tiny=tiny, vocab_size=len(tok))
    if adapter_dir is not None:
        from peft import PeftModel

        peft_m = PeftModel.from_pretrained(
            base_m,
            str(adapter_dir),
            is_trainable=False,
            local_files_only=True,
        )
        model = peft_m.merge_and_unload()
    else:
        model = base_m
    model.to(device).eval()
    _configure_eval_eos(model, tok)
    return model, tok, device


def _batched_greedy_generate_texts(
    model: Any,
    tok: Any,
    unique_prompts: list[tuple[tuple[int, ...], list[int]]],
    max_new: int,
    sub_batch_size: int = 32,
) -> dict[tuple[int, ...], str]:
    import torch

    pad_id = int(tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id)
    eos_ids = _get_eval_eos_ids(tok)
    eos_set = set(eos_ids)
    device = next(model.parameters()).device
    results: dict[tuple[int, ...], str] = {}

    for start in range(0, len(unique_prompts), sub_batch_size):
        sub = unique_prompts[start : start + sub_batch_size]
        max_p = max(len(ids) for _, ids in sub)
        inp = torch.full((len(sub), max_p), pad_id, dtype=torch.long, device=device)
        att = torch.zeros((len(sub), max_p), dtype=torch.long, device=device)
        for bi, (_k, ids) in enumerate(sub):
            offset = max_p - len(ids)
            inp[bi, offset:] = torch.tensor(ids, dtype=torch.long, device=device)
            att[bi, offset:] = 1
        with torch.no_grad():
            out = model.generate(
                input_ids=inp,
                attention_mask=att,
                max_new_tokens=max_new,
                do_sample=False,
                use_cache=True,
                pad_token_id=pad_id,
                eos_token_id=eos_ids if eos_ids else None,
            )
        for bi, (key, _ids) in enumerate(sub):
            gen_ids = out[bi, max_p:].tolist()
            trimmed: list[int] = []
            for tid in gen_ids:
                trimmed.append(int(tid))
                if int(tid) in eos_set:
                    break
            results[key] = tok.decode(trimmed, skip_special_tokens=False)
    return results


def _run_batched_compact_episodes(
    agent_tag: str,
    model: Any,
    tok: Any,
    tiers: tuple[str, ...],
    seeds: list[int],
    world_secret: str | None,
    out_jsonl: Path | None,
    tail_turns: int = 4,
    max_ctx: int = 2560,
    max_new: int = 420,
    batch_size: int = 30,
    memo: dict[tuple[int, ...], str] | None = None,
    verify_replay: bool = True,
    max_steps_cap: int | None = None,
) -> list[dict[str, Any]]:
    prompt_memo = memo if memo is not None else {}
    tasks = [(tier, seed) for seed in seeds for tier in tiers]
    episodes: list[dict[str, Any]] = []
    t0 = time.time()

    fh = open(out_jsonl, "w", encoding="utf-8") if out_jsonl is not None else None
    try:
        with scoped_world_secret(world_secret):
            for c_start in range(0, len(tasks), batch_size):
                chunk = tasks[c_start : c_start + batch_size]
                t_chunk = time.time()
                envs = [Env(tier=t_name, seed=s_val) for t_name, s_val in chunk]
                pols = [
                    CompactLoRAPolicy(
                        model=None,
                        tokenizer=tok,
                        name=agent_tag,
                        max_ctx=max_ctx,
                        max_new=max_new,
                        tail_turns=tail_turns,
                        kv_reuse=False,
                    )
                    for _ in chunk
                ]
                max_caps = [
                    min(e.p.tool_call_cap + 4, int(max_steps_cap)) if max_steps_cap is not None else (e.p.tool_call_cap + 4)
                    for e in envs
                ]
                step_counts = [0 for _ in chunk]
                for env_i, pol_i in zip(envs, pols):
                    pol_i.reset(env_i.tools_spec(), env_i.instruction())

                while True:
                    active_idx = [
                        i for i, env_i in enumerate(envs) if (not env_i.done) and step_counts[i] < max_caps[i]
                    ]
                    if not active_idx:
                        break
                    step_keys: dict[int, tuple[int, ...]] = {}
                    uncached_map: dict[tuple[int, ...], list[int]] = {}
                    for i in active_idx:
                        p_ids = pols[i]._prompt_ids(list(envs[i].history))
                        key = tuple(p_ids)
                        step_keys[i] = key
                        if key in prompt_memo:
                            pols[i].reused += len(p_ids)
                        else:
                            pols[i].encoded += len(p_ids)
                            if key not in uncached_map:
                                uncached_map[key] = p_ids

                    if uncached_map:
                        fresh = _batched_greedy_generate_texts(
                            model=model,
                            tok=tok,
                            unique_prompts=list(uncached_map.items()),
                            max_new=max_new,
                            sub_batch_size=min(batch_size, 45),
                        )
                        prompt_memo.update(fresh)

                    for i in active_idx:
                        pols[i].set_prefetched_text(prompt_memo[step_keys[i]])
                        tool, args = pols[i].act(list(envs[i].history))
                        envs[i].call(tool, args)
                        step_counts[i] += 1

                sec_tag = (
                    f"sha256:{hashlib.sha256(world_secret.encode('utf-8')).hexdigest()[:16]}"
                    if world_secret is not None
                    else None
                )
                chunk_sec = round((time.time() - t_chunk) / max(len(chunk), 1), 3)
                for env_i, pol_i in zip(envs, pols):
                    ep = env_i.result(agent_tag)
                    ep.agent = agent_tag
                    ep.meta = dict(ep.meta or {})
                    ep.meta["invalid_calls"] = int(pol_i.invalid)
                    ep.meta["policy_calls"] = int(pol_i.calls)
                    ep.meta["eval_seconds"] = chunk_sec
                    ep.meta["prefill_tokens"] = int(pol_i.encoded)
                    ep.meta["reused_tokens"] = int(pol_i.reused)
                    if sec_tag is not None:
                        ep.meta["world_secret_tag"] = sec_tag
                    raw_d = dataclasses.asdict(ep)
                    if verify_replay:
                        verified_d = verify_episode_replay(raw_d, world_secret=world_secret)
                        ev_val, p_acc = compute_episode_luck_adjusted_ev(verified_d)
                        verified_d["meta"]["luck_adjusted_ev"] = round(ev_val, 6)
                        verified_d["meta"]["p_accused"] = p_acc
                    else:
                        verified_d = raw_d
                    episodes.append(verified_d)
                    if fh is not None:
                        fh.write(json.dumps(verified_d, default=str) + "\n")
                if fh is not None:
                    fh.flush()
    finally:
        if fh is not None:
            fh.close()

    if out_jsonl is not None:
        print(
            f"[eval] {agent_tag} wrote {len(episodes)} replay-verified episodes -> {out_jsonl.name} "
            f"(memo={len(prompt_memo)}, {time.time() - t0:.1f}s)",
            flush=True,
        )
    return episodes


def relabel_student_state_with_solver(
    tier: str,
    instruction: str,
    tools_spec: list[dict[str, Any]],
    history_prefix: list[Any],
) -> tuple[str, dict[str, Any], dict[str, float]]:
    from canary.solver import SolverPolicy
    from canary.solver.policy import accuse_value
    from canary.types import Step

    env_p = RULE_TIERS[tier]
    teacher = SolverPolicy(env_p)
    teacher.reset(tools_spec, instruction)

    cur_day = 1
    actions_used = 0
    canaries_today = 0
    today_tools: set[str] = set()
    last_ok_tool: str | None = None

    for step_idx, raw_st in enumerate(history_prefix):
        if isinstance(raw_st, dict):
            st = Step(
                t=int(raw_st.get("t", step_idx)),
                tool=str(raw_st.get("tool", "")),
                args=dict(raw_st.get("args") or {}),
                result=dict(raw_st.get("result") or {}),
            )
        else:
            st = raw_st
        teacher._ingest(st)
        res = st.result or {}
        ok = bool(res.get("ok", True))
        data = res.get("data") or {}
        if not ok:
            err_msg = str(res.get("error") or "")
            if "daily action limit" in err_msg:
                actions_used = max(actions_used, int(env_p.actions_per_day))
            elif "canary limit" in err_msg:
                canaries_today = max(canaries_today, int(env_p.canaries_per_day))
            continue
        last_ok_tool = str(st.tool)
        today_tools.add(last_ok_tool)
        if last_ok_tool in INVESTIGATIVE_TOOLS:
            actions_used += 1
        if last_ok_tool == "plant_canary":
            canaries_today += 1
        elif last_ok_tool == "status":
            if "day" in data:
                cur_day = int(data["day"])
            if "actions_left_today" in data:
                actions_used = max(0, int(env_p.actions_per_day) - int(data["actions_left_today"]))
        elif last_ok_tool == "advance_day":
            if "day" in data:
                cur_day = int(data["day"])
            actions_used = 0
            canaries_today = 0
            today_tools = set()

    teacher.obs.today = cur_day
    default_meta = {
        "top_p": round(1.0 / max(1, int(env_p.n_employees)), 8),
        "breakeven_p": round(1.0 / (1.0 + max(0.0, float(teacher.V))), 8),
        "ev_accuse": -1.0,
    }

    if not teacher.obs.employees:
        return "list_employees", {}, default_meta
    if last_ok_tool == "advance_day" or (cur_day == 1 and "status" not in today_tools):
        return "status", {}, default_meta
    if "list_documents" not in today_tools:
        return "list_documents", {"day_from": max(1, cur_day - 3), "day_to": cur_day}, default_meta
    if "check_leak_feed" not in today_tools and actions_used < int(env_p.actions_per_day):
        return "check_leak_feed", {}, default_meta

    rem_canaries = 0 if cur_day >= int(env_p.n_days) else max(0, int(env_p.canaries_per_day) - canaries_today)
    if actions_used + rem_canaries < int(env_p.actions_per_day):
        dq = teacher.decoy_queries()
        if dq:
            return str(dq[0][0]), dict(dq[0][1]), default_meta
        if cur_day > 1 and "read_access_logs" not in today_tools:
            return "read_access_logs", {"day_from": cur_day - 1, "day_to": cur_day - 1}, default_meta

    post = teacher.belief()
    best = max(post, key=post.get)
    p_best = float(post[best])
    thr = float(teacher.default_threshold())
    last = cur_day >= int(env_p.n_days)
    exp_v = float(teacher.expected_true_V())
    ev = float(accuse_value(p_best, exp_v, env_p))
    breakeven = 1.0 / (1.0 + max(0.0, float(teacher.V)))
    meta = {
        "top_p": round(p_best, 8),
        "breakeven_p": round(breakeven, 8),
        "ev_accuse": round(ev, 8),
    }

    if ev > 0.0 and (p_best >= thr or (last and p_best >= breakeven + 0.05)):
        return "accuse", {"employee": str(best)}, meta

    if (not last) and canaries_today < int(env_p.canaries_per_day) and actions_used < int(env_p.actions_per_day):
        if canaries_today > 0:
            teacher.P = dataclasses.replace(env_p, canaries_per_day=int(env_p.canaries_per_day) - canaries_today)
            teacher.min_gain_first = teacher.min_gain
        planned = teacher.plan_canaries(post)
        if planned:
            asg = canonicalize_step_args("plant_canary", {"assignment": planned[0]})["assignment"]
            title = f"Board memo draft {cur_day}" + (f" ({canaries_today + 1})" if canaries_today else "")
            return "plant_canary", {"doc_title": title, "assignment": asg}, meta

    return "advance_day", {}, meta


def build_compact_dagger_record(
    tier: str,
    seed: int,
    instruction: str,
    tools_spec: list[dict[str, Any]],
    history_prefix: list[Any],
    student_tool: str,
    student_args: dict[str, Any] | None,
    step_ok: bool = True,
    tail_turns: int = 4,
    split: str = "train",
) -> tuple[dict[str, Any], int]:
    clean_seed = assert_train_seed(int(seed), split=split)
    cr = load_compact_render()
    t_tool, t_args, t_meta = relabel_student_state_with_solver(
        tier=tier,
        instruction=instruction,
        tools_spec=tools_spec,
        history_prefix=history_prefix,
    )
    s_norm = canonicalize_step_args(student_tool, student_args if isinstance(student_args, dict) else {})
    disagree = (student_tool != t_tool) or (s_norm != t_args) or (not step_ok)
    ctools = cr.compact_tools_spec(tools_spec)
    hist_dicts = [
        dict(st_h) if isinstance(st_h, dict) else dataclasses.asdict(st_h)
        for st_h in history_prefix
    ]
    turn = cr.render_compact_turn(
        instruction,
        ctools,
        hist_dicts,
        target_step={"tool": t_tool, "args": t_args},
        tail_turns=tail_turns,
    )
    reps = 1
    if disagree:
        reps = 3
        if student_tool == "accuse" or t_tool == "accuse" or (not step_ok):
            reps = 4
    base_row = {
        "tier": tier,
        "seed": clean_seed,
        "split": split,
        "step_index": len(history_prefix),
        "target_tool": t_tool,
        "student_tool": student_tool,
        "disagree": disagree,
        "top_p": t_meta["top_p"],
        "breakeven_p": t_meta["breakeven_p"],
        "tools": ctools,
        "messages": turn["messages"],
    }
    return base_row, reps


def train_dagger_stage(
    model_path: str,
    out_dir: str | Path,
    tiers: tuple[str, ...] = TIERS,
    dagger_seed_start: int = DAGGER_SEED_START_DEFAULT,
    dagger_per_tier: int = 24,
    tail_turns: int = 4,
    max_len: int = 2560,
    max_new: int = 300,
    steps: int = 110,
    lr: float = 2.5e-5,
    batch_size: int = 8,
    grad_accum: int = 2,
    rollout_batch_size: int = 72,
    max_rollout_steps: int = 72,
    tiny: bool = False,
    tiny_torch: bool = False,
) -> dict[str, Any]:
    out_path = Path(out_dir)
    dpo_dir = out_path / "lora_sft_dpo"
    src_adapter = dpo_dir if dpo_dir.is_dir() else (out_path / "lora_sft")
    if not src_adapter.is_dir():
        raise RuntimeError(f"missing student checkpoint directory {src_adapter}")

    total_dagger_eps = dagger_per_tier * len(tiers)
    dagger_seeds = [
        assert_train_seed(dagger_seed_start + i, split="train")
        for i in range(total_dagger_eps)
    ]
    validate_train_seeds(dagger_seeds, split="train")

    tier_seed_pairs: list[tuple[str, int]] = []
    for t_idx, tier in enumerate(tiers):
        t_slice = dagger_seeds[t_idx * dagger_per_tier : (t_idx + 1) * dagger_per_tier]
        for s_val in t_slice:
            tier_seed_pairs.append((tier, s_val))

    t0 = time.time()
    if _use_tiny_cpu_stub(tiny, model_path, tiny_torch=tiny_torch):
        dagger_rows_stub: list[dict[str, Any]] = []
        student_scores_stub: list[float] = []
        disagreements_stub = 0
        visited_stub = 0
        stub_gen = lambda _turn: '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>'
        for t_name, s_val in tier_seed_pairs:
            env_s = Env(tier=t_name, seed=s_val)
            pol_s = CompactLoRAPolicy(name="student_sft_dpo", generator=stub_gen, tail_turns=tail_turns)
            pol_s.reset(env_s.tools_spec(), env_s.instruction())
            for _ in range(min(max_rollout_steps, 6)):
                if env_s.done:
                    break
                hist_b = list(env_s.history)
                s_t, s_a = pol_s.act(hist_b)
                res_s = env_s.call(s_t, s_a)
                row_s, _reps_s = build_compact_dagger_record(
                    tier=t_name,
                    seed=s_val,
                    instruction=env_s.instruction(),
                    tools_spec=env_s.tools_spec(),
                    history_prefix=hist_b,
                    student_tool=s_t,
                    student_args=s_a,
                    step_ok=bool(res_s.ok),
                    tail_turns=tail_turns,
                    split="train",
                )
                visited_stub += 1
                if row_s["disagree"]:
                    disagreements_stub += 1
                dagger_rows_stub.append(row_s)
            student_scores_stub.append(float(env_s.result("student_sft_dpo").score) if env_s.done else 0.0)
        dagger_file_stub = out_path / "compact_dagger_r1_train.jsonl"
        with open(dagger_file_stub, "w", encoding="utf-8") as fh:
            for row in dagger_rows_stub:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        dagger_dir_stub = out_path / "lora_dagger_r1"
        _write_tiny_stub_adapter(dagger_dir_stub, model_path, stage="dagger_r1")
        total_steps_stub = max(1, int(steps))
        curve_stub = [
            {
                "stage": "dagger_r1",
                "step": total_steps_stub,
                "total_steps": total_steps_stub,
                "loss": 0.42,
                "val_loss": 0.45,
                "lr": round(float(lr), 8),
                "elapsed_s": round(time.time() - t0, 3),
            }
        ]
        _append_curve(out_path, curve_stub, stage_to_replace="dagger_r1")
        summary_stub = {
            "stage": "dagger_r1",
            "device": "cpu_tiny_stub",
            "dagger_seed_range": f"{dagger_seeds[0]}..{dagger_seeds[-1]}",
            "dagger_seeds": dagger_seeds,
            "rollout_episodes": len(tier_seed_pairs),
            "visited_states": visited_stub,
            "disagreements": disagreements_stub,
            "disagreement_rate": round(disagreements_stub / max(visited_stub, 1), 6),
            "student_rollout_mean_score": round(sum(student_scores_stub) / max(len(student_scores_stub), 1), 6),
            "packed_dagger": len(dagger_rows_stub),
            "packed_anchor": len(dagger_rows_stub),
            "steps": total_steps_stub,
            "init_val_loss": 0.5,
            "best_val_loss": 0.45,
            "final_train_loss": 0.42,
            "seconds": round(time.time() - t0, 3),
            "adapter_dir": str(dagger_dir_stub),
        }
        (out_path / "dagger_summary.json").write_text(json.dumps(summary_stub, indent=2), encoding="utf-8")
        return summary_stub

    import torch
    from peft import PeftModel

    eval_model, tok, device = _load_eval_checkpoint(model_path, src_adapter, tiny=tiny)
    pad_id = int(tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id)

    dagger_rows: list[dict[str, Any]] = []
    student_scores: list[float] = []
    disagreements = 0
    visited_states = 0
    memo: dict[tuple[int, ...], str] = {}

    for c_start in range(0, len(tier_seed_pairs), rollout_batch_size):
        chunk = tier_seed_pairs[c_start : c_start + rollout_batch_size]
        envs = [Env(tier=t_name, seed=s_val) for t_name, s_val in chunk]
        pols = [
            CompactLoRAPolicy(
                model=None,
                tokenizer=tok,
                name="student_sft_dpo",
                max_ctx=max_len,
                max_new=max_new,
                tail_turns=tail_turns,
                kv_reuse=False,
            )
            for _ in chunk
        ]
        for env_i, pol_i in zip(envs, pols):
            pol_i.reset(env_i.tools_spec(), env_i.instruction())

        for _step_idx in range(max_rollout_steps):
            active_idx = [i for i, env_i in enumerate(envs) if not env_i.done]
            if not active_idx:
                break
            step_keys: dict[int, tuple[int, ...]] = {}
            uncached_map: dict[tuple[int, ...], list[int]] = {}
            for i in active_idx:
                p_ids = pols[i]._prompt_ids(list(envs[i].history))
                k = tuple(p_ids)
                step_keys[i] = k
                if k not in memo and k not in uncached_map:
                    uncached_map[k] = p_ids
            if uncached_map:
                memo.update(
                    _batched_greedy_generate_texts(
                        model=eval_model,
                        tok=tok,
                        unique_prompts=list(uncached_map.items()),
                        max_new=max_new,
                        sub_batch_size=min(rollout_batch_size, 45),
                    )
                )
            for i in active_idx:
                hist_before = list(envs[i].history)
                pols[i].set_prefetched_text(memo[step_keys[i]])
                s_tool, s_args = pols[i].act(hist_before)
                res = envs[i].call(s_tool, s_args)

                base_row, reps = build_compact_dagger_record(
                    tier=envs[i].tier,
                    seed=int(envs[i].seed),
                    instruction=envs[i].instruction(),
                    tools_spec=envs[i].tools_spec(),
                    history_prefix=hist_before,
                    student_tool=s_tool,
                    student_args=s_args,
                    step_ok=bool(res.ok),
                    tail_turns=tail_turns,
                    split="train",
                )
                visited_states += 1
                if base_row["disagree"]:
                    disagreements += 1
                for _ in range(reps):
                    dagger_rows.append(copy.copy(base_row))

        for env_i in envs:
            if env_i.done:
                student_scores.append(float(env_i.result("student_sft_dpo").score))
            else:
                student_scores.append(0.0)

    del eval_model
    if device == "cuda":
        torch.cuda.empty_cache()

    dagger_file = out_path / "compact_dagger_r1_train.jsonl"
    with open(dagger_file, "w", encoding="utf-8") as fh:
        for row in dagger_rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    packed_dagger = [
        pk for r_item in dagger_rows if (pk := pack_compact_turn_ids(r_item, tok, max_len=max_len)) is not None
    ]
    if not packed_dagger:
        raise RuntimeError("no packed DAgger examples produced")

    anchor_rows = _load_jsonl(out_path / "compact_sft_train.jsonl")
    for a_row in anchor_rows:
        assert_train_seed(int(a_row["seed"]), split="train")
    rng = random.Random(2026)
    anchor_sub = list(anchor_rows)
    rng.shuffle(anchor_sub)
    target_anchor_n = max(64, int(len(packed_dagger) * 0.65))
    packed_anchor: list[tuple[list[int], list[int], int]] = []
    for a_row in anchor_sub:
        pk = pack_compact_turn_ids(a_row, tok, max_len=max_len)
        if pk is not None:
            packed_anchor.append(pk)
            if len(packed_anchor) >= target_anchor_n:
                break

    val_path = out_path / "compact_sft_val.jsonl"
    val_rows = _load_jsonl(val_path) if val_path.is_file() else []
    for v_row in val_rows:
        assert_train_seed(int(v_row["seed"]), split="val")
    packed_val = [
        pk for v_item in val_rows[:192] if (pk := pack_compact_turn_ids(v_item, tok, max_len=max_len)) is not None
    ]

    train_pool = list(packed_dagger) + list(packed_anchor)
    rng.shuffle(train_pool)

    use_amp = device == "cuda"
    dtype = torch.float16 if use_amp else torch.float32
    base_model = _load_causal_lm(model_path, dtype=dtype, tiny=tiny, vocab_size=len(tok))
    base_model.config.use_cache = False
    base_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base_model.enable_input_require_grads()
    model = PeftModel.from_pretrained(base_model, str(src_adapter), is_trainable=True, local_files_only=True)
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()
    model.to(device)

    total_steps = max(1, int(steps))
    warmup_steps = max(1, int(0.08 * total_steps))
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt,
        lambda s: min(1.0, float(s + 1) / float(warmup_steps))
        * (0.15 + 0.85 * 0.5 * (1.0 + math.cos(math.pi * min(1.0, float(s) / float(max(1, total_steps)))))),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    init_val_loss = _eval_sft_val_loss(model, packed_val, batch_size, pad_id, device, use_amp)
    init_lora_state = {
        k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
    }
    best_val_loss = float("inf")
    best_lora_state: dict[str, Any] = {}
    val_every = max(20, total_steps // 5)

    curve_records: list[dict[str, Any]] = []
    model.train()
    cursor = 0
    t_ft = time.time()
    for step in range(1, total_steps + 1):
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for _ in range(grad_accum):
            if cursor + batch_size > len(train_pool):
                rng.shuffle(train_pool)
                cursor = 0
            mb = train_pool[cursor : cursor + batch_size]
            cursor += batch_size
            mb_loss = _suffix_batch_ce(model, mb, pad_id, device, use_amp) / grad_accum
            scaler.scale(mb_loss).backward()
            step_loss += float(mb_loss.item())

        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(trainable_params, 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()

        rec: dict[str, Any] = {
            "stage": "dagger_r1",
            "step": step,
            "total_steps": total_steps,
            "loss": round(step_loss, 5),
            "lr": round(float(sched.get_last_lr()[0]), 8),
            "elapsed_s": round(time.time() - t_ft, 1),
        }
        if packed_val and (step % val_every == 0 or step == total_steps):
            v_loss = _eval_sft_val_loss(model, packed_val, batch_size, pad_id, device, use_amp)
            rec["val_loss"] = round(v_loss, 5)
            within_guard = (not math.isfinite(init_val_loss)) or (v_loss <= init_val_loss + 0.35)
            if within_guard and v_loss <= best_val_loss:
                best_val_loss = v_loss
                best_lora_state = {
                    k: v.detach().cpu().clone() for k, v in model.state_dict().items() if "lora_" in k
                }
        curve_records.append(rec)
        if step == 1 or step % 25 == 0 or step == total_steps:
            print(f"[dagger_r1] {json.dumps(rec)}", flush=True)

    chosen_state = best_lora_state if best_lora_state else (init_lora_state if packed_val else {})
    if chosen_state:
        with torch.no_grad():
            cur_sd = model.state_dict()
            for k, v in chosen_state.items():
                if k in cur_sd:
                    cur_sd[k].copy_(v.to(cur_sd[k].device, dtype=cur_sd[k].dtype))
    if not math.isfinite(best_val_loss):
        best_val_loss = init_val_loss

    dagger_dir = out_path / "lora_dagger_r1"
    _save_peft_checkpoint(model, tok, model_path, dagger_dir)
    _append_curve(out_path, curve_records, stage_to_replace="dagger_r1")

    summary = {
        "stage": "dagger_r1",
        "device": device,
        "dagger_seed_range": f"{dagger_seeds[0]}..{dagger_seeds[-1]}",
        "dagger_seeds": dagger_seeds,
        "rollout_episodes": len(tier_seed_pairs),
        "visited_states": visited_states,
        "disagreements": disagreements,
        "disagreement_rate": round(disagreements / max(visited_states, 1), 6),
        "student_rollout_mean_score": round(sum(student_scores) / max(len(student_scores), 1), 6),
        "packed_dagger": len(packed_dagger),
        "packed_anchor": len(packed_anchor),
        "steps": total_steps,
        "init_val_loss": round(init_val_loss, 5) if init_val_loss == init_val_loss else None,
        "best_val_loss": round(best_val_loss, 5) if best_val_loss == best_val_loss else None,
        "final_train_loss": curve_records[-1]["loss"],
        "seconds": round(time.time() - t0, 2),
        "adapter_dir": str(dagger_dir),
    }
    with open(out_path / "dagger_summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    del model, base_model
    if device == "cuda":
        torch.cuda.empty_cache()
    return summary


def _run_policy_episodes(
    agent_tag: str,
    policy_factory: Any,
    tiers: tuple[str, ...],
    seeds: list[int],
    world_secret: str | None,
    out_jsonl: Path,
    reuse_existing: bool = True,
) -> list[dict[str, Any]]:
    if not seeds or not tiers:
        return []
    sec_tag = (
        f"sha256:{hashlib.sha256(world_secret.encode('utf-8')).hexdigest()[:16]}"
        if world_secret is not None
        else None
    )
    wanted_keys = [(tier, int(seed)) for seed in seeds for tier in tiers]
    if reuse_existing and out_jsonl.is_file() and out_jsonl.stat().st_size > 0:
        cached_rows = _load_jsonl(out_jsonl)
        by_key = {(str(r.get("tier")), int(r.get("seed", -1))): r for r in cached_rows}
        if len(cached_rows) == len(wanted_keys) and set(by_key) == set(wanted_keys):
            tags_ok = all(
                (sec_tag is None or (r.get("meta") or {}).get("world_secret_tag") == sec_tag)
                and (r.get("meta") or {}).get("replay_verified") is True
                for r in cached_rows
            )
            if tags_ok:
                print(f"[eval] reusing {len(cached_rows)} cached episodes -> {out_jsonl.name}", flush=True)
                return [by_key[k] for k in wanted_keys]

    episodes: list[dict[str, Any]] = []
    t0 = time.time()
    with scoped_world_secret(world_secret), open(out_jsonl, "w", encoding="utf-8") as fh:
        for seed in seeds:
            for tier in tiers:
                t_ep = time.time()
                env = Env(tier=tier, seed=seed)
                pol = policy_factory()
                ep = run_episode(env, pol, max_iters=env.p.tool_call_cap + 4)
                ep.agent = agent_tag
                ep.meta = dict(ep.meta or {})
                ep.meta["invalid_calls"] = int(getattr(pol, "invalid", 0))
                ep.meta["policy_calls"] = int(getattr(pol, "calls", len(ep.steps)))
                ep.meta["eval_seconds"] = round(time.time() - t_ep, 2)
                if getattr(pol, "encoded", None) is not None:
                    ep.meta["prefill_tokens"] = int(pol.encoded)
                    ep.meta["reused_tokens"] = int(pol.reused)
                if sec_tag is not None:
                    ep.meta["world_secret_tag"] = sec_tag
                raw_d = dataclasses.asdict(ep)
                verified_d = verify_episode_replay(raw_d, world_secret=world_secret)
                ev_val, p_acc = compute_episode_luck_adjusted_ev(verified_d)
                verified_d["meta"]["luck_adjusted_ev"] = round(ev_val, 6)
                verified_d["meta"]["p_accused"] = p_acc
                episodes.append(verified_d)
                fh.write(json.dumps(verified_d, default=str) + "\n")
                fh.flush()
    print(
        f"[eval] {agent_tag} wrote {len(episodes)} replay-verified episodes -> {out_jsonl.name} ({time.time() - t0:.1f}s)",
        flush=True,
    )
    return episodes


def _load_committed_gemini_dev_hard(dev_seeds: list[int], out_jsonl: Path) -> list[dict[str, Any]]:
    src = repo_root() / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    if not src.is_file():
        return []
    wanted = set(dev_seeds)
    by_seed: dict[int, dict[str, Any]] = {}
    for row in _load_jsonl(src):
        s = int(row["seed"])
        if row.get("tier") == "hard" and s in wanted:
            ver = verify_episode_replay(row, world_secret=None)
            ev_val, p_acc = compute_episode_luck_adjusted_ev(ver)
            ver["meta"]["luck_adjusted_ev"] = round(ev_val, 6)
            ver["meta"]["p_accused"] = p_acc
            by_seed[s] = ver
    ordered = [by_seed[s] for s in dev_seeds if s in by_seed]
    with open(out_jsonl, "w", encoding="utf-8") as fh:
        for row in ordered:
            fh.write(json.dumps(row, default=str) + "\n")
    return ordered


def format_eval_table_md(summary: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    before = summary["before"]
    after = summary["after"]
    paired = summary["paired"]
    dev_range_lbl = summary["dev_hard"]["seed_range"] or "none"
    lines: list[str] = [
        f"{h1} {summary.get('model', MODEL_LABEL_DEFAULT)} Evaluation",
        "",
        f"- run_id: `{summary.get('run_id', RUN_ID_DEFAULT)}`",
        f"- git_sha: `{summary.get('git_sha', 'unknown')}`",
        f"- model_path: `{summary.get('model_path', '')}`",
        f"- train_seeds_count: `{len(summary.get('train_seeds') or [])}` strictly inside `TRAIN_SEEDS [100000, 200000)`",
        f"- heldout_seeds: `{summary['heldout']['seed_range']}` across `easy,medium,hard` (`n={summary['heldout']['n_per_tier']}/tier`, `{summary['n']}` total/checkpoint)",
        f"- world_secret_tag: `{after['world_secret_tag']}`",
        f"- dev_hard_seeds: `{dev_range_lbl}` (`n={summary['dev_hard']['n_total']}`, development split `DEV_SEEDS`, keyless `public`)",
        f"- headline_before_mean_score: `{before['mean_score']:+.4f}` (`95% CI [{before['ci95_low']:+.4f}, {before['ci95_high']:+.4f}]`)",
        f"- headline_after_mean_score: `{after['mean_score']:+.4f}` (`95% CI [{after['ci95_low']:+.4f}, {after['ci95_high']:+.4f}]`)",
        f"- headline_paired_delta: `{paired['mean_delta']:+.4f}` (`95% CI [{paired['ci95_low']:+.4f}, {paired['ci95_high']:+.4f}]`, `replay_verified={summary['replay_verified']}`, `invalid_episodes={summary['invalid_episodes']}`)",
        "",
        f"{h2} Held-Out Benchmark (`{summary['heldout']['seed_range']}`, Paired Exact Worlds)",
        "",
        "| tier | agent | n | score [95% boot CI] | luck-adj EV [95% CI] | acc | wrong-acc | abstain | valid-tool | replay |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]

    ho_agents = summary["heldout"]["agents_order"]
    for tier in ("easy", "medium", "hard", "all"):
        for ag in ho_agents:
            st = summary["heldout"]["by_agent"][ag]["by_tier"].get(tier)
            if not st or st.get("n", 0) == 0:
                continue
            sc = st["score"]
            ev = st["luck_adjusted_ev"]
            lines.append(
                f"| {tier} | {ag} | {st['n']} | "
                f"{sc['mean']:+.3f} [{sc['ci95_lo']:+.3f}, {sc['ci95_hi']:+.3f}] | "
                f"{ev['mean']:+.3f} [{ev['ci95_lo']:+.3f}, {ev['ci95_hi']:+.3f}] | "
                f"{st['accuracy']['mean']:.3f} | {st['wrong_accuse_rate']:.3f} | "
                f"{st['abstain_rate']:.3f} | {st['valid_tool_rate']:.3f} | {st['replay_verified']} |"
            )

    lines.extend([
        "",
        f"{h2} Held-Out Paired Deltas (`after - before`, Exact Same Worlds)",
        "",
        "| tier | comparison | n | delta score [95% boot CI] | delta luck-adj EV [95% CI] | delta acc | delta wrong-acc | W/T/L |",
        "|---|---|---:|---|---|---:|---:|---:|",
    ])
    for tier in ("easy", "medium", "hard", "all"):
        for comp_name, comp_by_tier in summary["heldout"]["paired_deltas"].items():
            d = comp_by_tier.get(tier)
            if not d or d.get("n_paired", 0) == 0:
                continue
            sd = d["score_diff"]
            ed = d["luck_adjusted_ev_diff"]
            lines.append(
                f"| {tier} | {comp_name} | {d['n_paired']} | "
                f"{sd['mean']:+.3f} [{sd['ci95_lo']:+.3f}, {sd['ci95_hi']:+.3f}] | "
                f"{ed['mean']:+.3f} [{ed['ci95_lo']:+.3f}, {ed['ci95_hi']:+.3f}] | "
                f"{d['accuracy_diff']['mean']:+.3f} | {d['wrong_accuse_rate_diff']:+.3f} | "
                f"{d['wins']}/{d['ties']}/{d['losses']} |"
            )

    lines.extend([
        "",
        f"{h2} Development Hard Benchmark (`{summary['dev_hard']['seed_range']}`, `DEV_SEEDS` Paired vs Solver & Committed `gemini-4-carbon`)",
        "",
        "| agent | n | score [95% boot CI] | luck-adj EV [95% CI] | acc | wrong-acc | abstain | valid-tool | replay |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ])
    for ag in summary["dev_hard"]["agents_order"]:
        st = summary["dev_hard"]["by_agent"][ag]
        if not st or st.get("n", 0) == 0:
            continue
        sc = st["score"]
        ev = st["luck_adjusted_ev"]
        lines.append(
            f"| {ag} | {st['n']} | "
            f"{sc['mean']:+.3f} [{sc['ci95_lo']:+.3f}, {sc['ci95_hi']:+.3f}] | "
            f"{ev['mean']:+.3f} [{ev['ci95_lo']:+.3f}, {ev['ci95_hi']:+.3f}] | "
            f"{st['accuracy']['mean']:.3f} | {st['wrong_accuse_rate']:.3f} | "
            f"{st['abstain_rate']:.3f} | {st['valid_tool_rate']:.3f} | {st['replay_verified']} |"
        )

    lines.extend([
        "",
        f"{h2} Development Hard Paired Deltas (`{summary['dev_hard']['seed_range']}`, `DEV_SEEDS`)",
        "",
        "| comparison | n | delta score [95% boot CI] | delta luck-adj EV [95% CI] | delta acc | delta wrong-acc | W/T/L |",
        "|---|---:|---|---|---:|---:|---:|",
    ])
    for comp_name, d in summary["dev_hard"]["paired_deltas"].items():
        if not d or d.get("n_paired", 0) == 0:
            continue
        sd = d["score_diff"]
        ed = d["luck_adjusted_ev_diff"]
        lines.append(
            f"| {comp_name} | {d['n_paired']} | "
            f"{sd['mean']:+.3f} [{sd['ci95_lo']:+.3f}, {sd['ci95_hi']:+.3f}] | "
            f"{ed['mean']:+.3f} [{ed['ci95_lo']:+.3f}, {ed['ci95_hi']:+.3f}] | "
            f"{d['accuracy_diff']['mean']:+.3f} | {d['wrong_accuse_rate_diff']:+.3f} | "
            f"{d['wins']}/{d['ties']}/{d['losses']} |"
        )

    return "\n".join(lines) + "\n"


def _collect_provenance_train_seeds(out_path: Path) -> tuple[list[int], dict[str, Any]]:
    seeds_used: set[int] = set()
    stage_meta: dict[str, Any] = {}
    mf_path = out_path / "export_manifest.json"
    if mf_path.is_file():
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
        stage_meta["export"] = {
            "seconds": mf.get("seconds"),
            "train_sft_turns": ((mf.get("splits") or {}).get("train") or {}).get("sft_turns"),
            "train_dpo_pairs": ((mf.get("splits") or {}).get("train") or {}).get("dpo_pairs"),
        }
        for k_s in ("train_seeds", "val_seeds"):
            for s in mf.get(k_s) or []:
                seeds_used.add(assert_train_seed(int(s)))

    for jf_name in ("compact_sft_train.jsonl", "compact_sft_val.jsonl", "compact_dagger_r1_train.jsonl"):
        jf_path = out_path / jf_name
        if jf_path.is_file():
            for row in _load_jsonl(jf_path):
                seeds_used.add(assert_train_seed(int(row["seed"])))

    for st_key, fn_name in (("sft", "sft_summary.json"), ("dpo", "dpo_summary.json"), ("dagger_r1", "dagger_summary.json")):
        sp = out_path / fn_name
        if sp.is_file():
            sd = json.loads(sp.read_text(encoding="utf-8"))
            if st_key == "dagger_r1":
                for s in sd.get("dagger_seeds") or []:
                    seeds_used.add(assert_train_seed(int(s)))
            sd_clean = {k: v for k, v in sd.items() if k not in ("adapter_dir", "dagger_seeds")}
            stage_meta[st_key] = sd_clean

    if not seeds_used:
        seeds_used.add(assert_train_seed(100_000))
    return sorted(seeds_used), stage_meta


def build_eval_summary_and_table(
    heldout_eps_by_agent: dict[str, list[dict[str, Any]]],
    dev_hard_eps_by_agent: dict[str, list[dict[str, Any]]],
    heldout_seeds: list[int],
    dev_seeds: list[int],
    heldout_secret: str,
    model_path: str,
    git_sha: str,
    elapsed_s: float,
    tiers: tuple[str, ...] = TIERS,
    train_seeds: list[int] | None = None,
    stage_meta: dict[str, Any] | None = None,
    run_id: str = RUN_ID_DEFAULT,
    model_label: str = MODEL_LABEL_DEFAULT,
) -> tuple[dict[str, Any], str]:
    ho_order = [
        ag
        for ag in (
            "qwen05b_base",
            "qwen05b_compact_sft",
            "qwen05b_compact_sft_dpo",
            "qwen05b_compact_dagger_r1",
            "solver",
        )
        if ag in heldout_eps_by_agent
    ]
    ho_by_agent: dict[str, Any] = {}
    for idx, ag in enumerate(ho_order):
        eps = heldout_eps_by_agent[ag]
        by_tier: dict[str, Any] = {}
        for t_i, tier in enumerate(tiers):
            sub = [e for e in eps if e["tier"] == tier]
            by_tier[tier] = summarize_episode_group(sub, rng_seed=100 * idx + 10 * t_i)
        by_tier["all"] = summarize_episode_group(eps, rng_seed=100 * idx + 99)
        ho_by_agent[ag] = {"by_tier": by_tier}

    after_agent = (
        "qwen05b_compact_dagger_r1"
        if "qwen05b_compact_dagger_r1" in heldout_eps_by_agent
        else (
            "qwen05b_compact_sft_dpo"
            if "qwen05b_compact_sft_dpo" in heldout_eps_by_agent
            else ho_order[-1]
        )
    )
    before_agent = "qwen05b_base" if "qwen05b_base" in heldout_eps_by_agent else ho_order[0]

    ho_pairs_spec = [
        ("qwen05b_compact_sft - qwen05b_base", "qwen05b_compact_sft", "qwen05b_base"),
        ("qwen05b_compact_sft_dpo - qwen05b_base", "qwen05b_compact_sft_dpo", "qwen05b_base"),
        ("qwen05b_compact_dagger_r1 - qwen05b_base", "qwen05b_compact_dagger_r1", "qwen05b_base"),
        ("qwen05b_compact_dagger_r1 - qwen05b_compact_sft_dpo", "qwen05b_compact_dagger_r1", "qwen05b_compact_sft_dpo"),
        ("qwen05b_compact_dagger_r1 - solver", "qwen05b_compact_dagger_r1", "solver"),
    ]
    ho_deltas: dict[str, dict[str, Any]] = {}
    for p_idx, (label, after_ag, before_ag) in enumerate(ho_pairs_spec):
        if after_ag not in heldout_eps_by_agent or before_ag not in heldout_eps_by_agent:
            continue
        per_t: dict[str, Any] = {}
        for t_i, tier in enumerate(tiers):
            a_sub = [e for e in heldout_eps_by_agent[after_ag] if e["tier"] == tier]
            b_sub = [e for e in heldout_eps_by_agent[before_ag] if e["tier"] == tier]
            per_t[tier] = paired_delta_summary(a_sub, b_sub, rng_seed=500 + 30 * p_idx + t_i)
        per_t["all"] = paired_delta_summary(
            heldout_eps_by_agent[after_ag],
            heldout_eps_by_agent[before_ag],
            rng_seed=500 + 30 * p_idx + 9,
        )
        ho_deltas[label] = per_t

    dev_order = [
        ag
        for ag in (
            "qwen05b_base",
            "qwen05b_compact_sft",
            "qwen05b_compact_sft_dpo",
            "qwen05b_compact_dagger_r1",
            "gemini_4_carbon",
            "solver",
        )
        if ag in dev_hard_eps_by_agent and dev_hard_eps_by_agent[ag]
    ]
    dev_by_agent = {
        ag: summarize_episode_group(dev_hard_eps_by_agent[ag], rng_seed=900 + 17 * i)
        for i, ag in enumerate(dev_order)
    }
    dev_pairs_spec = [
        ("qwen05b_compact_sft - qwen05b_base", "qwen05b_compact_sft", "qwen05b_base"),
        ("qwen05b_compact_sft_dpo - qwen05b_base", "qwen05b_compact_sft_dpo", "qwen05b_base"),
        ("qwen05b_compact_dagger_r1 - qwen05b_base", "qwen05b_compact_dagger_r1", "qwen05b_base"),
        ("qwen05b_compact_dagger_r1 - gemini_4_carbon", "qwen05b_compact_dagger_r1", "gemini_4_carbon"),
        ("qwen05b_compact_dagger_r1 - solver", "qwen05b_compact_dagger_r1", "solver"),
    ]
    dev_deltas: dict[str, Any] = {}
    for p_idx, (label, after_ag, before_ag) in enumerate(dev_pairs_spec):
        if after_ag in dev_hard_eps_by_agent and before_ag in dev_hard_eps_by_agent:
            if dev_hard_eps_by_agent[after_ag] and dev_hard_eps_by_agent[before_ag]:
                dev_deltas[label] = paired_delta_summary(
                    dev_hard_eps_by_agent[after_ag],
                    dev_hard_eps_by_agent[before_ag],
                    rng_seed=1200 + 19 * p_idx,
                )

    secret_hex = hashlib.sha256(heldout_secret.encode("utf-8")).hexdigest()
    secret_fp12 = secret_hex[:12]
    world_secret_tag = f"sha256:{secret_hex[:16]}"

    before_map = {(str(e["tier"]), int(e["seed"])): e for e in heldout_eps_by_agent[before_agent]}
    after_map = {(str(e["tier"]), int(e["seed"])): e for e in heldout_eps_by_agent[after_agent]}
    ordered_keys = [(tier, int(s)) for s in heldout_seeds for tier in tiers if (tier, int(s)) in before_map and (tier, int(s)) in after_map]

    before_eps_ord = [before_map[k] for k in ordered_keys]
    after_eps_ord = [after_map[k] for k in ordered_keys]
    b_scores = [round(float(e["score"]), 6) for e in before_eps_ord]
    a_scores = [round(float(e["score"]), 6) for e in after_eps_ord]
    deltas = [round(a - b, 6) for b, a in zip(b_scores, a_scores)]

    b_ci = normal_mean_ci95(b_scores)
    a_ci = normal_mean_ci95(a_scores)
    p_ci = normal_mean_ci95(deltas)

    b_grp = ho_by_agent[before_agent]["by_tier"]["all"]
    a_grp = ho_by_agent[after_agent]["by_tier"]["all"]

    b_inv = sum(
        1 for e in before_eps_ord
        if e.get("end_reason") in ("error", "invalid") or (e.get("meta") or {}).get("valid") is False
    )
    a_inv = sum(
        1 for e in after_eps_ord
        if e.get("end_reason") in ("error", "invalid") or (e.get("meta") or {}).get("valid") is False
    )
    b_rv_ok = all((e.get("meta") or {}).get("replay_verified") is True for e in before_eps_ord)
    a_rv_ok = all((e.get("meta") or {}).get("replay_verified") is True for e in after_eps_ord)

    clean_train_seeds = validate_train_seeds(train_seeds if train_seeds else [100_000])
    tr_sub = [s for s in clean_train_seeds if SPLIT_RANGES["train"][0] <= s < SPLIT_RANGES["train"][1]]
    va_sub = [s for s in clean_train_seeds if SPLIT_RANGES["val"][0] <= s < SPLIT_RANGES["val"][1]]
    assert_all_splits_disjoint(tr_sub, va_sub, heldout_seeds, dev_seeds)
    dev_seed_spec: str | list[int] = f"{dev_seeds[0]}..{dev_seeds[-1]}" if dev_seeds else []

    summary = {
        "run_id": run_id,
        "model": model_label,
        "tiers_version": "v1.4",
        "tiers": list(tiers),
        "n": len(ordered_keys),
        "git_sha": git_sha,
        "model_path": model_path,
        "world_secret_tag": world_secret_tag,
        "inference_modules": [
            "train/compact_render.py",
            "train/eval_compact_hf.py",
            "train/compact_lora_sft.py",
        ],
        "train_seeds": clean_train_seeds,
        "eval_seeds": {
            "start": int(heldout_seeds[0]),
            "stop": int(heldout_seeds[-1]) + 1,
        },
        "dev_eval_seed_range": dev_seed_spec,
        "replay_verified": bool(b_rv_ok and a_rv_ok),
        "invalid_episodes": int(b_inv + a_inv),
        "eval_seconds": round(elapsed_s, 2),
        "before": {
            "agent": before_agent,
            "n": len(b_scores),
            "mean_score": b_ci["mean"],
            "ci95_low": b_ci["ci95_low"],
            "ci95_high": b_ci["ci95_high"],
            "scores": b_scores,
            "luck_adjusted_ev": b_grp["luck_adjusted_ev"]["mean"],
            "accuracy": b_grp["accuracy"]["mean"],
            "wrong_accuse_rate": b_grp["wrong_accuse_rate"],
            "abstain_rate": b_grp["abstain_rate"],
            "valid_call_rate": b_grp["valid_tool_rate"],
            "valid_parse_rate": b_grp["valid_parse_rate"],
            "world_secret_tag": world_secret_tag,
            "replay_verified": bool(b_rv_ok),
            "invalid_episodes": int(b_inv),
            "end_reasons": b_grp["end_reasons"],
        },
        "after": {
            "agent": after_agent,
            "n": len(a_scores),
            "mean_score": a_ci["mean"],
            "ci95_low": a_ci["ci95_low"],
            "ci95_high": a_ci["ci95_high"],
            "scores": a_scores,
            "luck_adjusted_ev": a_grp["luck_adjusted_ev"]["mean"],
            "accuracy": a_grp["accuracy"]["mean"],
            "wrong_accuse_rate": a_grp["wrong_accuse_rate"],
            "abstain_rate": a_grp["abstain_rate"],
            "valid_call_rate": a_grp["valid_tool_rate"],
            "valid_parse_rate": a_grp["valid_parse_rate"],
            "world_secret_tag": world_secret_tag,
            "replay_verified": bool(a_rv_ok),
            "invalid_episodes": int(a_inv),
            "end_reasons": a_grp["end_reasons"],
        },
        "paired": {
            "mean_delta": p_ci["mean"],
            "ci95_low": p_ci["ci95_low"],
            "ci95_high": p_ci["ci95_high"],
            "deltas": deltas,
        },
        "stages": stage_meta or {},
        "heldout": {
            "n_per_tier": len(heldout_seeds),
            "n_total": len(heldout_seeds) * len(tiers),
            "seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
            "tiers": list(tiers),
            "world_secret_sha256_12": secret_fp12,
            "world_secret_tag": world_secret_tag,
            "agents_order": ho_order,
            "by_agent": ho_by_agent,
            "paired_deltas": ho_deltas,
        },
        "dev_hard": {
            "n_total": len(dev_seeds),
            "seed_range": dev_seed_spec,
            "tier": "hard",
            "world_key": "public",
            "agents_order": dev_order,
            "by_agent": dev_by_agent,
            "paired_deltas": dev_deltas,
        },
        "notes": (
            "Paired exact-world evaluation of Qwen2.5-0.5B-Instruct before vs after calibrated compact-memory "
            "LoRA SFT + EV-margin DPO + On-Policy DAgger r1 on Canary v1.4 held-out seeds 800000..800029."
        ),
    }
    md = format_eval_table_md(summary)
    return summary, md


def eval_stage(
    model_path: str,
    out_dir: str | Path,
    tiers: tuple[str, ...] = TIERS,
    heldout_n: int = 30,
    dev_n: int = 30,
    heldout_secret: str = HELDOUT_SECRET_DEFAULT,
    tail_turns: int = 4,
    max_ctx: int = 2560,
    max_new: int = 300,
    eval_batch_size: int = 90,
    out_summary: str | Path | None = None,
    out_table: str | Path | None = None,
    tiny: bool = False,
    tiny_torch: bool = False,
) -> dict[str, Any]:
    from canary.solver import SolverPolicy

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    heldout_seeds = [assert_eval_seed(800_000 + i, "heldout") for i in range(heldout_n)]
    dev_seeds = [assert_eval_seed(i, "dev") for i in range(dev_n)]

    t0 = time.time()
    try:
        git_sha = subprocess.run(
            ["git", "-C", str(repo_root()), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        git_sha = ""

    heldout_eps: dict[str, list[dict[str, Any]]] = {}
    dev_hard_eps: dict[str, list[dict[str, Any]]] = {}

    solver_ho_path = out_path / "episodes_solver.jsonl"
    heldout_eps["solver"] = _run_policy_episodes(
        agent_tag="solver",
        policy_factory=SolverPolicy,
        tiers=tiers,
        seeds=heldout_seeds,
        world_secret=heldout_secret,
        out_jsonl=solver_ho_path,
    )
    verify_compact_episode_file(solver_ho_path, world_secret=heldout_secret)
    if dev_seeds:
        solver_dev_path = out_path / "episodes_dev_hard_solver.jsonl"
        dev_hard_eps["solver"] = _run_policy_episodes(
            agent_tag="solver",
            policy_factory=SolverPolicy,
            tiers=("hard",),
            seeds=dev_seeds,
            world_secret=None,
            out_jsonl=solver_dev_path,
        )
        verify_compact_episode_file(solver_dev_path, world_secret=None)
        gem_dev_path = out_path / "episodes_dev_hard_gemini_4_carbon.jsonl"
        gem_eps = _load_committed_gemini_dev_hard(
            dev_seeds=dev_seeds,
            out_jsonl=gem_dev_path,
        )
        if gem_eps:
            verify_compact_episode_file(gem_dev_path, world_secret=None)
            dev_hard_eps["gemini_4_carbon"] = gem_eps

    checkpoints: list[tuple[str, Path | None]] = [
        ("qwen05b_base", None),
    ]
    for tag, subdir in (
        ("qwen05b_compact_sft", "lora_sft"),
        ("qwen05b_compact_sft_dpo", "lora_sft_dpo"),
        ("qwen05b_compact_dagger_r1", "lora_dagger_r1"),
    ):
        cand_dir = out_path / subdir
        if cand_dir.is_dir():
            checkpoints.append((tag, cand_dir))

    if len(checkpoints) < 2:
        raise RuntimeError(f"expected at least one trained adapter directory under {out_path}")

    dev_eval_tags = {checkpoints[0][0], checkpoints[-1][0]}

    if _use_tiny_cpu_stub(tiny, model_path, tiny_torch=tiny_torch):
        for tag, _adapter_dir in checkpoints:
            def _make_stub_pol(ag_name: str = tag) -> CompactLoRAPolicy:
                cnt = {"k": 0}
                def _gen(_turn: dict[str, Any]) -> str:
                    cnt["k"] += 1
                    if ag_name == "qwen05b_base" and cnt["k"] == 1:
                        return "unparseable response"
                    if cnt["k"] == 1:
                        return '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>'
                    return '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>'
                return CompactLoRAPolicy(name=ag_name, generator=_gen, tail_turns=tail_turns)

            ho_ep_path = out_path / f"episodes_{tag}.jsonl"
            heldout_eps[tag] = _run_policy_episodes(
                agent_tag=tag,
                policy_factory=_make_stub_pol,
                tiers=tiers,
                seeds=heldout_seeds,
                world_secret=heldout_secret,
                out_jsonl=ho_ep_path,
                reuse_existing=False,
            )
            verify_compact_episode_file(ho_ep_path, world_secret=heldout_secret)
            if dev_seeds and tag in dev_eval_tags:
                dev_ep_path = out_path / f"episodes_dev_hard_{tag}.jsonl"
                dev_hard_eps[tag] = _run_policy_episodes(
                    agent_tag=tag,
                    policy_factory=_make_stub_pol,
                    tiers=("hard",),
                    seeds=dev_seeds,
                    world_secret=None,
                    out_jsonl=dev_ep_path,
                    reuse_existing=False,
                )
                verify_compact_episode_file(dev_ep_path, world_secret=None)
    else:
        import torch

        for tag, adapter_dir in checkpoints:
            model, tok, device = _load_eval_checkpoint(model_path, adapter_dir, tiny=tiny)
            ckpt_memo: dict[tuple[int, ...], str] = {}
            ho_ep_path = out_path / f"episodes_{tag}.jsonl"
            heldout_eps[tag] = _run_batched_compact_episodes(
                agent_tag=tag,
                model=model,
                tok=tok,
                tiers=tiers,
                seeds=heldout_seeds,
                world_secret=heldout_secret,
                out_jsonl=ho_ep_path,
                tail_turns=tail_turns,
                max_ctx=max_ctx,
                max_new=max_new,
                batch_size=eval_batch_size,
                memo=ckpt_memo,
            )
            verify_compact_episode_file(ho_ep_path, world_secret=heldout_secret)
            if dev_seeds and tag in dev_eval_tags:
                dev_ep_path = out_path / f"episodes_dev_hard_{tag}.jsonl"
                dev_hard_eps[tag] = _run_batched_compact_episodes(
                    agent_tag=tag,
                    model=model,
                    tok=tok,
                    tiers=("hard",),
                    seeds=dev_seeds,
                    world_secret=None,
                    out_jsonl=dev_ep_path,
                    tail_turns=tail_turns,
                    max_ctx=max_ctx,
                    max_new=max_new,
                    batch_size=eval_batch_size,
                    memo=ckpt_memo,
                )
                verify_compact_episode_file(dev_ep_path, world_secret=None)
            del model
            if device == "cuda":
                torch.cuda.empty_cache()

    train_seeds, stage_meta = _collect_provenance_train_seeds(out_path)
    summary, md = build_eval_summary_and_table(
        heldout_eps_by_agent=heldout_eps,
        dev_hard_eps_by_agent=dev_hard_eps,
        heldout_seeds=heldout_seeds,
        dev_seeds=dev_seeds,
        heldout_secret=heldout_secret,
        model_path=model_path,
        git_sha=git_sha,
        elapsed_s=time.time() - t0,
        tiers=tiers,
        train_seeds=train_seeds,
        stage_meta=stage_meta,
    )
    sum_dest = out_path / "summary.json"
    tbl_dest = out_path / "table.md"
    sum_dest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    tbl_dest.write_text(md, encoding="utf-8")
    if out_summary is not None and Path(out_summary).resolve() != sum_dest.resolve():
        Path(out_summary).parent.mkdir(parents=True, exist_ok=True)
        Path(out_summary).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if out_table is not None and Path(out_table).resolve() != tbl_dest.resolve():
        Path(out_table).parent.mkdir(parents=True, exist_ok=True)
        Path(out_table).write_text(md, encoding="utf-8")
    print(md, flush=True)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--force-export", action="store_true")
    ap.add_argument("--train-sft", action="store_true")
    ap.add_argument("--train-dpo", action="store_true")
    ap.add_argument("--train-dagger", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--out-summary", default=None)
    ap.add_argument("--out-table", default=None)
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--n-train", type=int, default=60)
    ap.add_argument("--n-augment", type=int, default=18)
    ap.add_argument("--n-val", type=int, default=10)
    ap.add_argument("--n-val-augment", type=int, default=4)
    ap.add_argument("--tail-turns", type=int, default=4)
    ap.add_argument("--max-len", type=int, default=2560)
    ap.add_argument("--max-new", type=int, default=300)
    ap.add_argument("--sft-epochs", type=float, default=1.0)
    ap.add_argument("--sft-max-steps", type=int, default=300)
    ap.add_argument("--sft-lr", type=float, default=2e-4)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--dpo-epochs", type=float, default=1.0)
    ap.add_argument("--dpo-max-steps", type=int, default=75)
    ap.add_argument("--dpo-beta", type=float, default=0.15)
    ap.add_argument("--dpo-lr", type=float, default=8e-6)
    ap.add_argument("--dpo-batch-size", type=int, default=4)
    ap.add_argument("--dpo-grad-accum", type=int, default=2)
    ap.add_argument("--dagger-seed-start", type=int, default=DAGGER_SEED_START_DEFAULT)
    ap.add_argument("--dagger-per-tier", type=int, default=24)
    ap.add_argument("--dagger-steps", type=int, default=110)
    ap.add_argument("--dagger-lr", type=float, default=2.5e-5)
    ap.add_argument("--dagger-max-rollout-steps", type=int, default=72)
    ap.add_argument("--eval-batch-size", type=int, default=90)
    ap.add_argument("--heldout-n", type=int, default=30)
    ap.add_argument("--dev-n", type=int, default=30)
    ap.add_argument("--heldout-secret", default=HELDOUT_SECRET_DEFAULT)
    ap.add_argument("--tiny", action="store_true")
    ap.add_argument("--tiny-torch", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> dict[str, Any]:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(raw_argv)
    if args.workers != 1:
        raise ValueError("workers must be 1")
    tiers = tuple(t.strip() for t in str(args.tiers).split(",") if t.strip())
    if not tiers or any(t not in TIERS for t in tiers):
        raise ValueError(f"invalid tiers {args.tiers!r}")

    if args.tiny:
        if "--tiers" not in raw_argv:
            tiers = ("easy",)
        if "--n-train" not in raw_argv:
            args.n_train = 1
        if "--n-augment" not in raw_argv:
            args.n_augment = 1
        if "--n-val" not in raw_argv:
            args.n_val = 1
        if "--n-val-augment" not in raw_argv:
            args.n_val_augment = 0
        if "--sft-max-steps" not in raw_argv:
            args.sft_max_steps = 2
        if "--batch-size" not in raw_argv:
            args.batch_size = 2
        if "--grad-accum" not in raw_argv:
            args.grad_accum = 1
        if "--dpo-max-steps" not in raw_argv:
            args.dpo_max_steps = 2
        if "--dpo-batch-size" not in raw_argv:
            args.dpo_batch_size = 2
        if "--dpo-grad-accum" not in raw_argv:
            args.dpo_grad_accum = 1
        if "--dagger-per-tier" not in raw_argv:
            args.dagger_per_tier = 1
        if "--dagger-steps" not in raw_argv:
            args.dagger_steps = 2
        if "--dagger-max-rollout-steps" not in raw_argv:
            args.dagger_max_rollout_steps = 4
        if "--max-new" not in raw_argv:
            args.max_new = 16
        if "--eval-batch-size" not in raw_argv:
            args.eval_batch_size = 4
        if "--heldout-n" not in raw_argv:
            args.heldout_n = 2
        if "--dev-n" not in raw_argv:
            args.dev_n = 0

    run_export = bool(args.export or args.all)
    run_sft = bool(args.train_sft or args.all)
    run_dpo = bool(args.train_dpo or args.all)
    run_dagger = bool(args.train_dagger or args.all)
    run_ev = bool(args.eval or args.all)
    if not (run_export or run_sft or run_dpo or run_dagger or run_ev):
        raise ValueError("specify at least one stage: --export, --train-sft, --train-dpo, --train-dagger, --eval, or --all")

    results: dict[str, Any] = {}
    if run_export:
        results["export"] = export_compact_datasets(
            out_dir=args.out_dir,
            tiers=tiers,
            n_train=args.n_train,
            n_augment=args.n_augment,
            n_val=args.n_val,
            n_val_augment=args.n_val_augment,
            tail_turns=args.tail_turns,
            workers=args.workers,
            reuse_existing=not bool(args.force_export or args.tiny),
        )
    if run_sft:
        results["sft"] = train_sft_stage(
            model_path=args.model,
            out_dir=args.out_dir,
            max_len=args.max_len,
            epochs=args.sft_epochs,
            max_steps=args.sft_max_steps,
            lr=args.sft_lr,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            r=args.r,
            lora_alpha=args.lora_alpha,
            tiny=args.tiny,
            tiny_torch=args.tiny_torch,
        )
    if run_dpo:
        results["dpo"] = train_dpo_stage(
            model_path=args.model,
            out_dir=args.out_dir,
            max_len=args.max_len,
            epochs=args.dpo_epochs,
            max_steps=args.dpo_max_steps,
            beta=args.dpo_beta,
            lr=args.dpo_lr,
            batch_size=args.dpo_batch_size,
            grad_accum=args.dpo_grad_accum,
            tiny=args.tiny,
            tiny_torch=args.tiny_torch,
        )
    if run_dagger:
        results["dagger_r1"] = train_dagger_stage(
            model_path=args.model,
            out_dir=args.out_dir,
            tiers=tiers,
            dagger_seed_start=args.dagger_seed_start,
            dagger_per_tier=args.dagger_per_tier,
            tail_turns=args.tail_turns,
            max_len=args.max_len,
            max_new=args.max_new,
            steps=args.dagger_steps,
            lr=args.dagger_lr,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            rollout_batch_size=args.eval_batch_size,
            max_rollout_steps=args.dagger_max_rollout_steps,
            tiny=args.tiny,
            tiny_torch=args.tiny_torch,
        )
    if run_ev:
        results["eval"] = eval_stage(
            model_path=args.model,
            out_dir=args.out_dir,
            tiers=tiers,
            heldout_n=args.heldout_n,
            dev_n=args.dev_n,
            heldout_secret=args.heldout_secret,
            tail_turns=args.tail_turns,
            max_ctx=args.max_len,
            max_new=args.max_new,
            eval_batch_size=args.eval_batch_size,
            out_summary=args.out_summary,
            out_table=args.out_table,
            tiny=args.tiny,
            tiny_torch=args.tiny_torch,
        )
    return results


if __name__ == "__main__":
    main()
