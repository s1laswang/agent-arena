from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from canary.agents.frontier.common import empty_final_response, final_step
from canary.analysis.gap import mean_ci
from canary.baselines import BASELINES
from canary.env import Env
from canary.eval import make_env, parse_seeds, run_episode
from canary.llm.base import load_env
from canary.solver.policy import SolverPolicy
from paired_v13 import boot_ratio, p_acc, post_expected

RATE_RE = re.compile(r"RESOURCE_EXHAUSTED|\b429\b|rate.?limit|Quota exceeded", re.I)
EXTRA_ENV_CANDIDATES = (
    Path("/home/silas/momin/.env"),
    REPO_ROOT / ".env",
)
EXTRA_BIN_DIRS = (
    Path("/home/silas/momin/bin"),
    Path.home() / ".opencode" / "bin",
    Path.home() / ".local" / "bin",
)


def ensure_runtime_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    load_env()
    env = dict(os.environ if base_env is None else base_env)
    if not env.get("GEMINI_API_KEY"):
        for candidate in EXTRA_ENV_CANDIDATES:
            if candidate.is_file():
                try:
                    from dotenv import dotenv_values
                    for k, v in dotenv_values(candidate).items():
                        if v is not None and not env.get(k):
                            env[k] = v
                except Exception:
                    pass
    path_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    if not shutil.which("opencode", path=os.pathsep.join(path_parts)):
        for bdir in EXTRA_BIN_DIRS:
            if (bdir / "opencode").is_file() and str(bdir) not in path_parts:
                path_parts.insert(0, str(bdir))
    env["PATH"] = os.pathsep.join(path_parts)
    no_proxy_items = [x.strip() for x in (env.get("NO_PROXY") or env.get("no_proxy") or "").split(",") if x.strip()]
    for host in ("127.0.0.1", "localhost"):
        if host not in no_proxy_items:
            no_proxy_items.append(host)
    joined_no_proxy = ",".join(no_proxy_items)
    env["NO_PROXY"] = joined_no_proxy
    env["no_proxy"] = joined_no_proxy
    return env


def seed_social_cache_dir(cache_dir: Path, repo_cache: Path | None = None) -> Path:
    src = repo_cache if repo_cache is not None else (REPO_ROOT / "data" / "gemini_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and src.resolve() != cache_dir.resolve():
        for f in src.glob("*.json"):
            dst = cache_dir / f.name
            if not dst.exists():
                try:
                    dst.symlink_to(f.resolve())
                except OSError:
                    shutil.copy2(f, dst)
    return cache_dir


def parse_env_overrides(items: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE for --env, got {item!r}")
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            raise ValueError(f"empty key in --env {item!r}")
        out[k] = v
    return out


def arm_slug(arm_name: str, provider: str, model: str, env_overrides: dict[str, str]) -> str:
    safe_prov = re.sub(r"[^A-Za-z0-9_.-]+", "_", provider)
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", model.split("/")[-1])
    if not env_overrides:
        return f"{arm_name}-{safe_prov}-{safe_model}"
    digest = hashlib.sha256(json.dumps(env_overrides, sort_keys=True).encode()).hexdigest()[:8]
    return f"{arm_name}-{safe_prov}-{safe_model}-{digest}"


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


def read_eps(run_dir: Path) -> list[dict[str, Any]]:
    f = run_dir / "episodes.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def invalid_attempt_reason(run_dir: Path, ep: dict[str, Any] | None) -> str | None:
    if ep is None:
        return "invalid:no_episode_written"
    meta = ep.get("meta") or {}
    rc = meta.get("rc")
    if rc == "timeout" or ep.get("end_reason") == "timeout":
        return f"invalid:timeout (wall_s={meta.get('wall_s')})"
    err = str(meta.get("error") or "")
    if "timeout" in err.lower() or "timed out" in err.lower():
        return f"invalid:timeout ({err[:160]})"
    if ep.get("end_reason") == "accused" and meta.get("valid") is not False and not err:
        return None
    if meta.get("valid") is False or err:
        return f"invalid:{err[:200] or 'marked_invalid'}"
    tr = run_dir / "transcripts" / f"{ep.get('seed')}.txt"
    if tr.is_file():
        txt = tr.read_text(errors="replace")
        if "--- stderr\nTIMEOUT" in txt:
            return f"invalid:timeout (wall_s={meta.get('wall_s')})"
        if empty_final_response(txt):
            fs = final_step(txt) or {}
            toks = fs.get("tokens") or {}
            return (
                f"invalid:empty_model_response (finish={fs.get('reason')}, "
                f"out={toks.get('output')}, reasoning={toks.get('reasoning')})"
            )
    return None


def prewarm_social_cache(
    tier: str,
    seeds: list[int],
    provider_spec: str,
    cache_dir: Path,
    runtime_env: dict[str, str],
) -> dict[str, int]:
    if provider_spec in ("", "template") or "-template" in provider_spec:
        return {"seeds": 0, "calls": 0, "rejects": 0}
    prev_env: dict[str, str | None] = {}
    updates = dict(
        runtime_env,
        CANARY_SOCIAL_CACHE_DIR=str(cache_dir),
        CANARY_GEMINI_CACHE_DIR=str(cache_dir),
    )
    before_files = set(cache_dir.glob("*.json")) if cache_dir.is_dir() else set()
    try:
        for k, v in updates.items():
            prev_env[k] = os.environ.get(k)
            os.environ[k] = v
        from canary.text.gemini import get_provider
        prov = get_provider(provider_spec, cache_dir=str(cache_dir))
        for seed in seeds:
            env = Env(tier, seed, text_provider=prov)
            while not env.done:
                res = env.call("advance_day", {})
                if not res.ok:
                    break
        after_files = set(cache_dir.glob("*.json")) if cache_dir.is_dir() else set()
        new_files = len(after_files - before_files)
        calls = int(getattr(prov, "calls", getattr(getattr(prov, "social", None), "calls", 0)) or new_files)
        rejects = int(getattr(prov, "rejects", getattr(getattr(prov, "social", None), "rejects", 0)) or 0)
        return {"seeds": len(seeds), "calls": calls, "rejects": rejects}
    finally:
        for k, old in prev_env.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _load_committed_solver_v14(tier: str, seeds: list[int]) -> dict[int, dict[str, Any]]:
    ref_root = REPO_ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
    out: dict[int, dict[str, Any]] = {}
    if not ref_root.is_dir():
        return out
    wanted = set(seeds)
    for ep_file in sorted(ref_root.glob(f"solver-{tier}-*/episodes.jsonl")):
        for line in ep_file.read_text().splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            s = int(ep["seed"])
            if s in wanted and ep.get("agent") == "solver" and ep.get("tier") == tier:
                out[s] = ep
    return out


def _ep_to_dict(r: Any) -> dict[str, Any]:
    return {
        "tier": r.tier,
        "seed": r.seed,
        "agent": "solver",
        "score": r.score,
        "correct": r.correct,
        "accused": r.accused,
        "final_day": r.final_day,
        "end_reason": r.end_reason,
        "steps": [
            {"t": st.t, "day": st.day, "tool": st.tool, "args": st.args, "result": st.result}
            for st in r.steps
        ],
        "meta": dict(r.meta or {}, V=r.score if r.correct else None),
    }


def _template_social_spec(provider_spec: str) -> str:
    if provider_spec in ("social-v2", "v16") or provider_spec.startswith(("social-v2:", "v16:")):
        head, sep, rest = provider_spec.partition(":")
        base = "social-v2-template" if head.startswith("social-v2") else "v16-template"
        return f"{base}:{rest}" if sep else base
    return provider_spec


def verify_reference_and_baselines(
    tier: str,
    seeds: list[int],
    v16_provider: str,
    cache_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    prev_cache = os.environ.get("CANARY_SOCIAL_CACHE_DIR")
    prev_gemini_cache = os.environ.get("CANARY_GEMINI_CACHE_DIR")
    prev_offline = os.environ.get("CANARY_OFFLINE")
    os.environ["CANARY_SOCIAL_CACHE_DIR"] = str(cache_dir)
    os.environ["CANARY_GEMINI_CACHE_DIR"] = str(cache_dir)
    check_provider = _template_social_spec(v16_provider) if (dry_run or not os.environ.get("GEMINI_API_KEY")) else v16_provider
    if dry_run or not os.environ.get("GEMINI_API_KEY"):
        os.environ["CANARY_OFFLINE"] = "1"
    try:
        committed_s14 = {} if dry_run else _load_committed_solver_v14(tier, seeds)
        solver_seeds = seeds[:2] if dry_run else seeds
        solver_v14: dict[int, dict[str, Any]] = {}
        solver_v16: dict[int, dict[str, Any]] = {}
        dn_scores: list[float] = []
        se_scores: list[float] = []
        for seed in seeds:
            fb_spec = _template_social_spec(v16_provider)
            try:
                dn = run_episode(make_env(tier, seed, check_provider), BASELINES["do_nothing"](seed=seed))
                se = run_episode(make_env(tier, seed, check_provider), BASELINES["stop_early"](seed=seed))
            except Exception:
                dn = run_episode(make_env(tier, seed, fb_spec), BASELINES["do_nothing"](seed=seed))
                se = run_episode(make_env(tier, seed, fb_spec), BASELINES["stop_early"](seed=seed))
            dn_scores.append(float(dn.score))
            se_scores.append(float(se.score))
            if seed in solver_seeds:
                d14 = committed_s14.get(seed) or _ep_to_dict(run_episode(make_env(tier, seed, "template"), SolverPolicy()))
                try:
                    d16 = _ep_to_dict(run_episode(make_env(tier, seed, check_provider), SolverPolicy()))
                except Exception:
                    d16 = _ep_to_dict(run_episode(make_env(tier, seed, fb_spec), SolverPolicy()))
                solver_v14[seed] = d14
                solver_v16[seed] = d16
        return {
            "solver_v14": solver_v14,
            "solver_v16": solver_v16,
            "solver_v14_mean": sum(r["score"] for r in solver_v14.values()) / len(solver_v14),
            "solver_v16_mean": sum(r["score"] for r in solver_v16.values()) / len(solver_v16),
            "solver_exact_match": all(
                solver_v14[s]["score"] == solver_v16[s]["score"] and solver_v14[s]["accused"] == solver_v16[s]["accused"]
                for s in solver_v14
            ),
            "do_nothing_mean": sum(dn_scores) / len(dn_scores),
            "do_nothing_max": max(dn_scores),
            "stop_early_mean": sum(se_scores) / len(se_scores),
            "stop_early_max": max(se_scores),
        }
    finally:
        if prev_cache is None:
            os.environ.pop("CANARY_SOCIAL_CACHE_DIR", None)
        else:
            os.environ["CANARY_SOCIAL_CACHE_DIR"] = prev_cache
        if prev_gemini_cache is None:
            os.environ.pop("CANARY_GEMINI_CACHE_DIR", None)
        else:
            os.environ["CANARY_GEMINI_CACHE_DIR"] = prev_gemini_cache
        if prev_offline is None:
            os.environ.pop("CANARY_OFFLINE", None)
        else:
            os.environ["CANARY_OFFLINE"] = prev_offline


def load_committed_v14(tier: str, seeds: list[int], model: str) -> dict[int, dict[str, Any]]:
    model_short = model.split("/")[-1]
    ep_file = REPO_ROOT / "data" / "runs" / "committed" / "v1.4" / f"opencode-{model_short}" / tier / "episodes.jsonl"
    if not ep_file.is_file():
        raise FileNotFoundError(f"committed v1.4 run not found at {ep_file}")
    wanted = set(seeds)
    found: dict[int, dict[str, Any]] = {}
    for line in ep_file.read_text().splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        s = int(ep["seed"])
        if s not in wanted:
            continue
        reason = invalid_attempt_reason(ep_file.parent, ep)
        if reason is not None:
            raise ValueError(f"committed v1.4 seed {s} is invalid: {reason}")
        found[s] = ep
    missing = sorted(wanted - set(found))
    if missing:
        raise ValueError(f"committed v1.4 missing seeds: {missing}")
    return found


class EvalJob:
    def __init__(
        self,
        arm: str,
        provider: str,
        tier: str,
        seed: int,
        model: str,
        timeout_s: int,
        staging: Path,
        cache_dir: Path,
        env_overrides: dict[str, str],
    ):
        self.arm = arm
        self.provider = provider
        self.tier = tier
        self.seed = seed
        self.model = model if "/" in model else f"google/{model}"
        self.timeout_s = timeout_s
        self.staging = staging
        self.cache_dir = cache_dir
        self.env_overrides = dict(env_overrides)
        self.slug = arm_slug(arm, provider, self.model, self.env_overrides)
        self.dir = staging / self.slug / tier / str(seed)

    @property
    def key(self) -> str:
        return f"{self.arm}:{self.provider}/{self.tier}/{self.seed}"

    def cmd(self) -> list[str]:
        return [
            sys.executable,
            "-W",
            "ignore",
            "-m",
            "canary.agents.frontier.opencode_run",
            "--model",
            self.model,
            "--tier",
            self.tier,
            "--seeds",
            str(self.seed),
            "--jobs",
            "1",
            "--retries",
            "0",
            "--timeout",
            str(self.timeout_s),
            "--out",
            str(self.dir),
        ]

    def build_env(self, base_env: dict[str, str]) -> dict[str, str]:
        env = dict(base_env)
        env["CANARY_PROVIDER"] = self.provider
        env["CANARY_SOCIAL_CACHE_DIR"] = str(self.cache_dir)
        env["CANARY_GEMINI_CACHE_DIR"] = str(self.cache_dir)
        env["CANARY_LLM_MAX_RETRIES"] = env.get("CANARY_LLM_MAX_RETRIES", "12")
        if self.arm == "v1.6":
            env.update(self.env_overrides)
        return env

    def running(self) -> bool:
        rf = self.dir / "RUNNING.json"
        if not rf.is_file():
            return False
        try:
            info = json.loads(rf.read_text())
            return pid_alive(int(info["pid"]), str(self.dir))
        except Exception:
            return False

    def invalid_dirs(self) -> list[Path]:
        inv = self.staging / "invalid"
        if not inv.is_dir():
            return []
        return sorted(inv.glob(f"{self.slug}-{self.tier}-{self.seed}-*"))

    def attempts(self) -> int:
        valid_done = 0
        eps = read_eps(self.dir)
        if eps and invalid_attempt_reason(self.dir, eps[-1]) is None:
            valid_done = 1
        return len(self.invalid_dirs()) + valid_done


def run_jobs(
    jobs: list[EvalJob],
    slots: int,
    max_attempts: int,
    runtime_env: dict[str, str],
    staging: Path,
    dry_run: bool = False,
) -> None:
    (staging / "logs").mkdir(parents=True, exist_ok=True)
    backoff = {"until": 0.0, "delay": 45.0, "penalty": 0}

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def move_invalid(j: EvalJob, reason: str) -> Path:
        stamp = f"{time.strftime('%H%M%S')}-{os.getpid()}"
        dst = staging / "invalid" / f"{j.slug}-{j.tier}-{j.seed}-{stamp}"
        suffix = 0
        while dst.exists():
            suffix += 1
            dst = staging / "invalid" / f"{j.slug}-{j.tier}-{j.seed}-{stamp}-{suffix}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if j.dir.exists():
            shutil.move(str(j.dir), str(dst))
        else:
            dst.mkdir(parents=True, exist_ok=True)
        (dst / "INVALID.txt").write_text(reason + "\n")
        return dst

    for j in jobs:
        if j.running():
            continue
        rf = j.dir / "RUNNING.json"
        if rf.is_file():
            rf.unlink(missing_ok=True)
        eps = read_eps(j.dir)
        if eps:
            reason = invalid_attempt_reason(j.dir, eps[-1])
            if reason is not None:
                dst = move_invalid(j, reason)
                log(f"SWEEP {j.key} -> {reason} (moved to {dst.name})")

    if dry_run:
        for j in jobs:
            log(f"DRY-RUN {j.key} CANARY_PROVIDER={j.provider}: {' '.join(j.cmd())}")
        return

    while True:
        for j in jobs:
            rf = j.dir / "RUNNING.json"
            if not rf.is_file() or j.running():
                continue
            info = json.loads(rf.read_text())
            rf.unlink(missing_ok=True)
            eps = read_eps(j.dir)
            ep = eps[-1] if eps else None
            reason = invalid_attempt_reason(j.dir, ep)
            wall = time.time() - float(info.get("started", time.time()))
            if reason is not None:
                log_file = staging / "logs" / f"{j.slug}-{j.tier}-{j.seed}.log"
                tail = log_file.read_text(errors="replace")[-400:] if log_file.is_file() else ""
                full_reason = f"{reason} | tail={tail}" if ep is None and tail else reason
                move_invalid(j, full_reason)
                if RATE_RE.search(full_reason):
                    backoff["until"] = time.time() + backoff["delay"]
                    backoff["penalty"] = min(backoff["penalty"] + 1, max(0, slots - 1))
                    log(f"RATE-LIMIT on {j.key}: sleeping {backoff['delay']:.0f}s")
                    backoff["delay"] = min(backoff["delay"] * 2, 600.0)
                log(f"INVALID {j.key} wall={wall:.1f}s reason={reason} attempts={j.attempts()}/{max_attempts}")
            else:
                backoff["delay"] = 45.0
                backoff["penalty"] = max(0, backoff["penalty"] - 1)
                log(
                    f"VALID {j.key} score={ep['score']:+.3f} correct={ep['correct']} "
                    f"accused={ep.get('accused')} day={ep.get('final_day')} wall={wall:.1f}s"
                )

        active = [j for j in jobs if j.running()]
        pending = [
            j for j in jobs
            if not j.running()
            and not (read_eps(j.dir) and invalid_attempt_reason(j.dir, read_eps(j.dir)[-1]) is None)
            and j.attempts() < max_attempts
        ]
        eff_slots = max(1, slots - backoff["penalty"])
        while pending and len(active) < eff_slots and time.time() >= backoff["until"]:
            j = pending.pop(0)
            j.dir.mkdir(parents=True, exist_ok=True)
            log_file = (staging / "logs" / f"{j.slug}-{j.tier}-{j.seed}.log").open("a")
            proc = subprocess.Popen(
                j.cmd(),
                cwd=str(REPO_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=j.build_env(runtime_env),
                start_new_session=True,
            )
            (j.dir / "RUNNING.json").write_text(
                json.dumps({"pid": proc.pid, "started": time.time(), "cmd": j.cmd(), "provider": j.provider})
            )
            active.append(j)
            log(f"LAUNCH {j.key} pid={proc.pid} timeout={j.timeout_s}s ({len(active)}/{eff_slots} active)")
            time.sleep(3.0)

        if not active and not pending:
            break
        time.sleep(5.0)


def safe_boot_ratio(f_scores: list[float], s_scores: list[float]) -> tuple[float, float]:
    if len(f_scores) < 2 or sum(s_scores) <= 0:
        return float("nan"), float("nan")
    try:
        return boot_ratio(f_scores, s_scores)
    except Exception:
        return float("nan"), float("nan")


def summarize_arm(
    arm: str,
    provider: str,
    tier: str,
    planned_seeds: list[int],
    valid_eps: dict[int, dict[str, Any]],
    solver_eps: dict[int, dict[str, Any]],
    invalid_reasons: dict[int, list[str]],
) -> dict[str, Any]:
    ordered = [valid_eps[s] for s in planned_seeds if s in valid_eps]
    valid_seeds = [int(e["seed"]) for e in ordered]
    f_scores = [float(e["score"]) for e in ordered]
    s_scores = [float(solver_eps[s]["score"]) for s in valid_seeds]
    mean_f, ci_f = mean_ci(f_scores) if f_scores else (float("nan"), float("nan"))
    mean_s = (sum(s_scores) / len(s_scores)) if s_scores else float("nan")
    ratio = (mean_f / mean_s) if f_scores and mean_s > 0 else float("nan")
    r_lo, r_hi = safe_boot_ratio(f_scores, s_scores)
    diffs = [a - b for a, b in zip(f_scores, s_scores)]
    diff_m, diff_ci = mean_ci(diffs) if diffs else (float("nan"), float("nan"))

    ps = [x for x in (p_acc(e) for e in ordered if e.get("accused")) if x is not None]
    pe = [post_expected(e) for e in ordered]
    pe_s = [post_expected(solver_eps[s]) for s in valid_seeds]
    pe_ok = bool(pe) and None not in pe and None not in pe_s and sum(pe_s) > 0
    luck_ratio = (sum(pe) / sum(pe_s)) if pe_ok else float("nan")
    luck_lo, luck_hi = safe_boot_ratio(pe, pe_s) if pe_ok else (float("nan"), float("nan"))

    n_timeouts = sum(
        1 for reasons in invalid_reasons.values() for r in reasons if "invalid:timeout" in r
    )
    n_infra = sum(
        1 for reasons in invalid_reasons.values() for r in reasons if "invalid:timeout" not in r
    )
    accused_eps = [e for e in ordered if e.get("accused")]
    return {
        "arm": arm,
        "provider": provider,
        "tier": tier,
        "planned_seeds": planned_seeds,
        "valid_seeds": valid_seeds,
        "missing_or_invalid_seeds": [s for s in planned_seeds if s not in valid_eps],
        "n_planned": len(planned_seeds),
        "n_valid": len(ordered),
        "timeouts_excluded": n_timeouts,
        "infra_excluded": n_infra,
        "invalid_attempts": invalid_reasons,
        "mean_score": mean_f,
        "ci95": ci_f,
        "accuracy": (sum(1 for e in ordered if e.get("correct")) / len(ordered)) if ordered else float("nan"),
        "accused_rate": (len(accused_eps) / len(ordered)) if ordered else float("nan"),
        "mean_accuse_day": (
            sum(float(e.get("final_day") or 0) for e in accused_eps) / len(accused_eps)
            if accused_eps else float("nan")
        ),
        "mean_p_accused": (sum(ps) / len(ps)) if ps else float("nan"),
        "solver_same_seeds": mean_s,
        "ratio": ratio,
        "ratio_lo": r_lo,
        "ratio_hi": r_hi,
        "paired_diff": diff_m,
        "paired_diff_ci95": diff_ci,
        "luck_adjusted_score": (sum(pe) / len(pe)) if pe and None not in pe else float("nan"),
        "luck_adjusted_ratio": luck_ratio,
        "luck_adjusted_lo": luck_lo,
        "luck_adjusted_hi": luck_hi,
        "per_seed": {
            int(e["seed"]): {
                "score": float(e["score"]),
                "solver_score": float(solver_eps[int(e["seed"])]["score"]),
                "correct": bool(e.get("correct")),
                "accused": e.get("accused"),
                "final_day": int(e.get("final_day") or 0),
                "wall_s": (e.get("meta") or {}).get("wall_s"),
            }
            for e in ordered
        },
    }


def compute_paired_comparison(
    planned_seeds: list[int],
    v14_summary: dict[str, Any] | None,
    v16_summary: dict[str, Any] | None,
    ref_checks: dict[str, Any],
) -> dict[str, Any]:
    if not v14_summary or not v16_summary:
        return {"shared_seeds": [], "ship_gate_pass": False}
    shared = [
        s for s in planned_seeds
        if s in v14_summary["per_seed"] and s in v16_summary["per_seed"]
    ]
    if not shared:
        return {"shared_seeds": [], "ship_gate_pass": False}
    f14 = [v14_summary["per_seed"][s]["score"] for s in shared]
    f16 = [v16_summary["per_seed"][s]["score"] for s in shared]
    sol14 = [v14_summary["per_seed"][s]["solver_score"] for s in shared]
    sol16 = [v16_summary["per_seed"][s]["solver_score"] for s in shared]
    r14 = (sum(f14) / len(f14)) / (sum(sol14) / len(sol14)) if sum(sol14) > 0 else float("nan")
    r16 = (sum(f16) / len(f16)) / (sum(sol16) / len(sol16)) if sum(sol16) > 0 else float("nan")
    r14_lo, r14_hi = safe_boot_ratio(f14, sol14)
    r16_lo, r16_hi = safe_boot_ratio(f16, sol16)
    delta_scores = [b - a for a, b in zip(f14, f16)]
    dm, dci = mean_ci(delta_scores)
    complete = len(shared) == len(planned_seeds)
    baselines_zero = (
        ref_checks["do_nothing_mean"] == 0.0
        and ref_checks["do_nothing_max"] <= 0.0
        and ref_checks["stop_early_mean"] == 0.0
        and ref_checks["stop_early_max"] <= 0.0
    )
    below = bool(r16 == r16 and r14 == r14 and r16 < r14)
    return {
        "shared_seeds": shared,
        "complete": complete,
        "v14_ratio_shared": r14,
        "v14_ratio_shared_ci95": [r14_lo, r14_hi],
        "v16_ratio_shared": r16,
        "v16_ratio_shared_ci95": [r16_lo, r16_hi],
        "delta_ratio": r16 - r14,
        "delta_score_mean": dm,
        "delta_score_ci95": dci,
        "baselines_zero": baselines_zero,
        "solver_calibrated": bool(ref_checks["solver_exact_match"]),
        "below_v14": below,
        "ship_gate_pass": bool(complete and baselines_zero and ref_checks["solver_exact_match"] and below),
    }


def _fmt_num(x: float, nd: int = 3) -> str:
    if x != x:
        return "nan"
    return f"{x:.{nd}f}"


def _fmt_pct_ci(r: float, lo: float, hi: float) -> str:
    if r != r:
        return "nan"
    if lo != lo or hi != hi:
        return f"{r * 100:.1f}%"
    return f"{r * 100:.1f}% [{lo * 100:.1f}%, {hi * 100:.1f}%]"


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    ref = report["reference_checks"]
    lines.append(
        f"Calibration ({report['tier']} seeds {report['seeds_spec']}): "
        f"solver_v14={_fmt_num(ref['solver_v14_mean'])} "
        f"solver_v16={_fmt_num(ref['solver_v16_mean'])} "
        f"exact_match={ref['solver_exact_match']} "
        f"do_nothing={_fmt_num(ref['do_nothing_mean'])} "
        f"stop_early={_fmt_num(ref['stop_early_mean'])}"
    )
    lines.append("")
    lines.append(
        "| arm | provider | n_valid/n | timeouts_excl | score +/- CI | acc | solver | "
        "frontier/solver [95% CI] | luck-adj/solver [95% CI] |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for key in ("v1.4", "v1.6"):
        s = report["arms"].get(key)
        if not s:
            continue
        lines.append(
            f"| {key} | {s['provider']} | {s['n_valid']}/{s['n_planned']} | {s['timeouts_excluded']} | "
            f"{_fmt_num(s['mean_score'])} +/- {_fmt_num(s['ci95'])} | {_fmt_num(s['accuracy'], 2)} | "
            f"{_fmt_num(s['solver_same_seeds'])} | "
            f"{_fmt_pct_ci(s['ratio'], s['ratio_lo'], s['ratio_hi'])} | "
            f"{_fmt_pct_ci(s['luck_adjusted_ratio'], s['luck_adjusted_lo'], s['luck_adjusted_hi'])} |"
        )
    comp = report.get("paired_comparison") or {}
    if comp.get("shared_seeds"):
        lines.append("")
        lines.append(
            f"V1.4 ratio (paired n={len(comp['shared_seeds'])}): "
            f"{_fmt_pct_ci(comp['v14_ratio_shared'], *comp['v14_ratio_shared_ci95'])}"
        )
        lines.append(
            f"V1.6 ratio (paired n={len(comp['shared_seeds'])}): "
            f"{_fmt_pct_ci(comp['v16_ratio_shared'], *comp['v16_ratio_shared_ci95'])}"
        )
        lines.append(
            f"Delta (v1.6 - v1.4): ratio={comp['delta_ratio'] * 100:+.1f} pp, "
            f"score={comp['delta_score_mean']:+.3f} +/- {_fmt_num(comp['delta_score_ci95'])}, "
            f"ship_gate_pass={comp['ship_gate_pass']}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python scripts/eval_v16_social.py",
        description="Run OpenCode gemini-4-carbon on paired seeds for v1.4 and v1.6 social layer and print both ratios.",
    )
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--model", default="gemini-4-carbon")
    ap.add_argument("--v14-provider", default="template")
    ap.add_argument(
        "--v16-provider",
        "--provider",
        dest="v16_provider",
        default=os.environ.get("CANARY_V16_PROVIDER") or "social-v2",
    )
    ap.add_argument("--arms", default="v1.4,v1.6", help="comma-separated subset of v1.4,v1.6")
    ap.add_argument(
        "--v14-source",
        choices=("run", "committed"),
        default="run",
        help="run OpenCode live for v1.4 (default) or load data/runs/committed/v1.4",
    )
    ap.add_argument("--timeout", type=int, default=3600, help="per-episode OpenCode timeout in seconds (>=1)")
    ap.add_argument("--jobs", "--concurrency", dest="jobs", type=int, default=2)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--staging", default="/tmp/opencode/v16-eval-staging")
    ap.add_argument("--social-cache-dir", default="/tmp/opencode/v16-gemini-cache")
    ap.add_argument("--env", dest="env_vars", action="append", default=[], help="KEY=VALUE passed to v1.6 MCP server")
    ap.add_argument("--no-prewarm-social", action="store_true")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--dry-run", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout < 1:
        raise ValueError("--timeout must be >= 1")
    seeds = parse_seeds(args.seeds)
    wanted_arms = [x.strip() for x in args.arms.split(",") if x.strip()]
    for arm in wanted_arms:
        if arm not in ("v1.4", "v1.6"):
            raise ValueError(f"unknown arm {arm!r}; expected v1.4 and/or v1.6")

    env_overrides = parse_env_overrides(args.env_vars)
    runtime_env = ensure_runtime_env()
    staging = Path(args.staging)
    cache_dir = seed_social_cache_dir(Path(args.social_cache_dir))

    if "v1.6" in wanted_arms and not args.no_prewarm_social and not args.dry_run:
        warm = prewarm_social_cache(args.tier, seeds, args.v16_provider, cache_dir, runtime_env)
        print(
            f"[{time.strftime('%H:%M:%S')}] prewarmed {args.v16_provider} cache on {warm['seeds']} seeds "
            f"(new_calls={warm['calls']}, fallback_rejects={warm['rejects']})",
            flush=True,
        )

    ref_checks = verify_reference_and_baselines(args.tier, seeds, args.v16_provider, cache_dir, dry_run=args.dry_run)

    jobs_by_arm: dict[str, dict[int, EvalJob]] = {"v1.4": {}, "v1.6": {}}
    interleaved_jobs: list[EvalJob] = []
    for seed in seeds:
        if "v1.4" in wanted_arms and args.v14_source == "run":
            j14 = EvalJob("v1.4", args.v14_provider, args.tier, seed, args.model, args.timeout, staging, cache_dir, {})
            jobs_by_arm["v1.4"][seed] = j14
            interleaved_jobs.append(j14)
        if "v1.6" in wanted_arms:
            j16 = EvalJob(
                "v1.6",
                args.v16_provider,
                args.tier,
                seed,
                args.model,
                args.timeout,
                staging,
                cache_dir,
                env_overrides,
            )
            jobs_by_arm["v1.6"][seed] = j16
            interleaved_jobs.append(j16)

    if interleaved_jobs:
        run_jobs(interleaved_jobs, args.jobs, args.max_attempts, runtime_env, staging, dry_run=args.dry_run)

    if args.dry_run:
        print(
            f"Calibration ({args.tier} seeds {args.seeds}): "
            f"solver_v14={_fmt_num(ref_checks['solver_v14_mean'])} "
            f"solver_v16={_fmt_num(ref_checks['solver_v16_mean'])} "
            f"exact_match={ref_checks['solver_exact_match']} "
            f"do_nothing={_fmt_num(ref_checks['do_nothing_mean'])} "
            f"stop_early={_fmt_num(ref_checks['stop_early_mean'])}"
        )
        return 0

    arm_summaries: dict[str, Any] = {}
    if "v1.4" in wanted_arms or args.v14_source == "committed":
        eps14: dict[int, dict[str, Any]] | None = None
        inv14: dict[int, list[str]] = {}
        if args.v14_source == "committed":
            try:
                eps14 = load_committed_v14(args.tier, seeds, args.model)
            except (FileNotFoundError, ValueError):
                if "v1.4" in wanted_arms:
                    raise
        else:
            eps14 = {}
            for s, j in jobs_by_arm["v1.4"].items():
                eps = read_eps(j.dir)
                if eps and invalid_attempt_reason(j.dir, eps[-1]) is None:
                    eps14[s] = eps[-1]
                reasons = [
                    (d / "INVALID.txt").read_text().strip()
                    for d in j.invalid_dirs()
                    if (d / "INVALID.txt").is_file()
                ]
                if reasons:
                    inv14[s] = reasons
        if eps14 is not None:
            arm_summaries["v1.4"] = summarize_arm(
                "v1.4",
                args.v14_provider if args.v14_source == "run" else "template(committed)",
                args.tier,
                seeds,
                eps14,
                ref_checks["solver_v14"],
                inv14,
            )

    if "v1.6" in wanted_arms:
        eps16: dict[int, dict[str, Any]] = {}
        inv16: dict[int, list[str]] = {}
        for s, j in jobs_by_arm["v1.6"].items():
            eps = read_eps(j.dir)
            if eps and invalid_attempt_reason(j.dir, eps[-1]) is None:
                eps16[s] = eps[-1]
            reasons = [
                (d / "INVALID.txt").read_text().strip()
                for d in j.invalid_dirs()
                if (d / "INVALID.txt").is_file()
            ]
            if reasons:
                inv16[s] = reasons
        arm_summaries["v1.6"] = summarize_arm(
            "v1.6",
            args.v16_provider,
            args.tier,
            seeds,
            eps16,
            ref_checks["solver_v16"],
            inv16,
        )

    paired = compute_paired_comparison(
        seeds,
        arm_summaries.get("v1.4"),
        arm_summaries.get("v1.6"),
        ref_checks,
    )
    report = {
        "tier": args.tier,
        "seeds_spec": args.seeds,
        "seeds": seeds,
        "model": args.model,
        "timeout_s": args.timeout,
        "v14_source": args.v14_source,
        "v14_provider": args.v14_provider,
        "v16_provider": args.v16_provider,
        "env_overrides": env_overrides,
        "reference_checks": {
            k: v for k, v in ref_checks.items() if k not in ("solver_v14", "solver_v16")
        },
        "arms": arm_summaries,
        "paired_comparison": paired,
    }
    rendered = format_report(report)
    print(rendered, flush=True)
    if args.out_json:
        out_j = Path(args.out_json)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        out_j.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.out_md:
        out_m = Path(args.out_md)
        out_m.parent.mkdir(parents=True, exist_ok=True)
        out_m.write_text(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
