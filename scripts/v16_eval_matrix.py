"""V1.6 Paired Evaluation Harness for Canary social text variants."""
from __future__ import annotations

import argparse
import dataclasses
import fcntl
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.agents.frontier.common import empty_final_response
from canary.agents.frontier.opencode_run import normalize_model as normalize_oc_model
from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.agents.runlog import git_sha
from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.baselines import DoNothing, StopEarlyQuit
from canary.env import Env
from canary.llm.base import MissingKeyError
from canary.llm.stub import StubClient
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.text.template import TemplateProvider
from canary.types import EpisodeResult, Step

BACKOFF_SCHEDULE = (5.0, 15.0, 30.0)
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 42
OPENCODE_BIN_DIR = "/home/momin/momin/bin"
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
KEY_PATTERNS = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)


def parse_seed_spec(spec: str) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw_part in str(spec).split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
            if hi < lo:
                raise ValueError(f"invalid seed range: {part!r}")
            for s in range(lo, hi + 1):
                if s not in seen:
                    seen.add(s)
                    out.append(s)
        else:
            s = int(part)
            if s not in seen:
                seen.add(s)
                out.append(s)
    if not out:
        raise ValueError(f"no seeds parsed from {spec!r}")
    return out


def provider_spec_for_variant(variant: str) -> str:
    if variant == "v0_v14_control":
        return "template"
    return variant if ":" in variant else f"v16:{variant}"


def resolve_provider(variant: str, fake: bool = False) -> Any:
    if variant == "v0_v14_control":
        return TemplateProvider()
    spec = provider_spec_for_variant(variant)
    from canary.text import gemini as text_gemini

    if not fake:
        return text_gemini.get_provider(spec)
    try:
        return text_gemini.get_provider(spec)
    except (ValueError, MissingKeyError):
        return TemplateProvider()


def normalize_inproc_model(model: str) -> str:
    m = model.strip()
    if m.startswith("opencode:"):
        m = m.split(":", 1)[1]
    if m.startswith("google/"):
        return f"gemini:{m.split('/', 1)[1]}"
    if m.startswith("openai/"):
        return f"openai:{m.split('/', 1)[1]}"
    if ":" in m:
        return m
    if m.startswith("gemini"):
        return f"gemini:{m}"
    return m


def normalize_opencode_model(model: str) -> str:
    m = model.strip()
    if m.startswith("opencode:"):
        m = m.split(":", 1)[1]
    if m.startswith("gemini:"):
        m = m.split(":", 1)[1]
    elif m.startswith("openai:"):
        return f"openai/{m.split(':', 1)[1]}"
    return normalize_oc_model(m)


def backoff_seconds(retry_number: int) -> float:
    idx = max(0, min(retry_number - 1, len(BACKOFF_SCHEDULE) - 1))
    return float(BACKOFF_SCHEDULE[idx])


def invalid_episode_reason(
    res: EpisodeResult | None,
    *,
    model_tool_calls: int | None = None,
    opencode_empty_reply: bool = False,
) -> str | None:
    if res is None:
        return "missing_result"
    if getattr(res, "valid", True) is False:
        return "res_valid_false"
    meta = getattr(res, "meta", None) or {}
    if meta.get("valid") is False:
        return f"meta_valid_false:{meta.get('error', '')}"
    if meta.get("rc") == "timeout":
        return "timeout"
    if getattr(res, "end_reason", None) == "error":
        return f"end_reason_error:{meta.get('error', '')}"
    if meta.get("error"):
        return f"meta_error:{meta.get('error')}"
    steps = getattr(res, "steps", None) or []
    if len(steps) == 0:
        return "zero_steps"
    if model_tool_calls is not None and model_tool_calls <= 0:
        return "zero_model_tool_calls"
    if opencode_empty_reply:
        return "empty_final_response"
    return None


def make_fake_client(seed: int) -> StubClient:
    emp = f"e{seed % 12:02d}"
    script = [
        {"tool_calls": [{"id": f"fake_{seed}_0", "name": "list_employees", "args": {}}]},
        {"tool_calls": [{"id": f"fake_{seed}_1", "name": "status", "args": {}}]},
        {"tool_calls": [{"id": f"fake_{seed}_2", "name": "advance_day", "args": {}}]},
        {"tool_calls": [{"id": f"fake_{seed}_3", "name": "accuse", "args": {"employee": emp}}]},
    ]
    return StubClient(script=script, model="fake-gemini")


class _DeadlinePolicy:
    def __init__(self, inner: Any, hard_deadline: float, cancel_event: threading.Event, timeout_s: float):
        self._inner = inner
        self._hard_deadline = hard_deadline
        self._cancel = cancel_event
        self._timeout_s = float(timeout_s)
        self.name = inner.name

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self._inner.reset(tools_spec, instruction)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        now = time.monotonic()
        if self._cancel.is_set() or now > self._hard_deadline:
            raise TimeoutError(f"episode exceeded timeout {self._timeout_s}s")
        t_step = now
        out = self._inner.act(history)
        after = time.monotonic()
        if self._cancel.is_set() or (after - t_step) > self._timeout_s or after > self._hard_deadline:
            raise TimeoutError(f"episode exceeded timeout {self._timeout_s}s")
        return out


def count_model_tool_calls(transcript: list[dict[str, Any]]) -> int:
    return sum(len(m.get("tool_calls") or []) for m in transcript if m.get("role") == "assistant")


def run_inproc_attempt(
    *,
    tier: str,
    seed: int,
    variant: str,
    model: str,
    episode_timeout: float,
    fake: bool,
    env_factory: Callable[[str, int, Any], Any] | None = None,
    client_factory: Callable[[int], Any] | None = None,
) -> tuple[EpisodeResult, list[dict[str, Any]] | None, str | None]:
    provider = resolve_provider(variant, fake=fake)
    env = env_factory(tier, seed, provider) if env_factory is not None else Env(tier=tier, seed=seed, text_provider=provider)
    spec = normalize_inproc_model(model)
    client = client_factory(seed) if client_factory is not None else (make_fake_client(seed) if fake else None)
    if not fake and client is None:
        os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "12")
        os.environ.setdefault("CANARY_GEMINI_TIMEOUT_S", str(int(max(30.0, min(episode_timeout, 240.0)))))
    pol = LLMPolicy(spec, context="full", client=client)
    cancel_ev = threading.Event()
    ep_to = float(episode_timeout)
    hard_to = ep_to if ep_to < 10.0 else max(ep_to * 4.0, 3600.0)
    hard_deadline = time.monotonic() + hard_to
    wrapped = _DeadlinePolicy(pol, hard_deadline=hard_deadline, cancel_event=cancel_ev, timeout_s=ep_to)
    t0 = time.monotonic()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(run_episode, env, wrapped, pol.name)
        res = fut.result(timeout=hard_to)
    except FuturesTimeoutError:
        cancel_ev.set()
        err_res = EpisodeResult(
            tier=tier,
            seed=seed,
            agent=pol.name,
            steps=[],
            score=0.0,
            accused=None,
            correct=False,
            final_day=0,
            end_reason="error",
            meta={"error": f"TimeoutError: episode exceeded {episode_timeout}s", "valid": False, "rc": "timeout"},
        )
        return err_res, pol.transcript, "timeout"
    except Exception as exc:
        cancel_ev.set()
        err_res = EpisodeResult(
            tier=tier,
            seed=seed,
            agent=pol.name,
            steps=[],
            score=0.0,
            accused=None,
            correct=False,
            final_day=0,
            end_reason="error",
            meta={"error": f"{type(exc).__name__}: {exc}", "valid": False},
        )
        return err_res, pol.transcript, f"exception:{type(exc).__name__}"
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    wall_s = round(time.monotonic() - t0, 2)
    res.meta = {
        **(res.meta or {}),
        "usage": dict(pol.usage),
        "context": "full",
        "variant": variant,
        "fake": bool(fake),
        "wall_s": wall_s,
    }
    if hasattr(pol._client, "settings"):
        res.meta["provider_settings"] = pol._client.settings()
    n_tc = count_model_tool_calls(pol.transcript)
    reason = invalid_episode_reason(res, model_tool_calls=n_tc)
    return res, pol.transcript, reason


def run_opencode_attempt(
    *,
    tier: str,
    seed: int,
    variant: str,
    model: str,
    episode_timeout: float,
    attempt_dir: Path,
    fake: bool,
    env_factory: Callable[[str, int, Any], Any] | None = None,
    client_factory: Callable[[int], Any] | None = None,
) -> tuple[EpisodeResult, Any, str | None]:
    if fake:
        res, tr, reason = run_inproc_attempt(
            tier=tier,
            seed=seed,
            variant=variant,
            model=model,
            episode_timeout=episode_timeout,
            fake=True,
            env_factory=env_factory,
            client_factory=client_factory,
        )
        res.agent = f"opencode:{normalize_opencode_model(model)}"
        return res, tr, reason

    if attempt_dir.exists():
        shutil.rmtree(attempt_dir, ignore_errors=True)
    attempt_dir.parent.mkdir(parents=True, exist_ok=True)
    oc_model = normalize_opencode_model(model)
    env = dict(os.environ)
    env["CANARY_PROVIDER"] = provider_spec_for_variant(variant)
    cur_path = env.get("PATH", "")
    env["PATH"] = f"{OPENCODE_BIN_DIR}:{cur_path}" if cur_path else OPENCODE_BIN_DIR
    env["PYTHONPATH"] = str(REPO_ROOT)
    cmd = [
        sys.executable,
        "-m",
        "canary.agents.frontier.opencode_run",
        "--model",
        oc_model,
        "--tier",
        tier,
        "--seeds",
        str(seed),
        "--jobs",
        "1",
        "--retries",
        "0",
        "--timeout",
        str(max(1, int(episode_timeout))),
        "--out",
        str(attempt_dir),
    ]
    try:
        subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=float(episode_timeout) + 60.0,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(attempt_dir, ignore_errors=True)
        err_res = EpisodeResult(
            tier=tier,
            seed=seed,
            agent=f"opencode:{oc_model}",
            steps=[],
            score=0.0,
            accused=None,
            correct=False,
            final_day=0,
            end_reason="error",
            meta={"error": f"TimeoutExpired: exceeded {episode_timeout}s", "valid": False, "rc": "timeout"},
        )
        return err_res, None, "timeout"

    ep_file = attempt_dir / "episodes.jsonl"
    if not ep_file.is_file():
        shutil.rmtree(attempt_dir, ignore_errors=True)
        err_res = EpisodeResult(
            tier=tier,
            seed=seed,
            agent=f"opencode:{oc_model}",
            steps=[],
            score=0.0,
            accused=None,
            correct=False,
            final_day=0,
            end_reason="error",
            meta={"error": "no episodes.jsonl produced", "valid": False},
        )
        return err_res, None, "missing_episodes_jsonl"

    lines = [ln for ln in ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        shutil.rmtree(attempt_dir, ignore_errors=True)
        err_res = EpisodeResult(
            tier=tier,
            seed=seed,
            agent=f"opencode:{oc_model}",
            steps=[],
            score=0.0,
            accused=None,
            correct=False,
            final_day=0,
            end_reason="error",
            meta={"error": "empty episodes.jsonl", "valid": False},
        )
        return err_res, None, "empty_episodes_jsonl"

    res = to_result(json.loads(lines[-1]))
    tr_file = attempt_dir / "transcripts" / f"{seed}.txt"
    tr_text = tr_file.read_text(encoding="utf-8", errors="replace") if tr_file.is_file() else ""
    oc_empty = bool(tr_text and empty_final_response(tr_text))
    shutil.rmtree(attempt_dir, ignore_errors=True)
    reason = invalid_episode_reason(res, opencode_empty_reply=oc_empty)
    return res, tr_text or None, reason


def load_checkpoint_episodes(ckpt_file: Path, tier: str, fake: bool = False) -> dict[int, EpisodeResult]:
    completed: dict[int, EpisodeResult] = {}
    if not ckpt_file.is_file():
        return completed
    for line in ckpt_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if not isinstance(d, dict) or d.get("tier") != tier:
            continue
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        if d.get("valid") is False or meta.get("valid") is False:
            continue
        if not (d.get("valid") is True or meta.get("valid") is True):
            continue
        if bool(meta.get("fake", False)) != bool(fake):
            continue
        ep = to_result(d)
        if invalid_episode_reason(ep) is None:
            completed[int(ep.seed)] = ep
    return completed


def append_valid_checkpoint(
    ckpt_dir: Path,
    ep: EpisodeResult,
    transcript: Any,
    lock: threading.Lock,
    fake: bool = False,
) -> None:
    ep.meta = {**(ep.meta or {}), "valid": True, "fake": bool(fake)}
    rec = dataclasses.asdict(ep)
    rec["valid"] = True
    line = json.dumps(rec, sort_keys=True, default=str)
    with lock:
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        with (ckpt_dir / "episodes.jsonl").open("a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(line + "\n")
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        if transcript is not None:
            tr_dir = ckpt_dir / "transcripts"
            tr_dir.mkdir(parents=True, exist_ok=True)
            if isinstance(transcript, str):
                (tr_dir / f"seed_{ep.seed}.txt").write_text(transcript, encoding="utf-8")
            else:
                (tr_dir / f"seed_{ep.seed}.json").write_text(
                    json.dumps(transcript, indent=1, default=str),
                    encoding="utf-8",
                )


def append_invalid_attempt_log(
    ckpt_dir: Path,
    seed: int,
    attempt: int,
    reason: str,
    lock: threading.Lock,
) -> None:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": seed,
        "attempt": attempt,
        "reason": reason,
        "valid": False,
    }
    with lock:
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        with (ckpt_dir / "invalid_attempts.jsonl").open("a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def replay_verify_episode(
    ep: EpisodeResult,
    tier: str,
    variant: str,
    fake: bool = False,
    env_factory: Callable[[str, int, Any], Any] | None = None,
) -> tuple[bool, float | None]:
    provider = resolve_provider(variant, fake=fake)
    env = env_factory(tier, ep.seed, provider) if env_factory is not None else Env(tier=tier, seed=ep.seed, text_provider=provider)
    for st in ep.steps:
        if env.done:
            break
        env.call(st.tool, dict(st.args or {}))
    rep = env.result("replay")
    v_val = getattr(env, "V", getattr(env, "v", None))
    ok = (
        abs(float(rep.score) - float(ep.score)) < 1e-9
        and bool(rep.correct) == bool(ep.correct)
        and rep.accused == ep.accused
    )
    return ok, (float(v_val) if v_val is not None else None)


def episode_posterior_and_luck(
    ep: EpisodeResult,
    fallback_v: float | None = None,
) -> tuple[float | None, float | None, float]:
    if not ep.accused:
        return None, None, 0.0
    row = audit_episode(ep)
    p_acc = row.get("p_accused")
    if p_acc is None:
        params = tier_params_for_episode(ep.tier, ep.steps)
        sp = SolverPolicy(params)
        sp.obs.employees = [f"e{k:02d}" for k in range(params.n_employees)]
        for idx, st in enumerate(ep.steps):
            if st.tool == "accuse":
                for prev in ep.steps[sp.seen:idx]:
                    sp._ingest(prev)
                sp.seen = idx
                post = sp.belief()
                p_acc = round(post.get(st.args.get("employee"), 0.0), 3) if post else None
                break
        if p_acc is None:
            p_acc = round(1.0 / max(1, params.n_employees), 3)
    meta = ep.meta or {}
    v_raw = meta.get("V", meta.get("V_final", fallback_v))
    if v_raw is None:
        v_raw = float(ep.score) if ep.correct else 1.0
    p_val = float(p_acc)
    v_val = float(v_raw)
    luck = p_val * v_val - (1.0 - p_val)
    return p_val, v_val, luck


def bootstrap_mean_ci(
    xs: list[float],
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    n = len(xs)
    if n == 0:
        return None, None
    rng = random.Random(seed)
    vals = []
    for _ in range(n_resamples):
        vals.append(sum(xs[rng.randrange(n)] for _ in range(n)) / n)
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[max(0, int(0.975 * len(vals)) - 1)]
    return lo, hi


def paired_bootstrap_ratio_ci(
    num: list[float],
    den: list[float],
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if len(num) != len(den) or len(num) == 0:
        return None, None
    n = len(num)
    rng = random.Random(seed)
    vals: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        den_m = sum(den[i] for i in idx) / n
        if den_m > 0.0:
            num_m = sum(num[i] for i in idx) / n
            vals.append(num_m / den_m)
    if not vals:
        return None, None
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[max(0, int(0.975 * len(vals)) - 1)]
    return lo, hi


def assert_clean_output(payload: Any) -> None:
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
    dumped = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    for rx in KEY_PATTERNS:
        if rx.search(dumped):
            raise ValueError("secret key pattern detected in serialized output")


def evaluate_matrix(
    *,
    variant: str,
    tier: str,
    seeds: list[int],
    harness: str = "inproc",
    model: str = "gemini:gemini-4-carbon",
    jobs: int = 3,
    max_retries: int = 3,
    episode_timeout: float = 900.0,
    scratch_dir: str | Path = "/tmp/fleet-momin/shared/v16_runs",
    out_path: str | Path | None = None,
    fake: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    attempt_runner: Callable[[int, int], tuple[EpisodeResult, Any, str | None]] | None = None,
    env_factory: Callable[[str, int, Any], Any] | None = None,
    client_factory: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    if harness not in ("inproc", "opencode"):
        raise ValueError(f"unknown harness: {harness!r}")
    ckpt_dir = Path(scratch_dir) / harness / variant.replace(":", "__") / tier
    ckpt_file = ckpt_dir / "episodes.jsonl"
    ckpt_lock = threading.Lock()

    completed = load_checkpoint_episodes(ckpt_file, tier=tier, fake=bool(fake))
    missing_seeds = [s for s in seeds if s not in completed]
    if completed:
        resumed_in_set = [s for s in seeds if s in completed]
        if resumed_in_set:
            print(
                f"[v16_eval] resumed {len(resumed_in_set)}/{len(seeds)} valid seeds from {ckpt_file}: {resumed_in_set}",
                file=sys.stderr,
                flush=True,
            )

    def _run_seed(seed: int) -> EpisodeResult:
        last_reason = "unknown"
        for attempt_idx in range(max_retries + 1):
            if attempt_idx > 0:
                wait_s = backoff_seconds(attempt_idx)
                print(
                    f"[v16_eval] seed {seed}: retry {attempt_idx}/{max_retries} after {wait_s:.0f}s ({last_reason})",
                    file=sys.stderr,
                    flush=True,
                )
                sleep_fn(wait_s)
            else:
                print(f"[v16_eval] seed {seed}: starting", file=sys.stderr, flush=True)
            try:
                if attempt_runner is not None:
                    res, tr, reason = attempt_runner(seed, attempt_idx)
                    if reason is None:
                        reason = invalid_episode_reason(res)
                elif harness == "inproc":
                    res, tr, reason = run_inproc_attempt(
                        tier=tier,
                        seed=seed,
                        variant=variant,
                        model=model,
                        episode_timeout=episode_timeout,
                        fake=fake,
                        env_factory=env_factory,
                        client_factory=client_factory,
                    )
                else:
                    att_dir = ckpt_dir / "attempts" / f"seed_{seed}_try_{attempt_idx}"
                    res, tr, reason = run_opencode_attempt(
                        tier=tier,
                        seed=seed,
                        variant=variant,
                        model=model,
                        episode_timeout=episode_timeout,
                        attempt_dir=att_dir,
                        fake=fake,
                        env_factory=env_factory,
                        client_factory=client_factory,
                    )
            except Exception as exc:
                res = None
                tr = None
                reason = f"exception:{type(exc).__name__}:{exc}"

            if reason is None and res is not None:
                res.meta = {**(res.meta or {}), "attempts": attempt_idx + 1, "valid": True, "fake": bool(fake)}
                append_valid_checkpoint(ckpt_dir, res, tr, ckpt_lock, fake=bool(fake))
                print(
                    f"[v16_eval] seed {seed} DONE: score={res.score:+.3f} correct={res.correct} "
                    f"accused={res.accused} day={res.final_day} steps={len(res.steps)} attempts={attempt_idx + 1}",
                    file=sys.stderr,
                    flush=True,
                )
                return res

            last_reason = reason or "invalid_unknown"
            append_invalid_attempt_log(ckpt_dir, seed, attempt_idx + 1, last_reason, ckpt_lock)

        raise RuntimeError(f"seed {seed} failed all {max_retries + 1} attempts (last reason: {last_reason})")

    if missing_seeds:
        with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
            fresh_results = list(pool.map(_run_seed, missing_seeds))
        for ep in fresh_results:
            completed[int(ep.seed)] = ep

    ordered_gemini = [completed[s] for s in seeds]

    per_seed: list[dict[str, Any]] = []
    gemini_scores: list[float] = []
    solver_scores: list[float] = []
    solver_v14_scores: list[float] = []
    dn_scores: list[float] = []
    dn_v14_scores: list[float] = []
    se_scores: list[float] = []
    se_v14_scores: list[float] = []
    gemini_luck: list[float] = []
    solver_luck: list[float] = []
    gemini_ps: list[float] = []
    solver_ps: list[float] = []
    gemini_acc_days: list[int] = []
    solver_acc_days: list[int] = []
    replay_ok_count = 0

    usage_total = {
        "in": 0,
        "out": 0,
        "cached_in": 0,
        "calls": 0,
        "cost_usd": 0.0,
        "cost_usd_est": 0.0,
    }

    for seed, gem_ep in zip(seeds, ordered_gemini):
        make_e = env_factory if env_factory is not None else (lambda t, sd, pr: Env(tier=t, seed=sd, text_provider=pr))
        dn_ep = run_episode(make_e(tier, seed, resolve_provider(variant, fake=fake)), DoNothing(seed=seed))
        dn_v14_ep = run_episode(make_e(tier, seed, TemplateProvider()), DoNothing(seed=seed))
        se_ep = run_episode(make_e(tier, seed, resolve_provider(variant, fake=fake)), StopEarlyQuit(seed=seed))
        se_v14_ep = run_episode(make_e(tier, seed, TemplateProvider()), StopEarlyQuit(seed=seed))
        sol_ep = run_episode(make_e(tier, seed, resolve_provider(variant, fake=fake)), SolverPolicy())
        sol_v14_ep = run_episode(make_e(tier, seed, TemplateProvider()), SolverPolicy())

        rep_ok, rep_v = replay_verify_episode(
            gem_ep,
            tier=tier,
            variant=variant,
            fake=fake,
            env_factory=env_factory,
        )
        if rep_ok:
            replay_ok_count += 1

        gem_p, gem_v, gem_la = episode_posterior_and_luck(gem_ep, fallback_v=rep_v)
        sol_p, sol_v, sol_la = episode_posterior_and_luck(sol_ep)

        gemini_scores.append(float(gem_ep.score))
        solver_scores.append(float(sol_ep.score))
        solver_v14_scores.append(float(sol_v14_ep.score))
        dn_scores.append(float(dn_ep.score))
        dn_v14_scores.append(float(dn_v14_ep.score))
        se_scores.append(float(se_ep.score))
        se_v14_scores.append(float(se_v14_ep.score))
        gemini_luck.append(float(gem_la))
        solver_luck.append(float(sol_la))

        if gem_ep.accused:
            gemini_acc_days.append(int(gem_ep.final_day))
            if gem_p is not None:
                gemini_ps.append(float(gem_p))
        if sol_ep.accused:
            solver_acc_days.append(int(sol_ep.final_day))
            if sol_p is not None:
                solver_ps.append(float(sol_p))

        u = (gem_ep.meta or {}).get("usage") or {}
        usage_total["in"] += int(u.get("in", 0) or 0)
        usage_total["out"] += int(u.get("out", 0) or 0)
        usage_total["cached_in"] += int(u.get("cached_in", 0) or 0)
        usage_total["calls"] += int(u.get("calls", u.get("llm_calls", 0)) or 0)
        usage_total["cost_usd"] = round(
            usage_total["cost_usd"] + float(u.get("cost_usd", u.get("cost_usd_upper", 0.0)) or 0.0),
            6,
        )
        usage_total["cost_usd_est"] = round(
            usage_total["cost_usd_est"] + float(u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0),
            6,
        )

        per_seed.append({
            "seed": int(seed),
            "gemini_score": round(float(gem_ep.score), 6),
            "gemini_correct": bool(gem_ep.correct),
            "gemini_accused": gem_ep.accused,
            "gemini_final_day": int(gem_ep.final_day),
            "gemini_end_reason": gem_ep.end_reason,
            "gemini_step_count": len(gem_ep.steps),
            "gemini_v_accuse": round(gem_v, 6) if gem_v is not None else None,
            "gemini_p_accused": round(gem_p, 6) if gem_p is not None else None,
            "gemini_luck_adjusted": round(gem_la, 6),
            "replay_verified": bool(rep_ok),
            "solver_score": round(float(sol_ep.score), 6),
            "solver_v14_score": round(float(sol_v14_ep.score), 6),
            "solver_correct": bool(sol_ep.correct),
            "solver_accused": sol_ep.accused,
            "solver_final_day": int(sol_ep.final_day),
            "solver_v_accuse": round(sol_v, 6) if sol_v is not None else None,
            "solver_p_accused": round(sol_p, 6) if sol_p is not None else None,
            "solver_luck_adjusted": round(sol_la, 6),
            "do_nothing_score": round(float(dn_ep.score), 6),
            "stop_early_score": round(float(se_ep.score), 6),
        })

    n = len(seeds)
    gemini_mean = sum(gemini_scores) / n
    solver_mean = sum(solver_scores) / n
    solver_v14_mean = sum(solver_v14_scores) / n
    do_nothing_mean = sum(dn_scores) / n
    do_nothing_v14_mean = sum(dn_v14_scores) / n
    stop_early_mean = sum(se_scores) / n
    stop_early_v14_mean = sum(se_v14_scores) / n
    solver_calibration_diff = solver_mean - solver_v14_mean
    solver_calibration_max_abs_diff = max(
        (abs(a - b) for a, b in zip(solver_scores, solver_v14_scores)),
        default=0.0,
    )

    gemini_vs_solver_ratio = (gemini_mean / solver_mean) if solver_mean > 0.0 else None
    ratio_lo, ratio_hi = paired_bootstrap_ratio_ci(gemini_scores, solver_scores)
    gem_lo, gem_hi = bootstrap_mean_ci(gemini_scores)

    paired_diffs = [g - s for g, s in zip(gemini_scores, solver_scores)]
    paired_diff_mean = sum(paired_diffs) / n
    diff_lo, diff_hi = bootstrap_mean_ci(paired_diffs)

    luck_adj_mean = sum(gemini_luck) / n
    solver_luck_adj_mean = sum(solver_luck) / n
    luck_adj_ratio = (luck_adj_mean / solver_luck_adj_mean) if solver_luck_adj_mean > 0.0 else None
    luck_ratio_lo, luck_ratio_hi = paired_bootstrap_ratio_ci(gemini_luck, solver_luck)
    luck_lo, luck_hi = bootstrap_mean_ci(gemini_luck)

    luck_diffs = [g - s for g, s in zip(gemini_luck, solver_luck)]
    luck_diff_mean = sum(luck_diffs) / n
    luck_diff_lo, luck_diff_hi = bootstrap_mean_ci(luck_diffs)

    accuracy = sum(1 for ep in ordered_gemini if ep.correct) / n
    solver_accuracy = sum(1 for r in per_seed if r["solver_correct"]) / n
    accusation_rate = sum(1 for ep in ordered_gemini if ep.accused) / n
    solver_accusation_rate = sum(1 for r in per_seed if r["solver_accused"]) / n
    mean_accuse_day = (sum(gemini_acc_days) / len(gemini_acc_days)) if gemini_acc_days else None
    solver_mean_accuse_day = (sum(solver_acc_days) / len(solver_acc_days)) if solver_acc_days else None
    mean_p_accused = (sum(gemini_ps) / len(gemini_ps)) if gemini_ps else None
    solver_mean_p_accused = (sum(solver_ps) / len(solver_ps)) if solver_ps else None

    replay_rate = replay_ok_count / n
    gate_dn = abs(do_nothing_mean) < 1e-12 and abs(do_nothing_v14_mean) < 1e-12
    gate_se = abs(stop_early_mean) < 1e-12 and abs(stop_early_v14_mean) < 1e-12
    gate_cal = abs(solver_calibration_diff) < 1e-12
    gate_rep = (replay_ok_count == n) if harness == "inproc" else True
    gates = {
        "do_nothing_zero": bool(gate_dn),
        "stop_early_zero": bool(gate_se),
        "solver_calibration_zero": bool(gate_cal),
        "replay_verified": bool(gate_rep),
        "all_passed": bool(gate_dn and gate_se and gate_cal and gate_rep),
    }

    def _r(val: float | None) -> float | None:
        return round(float(val), 6) if val is not None else None

    payload: dict[str, Any] = {
        "variant": variant,
        "provider_spec": provider_spec_for_variant(variant),
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "harness": harness,
        "model": normalize_inproc_model(model) if harness == "inproc" else f"opencode:{normalize_opencode_model(model)}",
        "fake": bool(fake),
        "git_sha": git_sha(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_seeds": n,
        "seeds": [int(s) for s in seeds],
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "gemini_mean": _r(gemini_mean),
        "gemini_ci_95": [_r(gem_lo), _r(gem_hi)],
        "solver_mean": _r(solver_mean),
        "solver_v14_mean": _r(solver_v14_mean),
        "gemini_vs_solver_ratio": _r(gemini_vs_solver_ratio),
        "gemini_vs_solver_ratio_ci_95": [_r(ratio_lo), _r(ratio_hi)],
        "paired_diff_mean": _r(paired_diff_mean),
        "paired_diff_ci_95": [_r(diff_lo), _r(diff_hi)],
        "luck_adj_mean": _r(luck_adj_mean),
        "luck_adj_ci_95": [_r(luck_lo), _r(luck_hi)],
        "solver_luck_adj_mean": _r(solver_luck_adj_mean),
        "luck_adj_ratio": _r(luck_adj_ratio),
        "luck_adj_ratio_ci_95": [_r(luck_ratio_lo), _r(luck_ratio_hi)],
        "luck_adj_diff_mean": _r(luck_diff_mean),
        "luck_adj_diff_ci_95": [_r(luck_diff_lo), _r(luck_diff_hi)],
        "accuracy": _r(accuracy),
        "solver_accuracy": _r(solver_accuracy),
        "accusation_rate": _r(accusation_rate),
        "solver_accusation_rate": _r(solver_accusation_rate),
        "mean_accuse_day": _r(mean_accuse_day),
        "solver_mean_accuse_day": _r(solver_mean_accuse_day),
        "mean_p_accused": _r(mean_p_accused),
        "solver_mean_p_accused": _r(solver_mean_p_accused),
        "do_nothing_mean": _r(do_nothing_mean),
        "do_nothing_v14_mean": _r(do_nothing_v14_mean),
        "stop_early_mean": _r(stop_early_mean),
        "stop_early_v14_mean": _r(stop_early_v14_mean),
        "solver_calibration_diff": _r(solver_calibration_diff),
        "solver_calibration_max_abs_diff": _r(solver_calibration_max_abs_diff),
        "replay_verified_count": int(replay_ok_count),
        "replay_verified_rate": _r(replay_rate),
        "gates": gates,
        "usage_total": usage_total,
        "per_seed": per_seed,
    }

    assert_clean_output(payload)

    if out_path is not None:
        out_file = Path(out_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="V1.6 paired evaluation harness for Canary social text variants.")
    ap.add_argument("--variant", default="v0_v14_control")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="30-39")
    ap.add_argument("--harness", choices=("inproc", "opencode"), default="inproc")
    ap.add_argument("--model", default="gemini:gemini-4-carbon")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--episode-timeout", type=float, default=900.0)
    ap.add_argument("--scratch-dir", default="/tmp/fleet-momin/shared/v16_runs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--fake", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seeds = parse_seed_spec(args.seeds)
    payload = evaluate_matrix(
        variant=args.variant,
        tier=args.tier,
        seeds=seeds,
        harness=args.harness,
        model=args.model,
        jobs=args.jobs,
        max_retries=args.max_retries,
        episode_timeout=args.episode_timeout,
        scratch_dir=args.scratch_dir,
        out_path=args.out,
        fake=bool(args.fake),
    )
    print(json.dumps({
        "variant": payload["variant"],
        "tier": payload["tier"],
        "harness": payload["harness"],
        "n_seeds": payload["n_seeds"],
        "gemini_mean": payload["gemini_mean"],
        "solver_mean": payload["solver_mean"],
        "gemini_vs_solver_ratio": payload["gemini_vs_solver_ratio"],
        "gemini_vs_solver_ratio_ci_95": payload["gemini_vs_solver_ratio_ci_95"],
        "luck_adj_mean": payload["luck_adj_mean"],
        "solver_luck_adj_mean": payload["solver_luck_adj_mean"],
        "luck_adj_ratio": payload["luck_adj_ratio"],
        "luck_adj_ratio_ci_95": payload["luck_adj_ratio_ci_95"],
        "gates": payload["gates"],
    }, indent=2, sort_keys=True))
    return 0 if payload["gates"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
