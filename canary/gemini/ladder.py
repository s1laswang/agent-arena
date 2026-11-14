"""The Gemini Ladder: a thinking-to-competence curve across the Gemini family on Canary.

    python -m canary.gemini.ladder --models gemini-3.8-flash,gemini-4-carbon --levels low,high \
        --tiers medium,hard --seeds 0-9 --out ~/agent-arena-data/gemini/ladder/run1 \
        [--seeds-for gemini-4=0-5] [--shard i/n] [--concurrency K] [--model-cap gemini-4-carbon=8] \
        [--max-episodes N] [--dry-run] [--probe]

One cell = (model, thinking_level, tier, seed) = one in-process episode played by the frontier measurement's own
runner, `canary.agents.play.main` (LLMPolicy, full-history context, thought-signature replay; the same path
scripts/gemini_runner.py launches for its "inproc" harness), with the client built by
`canary.gemini.lab_client(f"gemini:{model}", feature="ladder", thinking_level=level)` so every Gemini call lands in
the usage ledger. Level "default" sends no thinking_level (the model default). Infra failures are classified by
scripts/gemini_runner.infra_reason (harness "inproc"), so "valid" means the same thing as in the measurement.

Lane: gemini-4-carbon at the model default is the AfterQuery measurement's cell (branch justSilas-gemini,
data/runs/committed/v1.4/inproc-gemini-4-carbon); the ladder imports it read-only and never reruns it.

Layout (each cell is a valid data/runs directory: canary.analysis.gap.load_runs / tags / paired scripts read it):
    OUT/<model>/<level>/<tier>/<seed>/episodes.jsonl      finished episode (one line; meta.ladder = labels)
    OUT/<model>/<level>/<tier>/<seed>/meta.json           play.py's meta + model, thinking level, tokens
    OUT/<model>/<level>/<tier>/<seed>/transcripts/<seed>.json
    OUT/<model>/<level>/<tier>/<seed>/RUNNING.json        in flight (host, pid); stale markers are ignored
    OUT/_invalid/<model>-<level>-<tier>-<seed>-<ts>/      infra-failed attempt + INVALID.txt; re-queued up to
                                                           --max-attempts, never scored
    OUT/_ledger/<host>-<pid>.jsonl                        Gemini usage ledger rows (feature=ladder)
    OUT/_progress.jsonl                                   one line per finished attempt
Resumable: rerun the same command; finished cells are skipped. `--shard i/n` takes every n-th cell of the
deterministic (slowest-first) cell order, so Slurm array tasks are disjoint.

Worlds: v1.4 public dev seeds (0..9999, HMAC key b"public": exact, reproducible from code, and the same worlds as
the measurement and its reference solver/baselines, seeds 0-29). Judge (900000-900039) and held-out
(800000-800199) seeds are refused.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

FEATURE = "ladder"
LEVELS = ("default", "minimal", "low", "medium", "high", "xhigh")
DEFAULT_MODELS = ("gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash",
                  "gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon")
# slowest first so the long gemini-4 / high-thinking episodes start early (scheduling only)
_MODEL_COST = {"gemini-4-carbon": 6, "gemini-4-argon": 5, "gemini-4-hydrogen": 4, "gemini-3.8-flash": 3,
               "gemini-3.5-flash": 2, "gemini-3.1-flash-lite": 1}
_LEVEL_COST = {"xhigh": 6, "high": 5, "default": 4, "medium": 3, "low": 2, "minimal": 1}
_TIER_COST = {"hard": 2, "medium": 1, "easy": 0}
HOST = socket.gethostname().split(".")[0]


# --------------------------------------------------------------------------- grid
@dataclasses.dataclass(frozen=True)
class Cell:
    model: str
    level: str
    tier: str
    seed: int

    @property
    def key(self) -> str:
        return f"{self.model}/{self.level}/{self.tier}/{self.seed}"

    @property
    def agent(self) -> str:
        """Episode `agent` field: one name per (model, level) so tag/paired tools group them apart."""
        return f"gemini:{self.model}+think:{self.level}"

    def dir(self, out: Path) -> Path:
        return Path(out) / self.model / self.level / self.tier / str(self.seed)


def parse_seed_spec(spec: str) -> list[int]:
    out: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            out.extend(range(a, b + 1))
        elif part:
            out.append(int(part))
    return out


def check_seeds(seeds: list[int]) -> None:
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
    bad = [s for s in seeds if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s < 0 or s >= 10_000]
    if bad:
        raise ValueError(f"ladder seeds must be public dev seeds 0..9999 (never judge/held-out); got {bad[:5]}")


def parse_overrides(items: list[str] | None) -> list[tuple[str, str]]:
    """['gemini-4=0-5', ...] -> [(prefix, value)], longest prefix wins at lookup."""
    out = []
    for it in items or []:
        for part in it.split(";"):
            if part.strip():
                k, _, v = part.partition("=")
                out.append((k.strip(), v.strip()))
    return sorted(out, key=lambda kv: -len(kv[0]))


def lookup(overrides: list[tuple[str, str]], model: str) -> str | None:
    return next((v for k, v in overrides if model.startswith(k)), None)


def expand_grid(models: list[str], levels: list[str], tiers: list[str], seeds: list[int],
                seeds_for: list[tuple[str, str]] | None = None,
                levels_for: list[tuple[str, str]] | None = None) -> list[Cell]:
    """All cells, slowest first (model, level, tier cost desc), then seed-major so every (model, level, tier)
    gets its first seeds early. Deterministic: the same arguments always give the same order."""
    cells = []
    for m in models:
        ss = parse_seed_spec(lookup(seeds_for or [], m)) if lookup(seeds_for or [], m) else seeds
        lv = lookup(levels_for or [], m)
        ls = [x for x in (lv.split("|") if lv else levels) if x]
        for lvl in ls:
            if lvl not in LEVELS:
                raise ValueError(f"unknown level {lvl!r}; known {LEVELS}")
            for t in tiers:
                for s in ss:
                    cells.append(Cell(m, lvl, t, s))
    check_seeds([c.seed for c in cells])
    rank = {s: i for i, s in enumerate(sorted({c.seed for c in cells}))}
    cells.sort(key=lambda c: (rank[c.seed] // 2,
                              -(_MODEL_COST.get(c.model, 3) * 10 + _LEVEL_COST.get(c.level, 3)) * 3 - _TIER_COST.get(c.tier, 1),
                              c.model, c.level, c.tier, c.seed))
    return cells


def shard(cells: list[Cell], spec: str | None) -> list[Cell]:
    if not spec:
        return cells
    i, n = (int(x) for x in spec.split("/"))
    if not (0 <= i < n):
        raise ValueError(f"--shard {spec}: need 0 <= i < n")
    return cells[i::n]


# --------------------------------------------------------------------------- cell state
def read_eps(d: Path) -> list[dict]:
    f = d / "episodes.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def is_done(out: Path, c: Cell) -> bool:
    eps = read_eps(c.dir(out))
    return bool(eps) and (eps[-1].get("meta") or {}).get("valid") is not False


def attempts(out: Path, c: Cell) -> int:
    inv = Path(out) / "_invalid"
    return len(list(inv.glob(f"{c.model}-{c.level}-{c.tier}-{c.seed}-*"))) if inv.exists() else 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def in_flight_elsewhere(out: Path, c: Cell) -> bool:
    """True if another live process on this host holds the cell (shards on other hosts are disjoint)."""
    f = c.dir(out) / "RUNNING.json"
    if not f.exists():
        return False
    try:
        r = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return r.get("host") == HOST and int(r.get("pid", -1)) != os.getpid() and _pid_alive(int(r["pid"]))


_INFRA = re.compile(r"ClientError|ServerError|APIError|RESOURCE_EXHAUSTED|UNAVAILABLE|INTERNAL|\b5\d\d\b|\b429\b|"
                    r"ConnectError|ConnectTimeout|ReadTimeout|ReadError|RemoteProtocolError|Server disconnected|"
                    r"Connection|Timeout|SSLError|ssl|MissingKeyError|LLMError", re.I)


def infra_reason(ep: dict) -> str | None:
    """Same rule as scripts/gemini_runner.py for the in-process harness: any exception out of the in-process
    loop comes from the API client, not from an agent decision -> infra, re-queued. Every other ending (wrong or
    no accusation, horizon, tool cap) counts as played."""
    if ep.get("end_reason") == "accused":
        return None
    m = ep.get("meta") or {}
    if m.get("valid") is False:
        return f"invalid: {str(m.get('error', ''))[:300]}"
    if ep.get("end_reason") == "error":
        err = str(m.get("error") or "")
        return f"api: {err[:300]}" if err else "api: episode ended with error and no message"
    return None


# --------------------------------------------------------------------------- clients
class TallyClient:
    """Wraps the ledgered client; tallies per-episode tokens incl. thinking and cached (for the report)."""

    def __init__(self, inner):
        self.inner = inner
        self.tally = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "latency_s": 0.0,
                      "max_call_s": 0.0}

    def __getattr__(self, name):
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages, **kw):
        t0 = time.time()
        r = self.inner.chat(messages, **kw)
        dt = time.time() - t0
        um = getattr(r.raw, "usage_metadata", None) if getattr(r, "raw", None) is not None else None

        def n(a):
            v = getattr(um, a, 0) if um is not None else 0
            return v if isinstance(v, int) else 0
        t = self.tally
        t["calls"] += 1
        t["latency_s"] = round(t["latency_s"] + dt, 2)
        t["max_call_s"] = round(max(t["max_call_s"], dt), 2)
        if um is not None:
            t["in"] += n("prompt_token_count")
            t["out"] += n("candidates_token_count")
            t["thinking"] += n("thoughts_token_count")
            t["cached"] += n("cached_content_token_count")
        else:
            u = getattr(r, "usage", None) or {}
            t["in"] += int(u.get("in", 0) or 0)
            t["out"] += int(u.get("out", 0) or 0)
        return r


def _sdk_client():
    """genai.Client for this process: through the FR8 gateway when GEMINI_GATEWAY_URL is set (no key on the
    compute node), else None (GeminiClient builds the direct client from .env)."""
    url = os.environ.get("GEMINI_GATEWAY_URL")
    if not url:
        return None
    from google import genai
    from google.genai import types
    timeout_ms = int(float(os.environ.get("CANARY_GEMINI_TIMEOUT_S", "600")) * 1000)
    try:
        from canary.gemini.gateway import gateway_http_options  # G1's helper, when merged
        opts = dict(gateway_http_options() or {})
    except Exception:  # noqa: BLE001
        opts = {"base_url": url}
    opts.setdefault("timeout", timeout_ms)
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or "gateway", http_options=types.HttpOptions(**opts))


def default_client_factory(c: Cell, run_id: str, meta: dict):
    from canary.gemini import lab_client
    kw: dict[str, Any] = {}
    if c.level != "default":
        kw["thinking_level"] = c.level
    sdk = _sdk_client()
    if sdk is not None:
        kw["sdk_client"] = sdk
    return lab_client(f"gemini:{c.model}", feature=FEATURE, run_id=run_id, meta=meta, **kw)


def _git_sha() -> str:
    from canary.agents.runlog import git_sha
    return git_sha()


# --------------------------------------------------------------------------- one cell
def _gemini_runner():
    """scripts/gemini_runner.py (the frontier measurement's driver), for its infra rule."""
    sd = str(Path(__file__).resolve().parents[2] / "scripts")
    if sd not in sys.path:
        sys.path.insert(0, sd)
    import gemini_runner
    return gemini_runner


def run_cell(out: Path, c: Cell, ladder_run: str, client_factory: Callable | None = None,
             play_argv_extra: list[str] | None = None, log: Callable[[str], None] = print) -> dict:
    """Play one cell with the measurement's own runner (canary.agents.play.main, in-process LLMPolicy, full
    history) and a ledgered client at the cell's thinking level; label the run dir; move infra failures to
    _invalid/ (rule: scripts/gemini_runner.infra_reason, harness "inproc"). Returns a progress row."""
    from canary.agents import play
    out = Path(out)
    d = c.dir(out)
    if d.exists():  # leftover from a killed attempt (no finished episode): start clean
        shutil.rmtree(d)
    d.mkdir(parents=True)
    t0 = time.time()
    (d / "RUNNING.json").write_text(json.dumps({"host": HOST, "pid": os.getpid(), "started": t0}))
    run_id = f"ladder:{ladder_run}:{c.key}"
    meta = {"ladder_run": ladder_run, "model": c.model, "level": c.level, "tier": c.tier, "seed": c.seed}
    client = None
    try:
        client = TallyClient((client_factory or default_client_factory)(c, run_id, meta))
        play.main(["--agent", f"gemini:{c.model}", "--tier", c.tier, "--seeds", str(c.seed), "--out", str(d),
                   *(play_argv_extra or [])], client=client)
    except Exception as e:  # noqa: BLE001  (client construction, missing key, ...): no episode -> infra
        (d / "ERROR.txt").write_text(f"{type(e).__name__}: {e}\n")
    wall = time.time() - t0
    tally = dict(client.tally) if client is not None else {}
    eps = read_eps(d)
    ep = eps[-1] if eps else None
    label = {**meta, "thinking_level": c.level, "label": f"{c.model} @ thinking={c.level}", "run_id": run_id,
             "wall_s": round(wall, 1), "tokens": tally, "attempt": attempts(out, c) + 1, "host": HOST,
             "gateway": bool(os.environ.get("GEMINI_GATEWAY_URL"))}
    if ep is not None:  # label the episode REAL: model + thinking level (agent field kept as play.py wrote it)
        ep.setdefault("meta", {})["ladder"] = label
        (d / "episodes.jsonl").write_text(json.dumps(ep, default=str) + "\n")
        mf = d / "meta.json"
        m = json.loads(mf.read_text()) if mf.exists() else {}
        m.update({"thinking_level": c.level, "label": label["label"], "feature": FEATURE, "ladder_run": ladder_run,
                  "run_id": run_id, "tokens": tally, "wall_s": round(wall, 1), "host": HOST,
                  "seed_key": "public (dev seed)", "smoke": False})
        mf.write_text(json.dumps(m, indent=1, default=str))
        reason = _gemini_runner().infra_reason("inproc", d, ep)
    else:
        err = (d / "ERROR.txt").read_text() if (d / "ERROR.txt").exists() else ""
        reason = f"no episode written: {err[:300]}"
    (d / "RUNNING.json").unlink(missing_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "cell": c.key, "score": ep and ep.get("score"),
           "correct": ep and ep.get("correct"), "end": ep and ep.get("end_reason"), "day": ep and ep.get("final_day"),
           "steps": len(ep.get("steps", [])) if ep else 0, "wall_s": round(wall, 1), "calls": tally.get("calls"),
           "thinking": tally.get("thinking"), "host": HOST, "infra_invalid": reason}
    if reason:
        dst = out / "_invalid" / f"{c.model}-{c.level}-{c.tier}-{c.seed}-{time.strftime('%H%M%S')}-{os.getpid()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d), str(dst))
        (dst / "INVALID.txt").write_text(reason + "\n")
    with _LOCK:
        with open(out / "_progress.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
    sc = ep.get("score") if ep else None
    log(f"DONE {c.key} score={sc if sc is None else round(sc, 3)} end={row['end']} day={row['day']} "
        f"calls={tally.get('calls')} think={tally.get('thinking')} wall={wall:.0f}s"
        f"{' INFRA-INVALID: ' + reason[:160] if reason else ''}")
    return row


_LOCK = threading.Lock()


# --------------------------------------------------------------------------- probe
def probe(models: list[str], levels: list[str], out: Path, log=print) -> list[dict]:
    """One tiny ledgered call per (model, level): which thinking levels does each model accept?"""
    from canary.gemini import lab_client
    rows = []
    for m in models:
        for lvl in levels:
            kw = {} if lvl == "default" else {"thinking_level": lvl}
            sdk = _sdk_client()
            if sdk is not None:
                kw["sdk_client"] = sdk
            t0 = time.time()
            try:
                c = lab_client(f"gemini:{m}", feature=FEATURE, run_id="ladder:probe", meta={"probe": True, "level": lvl},
                               max_retries=1, **kw)
                r = c.chat([{"role": "user", "content": "Reply with the single word OK."}])
                um = getattr(r.raw, "usage_metadata", None)
                th = getattr(um, "thoughts_token_count", 0) or 0
                rows.append({"model": m, "level": lvl, "ok": True, "text": (r.text or "")[:20], "thinking": th,
                             "latency_s": round(time.time() - t0, 2),
                             "model_version": getattr(r.raw, "model_version", None)})
            except Exception as e:  # noqa: BLE001
                rows.append({"model": m, "level": lvl, "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}",
                             "latency_s": round(time.time() - t0, 2)})
            log(json.dumps(rows[-1]))
    out.mkdir(parents=True, exist_ok=True)
    (out / "_probe.json").write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                                 "git_sha": _git_sha(), "rows": rows}, indent=1))
    return rows


# --------------------------------------------------------------------------- driver
def run_grid(out: Path, cells: list[Cell], concurrency: int = 4, max_episodes: int | None = None,
             max_attempts: int = 4, model_caps: dict[str, int] | None = None, ladder_run: str | None = None,
             client_factory: Callable | None = None, play_argv_extra: list[str] | None = None,
             log: Callable[[str], None] = print) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ladder_run = ladder_run or out.name
    todo = [c for c in cells if not is_done(out, c) and not in_flight_elsewhere(out, c)
            and attempts(out, c) < max_attempts]
    skipped = len(cells) - len(todo)
    if max_episodes is not None:
        todo = todo[:max_episodes]
    log(f"START ladder_run={ladder_run} cells={len(cells)} done/skipped={skipped} todo={len(todo)} "
        f"concurrency={concurrency} host={HOST} pid={os.getpid()}")
    caps = {m: threading.Semaphore(k) for m, k in (model_caps or {}).items()}
    pending: list[Cell] = list(todo)
    rows: list[dict] = []

    def work(c: Cell) -> dict:
        sem = next((s for m, s in caps.items() if c.model.startswith(m)), None)
        if sem:
            sem.acquire()
        try:
            for _ in range(max_attempts):
                try:
                    row = run_cell(out, c, ladder_run, client_factory, play_argv_extra, log)
                except Exception as e:  # noqa: BLE001  (bug in our own code: log, never kill the pool)
                    log(f"CRASH {c.key}: {type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
                    return {"cell": c.key, "crash": str(e)}
                if not row.get("infra_invalid") or attempts(out, c) >= max_attempts:
                    return row
                time.sleep(min(300, 30 * attempts(out, c)))  # let a rate limit / outage pass
            return row
        finally:
            if sem:
                sem.release()

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = []
        for c in pending:
            futs.append(ex.submit(work, c))
        for f in as_completed(futs):
            rows.append(f.result())
    done = sum(1 for c in cells if is_done(out, c))
    log(f"ALL DONE: {done}/{len(cells)} cells finished in {out}")
    return {"cells": len(cells), "done": done, "ran": len(rows), "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.ladder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--levels", default="low,medium,high")
    ap.add_argument("--levels-for", action="append", default=[],
                    help="per-model-prefix levels, e.g. 'gemini-3.1-flash-lite=minimal|low|medium|high'")
    ap.add_argument("--tiers", default="medium,hard")
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--seeds-for", action="append", default=[],
                    help="per-model-prefix seeds, e.g. 'gemini-4=0-5' (longest prefix wins)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", default=None, help="i/n: this process runs cells[i::n]")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--model-cap", action="append", default=[],
                    help="per-model-prefix concurrent episodes, e.g. 'gemini-4-carbon=8'")
    ap.add_argument("--max-episodes", type=int, default=None)
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--run-name", default=None, help="ladder_run label in the ledger (default: OUT's name)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", action="store_true", help="one tiny call per (model, level); writes OUT/_probe.json")
    a = ap.parse_args(argv)
    out = Path(os.path.expanduser(a.out))
    models = [m for m in a.models.split(",") if m]
    levels = [x for x in a.levels.split(",") if x]

    def log(msg: str) -> None:
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    if a.probe:
        os.environ.setdefault("CANARY_GEMINI_LEDGER", str(out / "_ledger" / f"{HOST}-{os.getpid()}.jsonl"))
        probe(models, levels, out, log)
        return 0
    cells = shard(expand_grid(models, levels, [t for t in a.tiers.split(",") if t], parse_seed_spec(a.seeds),
                              parse_overrides(a.seeds_for), parse_overrides(a.levels_for)), a.shard)
    caps = {k: int(v) for k, v in parse_overrides(a.model_cap)}
    if a.dry_run:
        n_done = sum(1 for c in cells if is_done(out, c))
        for c in cells[: a.max_episodes or len(cells)]:
            print(("done " if is_done(out, c) else "todo ") + c.key)
        log(f"DRY: {len(cells)} cells ({n_done} done) in shard {a.shard or '0/1'}")
        return 0
    os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "12")  # transport retries (as scripts/gemini_runner.py)
    os.environ.setdefault("CANARY_GEMINI_LEDGER", str(out / "_ledger" / f"{HOST}-{os.getpid()}.jsonl"))
    run_grid(out, cells, a.concurrency, a.max_episodes, a.max_attempts, caps, a.run_name, log=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
