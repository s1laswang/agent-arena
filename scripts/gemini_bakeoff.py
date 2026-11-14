"""Gemini model bake-off on Canary (rules = canary.rules.TIERS_VERSION, currently v1.4).

Plays the frontier in-process loop — canary.eval.run_episode + canary.agents.llm_policy.LLMPolicy +
canary.llm.gemini_backend.GeminiClient — on the same seeds as ``make reproduce`` (the JUDGE_SEEDS
prefix from canary.reproduce.seeds_per_tier). Reference solver, heuristic, do_nothing and stop_early
play those seeds too. Invalid / infra-failed episodes are stored and counted, and left out of the mean.

The API key is read from the process environment (GEMINI_API_KEY). If that variable is unset and a
repo-root ``.env`` file exists, the key is taken from that file and not overridden when the variable
is already set. The file is gitignored. This script never writes the key. It redacts the key from
episode JSON, the summary, and log records.

    # keyless: mock catalog + mock client, real env, real baselines, writes the summary table
    python scripts/gemini_bakeoff.py --dry-run --out /tmp/gemini-bakeoff-dry

    # live (GEMINI_API_KEY in the environment, or in a gitignored repo-root .env):
    uv run --python 3.12 --extra llm --extra dev python scripts/gemini_bakeoff.py \
        --out results/gemini_bakeoff

Models are chosen at runtime from models.list(): the strongest pro-class Gemini, plus up to three
faster flash / flash-lite models. A tiebreaker then runs the flash-lite model zero-shot and again
with notes distilled from its own training-seed episodes (TRAIN_SEEDS), scored on HELDOUT_SEEDS.
That is in-context text, not a weight update.

Sleeper's agents/gemini.py is a different environment and reads .env; it is not used.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Planning bounds, not a price quote. Anchored to results/gemini/ladder.md (Canary v1.4, in-process
# LLMPolicy): gemini-4-carbon hard/high ~36 min and ~80 calls; gemini-3.8-flash medium thinking ~12 min
# and ~70 calls; gemini-3.1-flash-lite high ~6 min and ~40 calls. Easy is not in that table.
MINUTES_PER_EPISODE = {
    "pro": {"easy": 12.0, "medium": 20.0, "hard": 36.0},
    "flash": {"easy": 3.0, "medium": 12.0, "hard": 12.0},
    "flash-lite": {"easy": 1.0, "medium": 3.0, "hard": 6.0},
}
CALLS_PER_EPISODE = {"pro": 90, "flash": 70, "flash-lite": 45}

DEFAULT_TIERS = ("easy", "medium", "hard")
REFERENCE_AGENTS = ("solver", "heuristic", "do_nothing", "stop_early")
REFERENCE_ROLE = {"solver": "reference", "heuristic": "baseline", "do_nothing": "baseline", "stop_early": "baseline"}

KNOWN_STRENGTH = {
    "gemini-4-carbon": 1000,
    "gemini-4-argon": 900,
    "gemini-4-hydrogen": 800,
    "gemini-2.5-pro": 700,
    "gemini-3-pro": 680,
    "gemini-3.8-flash": 600,
    "gemini-3.5-flash": 500,
    "gemini-2.5-flash": 450,
    "gemini-2.0-flash": 400,
    "gemini-3.1-flash-lite": 300,
    "gemini-2.5-flash-lite": 250,
    "gemini-2.0-flash-lite": 200,
}
EXCLUDE_TOKENS = (
    "embedding", "imagen", "veo", "tts", "aqa", "robot", "gemma", "lyria",
    "audio", "live", "computer", "nano", "research", "image",
)
HIDDEN_KEYS = {"mole", "ledger", "world", "secret", "api_key", "authorization", "raw", "provider_items"}
LESSONS_MARKER = "IN-CONTEXT NOTES (not a weight update)"
FINE_TUNE_NOTE = (
    "In-context learning only. The notes are text placed in the prompt, written by this runner from "
    "the model's own training-seed episodes (public tool results and scores). Weights are not updated. "
    "train/lora_sft.py and train/grpo_mole.py train local Hugging Face weights, not Gemini, and the "
    "Gemini tunedModels API is not wired in this repo. A tuning job would also not finish inside this bake-off."
)

# Fixture catalog for --dry-run and tests. Shaped like models.list() entries. Not a live inventory.
FIXTURE_CATALOG = [
    {"name": "models/gemini-4-carbon", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-4-argon", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-4-hydrogen", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-3.8-flash", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-3.5-flash", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-3.5-flash-preview", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-3.1-flash-lite", "supported_actions": ["generateContent"]},
    {"name": "models/gemini-embedding-2", "supported_actions": ["embedContent"]},
    {"name": "models/gemini-2.5-flash-tts", "supported_actions": ["generateContent"]},
]


class MissingAPIKey(RuntimeError):
    pass


# --------------------------------------------------------------------------- secrets
def _dotenv_value(path: Path, name: str) -> str:
    """One variable from a dotenv file. Does not log the value and does not write the file."""
    try:
        text = path.read_text()
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() != name:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        return val.strip()
    return ""


def load_repo_dotenv(path: Path | None = None, environ: dict | None = None) -> str:
    """Accept a repo-root ``.env`` only when that file is present.

    Returns ``environment`` (GEMINI_API_KEY was already set; the file is not allowed to override it),
    ``file`` (the key was copied out of the file because the variable was unset), or ``absent``
    (no file, or the file has no key). Never writes the key anywhere.
    """
    environ = os.environ if environ is None else environ
    path = (ROOT / ".env") if path is None else path
    existing = environ.get("GEMINI_API_KEY", "")
    if isinstance(existing, str) and existing.strip():
        return "environment"
    if not path.is_file():
        return "absent"
    key = _dotenv_value(path, "GEMINI_API_KEY")
    if not key:
        return "absent"
    environ["GEMINI_API_KEY"] = key
    return "file"


def read_api_key(environ: dict | None = None, dotenv_path: Path | None = None) -> str:
    """GEMINI_API_KEY from the process environment, or from a repo-root .env if that file exists."""
    environ = os.environ if environ is None else environ
    load_repo_dotenv(dotenv_path, environ)
    key = environ.get("GEMINI_API_KEY", "")
    if not isinstance(key, str):
        key = ""
    key = key.strip()
    if not key:
        raise MissingAPIKey(
            "GEMINI_API_KEY is not set in the environment and repo-root .env is missing or has no key")
    return key


def _secrets_from_env(extra: list[str] | None = None) -> list[str]:
    found = []
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(name, "")
        if isinstance(val, str) and len(val.strip()) >= 8:
            found.append(val.strip())
    for s in extra or []:
        if s and s not in found:
            found.append(s)
    return found


def scrub_text(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret and len(secret) >= 8 and secret in out:
            out = out.replace(secret, "[REDACTED]")
    return out


def scrub_obj(obj: Any, secrets: list[str]) -> Any:
    if isinstance(obj, str):
        return scrub_text(obj, secrets)
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            key = scrub_text(str(k), secrets)
            if key.lower() in HIDDEN_KEYS or "api_key" in key.lower():
                continue
            clean[key] = scrub_obj(v, secrets)
        return clean
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v, secrets) for v in obj]
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    return scrub_text(str(obj), secrets)


class RedactFilter(logging.Filter):
    """Rewrites log records so a key that reached a request/response log cannot be emitted."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = scrub_text(message, self.secrets)
        record.args = ()
        if record.exc_text:
            record.exc_text = scrub_text(record.exc_text, self.secrets)
        return True


def install_redact_filter(secrets: list[str]) -> RedactFilter:
    filt = RedactFilter(secrets)
    logging.getLogger().addFilter(filt)
    for name in ("httpx", "httpcore", "google", "google.genai", "urllib3"):
        logging.getLogger(name).addFilter(filt)
        logging.getLogger(name).setLevel(logging.WARNING)
    return filt


# --------------------------------------------------------------------------- model catalog
def model_record(obj: Any) -> dict | None:
    if isinstance(obj, dict):
        name = obj.get("name") or obj.get("id") or ""
        methods = obj.get("supported_actions") or obj.get("supported_generation_methods") or obj.get("methods") or []
    else:
        name = getattr(obj, "name", "") or getattr(obj, "id", "") or ""
        methods = (getattr(obj, "supported_actions", None) or getattr(obj, "supported_generation_methods", None) or [])
    mid = str(name).strip().split("/")[-1]
    if not mid:
        return None
    return {"id": mid, "methods": tuple(str(m) for m in methods)}


def model_class(model_id: str) -> str:
    n = model_id.lower()
    if "flash-lite" in n or "flash_lite" in n or "flashlite" in n:
        return "flash-lite"
    if "flash" in n and re.search(r"(^|[-_])lite($|[-_])", n):
        return "flash-lite"
    if "flash" in n:
        return "flash"
    return "pro"


def family_key(model_id: str) -> str:
    n = model_id.lower()
    for suf in ("-preview", "-experimental", "-exp", "-latest"):
        n = n.replace(suf, "")
    n = re.sub(r"-\d{3}$", "", n)
    return n


def strength(model_id: str) -> float:
    n = model_id.lower()
    if n in KNOWN_STRENGTH:
        base = float(KNOWN_STRENGTH[n])
    else:
        fam = family_key(n)
        if fam in KNOWN_STRENGTH:
            base = float(KNOWN_STRENGTH[fam])
        else:
            m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            ver = float(m.group(1)) if m else 0.0
            cls = model_class(n)
            bonus = {"pro": 30.0, "flash": 15.0, "flash-lite": 5.0}[cls]
            if "carbon" in n:
                bonus += 25
            elif "argon" in n:
                bonus += 18
            elif "hydrogen" in n:
                bonus += 12
            elif re.search(r"(^|-)pro($|-)", n):
                bonus += 20
            base = ver * 10 + bonus
    if any(s in n for s in ("-preview", "-experimental", "-exp")):
        base -= 0.5
    return base


def is_candidate(model_id: str) -> bool:
    n = model_id.lower()
    if not n.startswith("gemini-"):
        return False
    return not any(tok in n for tok in EXCLUDE_TOKENS)


def supports_generate(methods: tuple[str, ...]) -> bool:
    if not methods:
        return True
    blob = " ".join(methods).lower().replace("_", "")
    return "generatecontent" in blob


def select_models(raw_models: list, max_small: int = 3) -> list[dict]:
    """Strongest pro-class model, then up to ``max_small`` flash / flash-lite models.

    Preview aliases collapse into their stable family. Embedding, TTS, image and live models are dropped.
    """
    best_by_family: dict[str, dict] = {}
    for raw in raw_models:
        rec = model_record(raw)
        if rec is None or not is_candidate(rec["id"]) or not supports_generate(rec["methods"]):
            continue
        fam = family_key(rec["id"])
        prev = best_by_family.get(fam)
        if prev is None or strength(rec["id"]) > strength(prev["id"]):
            best_by_family[fam] = rec
    if not best_by_family:
        raise RuntimeError("no generateContent Gemini models in the catalog")
    infos = list(best_by_family.values())
    by_class: dict[str, list[dict]] = {"pro": [], "flash": [], "flash-lite": []}
    for info in infos:
        by_class[model_class(info["id"])].append(info)
    for rows in by_class.values():
        rows.sort(key=lambda r: strength(r["id"]), reverse=True)

    if by_class["pro"]:
        pro = by_class["pro"][0]
        pro_note = ""
    else:
        pro = max(infos, key=lambda r: strength(r["id"]))
        pro_note = "no pro-class id in the catalog; using the strongest generateContent model"

    small: list[dict] = []
    flashes, lites = by_class["flash"], by_class["flash-lite"]
    # One strongest flash and one flash-lite before any extra flash, so a 2-model cut still has both classes.
    if flashes and flashes[0]["id"] != pro["id"]:
        small.append(flashes[0])
    if lites and lites[0]["id"] != pro["id"]:
        small.append(lites[0])
    for cand in flashes[1:] + lites[1:]:
        if cand["id"] == pro["id"] or any(s["id"] == cand["id"] for s in small):
            continue
        small.append(cand)
        if len(small) >= max(0, max_small):
            break
    small = [s for s in small if s["id"] != pro["id"]][: max(0, max_small)]

    def pack(info: dict, role: str, note: str = "") -> dict:
        return {"id": info["id"], "role": role, "strength": strength(info["id"]), "note": note}

    return [pack(pro, "pro", pro_note)] + [pack(s, model_class(s["id"])) for s in small]


# --------------------------------------------------------------------------- stats
def mean_std_ci(xs: list[float]) -> dict:
    """Sample standard deviation and the normal 95% CI half-width used by canary.analysis.gap.mean_ci."""
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci95": None}
    mean = sum(xs) / n
    if n < 2:
        return {"n": n, "mean": mean, "std": 0.0, "ci95": 0.0}
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(var)
    return {"n": n, "mean": mean, "std": std, "ci95": 1.96 * std / math.sqrt(n)}


def _fmt(x: float | None, nd: int = 3, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "–"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def summarize_rows(records: list[dict], solver_by_key: dict[tuple, float] | None = None) -> list[dict]:
    """One row per (agent, tier). Means use valid episodes only."""
    groups: dict[tuple, list[dict]] = {}
    for rec in records:
        groups.setdefault((rec["agent"], rec["tier"]), []).append(rec)
    rows = []
    for (agent, tier), recs in groups.items():
        valid = [r for r in recs if r.get("valid")]
        invalid = [r for r in recs if not r.get("valid")]
        scores = [float(r["score"]) for r in valid]
        stats = mean_std_ci(scores)
        turns = mean_std_ci([float(r.get("turns") or 0) for r in valid])
        tokens = mean_std_ci([float((r.get("tokens") or {}).get("in", 0)) + float((r.get("tokens") or {}).get("out", 0))
                              for r in valid])
        vs = None
        if solver_by_key is not None and agent != "solver":
            diffs = []
            for r in valid:
                key = (tier, int(r["seed"]))
                if key in solver_by_key:
                    diffs.append(float(r["score"]) - solver_by_key[key])
            if diffs:
                vs = sum(diffs) / len(diffs)
        tag_counts: Counter = Counter()
        regret = 0.0
        for r in valid:
            regret += float(r.get("regret_total") or 0)
            tag_counts.update(r.get("tags") or {})
        rows.append({
            "tier": tier,
            "agent": agent,
            "role": recs[0].get("role") or "",
            "model": recs[0].get("model"),
            "n": stats["n"],
            "invalid": len(invalid),
            "attempted": len(recs),
            "mean": stats["mean"],
            "std": stats["std"],
            "ci95": stats["ci95"],
            "turns": turns["mean"],
            "tokens": tokens["mean"],
            "vs_solver": vs,
            "regret_mean": (regret / stats["n"]) if stats["n"] else None,
            "tags": dict(tag_counts),
            "seeds": sorted(int(r["seed"]) for r in valid),
            "invalid_seeds": sorted(int(r["seed"]) for r in invalid),
        })
    return rows


def _row_sort_key(row: dict, tier_order: list[str], agent_order: list[str]) -> tuple:
    try:
        ti = tier_order.index(row["tier"])
    except ValueError:
        ti = 99
    try:
        ai = agent_order.index(row["agent"])
    except ValueError:
        ai = 99
    return (ti, ai, row["agent"])


def format_table(rows: list[dict], tier_order: list[str], agent_order: list[str], title: str) -> str:
    ordered = sorted(rows, key=lambda r: _row_sort_key(r, tier_order, agent_order))
    header = ("| tier | agent | role | n | invalid | mean | std | 95% CI | turns | tokens | vs solver |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines = [title, ""]
    lines.extend(header)
    for r in ordered:
        ci = "–" if r["ci95"] is None else f"±{_fmt(r['ci95'])}"
        lines.append(
            f"| {r['tier']} | {r['agent']} | {r['role']} | {r['n']} | {r['invalid']} | "
            f"{_fmt(r['mean'], sign=True)} | {_fmt(r['std'])} | {ci} | "
            f"{_fmt(r['turns'], 1)} | {_fmt(r['tokens'], 0)} | {_fmt(r['vs_solver'], sign=True)} |"
        )
    lines.append("")
    lines.append("n, mean, std and the 95% CI use valid episodes only. "
                 "std is the sample standard deviation; the CI half-width is 1.96 * std / sqrt(n) "
                 "(same normal approximation as canary.analysis.gap.mean_ci). "
                 "invalid counts infra failures (API errors, timeouts, crashed policy) and they are not in the mean. "
                 "vs solver is the mean of (agent − solver) on seeds both played validly.")
    return "\n".join(lines)


def format_tie_table(zero_rows: list[dict], icl_rows: list[dict]) -> str:
    lines = ["", "## Tiebreaker (in-context, not weight training)", "",
             FINE_TUNE_NOTE, "",
             "| tier | condition | n | invalid | mean | std | 95% CI | reward change vs zero-shot |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    by_tier_z = {r["tier"]: r for r in zero_rows}
    by_tier_i = {r["tier"]: r for r in icl_rows}
    for tier in list(dict.fromkeys([r["tier"] for r in zero_rows + icl_rows])):
        z, i = by_tier_z.get(tier), by_tier_i.get(tier)
        delta = None
        if z and i and z["mean"] is not None and i["mean"] is not None:
            delta = i["mean"] - z["mean"]
        if z:
            lines.append(f"| {tier} | zero-shot | {z['n']} | {z['invalid']} | {_fmt(z['mean'], sign=True)} | "
                         f"{_fmt(z['std'])} | ±{_fmt(z['ci95'])} | – |")
        if i:
            lines.append(f"| {tier} | in-context | {i['n']} | {i['invalid']} | {_fmt(i['mean'], sign=True)} | "
                         f"{_fmt(i['std'])} | ±{_fmt(i['ci95'])} | {_fmt(delta, sign=True)} |")
    lines.append("")
    lines.append("Reward change is mean(in-context) − mean(zero-shot) on the held-out seeds, "
                 "valid episodes only. Train seeds are disjoint and are not in this table.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- lessons
def distill_lessons(episodes: list[dict], *, model: str, train_seeds: list[int], eval_seeds: list[int],
                    rules_version: str, secrets: list[str]) -> str:
    """Short lessons + a few public transcripts from this model's own training episodes.

    Refuses eval seeds. Drops hidden-state keys (mole, ledger, world). Does not call a model.
    """
    train_set, eval_set = set(train_seeds), set(eval_seeds)
    overlap = train_set & eval_set
    if overlap:
        raise ValueError(f"train and eval seeds overlap: {sorted(overlap)[:5]}")
    bad = [int(e["seed"]) for e in episodes if int(e["seed"]) not in train_set or int(e["seed"]) in eval_set]
    if bad:
        raise ValueError(f"lessons would include a seed outside the training list: {bad[:5]}")
    valid = [e for e in episodes if e.get("valid")]
    scores = [float(e["score"]) for e in valid]
    stats = mean_std_ci(scores)
    tags: Counter = Counter()
    for e in valid:
        tags.update(e.get("tags") or {})
    lines = [
        LESSONS_MARKER,
        f"model: {model}",
        f"rules: {rules_version}",
        "These notes were written from your own earlier episodes on training seeds. "
        "They are memory in the prompt. They are not a weight update and they do not contain the hidden mole, "
        "the ledger, or any held-out episode.",
        f"train_seeds: {list(train_seeds)}",
        f"valid_episodes: {stats['n']}  mean_score: {_fmt(stats['mean'], sign=True)}",
        "tag_counts: " + (", ".join(f"{k}={v}" for k, v in tags.most_common(6)) or "(none)"),
        "",
        "What tended to go wrong on these seeds: " + (
            ", ".join(tags.most_common(3)[i][0] for i in range(min(3, len(tags)))) or "no tagged mistakes"),
        "Accuse only when one employee is singled out by leaked canary variants. "
        "A canary helps only if different groups receive different variants. "
        "Wrong accusations score -1. Ending with no accusation scores 0.",
        "",
        "Public transcripts (tool name and the result you were shown; truncated):",
    ]
    shown = 0
    for ep in sorted(valid or episodes, key=lambda e: int(e["seed"])):
        if shown >= 2:
            break
        shown += 1
        lines.append(f"- seed {ep['seed']} score {_fmt(float(ep['score']), sign=True)} "
                     f"correct={bool(ep.get('correct'))} end={ep.get('end_reason')}")
        for step in (ep.get("steps") or [])[:8]:
            args = scrub_obj(step.get("args") or {}, secrets)
            result = scrub_obj(step.get("result") or {}, secrets)
            args_s = json.dumps(args, default=str)[:180]
            res_s = json.dumps(result, default=str)[:180]
            lines.append(f"    t={step.get('t')} {step.get('tool')} {args_s} -> {res_s}")
    text = scrub_text("\n".join(lines), secrets)
    return text[:6000]


class LessonsPolicy:
    """LLMPolicy with the lessons file appended to the system prompt. Same weights, extra text."""

    def __init__(self, spec: str, lessons: str, client: Any):
        from canary.agents.llm_policy import LLMPolicy
        self._inner = LLMPolicy(spec, client=client)
        self._lessons = lessons
        self.name = f"{spec}+icl"
        self.usage = self._inner.usage

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self._inner.reset(tools_spec, instruction)
        note = self._lessons.strip()
        self._inner.system = {**self._inner.system, "content": self._inner.system["content"].rstrip() + "\n\n" + note}
        self._inner.transcript[0] = self._inner.system
        self.usage = self._inner.usage

    def act(self, history):
        out = self._inner.act(history)
        self.usage = self._inner.usage
        return out


# --------------------------------------------------------------------------- episode IO
def _slug(agent: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", agent)


def episode_path(root: Path, agent: str, tier: str, seed: int) -> Path:
    return root / "episodes" / _slug(agent) / tier / f"{seed}.json"


def write_json(path: Path, obj: Any, secrets: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = scrub_obj(obj, secrets)
    text = json.dumps(clean, indent=1, sort_keys=True, default=str) + "\n"
    text = scrub_text(text, secrets)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def assert_no_secrets(root: Path, secrets: list[str]) -> None:
    leaked = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix == ".tmp":
            continue
        text = path.read_text(errors="replace")
        for secret in secrets:
            if secret and len(secret) >= 8 and secret in text:
                leaked.append(str(path))
                break
    if leaked:
        raise RuntimeError(f"refusing to leave a secret on disk: {leaked[:5]}")


def invalid_reason(res) -> str | None:
    """None when the episode was played. A policy/API crash is infra, not a score."""
    meta = res.meta or {}
    if meta.get("valid") is False:
        return str(meta.get("error") or "invalid")
    err = str(meta.get("error") or "")
    if res.end_reason == "error" and err and ("policy error" in err or "API" in err or "429" in err or "503" in err):
        return err
    return None


def tag_episode(res) -> tuple[dict, float]:
    try:
        from canary.solver.regret import attribute
        items = attribute(res) or []
    except Exception as exc:  # tagging must not fail the episode
        return {"_tag_error": 1, type(exc).__name__: 1}, 0.0
    counts: Counter = Counter()
    regret = 0.0
    for item in items:
        regret += float(item.get("regret") or 0)
        for tag in item.get("tags") or []:
            counts[str(tag)] += 1
    return dict(counts), round(regret, 6)


def record_from_result(res, *, model: str | None, role: str, rules_version: str, usage: dict,
                       secrets: list[str], reason: str | None) -> dict:
    tags, regret = tag_episode(res)
    valid = reason is None
    steps = []
    for step in res.steps:
        steps.append(scrub_obj({
            "t": step.t, "day": step.day, "tool": step.tool,
            "args": step.args, "result": step.result,
        }, secrets))
    tokens = {
        "in": int((usage or {}).get("in") or 0),
        "out": int((usage or {}).get("out") or 0),
        "calls": int((usage or {}).get("calls") or 0),
    }
    rec = {
        "tier": res.tier,
        "seed": int(res.seed),
        "agent": res.agent,
        "model": model,
        "role": role,
        "rules_version": rules_version,
        "score": round(float(res.score), 6),
        "correct": bool(res.correct),
        "accused": res.accused,
        "final_day": res.final_day,
        "end_reason": res.end_reason,
        "valid": valid,
        "invalid_reason": scrub_text(reason, secrets) if reason else None,
        "turns": len(res.steps),
        "tokens": tokens,
        "tags": tags,
        "regret_total": regret,
        "steps": steps,
    }
    return scrub_obj(rec, secrets)


def blank_invalid(*, agent: str, model: str | None, role: str, tier: str, seed: int, rules_version: str,
                  reason: str, secrets: list[str]) -> dict:
    return scrub_obj({
        "tier": tier, "seed": int(seed), "agent": agent, "model": model, "role": role,
        "rules_version": rules_version, "score": None, "correct": False, "accused": None,
        "final_day": None, "end_reason": "error", "valid": False,
        "invalid_reason": scrub_text(reason, secrets), "turns": 0,
        "tokens": {"in": 0, "out": 0, "calls": 0}, "tags": {}, "regret_total": 0.0, "steps": [],
    }, secrets)


# --------------------------------------------------------------------------- seeds and world
def bakeoff_seeds(n: int) -> list[int]:
    """The same seed list ``python -m canary.eval --reproduce --repro-seeds n`` uses."""
    if n < 1:
        raise ValueError("n must be >= 1")
    from canary.reproduce import seeds_per_tier
    return list(seeds_per_tier(n))


def tie_seeds(train_n: int, eval_n: int) -> tuple[list[int], list[int]]:
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
    train = list(TRAIN_SEEDS)[:train_n]
    held = list(HELDOUT_SEEDS)[:eval_n]
    judge = set(JUDGE_SEEDS)
    if set(train) & set(held) or set(train) & judge or set(held) & judge:
        raise RuntimeError("tiebreaker seeds are not disjoint from each other or from the judge seeds")
    if len(train) < train_n or len(held) < eval_n:
        raise RuntimeError("not enough train/held-out seeds")
    return train, held


def warm_world_secret() -> dict:
    """Create the per-process judge secret once, on this thread, before workers start.

    Returns a fingerprint only. The secret itself is not included.
    """
    import hashlib
    from canary import world
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
    world._key(list(JUDGE_SEEDS)[0])
    world._key(list(HELDOUT_SEEDS)[0])
    salt = ROOT / "data" / "worlds" / "judge" / "SALT"
    if os.environ.get("CANARY_WORLD_SECRET"):
        mode, raw = "CANARY_WORLD_SECRET", os.environ["CANARY_WORLD_SECRET"].encode()
    elif salt.exists():
        mode, raw = "SALT file", salt.read_bytes()
    elif world._SET_SECRET is not None:
        mode, raw = "in-process", world._SET_SECRET
    elif world._PROC_SECRET is not None:
        mode, raw = "per-process random (paired inside this process, not bit-exact across processes)", world._PROC_SECRET
    else:
        mode, raw = "public", b"public"
    return {"mode": mode, "fingerprint": hashlib.sha256(raw).hexdigest()[:12]}


# --------------------------------------------------------------------------- budget
def _minutes(role: str, tiers: list[str], n: int) -> float:
    table = MINUTES_PER_EPISODE[role]
    return sum(table.get(t, table["medium"]) * n for t in tiers)


def _calls(role: str, tiers: list[str], n: int) -> int:
    return CALLS_PER_EPISODE[role] * n * len(tiers)


def wall_minutes(pro_min: float, other_min: float, tie_min: float, slots: int, pro_parallel: int = 2) -> dict:
    """Three views of wall-clock. pro_parallel_2 assumes two pro calls in flight and the other slots on flash."""
    slots = max(1, slots)
    pro_parallel = max(1, min(pro_parallel, slots))
    other_slots = max(1, slots - pro_parallel)
    if pro_min and other_min:
        bake = max(pro_min / pro_parallel, other_min / other_slots)
    elif pro_min:
        bake = pro_min / pro_parallel
    else:
        bake = other_min / slots
    tie_wall = tie_min / slots
    during = pro_min if not other_min else max(pro_min, other_min / max(1, slots - 1))
    return {
        "blended": round((pro_min + other_min + tie_min) / slots, 1),
        "pro_parallel_2": round(bake + tie_wall, 1),
        "pro_serial": round(during + tie_wall, 1),
    }


def plan_for_budget(catalog_roles: list[dict], *, slots: int = 4, budget: float = 90.0,
                    train_n: int = 3, tie_eval_n: int = 5, tie_tier: str = "medium") -> dict:
    """Pick the richest grid whose 2-wide-pro estimate fits in ``budget`` minutes.

    Richness prefers the hard tier, then more pro seeds, then medium, then more small models.
    The catalog is still resolved at runtime; this only chooses tiers and seed counts.
    """
    have_lite = any(m["role"] == "flash-lite" for m in catalog_roles)
    n_flash = sum(1 for m in catalog_roles if m["role"] == "flash")
    best = None
    for tiers in (("hard",), ("medium", "hard"), ("medium",), ("easy", "medium", "hard")):
        for pro_n in (5, 4, 3, 2):
            for max_small in (3, 2, 1):
                for pro_tiers in (("hard",) if "hard" in tiers else tiers, tiers):
                    if pro_tiers != tiers and "hard" not in tiers:
                        continue
                    small_n = min(max_small, n_flash + (1 if have_lite else 0))
                    # minutes: one pro, `small_n` small models. Use flash minutes for every small slot
                    # except one lite slot when the catalog has a lite and max_small >= 2 (or == 1 and no flash).
                    pro_min = _minutes("pro", list(pro_tiers), pro_n)
                    n_lite = 1 if have_lite and small_n >= 1 and (small_n >= 2 or n_flash == 0) else 0
                    n_fl = small_n - n_lite
                    small_tiers = list(tiers)
                    other = n_fl * _minutes("flash", small_tiers, 5) + n_lite * _minutes("flash-lite", small_tiers, 5)
                    tie = _minutes("flash-lite", [tie_tier], train_n + 2 * tie_eval_n) if have_lite else _minutes(
                        "flash", [tie_tier], train_n + 2 * tie_eval_n)
                    calls = (
                        _calls("pro", list(pro_tiers), pro_n)
                        + n_fl * _calls("flash", small_tiers, 5)
                        + n_lite * _calls("flash-lite", small_tiers, 5)
                        + (CALLS_PER_EPISODE["flash-lite" if have_lite else "flash"]) * (train_n + 2 * tie_eval_n)
                    )
                    wall = wall_minutes(pro_min, other, tie, slots)
                    if wall["pro_parallel_2"] > budget:
                        continue
                    score = (
                        1 if "hard" in tiers else 0,
                        pro_n,
                        1 if "medium" in tiers else 0,
                        small_n,
                        1 if "easy" in tiers else 0,
                        -wall["pro_parallel_2"],
                    )
                    cand = {
                        "tiers": list(tiers), "pro_tiers": list(pro_tiers), "n": 5, "pro_n": pro_n,
                        "max_small": max_small, "slots": slots, "tie_tier": tie_tier,
                        "train_n": train_n, "tie_eval_n": tie_eval_n,
                        "calls": calls, "wall": wall, "score": score,
                    }
                    if best is None or cand["score"] > best["score"]:
                        best = cand
    if best is None:
        best = {"tiers": ["medium"], "pro_tiers": ["medium"], "n": 5, "pro_n": 2, "max_small": 1,
                "slots": slots, "tie_tier": tie_tier, "train_n": train_n, "tie_eval_n": tie_eval_n,
                "calls": None, "wall": {"pro_parallel_2": None}, "score": (),
                "note": "no candidate fit the budget under the 2-wide pro assumption"}
    return best


def budget_command(plan: dict, out: str = "results/gemini_bakeoff") -> str:
    parts = [
        "uv run --python 3.12 --extra llm --extra dev python scripts/gemini_bakeoff.py",
        f"--out {out}",
        "--tiers " + ",".join(plan["tiers"]),
        f"--n {plan['n']}",
        f"--slots {plan['slots']}",
        f"--max-small {plan['max_small']}",
        f"--tie-tier {plan['tie_tier']}",
    ]
    if plan.get("pro_n") and plan["pro_n"] != plan["n"]:
        parts.append(f"--pro-n {plan['pro_n']}")
    if plan.get("pro_tiers") and plan["pro_tiers"] != plan["tiers"]:
        parts.append("--pro-tiers " + ",".join(plan["pro_tiers"]))
    return " ".join(parts)


def full_plan_estimate(n_small: int, *, n: int, tiers: tuple[str, ...], slots: int,
                       train_n: int, tie_eval_n: int, tie_tier: str, has_lite: bool) -> dict:
    pro_min = _minutes("pro", list(tiers), n)
    # mirror select order: one flash, one lite, then extra flashes
    n_lite = 1 if has_lite and n_small else 0
    n_fl = max(0, n_small - n_lite)
    other = n_fl * _minutes("flash", list(tiers), n) + (n_lite * _minutes("flash-lite", list(tiers), n) if n_lite else 0)
    tie_role = "flash-lite" if has_lite else "flash"
    tie = _minutes(tie_role, [tie_tier], train_n + 2 * tie_eval_n)
    calls = (_calls("pro", list(tiers), n) + n_fl * _calls("flash", list(tiers), n)
             + (n_lite * _calls("flash-lite", list(tiers), n) if n_lite else 0)
             + CALLS_PER_EPISODE[tie_role] * (train_n + 2 * tie_eval_n))
    return {"calls": calls, "wall": wall_minutes(pro_min, other, tie, slots),
            "pro_minutes": pro_min, "other_minutes": other, "tie_minutes": tie}


# --------------------------------------------------------------------------- play
@dataclass
class Job:
    kind: str                 # baseline | model | tie-train | tie-zero | tie-icl
    agent: str
    role: str
    tier: str
    seed: int
    model: str | None = None
    lessons: str | None = None
    root: Path = field(default_factory=Path)


def play_job(job: Job, *, make_client: Callable[[str], Any], make_env: Callable[[str, int], Any],
             rules_version: str, secrets: list[str]) -> dict:
    path = episode_path(job.root, job.agent, job.tier, job.seed)
    try:
        env = make_env(job.tier, job.seed)
        usage: dict = {"in": 0, "out": 0, "calls": 0}
        if job.kind == "baseline":
            from canary.eval import make_policy_factory, run_episode
            policy = make_policy_factory(job.agent)(job.seed)
            res = run_episode(env, policy)
        else:
            from canary.eval import run_episode
            client = make_client(job.model or "", job.seed)
            spec = f"gemini:{job.model}"
            if job.lessons:
                policy = LessonsPolicy(spec, job.lessons, client)
            else:
                from canary.agents.llm_policy import LLMPolicy
                policy = LLMPolicy(spec, client=client)
            res = run_episode(env, policy)
            usage = dict(getattr(policy, "usage", {}) or {})
        reason = invalid_reason(res)
        if reason:
            reason = scrub_text(reason, secrets)
        rec = record_from_result(res, model=job.model, role=job.role, rules_version=rules_version,
                                 usage=usage, secrets=secrets, reason=reason)
    except Exception as exc:  # noqa: BLE001 — an infra failure is a recorded invalid episode
        reason = scrub_text(f"{type(exc).__name__}: {exc}", secrets)
        rec = blank_invalid(agent=job.agent, model=job.model, role=job.role, tier=job.tier, seed=job.seed,
                            rules_version=rules_version, reason=reason, secrets=secrets)
        rec["traceback"] = scrub_text(traceback.format_exc().splitlines()[-1], secrets)
    write_json(path, rec, secrets)
    print(scrub_text(f"[{time.strftime('%H:%M:%S')}] episode {job.agent} {job.tier} {job.seed} "
                     f"valid={rec.get('valid')} score={rec.get('score')} reason={rec.get('invalid_reason') or rec.get('reason') or ''}"[:400],
                     secrets), flush=True)
    if not rec["valid"]:
        side = job.root / "invalid" / f"{_slug(job.agent)}-{job.tier}-{job.seed}-{time.strftime('%H%M%S')}.json"
        write_json(side, rec, secrets)
    return rec


def _run_jobs(jobs: list[Job], slots: int, **kw) -> list[dict]:
    if not jobs:
        return []
    if slots <= 1 or len(jobs) == 1:
        return [play_job(j, **kw) for j in jobs]
    with ThreadPoolExecutor(max_workers=slots) as pool:
        return list(pool.map(lambda j: play_job(j, **kw), jobs))


def _reuse_or_run(jobs: list[Job], slots: int, resume: bool, **kw) -> list[dict]:
    pending, done = [], []
    for job in jobs:
        prev = load_json(episode_path(job.root, job.agent, job.tier, job.seed)) if resume else None
        if prev and prev.get("valid") and prev.get("rules_version") == kw["rules_version"]:
            done.append(prev)
        else:
            pending.append(job)
    return done + _run_jobs(pending, slots, **kw)


# --------------------------------------------------------------------------- mock client (dry-run / tests)
class MockGeminiClient:
    """Two-call investigator: list employees, then accuse. Optional one-shot infra failure.

    ``lessons_bias`` is only for tests that need the in-context arm to score differently.
    The default dry-run does not know the mole and does not read hidden state.
    """

    def __init__(self, model: str, *, fail: bool = False, secret: str = "", lessons_bias: str | None = None):
        self.model = model
        self.fail = fail
        self.secret = secret
        self.lessons_bias = lessons_bias
        self.calls = 0
        self.finish_reasons: dict = {}

    def settings(self) -> dict:
        return {"api": "mock", "temperature": "not sent"}

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=None, **_kw):
        from canary.llm.base import LLMResponse, ToolCall
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"503 UNAVAILABLE api_key={self.secret}")
        blob = json.dumps(messages, default=str)
        if "list_employees" not in blob:
            return LLMResponse(text="", tool_calls=[ToolCall(id=f"c{self.calls}", name="list_employees", args={})],
                               usage={"in": 120, "out": 16, "cost_usd": 0.0})
        emp = self.lessons_bias if (self.lessons_bias and LESSONS_MARKER in blob) else "e00"
        return LLMResponse(text="", tool_calls=[ToolCall(id=f"c{self.calls}", name="accuse", args={"employee": emp})],
                           usage={"in": 240, "out": 18, "cost_usd": 0.0})


def dry_run_client_factory(fail_on: set[tuple[str, int]] | None = None, secret: str = "",
                           lessons_bias: str | None = None, seed_of: dict | None = None):
    """``seed_of`` is unused; failures are decided by the closure in ``make_client_for_seed``."""
    fail_on = fail_on or set()

    def make_client(model: str, seed: int = -1) -> MockGeminiClient:
        return MockGeminiClient(model, fail=(model, seed) in fail_on, secret=secret, lessons_bias=lessons_bias)

    return make_client


# --------------------------------------------------------------------------- driver
def current_rules_version() -> str:
    if os.environ.get("CANARY_TIERS_OVERRIDE"):
        raise RuntimeError("refusing to run under CANARY_TIERS_OVERRIDE; the bake-off uses canary.rules as imported")
    from canary.rules import TIERS_VERSION
    return TIERS_VERSION


def run_bakeoff(
    out: Path,
    *,
    n: int = 5,
    tiers: tuple[str, ...] = DEFAULT_TIERS,
    slots: int = 4,
    catalog: list | None = None,
    make_client: Callable[..., Any] | None = None,
    make_env: Callable[[str, int], Any] | None = None,
    secrets: list[str] | None = None,
    skip_tiebreaker: bool = False,
    tie_tier: str = "medium",
    train_n: int = 3,
    tie_eval_n: int = 5,
    max_small: int = 3,
    pro_n: int | None = None,
    pro_tiers: tuple[str, ...] | None = None,
    resume: bool = True,
    dry_run: bool = False,
    fail_on: set[tuple[str, int]] | None = None,
    lessons_bias: str | None = None,
    skip_grid: bool = False,
    skip_pro: bool = False,
) -> dict:
    rules_version = current_rules_version()
    secrets = list(secrets) if secrets is not None else _secrets_from_env()
    install_redact_filter(secrets)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    catalog = FIXTURE_CATALOG if catalog is None else catalog
    selected = select_models(catalog, max_small=max_small)
    if skip_pro:
        selected = [m for m in selected if m["role"] != "pro"]
    seeds = bakeoff_seeds(n)
    pro_seed_n = n if pro_n is None else pro_n
    if pro_seed_n < 1 or pro_seed_n > n:
        raise ValueError("--pro-n must be between 1 and --n")
    pro_tier_set = tuple(pro_tiers) if pro_tiers else tuple(tiers)
    train_seeds, held_seeds = tie_seeds(train_n, tie_eval_n)
    world = warm_world_secret()

    if make_env is None:
        from canary.eval import make_env as real_make_env
        make_env = real_make_env

    def client_for(model: str, seed: int = -1):
        if make_client is None:
            return MockGeminiClient(model, fail=(model, seed) in (fail_on or set()), lessons_bias=lessons_bias)
        try:
            return make_client(model, seed)
        except TypeError:
            return make_client(model)

    def jobs_for(root: Path, kind: str, agent: str, role: str, model: str | None, tier: str, seed_list: list[int],
                 lessons: str | None = None) -> list[Job]:
        return [Job(kind, agent, role, tier, seed, model, lessons, root) for seed in seed_list]

    kw = dict(make_client=client_for, make_env=make_env, rules_version=rules_version, secrets=secrets)
    bake_root = out
    jobs: list[Job] = []
    for tier in tiers:
        for agent in REFERENCE_AGENTS:
            jobs.extend(jobs_for(bake_root, "baseline", agent, REFERENCE_ROLE[agent], None, tier, seeds))
    for model in selected:
        model_seeds = seeds[:pro_seed_n] if model["role"] == "pro" else seeds
        model_tiers = pro_tier_set if model["role"] == "pro" else tiers
        for tier in model_tiers:
            if tier not in tiers and model["role"] != "pro":
                continue
            jobs.extend(jobs_for(bake_root, "model", f"gemini:{model['id']}", model["role"], model["id"], tier, model_seeds))

    if skip_grid:
        jobs = [j for j in jobs if j.kind == "baseline"]
    records = _reuse_or_run(jobs, slots, resume, **kw)

    solver_by_key = {(r["tier"], int(r["seed"])): float(r["score"]) for r in records
                     if r["agent"] == "solver" and r.get("valid") and r.get("score") is not None}
    rows = summarize_rows(records, solver_by_key)
    agent_order = list(REFERENCE_AGENTS) + [f"gemini:{m['id']}" for m in selected]
    table = format_table(rows, list(tiers), agent_order,
                         f"# Gemini bake-off  rules {rules_version}  seeds {seeds[0]}-{seeds[-1]}  "
                         f"paired  dry_run={dry_run}")

    tie: dict[str, Any] = {"learning": "in-context", "weight_training": False, "note": FINE_TUNE_NOTE}
    tie_md = ""
    if not skip_tiebreaker:
        # The probe is a flash-lite even when --max-small drops that class from the scored grid.
        catalog_full = select_models(catalog, max_small=3)
        lite = next((m for m in catalog_full if m["role"] == "flash-lite"), None)
        if lite is None:
            lite = next((m for m in reversed(catalog_full) if m["role"] == "flash"), selected[0])
        tie_model = lite["id"]
        tie_root = out / "tiebreaker"
        train_jobs = jobs_for(tie_root, "tie-train", f"gemini:{tie_model}", "flash-lite-train", tie_model,
                              tie_tier, train_seeds)
        train_recs = _reuse_or_run(train_jobs, slots, resume, **kw)
        lessons = distill_lessons(train_recs, model=tie_model, train_seeds=train_seeds, eval_seeds=held_seeds,
                                  rules_version=rules_version, secrets=secrets)
        (tie_root).mkdir(parents=True, exist_ok=True)
        lessons_path = tie_root / "lessons.md"
        lessons_path.write_text(scrub_text(lessons, secrets) + "\n")
        if any(s and len(s) >= 8 and s in lessons_path.read_text() for s in secrets):
            raise RuntimeError("lessons file contains a secret")
        zero_jobs = jobs_for(tie_root, "tie-zero", f"gemini:{tie_model}", "zero-shot", tie_model, tie_tier, held_seeds)
        icl_agent = f"gemini:{tie_model}+icl"
        icl_jobs = jobs_for(tie_root, "tie-icl", icl_agent, "in-context", tie_model, tie_tier, held_seeds, lessons)
        with ThreadPoolExecutor(max_workers=2) as arms:
            fz = arms.submit(_reuse_or_run, zero_jobs, slots, resume, **kw)
            fi = arms.submit(_reuse_or_run, icl_jobs, slots, resume, **kw)
            zero_recs, icl_recs = fz.result(), fi.result()
        z_rows = summarize_rows(zero_recs, None)
        i_rows = summarize_rows(icl_recs, None)
        # paired reward change on the intersection of valid seeds
        z_by = {int(r["seed"]): float(r["score"]) for r in zero_recs if r.get("valid") and r.get("score") is not None}
        i_by = {int(r["seed"]): float(r["score"]) for r in icl_recs if r.get("valid") and r.get("score") is not None}
        both = sorted(set(z_by) & set(i_by))
        deltas = [i_by[s] - z_by[s] for s in both]
        paired = mean_std_ci(deltas)
        tie.update({
            "model": tie_model,
            "tier": tie_tier,
            "train_seeds": train_seeds,
            "eval_seeds": held_seeds,
            "disjoint": True,
            "lessons_file": str(lessons_path),
            "zero_shot": z_rows,
            "in_context": i_rows,
            "paired_reward_change": paired,
            "paired_seeds": both,
        })
        tie_md = format_tie_table(z_rows, i_rows)
        write_json(tie_root / "summary.json", tie, secrets)

    has_lite = any(m["role"] == "flash-lite" for m in selected)
    full_est = full_plan_estimate(sum(1 for m in selected if m["role"] != "pro"), n=n, tiers=tuple(tiers),
                                  slots=slots, train_n=train_n, tie_eval_n=tie_eval_n, tie_tier=tie_tier,
                                  has_lite=has_lite)
    # The 90-minute recommendation is a fixed recipe (4 slots, default tiebreaker sizes).
    # It does not shrink just because this invocation used a smaller --slots or --n.
    budget = plan_for_budget(select_models(catalog, max_small=3), slots=4, budget=90,
                             train_n=3, tie_eval_n=5, tie_tier="medium")
    summary = {
        "rules_version": rules_version,
        "dry_run": dry_run,
        "adapter": "canary.agents.llm_policy.LLMPolicy + canary.llm.gemini_backend.GeminiClient",
        "loop": "canary.eval.run_episode",
        "seeds": seeds,
        "seed_source": "canary.reproduce.seeds_per_tier (JUDGE_SEEDS prefix, the make reproduce set)",
        "tiers": list(tiers),
        "pro_tiers": list(pro_tier_set),
        "pro_n": pro_seed_n,
        "models": selected,
        "world": world,
        "rows": rows,
        "tiebreaker": tie,
        "estimate_this_grid": full_est,
        "budget_90": budget,
        "budget_90_command": budget_command(budget),
        "fine_tune": FINE_TUNE_NOTE,
    }
    write_json(out / "summary.json", summary, secrets)
    md = "\n".join([
        table,
        "",
        f"World secret mode: {world['mode']}. Fingerprint `{world['fingerprint']}` (not the secret).",
        "Train seeds for the tiebreaker use the public world key. Judge and held-out seeds use the secret above.",
        "A per-process random secret makes this run paired across models but not bit-exact against a later process.",
        "",
        f"Planning estimate for this grid (not a measurement): about {full_est['calls']} API calls, "
        f"~{full_est['wall']['pro_parallel_2']} min if the pro model accepts 2 concurrent episodes "
        f"(serial pro ~{full_est['wall']['pro_serial']} min).",
        "",
        "90-minute command (richest grid that fits the 2-wide-pro bound):",
        "",
        "```",
        budget_command(budget),
        "```",
        "",
        tie_md,
    ])
    (out / "summary.md").write_text(scrub_text(md, secrets) + "\n")
    assert_no_secrets(out, secrets)
    print(scrub_text(md, secrets))
    return summary


def build_live_client_factory(api_key: str):
    from google import genai
    from google.genai import types
    timeout_ms = int(float(os.environ.get("CANARY_GEMINI_TIMEOUT_S", "600")) * 1000)
    # live fix: retry 429/5xx with exponential backoff instead of turning one throttle into an invalid episode
    retry = types.HttpRetryOptions(attempts=int(os.environ.get("CANARY_GEMINI_ATTEMPTS", "6")), initial_delay=2.0,
                                   max_delay=60.0, http_status_codes=[408, 429, 500, 502, 503, 504])
    sdk = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms, retry_options=retry))

    def make_client(model: str, seed: int = -1):
        from canary.llm.gemini_backend import GeminiClient
        return GeminiClient(model=model, sdk_client=sdk)

    def catalog() -> list:
        return list(sdk.models.list())

    return catalog, make_client


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="run directory (default results/gemini_bakeoff/<timestamp>)")
    ap.add_argument("--n", type=int, default=5, help="episodes per model per tier (default 5, judge-seed prefix)")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--max-small", type=int, default=3, help="how many flash / flash-lite models beside the pro model")
    ap.add_argument("--pro-n", type=int, default=None, help="seeds for the pro model (prefix of --n); default all")
    ap.add_argument("--pro-tiers", default=None, help="tiers for the pro model (default: same as --tiers)")
    ap.add_argument("--tie-tier", default="medium")
    ap.add_argument("--train-n", type=int, default=3, help="training seeds for the in-context notes")
    ap.add_argument("--tie-eval-n", type=int, default=5, help="held-out seeds for the tiebreaker")
    ap.add_argument("--skip-tiebreaker", action="store_true")
    ap.add_argument("--skip-grid", action="store_true", help="play only the local baselines and the tiebreaker")
    ap.add_argument("--skip-pro", action="store_true", help="drop the pro model from the grid (run it in another process)")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="no network and no API key: fixture catalog, mock client, real Canary env and baselines")
    args = ap.parse_args(argv)
    if args.n < 1:
        print("gemini_bakeoff: --n must be >= 1", flush=True)
        return 2
    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    pro_tiers = tuple(t.strip() for t in args.pro_tiers.split(",") if t.strip()) if args.pro_tiers else None
    out = Path(args.out) if args.out else Path("results/gemini_bakeoff") / time.strftime("%Y%m%d-%H%M%S")
    catalog = None
    make_client = None
    dry = args.dry_run
    # Load a gitignored repo-root .env when it exists, including on a dry-run, so the key is in the
    # scrub list. A value already in the process environment wins. The file is never written.
    load_repo_dotenv()
    if not dry:
        try:
            key = read_api_key()
        except MissingAPIKey as exc:
            print(f"gemini_bakeoff: {exc}", flush=True)
            return 2
        try:
            catalog_fn, make_client = build_live_client_factory(key)
            catalog = catalog_fn()
        except MissingAPIKey as exc:
            print(f"gemini_bakeoff: {exc}", flush=True)
            return 2
        except Exception as exc:  # noqa: BLE001
            print("gemini_bakeoff: model list failed: " + scrub_text(f"{type(exc).__name__}: {exc}", [key]), flush=True)
            return 2
        # the key must not sit in the summary; scrub list still redacts it
    try:
        run_bakeoff(
            out, n=args.n, tiers=tiers, slots=args.slots, catalog=catalog, make_client=make_client,
            skip_tiebreaker=args.skip_tiebreaker, tie_tier=args.tie_tier, train_n=args.train_n,
            tie_eval_n=args.tie_eval_n, max_small=args.max_small, pro_n=args.pro_n, pro_tiers=pro_tiers,
            resume=not args.no_resume, dry_run=dry, skip_grid=args.skip_grid, skip_pro=args.skip_pro,
        )
    except Exception as exc:  # noqa: BLE001
        secrets = _secrets_from_env()
        print("gemini_bakeoff: " + scrub_text(f"{type(exc).__name__}: {exc}", secrets), flush=True)
        return 2
    print(f"\nwrote {out}/summary.md and episode JSON", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
