from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from canary.agents.frontier.common import empty_final_response
from canary.agents.runlog import git_sha
from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.baselines import BASELINES
from canary.env import Env
from canary.eval import make_env, parse_seeds, run_episode
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.policy import SolverPolicy
import verify_replay

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3

DEFAULT_SEEDS = "0-9"
DEFAULT_TIER = "hard"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_V16_PROVIDER = "social-v2"
DEFAULT_WALL_CAP_S = 3600.0
DEFAULT_BOOTSTRAP_RESAMPLES = 10000
DEFAULT_BOOTSTRAP_SEED = 0

DEFAULT_V14_DIR = REPO_ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon"
DEFAULT_REFERENCE_DIR = REPO_ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
DEFAULT_V16_ROOT = REPO_ROOT / "results" / "v16_social" / "opencode_v16"
DEFAULT_REF_30_49_JSON = REPO_ROOT / "results" / "v16_social" / "reference_seeds_30_49.json"
DEFAULT_OUT_JSON = REPO_ROOT / "results" / "v16_social" / "paired_v14_vs_v16_0_9.json"
DEFAULT_OUT_MD = REPO_ROOT / "results" / "v16_social" / "paired_v14_vs_v16_0_9.md"
DEFAULT_OUT_GATE_MD = REPO_ROOT / "docs" / "reports" / "v16_social_gate.md"

AZURE_RELAYED_SCORES: tuple[tuple[str, tuple[tuple[int, float], ...]], ...] = (
    ("v0_v14_control", ((30, 0.54), (31, 0.55), (32, 0.48))),
    ("v5_full9_cocktail", ((30, 0.50), (31, 0.64), (32, 0.71))),
    ("v1_anchoring_authority_confirmation", ((30, 0.65),)),
    ("v3_grudge_falsemem_misforward", ((30, 0.65), (31, 0.64))),
)

DEFAULT_STAGING_GLOBS: tuple[str, ...] = (
    "/localscratch/fleet-silas/v16-eval-staging*",
    "/tmp/opencode/v16-eval-staging*",
    "/tmp/fleet-silas/shared/v16_runs*",
    "/localscratch/fleet-silas/v16_runs*",
)

DEFAULT_POLL_BRANCHES: tuple[str, ...] = (
    "origin/fr8/canary/canary-staffai-w1",
    "origin/fr8/canary/canary-staffai-w4",
    "origin/fr8/canary/canary-staffai-w8",
    "origin/fr8/canary/canary-port-w5",
    "origin/fr8/canary/canary-port-w1",
    "origin/fr8/canary/staffai",
    "origin/fr8/canary/port",
)

SHARD_OWNERS: dict[int, str] = {
    0: "canary-staffai-w1",
    1: "canary-staffai-w1",
    2: "canary-staffai-w4",
    3: "canary-staffai-w4",
    4: "canary-staffai-w8",
    5: "canary-port-w5",
    6: "canary-port-w5",
    7: "canary-port-w5",
    8: "canary-port-w1",
    9: "canary-port-w1",
}

FORBIDDEN_OUTPUT_KEYS = frozenset({
    "mole",
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})

KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)


def pid_alive(pid: int, needle: str = "") -> bool:
    if pid <= 0:
        return False
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            raw = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
            if not raw.strip():
                return False
            return (needle in raw) if needle else True
        except OSError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def template_social_spec(provider_spec: str) -> str:
    if provider_spec in ("social-v2", "v16") or provider_spec.startswith(("social-v2:", "v16:")):
        head, sep, rest = provider_spec.partition(":")
        base = "social-v2-template" if head.startswith("social-v2") else "v16-template"
        return f"{base}:{rest}" if sep else base
    return provider_spec


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _round_or_none(val: float | None, ndigits: int = 6) -> float | None:
    if val is None or not math.isfinite(float(val)):
        return None
    return round(float(val), ndigits)


def boot_ratio(
    num: list[float],
    den: list[float],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    rng_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if len(num) != len(den) or len(num) < 2 or sum(den) <= 0.0:
        return None, None
    n = len(num)
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(den[i] for i in idx) / n
        if ms > 0.0:
            vals.append((sum(num[i] for i in idx) / n) / ms)
    if not vals:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[max(0, int(0.975 * len(vals)) - 1)]


def boot_delta_ratio(
    num_b: list[float],
    num_a: list[float],
    den: list[float],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    rng_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if not (len(num_b) == len(num_a) == len(den)) or len(den) < 2 or sum(den) <= 0.0:
        return None, None
    n = len(den)
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(den[i] for i in idx) / n
        if ms > 0.0:
            mb = sum(num_b[i] for i in idx) / n
            ma = sum(num_a[i] for i in idx) / n
            vals.append((mb - ma) / ms)
    if not vals:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[max(0, int(0.975 * len(vals)) - 1)]


def boot_mean_ci(
    xs: list[float],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    rng_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if len(xs) < 2:
        return None, None
    n = len(xs)
    rng = random.Random(rng_seed)
    vals = [sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)]
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[max(0, int(0.975 * len(vals)) - 1)]


def find_transcript_text(run_dir: Path | None, seed: int) -> str:
    if run_dir is None or not run_dir.is_dir():
        return ""
    candidates = (
        run_dir / "transcripts" / f"{seed}.txt",
        run_dir / "transcripts" / f"seed_{seed}.txt",
        run_dir / f"{seed}.txt",
        run_dir / "transcript.txt",
    )
    for cand in candidates:
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""


def check_score_invariants(ep: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    raw_score = ep.get("score")
    if not _is_finite_num(raw_score):
        return [f"non_finite_score:{raw_score!r}"]
    score = float(raw_score)
    if not (-1.0 <= score <= 1.0):
        errs.append(f"score_out_of_bounds:{score}")
    accused = ep.get("accused")
    has_accused = isinstance(accused, str) and bool(accused.strip())
    if accused is not None and not has_accused:
        errs.append(f"invalid_accused:{accused!r}")
    correct = bool(ep.get("correct"))
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    if score > 0.0 and not (has_accused and correct):
        errs.append("positive_score_without_correct_accusation")
    if has_accused and correct:
        zero_v = score == 0.0 and "V" in meta and meta.get("V") == 0.0
        if not (score > 0.0 or zero_v):
            errs.append(f"correct_accusation_nonpositive_score:{score}")
    if not has_accused:
        if score != 0.0:
            errs.append(f"no_accusation_nonzero_score:{score}")
        if correct:
            errs.append("no_accusation_marked_correct")
    if has_accused and not correct and score != -1.0:
        errs.append(f"wrong_accusation_score_not_minus_one:{score}")
    return errs


def evaluate_episode_data_rule(
    ep: dict[str, Any] | None,
    *,
    run_dir: Path | None = None,
    transcript_text: str | None = None,
    wall_cap_s: float | None = DEFAULT_WALL_CAP_S,
    allow_fake: bool = False,
) -> dict[str, Any]:
    if ep is None or not isinstance(ep, dict):
        return {
            "ok": False,
            "timeout": False,
            "error": True,
            "wall_cap": False,
            "valid_false": False,
            "reasons": ["missing_episode"],
        }

    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    reasons: list[str] = []
    is_timeout = False
    is_error = False
    is_wall_cap = False
    is_valid_false = False

    if ep.get("valid") is False or meta.get("valid") is False:
        is_valid_false = True
        reasons.append("valid_false")

    rc = meta.get("rc")
    end_reason = str(ep.get("end_reason") or "")
    err_str = str(meta.get("error") or ep.get("error") or "")
    err_low = err_str.lower()

    seed_val = int(ep.get("seed", -1))
    tr_txt = transcript_text if transcript_text is not None else find_transcript_text(run_dir, seed_val)

    if (
        rc == "timeout"
        or end_reason == "timeout"
        or "timeout" in err_low
        or "timed out" in err_low
        or ("--- stderr\nTIMEOUT" in tr_txt)
    ):
        is_timeout = True
        reasons.append("timeout")

    wall_raw = meta.get("wall_s", ep.get("wall_s"))
    wall_s = float(wall_raw) if _is_finite_num(wall_raw) else None
    cap_raw = meta.get("timeout_s", meta.get("wall_cap_s"))
    eff_cap = float(cap_raw) if _is_finite_num(cap_raw) else wall_cap_s

    if (
        end_reason in ("wall_cap", "wall-cap")
        or rc in ("wall_cap", "wall-cap")
        or meta.get("wall_cap") is True
        or "wall_cap" in err_low
        or "wall-cap" in err_low
        or "wall cap" in err_low
    ):
        is_wall_cap = True
        reasons.append("wall_cap")
    elif eff_cap is not None and wall_s is not None and wall_s >= float(eff_cap):
        is_wall_cap = True
        reasons.append(f"wall_cap:wall_s={wall_s}>={float(eff_cap)}")

    if end_reason == "error":
        is_error = True
        reasons.append("end_reason_error")
    if err_str and not is_timeout and not is_wall_cap:
        is_error = True
        reasons.append(f"error:{err_str[:120]}")
    if rc not in (None, 0, "timeout", "wall_cap", "wall-cap"):
        is_error = True
        reasons.append(f"nonzero_rc:{rc}")
    if not allow_fake and (bool(ep.get("fake", False)) or bool(meta.get("fake", False))):
        is_error = True
        reasons.append("fake_episode_disallowed")

    steps = ep.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        is_error = True
        reasons.append("zero_steps")

    if tr_txt and end_reason != "accused" and empty_final_response(tr_txt):
        is_error = True
        reasons.append("empty_model_response")

    inv_errs = check_score_invariants(ep)
    if inv_errs:
        is_error = True
        reasons.extend(inv_errs)

    ok = not (is_timeout or is_error or is_wall_cap or is_valid_false)
    return {
        "ok": ok,
        "timeout": is_timeout,
        "error": is_error,
        "wall_cap": is_wall_cap,
        "valid_false": is_valid_false,
        "reasons": reasons,
    }


def replay_and_verify_episodes(
    episodes: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    ordered_seeds = sorted(episodes)
    if not ordered_seeds:
        return (
            {
                "script": "scripts/verify_replay.py",
                "verified": 0,
                "total": 0,
                "rc": 0,
                "pass": True,
                "failed_seeds": [],
            },
            {},
        )

    per_seed_replay: dict[int, dict[str, Any]] = {}
    failed_seeds: list[int] = []

    tmp_base = Path("/tmp/opencode") if Path("/tmp/opencode").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="v16-replay-", dir=str(tmp_base) if tmp_base else None) as td:
        ep_path = Path(td) / "episodes.jsonl"
        lines: list[str] = []
        for s in ordered_seeds:
            ep = dict(episodes[s])
            meta = dict(ep.get("meta") or {})
            meta["valid"] = True
            ep["meta"] = meta
            lines.append(json.dumps(ep, default=str))

            env = Env(ep["tier"], int(ep["seed"]))
            for st in ep.get("steps") or []:
                if env.done:
                    break
                env.call(st["tool"], st.get("args") or {})
            rep_res = env.result("replay")
            rep_check = verify_replay.replay_episode(ep)
            v_val = round(float(env.V), 6)
            match = (
                abs(float(rep_check["score"]) - float(ep["score"])) < 1e-9
                and rep_check["accused"] == ep.get("accused")
                and bool(rep_check["correct"]) == bool(ep.get("correct"))
                and abs(float(rep_res.score) - float(ep["score"])) < 1e-9
            )
            if not match:
                failed_seeds.append(s)
            per_seed_replay[s] = {
                "ok": match,
                "replay_score": round(float(rep_check["score"]), 6),
                "replay_accused": rep_check["accused"],
                "replay_correct": bool(rep_check["correct"]),
                "replay_final_day": int(rep_check["final_day"]),
                "env_v_at_end": v_val,
            }

        ep_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = int(verify_replay.main([str(ep_path)]))
        out_txt = buf.getvalue()

    expected_marker = f"{len(ordered_seeds)}/{len(ordered_seeds)} episodes replay-verified"
    script_ok = (rc == 0) and (expected_marker in out_txt) and not failed_seeds
    verified_count = len(ordered_seeds) - len(failed_seeds)
    return (
        {
            "script": "scripts/verify_replay.py",
            "verified": verified_count,
            "total": len(ordered_seeds),
            "rc": rc,
            "pass": bool(script_ok),
            "failed_seeds": failed_seeds,
        },
        per_seed_replay,
    )


def compute_posterior_and_luck(
    ep: dict[str, Any],
    fallback_v: float | None = None,
) -> tuple[float | None, float]:
    if not ep.get("accused"):
        return None, 0.0
    ep_obj = to_result(ep)
    try:
        p_val = audit_episode(ep_obj).get("p_accused")
    except Exception:
        p_val = None
    if p_val is None:
        params = tier_params_for_episode(ep_obj.tier, ep_obj.steps)
        sp = SolverPolicy(params)
        sp.obs.employees = [f"e{k:02d}" for k in range(params.n_employees)]
        for idx, st in enumerate(ep_obj.steps):
            if st.tool == "accuse":
                for prev in ep_obj.steps[sp.seen:idx]:
                    sp._ingest(prev)
                sp.seen = idx
                post = sp.belief()
                p_val = round(post.get(st.args.get("employee"), 0.0), 3) if post else None
                break
        if p_val is None:
            p_val = round(1.0 / max(1, params.n_employees), 3)
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    v_raw = meta.get("V", meta.get("V_final", fallback_v))
    if v_raw is None:
        v_raw = float(ep["score"]) if ep.get("correct") else 1.0
    p_f = float(p_val)
    v_f = float(v_raw)
    return p_f, p_f * v_f - (1.0 - p_f)


def _ep_obj_to_dict(r: Any, agent_name: str = "solver") -> dict[str, Any]:
    return {
        "tier": r.tier,
        "seed": int(r.seed),
        "agent": agent_name,
        "score": float(r.score),
        "correct": bool(r.correct),
        "accused": r.accused,
        "final_day": int(r.final_day),
        "end_reason": r.end_reason,
        "steps": [
            {"t": st.t, "day": st.day, "tool": st.tool, "args": st.args, "result": st.result}
            for st in r.steps
        ],
        "meta": dict(r.meta or {}, V=float(r.score) if r.correct else None, valid=True, rc=0),
    }


def load_committed_solver(tier: str, seeds: list[int], reference_dir: Path) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    if not reference_dir.is_dir():
        return out
    wanted = set(seeds)
    for ep_file in sorted(reference_dir.glob(f"solver-{tier}-*/episodes.jsonl")):
        for line in ep_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            s = int(ep["seed"])
            if s in wanted and ep.get("agent") == "solver" and ep.get("tier") == tier:
                out[s] = ep
    return out


def verify_baselines_and_solver(
    tier: str,
    seeds: list[int],
    v16_provider: str,
    reference_dir: Path,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    prev_offline = os.environ.get("CANARY_OFFLINE")
    os.environ["CANARY_OFFLINE"] = "1"
    check_spec = template_social_spec(v16_provider)
    try:
        committed_sol = load_committed_solver(tier, seeds, reference_dir)
        solver_eps: dict[int, dict[str, Any]] = {}
        solver_v16_scores: dict[int, float] = {}
        solver_v16_accused: dict[int, str | None] = {}
        dn_v14: list[float] = []
        dn_v16: list[float] = []
        se_v14: list[float] = []
        se_v16: list[float] = []

        for s in seeds:
            r_dn14 = run_episode(make_env(tier, s, "template"), BASELINES["do_nothing"](seed=s))
            r_dn16 = run_episode(make_env(tier, s, check_spec), BASELINES["do_nothing"](seed=s))
            r_se14 = run_episode(make_env(tier, s, "template"), BASELINES["stop_early"](seed=s))
            r_se16 = run_episode(make_env(tier, s, check_spec), BASELINES["stop_early"](seed=s))
            dn_v14.append(float(r_dn14.score))
            dn_v16.append(float(r_dn16.score))
            se_v14.append(float(r_se14.score))
            se_v16.append(float(r_se16.score))

            live_s14 = _ep_obj_to_dict(run_episode(make_env(tier, s, "template"), SolverPolicy()))
            live_s16 = _ep_obj_to_dict(run_episode(make_env(tier, s, check_spec), SolverPolicy()))
            base_s14 = committed_sol.get(s, live_s14)
            if s in committed_sol:
                if abs(float(base_s14["score"]) - float(live_s14["score"])) >= 1e-9 or base_s14.get("accused") != live_s14.get("accused"):
                    raise ValueError(f"committed solver mismatch against live v1.4 solver on seed {s}")
            solver_eps[s] = base_s14
            solver_v16_scores[s] = float(live_s16["score"])
            solver_v16_accused[s] = live_s16.get("accused")

        sol_replay_summary, sol_replay_map = replay_and_verify_episodes(solver_eps)
        for s, ep in solver_eps.items():
            meta = dict(ep.get("meta") or {})
            if meta.get("V") is None and meta.get("V_final") is None and s in sol_replay_map:
                meta["V_final"] = sol_replay_map[s]["env_v_at_end"]
            ep["meta"] = meta

        exact_match = all(
            abs(float(solver_eps[s]["score"]) - solver_v16_scores[s]) < 1e-9
            and solver_eps[s].get("accused") == solver_v16_accused[s]
            for s in seeds
        )
        dn_zero = all(x == 0.0 for x in dn_v14) and all(x == 0.0 for x in dn_v16)
        se_zero = all(x == 0.0 for x in se_v14) and all(x == 0.0 for x in se_v16)
        n = max(1, len(seeds))
        checks = {
            "v16_check_provider": check_spec,
            "solver_v14_mean": round(sum(float(solver_eps[s]["score"]) for s in seeds) / n, 6),
            "solver_v16_mean": round(sum(solver_v16_scores[s] for s in seeds) / n, 6),
            "solver_exact_match": bool(exact_match),
            "solver_replay_verified": bool(sol_replay_summary["pass"]),
            "do_nothing_v14_mean": round(sum(dn_v14) / n, 6),
            "do_nothing_v14_max": round(max(dn_v14) if dn_v14 else 0.0, 6),
            "do_nothing_v16_mean": round(sum(dn_v16) / n, 6),
            "do_nothing_v16_max": round(max(dn_v16) if dn_v16 else 0.0, 6),
            "do_nothing_zero": bool(dn_zero),
            "stop_early_v14_mean": round(sum(se_v14) / n, 6),
            "stop_early_v14_max": round(max(se_v14) if se_v14 else 0.0, 6),
            "stop_early_v16_mean": round(sum(se_v16) / n, 6),
            "stop_early_v16_max": round(max(se_v16) if se_v16 else 0.0, 6),
            "stop_early_zero": bool(se_zero),
        }
        return checks, solver_eps
    finally:
        if prev_offline is None:
            os.environ.pop("CANARY_OFFLINE", None)
        else:
            os.environ["CANARY_OFFLINE"] = prev_offline


def load_primary_v14(
    v14_dir: Path,
    tier: str,
    seeds: list[int],
    allow_fake: bool = False,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    tier_dir = v14_dir / tier if (v14_dir / tier / "episodes.jsonl").is_file() else v14_dir
    ep_file = tier_dir / "episodes.jsonl"
    if not ep_file.is_file():
        raise FileNotFoundError(f"primary v1.4 episodes.jsonl not found at {ep_file}")

    wanted = set(seeds)
    valid_eps: dict[int, dict[str, Any]] = {}
    counts = {"timeouts": 0, "errors": 0, "wall_cap": 0, "valid_false": 0}
    violations: list[dict[str, Any]] = []

    for line in ep_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        s = int(ep["seed"])
        if s not in wanted or ep.get("tier") != tier:
            continue
        dr = evaluate_episode_data_rule(ep, run_dir=tier_dir, wall_cap_s=None, allow_fake=allow_fake)
        if not dr["ok"]:
            counts["timeouts"] += int(dr["timeout"])
            counts["errors"] += int(dr["error"])
            counts["wall_cap"] += int(dr["wall_cap"])
            counts["valid_false"] += int(dr["valid_false"])
            violations.append({"seed": s, "reasons": dr["reasons"], "source": str(ep_file)})
            continue
        valid_eps[s] = ep

    missing = sorted(wanted - set(valid_eps))
    summary = {
        "source": str(ep_file),
        "timeouts": counts["timeouts"],
        "errors": counts["errors"],
        "wall_cap": counts["wall_cap"],
        "valid_false": counts["valid_false"],
        "missing_seeds": missing,
        "violations": violations,
        "pass": (
            counts["timeouts"] == 0
            and counts["errors"] == 0
            and counts["wall_cap"] == 0
            and counts["valid_false"] == 0
            and not missing
        ),
    }
    return valid_eps, summary


def _extract_episodes_from_path(path: Path, tier: str) -> list[tuple[dict[str, Any], Path | None]]:
    out: list[tuple[dict[str, Any], Path | None]] = []
    if path.is_file():
        if path.suffix == ".jsonl":
            for ln in path.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    obj = json.loads(ln)
                    if isinstance(obj, dict) and obj.get("tier") == tier and "seed" in obj and "steps" in obj:
                        out.append((obj, path.parent))
        elif path.suffix == ".json":
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return out
            if isinstance(obj, dict) and obj.get("tier") == tier and "seed" in obj and "steps" in obj:
                out.append((obj, path.parent))
        return out

    if not path.is_dir():
        return out

    rf = path / "RUNNING.json"
    if rf.is_file():
        try:
            rinfo = json.loads(rf.read_text(encoding="utf-8"))
            if pid_alive(int(rinfo.get("pid", 0)), str(path)):
                return out
        except Exception:
            pass

    ep_jsonl = path / "episodes.jsonl"
    if ep_jsonl.is_file():
        for ln in ep_jsonl.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                obj = json.loads(ln)
                if isinstance(obj, dict) and obj.get("tier") == tier and "seed" in obj and "steps" in obj:
                    out.append((obj, path))
        return out

    for name in ("episode.json",):
        f = path / name
        if f.is_file():
            out.extend(_extract_episodes_from_path(f, tier))
            if out:
                return out

    for sub in sorted(path.glob("*.jsonl")) + sorted(path.glob("seed_*.json")):
        if sub.name == "invalid_attempts.jsonl":
            continue
        out.extend(_extract_episodes_from_path(sub, tier))
    return out


def _scan_in_flight_staging(staging_dirs: list[Path], tier: str, seeds: set[int]) -> dict[int, str]:
    in_flight: dict[int, str] = {}
    for stg in staging_dirs:
        if not stg.is_dir():
            continue
        for slug_dir in sorted(stg.iterdir()):
            if not slug_dir.is_dir() or not slug_dir.name.startswith("v1.6"):
                continue
            tier_dir = slug_dir / tier
            if not tier_dir.is_dir():
                continue
            for s_dir in sorted(tier_dir.iterdir()):
                if not s_dir.is_dir() or not s_dir.name.isdigit():
                    continue
                s = int(s_dir.name)
                if s not in seeds:
                    continue
                rf = s_dir / "RUNNING.json"
                if rf.is_file():
                    try:
                        rinfo = json.loads(rf.read_text(encoding="utf-8"))
                        if pid_alive(int(rinfo.get("pid", 0)), str(s_dir)):
                            in_flight[s] = str(s_dir)
                    except Exception:
                        pass
    return in_flight


def _git_show_text(repo_root: Path, ref: str, rel_path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _fmt_score_pm_ci(mean_val: float | None, ci_val: float | None, nd: int = 3) -> str:
    if mean_val is None:
        return "n/a"
    if ci_val is None:
        return f"{mean_val:.{nd}f}"
    return f"{mean_val:.{nd}f} +/- {ci_val:.{nd}f}"


def discover_v16_shards(
    *,
    v16_root: Path,
    tier: str,
    seeds: list[int],
    v16_provider: str = DEFAULT_V16_PROVIDER,
    staging_globs: list[str],
    worker_wt_glob: str | None,
    poll_branches: list[str],
    wall_cap_s: float = DEFAULT_WALL_CAP_S,
    allow_fake: bool = False,
    materialize_shards: bool = False,
) -> tuple[dict[int, dict[str, Any]], dict[int, str], dict[str, Any], dict[str, dict[int, tuple[dict[str, Any], str]]]]:
    wanted = set(seeds)
    valid_eps: dict[int, dict[str, Any]] = {}
    sources: dict[int, str] = {}
    extra_variants: dict[str, dict[int, tuple[dict[str, Any], str]]] = {}

    safe_prov = re.sub(r"[^A-Za-z0-9_.-]+", "_", v16_provider)
    prov_tail = v16_provider.split(":", 1)[-1]

    primary_counts = {"timeouts": 0, "errors": 0, "wall_cap": 0, "valid_false": 0}
    primary_violations: list[dict[str, Any]] = []
    staging_excluded: list[dict[str, Any]] = []

    for s in seeds:
        primary_candidates = (
            v16_root / f"{tier}-s{s}",
            v16_root / f"s{s}",
            v16_root / tier / str(s),
            v16_root / f"{tier}-s{s}.jsonl",
            v16_root / f"{tier}-s{s}.json",
        )
        for cand in primary_candidates:
            for ep, rdir in _extract_episodes_from_path(cand, tier):
                if int(ep.get("seed", -1)) != s:
                    continue
                dr = evaluate_episode_data_rule(ep, run_dir=rdir, wall_cap_s=wall_cap_s, allow_fake=allow_fake)
                if not dr["ok"]:
                    primary_counts["timeouts"] += int(dr["timeout"])
                    primary_counts["errors"] += int(dr["error"])
                    primary_counts["wall_cap"] += int(dr["wall_cap"])
                    primary_counts["valid_false"] += int(dr["valid_false"])
                    primary_violations.append({"seed": s, "reasons": dr["reasons"], "source": str(cand)})
                else:
                    valid_eps[s] = ep
                    sources[s] = str(cand)
        if s not in valid_eps and (v16_root / "episodes.jsonl").is_file():
            for ep, rdir in _extract_episodes_from_path(v16_root / "episodes.jsonl", tier):
                if int(ep.get("seed", -1)) != s:
                    continue
                dr = evaluate_episode_data_rule(ep, run_dir=rdir, wall_cap_s=wall_cap_s, allow_fake=allow_fake)
                if not dr["ok"]:
                    primary_counts["timeouts"] += int(dr["timeout"])
                    primary_counts["errors"] += int(dr["error"])
                    primary_counts["wall_cap"] += int(dr["wall_cap"])
                    primary_counts["valid_false"] += int(dr["valid_false"])
                    primary_violations.append(
                        {"seed": s, "reasons": dr["reasons"], "source": str(v16_root / "episodes.jsonl")}
                    )
                else:
                    valid_eps[s] = ep
                    sources[s] = str(v16_root / "episodes.jsonl")

    if worker_wt_glob:
        for wt_str in sorted(glob.glob(worker_wt_glob)):
            wt = Path(wt_str)
            if wt.resolve() == REPO_ROOT.resolve():
                continue
            wt_v16 = wt / "results" / "v16_social" / "opencode_v16"
            if not wt_v16.is_dir():
                continue
            for s in seeds:
                if s in valid_eps:
                    continue
                cand = wt_v16 / f"{tier}-s{s}"
                for ep, rdir in _extract_episodes_from_path(cand, tier):
                    if int(ep.get("seed", -1)) != s:
                        continue
                    dr = evaluate_episode_data_rule(ep, run_dir=rdir, wall_cap_s=wall_cap_s, allow_fake=allow_fake)
                    if dr["ok"]:
                        valid_eps[s] = ep
                        sources[s] = str(cand)
                    else:
                        staging_excluded.append({"seed": s, "reasons": dr["reasons"], "source": str(cand)})

    staging_dirs: list[Path] = []
    for pat in staging_globs:
        for m in sorted(glob.glob(pat)):
            p = Path(m)
            if p.is_dir() and p not in staging_dirs:
                staging_dirs.append(p)

    in_flight = _scan_in_flight_staging(staging_dirs, tier, wanted)
    inv_seed_rx = re.compile(rf"^v1\.6.*-{re.escape(tier)}-(\d+)-")

    for stg in staging_dirs:
        inv_dir = stg / "invalid"
        if inv_dir.is_dir():
            for inv_item in sorted(inv_dir.glob(f"v1.6*-{tier}-*")):
                inv_txt = inv_item / "INVALID.txt"
                reason_txt = inv_txt.read_text(encoding="utf-8", errors="replace").strip() if inv_txt.is_file() else "invalid"
                m_seed = inv_seed_rx.match(inv_item.name)
                entry: dict[str, Any] = {"dir": inv_item.name, "reason": reason_txt[:160], "source": str(stg)}
                if m_seed:
                    entry["seed"] = int(m_seed.group(1))
                staging_excluded.append(entry)

        for slug_dir in sorted(stg.iterdir()):
            if not slug_dir.is_dir():
                continue
            if slug_dir.name.startswith("v1.6"):
                is_primary_slug = (
                    slug_dir.name == "v1.6"
                    or slug_dir.name == f"v1.6-{safe_prov}"
                    or slug_dir.name.startswith(f"v1.6-{safe_prov}-")
                )
                for s in seeds:
                    s_dir = slug_dir / tier / str(s)
                    for ep, rdir in _extract_episodes_from_path(s_dir, tier):
                        if int(ep.get("seed", -1)) != s:
                            continue
                        dr = evaluate_episode_data_rule(ep, run_dir=rdir, wall_cap_s=wall_cap_s, allow_fake=allow_fake)
                        if dr["ok"]:
                            if is_primary_slug:
                                if s not in valid_eps:
                                    valid_eps[s] = ep
                                    sources[s] = str(s_dir)
                            else:
                                var_map = extra_variants.setdefault(slug_dir.name, {})
                                if s not in var_map:
                                    var_map[s] = (ep, str(s_dir))
                        else:
                            staging_excluded.append({"seed": s, "reasons": dr["reasons"], "source": str(s_dir)})
            elif slug_dir.name == "opencode":
                opencode_vars = [
                    vd for vd in sorted(slug_dir.iterdir())
                    if vd.is_dir() and vd.name != "v0_v14_control"
                ]
                for var_dir in opencode_vars:
                    t_dir = var_dir / tier
                    ep_f = t_dir / "episodes.jsonl"
                    if not ep_f.is_file():
                        continue
                    is_primary_var = var_dir.name in (v16_provider, prov_tail, safe_prov) or (
                        len(opencode_vars) == 1 and not valid_eps
                    )
                    for ep, rdir in _extract_episodes_from_path(ep_f, tier):
                        s = int(ep.get("seed", -1))
                        if s not in wanted:
                            continue
                        dr = evaluate_episode_data_rule(ep, run_dir=t_dir, wall_cap_s=wall_cap_s, allow_fake=allow_fake)
                        src_tag = f"{ep_f}:seed={s}"
                        if dr["ok"]:
                            if is_primary_var:
                                if s not in valid_eps:
                                    valid_eps[s] = ep
                                    sources[s] = src_tag
                            else:
                                var_map = extra_variants.setdefault(f"v16:{var_dir.name}", {})
                                if s not in var_map:
                                    var_map[s] = (ep, src_tag)
                        else:
                            staging_excluded.append({"seed": s, "reasons": dr["reasons"], "source": str(ep_f)})

    for ref in poll_branches:
        if len(valid_eps) == len(seeds):
            break
        for s in seeds:
            if s in valid_eps:
                continue
            rel_base = f"results/v16_social/opencode_v16/{tier}-s{s}"
            raw_jsonl = _git_show_text(REPO_ROOT, ref, f"{rel_base}/episodes.jsonl")
            if not raw_jsonl:
                continue
            tr_txt = (
                _git_show_text(REPO_ROOT, ref, f"{rel_base}/transcripts/{s}.txt")
                or _git_show_text(REPO_ROOT, ref, f"{rel_base}/transcripts/seed_{s}.txt")
                or ""
            )
            for ln in raw_jsonl.splitlines():
                if not ln.strip():
                    continue
                ep = json.loads(ln)
                if int(ep.get("seed", -1)) != s or ep.get("tier") != tier:
                    continue
                dr = evaluate_episode_data_rule(
                    ep,
                    transcript_text=tr_txt,
                    wall_cap_s=wall_cap_s,
                    allow_fake=allow_fake,
                )
                if dr["ok"]:
                    valid_eps[s] = ep
                    sources[s] = f"{ref}:{rel_base}/episodes.jsonl"
                else:
                    staging_excluded.append(
                        {"seed": s, "reasons": dr["reasons"], "source": f"{ref}:{rel_base}/episodes.jsonl"}
                    )

    if materialize_shards:
        for s, ep in sorted(valid_eps.items()):
            dst_dir = v16_root / f"{tier}-s{s}"
            dst_file = dst_dir / "episodes.jsonl"
            if not dst_file.is_file():
                clean_ep = dict(ep)
                clean_meta = dict(clean_ep.get("meta") or {})
                clean_meta.pop("ledger_events", None)
                clean_ep["meta"] = clean_meta
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst_file.write_text(json.dumps(clean_ep, sort_keys=True, default=str) + "\n", encoding="utf-8")

    missing = [s for s in seeds if s not in valid_eps]
    excluded_seeds = sorted({
        int(item["seed"])
        for item in staging_excluded
        if isinstance(item.get("seed"), int) and int(item["seed"]) in wanted and int(item["seed"]) not in valid_eps
    })
    v16_data_rule = {
        "timeouts": primary_counts["timeouts"],
        "errors": primary_counts["errors"],
        "wall_cap": primary_counts["wall_cap"],
        "valid_false": primary_counts["valid_false"],
        "violations": primary_violations,
        "staging_excluded_attempts_count": len(staging_excluded),
        "staging_excluded_attempts": staging_excluded[:50],
        "excluded_seeds": excluded_seeds,
        "in_flight_seeds": sorted(s for s in in_flight if s not in valid_eps),
        "in_flight_paths": {str(s): in_flight[s] for s in sorted(in_flight) if s not in valid_eps},
        "missing_seeds": missing,
        "pass": (
            primary_counts["timeouts"] == 0
            and primary_counts["errors"] == 0
            and primary_counts["wall_cap"] == 0
            and primary_counts["valid_false"] == 0
        ),
    }
    return valid_eps, sources, v16_data_rule, extra_variants


def summarize_arm_metrics(
    *,
    arm_name: str,
    provider_label: str,
    tier: str,
    planned_seeds: list[int],
    episodes: dict[int, dict[str, Any]],
    solver_eps: dict[int, dict[str, Any]],
    replay_map: dict[int, dict[str, Any]],
    sources: dict[int, str],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    rng_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    valid_seeds = [s for s in planned_seeds if s in episodes and replay_map.get(s, {}).get("ok", False)]
    n_valid = len(valid_seeds)

    raw_scores: list[float] = []
    sol_scores: list[float] = []
    luck_scores: list[float] = []
    sol_luck_scores: list[float] = []
    p_vals: list[float] = []
    acc_days: list[int] = []
    per_seed_rows: list[dict[str, Any]] = []

    for s in valid_seeds:
        ep = episodes[s]
        sol = solver_eps[s]
        rep_info = replay_map[s]
        p_acc_val, luck_val = compute_posterior_and_luck(ep, fallback_v=rep_info.get("env_v_at_end"))
        _, sol_luck_val = compute_posterior_and_luck(sol, fallback_v=float(sol["score"]) if sol.get("correct") else None)

        sc = float(ep["score"])
        ssc = float(sol["score"])
        raw_scores.append(sc)
        sol_scores.append(ssc)
        luck_scores.append(float(luck_val))
        sol_luck_scores.append(float(sol_luck_val))

        if ep.get("accused"):
            acc_days.append(int(ep.get("final_day") or 0))
            if p_acc_val is not None:
                p_vals.append(float(p_acc_val))

        meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
        wall_raw = meta.get("wall_s")
        wall_val = round(float(wall_raw), 2) if _is_finite_num(wall_raw) else None
        seed_ratio = (sc / ssc) if ssc > 0.0 else None

        per_seed_rows.append({
            "seed": int(s),
            "owner": SHARD_OWNERS.get(int(s), "unassigned"),
            "source": sources.get(int(s), ""),
            "score": round(sc, 6),
            "solver_score": round(ssc, 6),
            "ratio_of_solver": _round_or_none(seed_ratio, 6),
            "pct_of_solver": _round_or_none(seed_ratio * 100.0 if seed_ratio is not None else None, 4),
            "correct": bool(ep.get("correct")),
            "accused": ep.get("accused"),
            "final_day": int(ep.get("final_day") or 0),
            "end_reason": str(ep.get("end_reason") or ""),
            "step_count": len(ep.get("steps") or []),
            "wall_s": wall_val,
            "p_accused": _round_or_none(p_acc_val, 6),
            "luck_adjusted_score": round(float(luck_val), 6),
            "solver_luck_adjusted_score": round(float(sol_luck_val), 6),
            "replay_verified": bool(rep_info["ok"]),
        })

    if n_valid > 0:
        m_raw, ci_raw_val = mean_ci(raw_scores)
        ci_raw = ci_raw_val if n_valid >= 2 else None
        b_lo, b_hi = boot_mean_ci(raw_scores, resamples=resamples, rng_seed=rng_seed)
        m_sol = sum(sol_scores) / n_valid
        raw_ratio = (m_raw / m_sol) if m_sol > 0.0 else None
        r_lo, r_hi = boot_ratio(raw_scores, sol_scores, resamples=resamples, rng_seed=rng_seed)

        diffs = [a - b for a, b in zip(raw_scores, sol_scores)]
        diff_m, diff_ci_val = mean_ci(diffs)
        diff_ci = diff_ci_val if n_valid >= 2 else None

        m_luck = sum(luck_scores) / n_valid
        m_sol_luck = sum(sol_luck_scores) / n_valid
        luck_ratio = (m_luck / m_sol_luck) if m_sol_luck > 0.0 else None
        l_lo, l_hi = boot_ratio(luck_scores, sol_luck_scores, resamples=resamples, rng_seed=rng_seed)

        accuracy = sum(1 for r in per_seed_rows if r["correct"]) / n_valid
        accused_rate = sum(1 for r in per_seed_rows if r["accused"]) / n_valid
        mean_acc_day = (sum(acc_days) / len(acc_days)) if acc_days else None
        mean_p = (sum(p_vals) / len(p_vals)) if p_vals else None
    else:
        m_raw = ci_raw = b_lo = b_hi = m_sol = raw_ratio = r_lo = r_hi = None
        diff_m = diff_ci = m_luck = m_sol_luck = luck_ratio = l_lo = l_hi = None
        accuracy = accused_rate = mean_acc_day = mean_p = None

    return {
        "arm": arm_name,
        "provider": provider_label,
        "tier": tier,
        "n_planned": len(planned_seeds),
        "n_valid": n_valid,
        "planned_seeds": [int(s) for s in planned_seeds],
        "valid_seeds": [int(s) for s in valid_seeds],
        "missing_seeds": [int(s) for s in planned_seeds if s not in valid_seeds],
        "raw_score_mean": _round_or_none(m_raw),
        "raw_score_ci95": _round_or_none(ci_raw),
        "raw_score_boot_ci95": [_round_or_none(b_lo), _round_or_none(b_hi)],
        "solver_raw_score_mean": _round_or_none(m_sol),
        "raw_ratio_of_solver": _round_or_none(raw_ratio),
        "raw_pct_of_solver": _round_or_none(raw_ratio * 100.0 if raw_ratio is not None else None, 4),
        "raw_pct_of_solver_ci95": [
            _round_or_none(r_lo * 100.0 if r_lo is not None else None, 4),
            _round_or_none(r_hi * 100.0 if r_hi is not None else None, 4),
        ],
        "paired_diff_vs_solver_mean": _round_or_none(diff_m),
        "paired_diff_vs_solver_ci95": _round_or_none(diff_ci),
        "luck_adjusted_score_mean": _round_or_none(m_luck),
        "solver_luck_adjusted_score_mean": _round_or_none(m_sol_luck),
        "luck_adjusted_ratio_of_solver": _round_or_none(luck_ratio),
        "luck_adjusted_pct_of_solver": _round_or_none(luck_ratio * 100.0 if luck_ratio is not None else None, 4),
        "luck_adjusted_pct_of_solver_ci95": [
            _round_or_none(l_lo * 100.0 if l_lo is not None else None, 4),
            _round_or_none(l_hi * 100.0 if l_hi is not None else None, 4),
        ],
        "accuracy": _round_or_none(accuracy),
        "accused_rate": _round_or_none(accused_rate),
        "mean_accuse_day": _round_or_none(mean_acc_day, 4),
        "mean_p_accused": _round_or_none(mean_p, 4),
        "per_seed": per_seed_rows,
    }


def compute_paired_gate(
    *,
    planned_seeds: list[int],
    v14_summary: dict[str, Any],
    v16_summary: dict[str, Any],
    solver_eps: dict[int, dict[str, Any]],
    ref_checks: dict[str, Any],
    v14_data_rule: dict[str, Any],
    v16_data_rule: dict[str, Any],
    v14_replay: dict[str, Any],
    v16_replay: dict[str, Any],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    rng_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    by_s14 = {int(r["seed"]): r for r in v14_summary["per_seed"]}
    by_s16 = {int(r["seed"]): r for r in v16_summary["per_seed"]}
    shared = [s for s in planned_seeds if s in by_s14 and s in by_s16]

    data_rule_pass = bool(v14_data_rule["pass"] and v16_data_rule["pass"])
    replay_pass = bool(v14_replay["pass"] and v16_replay["pass"])
    baselines_zero = bool(ref_checks["do_nothing_zero"] and ref_checks["stop_early_zero"])
    solver_calibrated = bool(ref_checks["solver_exact_match"] and ref_checks["solver_replay_verified"])
    complete = len(shared) == len(planned_seeds)

    if shared:
        n_sh = len(shared)
        f14 = [float(by_s14[s]["score"]) for s in shared]
        f16 = [float(by_s16[s]["score"]) for s in shared]
        sol = [float(solver_eps[s]["score"]) for s in shared]

        l14 = [float(by_s14[s]["luck_adjusted_score"]) for s in shared]
        l16 = [float(by_s16[s]["luck_adjusted_score"]) for s in shared]
        lsol = [float(by_s14[s]["solver_luck_adjusted_score"]) for s in shared]

        m14, ci14_val = mean_ci(f14)
        m16, ci16_val = mean_ci(f16)
        ci14 = ci14_val if n_sh >= 2 else None
        ci16 = ci16_val if n_sh >= 2 else None
        msol = sum(sol) / n_sh
        mlsol = sum(lsol) / n_sh

        r14 = (m14 / msol) if msol > 0.0 else None
        r16 = (m16 / msol) if msol > 0.0 else None
        r14_lo, r14_hi = boot_ratio(f14, sol, resamples=resamples, rng_seed=rng_seed)
        r16_lo, r16_hi = boot_ratio(f16, sol, resamples=resamples, rng_seed=rng_seed)
        dr_lo, dr_hi = boot_delta_ratio(f16, f14, sol, resamples=resamples, rng_seed=rng_seed)

        ml14 = sum(l14) / n_sh
        ml16 = sum(l16) / n_sh
        lr14 = (ml14 / mlsol) if mlsol > 0.0 else None
        lr16 = (ml16 / mlsol) if mlsol > 0.0 else None
        lr14_lo, lr14_hi = boot_ratio(l14, lsol, resamples=resamples, rng_seed=rng_seed)
        lr16_lo, lr16_hi = boot_ratio(l16, lsol, resamples=resamples, rng_seed=rng_seed)
        dlr_lo, dlr_hi = boot_delta_ratio(l16, l14, lsol, resamples=resamples, rng_seed=rng_seed)

        d_raw = [b - a for a, b in zip(f14, f16)]
        d_raw_m, d_raw_ci_val = mean_ci(d_raw)
        d_raw_ci = d_raw_ci_val if n_sh >= 2 else None
        d_luck = [b - a for a, b in zip(l14, l16)]
        d_luck_m, d_luck_ci_val = mean_ci(d_luck)
        d_luck_ci = d_luck_ci_val if n_sh >= 2 else None

        acc14 = sum(1 for s in shared if by_s14[s]["correct"]) / n_sh
        acc16 = sum(1 for s in shared if by_s16[s]["correct"]) / n_sh
        days14 = [int(by_s14[s]["final_day"]) for s in shared if by_s14[s]["accused"]]
        days16 = [int(by_s16[s]["final_day"]) for s in shared if by_s16[s]["accused"]]
        day14 = (sum(days14) / len(days14)) if days14 else None
        day16 = (sum(days16) / len(days16)) if days16 else None

        raw_below = bool(r14 is not None and r16 is not None and r16 < r14 - 1e-12)
        v16_higher: bool | None = bool(m16 > m14 + 1e-12)
        v16_equal: bool | None = bool(abs(m16 - m14) <= 1e-12)
        luck_below = bool(lr14 is not None and lr16 is not None and lr16 < lr14 - 1e-12)
        delta_raw_pp = ((r16 - r14) * 100.0) if (r14 is not None and r16 is not None) else None
        delta_luck_pp = ((lr16 - lr14) * 100.0) if (lr14 is not None and lr16 is not None) else None
        day_diff = (day16 - day14) if (day14 is not None and day16 is not None) else None
    else:
        m14 = ci14 = m16 = ci16 = msol = mlsol = None
        r14 = r16 = r14_lo = r14_hi = r16_lo = r16_hi = dr_lo = dr_hi = None
        ml14 = ml16 = lr14 = lr16 = lr14_lo = lr14_hi = lr16_lo = lr16_hi = dlr_lo = dlr_hi = None
        d_raw_m = d_raw_ci = d_luck_m = d_luck_ci = None
        acc14 = acc16 = day14 = day16 = delta_raw_pp = delta_luck_pp = day_diff = None
        raw_below = False
        v16_higher = None
        v16_equal = None
        luck_below = False

    ship_gate_pass = bool(
        complete
        and data_rule_pass
        and replay_pass
        and baselines_zero
        and solver_calibrated
        and raw_below
    )
    gate_met = bool(ship_gate_pass)

    if shared:
        r16_disp = f"{r16:.3f} ({r16 * 100.0:.1f}%)" if r16 is not None else "n/a"
        r14_disp = f"{r14:.3f} ({r14 * 100.0:.1f}%)" if r14 is not None else "n/a"
        if v16_higher:
            shared_direction_statement = (
                f"On shared valid seeds {shared} (n_valid={len(shared)}/{len(planned_seeds)}), "
                f"v1.6 scores HIGHER for Gemini than v1.4 on the same seeds "
                f"(gemini {m16:.3f} vs {m14:.3f}; solver {msol:.3f}; ratio {r16_disp} vs {r14_disp}). "
                f"The gate is NOT met."
            )
        elif v16_equal:
            shared_direction_statement = (
                f"On shared valid seeds {shared} (n_valid={len(shared)}/{len(planned_seeds)}), "
                f"v1.6 scores EQUAL to v1.4 for Gemini on the same seeds (v1.6 does NOT score higher than v1.4, "
                f"and does NOT drop below v1.4: gemini {m16:.3f} vs {m14:.3f}; solver {msol:.3f}; "
                f"ratio {r16_disp} vs {r14_disp}). The gate is NOT met."
            )
        elif gate_met:
            shared_direction_statement = (
                f"On shared valid seeds {shared} (n_valid={len(shared)}/{len(planned_seeds)}), "
                f"v1.6 does NOT score higher than v1.4; v1.6 scores LOWER for Gemini than v1.4 on the same seeds "
                f"(gemini {m16:.3f} vs {m14:.3f}; solver {msol:.3f}; ratio {r16_disp} vs {r14_disp}). "
                f"The gate IS met."
            )
        else:
            shared_direction_statement = (
                f"On shared valid seeds {shared} (n_valid={len(shared)}/{len(planned_seeds)}), "
                f"v1.6 does NOT score higher than v1.4 on completed shared seeds (v1.6 scores LOWER: "
                f"gemini {m16:.3f} vs {m14:.3f}; solver {msol:.3f}; ratio {r16_disp} vs {r14_disp}), "
                f"but the gate is NOT met."
            )
    else:
        shared_direction_statement = (
            f"No valid v1.6 episodes have completed on shared seeds yet (n_valid=0/{len(planned_seeds)}), "
            f"so paired v1.6 vs v1.4 Gemini direction on the same seeds is not yet observed; the gate is NOT met."
        )

    reasons: list[str] = []
    if not data_rule_pass:
        reasons.append("DATA RULE failed (nonzero timeout, error, wall-cap, or valid=False)")
    if not replay_pass:
        reasons.append("Replay verification failed in scripts/verify_replay.py")
    if not baselines_zero:
        reasons.append("Baseline check failed (do_nothing != 0.0 or stop_early != 0.0)")
    if not solver_calibrated:
        reasons.append("Solver calibration check failed (solver_v14 != solver_v16)")
    if not complete:
        missing = [s for s in planned_seeds if s not in shared]
        reasons.append(
            f"Gate NOT met: incomplete v1.6 shard set (n_valid={len(shared)}/{len(planned_seeds)}; missing seeds {missing})"
        )
    if shared and r14 is not None and r16 is not None and delta_raw_pp is not None:
        if v16_higher:
            reasons.append(
                f"Gate NOT met: on shared seeds {shared}, v1.6 scores HIGHER for Gemini than v1.4 "
                f"(ratio {r16:.3f} [{r16 * 100.0:.1f}%] vs {r14:.3f} [{r14 * 100.0:.1f}%], {delta_raw_pp:+.1f} pp)"
            )
        elif raw_below:
            reasons.append(
                f"On shared seeds {shared}, v1.6 raw ratio ({r16:.3f} [{r16 * 100.0:.1f}%]) is below v1.4 "
                f"({r14:.3f} [{r14 * 100.0:.1f}%]) by {delta_raw_pp:+.1f} pp"
            )
        else:
            reasons.append(
                f"Gate NOT met: on shared seeds {shared}, v1.6 raw ratio ({r16:.3f} [{r16 * 100.0:.1f}%]) "
                f"did NOT drop below v1.4 ({r14:.3f} [{r14 * 100.0:.1f}%])"
            )
    if shared and lr14 is not None and lr16 is not None and delta_luck_pp is not None:
        if luck_below:
            reasons.append(
                f"On shared seeds {shared}, v1.6 luck-adjusted % of solver ({lr16 * 100.0:.1f}%) is below v1.4 "
                f"({lr14 * 100.0:.1f}%) by {delta_luck_pp:+.1f} pp"
            )
        else:
            reasons.append(
                f"On shared seeds {shared}, v1.6 luck-adjusted % of solver ({lr16 * 100.0:.1f}%) is >= v1.4 "
                f"({lr14 * 100.0:.1f}%)"
            )

    verdict = "GATE MET / SHIP (PASS)" if gate_met else "GATE NOT MET / DO NOT SHIP"

    return {
        "planned_seeds": [int(s) for s in planned_seeds],
        "shared_seeds": [int(s) for s in shared],
        "n_planned": len(planned_seeds),
        "n_shared": len(shared),
        "complete": bool(complete),
        "solver_shared": {
            "raw_score_mean": _round_or_none(msol),
            "luck_adjusted_score_mean": _round_or_none(mlsol),
        },
        "v14_shared": {
            "raw_score_mean": _round_or_none(m14),
            "raw_score_ci95": _round_or_none(ci14),
            "raw_ratio_of_solver": _round_or_none(r14),
            "raw_pct_of_solver": _round_or_none(r14 * 100.0 if r14 is not None else None, 4),
            "raw_pct_of_solver_ci95": [
                _round_or_none(r14_lo * 100.0 if r14_lo is not None else None, 4),
                _round_or_none(r14_hi * 100.0 if r14_hi is not None else None, 4),
            ],
            "luck_adjusted_score_mean": _round_or_none(ml14),
            "luck_adjusted_pct_of_solver": _round_or_none(lr14 * 100.0 if lr14 is not None else None, 4),
            "luck_adjusted_pct_of_solver_ci95": [
                _round_or_none(lr14_lo * 100.0 if lr14_lo is not None else None, 4),
                _round_or_none(lr14_hi * 100.0 if lr14_hi is not None else None, 4),
            ],
            "accuracy": _round_or_none(acc14),
            "mean_accuse_day": _round_or_none(day14, 4),
        },
        "v16_shared": {
            "raw_score_mean": _round_or_none(m16),
            "raw_score_ci95": _round_or_none(ci16),
            "raw_ratio_of_solver": _round_or_none(r16),
            "raw_pct_of_solver": _round_or_none(r16 * 100.0 if r16 is not None else None, 4),
            "raw_pct_of_solver_ci95": [
                _round_or_none(r16_lo * 100.0 if r16_lo is not None else None, 4),
                _round_or_none(r16_hi * 100.0 if r16_hi is not None else None, 4),
            ],
            "luck_adjusted_score_mean": _round_or_none(ml16),
            "luck_adjusted_pct_of_solver": _round_or_none(lr16 * 100.0 if lr16 is not None else None, 4),
            "luck_adjusted_pct_of_solver_ci95": [
                _round_or_none(lr16_lo * 100.0 if lr16_lo is not None else None, 4),
                _round_or_none(lr16_hi * 100.0 if lr16_hi is not None else None, 4),
            ],
            "accuracy": _round_or_none(acc16),
            "mean_accuse_day": _round_or_none(day16, 4),
        },
        "delta_v16_minus_v14": {
            "raw_score_mean": _round_or_none(d_raw_m),
            "raw_score_ci95": _round_or_none(d_raw_ci),
            "raw_pct_points": _round_or_none(delta_raw_pp, 4),
            "raw_pct_points_ci95": [
                _round_or_none(dr_lo * 100.0 if dr_lo is not None else None, 4),
                _round_or_none(dr_hi * 100.0 if dr_hi is not None else None, 4),
            ],
            "luck_adjusted_score_mean": _round_or_none(d_luck_m),
            "luck_adjusted_score_ci95": _round_or_none(d_luck_ci),
            "luck_adjusted_pct_points": _round_or_none(delta_luck_pp, 4),
            "luck_adjusted_pct_points_ci95": [
                _round_or_none(dlr_lo * 100.0 if dlr_lo is not None else None, 4),
                _round_or_none(dlr_hi * 100.0 if dlr_hi is not None else None, 4),
            ],
            "accuracy_diff": _round_or_none((acc16 - acc14) if (acc14 is not None and acc16 is not None) else None),
            "mean_accuse_day_diff": _round_or_none(day_diff, 4),
        },
        "ship_gate": {
            "complete": bool(complete),
            "data_rule_pass": bool(data_rule_pass),
            "replay_verified_pass": bool(replay_pass),
            "baselines_zero_pass": bool(baselines_zero),
            "solver_calibrated_pass": bool(solver_calibrated),
            "raw_below_v14": bool(raw_below),
            "v16_higher_than_v14_on_shared": v16_higher,
            "v16_equal_to_v14_on_shared": v16_equal,
            "luck_adjusted_below_v14": bool(luck_below),
            "gate_met": bool(gate_met),
            "ship_gate_pass": bool(ship_gate_pass),
            "verdict": verdict,
            "shared_direction_statement": shared_direction_statement,
            "reasons": reasons,
        },
    }


def assert_clean_payload(payload: Any) -> str:
    def _walk(obj: Any, path: str = "root") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden hygiene key {ks!r} at {path}.{ks}")
                _walk(v, f"{path}.{ks}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")
        elif isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError(f"non-finite float at {path}: {obj!r}")

    _walk(payload)
    dumped = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=True)
    for rx in KEY_PATTERNS:
        if rx.search(dumped):
            raise ValueError("secret key pattern detected in serialized output")
    if "\u2014" in dumped or "\u2013" in dumped:
        raise ValueError("dash hygiene violation in serialized output")
    return dumped


def _fmt_f(val: float | None, nd: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{val:.{nd}f}"


def _fmt_pct_ci(pct: float | None, ci: list[float | None]) -> str:
    if pct is None:
        return "n/a"
    lo, hi = (ci + [None, None])[:2]
    if lo is None or hi is None:
        return f"{pct:.1f}%"
    return f"{pct:.1f}% [{lo:.1f}%, {hi:.1f}%]"


def format_paired_table_md(payload: dict[str, Any]) -> str:
    ref = payload["reference_checks"]
    dr = payload["data_rule"]
    rep = payload["replay_verification"]
    comp = payload["paired_comparison"]
    sg = comp["ship_gate"]
    arms = payload["arms"]
    s_sol = arms["solver"]
    s_14 = arms["v1.4"]
    s_16 = arms["v1.6"]
    extra_vars = payload.get("extra_variants") or {}

    lines: list[str] = [
        f"{H1} Paired V1.4 vs V1.6 Social Honest Table ({payload['tier']} seeds {payload['seeds_spec']})",
        "",
        f"- Model: `opencode:google/{payload['model']}` (MCP harness, timeout {int(payload['wall_cap_s'])}s)",
        f"- Verdict: **{sg['verdict']}** (`gate_met={sg['gate_met']}`, `ship_gate_pass={sg['ship_gate_pass']}`)",
        f"- Plain shared-seed verdict: {sg['shared_direction_statement']}",
        f"- Calibration: `solver_v14={_fmt_f(ref['solver_v14_mean'])}`, `solver_v16={_fmt_f(ref['solver_v16_mean'])}`, "
        f"`exact_match={ref['solver_exact_match']}`, `do_nothing={_fmt_f(ref['do_nothing_v16_mean'])}`, "
        f"`stop_early={_fmt_f(ref['stop_early_v16_mean'])}`",
        f"- DATA RULE: v1.4 pass={dr['v14']['pass']} "
        f"(timeouts={dr['v14']['timeouts']}, errors={dr['v14']['errors']}, wall_cap={dr['v14']['wall_cap']}, valid_false={dr['v14']['valid_false']}); "
        f"v1.6 pass={dr['v16']['pass']} "
        f"(timeouts={dr['v16']['timeouts']}, errors={dr['v16']['errors']}, wall_cap={dr['v16']['wall_cap']}, valid_false={dr['v16']['valid_false']})",
        f"- Replay (`scripts/verify_replay.py`): v1.4 {rep['v14']['verified']}/{rep['v14']['total']} verified; "
        f"v1.6 {rep['v16']['verified']}/{rep['v16']['total']} verified",
        "",
        f"{H2} Per-Variant Summary (All Replay-Verified Valid Episodes)",
        "",
        "| variant | provider | n_valid | gemini score | solver score | ratio | % of solver [95% CI] | luck-adj score | luck-adj % of solver [95% CI] | accuracy | mean accuse day |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| reference solver | template == {payload['v16_provider']} | {s_sol['n_valid']}/{s_sol['n_planned']} | "
        f"n/a | {_fmt_score_pm_ci(s_sol['raw_score_mean'], s_sol['raw_score_ci95'])} | 1.000 | 100.0% | "
        f"{_fmt_f(s_sol['luck_adjusted_score_mean'])} | 100.0% | {_fmt_f(s_sol['accuracy'], 2)} | {_fmt_f(s_sol['mean_accuse_day'], 1)} |",
        f"| v1.4 primary (committed) | template | {s_14['n_valid']}/{s_14['n_planned']} | "
        f"{_fmt_score_pm_ci(s_14['raw_score_mean'], s_14['raw_score_ci95'])} | {_fmt_f(s_14['solver_raw_score_mean'])} | "
        f"{_fmt_f(s_14['raw_ratio_of_solver'])} | {_fmt_pct_ci(s_14['raw_pct_of_solver'], s_14['raw_pct_of_solver_ci95'])} | "
        f"{_fmt_f(s_14['luck_adjusted_score_mean'])} | "
        f"{_fmt_pct_ci(s_14['luck_adjusted_pct_of_solver'], s_14['luck_adjusted_pct_of_solver_ci95'])} | "
        f"{_fmt_f(s_14['accuracy'], 2)} | {_fmt_f(s_14['mean_accuse_day'], 1)} |",
    ]

    if 0 < comp["n_shared"] < comp["n_planned"]:
        v14_sh = comp["v14_shared"]
        sol_sh = comp["solver_shared"]
        lines.append(
            f"| v1.4 (paired on shared seeds {comp['shared_seeds']}) | template | {comp['n_shared']}/{comp['n_planned']} | "
            f"{_fmt_score_pm_ci(v14_sh['raw_score_mean'], v14_sh['raw_score_ci95'])} | {_fmt_f(sol_sh['raw_score_mean'])} | "
            f"{_fmt_f(v14_sh['raw_ratio_of_solver'])} | {_fmt_pct_ci(v14_sh['raw_pct_of_solver'], v14_sh['raw_pct_of_solver_ci95'])} | "
            f"{_fmt_f(v14_sh['luck_adjusted_score_mean'])} | "
            f"{_fmt_pct_ci(v14_sh['luck_adjusted_pct_of_solver'], v14_sh['luck_adjusted_pct_of_solver_ci95'])} | "
            f"{_fmt_f(v14_sh['accuracy'], 2)} | {_fmt_f(v14_sh['mean_accuse_day'], 1)} |"
        )

    lines.append(
        f"| v1.6 social | {payload['v16_provider']} | {s_16['n_valid']}/{s_16['n_planned']} | "
        f"{_fmt_score_pm_ci(s_16['raw_score_mean'], s_16['raw_score_ci95'])} | {_fmt_f(s_16['solver_raw_score_mean'])} | "
        f"{_fmt_f(s_16['raw_ratio_of_solver'])} | {_fmt_pct_ci(s_16['raw_pct_of_solver'], s_16['raw_pct_of_solver_ci95'])} | "
        f"{_fmt_f(s_16['luck_adjusted_score_mean'])} | "
        f"{_fmt_pct_ci(s_16['luck_adjusted_pct_of_solver'], s_16['luck_adjusted_pct_of_solver_ci95'])} | "
        f"{_fmt_f(s_16['accuracy'], 2)} | {_fmt_f(s_16['mean_accuse_day'], 1)} |"
    )

    for ev_name, ev_sum in sorted(extra_vars.items()):
        lines.append(
            f"| {ev_name} | {ev_sum['provider']} | {ev_sum['n_valid']}/{ev_sum['n_planned']} | "
            f"{_fmt_score_pm_ci(ev_sum['raw_score_mean'], ev_sum['raw_score_ci95'])} | {_fmt_f(ev_sum['solver_raw_score_mean'])} | "
            f"{_fmt_f(ev_sum['raw_ratio_of_solver'])} | {_fmt_pct_ci(ev_sum['raw_pct_of_solver'], ev_sum['raw_pct_of_solver_ci95'])} | "
            f"{_fmt_f(ev_sum['luck_adjusted_score_mean'])} | "
            f"{_fmt_pct_ci(ev_sum['luck_adjusted_pct_of_solver'], ev_sum['luck_adjusted_pct_of_solver_ci95'])} | "
            f"{_fmt_f(ev_sum['accuracy'], 2)} | {_fmt_f(ev_sum['mean_accuse_day'], 1)} |"
        )

    lines.extend([
        "",
        f"{H2} Paired Comparison on Shared Seeds (n={comp['n_shared']}/{comp['n_planned']})",
        "",
    ])

    if comp["n_shared"] > 0:
        v14_sh = comp["v14_shared"]
        v16_sh = comp["v16_shared"]
        sol_sh = comp["solver_shared"]
        dl = comp["delta_v16_minus_v14"]
        lines.extend([
            f"- Shared seeds: `{comp['shared_seeds']}` (`n_valid={comp['n_shared']}`)",
            f"- Does v1.6 score higher for Gemini than v1.4 on the same seeds? **{'YES' if sg['v16_higher_than_v14_on_shared'] else 'NO'}** (`gate_met={sg['gate_met']}`)",
            f"- Paired solver score on shared seeds: `{_fmt_f(sol_sh['raw_score_mean'])}` (luck-adjusted `{_fmt_f(sol_sh['luck_adjusted_score_mean'])}`)",
            f"- Paired v1.4 on shared seeds: gemini `{_fmt_score_pm_ci(v14_sh['raw_score_mean'], v14_sh['raw_score_ci95'])}`, "
            f"ratio `{_fmt_f(v14_sh['raw_ratio_of_solver'])}` (`{_fmt_pct_ci(v14_sh['raw_pct_of_solver'], v14_sh['raw_pct_of_solver_ci95'])}`), "
            f"acc `{_fmt_f(v14_sh['accuracy'], 2)}`, mean accuse day `{_fmt_f(v14_sh['mean_accuse_day'], 1)}`",
            f"- Paired v1.6 on shared seeds: gemini `{_fmt_score_pm_ci(v16_sh['raw_score_mean'], v16_sh['raw_score_ci95'])}`, "
            f"ratio `{_fmt_f(v16_sh['raw_ratio_of_solver'])}` (`{_fmt_pct_ci(v16_sh['raw_pct_of_solver'], v16_sh['raw_pct_of_solver_ci95'])}`), "
            f"acc `{_fmt_f(v16_sh['accuracy'], 2)}`, mean accuse day `{_fmt_f(v16_sh['mean_accuse_day'], 1)}`",
            f"- Paired v1.4 luck-adjusted % of solver: `{_fmt_pct_ci(v14_sh['luck_adjusted_pct_of_solver'], v14_sh['luck_adjusted_pct_of_solver_ci95'])}`",
            f"- Paired v1.6 luck-adjusted % of solver: `{_fmt_pct_ci(v16_sh['luck_adjusted_pct_of_solver'], v16_sh['luck_adjusted_pct_of_solver_ci95'])}`",
            f"- Delta (v1.6 - v1.4): raw `{_fmt_score_pm_ci(dl['raw_score_mean'], dl['raw_score_ci95'])}` "
            f"(`{_fmt_pct_ci(dl['raw_pct_points'], dl['raw_pct_points_ci95'])}` pp vs solver), "
            f"luck-adjusted `{_fmt_pct_ci(dl['luck_adjusted_pct_points'], dl['luck_adjusted_pct_points_ci95'])}` pp vs solver",
            "",
        ])
    else:
        lines.extend([
            f"- Shared seeds: none landed yet (`n_valid=0/{comp['n_planned']}`).",
            f"- Gate status: **GATE NOT MET** (`gate_met=False`).",
            "",
        ])

    lines.extend([
        f"{H2} Per-Variant and Per-Seed Honest Table (Seeds {payload['seeds_spec']})",
        "",
        "| seed | owner | solver score | v1.4 gemini score (day, P) | v1.4 ratio | v1.4 luck-adj | v1.6 status | v1.6 gemini score (day, P) | v1.6 ratio | v1.6 luck-adj | v1.6 > v1.4? | replay |",
        "|---:|---|---:|---|---:|---:|---|---|---:|---:|---|---|",
    ])

    by_sol = {int(r["seed"]): r for r in s_sol["per_seed"]}
    by_14 = {int(r["seed"]): r for r in s_14["per_seed"]}
    by_16 = {int(r["seed"]): r for r in s_16["per_seed"]}
    in_flight_set = set(dr["v16"]["in_flight_seeds"])
    excluded_set = set(dr["v16"].get("excluded_seeds") or [])

    for s in payload["seeds"]:
        owner = SHARD_OWNERS.get(int(s), "unassigned")
        rsol = by_sol.get(int(s))
        r14 = by_14.get(int(s))
        r16 = by_16.get(int(s))
        sol_cell = f"{_fmt_f(rsol['score'])}" if rsol else "n/a"
        if r14:
            c14 = f"{_fmt_f(r14['score'])} (d{r14['final_day']}, P={_fmt_f(r14['p_accused'], 2)})"
            rat14 = _fmt_f(r14.get("ratio_of_solver"))
            l14 = _fmt_f(r14["luck_adjusted_score"])
        else:
            c14, rat14, l14 = "n/a", "n/a", "n/a"

        if r16:
            st16 = "VALID"
            c16 = f"{_fmt_f(r16['score'])} (d{r16['final_day']}, P={_fmt_f(r16['p_accused'], 2)})"
            rat16 = _fmt_f(r16.get("ratio_of_solver"))
            l16 = _fmt_f(r16["luck_adjusted_score"])
            if r14:
                diff_s = float(r16["score"]) - float(r14["score"])
                if diff_s > 1e-12:
                    cmp_cell = f"YES ({diff_s:+.3f})"
                elif diff_s < -1e-12:
                    cmp_cell = f"NO ({diff_s:+.3f})"
                else:
                    cmp_cell = "TIE (+0.000)"
            else:
                cmp_cell = "n/a"
            rep_cell = "PASS" if (r14 and r14["replay_verified"] and r16["replay_verified"]) else "FAIL"
        elif int(s) in in_flight_set:
            st16 = "IN_FLIGHT"
            c16, rat16, l16, cmp_cell = "running", "n/a", "n/a", "n/a"
            rep_cell = "v1.4 PASS"
        elif int(s) in excluded_set:
            st16 = "EXCLUDED_INVALID"
            c16, rat16, l16, cmp_cell = "excluded", "n/a", "n/a", "n/a"
            rep_cell = "v1.4 PASS"
        else:
            st16 = "NOT_RUN"
            c16, rat16, l16, cmp_cell = "not_run", "n/a", "n/a", "n/a"
            rep_cell = "v1.4 PASS"
        lines.append(
            f"| {s} | {owner} | {sol_cell} | {c14} | {rat14} | {l14} | {st16} | {c16} | {rat16} | {l16} | {cmp_cell} | {rep_cell} |"
        )

    if extra_vars:
        lines.extend(["", f"{H2} Extra V1.6 Variants Per-Seed Breakdown", ""])
        lines.extend([
            "| variant | seed | gemini score | solver score | ratio | replay |",
            "|---|---:|---:|---:|---:|---|",
        ])
        for ev_name, ev_sum in sorted(extra_vars.items()):
            for r in ev_sum["per_seed"]:
                lines.append(
                    f"| {ev_name} | {r['seed']} | {_fmt_f(r['score'])} | {_fmt_f(r['solver_score'])} | "
                    f"{_fmt_f(r.get('ratio_of_solver'))} | {'PASS' if r['replay_verified'] else 'FAIL'} |"
                )

    az = payload.get("azure_relayed_30_44")
    if isinstance(az, dict) and az.get("variants"):
        lines.extend([
            "",
            f"{H2} Relayed Azure In-Process Checkpoints (Hard Seeds 30-32, Labelled Non-Local Checkpoint)",
            "",
            f"- Source: `{az['source_note']}`",
            f"- Plain verdict (shared seeds 30-32): {az['plain_statement']}",
            f"- Reference solver context (`results/v16_social/reference_seeds_30_49.json`): 20-seed hard 30-49 raw mean `{_fmt_f(az['solver_30_49_raw_mean'])}`; "
            f"on seeds `[30, 31, 32]` raw mean is `{_fmt_f(az['solver_30_32_raw_mean'])}` (wrong high-confidence accusations on seeds 30 and 32) and luck-adjusted mean is `{_fmt_f(az['solver_30_32_luck_adj_mean'])}`.",
            "",
            "| variant | shared seeds | n_valid | gemini mean | solver raw mean | solver luck-adj mean | ratio vs solver (30-49 ref) | ratio vs solver (luck-adj) | paired v1.6 / v1.4 ratio | v1.6 > v1.4? |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ])
        for vr in az["variants"]:
            lines.append(
                f"| {vr['variant']} | {vr['seeds']} | {vr['n_valid']} | {_fmt_f(vr['gemini_mean'])} | "
                f"{_fmt_f(vr['solver_raw_mean'])} | {_fmt_f(vr['solver_luck_adj_mean'])} | "
                f"{_fmt_f(vr['ratio_vs_solver_30_49'])} | {_fmt_f(vr['ratio_vs_solver_luck_adj'])} | "
                f"{_fmt_f(vr['paired_ratio_vs_v14_control'])} | {vr['higher_than_v14_label']} |"
            )
        lines.extend([
            "",
            "| variant | seed | gemini score | solver raw score | solver luck-adj | ratio vs solver (luck-adj) | paired v1.6 / v1.4 seed ratio | v1.6 > v1.4? |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for sr in az["per_seed"]:
            lines.append(
                f"| {sr['variant']} | {sr['seed']} | {_fmt_f(sr['gemini_score'])} | {_fmt_f(sr['solver_raw_score'])} | "
                f"{_fmt_f(sr['solver_luck_adj_score'])} | {_fmt_f(sr['ratio_vs_solver_luck_adj'])} | "
                f"{_fmt_f(sr['paired_ratio_vs_v14_seed'])} | {sr['higher_than_v14_label']} |"
            )

    lines.extend(["", f"{H2} Ship-Gate Reasons", ""])
    for reason in sg["reasons"]:
        lines.append(f"- {reason}")

    out = "\n".join(lines) + "\n"
    out.encode("ascii")
    return out


def build_azure_relayed_summary(ref_30_49_path: Path = DEFAULT_REF_30_49_JSON) -> dict[str, Any]:
    ref_by_seed: dict[int, dict[str, Any]] = {}
    ref_all_raw: list[float] = []
    if ref_30_49_path.is_file():
        raw_doc = json.loads(ref_30_49_path.read_text(encoding="utf-8"))
        for row in raw_doc.get("seeds") or []:
            s_id = int(row["seed"])
            ref_by_seed[s_id] = row
            ref_all_raw.append(float(row["solver_score"]))

    for s_req in (30, 31, 32):
        if s_req not in ref_by_seed:
            r_sol = run_episode(make_env("hard", s_req, "template"), SolverPolicy())
            sol_dict = _ep_obj_to_dict(r_sol, "solver")
            _, luck_v = compute_posterior_and_luck(sol_dict, fallback_v=float(r_sol.score) if r_sol.correct else None)
            ref_by_seed[s_req] = {
                "seed": s_req,
                "solver_score": float(r_sol.score),
                "solver_luck_adj": float(luck_v),
            }

    sol_30_49_mean = (sum(ref_all_raw) / len(ref_all_raw)) if ref_all_raw else None
    ctrl_by_seed = dict(AZURE_RELAYED_SCORES[0][1])
    sol_30_32_raw = sum(float(ref_by_seed[s]["solver_score"]) for s in (30, 31, 32)) / 3.0
    sol_30_32_luck = sum(float(ref_by_seed[s]["solver_luck_adj"]) for s in (30, 31, 32)) / 3.0

    variant_rows: list[dict[str, Any]] = []
    seed_rows: list[dict[str, Any]] = []
    for var_name, pairs in AZURE_RELAYED_SCORES:
        s_ids = [int(s) for s, _ in pairs]
        g_vals = [float(v) for _, v in pairs]
        c_vals = [float(ctrl_by_seed[s]) for s in s_ids]
        sr_vals = [float(ref_by_seed[s]["solver_score"]) for s in s_ids]
        sl_vals = [float(ref_by_seed[s]["solver_luck_adj"]) for s in s_ids]
        n_v = len(s_ids)
        g_m = sum(g_vals) / n_v
        c_m = sum(c_vals) / n_v
        sr_m = sum(sr_vals) / n_v
        sl_m = sum(sl_vals) / n_v
        rat_ref = (g_m / sol_30_49_mean) if (sol_30_49_mean and sol_30_49_mean > 0.0) else None
        rat_luck = (g_m / sl_m) if sl_m > 0.0 else None
        rat_ctrl = (g_m / c_m) if c_m > 0.0 else None
        if var_name == "v0_v14_control":
            hi_lbl = "CONTROL (baseline)"
            is_hi = False
        else:
            diff_m = g_m - c_m
            is_hi = diff_m > 1e-12
            hi_lbl = f"YES ({diff_m:+.3f})" if is_hi else f"NO ({diff_m:+.3f})"
        variant_rows.append({
            "variant": var_name,
            "seeds": s_ids,
            "n_valid": n_v,
            "gemini_mean": round(g_m, 6),
            "v14_control_mean_same_seeds": round(c_m, 6),
            "solver_raw_mean": round(sr_m, 6),
            "solver_luck_adj_mean": round(sl_m, 6),
            "ratio_vs_solver_30_49": _round_or_none(rat_ref),
            "ratio_vs_solver_luck_adj": _round_or_none(rat_luck),
            "paired_ratio_vs_v14_control": _round_or_none(rat_ctrl),
            "v16_higher_than_v14": bool(is_hi),
            "higher_than_v14_label": hi_lbl,
        })
        for s, g_sc in pairs:
            sr_sc = float(ref_by_seed[int(s)]["solver_score"])
            sl_sc = float(ref_by_seed[int(s)]["solver_luck_adj"])
            c_sc = float(ctrl_by_seed[int(s)])
            r_sl = (float(g_sc) / sl_sc) if sl_sc > 0.0 else None
            r_c = (float(g_sc) / c_sc) if c_sc > 0.0 else None
            if var_name == "v0_v14_control":
                s_lbl = "CONTROL"
            else:
                d_s = float(g_sc) - c_sc
                s_lbl = f"YES ({d_s:+.3f})" if d_s > 1e-12 else (f"NO ({d_s:+.3f})" if d_s < -1e-12 else "TIE (+0.000)")
            seed_rows.append({
                "variant": var_name,
                "seed": int(s),
                "gemini_score": round(float(g_sc), 6),
                "solver_raw_score": round(sr_sc, 6),
                "solver_luck_adj_score": round(sl_sc, 6),
                "ratio_vs_solver_luck_adj": _round_or_none(r_sl),
                "paired_ratio_vs_v14_seed": _round_or_none(r_c),
                "higher_than_v14_label": s_lbl,
            })

    plain_stmt = (
        "With n=3 shared seeds (30-32) in the relayed Azure in-process gemini-4-carbon evaluation, "
        "v1.6 (v5_full9_cocktail mean 0.617) scores HIGHER for Gemini than v1.4 "
        "(v0_v14_control mean 0.523, paired v1.6/v1.4 ratio 1.178), and v1 (n=1, 0.650 vs 0.540) "
        "and v3 (n=2, 0.645 vs 0.545) likewise score higher than v1.4 on the same seeds; the gate is NOT met."
    )
    return {
        "labelled_non_replay_relayed": True,
        "source_note": "Relayed from Azure VM /tmp/fleet-momin/shared/v16_runs (in-process gemini-4-carbon, hard seeds 30-44, jobs=1; solver scores verified locally from results/v16_social/reference_seeds_30_49.json)",
        "gate_met": False,
        "v16_higher_than_v14_on_n3": True,
        "plain_statement": plain_stmt,
        "solver_30_49_raw_mean": _round_or_none(sol_30_49_mean),
        "solver_30_32_raw_mean": round(sol_30_32_raw, 6),
        "solver_30_32_luck_adj_mean": round(sol_30_32_luck, 6),
        "variants": variant_rows,
        "per_seed": seed_rows,
    }


def format_gate_report_md(payload: dict[str, Any]) -> str:
    sg = payload["paired_comparison"]["ship_gate"]
    az = payload.get("azure_relayed_30_44") or {}
    az_line = (
        f"- Relayed Azure shared-seed summary (hard seeds 30-32, n=3): {az['plain_statement']}"
        if az.get("plain_statement")
        else "- Relayed Azure shared-seed summary: n/a"
    )
    header = [
        f"{H1} Canary V1.6 Social Layer Gate Report",
        "",
        f"{H2} Background and Experimental Protocol",
        "",
        "- Prior v1.5 Gate B negative result: on hard seeds 0-9, `gemini-4-carbon` over OpenCode MCP rose from "
        "60.9% [3.4%, 103.8%] of the solver on v1.4 to 108% on v1.5 because v1.5 seeded rumours away from the true mole, "
        "allowing frontier models to invert the rumour target as an exoneration signal.",
        "- V1.6 fix (`social-v2` / zero-mole-info `PublicDayFacts`): all rumours, grudges, authority pressure, and "
        "misforwards are deterministically derived from public observables only (zero mole/decoy inputs), preserving "
        "exact solver calibration (`solver_v14 == solver_v16 == 0.576` on hard seeds 0-9) and `do_nothing == 0.0`, `stop_early == 0.0`.",
        "- Pre-registered V1.6 Gate B rule: aggregate incoming OpenCode `google/gemini-4-carbon` (`--timeout 3600`, `--jobs 1`) "
        "shards on hard seeds 0-9 against the primary committed `data/runs/committed/v1.4/opencode-gemini-4-carbon` hard seeds 0-9 "
        "and the reference solver; enforce DATA RULE (0 timeouts, 0 errors, 0 wall-cap, `valid != False`) and `scripts/verify_replay.py` "
        "on every episode; ship only if all 10 seeds complete cleanly and v1.6 drops below v1.4.",
        "",
        f"{H2} Current Gate Verdict: {sg['verdict']}",
        "",
        f"- Plain shared-seed summary (OpenCode hard 0-9): {sg['shared_direction_statement']}",
        az_line,
        f"- Reproduce offline: `python scripts/build_v16_paired_table.py`",
        f"- Machine-readable artifact: `results/v16_social/paired_v14_vs_v16_0_9.json`",
        f"- Paired table artifact: `results/v16_social/paired_v14_vs_v16_0_9.md`",
        "",
    ]
    body = format_paired_table_md(payload).splitlines()
    if body and body[0].startswith(f"{H1} "):
        body = body[1:]
    combined = "\n".join(header + body).rstrip() + "\n"
    combined.encode("ascii")
    return combined


def build_paired_table(
    *,
    tier: str = DEFAULT_TIER,
    seeds: list[int] | None = None,
    seeds_spec: str = DEFAULT_SEEDS,
    model: str = DEFAULT_MODEL,
    v14_dir: Path = DEFAULT_V14_DIR,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    v16_root: Path = DEFAULT_V16_ROOT,
    staging_globs: list[str] | None = None,
    worker_wt_glob: str | None = "/tmp/fleet-silas/wt/canary-*",
    poll_branches: list[str] | None = None,
    v16_provider: str = DEFAULT_V16_PROVIDER,
    wall_cap_s: float = DEFAULT_WALL_CAP_S,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    allow_fake: bool = False,
    materialize_shards: bool = False,
    out_json: Path | None = DEFAULT_OUT_JSON,
    out_md: Path | None = DEFAULT_OUT_MD,
    out_gate_md: Path | None = DEFAULT_OUT_GATE_MD,
) -> dict[str, Any]:
    prev_offline = os.environ.get("CANARY_OFFLINE")
    os.environ["CANARY_OFFLINE"] = "1"
    try:
        seed_list = list(seeds) if seeds is not None else parse_seeds(seeds_spec)
        eff_staging = list(staging_globs) if staging_globs is not None else list(DEFAULT_STAGING_GLOBS)
        eff_branches = list(poll_branches) if poll_branches is not None else []

        ref_checks, solver_eps = verify_baselines_and_solver(tier, seed_list, v16_provider, reference_dir)
        v14_eps, v14_data_rule = load_primary_v14(v14_dir, tier, seed_list, allow_fake=allow_fake)
        v16_eps, v16_sources, v16_data_rule, raw_extra_variants = discover_v16_shards(
            v16_root=v16_root,
            tier=tier,
            seeds=seed_list,
            v16_provider=v16_provider,
            staging_globs=eff_staging,
            worker_wt_glob=worker_wt_glob,
            poll_branches=eff_branches,
            wall_cap_s=wall_cap_s,
            allow_fake=allow_fake,
            materialize_shards=materialize_shards,
        )

        _, sol_replay_map = replay_and_verify_episodes(solver_eps)
        v14_replay, v14_replay_map = replay_and_verify_episodes(v14_eps)
        v16_replay, v16_replay_map = replay_and_verify_episodes(v16_eps)

        extra_variant_summaries: dict[str, Any] = {}
        extra_variant_replays: dict[str, Any] = {}
        for ev_name, ev_map in sorted(raw_extra_variants.items()):
            ev_eps = {s: pair[0] for s, pair in ev_map.items()}
            ev_sources = {s: pair[1] for s, pair in ev_map.items()}
            ev_rep, ev_rep_map = replay_and_verify_episodes(ev_eps)
            extra_variant_replays[ev_name] = ev_rep
            extra_variant_summaries[ev_name] = summarize_arm_metrics(
                arm_name=ev_name,
                provider_label=ev_name,
                tier=tier,
                planned_seeds=seed_list,
                episodes=ev_eps,
                solver_eps=solver_eps,
                replay_map=ev_rep_map,
                sources=ev_sources,
                resamples=bootstrap_resamples,
                rng_seed=bootstrap_seed,
            )

        sol_sources = {s: str(reference_dir) for s in seed_list}
        v14_sources = {s: v14_data_rule["source"] for s in v14_eps}

        solver_summary = summarize_arm_metrics(
            arm_name="solver",
            provider_label="template",
            tier=tier,
            planned_seeds=seed_list,
            episodes=solver_eps,
            solver_eps=solver_eps,
            replay_map=sol_replay_map,
            sources=sol_sources,
            resamples=bootstrap_resamples,
            rng_seed=bootstrap_seed,
        )
        v14_summary = summarize_arm_metrics(
            arm_name="v1.4",
            provider_label="template(committed)",
            tier=tier,
            planned_seeds=seed_list,
            episodes=v14_eps,
            solver_eps=solver_eps,
            replay_map=v14_replay_map,
            sources=v14_sources,
            resamples=bootstrap_resamples,
            rng_seed=bootstrap_seed,
        )
        v16_summary = summarize_arm_metrics(
            arm_name="v1.6",
            provider_label=v16_provider,
            tier=tier,
            planned_seeds=seed_list,
            episodes=v16_eps,
            solver_eps=solver_eps,
            replay_map=v16_replay_map,
            sources=v16_sources,
            resamples=bootstrap_resamples,
            rng_seed=bootstrap_seed,
        )

        extra_replays_ok = all(r["pass"] for r in extra_variant_replays.values())
        eff_v16_replay = {
            **v16_replay,
            "pass_primary": bool(v16_replay["pass"]),
            "pass": bool(v16_replay["pass"] and extra_replays_ok),
        }

        paired_comp = compute_paired_gate(
            planned_seeds=seed_list,
            v14_summary=v14_summary,
            v16_summary=v16_summary,
            solver_eps=solver_eps,
            ref_checks=ref_checks,
            v14_data_rule=v14_data_rule,
            v16_data_rule=v16_data_rule,
            v14_replay=v14_replay,
            v16_replay=eff_v16_replay,
            resamples=bootstrap_resamples,
            rng_seed=bootstrap_seed,
        )

        payload: dict[str, Any] = {
            "schema_version": "v16_paired_table_v1",
            "git_sha": git_sha(),
            "tiers_version": TIERS_VERSION,
            "tier": tier,
            "seeds_spec": seeds_spec,
            "seeds": [int(s) for s in seed_list],
            "model": model,
            "v16_provider": v16_provider,
            "wall_cap_s": float(wall_cap_s),
            "bootstrap_resamples": int(bootstrap_resamples),
            "bootstrap_seed": int(bootstrap_seed),
            "reference_checks": ref_checks,
            "data_rule": {
                "v14": v14_data_rule,
                "v16": v16_data_rule,
                "all_pass": bool(v14_data_rule["pass"] and v16_data_rule["pass"]),
            },
            "replay_verification": {
                "v14": v14_replay,
                "v16": v16_replay,
                "extra_variants": extra_variant_replays,
                "all_pass": bool(v14_replay["pass"] and v16_replay["pass"] and extra_replays_ok),
            },
            "arms": {
                "solver": solver_summary,
                "v1.4": v14_summary,
                "v1.6": v16_summary,
            },
            "extra_variants": extra_variant_summaries,
            "azure_relayed_30_44": build_azure_relayed_summary(),
            "paired_comparison": paired_comp,
        }

        dumped_json = assert_clean_payload(payload)
        rendered_md = format_paired_table_md(payload)
        rendered_gate_md = format_gate_report_md(payload)

        if out_json is not None:
            out_json = Path(out_json)
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(dumped_json + "\n", encoding="utf-8")
        if out_md is not None:
            out_md = Path(out_md)
            out_md.parent.mkdir(parents=True, exist_ok=True)
            out_md.write_text(rendered_md, encoding="utf-8")
        if out_gate_md is not None:
            out_gate_md = Path(out_gate_md)
            out_gate_md.parent.mkdir(parents=True, exist_ok=True)
            out_gate_md.write_text(rendered_gate_md, encoding="utf-8")

        return payload
    finally:
        if prev_offline is None:
            os.environ.pop("CANARY_OFFLINE", None)
        else:
            os.environ["CANARY_OFFLINE"] = prev_offline


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python scripts/build_v16_paired_table.py",
        description="Aggregate V1.6 OpenCode hard seeds 0-9 against committed V1.4 and solver with DATA RULE and replay checks.",
    )
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--seeds", default=DEFAULT_SEEDS)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--v14-dir", default=str(DEFAULT_V14_DIR))
    ap.add_argument("--reference-dir", default=str(DEFAULT_REFERENCE_DIR))
    ap.add_argument("--v16-root", default=str(DEFAULT_V16_ROOT))
    ap.add_argument("--staging-glob", action="append", default=[])
    ap.add_argument("--no-auto-staging", action="store_true")
    ap.add_argument("--worker-wt-glob", default="/tmp/fleet-silas/wt/canary-*")
    ap.add_argument("--no-worker-discovery", action="store_true")
    ap.add_argument("--discover-git-branches", action="store_true")
    ap.add_argument("--poll-branches", default=",".join(DEFAULT_POLL_BRANCHES))
    ap.add_argument("--materialize-shards", action="store_true")
    ap.add_argument("--v16-provider", default=DEFAULT_V16_PROVIDER)
    ap.add_argument("--wall-cap", type=float, default=DEFAULT_WALL_CAP_S)
    ap.add_argument("--bootstrap-resamples", type=int, default=DEFAULT_BOOTSTRAP_RESAMPLES)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--allow-fake", action="store_true")
    ap.add_argument("--require-complete", action="store_true")
    ap.add_argument("--poll-interval", type=float, default=0.0)
    ap.add_argument("--poll-max-seconds", type=float, default=0.0)
    ap.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    ap.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    ap.add_argument("--out-gate-md", default=str(DEFAULT_OUT_GATE_MD))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeds = parse_seeds(args.seeds)
    if args.staging_glob:
        staging_globs = list(args.staging_glob)
    elif args.no_auto_staging:
        staging_globs = []
    else:
        staging_globs = list(DEFAULT_STAGING_GLOBS)

    wt_glob = None if args.no_worker_discovery else args.worker_wt_glob
    branches = (
        [b.strip() for b in args.poll_branches.split(",") if b.strip()]
        if args.discover_git_branches
        else []
    )

    t_start = time.monotonic()
    while True:
        if args.discover_git_branches:
            subprocess.run(["git", "fetch", "origin"], cwd=str(REPO_ROOT), capture_output=True, timeout=30)
        payload = build_paired_table(
            tier=args.tier,
            seeds=seeds,
            seeds_spec=args.seeds,
            model=args.model,
            v14_dir=Path(args.v14_dir),
            reference_dir=Path(args.reference_dir),
            v16_root=Path(args.v16_root),
            staging_globs=staging_globs,
            worker_wt_glob=wt_glob,
            poll_branches=branches,
            v16_provider=args.v16_provider,
            wall_cap_s=args.wall_cap,
            bootstrap_resamples=args.bootstrap_resamples,
            bootstrap_seed=args.bootstrap_seed,
            allow_fake=bool(args.allow_fake),
            materialize_shards=bool(args.materialize_shards),
            out_json=Path(args.out_json) if args.out_json else None,
            out_md=Path(args.out_md) if args.out_md else None,
            out_gate_md=Path(args.out_gate_md) if args.out_gate_md else None,
        )
        comp = payload["paired_comparison"]
        if args.poll_interval <= 0.0 or comp["complete"]:
            break
        if args.poll_max_seconds > 0.0 and (time.monotonic() - t_start) >= args.poll_max_seconds:
            break
        time.sleep(args.poll_interval)

    print(format_paired_table_md(payload), end="", flush=True)
    sg = payload["paired_comparison"]["ship_gate"]
    integrity_ok = (
        sg["data_rule_pass"]
        and sg["replay_verified_pass"]
        and sg["baselines_zero_pass"]
        and sg["solver_calibrated_pass"]
    )
    if not integrity_ok:
        return 1
    if args.require_complete and not sg["complete"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
