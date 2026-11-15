"""Offline paired comparison CLI for V1.6 checkpoints on hard seeds 30..44."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import fcntl
import json
import logging
import math
import random
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.baselines import DoNothing, StopEarlyQuit
from canary.env import Env
from canary.eval import run_episode
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.social.engine import make_v16_provider
from canary.social.variants import VARIANTS
from canary.solver.policy import SolverPolicy
from canary.text.template import TemplateProvider
from canary.types import EpisodeResult

ALLOWED_TIER = "hard"
ALLOWED_SEED_MIN = 30
ALLOWED_SEED_MAX = 44
ALLOWED_SEEDS: frozenset[int] = frozenset(range(ALLOWED_SEED_MIN, ALLOWED_SEED_MAX + 1))
CONTROL_VARIANT = "v0_v14_control"
CANONICAL_VARIANTS: tuple[str, ...] = (
    "v1_anchoring_authority_confirmation",
    "v2_recency_bandwagon_sycophancy",
    "v3_grudge_falsemem_misforward",
    "v4_triad_authority_recency_grudge",
    "v5_full9_cocktail",
)
DEFAULT_RUNS_ROOT = Path("/tmp/fleet-momin/shared/v16_runs")
DEFAULT_REFERENCE_JSON = REPO_ROOT / "results" / "v16_social" / "reference_seeds_30_49.json"
DEFAULT_N_BOOT = 2000
DEFAULT_BOOTSTRAP_SEED = 42
MD_H = chr(35)

FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset({
    "mole",
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})
EMP_ID_PATTERN = re.compile(r"\be\d{2,3}\b", re.IGNORECASE)
KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)

_BASELINE_SEED_CACHE: dict[tuple[str, str, int], dict[str, Any]] = {}


@dataclass
class StoredEpisode:
    seed: int
    variant: str
    score: float
    correct: bool
    accused: str | None
    final_day: int
    end_reason: str
    episode: EpisodeResult | None
    v_accuse: float | None = None
    p_accused: float | None = None
    luck_adjusted: float | None = None
    replay_verified: bool | None = None
    source: str = ""


@dataclass
class VariantBucket:
    variant: str
    valid_by_seed: dict[int, StoredEpisode] = field(default_factory=dict)
    invalid_seeds: set[int] = field(default_factory=set)
    invalid_attempt_count: int = 0
    rejected_out_of_range_seeds: set[int] = field(default_factory=set)
    rejected_non_hard_count: int = 0
    sources: list[str] = field(default_factory=list)

    def add_source(self, src: str) -> None:
        if src and src not in self.sources:
            self.sources.append(src)


@dataclass
class AuditedSeed:
    seed: int
    score: float
    correct: bool
    accused_bool: bool
    final_day: int
    v_accuse: float | None
    p_accused: float | None
    luck_adj: float
    replay_verified: bool


def is_allowed_seed(seed: Any) -> bool:
    return isinstance(seed, int) and not isinstance(seed, bool) and seed in ALLOWED_SEEDS


def validate_seed_window(seeds: Iterable[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in seeds:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"seed must be int in 30..44, got {raw!r}")
        if raw not in ALLOWED_SEEDS:
            raise ValueError(f"seed {raw} outside allowed hard window 30..44")
        if raw not in seen:
            seen.add(raw)
            out.append(raw)
    return out


def parse_seeds_30_44(spec: str) -> list[int]:
    parsed: list[int] = []
    for raw_part in str(spec).split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s.strip()), int(hi_s.strip())
            if hi < lo:
                raise ValueError(f"invalid seed range {part!r}")
            parsed.extend(range(lo, hi + 1))
        else:
            parsed.append(int(part))
    if not parsed:
        raise ValueError(f"no seeds parsed from {spec!r}")
    return validate_seed_window(parsed)


def normalize_variant_name(raw_variant: str | None) -> str | None:
    if not raw_variant:
        return None
    val = str(raw_variant).strip().replace("__", ":")
    if not val:
        return None
    for prefix in ("v16-gemini-stub:", "v16-gemini:", "v16:"):
        if val.startswith(prefix):
            return val.split(":", 1)[1].strip() or None
    if val == "template":
        return CONTROL_VARIANT
    return val


def infer_variant_from_path(path: Path) -> str | None:
    parts = list(path.parts)
    for idx, part in enumerate(parts):
        if part in ("inproc", "opencode") and idx + 1 < len(parts):
            cand = normalize_variant_name(parts[idx + 1])
            if cand and cand != ALLOWED_TIER:
                return cand
    for part in reversed(parts[:-1]):
        cand = normalize_variant_name(part)
        if cand and (cand == CONTROL_VARIANT or cand in VARIANTS or cand.startswith(("v0_", "v1_", "v2_", "v3_", "v4_", "v5_"))):
            return cand
    stem = normalize_variant_name(path.stem)
    if stem and stem not in ("episodes", "invalid_attempts", "meta", ALLOWED_TIER):
        return stem
    return None


def infer_variant_from_record(rec: dict[str, Any], fallback_variant: str | None = None) -> str:
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    for candidate in (rec.get("variant"), meta.get("variant"), meta.get("provider"), fallback_variant):
        norm = normalize_variant_name(str(candidate)) if candidate is not None else None
        if norm:
            return norm
    return fallback_variant or "unknown_variant"


def provider_spec_for_variant(variant: str, ep_meta: dict[str, Any] | None = None) -> str:
    meta_prov = str((ep_meta or {}).get("provider") or "").strip()
    if variant == CONTROL_VARIANT or meta_prov == "template":
        return "template"
    if meta_prov.startswith("v16-gemini-stub:"):
        return meta_prov
    if meta_prov.startswith("v16-gemini:"):
        return "v16:" + meta_prov.split(":", 1)[1].strip()
    if meta_prov.startswith("v16:"):
        return meta_prov
    if variant.startswith("v16-gemini-stub:"):
        return variant
    if variant.startswith("v16-gemini:"):
        return "v16:" + variant.split(":", 1)[1].strip()
    if variant.startswith("v16:"):
        return variant
    if variant in VARIANTS:
        return f"v16:{variant}"
    if not meta_prov:
        return "template"
    return f"v16:{variant}"


def resolve_offline_provider(variant: str, ep_meta: dict[str, Any] | None = None) -> Any:
    spec = provider_spec_for_variant(variant, ep_meta)
    if spec == "template":
        return TemplateProvider()
    if spec.startswith("v16-gemini-stub:"):
        return make_v16_provider(spec)
    if spec.startswith("v16:"):
        v_name = spec.split(":", 1)[1].strip()
        if v_name == CONTROL_VARIANT:
            return TemplateProvider()
        return make_v16_provider(v_name, mode="template")
    raise ValueError(f"unsupported offline provider spec {spec!r}")


def compute_luck_adjusted_score(
    accused: str | None,
    p_accused: float | None,
    v_at_accuse: float | None,
) -> float:
    if not accused or p_accused is None:
        return 0.0
    p_val = float(p_accused)
    v_val = 0.0 if v_at_accuse is None else float(v_at_accuse)
    return p_val * v_val - (1.0 - p_val)


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
    luck = compute_luck_adjusted_score(ep.accused, p_val, v_val)
    return p_val, v_val, luck


def audit_and_verify_episode(
    stored: StoredEpisode,
    variant: str,
    env_factory: Callable[[str, int, Any], Any] | None = None,
) -> AuditedSeed:
    if stored.episode is not None:
        ep = stored.episode
        prov = resolve_offline_provider(variant, ep.meta)
        env = (
            env_factory(ALLOWED_TIER, ep.seed, prov)
            if env_factory is not None
            else Env(ALLOWED_TIER, ep.seed, text_provider=prov)
        )
        for st in ep.steps:
            if env.done:
                break
            env.call(st.tool, dict(st.args or {}))
        rep = env.result("replay")
        rep_v = float(getattr(env, "V", (rep.meta or {}).get("V", 0.0)))
        meta_v = (ep.meta or {}).get("V")
        v_consistent = True if meta_v is None else (abs(float(meta_v) - rep_v) < 1e-6)
        replay_ok = (
            abs(float(rep.score) - float(ep.score)) < 1e-9
            and bool(rep.correct) == bool(ep.correct)
            and rep.accused == ep.accused
            and int(rep.final_day) == int(ep.final_day)
            and v_consistent
        )
        p_val, v_val, luck = episode_posterior_and_luck(ep, fallback_v=rep_v)
        return AuditedSeed(
            seed=int(ep.seed),
            score=float(ep.score),
            correct=bool(ep.correct),
            accused_bool=bool(ep.accused),
            final_day=int(ep.final_day),
            v_accuse=v_val,
            p_accused=p_val,
            luck_adj=luck,
            replay_verified=bool(replay_ok),
        )

    luck = (
        float(stored.luck_adjusted)
        if stored.luck_adjusted is not None
        else compute_luck_adjusted_score(stored.accused, stored.p_accused, stored.v_accuse)
    )
    return AuditedSeed(
        seed=int(stored.seed),
        score=float(stored.score),
        correct=bool(stored.correct),
        accused_bool=bool(stored.accused),
        final_day=int(stored.final_day),
        v_accuse=stored.v_accuse,
        p_accused=stored.p_accused,
        luck_adj=luck,
        replay_verified=bool(stored.replay_verified),
    )


def _read_text_locked(path: Path) -> str:
    with path.open("r", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        except OSError:
            pass
        try:
            return fh.read()
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _parse_int_seed(raw: Any) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _ingest_episode_dict(
    rec: dict[str, Any],
    buckets: dict[str, VariantBucket],
    *,
    forced_variant: str | None = None,
    fallback_variant: str | None = None,
    source: str = "",
    allow_fake: bool = False,
    strict_seeds: bool = False,
    only_if_missing: bool = False,
) -> None:
    var_name = forced_variant or infer_variant_from_record(rec, fallback_variant=fallback_variant)
    bucket = buckets.setdefault(var_name, VariantBucket(variant=var_name))
    bucket.add_source(source)

    tier_val = rec.get("tier")
    if tier_val is not None and tier_val != ALLOWED_TIER:
        bucket.rejected_non_hard_count += 1
        return

    seed = _parse_int_seed(rec.get("seed"))
    if seed is None:
        bucket.invalid_attempt_count += 1
        return

    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    if rec.get("valid") is False or meta.get("valid") is False:
        bucket.invalid_attempt_count += 1
        if seed in ALLOWED_SEEDS:
            bucket.invalid_seeds.add(seed)
        return

    if not allow_fake and bool(meta.get("fake", False)):
        return

    if (
        meta.get("rc") == "timeout"
        or rec.get("end_reason") == "error"
        or bool(meta.get("error"))
    ):
        bucket.invalid_attempt_count += 1
        if seed in ALLOWED_SEEDS:
            bucket.invalid_seeds.add(seed)
        return

    steps = rec.get("steps")
    if steps is not None and len(steps) == 0:
        bucket.invalid_attempt_count += 1
        if seed in ALLOWED_SEEDS:
            bucket.invalid_seeds.add(seed)
        return

    if seed not in ALLOWED_SEEDS:
        bucket.rejected_out_of_range_seeds.add(seed)
        if strict_seeds:
            raise ValueError(f"seed {seed} in {source or var_name} outside allowed hard window 30..44")
        return

    if only_if_missing and seed in bucket.valid_by_seed:
        return

    raw_score = rec.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)) or not math.isfinite(float(raw_score)):
        bucket.invalid_attempt_count += 1
        bucket.invalid_seeds.add(seed)
        return

    ep_dict = dict(rec)
    ep_dict["tier"] = ALLOWED_TIER
    ep_dict["seed"] = seed
    ep_dict.pop("valid", None)
    ep_obj = to_result(ep_dict)
    bucket.valid_by_seed[seed] = StoredEpisode(
        seed=seed,
        variant=var_name,
        score=float(ep_obj.score),
        correct=bool(ep_obj.correct),
        accused=ep_obj.accused,
        final_day=int(ep_obj.final_day),
        end_reason=str(ep_obj.end_reason),
        episode=ep_obj,
        source=source,
    )


def _ingest_exported_summary_json(
    payload: dict[str, Any],
    buckets: dict[str, VariantBucket],
    *,
    forced_variant: str | None = None,
    fallback_variant: str | None = None,
    source: str = "",
    allow_fake: bool = False,
    strict_seeds: bool = False,
) -> None:
    if payload.get("tier") not in (None, ALLOWED_TIER):
        return
    if not allow_fake and bool(payload.get("fake", False)):
        return
    var_name = forced_variant or normalize_variant_name(payload.get("variant")) or fallback_variant
    if not var_name:
        return
    per_seed = payload.get("per_seed")
    if not isinstance(per_seed, list):
        return
    bucket = buckets.setdefault(var_name, VariantBucket(variant=var_name))
    bucket.add_source(source)
    for row in per_seed:
        if not isinstance(row, dict) or "gemini_score" not in row:
            continue
        seed = _parse_int_seed(row.get("seed"))
        if seed is None:
            continue
        if seed not in ALLOWED_SEEDS:
            bucket.rejected_out_of_range_seeds.add(seed)
            if strict_seeds:
                raise ValueError(f"seed {seed} in {source} outside allowed hard window 30..44")
            continue
        if seed in bucket.valid_by_seed:
            continue
        accused_val = row.get("gemini_accused")
        if accused_val is None and row.get("gemini_accused_bool") is True:
            accused_val = "exported"
        bucket.valid_by_seed[seed] = StoredEpisode(
            seed=seed,
            variant=var_name,
            score=float(row["gemini_score"]),
            correct=bool(row.get("gemini_correct", False)),
            accused=str(accused_val) if accused_val else None,
            final_day=int(row.get("gemini_final_day", 0)),
            end_reason=str(row.get("gemini_end_reason", "accused" if accused_val else "horizon")),
            episode=None,
            v_accuse=float(row["gemini_v_accuse"]) if row.get("gemini_v_accuse") is not None else None,
            p_accused=float(row["gemini_p_accused"]) if row.get("gemini_p_accused") is not None else None,
            luck_adjusted=float(row["gemini_luck_adjusted"]) if row.get("gemini_luck_adjusted") is not None else None,
            replay_verified=bool(row.get("replay_verified", False)),
            source=source,
        )


def load_checkpoint_file(
    path: Path,
    buckets: dict[str, VariantBucket],
    *,
    forced_variant: str | None = None,
    allow_fake: bool = False,
    strict_seeds: bool = False,
    only_if_missing: bool = False,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"checkpoint file not found: {path}")
    fallback_var = forced_variant or infer_variant_from_path(path)
    raw_text = _read_text_locked(path)
    src = str(path)

    if path.suffix.lower() == ".json":
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    _ingest_episode_dict(
                        item,
                        buckets,
                        forced_variant=forced_variant,
                        fallback_variant=fallback_var,
                        source=src,
                        allow_fake=allow_fake,
                        strict_seeds=strict_seeds,
                        only_if_missing=only_if_missing,
                    )
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("episodes"), list):
                for item in parsed["episodes"]:
                    if isinstance(item, dict):
                        _ingest_episode_dict(
                            item,
                            buckets,
                            forced_variant=forced_variant,
                            fallback_variant=fallback_var,
                            source=src,
                            allow_fake=allow_fake,
                            strict_seeds=strict_seeds,
                            only_if_missing=only_if_missing,
                        )
            elif isinstance(parsed.get("per_seed"), list):
                _ingest_exported_summary_json(
                    parsed,
                    buckets,
                    forced_variant=forced_variant,
                    fallback_variant=fallback_var,
                    source=src,
                    allow_fake=allow_fake,
                    strict_seeds=strict_seeds,
                )
            elif "seed" in parsed and "score" in parsed:
                _ingest_episode_dict(
                    parsed,
                    buckets,
                    forced_variant=forced_variant,
                    fallback_variant=fallback_var,
                    source=src,
                    allow_fake=allow_fake,
                    strict_seeds=strict_seeds,
                    only_if_missing=only_if_missing,
                )
        return

    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    for idx, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if idx == len(lines) - 1:
                continue
            raise
        if isinstance(rec, dict):
            _ingest_episode_dict(
                rec,
                buckets,
                forced_variant=forced_variant,
                fallback_variant=fallback_var,
                source=src,
                allow_fake=allow_fake,
                strict_seeds=strict_seeds,
                only_if_missing=only_if_missing,
            )


def _parse_variant_arg(spec: str) -> tuple[str | None, Path]:
    p_direct = Path(spec)
    if p_direct.exists() or "=" not in spec:
        return None, p_direct
    name_part, path_part = spec.split("=", 1)
    norm_name = normalize_variant_name(name_part)
    return norm_name, Path(path_part)


def discover_under_runs_root(
    runs_root: Path,
    buckets: dict[str, VariantBucket],
    *,
    include_control: bool = True,
    include_variants: bool = True,
    allow_fake: bool = False,
    strict_seeds: bool = False,
) -> None:
    if not runs_root.exists():
        raise FileNotFoundError(f"runs root does not exist: {runs_root}")

    ep_files = [
        p
        for p in runs_root.rglob("episodes.jsonl")
        if "attempts" not in p.parts and "superseded" not in p.parts
    ]
    ep_files.sort(key=lambda p: (p.stat().st_mtime, str(p)))

    for ep_file in ep_files:
        path_var = infer_variant_from_path(ep_file)
        if path_var == CONTROL_VARIANT and not include_control:
            continue
        if path_var is not None and path_var != CONTROL_VARIANT and not include_variants:
            continue
        temp_buckets: dict[str, VariantBucket] = {}
        load_checkpoint_file(
            ep_file,
            temp_buckets,
            allow_fake=allow_fake,
            strict_seeds=strict_seeds,
        )
        for v_name, bkt in temp_buckets.items():
            if v_name == CONTROL_VARIANT and not include_control:
                continue
            if v_name != CONTROL_VARIANT and not include_variants:
                continue
            dst = buckets.setdefault(v_name, VariantBucket(variant=v_name))
            for src in bkt.sources:
                dst.add_source(src)
            dst.valid_by_seed.update(bkt.valid_by_seed)
            dst.invalid_seeds.update(bkt.invalid_seeds)
            dst.invalid_attempt_count += bkt.invalid_attempt_count
            dst.rejected_out_of_range_seeds.update(bkt.rejected_out_of_range_seeds)
            dst.rejected_non_hard_count += bkt.rejected_non_hard_count

    inv_files = [
        p
        for p in sorted(runs_root.rglob("invalid_attempts.jsonl"))
        if "attempts" not in p.parts and "superseded" not in p.parts
    ]
    for inv_file in inv_files:
        if inv_file.parent.name not in (ALLOWED_TIER, "inproc", "opencode") and ALLOWED_TIER not in inv_file.parts:
            continue
        path_var = infer_variant_from_path(inv_file)
        if not path_var:
            continue
        if path_var == CONTROL_VARIANT and not include_control:
            continue
        if path_var != CONTROL_VARIANT and not include_variants:
            continue
        temp_buckets = {}
        load_checkpoint_file(
            inv_file,
            temp_buckets,
            forced_variant=path_var,
            allow_fake=allow_fake,
            strict_seeds=strict_seeds,
        )
        if path_var in temp_buckets:
            bkt = temp_buckets[path_var]
            dst = buckets.setdefault(path_var, VariantBucket(variant=path_var))
            for src in bkt.sources:
                dst.add_source(src)
            dst.invalid_seeds.update(bkt.invalid_seeds)
            dst.invalid_attempt_count += bkt.invalid_attempt_count
            dst.rejected_out_of_range_seeds.update(bkt.rejected_out_of_range_seeds)

    json_files = [
        p
        for p in sorted(runs_root.rglob("*.json"))
        if "transcripts" not in p.parts
        and "attempts" not in p.parts
        and "superseded" not in p.parts
        and p.name != "meta.json"
        and not p.name.startswith("seed_")
    ]
    for jf in json_files:
        temp_buckets = {}
        try:
            load_checkpoint_file(
                jf,
                temp_buckets,
                allow_fake=allow_fake,
                strict_seeds=strict_seeds,
                only_if_missing=True,
            )
        except (ValueError, KeyError):
            if strict_seeds:
                raise
            continue
        for v_name, bkt in temp_buckets.items():
            if v_name == CONTROL_VARIANT and not include_control:
                continue
            if v_name != CONTROL_VARIANT and not include_variants:
                continue
            dst = buckets.setdefault(v_name, VariantBucket(variant=v_name))
            for src in bkt.sources:
                dst.add_source(src)
            for sd, ep_st in bkt.valid_by_seed.items():
                dst.valid_by_seed.setdefault(sd, ep_st)
            dst.invalid_seeds.update(bkt.invalid_seeds)
            dst.invalid_attempt_count += bkt.invalid_attempt_count
            dst.rejected_out_of_range_seeds.update(bkt.rejected_out_of_range_seeds)


def load_reference_30_44(reference_json: Path | None) -> tuple[dict[int, dict[str, Any]], list[int]]:
    if reference_json is None:
        return {}, []
    if not reference_json.is_file():
        raise FileNotFoundError(f"reference JSON not found: {reference_json}")
    data = json.loads(reference_json.read_text(encoding="utf-8"))
    if data.get("tier") not in (None, ALLOWED_TIER):
        raise ValueError(f"reference JSON tier must be {ALLOWED_TIER!r}, got {data.get('tier')!r}")
    by_seed: dict[int, dict[str, Any]] = {}
    rejected_ref_seeds: list[int] = []
    for row in data.get("seeds") or []:
        if not isinstance(row, dict):
            continue
        sd = _parse_int_seed(row.get("seed"))
        if sd is None:
            continue
        if sd not in ALLOWED_SEEDS:
            rejected_ref_seeds.append(sd)
            continue
        by_seed[sd] = row
    return by_seed, sorted(set(rejected_ref_seeds))


def evaluate_baselines_for_seed(
    seed: int,
    variant: str,
    env_factory: Callable[[str, int, Any], Any] | None = None,
) -> dict[str, Any]:
    if seed not in ALLOWED_SEEDS:
        raise ValueError(f"seed {seed} outside allowed hard window 30..44")
    prov_spec = provider_spec_for_variant(variant)
    cache_key = (ALLOWED_TIER, prov_spec, int(seed))
    if env_factory is None and cache_key in _BASELINE_SEED_CACHE:
        return _BASELINE_SEED_CACHE[cache_key]

    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    make_e = (
        env_factory
        if env_factory is not None
        else (lambda t, s, pr: Env(t, s, text_provider=pr))
    )

    sol_ep = run_episode(
        make_e(ALLOWED_TIER, seed, resolve_offline_provider(variant)),
        SolverPolicy(ALLOWED_TIER),
    )
    sol_p, sol_v, sol_luck = episode_posterior_and_luck(sol_ep)

    dn_ep = run_episode(
        make_e(ALLOWED_TIER, seed, resolve_offline_provider(variant)),
        DoNothing(seed=seed),
    )
    se_ep = run_episode(
        make_e(ALLOWED_TIER, seed, resolve_offline_provider(variant)),
        StopEarlyQuit(seed=seed),
    )

    out = {
        "seed": int(seed),
        "provider_spec": prov_spec,
        "solver_score": float(sol_ep.score),
        "solver_correct": bool(sol_ep.correct),
        "solver_accused_bool": bool(sol_ep.accused is not None),
        "solver_day": int(sol_ep.final_day),
        "solver_v_accuse": sol_v,
        "solver_p_accused": sol_p,
        "solver_luck_adj": float(sol_luck),
        "do_nothing_score": float(dn_ep.score),
        "stop_early_score": float(se_ep.score),
    }
    if env_factory is None:
        _BASELINE_SEED_CACHE[cache_key] = out
    return out


def _percentile_95(vals: list[float]) -> tuple[float | None, float | None]:
    if not vals:
        return None, None
    ordered = sorted(vals)
    lo = ordered[int(0.025 * len(ordered))]
    hi = ordered[max(0, int(0.975 * len(ordered)) - 1)]
    return lo, hi


def bootstrap_mean_ci(
    xs: list[float],
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    n = len(xs)
    if n == 0:
        return None, None
    rng = random.Random(int(seed))
    vals = [sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(int(n_boot))]
    return _percentile_95(vals)


def paired_bootstrap_diff_ci(
    xs: list[float],
    ys: list[float],
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if len(xs) != len(ys) or not xs:
        return None, None
    diffs = [float(x) - float(y) for x, y in zip(xs, ys)]
    return bootstrap_mean_ci(diffs, n_boot=n_boot, seed=seed)


def paired_bootstrap_ratio_ci(
    num: list[float],
    den: list[float],
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    if len(num) != len(den) or not num:
        return None, None
    n = len(num)
    if (sum(den) / n) <= 0.0:
        return None, None
    rng = random.Random(int(seed))
    vals: list[float] = []
    for _ in range(int(n_boot)):
        idx = [rng.randrange(n) for _ in range(n)]
        den_m = sum(den[i] for i in idx) / n
        if den_m > 0.0:
            num_m = sum(num[i] for i in idx) / n
            vals.append(num_m / den_m)
    return _percentile_95(vals)


def _r(val: float | None, ndigits: int = 6) -> float | None:
    if val is None:
        return None
    f = float(val)
    if not math.isfinite(f):
        return None
    return round(f, ndigits)


def assert_clean_output(payload: Any) -> None:
    def _walk(obj: Any, path: str = "root", in_path_field: bool = False) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden hygiene key {ks!r} at {path}.{ks}")
                child_is_path = in_path_field or ks in ("sources", "runs_root", "reference_json")
                _walk(v, f"{path}.{ks}", child_is_path)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                _walk(item, f"{path}[{idx}]", in_path_field)
        elif isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError(f"non-finite float at {path}: {obj!r}")
        elif isinstance(obj, str) and not in_path_field:
            if EMP_ID_PATTERN.search(obj):
                raise ValueError(f"employee identifier detected at {path}: {obj!r}")

    _walk(payload)
    serialized = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    for rx in KEY_PATTERNS:
        if rx.search(serialized):
            raise ValueError("secret API key pattern detected in output")


def _variant_sort_key(name: str) -> tuple[int, str]:
    if name in CANONICAL_VARIANTS:
        return (CANONICAL_VARIANTS.index(name), name)
    return (len(CANONICAL_VARIANTS), name)


def compare_variant_to_control(
    variant_bucket: VariantBucket,
    control_bucket: VariantBucket,
    *,
    ref_by_seed: dict[int, dict[str, Any]] | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    env_factory: Callable[[str, int, Any], Any] | None = None,
    audited_control_cache: dict[int, AuditedSeed] | None = None,
) -> dict[str, Any]:
    v_name = variant_bucket.variant
    var_valid = set(variant_bucket.valid_by_seed.keys()) & set(ALLOWED_SEEDS)
    ctl_valid = set(control_bucket.valid_by_seed.keys()) & set(ALLOWED_SEEDS)
    paired_seeds = sorted(var_valid & ctl_valid & set(ALLOWED_SEEDS))
    n = len(paired_seeds)

    base_info: dict[str, Any] = {
        "variant": v_name,
        "provider_spec": provider_spec_for_variant(v_name),
        "variant_valid_seeds": sorted(var_valid),
        "control_valid_seeds": sorted(ctl_valid),
        "paired_seeds": paired_seeds,
        "n_paired": n,
        "variant_only_seeds": sorted(var_valid - set(paired_seeds)),
        "control_only_seeds": sorted(ctl_valid - set(paired_seeds)),
        "excluded_invalid_seeds": sorted(variant_bucket.invalid_seeds - var_valid),
        "invalid_attempt_count": int(variant_bucket.invalid_attempt_count),
        "rejected_out_of_range_seeds": sorted(variant_bucket.rejected_out_of_range_seeds),
        "sources": list(variant_bucket.sources),
    }

    if n == 0:
        return {
            **base_info,
            "variant_raw_mean": None,
            "variant_raw_ci_95": [None, None],
            "control_raw_mean": None,
            "control_raw_ci_95": [None, None],
            "solver_raw_mean": None,
            "solver_raw_ci_95": [None, None],
            "variant_vs_solver_raw_ratio": None,
            "variant_vs_solver_raw_ratio_ci_95": [None, None],
            "control_vs_solver_raw_ratio": None,
            "control_vs_solver_raw_ratio_ci_95": [None, None],
            "paired_delta_raw_mean": None,
            "paired_delta_raw_ci_95": [None, None],
            "variant_vs_solver_raw_diff_mean": None,
            "variant_vs_solver_raw_diff_ci_95": [None, None],
            "control_vs_solver_raw_diff_mean": None,
            "control_vs_solver_raw_diff_ci_95": [None, None],
            "variant_luck_adj_mean": None,
            "variant_luck_adj_ci_95": [None, None],
            "control_luck_adj_mean": None,
            "control_luck_adj_ci_95": [None, None],
            "solver_luck_adj_mean": None,
            "solver_luck_adj_ci_95": [None, None],
            "variant_vs_solver_luck_adj_ratio": None,
            "variant_vs_solver_luck_adj_ratio_ci_95": [None, None],
            "control_vs_solver_luck_adj_ratio": None,
            "control_vs_solver_luck_adj_ratio_ci_95": [None, None],
            "paired_delta_luck_adj_mean": None,
            "paired_delta_luck_adj_ci_95": [None, None],
            "variant_vs_solver_luck_adj_diff_mean": None,
            "variant_vs_solver_luck_adj_diff_ci_95": [None, None],
            "control_vs_solver_luck_adj_diff_mean": None,
            "control_vs_solver_luck_adj_diff_ci_95": [None, None],
            "variant_accuracy": None,
            "control_accuracy": None,
            "solver_accuracy": None,
            "variant_accused_rate": None,
            "control_accused_rate": None,
            "solver_accused_rate": None,
            "variant_mean_p_accused": None,
            "control_mean_p_accused": None,
            "solver_mean_p_accused": None,
            "variant_mean_accuse_day": None,
            "control_mean_accuse_day": None,
            "solver_mean_accuse_day": None,
            "do_nothing_mean": 0.0,
            "stop_early_mean": 0.0,
            "solver_calibration_diff": 0.0,
            "solver_reference_max_abs_diff": 0.0 if ref_by_seed else None,
            "variant_replay_verified_count": 0,
            "control_replay_verified_count": 0,
            "gates": {
                "do_nothing_zero": True,
                "stop_early_zero": True,
                "solver_calibration_zero": True,
                "replay_verified": True,
                "reference_consistent": True,
                "all_passed": True,
            },
            "per_seed": [],
        }

    var_raw: list[float] = []
    ctl_raw: list[float] = []
    sol_raw: list[float] = []
    sol_ctl_raw: list[float] = []
    var_luck: list[float] = []
    ctl_luck: list[float] = []
    sol_luck: list[float] = []
    dn_scores: list[float] = []
    dn_ctl_scores: list[float] = []
    se_scores: list[float] = []
    se_ctl_scores: list[float] = []

    var_ps: list[float] = []
    ctl_ps: list[float] = []
    sol_ps: list[float] = []
    var_days: list[int] = []
    ctl_days: list[int] = []
    sol_days: list[int] = []
    var_rep_ok = 0
    ctl_rep_ok = 0
    ref_diffs: list[float] = []
    per_seed: list[dict[str, Any]] = []

    for sd in paired_seeds:
        v_aud = audit_and_verify_episode(variant_bucket.valid_by_seed[sd], v_name, env_factory=env_factory)
        if audited_control_cache is not None and sd in audited_control_cache:
            c_aud = audited_control_cache[sd]
        else:
            c_aud = audit_and_verify_episode(
                control_bucket.valid_by_seed[sd],
                CONTROL_VARIANT,
                env_factory=env_factory,
            )
            if audited_control_cache is not None:
                audited_control_cache[sd] = c_aud

        b_var = evaluate_baselines_for_seed(sd, v_name, env_factory=env_factory)
        b_ctl = evaluate_baselines_for_seed(sd, CONTROL_VARIANT, env_factory=env_factory)

        if v_aud.replay_verified:
            var_rep_ok += 1
        if c_aud.replay_verified:
            ctl_rep_ok += 1

        var_raw.append(v_aud.score)
        ctl_raw.append(c_aud.score)
        sol_raw.append(b_var["solver_score"])
        sol_ctl_raw.append(b_ctl["solver_score"])
        var_luck.append(v_aud.luck_adj)
        ctl_luck.append(c_aud.luck_adj)
        sol_luck.append(b_var["solver_luck_adj"])
        dn_scores.append(b_var["do_nothing_score"])
        dn_ctl_scores.append(b_ctl["do_nothing_score"])
        se_scores.append(b_var["stop_early_score"])
        se_ctl_scores.append(b_ctl["stop_early_score"])

        if v_aud.accused_bool:
            var_days.append(v_aud.final_day)
            if v_aud.p_accused is not None:
                var_ps.append(v_aud.p_accused)
        if c_aud.accused_bool:
            ctl_days.append(c_aud.final_day)
            if c_aud.p_accused is not None:
                ctl_ps.append(c_aud.p_accused)
        if b_var["solver_accused_bool"]:
            sol_days.append(int(b_var["solver_day"]))
            if b_var["solver_p_accused"] is not None:
                sol_ps.append(float(b_var["solver_p_accused"]))

        if ref_by_seed and sd in ref_by_seed:
            ref_row = ref_by_seed[sd]
            ref_diffs.append(abs(float(b_var["solver_score"]) - float(ref_row["solver_score"])))
            ref_diffs.append(abs(float(b_var["solver_luck_adj"]) - float(ref_row["solver_luck_adj"])))

        per_seed.append({
            "seed": int(sd),
            "variant_score": _r(v_aud.score),
            "variant_correct": bool(v_aud.correct),
            "variant_accused_bool": bool(v_aud.accused_bool),
            "variant_final_day": int(v_aud.final_day),
            "variant_v_accuse": _r(v_aud.v_accuse),
            "variant_p_accused": _r(v_aud.p_accused),
            "variant_luck_adj": _r(v_aud.luck_adj),
            "variant_replay_verified": bool(v_aud.replay_verified),
            "control_score": _r(c_aud.score),
            "control_correct": bool(c_aud.correct),
            "control_accused_bool": bool(c_aud.accused_bool),
            "control_final_day": int(c_aud.final_day),
            "control_v_accuse": _r(c_aud.v_accuse),
            "control_p_accused": _r(c_aud.p_accused),
            "control_luck_adj": _r(c_aud.luck_adj),
            "control_replay_verified": bool(c_aud.replay_verified),
            "paired_delta_raw": _r(v_aud.score - c_aud.score),
            "paired_delta_luck_adj": _r(v_aud.luck_adj - c_aud.luck_adj),
            "solver_score": _r(b_var["solver_score"]),
            "solver_correct": bool(b_var["solver_correct"]),
            "solver_accused_bool": bool(b_var["solver_accused_bool"]),
            "solver_day": int(b_var["solver_day"]),
            "solver_p_accused": _r(b_var["solver_p_accused"]),
            "solver_luck_adj": _r(b_var["solver_luck_adj"]),
            "do_nothing_score": _r(b_var["do_nothing_score"]),
            "stop_early_score": _r(b_var["stop_early_score"]),
        })

    var_raw_mean = sum(var_raw) / n
    ctl_raw_mean = sum(ctl_raw) / n
    sol_raw_mean = sum(sol_raw) / n
    sol_ctl_raw_mean = sum(sol_ctl_raw) / n

    var_luck_mean = sum(var_luck) / n
    ctl_luck_mean = sum(ctl_luck) / n
    sol_luck_mean = sum(sol_luck) / n

    var_raw_lo, var_raw_hi = bootstrap_mean_ci(var_raw, n_boot=n_boot, seed=bootstrap_seed)
    ctl_raw_lo, ctl_raw_hi = bootstrap_mean_ci(ctl_raw, n_boot=n_boot, seed=bootstrap_seed)
    sol_raw_lo, sol_raw_hi = bootstrap_mean_ci(sol_raw, n_boot=n_boot, seed=bootstrap_seed)

    var_luck_lo, var_luck_hi = bootstrap_mean_ci(var_luck, n_boot=n_boot, seed=bootstrap_seed)
    ctl_luck_lo, ctl_luck_hi = bootstrap_mean_ci(ctl_luck, n_boot=n_boot, seed=bootstrap_seed)
    sol_luck_lo, sol_luck_hi = bootstrap_mean_ci(sol_luck, n_boot=n_boot, seed=bootstrap_seed)

    var_sol_raw_ratio = (var_raw_mean / sol_raw_mean) if sol_raw_mean > 0.0 else None
    var_sol_raw_lo, var_sol_raw_hi = paired_bootstrap_ratio_ci(
        var_raw,
        sol_raw,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )
    ctl_sol_raw_ratio = (ctl_raw_mean / sol_raw_mean) if sol_raw_mean > 0.0 else None
    ctl_sol_raw_lo, ctl_sol_raw_hi = paired_bootstrap_ratio_ci(
        ctl_raw,
        sol_raw,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )

    var_sol_luck_ratio = (var_luck_mean / sol_luck_mean) if sol_luck_mean > 0.0 else None
    var_sol_luck_lo, var_sol_luck_hi = paired_bootstrap_ratio_ci(
        var_luck,
        sol_luck,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )
    ctl_sol_luck_ratio = (ctl_luck_mean / sol_luck_mean) if sol_luck_mean > 0.0 else None
    ctl_sol_luck_lo, ctl_sol_luck_hi = paired_bootstrap_ratio_ci(
        ctl_luck,
        sol_luck,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )

    delta_raw_mean = var_raw_mean - ctl_raw_mean
    delta_raw_lo, delta_raw_hi = paired_bootstrap_diff_ci(
        var_raw,
        ctl_raw,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )
    delta_luck_mean = var_luck_mean - ctl_luck_mean
    delta_luck_lo, delta_luck_hi = paired_bootstrap_diff_ci(
        var_luck,
        ctl_luck,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )

    var_sol_raw_diff = var_raw_mean - sol_raw_mean
    var_sol_raw_diff_lo, var_sol_raw_diff_hi = paired_bootstrap_diff_ci(
        var_raw,
        sol_raw,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )
    ctl_sol_raw_diff = ctl_raw_mean - sol_raw_mean
    ctl_sol_raw_diff_lo, ctl_sol_raw_diff_hi = paired_bootstrap_diff_ci(
        ctl_raw,
        sol_raw,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )

    var_sol_luck_diff = var_luck_mean - sol_luck_mean
    var_sol_luck_diff_lo, var_sol_luck_diff_hi = paired_bootstrap_diff_ci(
        var_luck,
        sol_luck,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )
    ctl_sol_luck_diff = ctl_luck_mean - sol_luck_mean
    ctl_sol_luck_diff_lo, ctl_sol_luck_diff_hi = paired_bootstrap_diff_ci(
        ctl_luck,
        sol_luck,
        n_boot=n_boot,
        seed=bootstrap_seed,
    )

    dn_mean = sum(dn_scores) / n
    dn_ctl_mean = sum(dn_ctl_scores) / n
    se_mean = sum(se_scores) / n
    se_ctl_mean = sum(se_ctl_scores) / n
    cal_diff = sol_raw_mean - sol_ctl_raw_mean
    max_cal_abs = max((abs(a - b) for a, b in zip(sol_raw, sol_ctl_raw)), default=0.0)
    ref_max_abs = max(ref_diffs) if ref_diffs else (0.0 if ref_by_seed else None)

    gate_dn = all(abs(x) < 1e-12 for x in dn_scores + dn_ctl_scores)
    gate_se = all(abs(x) < 1e-12 for x in se_scores + se_ctl_scores)
    gate_cal = max_cal_abs < 1e-12
    gate_rep = (var_rep_ok == n) and (ctl_rep_ok == n)
    gate_ref = True if ref_max_abs is None else (ref_max_abs < 1e-5)

    return {
        **base_info,
        "variant_raw_mean": _r(var_raw_mean),
        "variant_raw_ci_95": [_r(var_raw_lo), _r(var_raw_hi)],
        "control_raw_mean": _r(ctl_raw_mean),
        "control_raw_ci_95": [_r(ctl_raw_lo), _r(ctl_raw_hi)],
        "solver_raw_mean": _r(sol_raw_mean),
        "solver_raw_ci_95": [_r(sol_raw_lo), _r(sol_raw_hi)],
        "variant_vs_solver_raw_ratio": _r(var_sol_raw_ratio),
        "variant_vs_solver_raw_ratio_ci_95": [_r(var_sol_raw_lo), _r(var_sol_raw_hi)],
        "control_vs_solver_raw_ratio": _r(ctl_sol_raw_ratio),
        "control_vs_solver_raw_ratio_ci_95": [_r(ctl_sol_raw_lo), _r(ctl_sol_raw_hi)],
        "paired_delta_raw_mean": _r(delta_raw_mean),
        "paired_delta_raw_ci_95": [_r(delta_raw_lo), _r(delta_raw_hi)],
        "variant_vs_solver_raw_diff_mean": _r(var_sol_raw_diff),
        "variant_vs_solver_raw_diff_ci_95": [_r(var_sol_raw_diff_lo), _r(var_sol_raw_diff_hi)],
        "control_vs_solver_raw_diff_mean": _r(ctl_sol_raw_diff),
        "control_vs_solver_raw_diff_ci_95": [_r(ctl_sol_raw_diff_lo), _r(ctl_sol_raw_diff_hi)],
        "variant_luck_adj_mean": _r(var_luck_mean),
        "variant_luck_adj_ci_95": [_r(var_luck_lo), _r(var_luck_hi)],
        "control_luck_adj_mean": _r(ctl_luck_mean),
        "control_luck_adj_ci_95": [_r(ctl_luck_lo), _r(ctl_luck_hi)],
        "solver_luck_adj_mean": _r(sol_luck_mean),
        "solver_luck_adj_ci_95": [_r(sol_luck_lo), _r(sol_luck_hi)],
        "variant_vs_solver_luck_adj_ratio": _r(var_sol_luck_ratio),
        "variant_vs_solver_luck_adj_ratio_ci_95": [_r(var_sol_luck_lo), _r(var_sol_luck_hi)],
        "control_vs_solver_luck_adj_ratio": _r(ctl_sol_luck_ratio),
        "control_vs_solver_luck_adj_ratio_ci_95": [_r(ctl_sol_luck_lo), _r(ctl_sol_luck_hi)],
        "paired_delta_luck_adj_mean": _r(delta_luck_mean),
        "paired_delta_luck_adj_ci_95": [_r(delta_luck_lo), _r(delta_luck_hi)],
        "variant_vs_solver_luck_adj_diff_mean": _r(var_sol_luck_diff),
        "variant_vs_solver_luck_adj_diff_ci_95": [_r(var_sol_luck_diff_lo), _r(var_sol_luck_diff_hi)],
        "control_vs_solver_luck_adj_diff_mean": _r(ctl_sol_luck_diff),
        "control_vs_solver_luck_adj_diff_ci_95": [_r(ctl_sol_luck_diff_lo), _r(ctl_sol_luck_diff_hi)],
        "variant_accuracy": _r(sum(1 for r in per_seed if r["variant_correct"]) / n),
        "control_accuracy": _r(sum(1 for r in per_seed if r["control_correct"]) / n),
        "solver_accuracy": _r(sum(1 for r in per_seed if r["solver_correct"]) / n),
        "variant_accused_rate": _r(sum(1 for r in per_seed if r["variant_accused_bool"]) / n),
        "control_accused_rate": _r(sum(1 for r in per_seed if r["control_accused_bool"]) / n),
        "solver_accused_rate": _r(sum(1 for r in per_seed if r["solver_accused_bool"]) / n),
        "variant_mean_p_accused": _r(sum(var_ps) / len(var_ps)) if var_ps else None,
        "control_mean_p_accused": _r(sum(ctl_ps) / len(ctl_ps)) if ctl_ps else None,
        "solver_mean_p_accused": _r(sum(sol_ps) / len(sol_ps)) if sol_ps else None,
        "variant_mean_accuse_day": _r(sum(var_days) / len(var_days)) if var_days else None,
        "control_mean_accuse_day": _r(sum(ctl_days) / len(ctl_days)) if ctl_days else None,
        "solver_mean_accuse_day": _r(sum(sol_days) / len(sol_days)) if sol_days else None,
        "do_nothing_mean": _r(dn_mean),
        "do_nothing_control_mean": _r(dn_ctl_mean),
        "stop_early_mean": _r(se_mean),
        "stop_early_control_mean": _r(se_ctl_mean),
        "solver_calibration_diff": _r(cal_diff),
        "solver_reference_max_abs_diff": _r(ref_max_abs),
        "variant_replay_verified_count": int(var_rep_ok),
        "control_replay_verified_count": int(ctl_rep_ok),
        "gates": {
            "do_nothing_zero": bool(gate_dn),
            "stop_early_zero": bool(gate_se),
            "solver_calibration_zero": bool(gate_cal),
            "replay_verified": bool(gate_rep),
            "reference_consistent": bool(gate_ref),
            "all_passed": bool(gate_dn and gate_se and gate_cal and gate_rep and gate_ref),
        },
        "per_seed": per_seed,
    }


def compare_v16_checkpoints(
    *,
    runs_root: str | Path | None = DEFAULT_RUNS_ROOT,
    control_jsonl: str | Path | Iterable[str | Path] | None = None,
    variant_jsonl: str | Path | Iterable[str | Path] | None = None,
    reference_json: str | Path | None = DEFAULT_REFERENCE_JSON,
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    allow_fake: bool = False,
    strict_seeds: bool = False,
    env_factory: Callable[[str, int, Any], Any] | None = None,
) -> dict[str, Any]:
    buckets: dict[str, VariantBucket] = {}

    has_explicit_control = control_jsonl is not None
    if isinstance(control_jsonl, (str, Path)):
        ctl_specs = [control_jsonl]
    elif control_jsonl is not None:
        ctl_specs = list(control_jsonl)
    else:
        ctl_specs = []

    if isinstance(variant_jsonl, (str, Path)):
        var_specs = [variant_jsonl]
    elif variant_jsonl is not None:
        var_specs = list(variant_jsonl)
    else:
        var_specs = []
    has_explicit_variants = len(var_specs) > 0

    for ctl_item in ctl_specs:
        load_checkpoint_file(
            Path(ctl_item),
            buckets,
            forced_variant=CONTROL_VARIANT,
            allow_fake=allow_fake,
            strict_seeds=strict_seeds,
        )

    for var_item in var_specs:
        forced_var, v_path = _parse_variant_arg(str(var_item))
        load_checkpoint_file(
            v_path,
            buckets,
            forced_variant=forced_var,
            allow_fake=allow_fake,
            strict_seeds=strict_seeds,
        )

    resolved_runs_root = Path(runs_root) if runs_root is not None else None
    if not has_explicit_control or not has_explicit_variants:
        if resolved_runs_root is None:
            raise ValueError("runs_root is required when control_jsonl or variant_jsonl is omitted")
        discover_under_runs_root(
            resolved_runs_root,
            buckets,
            include_control=not has_explicit_control,
            include_variants=not has_explicit_variants,
            allow_fake=allow_fake,
            strict_seeds=strict_seeds,
        )

    control_bucket = buckets.get(CONTROL_VARIANT, VariantBucket(variant=CONTROL_VARIANT))
    variant_names = sorted(
        (k for k in buckets.keys() if k != CONTROL_VARIANT),
        key=_variant_sort_key,
    )

    resolved_ref: Path | None = None
    if reference_json is not None and str(reference_json).strip():
        cand_ref = Path(reference_json)
        if cand_ref.is_file() or reference_json != DEFAULT_REFERENCE_JSON:
            resolved_ref = cand_ref
    ref_by_seed, rejected_ref_seeds = load_reference_30_44(
        resolved_ref if env_factory is None else None
    )

    audited_control_cache: dict[int, AuditedSeed] = {}
    variant_reports: dict[str, Any] = {}
    for v_name in variant_names:
        variant_reports[v_name] = compare_variant_to_control(
            buckets[v_name],
            control_bucket,
            ref_by_seed=ref_by_seed,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
            env_factory=env_factory,
            audited_control_cache=audited_control_cache,
        )

    ctl_valid_sorted = sorted(set(control_bucket.valid_by_seed.keys()) & set(ALLOWED_SEEDS))
    for sd in ctl_valid_sorted:
        if sd not in audited_control_cache:
            audited_control_cache[sd] = audit_and_verify_episode(
                control_bucket.valid_by_seed[sd],
                CONTROL_VARIANT,
                env_factory=env_factory,
            )
    ctl_replay_ok = sum(1 for sd in ctl_valid_sorted if audited_control_cache[sd].replay_verified)

    all_rep = (ctl_replay_ok == len(ctl_valid_sorted)) and all(
        r["gates"]["replay_verified"] for r in variant_reports.values()
    )
    all_dn = all(r["gates"]["do_nothing_zero"] for r in variant_reports.values())
    all_se = all(r["gates"]["stop_early_zero"] for r in variant_reports.values())
    all_cal = all(r["gates"]["solver_calibration_zero"] for r in variant_reports.values())
    all_ref = all(r["gates"]["reference_consistent"] for r in variant_reports.values())

    payload: dict[str, Any] = {
        "schema_version": "v16_compare_30_44.v1",
        "tier": ALLOWED_TIER,
        "tiers_version": TIERS_VERSION,
        "seed_window": [ALLOWED_SEED_MIN, ALLOWED_SEED_MAX],
        "n_boot": int(n_boot),
        "bootstrap_seed": int(bootstrap_seed),
        "runs_root": str(resolved_runs_root) if resolved_runs_root is not None else None,
        "reference_json": str(resolved_ref) if resolved_ref is not None else None,
        "reference_seeds_loaded": sorted(ref_by_seed.keys()),
        "reference_seeds_rejected_out_of_range": rejected_ref_seeds,
        "control": {
            "variant": CONTROL_VARIANT,
            "valid_seeds": ctl_valid_sorted,
            "n_valid": len(ctl_valid_sorted),
            "replay_verified_count": int(ctl_replay_ok),
            "excluded_invalid_seeds": sorted(control_bucket.invalid_seeds - set(ctl_valid_sorted)),
            "invalid_attempt_count": int(control_bucket.invalid_attempt_count),
            "rejected_out_of_range_seeds": sorted(control_bucket.rejected_out_of_range_seeds),
            "sources": list(control_bucket.sources),
        },
        "variants": variant_reports,
        "gates": {
            "all_replay_verified": bool(all_rep),
            "all_do_nothing_zero": bool(all_dn),
            "all_stop_early_zero": bool(all_se),
            "all_solver_calibration_zero": bool(all_cal),
            "all_reference_consistent": bool(all_ref),
            "all_passed": bool(all_rep and all_dn and all_se and all_cal and all_ref),
        },
    }

    assert_clean_output(payload)

    if out_json is not None:
        out_j = Path(out_json)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        out_j.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    md_text = render_markdown_report(payload)
    if out_md is not None:
        out_m = Path(out_md)
        out_m.parent.mkdir(parents=True, exist_ok=True)
        out_m.write_text(md_text + "\n", encoding="utf-8")

    return payload


def _fmt_num(val: float | None, nd: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{float(val):.{nd}f}"


def _fmt_signed(val: float | None, nd: int = 3) -> str:
    if val is None:
        return "n/a"
    return f"{float(val):+.{nd}f}"


def _fmt_val_ci(val: float | None, ci: list[float | None], *, signed: bool = False, pct: bool = False) -> str:
    if val is None:
        return "n/a"
    lo, hi = ci[0], ci[1]
    if pct:
        base = f"{float(val) * 100.0:.1f}%"
        if lo is None or hi is None:
            return base
        return f"{base} [{float(lo) * 100.0:.1f}%, {float(hi) * 100.0:.1f}%]"
    base = _fmt_signed(val) if signed else _fmt_num(val)
    if lo is None or hi is None:
        return base
    lo_s = _fmt_signed(lo) if signed else _fmt_num(lo)
    hi_s = _fmt_signed(hi) if signed else _fmt_num(hi)
    return f"{base} [{lo_s}, {hi_s}]"


def _fmt_seeds(seeds: list[int]) -> str:
    if not seeds:
        return "none"
    return ",".join(str(s) for s in seeds)


def render_markdown_report(payload: dict[str, Any]) -> str:
    ctl = payload["control"]
    lines: list[str] = [
        f"{MD_H} V1.6 Paired Checkpoint Comparison (Hard Seeds {ALLOWED_SEED_MIN}..{ALLOWED_SEED_MAX})",
        "",
        f"- Tier: `{payload['tier']}` (`{payload['tiers_version']}`), seed window `{ALLOWED_SEED_MIN}..{ALLOWED_SEED_MAX}` only",
        f"- Bootstrap: paired seed resamples `n_boot={payload['n_boot']}`, `seed={payload['bootstrap_seed']}`",
        f"- Control (`{ctl['variant']}`): `n_valid={ctl['n_valid']}`, seeds `{_fmt_seeds(ctl['valid_seeds'])}`, "
        f"replay `{ctl['replay_verified_count']}/{ctl['n_valid']}`, "
        f"invalid attempts excluded `{ctl['invalid_attempt_count']}`, "
        f"out-of-range rejected `{_fmt_seeds(ctl['rejected_out_of_range_seeds'])}`",
        f"- Gates all passed: `{payload['gates']['all_passed']}`",
        "",
        f"{MD_H}{MD_H} Paired Comparison on Exact Seed Intersection S",
        "",
        "| variant | n(S) | paired seeds S | ctl raw | var raw | solver raw | ctl/sol raw [95% CI] | var/sol raw [95% CI] | delta raw (var-ctl) [95% CI] | ctl luck | var luck | solver luck | ctl/sol luck [95% CI] | var/sol luck [95% CI] | delta luck (var-ctl) [95% CI] | replay | dn/se |",
        "|---|---:|---|---:|---:|---:|---|---|---|---|---:|---:|---:|---|---|---|---|---|",
    ]

    variants: dict[str, Any] = payload["variants"]
    if not variants:
        lines.append("| (no variants discovered) | 0 | none | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
    else:
        for v_name, r in variants.items():
            n_s = int(r["n_paired"])
            rep_s = f"{r['variant_replay_verified_count']}/{n_s}" if n_s > 0 else "0/0"
            dn_se = (
                f"{_fmt_num(r['do_nothing_mean'], 1)}/{_fmt_num(r['stop_early_mean'], 1)}"
                if n_s > 0
                else "0.0/0.0"
            )
            lines.append(
                f"| `{v_name}` | {n_s} | {_fmt_seeds(r['paired_seeds'])} | "
                f"{_fmt_num(r['control_raw_mean'])} | {_fmt_num(r['variant_raw_mean'])} | {_fmt_num(r['solver_raw_mean'])} | "
                f"{_fmt_val_ci(r['control_vs_solver_raw_ratio'], r['control_vs_solver_raw_ratio_ci_95'], pct=True)} | "
                f"{_fmt_val_ci(r['variant_vs_solver_raw_ratio'], r['variant_vs_solver_raw_ratio_ci_95'], pct=True)} | "
                f"{_fmt_val_ci(r['paired_delta_raw_mean'], r['paired_delta_raw_ci_95'], signed=True)} | "
                f"{_fmt_num(r['control_luck_adj_mean'])} | {_fmt_num(r['variant_luck_adj_mean'])} | {_fmt_num(r['solver_luck_adj_mean'])} | "
                f"{_fmt_val_ci(r['control_vs_solver_luck_adj_ratio'], r['control_vs_solver_luck_adj_ratio_ci_95'], pct=True)} | "
                f"{_fmt_val_ci(r['variant_vs_solver_luck_adj_ratio'], r['variant_vs_solver_luck_adj_ratio_ci_95'], pct=True)} | "
                f"{_fmt_val_ci(r['paired_delta_luck_adj_mean'], r['paired_delta_luck_adj_ci_95'], signed=True)} | "
                f"{rep_s} | {dn_se} |"
            )

    lines.extend([
        "",
        f"{MD_H}{MD_H} Seed Accounting & Diagnostics",
        "",
        "| variant | valid seeds (30..44) | invalid attempts | rejected out-of-range | ctl P(acc) | var P(acc) | sol P(acc) | gates |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ])
    for v_name, r in variants.items():
        lines.append(
            f"| `{v_name}` | {_fmt_seeds(r['variant_valid_seeds'])} | {r['invalid_attempt_count']} | "
            f"{_fmt_seeds(r['rejected_out_of_range_seeds'])} | "
            f"{_fmt_num(r['control_mean_p_accused'])} | {_fmt_num(r['variant_mean_p_accused'])} | "
            f"{_fmt_num(r['solver_mean_p_accused'])} | {'PASS' if r['gates']['all_passed'] else 'FAIL'} |"
        )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Offline paired comparison CLI for V1.6 checkpoints on hard seeds 30..44."
    )
    ap.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    ap.add_argument("--control-jsonl", action="append", default=None)
    ap.add_argument("--variant-jsonl", action="append", default=None)
    ap.add_argument("--reference-json", default=str(DEFAULT_REFERENCE_JSON))
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--allow-fake", action="store_true")
    ap.add_argument("--strict-seeds", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = compare_v16_checkpoints(
            runs_root=args.runs_root,
            control_jsonl=args.control_jsonl,
            variant_jsonl=args.variant_jsonl,
            reference_json=args.reference_json,
            out_json=args.out_json,
            out_md=args.out_md,
            n_boot=args.n_boot,
            bootstrap_seed=args.bootstrap_seed,
            allow_fake=bool(args.allow_fake),
            strict_seeds=bool(args.strict_seeds),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(render_markdown_report(payload))
    return 0 if payload["gates"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
