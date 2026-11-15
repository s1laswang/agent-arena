from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import json
import math
import random
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from canary.baselines import ObviousHeuristic, play
from canary.env import Env
from canary.mole.dsl import MoleDoc, MoleStrategy, MoleView, StrategyError
from canary.rules import JUDGE_SEEDS, TIERS, TRACKS
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROLES_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
DEFAULT_DEV_SEEDS: tuple[int, ...] = (0, 1, 2, 3, 4)

ALLOWED_MOLE_VIEW_FIELDS: frozenset[str] = frozenset({
    "day",
    "docs",
    "days_since_last_leak",
    "i_am_restricted",
    "n_restricted_colleagues",
    "recent_low_recipient_docs",
    "peers",
    "restricted_peers",
    "decoy",
    "can_leak",
    "select_weights",
})

ALLOWED_MOLE_DOC_FIELDS: frozenset[str] = frozenset({
    "doc_id",
    "title",
    "recipient_count",
    "age_days",
})

PRIVILEGED_FIELD_NAMES: frozenset[str] = frozenset({
    "is_canary",
    "canary",
    "canaries",
    "canary_ids",
    "variant",
    "variants",
    "mole",
    "mole_id",
    "true_mole",
    "posterior",
    "belief",
    "investigator_belief",
    "recipients",
    "world_seed",
    "salt",
    "ledger",
    "feed",
    "logs",
    "messages",
    "secret",
})

_STRUCTURED_PRIVILEGED_RE = re.compile(
    r'"(?:is_canary|variants?|posterior|investigator_belief|true_mole|world_seed)"\s*:',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StrategyEntry:
    run_id: str
    source_kind: str
    source_file: str
    tier: str
    label: str
    is_top: bool
    strategy: MoleStrategy
    strategy_json: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_kind": self.source_kind,
            "source_file": self.source_file,
            "tier": self.tier,
            "label": self.label,
            "is_top": self.is_top,
            "strategy_json": self.strategy_json,
        }


@dataclass(frozen=True)
class StrategyRun:
    run_id: str
    run_dir: Path
    source_kind: str
    tier: str
    top_entry: StrategyEntry
    entries: tuple[StrategyEntry, ...]

    @property
    def top_strategy(self) -> MoleStrategy:
        return self.top_entry.strategy

    @property
    def strategies(self) -> tuple[MoleStrategy, ...]:
        return tuple(entry.strategy for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "source_kind": self.source_kind,
            "tier": self.tier,
            "top_entry": self.top_entry.to_dict(),
            "n_entries": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class EpisodeReplayAudit:
    seed: int
    solver_score: float
    solver_repro_score: float
    solver_correct: bool
    solver_repro_correct: bool
    solver_accused: str | None
    solver_leak_count: int
    obvious_score: float
    obvious_repro_score: float
    obvious_correct: bool
    obvious_repro_correct: bool
    obvious_accused: str | None
    obvious_leak_count: int
    views_checked: int
    privileged_field_violations: tuple[str, ...]
    deterministic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "solver_score": self.solver_score,
            "solver_repro_score": self.solver_repro_score,
            "solver_correct": self.solver_correct,
            "solver_repro_correct": self.solver_repro_correct,
            "solver_accused": self.solver_accused,
            "solver_leak_count": self.solver_leak_count,
            "obvious_score": self.obvious_score,
            "obvious_repro_score": self.obvious_repro_score,
            "obvious_correct": self.obvious_correct,
            "obvious_repro_correct": self.obvious_repro_correct,
            "obvious_accused": self.obvious_accused,
            "obvious_leak_count": self.obvious_leak_count,
            "views_checked": self.views_checked,
            "privileged_field_violations": list(self.privileged_field_violations),
            "deterministic": self.deterministic,
        }


@dataclass(frozen=True)
class StrategyReplayReport:
    run_id: str
    source_kind: str
    tier: str
    strategy_label: str
    behavioral_signature: str
    seeds: tuple[int, ...]
    episodes: tuple[EpisodeReplayAudit, ...]
    solver_mean_score: float
    solver_accuracy: float
    obvious_mean_score: float
    obvious_accuracy: float
    catchability_margin: float
    total_leak_count: int
    min_seed_leak_count: int
    obvious_total_leak_count: int
    views_checked: int
    privileged_field_violations: tuple[str, ...]
    deterministic_ok: bool
    leaks_ok: bool
    catchable_ok: bool
    mole_view_clean_ok: bool
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "source_kind": self.source_kind,
            "tier": self.tier,
            "strategy_label": self.strategy_label,
            "behavioral_signature": self.behavioral_signature,
            "seeds": list(self.seeds),
            "solver_mean_score": round(self.solver_mean_score, 6),
            "solver_accuracy": round(self.solver_accuracy, 6),
            "obvious_mean_score": round(self.obvious_mean_score, 6),
            "obvious_accuracy": round(self.obvious_accuracy, 6),
            "catchability_margin": round(self.catchability_margin, 6),
            "total_leak_count": self.total_leak_count,
            "min_seed_leak_count": self.min_seed_leak_count,
            "obvious_total_leak_count": self.obvious_total_leak_count,
            "views_checked": self.views_checked,
            "privileged_field_violations": list(self.privileged_field_violations),
            "deterministic_ok": self.deterministic_ok,
            "leaks_ok": self.leaks_ok,
            "catchable_ok": self.catchable_ok,
            "mole_view_clean_ok": self.mole_view_clean_ok,
            "passed": self.passed,
            "episodes": [ep.to_dict() for ep in self.episodes],
        }


@dataclass(frozen=True)
class BehavioralEquivalenceClass:
    signature: str
    representative_run_id: str
    representative_label: str
    source_kinds: tuple[str, ...]
    member_count: int
    members: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "representative_run_id": self.representative_run_id,
            "representative_label": self.representative_label,
            "source_kinds": list(self.source_kinds),
            "member_count": self.member_count,
            "members": [dict(m) for m in self.members],
        }


@dataclass(frozen=True)
class BehavioralEquivalenceSummary:
    n_strategies: int
    n_syntactic_unique: int
    n_equivalence_classes: int
    n_synthetic_views: int
    classes: tuple[BehavioralEquivalenceClass, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_strategies": self.n_strategies,
            "n_syntactic_unique": self.n_syntactic_unique,
            "n_equivalence_classes": self.n_equivalence_classes,
            "n_synthetic_views": self.n_synthetic_views,
            "classes": [c.to_dict() for c in self.classes],
        }


@dataclass(frozen=True)
class ReplayAuditSummary:
    roles_dir: str
    populated: bool
    seeds: tuple[int, ...]
    n_runs: int
    n_mole_forge_runs: int
    n_paired_designer_runs: int
    all_passed: bool
    runs: tuple[StrategyReplayReport, ...]
    all_strategies_equivalence: BehavioralEquivalenceSummary
    top_strategies_equivalence: BehavioralEquivalenceSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "roles_dir": self.roles_dir,
            "populated": self.populated,
            "seeds": list(self.seeds),
            "n_runs": self.n_runs,
            "n_mole_forge_runs": self.n_mole_forge_runs,
            "n_paired_designer_runs": self.n_paired_designer_runs,
            "all_passed": self.all_passed,
            "runs": [r.to_dict() for r in self.runs],
            "all_strategies_equivalence": self.all_strategies_equivalence.to_dict(),
            "top_strategies_equivalence": self.top_strategies_equivalence.to_dict(),
        }


def parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ".." in part:
            lo_s, hi_s = part.split("..", 1)
            out.extend(range(int(lo_s.strip()), int(hi_s.strip()) + 1))
        elif "-" in part:
            lo_s, hi_s = part.split("-", 1)
            out.extend(range(int(lo_s.strip()), int(hi_s.strip()) + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError(f"empty seed specification: {spec!r}")
    return out


def validate_dev_seeds(seeds: Sequence[int]) -> tuple[int, ...]:
    seed_tuple = tuple(int(s) for s in seeds)
    if not seed_tuple:
        raise ValueError("seeds must not be empty")
    judge_hits = [s for s in seed_tuple if s in JUDGE_SEEDS]
    if judge_hits:
        raise ValueError(f"refusing judge seeds {judge_hits}: replay audit uses dev seeds only")
    if any(s < 0 for s in seed_tuple):
        raise ValueError(f"seeds must be non-negative integers, got {seed_tuple}")
    return seed_tuple


def coerce_strategy(strategy_or_obj: MoleStrategy | Mapping[str, Any]) -> MoleStrategy:
    if isinstance(strategy_or_obj, MoleStrategy):
        return strategy_or_obj
    if isinstance(strategy_or_obj, Mapping):
        raw = _extract_raw_strategy_dict(strategy_or_obj)
        if raw is None:
            raise StrategyError("mapping does not contain a valid MoleStrategy payload")
        return MoleStrategy.from_json(raw)
    raise StrategyError(f"expected MoleStrategy or mapping, got {type(strategy_or_obj).__name__}")


def canonical_strategy_json(strategy_or_obj: MoleStrategy | Mapping[str, Any]) -> str:
    parsed = coerce_strategy(strategy_or_obj)
    exported = parsed.to_json()
    normalized = {"rules": exported["rules"], "default": exported["default"]}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _extract_raw_strategy_dict(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, Mapping):
        return None
    for key in ("strategy_json", "mole_strategy", "strategy"):
        inner = obj.get(key)
        if isinstance(inner, Mapping):
            return _extract_raw_strategy_dict(inner)
    cand = obj.get("candidate")
    if isinstance(cand, Mapping):
        return _extract_raw_strategy_dict(cand)
    if "rules" in obj or "default" in obj:
        filtered: dict[str, Any] = {}
        if "rules" in obj:
            filtered["rules"] = obj["rules"]
        if "default" in obj:
            filtered["default"] = obj["default"]
        if isinstance(obj.get("name"), str) and len(obj["name"]) <= 80:
            filtered["name"] = obj["name"]
        return filtered
    return None


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _resolve_tier(*sources: Mapping[str, Any] | None, default: str = "hard") -> str:
    for src in sources:
        if isinstance(src, Mapping):
            t = src.get("tier")
            if isinstance(t, str) and (t in TIERS or t in TRACKS):
                return t
    return default


def _finite_float(val: Any, fallback: float) -> float:
    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
        return float(val)
    return fallback


def load_mole_forge_run(run_dir: str | Path) -> StrategyRun:
    rdir = Path(run_dir)
    hof_path = rdir / "hall_of_fame.jsonl"
    if not hof_path.is_file():
        raise FileNotFoundError(f"missing hall_of_fame.jsonl in {rdir}")
    meta = _read_json_if_exists(rdir / "meta.json")
    tier = _resolve_tier(meta)
    run_id = rdir.name

    indexed_rows: list[tuple[int, float, int, str, MoleStrategy, dict[str, Any]]] = []
    for line_idx, raw_line in enumerate(hof_path.read_text(encoding="utf-8").splitlines()):
        stripped = raw_line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        if not isinstance(row, dict):
            continue
        raw_strat = _extract_raw_strategy_dict(row)
        if raw_strat is None:
            continue
        parsed = MoleStrategy.from_json(raw_strat)
        rank_val = row.get("rank")
        rank = int(rank_val) if isinstance(rank_val, int) and not isinstance(rank_val, bool) else line_idx + 1
        fitness = _finite_float(row.get("fitness"), -1e9)
        label = str(row.get("name") or raw_strat.get("name") or f"rank_{rank}")
        indexed_rows.append((rank, -fitness, line_idx, label, parsed, parsed.to_json()))

    if not indexed_rows and isinstance(meta, dict):
        fallback_raw = _extract_raw_strategy_dict(meta.get("top_strategy"))
        if fallback_raw is not None:
            parsed = MoleStrategy.from_json(fallback_raw)
            indexed_rows.append((1, 0.0, 0, "top_strategy", parsed, parsed.to_json()))

    if not indexed_rows:
        raise ValueError(f"no valid MoleStrategy entries found in {hof_path}")

    indexed_rows.sort(key=lambda item: (item[0], item[1], item[2]))
    entries = tuple(
        StrategyEntry(
            run_id=run_id,
            source_kind="mole_forge",
            source_file=hof_path.name,
            tier=tier,
            label=label,
            is_top=(idx == 0),
            strategy=parsed,
            strategy_json=s_json,
        )
        for idx, (_, _, _, label, parsed, s_json) in enumerate(indexed_rows)
    )
    return StrategyRun(
        run_id=run_id,
        run_dir=rdir,
        source_kind="mole_forge",
        tier=tier,
        top_entry=entries[0],
        entries=entries,
    )


def _is_paired_report_payload(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if isinstance(payload.get("selected_top_scenario"), Mapping):
        return True
    if isinstance(payload.get("selected_scenario"), Mapping):
        return True
    kept = payload.get("kept")
    if isinstance(kept, list) and any(_extract_raw_strategy_dict(item) is not None for item in kept):
        return True
    rows = payload.get("rows")
    if isinstance(rows, list) and any(_extract_raw_strategy_dict(item) is not None for item in rows):
        return True
    return False


def _candidate_label(obj: Mapping[str, Any], default_label: str) -> str:
    for key in ("name", "scenario_name"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    cand = obj.get("candidate")
    if isinstance(cand, Mapping):
        val = cand.get("name")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return default_label


def load_paired_designer_run(run_dir: str | Path) -> StrategyRun:
    rdir = Path(run_dir)
    design_report = _read_json_if_exists(rdir / "design_report.json")
    skill_gap = _read_json_if_exists(rdir / "skill_gap.json")
    alt_report = _read_json_if_exists(rdir / "report.json") if design_report is None else None
    if alt_report is not None and not _is_paired_report_payload(alt_report):
        alt_report = None

    if design_report is None and skill_gap is None and alt_report is None:
        raise FileNotFoundError(f"missing PAIRED designer artifacts in {rdir}")

    meta = _read_json_if_exists(rdir / "meta.json")
    primary_report = design_report if design_report is not None else alt_report
    primary_file = "design_report.json" if design_report is not None else ("report.json" if alt_report is not None else "skill_gap.json")
    tier = _resolve_tier(design_report, skill_gap, alt_report, meta)
    run_id = rdir.name

    top_candidate: tuple[str, str, MoleStrategy] | None = None

    if isinstance(primary_report, Mapping):
        sel_top = primary_report.get("selected_top_scenario")
        if isinstance(sel_top, Mapping):
            raw = _extract_raw_strategy_dict(sel_top)
            if raw is not None:
                top_candidate = (
                    primary_file,
                    _candidate_label(sel_top, "selected_top_scenario"),
                    MoleStrategy.from_json(raw),
                )

    if top_candidate is None and isinstance(skill_gap, Mapping):
        sel_sg = skill_gap.get("selected_scenario")
        if isinstance(sel_sg, Mapping):
            raw = _extract_raw_strategy_dict(sel_sg)
            if raw is not None:
                top_candidate = (
                    "skill_gap.json",
                    _candidate_label(sel_sg, "selected_scenario"),
                    MoleStrategy.from_json(raw),
                )

    if top_candidate is None and isinstance(primary_report, Mapping):
        rows = primary_report.get("rows")
        if isinstance(rows, list):
            kept_scored: list[tuple[float, float, int, str, MoleStrategy]] = []
            all_scored: list[tuple[float, int, str, MoleStrategy]] = []
            for idx, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    continue
                raw = _extract_raw_strategy_dict(row)
                if raw is None:
                    continue
                parsed = MoleStrategy.from_json(raw)
                label = _candidate_label(row, f"proposal_{idx}")
                solver_val = _finite_float(row.get("solver"), -1e9)
                regret_val = _finite_float(row.get("regret"), solver_val)
                all_scored.append((-solver_val, idx, label, parsed))
                if bool(row.get("keep")):
                    kept_scored.append((-regret_val, -solver_val, idx, label, parsed))
            if kept_scored:
                kept_scored.sort(key=lambda item: (item[0], item[1], item[2]))
                _, _, _, label, parsed = kept_scored[0]
                top_candidate = (primary_file, label, parsed)
            elif isinstance(primary_report.get("kept"), list):
                for idx, item in enumerate(primary_report["kept"]):
                    if isinstance(item, Mapping):
                        raw = _extract_raw_strategy_dict(item)
                        if raw is not None:
                            top_candidate = (primary_file, _candidate_label(item, f"kept_{idx}"), MoleStrategy.from_json(raw))
                            break
            if top_candidate is None and all_scored:
                all_scored.sort(key=lambda item: (item[0], item[1]))
                _, _, label, parsed = all_scored[0]
                top_candidate = (primary_file, label, parsed)

    if top_candidate is None and isinstance(primary_report, Mapping) and isinstance(primary_report.get("kept"), list):
        for idx, item in enumerate(primary_report["kept"]):
            if isinstance(item, Mapping):
                raw = _extract_raw_strategy_dict(item)
                if raw is not None:
                    top_candidate = (primary_file, _candidate_label(item, f"kept_{idx}"), MoleStrategy.from_json(raw))
                    break

    if top_candidate is None:
        for fname, doc in (("design_report.json", design_report), ("skill_gap.json", skill_gap), ("report.json", alt_report)):
            if isinstance(doc, Mapping):
                raw = _extract_raw_strategy_dict(doc)
                if raw is not None:
                    top_candidate = (fname, _candidate_label(doc, "top_scenario"), MoleStrategy.from_json(raw))
                    break

    if top_candidate is None:
        raise ValueError(f"no valid MoleStrategy found in PAIRED designer folder {rdir}")

    collected: list[tuple[str, str, MoleStrategy]] = [top_candidate]
    seen_keys: set[tuple[str, str]] = {(top_candidate[1], canonical_strategy_json(top_candidate[2]))}

    def _append_candidate(src_file: str, label: str, strat: MoleStrategy) -> None:
        dedupe_key = (label, canonical_strategy_json(strat))
        if dedupe_key not in seen_keys:
            seen_keys.add(dedupe_key)
            collected.append((src_file, label, strat))

    if isinstance(primary_report, Mapping):
        kept_list = primary_report.get("kept")
        added_from_kept = False
        if isinstance(kept_list, list):
            for idx, item in enumerate(kept_list):
                if isinstance(item, Mapping):
                    raw = _extract_raw_strategy_dict(item)
                    if raw is not None:
                        _append_candidate(primary_file, _candidate_label(item, f"kept_{idx}"), MoleStrategy.from_json(raw))
                        added_from_kept = True
        rows_list = primary_report.get("rows")
        if not added_from_kept and isinstance(rows_list, list):
            kept_rows = [r for r in rows_list if isinstance(r, Mapping) and bool(r.get("keep"))]
            source_rows = kept_rows if kept_rows else [r for r in rows_list if isinstance(r, Mapping)]
            for idx, row in enumerate(source_rows):
                raw = _extract_raw_strategy_dict(row)
                if raw is not None:
                    _append_candidate(primary_file, _candidate_label(row, f"proposal_{idx}"), MoleStrategy.from_json(raw))

    if isinstance(skill_gap, Mapping):
        sel_sg = skill_gap.get("selected_scenario")
        if isinstance(sel_sg, Mapping):
            raw = _extract_raw_strategy_dict(sel_sg)
            if raw is not None:
                _append_candidate("skill_gap.json", _candidate_label(sel_sg, "selected_scenario"), MoleStrategy.from_json(raw))

    entries = tuple(
        StrategyEntry(
            run_id=run_id,
            source_kind="paired_designer",
            source_file=src_file,
            tier=tier,
            label=label,
            is_top=(idx == 0),
            strategy=strat,
            strategy_json=strat.to_json(),
        )
        for idx, (src_file, label, strat) in enumerate(collected)
    )
    return StrategyRun(
        run_id=run_id,
        run_dir=rdir,
        source_kind="paired_designer",
        tier=tier,
        top_entry=entries[0],
        entries=entries,
    )


def _classify_run_dir(candidate_dir: Path) -> str | None:
    if (candidate_dir / "hall_of_fame.jsonl").is_file():
        return "mole_forge"
    if (candidate_dir / "design_report.json").is_file() or (candidate_dir / "skill_gap.json").is_file():
        return "paired_designer"
    if (candidate_dir / "report.json").is_file():
        payload = _read_json_if_exists(candidate_dir / "report.json")
        if _is_paired_report_payload(payload):
            return "paired_designer"
    return None


def load_strategy_runs(roles_dir: str | Path = DEFAULT_ROLES_DIR) -> list[StrategyRun]:
    base = Path(roles_dir)
    if not base.exists() or not base.is_dir():
        return []

    candidate_dirs: list[Path] = []
    if _classify_run_dir(base) is not None:
        candidate_dirs.append(base)
    else:
        seen_dirs: set[Path] = set()
        for marker in ("hall_of_fame.jsonl", "design_report.json", "skill_gap.json", "report.json"):
            for matched_file in sorted(base.rglob(marker)):
                parent = matched_file.parent
                if parent not in seen_dirs and _classify_run_dir(parent) is not None:
                    seen_dirs.add(parent)
                    candidate_dirs.append(parent)

    candidate_dirs.sort(key=lambda p: p.relative_to(base).as_posix() if p != base else p.name)
    runs: list[StrategyRun] = []
    for cdir in candidate_dirs:
        kind = _classify_run_dir(cdir)
        if kind == "mole_forge":
            runs.append(load_mole_forge_run(cdir))
        elif kind == "paired_designer":
            runs.append(load_paired_designer_run(cdir))
    runs.sort(key=lambda r: (r.run_id, r.source_kind))
    return runs


def _object_fields(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, Mapping):
        return {str(k): v for k, v in obj.items()}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
        extra = getattr(obj, "__dict__", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                ks = str(k)
                if not (ks.startswith("__") and ks.endswith("__")):
                    result[ks] = v
        return result
    if hasattr(obj, "__dict__") and not isinstance(obj, (type, str, bytes, bytearray)):
        return {
            str(k): v
            for k, v in vars(obj).items()
            if not (str(k).startswith("__") and str(k).endswith("__"))
        }
    return None


def _check_strings_for_privileged_leaks(value: Any, path: str, violations: list[str]) -> None:
    if isinstance(value, str):
        if _STRUCTURED_PRIVILEGED_RE.search(value):
            violations.append(f"{path}:structured_privileged_payload")
        return
    if isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            _check_strings_for_privileged_leaks(item, f"{path}[{idx}]", violations)
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            ks = str(k)
            if ks.lower() in PRIVILEGED_FIELD_NAMES:
                violations.append(f"{path}.{ks}:privileged_field")
            _check_strings_for_privileged_leaks(v, f"{path}.{ks}", violations)


def check_mole_view_privileges(view: Any) -> list[str]:
    mapping = _object_fields(view)
    if mapping is None:
        return [f"mole_view:invalid_view_type:{type(view).__name__}"]

    violations: list[str] = []
    for key, val in sorted(mapping.items()):
        lowered = key.lower()
        if lowered in PRIVILEGED_FIELD_NAMES:
            violations.append(f"mole_view.{key}:privileged_field")
            continue
        if key not in ALLOWED_MOLE_VIEW_FIELDS:
            violations.append(f"mole_view.{key}:unauthorized_field")
            continue
        if key == "docs":
            if not isinstance(val, (list, tuple)):
                violations.append("mole_view.docs:not_a_sequence")
                continue
            for idx, doc in enumerate(val):
                doc_map = _object_fields(doc)
                if doc_map is None:
                    violations.append(f"mole_view.docs[{idx}]:invalid_doc_type")
                    continue
                for dkey, dval in sorted(doc_map.items()):
                    if dkey.lower() in PRIVILEGED_FIELD_NAMES:
                        violations.append(f"mole_view.docs[{idx}].{dkey}:privileged_doc_field")
                    elif dkey not in ALLOWED_MOLE_DOC_FIELDS:
                        violations.append(f"mole_view.docs[{idx}].{dkey}:unauthorized_doc_field")
                    _check_strings_for_privileged_leaks(dval, f"mole_view.docs[{idx}].{dkey}", violations)
        else:
            _check_strings_for_privileged_leaks(val, f"mole_view.{key}", violations)

    return list(dict.fromkeys(violations))


class _MoleViewRecorder:
    def __init__(self, inner: MoleStrategy):
        self.inner = inner
        self.views: list[MoleView] = []

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, Any]:
        self.views.append(view)
        return self.inner.decide(view, rng)


def _make_doc_portfolio(
    n_docs: int,
    min_rc: int,
    max_rc: int,
    n_low: int,
    newest_age: int,
    max_age: int,
) -> tuple[MoleDoc, ...]:
    if n_docs <= 0:
        return ()
    if n_docs == 1:
        return (MoleDoc("d0", "Doc 0", max_rc, newest_age),)
    if n_docs == 2:
        return (
            MoleDoc("d0", "Doc 0", min_rc, max_age),
            MoleDoc("d1", "Doc 1", max_rc, newest_age),
        )
    mid_rc = max(min_rc + 1, min(max_rc - 1, (min_rc + max_rc) // 2))
    if min_rc >= max_rc:
        mid_rc = min_rc
    ages = [max_age] * (n_docs // 2) + [newest_age] * (n_docs - n_docs // 2)
    rcs: list[int] = []
    for idx in range(n_docs):
        if idx == 0:
            rcs.append(mid_rc if n_low < n_docs else min_rc)
        elif idx == 1:
            rcs.append(min_rc)
        elif idx == n_docs - 1:
            rcs.append(max_rc)
        else:
            low_so_far = sum(1 for x in rcs if x <= 3)
            rcs.append(2 if low_so_far < n_low else max(4, mid_rc))
    return tuple(MoleDoc(f"d{idx}", f"Doc {idx}", rcs[idx], ages[idx]) for idx in range(n_docs))


@functools.lru_cache(maxsize=1)
def build_synthetic_mole_views() -> tuple[MoleView, ...]:
    peers = tuple(f"e{i:02d}" for i in range(1, 20))
    restricted_pool = peers[1:]
    views: list[MoleView] = []

    core_portfolios = (
        (0, 0, 0, 0, 0),
        (1, 2, 2, 1, 0),
        (2, 2, 5, 1, 0),
        (3, 2, 6, 1, 0),
        (4, 2, 4, 2, 0),
        (4, 2, 6, 1, 0),
        (4, 2, 8, 2, 1),
        (4, 5, 9, 0, 0),
        (5, 1, 5, 2, 0),
    )

    for day in range(1, 16):
        dsll_values = sorted({1, min(3, day), min(6, day), day})
        for dsll in dsll_values:
            for restr, n_rc in ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1)):
                if (day + dsll + restr + n_rc) % 2 != 0:
                    continue
                rpeers = restricted_pool[:n_rc]
                for n_docs, min_rc, max_rc, n_low, newest_age in core_portfolios:
                    if newest_age > day - 1:
                        continue
                    max_age = max(newest_age, min(2, day - 1))
                    docs = _make_doc_portfolio(n_docs, min_rc, max_rc, n_low, newest_age, max_age)
                    actual_low = sum(1 for d in docs if d.recipient_count <= 3)
                    views.append(
                        MoleView(
                            day=day,
                            docs=docs,
                            days_since_last_leak=dsll,
                            i_am_restricted=restr,
                            n_restricted_colleagues=n_rc,
                            recent_low_recipient_docs=actual_low,
                            peers=peers,
                            restricted_peers=rpeers,
                            decoy="e01",
                            can_leak=(n_docs > 0),
                        )
                    )

    for day in range(1, 22):
        max_age = min(2, day - 1)
        for max_rc in (2, 3, 4, 5, 6, 7, 8):
            min_rc = min(2, max_rc)
            for n_docs in (1, 2, 3, 4, 5, 7):
                docs = _make_doc_portfolio(n_docs, min_rc, max_rc, 2 if min_rc <= 3 else 0, 0, max_age)
                actual_low = sum(1 for d in docs if d.recipient_count <= 3)
                for dsll in sorted({1, min(2, day), min(4, day), min(7, day), day}):
                    if (day + max_rc + n_docs + dsll) % 4 != 0:
                        continue
                    n_rc = max_rc % 3
                    views.append(
                        MoleView(
                            day=day,
                            docs=docs,
                            days_since_last_leak=dsll,
                            i_am_restricted=day % 2,
                            n_restricted_colleagues=n_rc,
                            recent_low_recipient_docs=actual_low,
                            peers=peers,
                            restricted_peers=restricted_pool[:n_rc],
                            decoy="e01",
                            can_leak=True,
                        )
                    )

    gate_closed_docs = _make_doc_portfolio(4, 2, 7, 2, 0, 1)
    for day in (2, 5, 9, 13):
        for decoy in ("e01", None):
            for n_rc in (0, 2):
                views.append(
                    MoleView(
                        day=day,
                        docs=gate_closed_docs,
                        days_since_last_leak=min(2, day),
                        i_am_restricted=0,
                        n_restricted_colleagues=n_rc,
                        recent_low_recipient_docs=sum(1 for d in gate_closed_docs if d.recipient_count <= 3),
                        peers=peers,
                        restricted_peers=restricted_pool[:n_rc],
                        decoy=decoy,
                        can_leak=False,
                    )
                )
                views.append(
                    MoleView(
                        day=day,
                        docs=gate_closed_docs,
                        days_since_last_leak=day,
                        i_am_restricted=1,
                        n_restricted_colleagues=n_rc,
                        recent_low_recipient_docs=sum(1 for d in gate_closed_docs if d.recipient_count <= 3),
                        peers=peers,
                        restricted_peers=restricted_pool[:n_rc],
                        decoy=decoy,
                        can_leak=True,
                    )
                )

    return tuple(views)


_RNG_STATE_A = random.Random(104729).getstate()
_RNG_STATE_B = random.Random(130363).getstate()


def behavioral_signature(
    strategy: MoleStrategy | Mapping[str, Any],
    views: Sequence[MoleView] | None = None,
) -> str:
    parsed = coerce_strategy(strategy)
    eval_views = build_synthetic_mole_views() if views is None else views
    rng_a = random.Random()
    rng_b = random.Random()
    digest = hashlib.sha256()
    for view in eval_views:
        rng_a.setstate(_RNG_STATE_A)
        rng_b.setstate(_RNG_STATE_B)
        move_a = parsed.decide(view, rng_a)
        move_b = parsed.decide(view, rng_b)
        token = f"{move_a.get('leak')},{move_a.get('frame')};{move_b.get('leak')},{move_b.get('frame')}|"
        digest.update(token.encode("ascii"))
    return digest.hexdigest()[:16]


def compute_equivalence_classes(
    items: Sequence[StrategyEntry | MoleStrategy | Mapping[str, Any]],
    views: Sequence[MoleView] | None = None,
) -> BehavioralEquivalenceSummary:
    eval_views = build_synthetic_mole_views() if views is None else views
    normalized_items: list[tuple[str, str, str, str, MoleStrategy]] = []
    for idx, item in enumerate(items):
        if isinstance(item, StrategyEntry):
            normalized_items.append((item.run_id, item.source_kind, item.tier, item.label, item.strategy))
        else:
            parsed = coerce_strategy(item)
            label = parsed.name if parsed.name != "custom" else f"strategy_{idx}"
            normalized_items.append(("inline", "inline", "hard", label, parsed))

    syntactic_keys = {canonical_strategy_json(strat) for _, _, _, _, strat in normalized_items}
    grouped: dict[str, list[dict[str, str]]] = {}
    for run_id, source_kind, tier, label, strat in normalized_items:
        sig = behavioral_signature(strat, views=eval_views)
        grouped.setdefault(sig, []).append({
            "run_id": run_id,
            "source_kind": source_kind,
            "tier": tier,
            "label": label,
        })

    classes: list[BehavioralEquivalenceClass] = []
    for sig, members in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[1][0]["run_id"], kv[1][0]["label"], kv[0])):
        rep = members[0]
        kinds = tuple(sorted({m["source_kind"] for m in members}))
        classes.append(
            BehavioralEquivalenceClass(
                signature=sig,
                representative_run_id=rep["run_id"],
                representative_label=rep["label"],
                source_kinds=kinds,
                member_count=len(members),
                members=tuple(members),
            )
        )

    return BehavioralEquivalenceSummary(
        n_strategies=len(normalized_items),
        n_syntactic_unique=len(syntactic_keys),
        n_equivalence_classes=len(classes),
        n_synthetic_views=len(eval_views),
        classes=tuple(classes),
    )


def _count_leaks(env: Env) -> int:
    return sum(1 for entry in env.ledger() if entry.event == "leak")


def _steps_signature(env: Env) -> list[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    return [(s.day, s.tool, s.args, s.result) for s in env.history]


def replay_strategy(
    strategy: MoleStrategy | Mapping[str, Any],
    *,
    tier: str = "hard",
    seeds: Sequence[int] = DEFAULT_DEV_SEEDS,
    run_id: str = "inline",
    source_kind: str = "inline",
    strategy_label: str | None = None,
) -> StrategyReplayReport:
    if tier not in TIERS and tier not in TRACKS:
        raise ValueError(f"unknown tier {tier!r}")
    seed_tuple = validate_dev_seeds(seeds)
    parsed = coerce_strategy(strategy)
    resolved_label = strategy_label or parsed.name
    sig = behavioral_signature(parsed)

    episodes: list[EpisodeReplayAudit] = []
    all_violations: list[str] = []
    total_views = 0

    for seed in seed_tuple:
        env_s1 = Env(tier, seed, mole_strategy=parsed)
        score_s1 = float(play(env_s1, SolverPolicy()))
        verdict_s1 = env_s1.verdict()
        leaks_s1 = _count_leaks(env_s1)

        rec_s = _MoleViewRecorder(parsed)
        env_s2 = Env(tier, seed, mole_strategy=rec_s)
        score_s2 = float(play(env_s2, SolverPolicy()))
        verdict_s2 = env_s2.verdict()
        leaks_s2 = _count_leaks(env_s2)

        solver_det = (
            score_s1 == score_s2
            and verdict_s1 == verdict_s2
            and leaks_s1 == leaks_s2
            and _steps_signature(env_s1) == _steps_signature(env_s2)
        )

        env_o1 = Env(tier, seed, mole_strategy=parsed)
        score_o1 = float(play(env_o1, ObviousHeuristic(seed=seed)))
        verdict_o1 = env_o1.verdict()
        leaks_o1 = _count_leaks(env_o1)

        rec_o = _MoleViewRecorder(parsed)
        env_o2 = Env(tier, seed, mole_strategy=rec_o)
        score_o2 = float(play(env_o2, ObviousHeuristic(seed=seed)))
        verdict_o2 = env_o2.verdict()
        leaks_o2 = _count_leaks(env_o2)

        obvious_det = (
            score_o1 == score_o2
            and verdict_o1 == verdict_o2
            and leaks_o1 == leaks_o2
            and _steps_signature(env_o1) == _steps_signature(env_o2)
        )

        seed_violations: list[str] = []
        for view_idx, recorded_view in enumerate(rec_s.views):
            for v in check_mole_view_privileges(recorded_view):
                seed_violations.append(f"seed[{seed}].solver[{view_idx}].{v}")
        for view_idx, recorded_view in enumerate(rec_o.views):
            for v in check_mole_view_privileges(recorded_view):
                seed_violations.append(f"seed[{seed}].obvious[{view_idx}].{v}")

        dedup_seed_viols = tuple(dict.fromkeys(seed_violations))
        all_violations.extend(dedup_seed_viols)
        seed_views = len(rec_s.views) + len(rec_o.views)
        total_views += seed_views

        episodes.append(
            EpisodeReplayAudit(
                seed=seed,
                solver_score=score_s1,
                solver_repro_score=score_s2,
                solver_correct=bool(verdict_s1["correct"]),
                solver_repro_correct=bool(verdict_s2["correct"]),
                solver_accused=verdict_s1["accused"],
                solver_leak_count=leaks_s1,
                obvious_score=score_o1,
                obvious_repro_score=score_o2,
                obvious_correct=bool(verdict_o1["correct"]),
                obvious_repro_correct=bool(verdict_o2["correct"]),
                obvious_accused=verdict_o1["accused"],
                obvious_leak_count=leaks_o1,
                views_checked=seed_views,
                privileged_field_violations=dedup_seed_viols,
                deterministic=(solver_det and obvious_det),
            )
        )

    solver_mean = float(mean(ep.solver_score for ep in episodes))
    solver_acc = float(mean(1.0 if ep.solver_correct else 0.0 for ep in episodes))
    obvious_mean = float(mean(ep.obvious_score for ep in episodes))
    obvious_acc = float(mean(1.0 if ep.obvious_correct else 0.0 for ep in episodes))
    margin = solver_mean - obvious_mean
    total_leaks = sum(ep.solver_leak_count for ep in episodes)
    min_seed_leaks = min(ep.solver_leak_count for ep in episodes)
    obvious_leaks = sum(ep.obvious_leak_count for ep in episodes)
    dedup_all_viols = tuple(dict.fromkeys(all_violations))

    deterministic_ok = all(ep.deterministic for ep in episodes)
    leaks_ok = total_leaks >= 1
    catchable_ok = solver_mean > obvious_mean
    mole_view_clean_ok = len(dedup_all_viols) == 0 and total_views >= 1
    passed = deterministic_ok and leaks_ok and catchable_ok and mole_view_clean_ok

    return StrategyReplayReport(
        run_id=run_id,
        source_kind=source_kind,
        tier=tier,
        strategy_label=resolved_label,
        behavioral_signature=sig,
        seeds=seed_tuple,
        episodes=tuple(episodes),
        solver_mean_score=solver_mean,
        solver_accuracy=solver_acc,
        obvious_mean_score=obvious_mean,
        obvious_accuracy=obvious_acc,
        catchability_margin=margin,
        total_leak_count=total_leaks,
        min_seed_leak_count=min_seed_leaks,
        obvious_total_leak_count=obvious_leaks,
        views_checked=total_views,
        privileged_field_violations=dedup_all_viols,
        deterministic_ok=deterministic_ok,
        leaks_ok=leaks_ok,
        catchable_ok=catchable_ok,
        mole_view_clean_ok=mole_view_clean_ok,
        passed=passed,
    )


def audit_adaptive_mole_runs(
    roles_dir: str | Path = DEFAULT_ROLES_DIR,
    *,
    seeds: Sequence[int] = DEFAULT_DEV_SEEDS,
) -> ReplayAuditSummary:
    seed_tuple = validate_dev_seeds(seeds)
    resolved_dir = Path(roles_dir)
    loaded_runs = load_strategy_runs(resolved_dir)

    reports: list[StrategyReplayReport] = []
    all_entries: list[StrategyEntry] = []
    top_entries: list[StrategyEntry] = []

    for run in loaded_runs:
        all_entries.extend(run.entries)
        top_entries.append(run.top_entry)
        reports.append(
            replay_strategy(
                run.top_strategy,
                tier=run.tier,
                seeds=seed_tuple,
                run_id=run.run_id,
                source_kind=run.source_kind,
                strategy_label=run.top_entry.label,
            )
        )

    all_eq = compute_equivalence_classes(all_entries)
    top_eq = compute_equivalence_classes(top_entries)
    n_forge = sum(1 for r in loaded_runs if r.source_kind == "mole_forge")
    n_paired = sum(1 for r in loaded_runs if r.source_kind == "paired_designer")

    return ReplayAuditSummary(
        roles_dir=str(resolved_dir),
        populated=bool(loaded_runs),
        seeds=seed_tuple,
        n_runs=len(loaded_runs),
        n_mole_forge_runs=n_forge,
        n_paired_designer_runs=n_paired,
        all_passed=all(r.passed for r in reports),
        runs=tuple(reports),
        all_strategies_equivalence=all_eq,
        top_strategies_equivalence=top_eq,
    )


def format_summary_table(summary: ReplayAuditSummary) -> str:
    if not summary.populated:
        return (
            f"roles_dir={summary.roles_dir} populated=false n_runs=0 "
            f"equivalence_classes=0/0"
        )
    header = (
        f"{'run_id':<40} {'kind':<16} {'tier':<7} {'solver':>7} "
        f"{'obvious':>8} {'leaks':>6} {'views':>6} {'sig':<16} {'status':<6}"
    )
    lines = [header, "-" * len(header)]
    for rep in summary.runs:
        status = "PASS" if rep.passed else "FAIL"
        lines.append(
            f"{rep.run_id[:40]:<40} {rep.source_kind:<16} {rep.tier:<7} "
            f"{rep.solver_mean_score:+7.3f} {rep.obvious_mean_score:+8.3f} "
            f"{rep.total_leak_count:6d} {rep.views_checked:6d} "
            f"{rep.behavioral_signature:<16} {status:<6}"
        )
    all_eq = summary.all_strategies_equivalence
    top_eq = summary.top_strategies_equivalence
    lines.append(
        f"runs={summary.n_runs} (mole_forge={summary.n_mole_forge_runs}, "
        f"paired_designer={summary.n_paired_designer_runs}) "
        f"all_strategies_classes={all_eq.n_equivalence_classes}/{all_eq.n_strategies} "
        f"top_strategies_classes={top_eq.n_equivalence_classes}/{top_eq.n_strategies} "
        f"all_passed={summary.all_passed}"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m canary.gemini.mole_replay_audit")
    parser.add_argument(
        "--roles-dir",
        default=str(DEFAULT_ROLES_DIR),
        help="Adaptive mole roles directory (default: results/gemini/roles_carbon/adaptive_mole)",
    )
    parser.add_argument(
        "--seeds",
        default="0..4",
        help="Dev seed range or list (default: 0..4)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write JSON audit output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON audit report to stdout",
    )
    parser.add_argument(
        "--require-populated",
        action="store_true",
        help="Return non-zero exit code if roles directory has zero runs",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    seeds = parse_seeds(args.seeds)
    summary = audit_adaptive_mole_runs(args.roles_dir, seeds=seeds)
    payload = summary.to_dict()

    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_summary_table(summary))

    if not summary.all_passed:
        return 1
    if args.require_populated and not summary.populated:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
