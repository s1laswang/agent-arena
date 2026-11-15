from __future__ import annotations

import base64
from functools import lru_cache
import io
import json
import math
import os
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env
from canary.eval import episode_from_dict, summarize
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, tier_params

ROOT = Path(__file__).resolve().parents[1]
SELF_TEST_PATH = Path(__file__).resolve()

HARD_TARGET_SEEDS = (6, 26, 4, 18, 15, 11, 5, 23)
MEDIUM_TARGET_SEEDS = (0, 12)
SEALED_TOKEN = "[SEALED]"

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)

FORBIDDEN_PRE_END_KEYS = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "decoy",
        "true_decoy",
        "decoy_id",
        "correct",
        "accused_correct",
        "score",
        "true_V",
        "true_v",
        "V_final",
        "ledger",
        "ledger_events",
        "sealed_reveal_b64",
        "solver_sealed_reveal_b64",
        "world_seed",
        "_world",
    }
)

EMP_ID_RE = re.compile(r"^e\d{2,3}$")


def _replay_js_path() -> Path:
    override = os.environ.get("CANARY_ARENA_REPLAY_JS")
    if override:
        return Path(override).resolve()
    return ROOT / "docs" / "arena" / "replay_engine.js"


def _duel_pack_js_path() -> Path:
    override = os.environ.get("CANARY_ARENA_DUEL_PACK_JS")
    if override:
        return Path(override).resolve()
    return ROOT / "docs" / "arena" / "data" / "committed_duel_pack.js"


def _find_node_bin() -> str | None:
    override = os.environ.get("CANARY_NODE_BIN")
    if override and Path(override).is_file():
        return override
    found = shutil.which("node")
    if found:
        return found
    home_node = Path.home() / "tools" / "node" / "bin" / "node"
    if home_node.is_file():
        return str(home_node)
    return None


def _committed_paths(tier: str, agent_key: str) -> tuple[Path, ...]:
    base = ROOT / "data" / "runs" / "committed" / "v1.4"
    if agent_key == "gemini":
        return (base / "opencode-gemini-4-carbon" / tier / "episodes.jsonl",)
    if agent_key == "solver":
        if tier == "hard":
            return (
                base / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
                base / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
            )
        if tier == "medium":
            return (
                base / "reference" / "solver-medium-20261114-121126" / "episodes.jsonl",
                base / "reference" / "solver-medium-seeds20to29" / "episodes.jsonl",
            )
    raise ValueError(f"unsupported tier/agent: {tier}/{agent_key}")


@lru_cache(maxsize=8)
def _load_committed_lines_by_seed(tier: str, agent_key: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for p in _committed_paths(tier, agent_key):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            out[int(obj["seed"])] = line
    return out


@lru_cache(maxsize=64)
def _replayed_oracle(tier: str, seed: int, agent_key: str) -> dict[str, Any]:
    raw_line = _load_committed_lines_by_seed(tier, agent_key)[seed]
    raw_ep = json.loads(raw_line)
    ep_res = episode_from_dict(raw_ep)
    env = Env(tier, seed)
    mole_id = env._world.mole
    decoy_id = env._world.decoy
    known_vs: list[float] = []
    true_vs: list[float] = []
    for idx, st in enumerate(raw_ep["steps"]):
        assert int(st["t"]) == idx
        res = env.call(st["tool"], st["args"])
        assert res.ok is bool(st["result"]["ok"]), (tier, seed, agent_key, idx, st["tool"])
        known_vs.append(env.visible_V())
        true_vs.append(round(env.V, 10))
    verdict = env.verdict()
    return {
        "raw_line": raw_line,
        "raw_ep": raw_ep,
        "ep_res": ep_res,
        "tier": tier,
        "seed": seed,
        "agent_key": agent_key,
        "agent": raw_ep["agent"],
        "mole": mole_id,
        "decoy": decoy_id,
        "known_vs": known_vs,
        "true_vs": true_vs,
        "verdict": verdict,
    }


def compute_known_v_from_public_steps(tier: str, steps: list[dict[str, Any]]) -> list[float]:
    p = tier_params(tier)
    cur_v = 1.0
    restricted: set[str] = set()
    out: list[float] = []
    for st in steps:
        tool = st["tool"]
        res = st.get("result") or {}
        ok = bool(res.get("ok"))
        data = res.get("data") or {}
        if ok:
            if tool == "status" and isinstance(data.get("V"), (int, float)):
                cur_v = round(float(data["V"]), 10)
            elif tool == "advance_day":
                if isinstance(data.get("V"), (int, float)):
                    cur_v = round(float(data["V"]), 10)
                elif data.get("episode_over") and restricted:
                    cur_v = round(max(0.0, cur_v - p.restrict_cost_per_day * len(restricted)), 10)
            elif tool == "plant_canary":
                cur_v = round(max(0.0, cur_v - p.canary_cost), 10)
            elif tool == "restrict_access" and isinstance(data.get("restricted"), str):
                restricted.add(data["restricted"])
            elif tool == "unrestrict_access" and isinstance(data.get("unrestricted"), str):
                restricted.discard(data["unrestricted"])
        out.append(cur_v)
    return out


def summarize_step_public(tool: str, args: dict[str, Any], ok: bool, mask_accuse: bool) -> str:
    if tool == "accuse":
        if mask_accuse:
            return f"accuse {SEALED_TOKEN}"
        return f"accuse {args.get('employee', '')}".strip()
    if tool in {"interview", "restrict_access", "unrestrict_access"}:
        return f"{tool} {args.get('employee', '')}".strip()
    if tool == "plant_canary":
        return f"plant_canary ({len(args.get('assignment') or {})} staff)"
    return tool if ok else f"{tool} (rejected)"


def project_episode_reference(
    oracle: dict[str, Any],
    human_day: int,
    human_done: bool = False,
    max_call_idx: int | None = None,
) -> dict[str, Any]:
    raw_ep = oracle["raw_ep"]
    known_vs = oracle["known_vs"]
    raw_steps = raw_ep["steps"]
    final_day = int(raw_ep["final_day"])

    projected_steps: list[dict[str, Any]] = []
    for idx, st in enumerate(raw_steps):
        s_day = int(st["day"])
        if not human_done:
            if s_day > human_day:
                continue
            if max_call_idx is not None and idx > max_call_idx:
                continue
        is_masked_accuse = (not human_done) and st["tool"] == "accuse"
        safe_args = {"employee": SEALED_TOKEN} if is_masked_accuse else dict(st["args"])
        ok = bool(st["result"]["ok"])
        projected_steps.append(
            {
                "day": s_day,
                "call_idx": idx,
                "tool": st["tool"],
                "args": safe_args,
                "ok": ok,
                "summary": summarize_step_public(st["tool"], st["args"], ok, is_masked_accuse),
                "V": known_vs[idx],
            }
        )

    if human_done:
        final_obj: dict[str, Any] | None = {
            "sealed": False,
            "score": float(raw_ep["score"]),
            "correct": bool(raw_ep["correct"]),
            "accused": raw_ep["accused"],
            "mole": oracle["mole"],
            "final_day": final_day,
            "end_reason": raw_ep["end_reason"],
            "tool_calls": len(raw_steps),
        }
    else:
        ai_finished_by_cap = final_day <= human_day and (
            max_call_idx is None or max_call_idx >= len(raw_steps) - 1
        )
        final_obj = {"sealed": True, "final_day": final_day} if ai_finished_by_cap else None

    return {
        "seed": int(raw_ep["seed"]),
        "tier": raw_ep["tier"],
        "agent": raw_ep["agent"],
        "steps": projected_steps,
        "final": final_obj,
    }


def collect_pre_end_leak_violations(
    node: Any,
    oracle: dict[str, Any],
    human_day: int,
    loc: str = "view",
    max_call_idx: int | None = None,
) -> list[str]:
    violations: list[str] = []

    def _walk(cur: Any, path: str) -> None:
        if isinstance(cur, list):
            for i, item in enumerate(cur):
                _walk(item, f"{path}[{i}]")
            return
        if not isinstance(cur, dict):
            return
        for k, v in cur.items():
            ks = str(k)
            cpath = f"{path}.{ks}"
            if ks in FORBIDDEN_PRE_END_KEYS and v is not None:
                violations.append(f"{cpath}: forbidden pre-end key {ks}={v!r}")
            if ks == "accused" and v is not None and v != SEALED_TOKEN:
                violations.append(f"{cpath}: unmasked accused={v!r}")
            _walk(v, cpath)

    _walk(node, loc)
    if not isinstance(node, dict):
        violations.append(f"{loc}: view is not a dict")
        return violations

    steps = node.get("steps")
    if not isinstance(steps, list):
        violations.append(f"{loc}.steps: missing list")
        return violations

    expected_accused = oracle["raw_ep"]["accused"]
    for i, st in enumerate(steps):
        spath = f"{loc}.steps[{i}]"
        if not isinstance(st, dict):
            violations.append(f"{spath}: step is not a dict")
            continue
        s_day = st.get("day")
        if not isinstance(s_day, int) or s_day > human_day:
            violations.append(f"{spath}.day: {s_day!r} exceeds human_day={human_day}")
        if st.get("tool") == "accuse":
            args_obj = st.get("args")
            emp_val = args_obj if args_obj == SEALED_TOKEN else (
                args_obj.get("employee") if isinstance(args_obj, dict) else None
            )
            if emp_val != SEALED_TOKEN:
                violations.append(f"{spath}.args.employee: expected {SEALED_TOKEN!r}, got {emp_val!r}")
            summary_val = str(st.get("summary") or "")
            if SEALED_TOKEN not in summary_val:
                violations.append(f"{spath}.summary: missing {SEALED_TOKEN!r} in {summary_val!r}")
            step_dump = json.dumps(st)
            if isinstance(expected_accused, str) and expected_accused in step_dump:
                violations.append(f"{spath}: raw accused id {expected_accused!r} leaked in accuse step")
            if oracle["mole"] in step_dump:
                violations.append(f"{spath}: true mole id {oracle['mole']!r} leaked in accuse step")
            for tok in re.findall(r"\be\d{2,3}\b", step_dump):
                if EMP_ID_RE.match(tok):
                    violations.append(f"{spath}: employee id {tok!r} leaked in masked accuse step")

    final_val = node.get("final")
    final_day = int(oracle["raw_ep"]["final_day"])
    total_steps = len(oracle["raw_ep"]["steps"])
    has_accuse = oracle["raw_ep"]["end_reason"] == "accused"
    ai_reached_end = human_day >= final_day and (max_call_idx is None or max_call_idx >= total_steps - 1)
    if not ai_reached_end:
        if final_val is not None:
            if not (isinstance(final_val, dict) and final_val.get("done") is False and final_val.get("sealed") is False):
                violations.append(f"{loc}.final: expected None before AI end, got {final_val!r}")
    else:
        if isinstance(final_val, dict):
            if final_val.get("sealed") is not True:
                violations.append(f"{loc}.final.sealed: expected True while !humanDone, got {final_val!r}")
            if int(final_val.get("final_day", -1)) != final_day:
                violations.append(f"{loc}.final.final_day: expected {final_day}, got {final_val!r}")
            extra = set(final_val.keys()) - {"sealed", "final_day", "done", "status", "end_reason"}
            if extra:
                violations.append(f"{loc}.final: unexpected keys {sorted(extra)} while !humanDone")
        elif final_val is None:
            if has_accuse and node.get("status") != "sealed_accusation":
                violations.append(
                    f"{loc}: expected final={{sealed:True,final_day:{final_day}}} or status='sealed_accusation'"
                )
        else:
            violations.append(f"{loc}.final: invalid pre-end value {final_val!r}")

    return violations


def _build_fixture_duel_pack(seeds_by_tier: dict[str, tuple[int, ...]]) -> dict[str, Any]:
    episodes: dict[str, Any] = {}
    by_agent: dict[str, Any] = {}
    for tier, seeds in seeds_by_tier.items():
        p = tier_params(tier)
        for seed in seeds:
            gem_oracle = _replayed_oracle(tier, seed, "gemini")
            sol_oracle = _replayed_oracle(tier, seed, "solver")
            pair_entries: dict[str, dict[str, Any]] = {}
            for akey, orc in (("gemini", gem_oracle), ("solver", sol_oracle)):
                raw_ep = orc["raw_ep"]
                pre_steps: list[dict[str, Any]] = []
                accuse_idx: int | None = None
                accuse_args: dict[str, Any] | None = None
                accuse_summary: str | None = None
                for idx, st in enumerate(raw_ep["steps"]):
                    ok = bool(st["result"]["ok"])
                    is_acc = st["tool"] == "accuse"
                    if is_acc:
                        accuse_idx = idx
                        accuse_args = dict(st["args"])
                        accuse_summary = summarize_step_public(st["tool"], st["args"], ok, False)
                    pre_steps.append(
                        {
                            "day": int(st["day"]),
                            "call_idx": idx,
                            "t": idx,
                            "tool": st["tool"],
                            "args": {"employee": SEALED_TOKEN} if is_acc else dict(st["args"]),
                            "ok": ok,
                            "summary": SEALED_TOKEN if is_acc else summarize_step_public(st["tool"], st["args"], ok, False),
                            "V": orc["known_vs"][idx],
                        }
                    )
                reveal_payload = {
                    "seed": seed,
                    "tier": tier,
                    "agent": akey,
                    "agent_raw": raw_ep["agent"],
                    "mole": orc["mole"],
                    "true_mole": orc["mole"],
                    "decoy": orc["decoy"],
                    "accused": raw_ep["accused"],
                    "correct": bool(raw_ep["correct"]),
                    "score": float(raw_ep["score"]),
                    "true_V": orc["verdict"]["V"],
                    "known_V_final": orc["known_vs"][-1],
                    "final_day": int(raw_ep["final_day"]),
                    "end_reason": raw_ep["end_reason"],
                    "tool_calls": len(raw_ep["steps"]),
                    "accuse_call_idx": accuse_idx,
                    "accuse_args": accuse_args,
                    "accuse_summary": accuse_summary,
                    "final": {
                        "sealed": False,
                        "done": True,
                        "score": float(raw_ep["score"]),
                        "correct": bool(raw_ep["correct"]),
                        "accused": raw_ep["accused"],
                        "mole": orc["mole"],
                        "final_day": int(raw_ep["final_day"]),
                        "end_reason": raw_ep["end_reason"],
                        "tool_calls": len(raw_ep["steps"]),
                    },
                }
                b64 = base64.b64encode(json.dumps(reveal_payload, separators=(",", ":")).encode("ascii")).decode("ascii")
                ep_pack = {
                    "key": f"{tier}:{seed}:{akey}",
                    "seed": seed,
                    "tier": tier,
                    "agent": akey,
                    "agent_raw": raw_ep["agent"],
                    "n_days": p.n_days,
                    "final_day": int(raw_ep["final_day"]),
                    "total_calls": len(raw_ep["steps"]),
                    "has_accuse": accuse_idx is not None,
                    "steps": pre_steps,
                    "sealed_reveal_b64": f"sealed:{b64}",
                }
                pair_entries[akey] = ep_pack
                by_agent[f"{tier}:{seed}:{akey}"] = ep_pack
                episodes[f"{tier}:{seed}:{akey}"] = ep_pack

            world_ep = dict(pair_entries["gemini"])
            world_ep["key"] = f"{tier}:{seed}"
            world_ep["solver_steps"] = pair_entries["solver"]["steps"]
            world_ep["solver_final_day"] = pair_entries["solver"]["final_day"]
            world_ep["solver_sealed_reveal_b64"] = pair_entries["solver"]["sealed_reveal_b64"]
            episodes[f"{tier}:{seed}"] = world_ep

    return {
        "schema_version": "canary_duel_pack.v1",
        "tiers_version": "v1.4",
        "known_v_mode": True,
        "default_tier": "hard",
        "default_seed": 6,
        "featured_seeds": [6, 26],
        "default_seeds": list(seeds_by_tier.get("hard", ())),
        "seeds": {k: list(v) for k, v in seeds_by_tier.items()},
        "agents": ["gemini", "solver"],
        "episodes": episodes,
        "by_agent": by_agent,
    }


def _assert_js_hygiene(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    assert len(raw.strip()) > 0, f"empty JS file: {path}"
    assert raw.isascii(), f"non-ASCII character in {path.name}"
    assert EM_DASH not in raw, f"em dash in {path.name}"
    assert EN_DASH not in raw, f"en dash in {path.name}"
    assert UNICODE_MINUS not in raw, f"unicode minus in {path.name}"
    assert SLASH_SLASH not in raw, f"line comment marker in {path.name}"
    assert SLASH_STAR not in raw, f"block comment open in {path.name}"
    assert STAR_SLASH not in raw, f"block comment close in {path.name}"
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in raw, f"unsafe DOM sink {sink} in {path.name}"
    return raw


def test_self_python_file_ascii_and_zero_comments() -> None:
    raw = SELF_TEST_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert EM_DASH not in raw
    assert EN_DASH not in raw
    assert UNICODE_MINUS not in raw
    assert HASH_CH not in raw
    assert SLASH_SLASH not in raw
    assert SLASH_STAR not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []


def test_committed_duel_target_seeds_and_canary_eval_scores() -> None:
    for s in (*HARD_TARGET_SEEDS, *MEDIUM_TARGET_SEEDS):
        assert s in DEV_SEEDS
        assert s not in JUDGE_SEEDS
        assert s not in HELDOUT_SEEDS

    s6_gem = _replayed_oracle("hard", 6, "gemini")
    s6_sol = _replayed_oracle("hard", 6, "solver")
    assert s6_gem["mole"] == "e34"
    assert s6_sol["mole"] == "e34"
    assert math.isclose(s6_gem["verdict"]["score"], 0.73, abs_tol=1e-9)
    assert math.isclose(s6_gem["ep_res"].score, 0.73, abs_tol=1e-9)
    assert s6_gem["verdict"]["correct"] is True
    assert s6_gem["verdict"]["accused"] == "e34"
    assert s6_gem["verdict"]["final_day"] == 6
    assert len(s6_gem["ep_res"].steps) == 57

    assert math.isclose(s6_sol["verdict"]["score"], 0.71, abs_tol=1e-9)
    assert math.isclose(s6_sol["ep_res"].score, 0.71, abs_tol=1e-9)
    assert s6_sol["verdict"]["correct"] is True
    assert s6_sol["verdict"]["accused"] == "e34"
    assert s6_sol["verdict"]["final_day"] == 6
    assert len(s6_sol["ep_res"].steps) == 52

    s26_gem = _replayed_oracle("hard", 26, "gemini")
    s26_sol = _replayed_oracle("hard", 26, "solver")
    assert s26_gem["mole"] == "e08"
    assert s26_sol["mole"] == "e08"
    assert math.isclose(s26_gem["verdict"]["score"], -1.00, abs_tol=1e-9)
    assert math.isclose(s26_gem["ep_res"].score, -1.00, abs_tol=1e-9)
    assert s26_gem["verdict"]["correct"] is False
    assert s26_gem["verdict"]["accused"] == "e04"
    assert s26_gem["verdict"]["final_day"] == 10
    assert len(s26_gem["ep_res"].steps) == 91

    assert math.isclose(s26_sol["verdict"]["score"], 0.69, abs_tol=1e-9)
    assert math.isclose(s26_sol["ep_res"].score, 0.69, abs_tol=1e-9)
    assert s26_sol["verdict"]["correct"] is True
    assert s26_sol["verdict"]["accused"] == "e08"
    assert s26_sol["verdict"]["final_day"] == 7
    assert len(s26_sol["ep_res"].steps) == 60

    s11_gem = _replayed_oracle("hard", 11, "gemini")
    assert math.isclose(s11_gem["verdict"]["score"], 0.0, abs_tol=1e-9)
    assert s11_gem["verdict"]["accused"] is None
    assert s11_gem["verdict"]["correct"] is False
    assert s11_gem["verdict"]["end_reason"] == "horizon"
    assert s11_gem["verdict"]["final_day"] == 21
    assert len(s11_gem["ep_res"].steps) == 212

    hard_gem_eps = []
    hard_sol_eps = []
    for seed in HARD_TARGET_SEEDS:
        for akey, bucket in (("gemini", hard_gem_eps), ("solver", hard_sol_eps)):
            orc = _replayed_oracle("hard", seed, akey)
            ep = orc["ep_res"]
            vd = orc["verdict"]
            assert math.isclose(ep.score, vd["score"], abs_tol=1e-9)
            assert ep.correct is vd["correct"]
            assert ep.accused == vd["accused"]
            assert ep.final_day == vd["final_day"]
            assert ep.end_reason == vd["end_reason"]
            bucket.append(ep)

    gem_summary = summarize(hard_gem_eps)
    sol_summary = summarize(hard_sol_eps)
    assert gem_summary["n"] == 8 and sol_summary["n"] == 8
    assert gem_summary["accused"] == 7 and sol_summary["accused"] == 8
    assert math.isclose(sol_summary["accuracy"], 7 / 8, abs_tol=1e-9)
    assert math.isclose(gem_summary["accuracy"], 4 / 8, abs_tol=1e-9)

    for seed, exp_gem, exp_sol, exp_mole in (
        (0, 0.63, 0.74, "e05"),
        (12, 0.81, 0.67, "e06"),
    ):
        mg = _replayed_oracle("medium", seed, "gemini")
        ms = _replayed_oracle("medium", seed, "solver")
        assert mg["mole"] == exp_mole and ms["mole"] == exp_mole
        assert math.isclose(mg["verdict"]["score"], exp_gem, abs_tol=1e-9)
        assert math.isclose(ms["verdict"]["score"], exp_sol, abs_tol=1e-9)


def test_known_v_reconstruction_matches_env_and_hides_unsurfaced_leaks() -> None:
    total_steps = 0
    divergent_steps = 0
    for tier, seeds in (("hard", HARD_TARGET_SEEDS), ("medium", MEDIUM_TARGET_SEEDS)):
        for seed in seeds:
            for akey in ("gemini", "solver"):
                orc = _replayed_oracle(tier, seed, akey)
                inferred = compute_known_v_from_public_steps(tier, orc["raw_ep"]["steps"])
                assert len(inferred) == len(orc["known_vs"])
                for kv_inf, kv_env, tv_env in zip(inferred, orc["known_vs"], orc["true_vs"]):
                    total_steps += 1
                    assert math.isclose(kv_inf, kv_env, abs_tol=1e-9)
                    assert kv_env >= tv_env - 1e-9
                    if abs(kv_env - tv_env) > 1e-9:
                        divergent_steps += 1

    assert total_steps > 1500
    assert divergent_steps > 200

    s6_gem = _replayed_oracle("hard", 6, "gemini")
    day2_indices = [i for i, st in enumerate(s6_gem["raw_ep"]["steps"]) if st["day"] == 2]
    first_day2 = day2_indices[0]
    assert math.isclose(s6_gem["known_vs"][first_day2], 0.98, abs_tol=1e-9)
    assert math.isclose(s6_gem["true_vs"][first_day2], 0.93, abs_tol=1e-9)

    s26_gem = _replayed_oracle("hard", 26, "gemini")
    day3_indices = [i for i, st in enumerate(s26_gem["raw_ep"]["steps"]) if st["day"] == 3]
    first_day3 = day3_indices[0]
    assert math.isclose(s26_gem["known_vs"][first_day3], 1.00, abs_tol=1e-9)
    assert math.isclose(s26_gem["true_vs"][first_day3], 0.95, abs_tol=1e-9)


def test_python_reference_projection_zero_leak_sync_and_negative_controls() -> None:
    for seed in (6, 26, 11):
        for akey in ("gemini", "solver"):
            orc = _replayed_oracle("hard", seed, akey)
            raw_steps = orc["raw_ep"]["steps"]
            for day in range(1, 22):
                view = project_episode_reference(orc, human_day=day, human_done=False)
                leaks = collect_pre_end_leak_violations(view, orc, human_day=day)
                assert leaks == []
                expected_indices = [i for i, st in enumerate(raw_steps) if int(st["day"]) <= day]
                assert [s["call_idx"] for s in view["steps"]] == expected_indices
                assert [s["V"] for s in view["steps"]] == [orc["known_vs"][i] for i in expected_indices]

            for cutoff in (0, 5, int(len(raw_steps) * 0.5), len(raw_steps) - 1):
                step_view = project_episode_reference(orc, human_day=21, human_done=False, max_call_idx=cutoff)
                assert collect_pre_end_leak_violations(step_view, orc, human_day=21, max_call_idx=cutoff) == []
                assert [s["call_idx"] for s in step_view["steps"]] == list(range(cutoff + 1))

            done_view = project_episode_reference(orc, human_day=1, human_done=True)
            assert len(done_view["steps"]) == len(raw_steps)
            assert done_view["final"] is not None
            assert done_view["final"]["sealed"] is False
            assert math.isclose(done_view["final"]["score"], orc["verdict"]["score"], abs_tol=1e-9)
            assert done_view["final"]["correct"] is orc["verdict"]["correct"]
            assert done_view["final"]["accused"] == orc["verdict"]["accused"]
            assert done_view["final"]["mole"] == orc["mole"]
            if orc["verdict"]["accused"] is not None:
                assert done_view["steps"][-1]["args"]["employee"] == orc["verdict"]["accused"]

    s26_gem = _replayed_oracle("hard", 26, "gemini")
    bad_mole = project_episode_reference(s26_gem, human_day=4, human_done=False)
    bad_mole["true_mole"] = "e08"
    assert any("true_mole" in v for v in collect_pre_end_leak_violations(bad_mole, s26_gem, human_day=4))

    bad_accuse = project_episode_reference(s26_gem, human_day=10, human_done=False)
    bad_accuse["steps"][-1]["args"]["employee"] = "e04"
    assert any("e04" in v or "args.employee" in v for v in collect_pre_end_leak_violations(bad_accuse, s26_gem, human_day=10))

    bad_day = project_episode_reference(s26_gem, human_day=3, human_done=False)
    bad_day["steps"].append({"day": 4, "call_idx": 99, "tool": "status", "args": {}, "ok": True, "summary": "status", "V": 0.95})
    assert any("exceeds human_day=3" in v for v in collect_pre_end_leak_violations(bad_day, s26_gem, human_day=3))


def test_arena_js_artifacts_ascii_and_comment_free() -> None:
    arena_index = ROOT / "docs" / "arena" / "index.html"
    replay_js = _replay_js_path()
    pack_js = _duel_pack_js_path()

    if arena_index.is_file():
        assert replay_js.is_file(), f"missing {replay_js} in integrated Arena tree"
        assert pack_js.is_file(), f"missing {pack_js} in integrated Arena tree"

    if not replay_js.is_file() and not pack_js.is_file():
        pytest.skip("Arena JS artifacts live on w2-arena / w3-arena / arena integration branch")

    if replay_js.is_file():
        src = _assert_js_hygiene(replay_js)
        assert "CanaryReplayEngine" in src
        assert SEALED_TOKEN in src
    if pack_js.is_file():
        pack_src = _assert_js_hygiene(pack_js)
        assert "CANARY_DUEL_PACK" in pack_src


def test_duel_pack_js_schema_and_zero_unsealed_truth() -> None:
    pack_js = _duel_pack_js_path()
    if not pack_js.is_file():
        pytest.skip("docs/arena/data/committed_duel_pack.js not present in this checkout")
    node_bin = _find_node_bin()
    assert node_bin is not None, "node binary required to inspect committed_duel_pack.js"

    probe = """
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import vm from "node:vm";

const packPath = JSON.parse(fs.readFileSync(0, "utf8")).packPath;
const code = fs.readFileSync(packPath, "utf8");
globalThis.window = globalThis;
globalThis.self = globalThis;
let modPack = null;
try {
  const m = await import(pathToFileURL(packPath).href);
  modPack = m.CANARY_DUEL_PACK || m.default || globalThis.CANARY_DUEL_PACK;
} catch (_) {
  vm.runInThisContext(code, { filename: packPath });
  modPack = globalThis.CANARY_DUEL_PACK;
}
if (!modPack) process.exit(2);

function decodeSealedToken(tok) {
  if (!tok) return null;
  if (typeof tok === "object") return tok;
  if (typeof tok !== "string") return null;
  let clean = tok.trim();
  if (clean.startsWith("sealed:")) clean = clean.slice(7).trim();
  if (clean.startsWith("b64:")) clean = clean.slice(4).trim();
  if (!clean) return null;
  if (clean.startsWith("{")) {
    try { return JSON.parse(clean); } catch (_) { return null; }
  }
  try {
    return JSON.parse(Buffer.from(clean, "base64").toString("utf8"));
  } catch (_) {
    return null;
  }
}

const unsealed = {};
const rawEps = {};
const tiers = { hard: [6, 26, 4, 18, 15, 11, 5, 23], medium: [0, 12] };
for (const [tier, seeds] of Object.entries(tiers)) {
  for (const seed of seeds) {
    for (const agent of ["gemini", "solver"]) {
      const k1 = `${tier}:${seed}:${agent}`;
      const kWorld = `${tier}:${seed}`;
      let ep = (modPack.by_agent && modPack.by_agent[k1])
        || (modPack.episodes && modPack.episodes[k1])
        || null;
      let worldEntry = (modPack.episodes && (modPack.episodes[kWorld] || modPack.episodes[String(seed)])) || null;
      if (!ep && worldEntry) {
        if (worldEntry[agent] && Array.isArray(worldEntry[agent].steps)) {
          ep = worldEntry[agent];
        } else if (worldEntry.tracks && worldEntry.tracks[agent] && Array.isArray(worldEntry.tracks[agent].steps)) {
          ep = worldEntry.tracks[agent];
        } else if (agent === "gemini" && Array.isArray(worldEntry.steps)) {
          ep = worldEntry;
        } else if (agent === "solver" && Array.isArray(worldEntry.solver_steps)) {
          ep = {
            seed,
            tier,
            agent: "solver",
            steps: worldEntry.solver_steps,
            sealed_reveal_b64: worldEntry.solver_sealed_reveal_b64 || worldEntry.sealed_reveal_b64,
          };
        }
      }
      if (!ep) { console.error("missing", k1); process.exit(3); }
      const clone = JSON.parse(JSON.stringify(ep));
      for (const k of Object.keys(clone)) {
        if (k.includes("sealed") || k === "solver_steps") {
          delete clone[k];
        }
      }
      rawEps[k1] = clone;

      let rev = null;
      if (typeof modPack.unlockPostGameReveal === "function") {
        try {
          const u = modPack.unlockPostGameReveal(tier, seed, true, agent);
          if (u && typeof u === "object") {
            if (u[agent] && typeof u[agent] === "object") {
              rev = Object.assign({ mole: u.mole ?? null }, u[agent]);
            } else if (agent === "gemini" && u.score !== undefined) {
              rev = u;
            } else if (agent === "solver" && u.solver && typeof u.solver === "object") {
              rev = Object.assign({ mole: u.mole ?? null }, u.solver);
            } else if (u.score !== undefined) {
              rev = u;
            }
          }
        } catch (_) {}
      }
      if (!rev && typeof modPack.unsealReveal === "function") {
        try {
          const tok = ep.sealed_reveal_b64 || ep.solver_sealed_reveal_b64 || ep;
          const u = modPack.unsealReveal(tok);
          if (u && typeof u === "object") {
            rev = (agent === "solver" && u.solver && typeof u.solver === "object")
              ? Object.assign({ mole: u.mole ?? null }, u.solver)
              : u;
          }
        } catch (_) {}
      }
      if (!rev) {
        const candidates = [
          ep.sealed_reveal_b64,
          ep.sealed_reveal,
          ep.sealed_verdict,
          worldEntry && (agent === "solver" ? worldEntry.solver_sealed_reveal_b64 : worldEntry.sealed_reveal_b64),
          worldEntry && worldEntry.sealed_reveal_b64,
          worldEntry && worldEntry.sealed_verdict,
        ];
        for (const c of candidates) {
          const parsed = decodeSealedToken(c);
          if (parsed && typeof parsed === "object") {
            rev = (agent === "solver" && parsed.solver && typeof parsed.solver === "object")
              ? Object.assign({ mole: parsed.mole ?? null }, parsed.solver)
              : (agent === "gemini" && parsed.gemini && typeof parsed.gemini === "object")
                ? Object.assign({ mole: parsed.mole ?? null }, parsed.gemini)
                : parsed;
            if (rev && (rev.score !== undefined || rev.final)) break;
          }
        }
      }
      unsealed[k1] = rev;
    }
  }
}
console.log(JSON.stringify({ rawEps, unsealed }));
"""
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", probe],
        input=json.dumps({"packPath": str(pack_js)}),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])

    for tier, seeds in (("hard", HARD_TARGET_SEEDS), ("medium", MEDIUM_TARGET_SEEDS)):
        for seed in seeds:
            for akey in ("gemini", "solver"):
                key = f"{tier}:{seed}:{akey}"
                orc = _replayed_oracle(tier, seed, akey)
                ep = payload["rawEps"][key]
                ep_view = {
                    "seed": seed,
                    "tier": tier,
                    "agent": akey,
                    "steps": ep["steps"],
                    "final": {"sealed": True, "final_day": int(orc["raw_ep"]["final_day"])},
                }
                leaks = collect_pre_end_leak_violations(ep_view, orc, human_day=21, loc=key)
                assert leaks == [], leaks
                assert len(ep["steps"]) == len(orc["known_vs"])
                for idx, (st, exp_kv) in enumerate(zip(ep["steps"], orc["known_vs"])):
                    if "t" in st and st["t"] is not None:
                        assert int(st["t"]) == idx
                    if "call_idx" in st and st["call_idx"] is not None:
                        assert int(st["call_idx"]) in (idx, idx + 1)
                    st_v = st.get("V")
                    if st_v is None:
                        st_v = st.get("known_v", st.get("visible_v"))
                    assert st_v is not None, (key, idx, st)
                    assert math.isclose(float(st_v), exp_kv, abs_tol=1e-9), (key, idx, st_v, exp_kv)

                rev = payload["unsealed"][key]
                assert rev is not None, f"missing unsealed reveal for {key}"
                rev_final = rev.get("final") if isinstance(rev.get("final"), dict) else rev
                assert math.isclose(float(rev_final["score"]), orc["verdict"]["score"], abs_tol=1e-9)
                assert bool(rev_final["correct"]) is orc["verdict"]["correct"]
                assert rev_final["accused"] == orc["verdict"]["accused"]
                if "mole" in rev_final and rev_final["mole"] is not None:
                    assert rev_final["mole"] == orc["mole"]


def _run_replay_engine_js_probe(
    node_bin: str,
    replay_js: Path,
    pack_js: Path | None,
    fixture_pack: dict[str, Any] | None,
    raw_jsonl_bundles: dict[str, str] | None,
) -> dict[str, Any]:
    cfg = {
        "replayUrl": replay_js.as_uri(),
        "packPath": str(pack_js) if pack_js and pack_js.is_file() else None,
        "fixturePack": fixture_pack,
        "rawBundles": raw_jsonl_bundles or {},
    }
    script = """
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import vm from "node:vm";

const cfg = JSON.parse(fs.readFileSync(0, "utf8"));
globalThis.window = globalThis;
globalThis.self = globalThis;

let pack = cfg.fixturePack;
if (cfg.packPath) {
  const packCode = fs.readFileSync(cfg.packPath, "utf8");
  try {
    const pm = await import(pathToFileURL(cfg.packPath).href);
    pack = pm.CANARY_DUEL_PACK || pm.default || globalThis.CANARY_DUEL_PACK;
  } catch (_) {
    vm.runInThisContext(packCode, { filename: cfg.packPath });
    pack = globalThis.CANARY_DUEL_PACK;
  }
}
globalThis.CANARY_DUEL_PACK = pack;

const mod = await import(cfg.replayUrl);
const RE = mod.CanaryReplayEngine || mod.default || globalThis.CanaryReplayEngine;
if (!RE) {
  throw new Error("CanaryReplayEngine not exported on module or window");
}

function makePackEngine(p) {
  if (typeof RE.fromPack === "function") return RE.fromPack(p);
  if (typeof mod.fromPack === "function") return mod.fromPack(p);
  if (typeof RE.createReplayEngine === "function") return RE.createReplayEngine(p);
  if (typeof mod.createReplayEngine === "function") return mod.createReplayEngine(p);
  if (typeof RE === "function") {
    try { return new RE(p); } catch (_) { return RE(p); }
  }
  if (typeof RE.loadReplays === "function") {
    RE.loadReplays(p);
    return RE;
  }
  return RE;
}

function makeJsonlEngine(jsonlText, tier) {
  if (typeof RE.fromJsonl === "function") return RE.fromJsonl(jsonlText, { tier });
  if (typeof mod.fromJsonl === "function") return mod.fromJsonl(jsonlText, { tier });
  if (typeof RE.createReplayEngine === "function") return RE.createReplayEngine(jsonlText);
  if (typeof mod.createReplayEngine === "function") return mod.createReplayEngine(jsonlText);
  if (typeof RE === "function") {
    const inst = new RE();
    if (typeof inst.loadJsonl === "function") { inst.loadJsonl(jsonlText, { tier }); return inst; }
    if (typeof inst.loadEpisodesJsonl === "function") { inst.loadEpisodesJsonl(jsonlText); return inst; }
  }
  const parseFn = RE.parseEpisodesJsonl || mod.parseEpisodesJsonl;
  const projFn = RE.projectEpisode || mod.projectEpisode;
  if (typeof parseFn === "function" && typeof projFn === "function") {
    const eps = parseFn(jsonlText);
    return {
      _eps: eps,
      getView(opts) {
        const want = opts.agent === "gemini" ? "gemini" : "solver";
        const found = eps.find((e) => Number(e.seed) === Number(opts.seed) && (
          want === "solver" ? String(e.agent).includes("solver") : String(e.agent).includes("gemini")
        ));
        return projFn(found, opts);
      }
    };
  }
  throw new Error("No JSONL entrypoint found on CanaryReplayEngine");
}

function queryEngine(eng, { tier, seed, agent, humanDay, humanDone, maxCallIdx = null }) {
  const opts = { tier, seed, agent, humanDay, humanDone, maxCallIdx };
  for (const fnName of ["getEpisodeView", "getView", "stepView"]) {
    if (eng && typeof eng[fnName] === "function") {
      return eng[fnName](opts);
    }
  }
  for (const fnName of ["getDuelView", "getDayState"]) {
    if (eng && typeof eng[fnName] === "function") {
      let res = null;
      if (eng[fnName].length >= 2) {
        res = eng[fnName](seed, humanDay, humanDone, tier, agent);
      } else {
        res = eng[fnName](opts);
      }
      if (res && res.gemini && res.solver && !Array.isArray(res.steps)) {
        return agent === "solver" ? res.solver : res.gemini;
      }
      if (res && agent === "solver" && String(res.agent || "").includes("gemini") && Array.isArray(res.solver_steps)) {
        const solFinal = humanDone && res.final && res.final.solver ? res.final.solver : (
          !humanDone && res.solver_final_day && res.solver_final_day <= humanDay
            ? { sealed: true, final_day: res.solver_final_day }
            : null
        );
        return { seed, tier, agent: "solver", steps: res.solver_steps, final: solFinal };
      }
      return res;
    }
  }
  throw new Error("No query method found on engine");
}

const packEng = makePackEngine(pack);
const packSweep = {};
for (const [tier, seeds] of [["hard", [6, 26, 11, 15]], ["medium", [0, 12]]]) {
  const nDays = tier === "hard" ? 21 : 14;
  for (const seed of seeds) {
    for (const agent of ["gemini", "solver"]) {
      const days = {};
      for (let d = 1; d <= nDays; d += 1) {
        days[String(d)] = queryEngine(packEng, { tier, seed, agent, humanDay: d, humanDone: false });
      }
      const done = queryEngine(packEng, { tier, seed, agent, humanDay: nDays, humanDone: true });
      packSweep[`${tier}:${seed}:${agent}`] = { days, done };
    }
  }
}

const packFinals = {};
for (const [tier, seeds] of [["hard", [6, 26, 4, 18, 15, 11, 5, 23]], ["medium", [0, 12]]]) {
  const nDays = tier === "hard" ? 21 : 14;
  for (const seed of seeds) {
    for (const agent of ["gemini", "solver"]) {
      packFinals[`${tier}:${seed}:${agent}`] = queryEngine(packEng, { tier, seed, agent, humanDay: nDays, humanDone: true });
    }
  }
}

let staticApi = null;
const winRE = globalThis.CanaryReplayEngine;
if (winRE) {
  staticApi = {
    hasWindowGlobal: true,
    hardSeeds: typeof winRE.listSeeds === "function" ? winRE.listSeeds("hard") : null,
    staticDay6Pre: typeof winRE.getDuelView === "function" ? winRE.getDuelView(6, 6, false, "hard") : null,
    staticDay6Done: typeof winRE.getDuelView === "function" ? winRE.getDuelView(6, 6, true, "hard") : null,
  };
}

const subdayGating = {
  s6_c0: queryEngine(packEng, { tier: "hard", seed: 6, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 0 }),
  s6_c5: queryEngine(packEng, { tier: "hard", seed: 6, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 5 }),
  s6_c55: queryEngine(packEng, { tier: "hard", seed: 6, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 55 }),
  s6_c56: queryEngine(packEng, { tier: "hard", seed: 6, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 56 }),
  s26_c89: queryEngine(packEng, { tier: "hard", seed: 26, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 89 }),
  s26_c90: queryEngine(packEng, { tier: "hard", seed: 26, agent: "gemini", humanDay: 21, humanDone: false, maxCallIdx: 90 }),
};

let instanceApi = null;
if (packEng && typeof packEng.selectEpisode === "function" && typeof packEng.compareWithHuman === "function") {
  const sel6 = packEng.selectEpisode("hard", 6);
  const stepDay6Pre = typeof packEng.stepToDay === "function" ? packEng.stepToDay(6, false) : null;
  const cmpPre = packEng.compareWithHuman({ score: 0.80, accused: "e34", correct: true, final_day: 5, tool_calls: 40 }, false);
  const cmpDone6 = packEng.compareWithHuman({ tier: "hard", seed: 6, score: 0.80, accused: "e34", correct: true, final_day: 5, tool_calls: 40 }, true);
  packEng.selectEpisode("hard", 26);
  const cmpDone26 = packEng.compareWithHuman({ tier: "hard", seed: 26, score: -1.00, accused: "e04", correct: false, final_day: 9, tool_calls: 70 }, true);
  instanceApi = { sel6, stepDay6Pre, cmpPre, cmpDone6, cmpDone26 };
}

const jsonlResults = {};
for (const [tier, text] of Object.entries(cfg.rawBundles)) {
  const jEng = makeJsonlEngine(text, tier);
  const seeds = tier === "hard" ? [6, 26, 11] : [0, 12];
  const nDays = tier === "hard" ? 21 : 14;
  for (const seed of seeds) {
    for (const agent of ["gemini", "solver"]) {
      const days = {};
      for (let d = 1; d <= nDays; d += 1) {
        days[String(d)] = queryEngine(jEng, { tier, seed, agent, humanDay: d, humanDone: false });
      }
      const done = queryEngine(jEng, { tier, seed, agent, humanDay: nDays, humanDone: true });
      jsonlResults[`${tier}:${seed}:${agent}`] = { days, done };
    }
  }
}

console.log(JSON.stringify({ packSweep, packFinals, staticApi, subdayGating, instanceApi, jsonlResults }));
"""
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        input=json.dumps(cfg),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_replay_engine_js_pack_and_raw_jsonl_parity() -> None:
    replay_js = _replay_js_path()
    if not replay_js.is_file():
        pytest.skip("docs/arena/replay_engine.js not present in this checkout")
    node_bin = _find_node_bin()
    assert node_bin is not None, "node binary required to execute docs/arena/replay_engine.js"

    pack_js = _duel_pack_js_path()
    fixture_pack = None if pack_js.is_file() else _build_fixture_duel_pack(
        {"hard": HARD_TARGET_SEEDS, "medium": MEDIUM_TARGET_SEEDS}
    )

    hard_raw_lines: list[str] = []
    for s in (6, 26, 11):
        hard_raw_lines.append(_replayed_oracle("hard", s, "gemini")["raw_line"])
        hard_raw_lines.append(_replayed_oracle("hard", s, "solver")["raw_line"])
    med_raw_lines: list[str] = []
    for s in (0, 12):
        med_raw_lines.append(_replayed_oracle("medium", s, "gemini")["raw_line"])
        med_raw_lines.append(_replayed_oracle("medium", s, "solver")["raw_line"])

    out = _run_replay_engine_js_probe(
        node_bin=node_bin,
        replay_js=replay_js,
        pack_js=pack_js if pack_js.is_file() else None,
        fixture_pack=fixture_pack,
        raw_jsonl_bundles={
            "hard": "\n".join(hard_raw_lines) + "\n",
            "medium": "\n".join(med_raw_lines) + "\n",
        },
    )

    assert out["staticApi"] is not None and out["staticApi"]["hasWindowGlobal"] is True
    if out["staticApi"]["hardSeeds"] is not None:
        assert 6 in out["staticApi"]["hardSeeds"] and 26 in out["staticApi"]["hardSeeds"]
    if out["staticApi"]["staticDay6Pre"] is not None:
        s6_gem_orc = _replayed_oracle("hard", 6, "gemini")
        pre6 = out["staticApi"]["staticDay6Pre"]
        pre6_view = pre6["gemini"] if "gemini" in pre6 and "steps" not in pre6 else pre6
        assert collect_pre_end_leak_violations(pre6_view, s6_gem_orc, human_day=6, loc="staticDay6Pre") == []

    for source_name, sweep_map in (("pack", out["packSweep"]), ("raw_jsonl", out["jsonlResults"])):
        for key, entry in sweep_map.items():
            tier, seed_str, akey = key.split(":")
            seed = int(seed_str)
            orc = _replayed_oracle(tier, seed, akey)
            raw_steps = orc["raw_ep"]["steps"]
            n_days = 21 if tier == "hard" else 14

            for d in range(1, n_days + 1):
                view = entry["days"][str(d)]
                assert int(view["seed"]) == seed
                assert view["tier"] == tier
                leaks = collect_pre_end_leak_violations(view, orc, human_day=d, loc=f"{source_name}:{key}:d{d}")
                assert leaks == [], leaks

                exp_indices = [i for i, st in enumerate(raw_steps) if int(st["day"]) <= d]
                assert len(view["steps"]) == len(exp_indices), (source_name, key, d)
                for pos, (got_st, orig_idx) in enumerate(zip(view["steps"], exp_indices)):
                    orig = raw_steps[orig_idx]
                    assert int(got_st["day"]) == int(orig["day"])
                    assert int(got_st["call_idx"]) == orig_idx
                    assert got_st["tool"] == orig["tool"]
                    assert bool(got_st["ok"]) is bool(orig["result"]["ok"])
                    assert isinstance(got_st["summary"], str) and len(got_st["summary"]) > 0
                    assert math.isclose(float(got_st["V"]), orc["known_vs"][orig_idx], abs_tol=1e-9), (
                        source_name,
                        key,
                        d,
                        pos,
                        got_st["V"],
                        orc["known_vs"][orig_idx],
                    )

            done_view = entry["done"]
            assert len(done_view["steps"]) == len(raw_steps)
            assert done_view["final"] is not None
            assert done_view["final"].get("sealed") in (False, None)
            assert math.isclose(float(done_view["final"]["score"]), orc["verdict"]["score"], abs_tol=1e-9)
            assert bool(done_view["final"]["correct"]) is orc["verdict"]["correct"]
            assert done_view["final"]["accused"] == orc["verdict"]["accused"]
            assert int(done_view["final"]["final_day"]) == orc["verdict"]["final_day"]
            if orc["verdict"]["accused"] is not None:
                assert done_view["steps"][-1]["tool"] == "accuse"
                assert done_view["steps"][-1]["args"]["employee"] == orc["verdict"]["accused"]
            if source_name == "pack" and done_view["final"].get("mole") is not None:
                assert done_view["final"]["mole"] == orc["mole"]

    for tier, seeds in (("hard", HARD_TARGET_SEEDS), ("medium", MEDIUM_TARGET_SEEDS)):
        for seed in seeds:
            for akey in ("gemini", "solver"):
                key = f"{tier}:{seed}:{akey}"
                orc = _replayed_oracle(tier, seed, akey)
                fin = out["packFinals"][key]["final"]
                assert fin is not None
                assert math.isclose(float(fin["score"]), orc["verdict"]["score"], abs_tol=1e-9)
                assert bool(fin["correct"]) is orc["verdict"]["correct"]
                assert fin["accused"] == orc["verdict"]["accused"]
                assert int(fin["final_day"]) == orc["verdict"]["final_day"]

    assert math.isclose(float(out["packFinals"]["hard:6:gemini"]["final"]["score"]), 0.73, abs_tol=1e-9)
    assert math.isclose(float(out["packFinals"]["hard:6:solver"]["final"]["score"]), 0.71, abs_tol=1e-9)
    assert math.isclose(float(out["packFinals"]["hard:26:gemini"]["final"]["score"]), -1.00, abs_tol=1e-9)
    assert math.isclose(float(out["packFinals"]["hard:26:solver"]["final"]["score"]), 0.69, abs_tol=1e-9)
    assert math.isclose(float(out["packFinals"]["hard:11:gemini"]["final"]["score"]), 0.0, abs_tol=1e-9)
    assert math.isclose(float(out["packFinals"]["hard:11:solver"]["final"]["score"]), 0.62, abs_tol=1e-9)

    s6_gem_orc = _replayed_oracle("hard", 6, "gemini")
    s26_gem_orc = _replayed_oracle("hard", 26, "gemini")
    for tag, orc, cutoff in (
        ("s6_c0", s6_gem_orc, 0),
        ("s6_c5", s6_gem_orc, 5),
        ("s6_c55", s6_gem_orc, 55),
        ("s6_c56", s6_gem_orc, 56),
        ("s26_c89", s26_gem_orc, 89),
        ("s26_c90", s26_gem_orc, 90),
    ):
        gview = out["subdayGating"][tag]
        assert len(gview["steps"]) == cutoff + 1
        assert collect_pre_end_leak_violations(gview, orc, human_day=21, loc=tag, max_call_idx=cutoff) == []

    if out["instanceApi"] is not None:
        inst = out["instanceApi"]
        assert inst["sel6"]["seed"] == 6 and inst["sel6"]["tier"] == "hard"
        assert inst["sel6"]["hasGemini"] is True and inst["sel6"]["hasSolver"] is True
        if inst["stepDay6Pre"] is not None:
            assert collect_pre_end_leak_violations(
                inst["stepDay6Pre"]["gemini"], s6_gem_orc, human_day=6, loc="stepDay6Pre.gemini"
            ) == []
            assert collect_pre_end_leak_violations(
                inst["stepDay6Pre"]["solver"], _replayed_oracle("hard", 6, "solver"), human_day=6, loc="stepDay6Pre.solver"
            ) == []
        assert inst["cmpPre"] is None
        assert inst["cmpDone6"]["winner"] == "human"
        assert inst["cmpDone6"]["firstCatch"] == "You"
        assert "CANARY ARENA | Seed 6 (hard)" in inst["cmpDone6"]["summary"]
        assert inst["cmpDone26"]["winner"] == "solver"
        assert inst["cmpDone26"]["firstCatch"] == "Solver"
        assert "CANARY ARENA | Seed 26 (hard)" in inst["cmpDone26"]["summary"]
