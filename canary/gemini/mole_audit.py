from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
import dataclasses
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from canary.agents.mole_arena import LLMMole
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FEATURES,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleStrategy,
    MoleView,
    OPS,
    StrategyError,
)
from canary.rules import tier_params
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FORGE_DIR = ROOT / "data" / "forge"
CONFIRMATION_SEEDS: tuple[int, ...] = tuple(range(5000, 5020))
MIN_SOLVER_ACCURACY: float = 0.75
DEFAULT_TIER: str = "hard"
DEFAULT_LOW_RECIPIENT_THRESHOLD: int = 3

ALLOWED_VIEW_FIELDS = frozenset({
    "day",
    "docs",
    "held_docs",
    "leakable",
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

ALLOWED_DOC_FIELDS = frozenset({
    "doc_id",
    "title",
    "recipient_count",
    "age_days",
})

ALLOWED_LOG_ENVELOPE_FIELDS = frozenset({
    "tier",
    "seed",
    "investigator",
    "day",
    "mole_view",
    "view",
    "prompt_view",
    "move",
    "leak",
    "frame",
    "reason",
    "rejected",
    "error",
})

ALLOWED_MOVE_FIELDS = frozenset({
    "leak",
    "frame",
    "reason",
})

CANARY_KEY_NAMES = frozenset({
    "is_canary",
    "canary",
    "canary_flag",
    "canary_id",
    "canary_ids",
    "canaries_planted",
    "planted_canaries",
    "canary_doc",
    "is_trap",
})

VARIANT_KEY_NAMES = frozenset({
    "variant",
    "variants",
    "true_variant",
    "assignment",
    "variant_assignment",
    "fingerprint",
    "fingerprint_accuracy",
    "canary_variant",
})

BELIEF_KEY_NAMES = frozenset({
    "belief",
    "beliefs",
    "posterior",
    "posteriors",
    "investigator_belief",
    "suspect_posterior",
    "suspect_probs",
    "suspicion",
    "accuse_prob",
    "investigator_history",
    "investigator_steps",
    "solver_belief",
})

SECRET_KEY_NAMES = frozenset({
    "secret",
    "secrets",
    "secret_key",
    "world_secret",
    "world_seed",
    "ledger_token",
    "api_key",
    "gemini_api_key",
    "google_api_key",
    "google_generative_ai_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "xai_api_key",
    "canary_world_secret",
    "canary_ledger_token",
    "salt",
    "private_key",
    "token",
})

SECRET_ENV_VARS = (
    "CANARY_WORLD_SECRET",
    "CANARY_LEDGER_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)

SAFE_PLACEHOLDERS = frozenset({
    "",
    "null",
    "none",
    "false",
    "true",
    "unset",
    "redacted",
    "[redacted]",
    "<redacted>",
    "empty",
    "missing",
})

GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{8,}")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
PREFIXED_SECRET_RE = re.compile(r"(?<![A-Za-z0-9_])(?:ws|tok)-[0-9a-fA-F]{16,}")
ENV_ASSIGN_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY|"
    r"CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
STRUCTURED_CANARY_RE = re.compile(
    r"[\"']is_canary[\"']\s*:|\bis_canary\s*=\s*(?:True|False|true|false|1|0)\b"
)
STRUCTURED_VARIANT_RE = re.compile(
    r"[\"'](?:variant|variants|true_variant)[\"']\s*:|\bvariant\s*=\s*[\"'][A-Za-z0-9_\-]+[\"']"
)
STRUCTURED_BELIEF_RE = re.compile(
    r"[\"'](?:belief|beliefs|posterior|posteriors|investigator_belief|suspect_probs)[\"']\s*:"
)


@dataclass(frozen=True)
class IsolationViolation:
    category: str
    path: str
    field: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "path": self.path,
            "field": self.field,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IsolationReport:
    passed: bool
    views_checked: int
    violations: tuple[IsolationViolation, ...]
    categories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "views_checked": self.views_checked,
            "categories": list(self.categories),
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass(frozen=True)
class DeceptionMetrics:
    n_decisions: int
    n_leak_opportunities: int
    n_silent_decisions: int
    n_leaks: int
    n_frames: int
    n_decoy_frames: int
    n_peer_frames: int
    n_low_recipient_opportunities: int
    n_low_recipient_evaded: int
    low_recipient_threshold: int
    strategic_silence_rate: float
    framing_rate: float
    decoy_framing_rate: float
    peer_framing_rate: float
    low_recipient_canary_evasion_rate: float

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class SeedSolvability:
    seed: int
    correct: bool
    score: float
    accused: str | None
    final_day: int
    end_reason: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class SolvabilityReport:
    passed: bool
    tier: str
    seeds: tuple[int, ...]
    min_accuracy: float
    catch_accuracy: float
    mean_score: float
    mean_final_day: float
    episodes: tuple[SeedSolvability, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tier": self.tier,
            "seeds": list(self.seeds),
            "min_accuracy": self.min_accuracy,
            "catch_accuracy": self.catch_accuracy,
            "mean_score": self.mean_score,
            "mean_final_day": self.mean_final_day,
            "episodes": [ep.to_dict() for ep in self.episodes],
        }


@dataclass(frozen=True)
class MoleAuditReport:
    name: str
    kind: str
    passed: bool
    isolation: IsolationReport
    deception: DeceptionMetrics
    solvability: SolvabilityReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "isolation": self.isolation.to_dict(),
            "deception": self.deception.to_dict(),
            "solvability": self.solvability.to_dict() if self.solvability is not None else None,
        }


def _dedupe_violations(items: Iterable[IsolationViolation]) -> tuple[IsolationViolation, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[IsolationViolation] = []
    for item in items:
        key = (item.category, item.path, item.field, item.detail)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return tuple(out)


def _make_isolation_report(violations: Iterable[IsolationViolation], views_checked: int) -> IsolationReport:
    deduped = _dedupe_violations(violations)
    cats = tuple(sorted({v.category for v in deduped}))
    return IsolationReport(
        passed=len(deduped) == 0,
        views_checked=views_checked,
        violations=deduped,
        categories=cats,
    )


def _classify_forbidden_key(name: str) -> str | None:
    norm = str(name).strip().lower().lstrip("_")
    if not norm:
        return None
    if norm in CANARY_KEY_NAMES or "is_canary" in norm:
        return "is_canary"
    if norm in VARIANT_KEY_NAMES or "variant" in norm:
        return "variant"
    if norm in BELIEF_KEY_NAMES or "belief" in norm or "posterior" in norm:
        return "investigator_belief"
    if (
        norm in SECRET_KEY_NAMES
        or "secret" in norm
        or "api_key" in norm
        or "ledger_token" in norm
        or "world_seed" in norm
    ):
        return "secret_key"
    return None


def _has_env_secret_assignment(text: str) -> bool:
    for match in ENV_ASSIGN_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            return True
    return False


def _normalize_secrets(known_secrets: Sequence[str | bytes] = ()) -> tuple[str, ...]:
    collected: list[str] = []
    for item in known_secrets:
        if isinstance(item, (bytes, bytearray)):
            s = bytes(item).decode("latin-1").strip()
        else:
            s = str(item or "").strip()
        if len(s) >= 4 and s.lower() not in SAFE_PLACEHOLDERS:
            collected.append(s)
    for var in SECRET_ENV_VARS:
        val = (os.environ.get(var) or "").strip()
        if len(val) >= 6 and val.lower() not in SAFE_PLACEHOLDERS:
            collected.append(val)
    return tuple(dict.fromkeys(collected))


def _extract_mapping(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, Mapping):
        return {str(k): v for k, v in obj.items()}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
        extra = getattr(obj, "__dict__", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                ks = str(k)
                if not (ks.startswith("__") and ks.endswith("__")):
                    out[ks] = v
        return out
    if hasattr(obj, "__dict__") and not isinstance(obj, (type, str, bytes, bytearray)):
        return {
            str(k): v
            for k, v in vars(obj).items()
            if not (str(k).startswith("__") and str(k).endswith("__"))
        }
    return None


def _scan_string_violations(
    text: str,
    path: str,
    field: str,
    known_secrets: tuple[str, ...],
    *,
    check_structured_leak: bool = True,
) -> list[IsolationViolation]:
    out: list[IsolationViolation] = []
    if GOOGLE_KEY_RE.search(text):
        out.append(IsolationViolation("secret_key", path, field, "google_api_key pattern in mole payload"))
    if SK_KEY_RE.search(text):
        out.append(IsolationViolation("secret_key", path, field, "sk_api_key pattern in mole payload"))
    if OAUTH_RE.search(text):
        out.append(IsolationViolation("secret_key", path, field, "oauth_token pattern in mole payload"))
    if PREFIXED_SECRET_RE.search(text):
        out.append(IsolationViolation("secret_key", path, field, "world or ledger secret token in mole payload"))
    if _has_env_secret_assignment(text):
        out.append(IsolationViolation("secret_key", path, field, "secret env assignment in mole payload"))
    if any(sec in text for sec in known_secrets):
        out.append(IsolationViolation("secret_key", path, field, "known secret value present in mole payload"))
    if check_structured_leak:
        if STRUCTURED_CANARY_RE.search(text):
            out.append(IsolationViolation("is_canary", path, field, "structured is_canary leakage in text"))
        if STRUCTURED_VARIANT_RE.search(text):
            out.append(IsolationViolation("variant", path, field, "structured variant leakage in text"))
        if STRUCTURED_BELIEF_RE.search(text):
            out.append(
                IsolationViolation(
                    "investigator_belief",
                    path,
                    field,
                    "structured investigator belief leakage in text",
                )
            )
    return out


def _scan_nested_value(
    val: Any,
    path: str,
    field: str,
    known_secrets: tuple[str, ...],
    *,
    check_keys: bool = True,
    check_structured_leak: bool = True,
) -> list[IsolationViolation]:
    if val is None or isinstance(val, (int, float, bool)):
        return []
    if isinstance(val, (bytes, bytearray)):
        decoded = bytes(val).decode("latin-1")
        return _scan_string_violations(
            decoded,
            path,
            field,
            known_secrets,
            check_structured_leak=check_structured_leak,
        )
    if isinstance(val, str):
        return _scan_string_violations(
            val,
            path,
            field,
            known_secrets,
            check_structured_leak=check_structured_leak,
        )
    if isinstance(val, (list, tuple, set, frozenset)):
        out: list[IsolationViolation] = []
        for idx, item in enumerate(val):
            out.extend(
                _scan_nested_value(
                    item,
                    f"{path}[{idx}]",
                    field,
                    known_secrets,
                    check_keys=check_keys,
                    check_structured_leak=check_structured_leak,
                )
            )
        return out
    mapping = _extract_mapping(val)
    if mapping is not None:
        out = []
        for k, v in mapping.items():
            sub_path = f"{path}.{k}"
            if check_keys:
                cat = _classify_forbidden_key(k)
                if cat is not None:
                    out.append(IsolationViolation(cat, sub_path, k, f"forbidden {cat} field in nested payload"))
            out.extend(
                _scan_nested_value(
                    v,
                    sub_path,
                    k,
                    known_secrets,
                    check_keys=check_keys,
                    check_structured_leak=check_structured_leak,
                )
            )
        return out
    return []


def audit_view_isolation(
    view: Any,
    *,
    path: str = "mole_view",
    known_secrets: Sequence[str | bytes] = (),
) -> list[IsolationViolation]:
    secrets = _normalize_secrets(known_secrets)
    mapping = _extract_mapping(view)
    if mapping is None:
        return [
            IsolationViolation(
                "unexpected_field",
                path,
                type(view).__name__,
                "mole view must be a MoleView, mapping, or attribute object",
            )
        ]
    violations: list[IsolationViolation] = []
    for k, v in mapping.items():
        field_path = f"{path}.{k}"
        cat = _classify_forbidden_key(k)
        if cat is not None:
            violations.append(IsolationViolation(cat, field_path, k, f"forbidden {cat} field in mole view"))
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
            continue
        if k not in ALLOWED_VIEW_FIELDS:
            violations.append(
                IsolationViolation("unexpected_field", field_path, k, f"unauthorized field {k!r} in mole view")
            )
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
            continue
        if k in ("docs", "held_docs") and v is not None:
            if not isinstance(v, (list, tuple)):
                violations.append(
                    IsolationViolation("unexpected_field", field_path, k, "document list must be a sequence")
                )
                continue
            for idx, doc in enumerate(v):
                doc_path = f"{field_path}[{idx}]"
                doc_map = _extract_mapping(doc)
                if doc_map is None:
                    violations.append(
                        IsolationViolation("unexpected_field", doc_path, k, "document entry must be an object or dict")
                    )
                    continue
                for dk, dv in doc_map.items():
                    dk_path = f"{doc_path}.{dk}"
                    dcat = _classify_forbidden_key(dk)
                    if dcat is not None:
                        violations.append(
                            IsolationViolation(dcat, dk_path, dk, f"forbidden {dcat} field in mole document")
                        )
                    elif dk not in ALLOWED_DOC_FIELDS:
                        violations.append(
                            IsolationViolation(
                                "unexpected_field",
                                dk_path,
                                dk,
                                f"unauthorized document field {dk!r}",
                            )
                        )
                    violations.extend(_scan_nested_value(dv, dk_path, dk, secrets))
        else:
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
    return list(_dedupe_violations(violations))


def _unwrap_strategy_dict(obj: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    if "strategy_json" in obj:
        outer = {k: v for k, v in obj.items() if k != "strategy_json"}
        return obj["strategy_json"], outer
    if "strategy" in obj and isinstance(obj.get("strategy"), Mapping):
        outer = {k: v for k, v in obj.items() if k != "strategy"}
        return obj["strategy"], outer
    return dict(obj), None


def audit_strategy_dsl_isolation(
    strategy_obj: Any,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> IsolationReport:
    secrets = _normalize_secrets(known_secrets)
    violations: list[IsolationViolation] = []
    if isinstance(strategy_obj, MoleStrategy):
        raw: Any = strategy_obj.to_json()
    elif isinstance(strategy_obj, Mapping):
        raw, outer = _unwrap_strategy_dict(strategy_obj)
        if outer is not None:
            violations.extend(
                _scan_nested_value(outer, "hof_entry", "hof_entry", secrets, check_keys=False)
            )
    else:
        return _make_isolation_report(
            [IsolationViolation("unexpected_field", "strategy", "type", "strategy must be MoleStrategy or dict")],
            views_checked=0,
        )

    if not isinstance(raw, Mapping):
        return _make_isolation_report(
            [IsolationViolation("unexpected_field", "strategy", "type", "strategy JSON must be an object")],
            views_checked=0,
        )

    for k, v in raw.items():
        if k not in {"rules", "default", "name"}:
            cat = _classify_forbidden_key(str(k)) or "unexpected_field"
            violations.append(
                IsolationViolation(cat, f"strategy.{k}", str(k), f"unauthorized key {k!r} in strategy")
            )
        violations.extend(_scan_nested_value(v, f"strategy.{k}", str(k), secrets, check_keys=False))

    rules = raw.get("rules", [])
    if isinstance(rules, list):
        for r_idx, rule in enumerate(rules):
            r_path = f"strategy.rules[{r_idx}]"
            if not isinstance(rule, Mapping):
                violations.append(IsolationViolation("unexpected_field", r_path, "rule", "rule must be an object"))
                continue
            for rk in rule:
                if rk not in {"if", "then"}:
                    cat = _classify_forbidden_key(str(rk)) or "unexpected_field"
                    violations.append(
                        IsolationViolation(cat, f"{r_path}.{rk}", str(rk), f"unauthorized rule key {rk!r}")
                    )
            conds = rule.get("if", [])
            if isinstance(conds, list):
                for c_idx, cond in enumerate(conds):
                    c_path = f"{r_path}.if[{c_idx}]"
                    feat: str | None = None
                    op: str | None = None
                    if isinstance(cond, str):
                        parts = cond.split()
                        feat = parts[0] if parts else ""
                        op = parts[1] if len(parts) > 1 else None
                    elif isinstance(cond, (list, tuple)) and len(cond) >= 1:
                        feat = str(cond[0])
                        op = str(cond[1]) if len(cond) > 1 else None
                    if feat is not None:
                        cat = _classify_forbidden_key(feat)
                        if cat is not None:
                            violations.append(
                                IsolationViolation(
                                    cat,
                                    c_path,
                                    feat,
                                    f"forbidden {cat} feature {feat!r} in strategy condition",
                                )
                            )
                        elif feat not in FEATURES:
                            violations.append(
                                IsolationViolation(
                                    "unexpected_field",
                                    c_path,
                                    feat,
                                    f"unknown feature {feat!r} in strategy condition",
                                )
                            )
                    if op is not None and op not in OPS:
                        violations.append(
                            IsolationViolation("unexpected_field", c_path, str(op), f"invalid operator {op!r}")
                        )
            then_obj = rule.get("then")
            if isinstance(then_obj, Mapping):
                _audit_then_clause(then_obj, f"{r_path}.then", violations)

    default_obj = raw.get("default")
    if isinstance(default_obj, Mapping):
        _audit_then_clause(default_obj, "strategy.default", violations)

    try:
        MoleStrategy.from_json(dict(raw))
    except StrategyError as exc:
        if not violations:
            violations.append(IsolationViolation("unexpected_field", "strategy", "dsl", str(exc)))

    return _make_isolation_report(violations, views_checked=0)


def _audit_then_clause(then_obj: Mapping[str, Any], path: str, violations: list[IsolationViolation]) -> None:
    for tk, tv in then_obj.items():
        tks = str(tk)
        if tks not in {"leak", "frame"}:
            cat = _classify_forbidden_key(tks) or "unexpected_field"
            violations.append(IsolationViolation(cat, f"{path}.{tks}", tks, f"unauthorized action key {tks!r}"))
            continue
        if tv is None:
            continue
        tvs = str(tv)
        valid = LEAK_SELECTORS if tks == "leak" else FRAME_SELECTORS
        if tvs not in valid:
            cat = _classify_forbidden_key(tvs) or "unexpected_field"
            violations.append(IsolationViolation(cat, f"{path}.{tks}", tvs, f"invalid {tks} selector {tvs!r}"))


def _is_log_envelope(mapping: Mapping[str, Any]) -> bool:
    if any(k in mapping for k in ("mole_view", "view", "prompt_view", "move", "rejected", "reason")):
        return True
    if ("leak" in mapping or "frame" in mapping) and "docs" not in mapping and "held_docs" not in mapping:
        return True
    return False


def _audit_single_record(
    record: Any,
    idx: int,
    secrets: tuple[str, ...],
) -> tuple[list[IsolationViolation], int]:
    if isinstance(record, MoleView):
        return audit_view_isolation(record, path=f"records[{idx}]", known_secrets=secrets), 1
    if isinstance(record, tuple) and len(record) == 2:
        view, move = record
        viols = audit_view_isolation(view, path=f"records[{idx}].view", known_secrets=secrets)
        viols.extend(_scan_nested_value(move, f"records[{idx}].move", "move", secrets))
        return viols, 1
    mapping = _extract_mapping(record)
    if mapping is None:
        return [
            IsolationViolation(
                "unexpected_field",
                f"records[{idx}]",
                type(record).__name__,
                "decision record must be a dict, MoleView, or (view, move) pair",
            )
        ], 0
    if not _is_log_envelope(mapping):
        return audit_view_isolation(record, path=f"records[{idx}]", known_secrets=secrets), 1

    violations: list[IsolationViolation] = []
    views_checked = 0
    for k, v in mapping.items():
        field_path = f"records[{idx}].{k}"
        cat = _classify_forbidden_key(k)
        if cat is not None:
            violations.append(IsolationViolation(cat, field_path, k, f"forbidden {cat} field in decision log"))
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
            continue
        if k not in ALLOWED_LOG_ENVELOPE_FIELDS:
            violations.append(
                IsolationViolation("unexpected_field", field_path, k, f"unauthorized log field {k!r}")
            )
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
            continue
        if k in ("mole_view", "view", "prompt_view"):
            if v is not None:
                views_checked += 1
                violations.extend(audit_view_isolation(v, path=field_path, known_secrets=secrets))
        elif k == "move" and v is not None:
            move_map = _extract_mapping(v)
            if move_map is None:
                violations.append(IsolationViolation("unexpected_field", field_path, k, "move must be a mapping"))
            else:
                for mk, mv in move_map.items():
                    mk_path = f"{field_path}.{mk}"
                    mcat = _classify_forbidden_key(mk)
                    if mcat is not None:
                        violations.append(IsolationViolation(mcat, mk_path, mk, f"forbidden {mcat} field in move"))
                    elif mk not in ALLOWED_MOVE_FIELDS:
                        violations.append(
                            IsolationViolation("unexpected_field", mk_path, mk, f"unauthorized move field {mk!r}")
                        )
                    violations.extend(_scan_nested_value(mv, mk_path, mk, secrets))
        else:
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
    return violations, views_checked


def _audit_llm_mole_internals(mole: Any, secrets: tuple[str, ...]) -> tuple[list[IsolationViolation], int]:
    violations: list[IsolationViolation] = []
    views_checked = 0

    sys_prompt = getattr(mole, "system", None)
    if isinstance(sys_prompt, str):
        violations.extend(_scan_string_violations(sys_prompt, "llm_mole.system", "system", secrets))

    decisions = getattr(mole, "decisions", None)
    if isinstance(decisions, list) and decisions:
        for idx, rec in enumerate(decisions):
            v_list, count = _audit_single_record(rec, idx, secrets)
            violations.extend(v_list)
            views_checked += count
    else:
        log_rows = getattr(mole, "log", None)
        if isinstance(log_rows, list) and log_rows:
            for idx, rec in enumerate(log_rows):
                v_list, count = _audit_single_record(rec, idx, secrets)
                violations.extend(v_list)
                views_checked += count

    client = getattr(mole, "client", None)
    seen_clients: set[int] = set()
    while client is not None and id(client) not in seen_clients:
        seen_clients.add(id(client))
        calls = getattr(client, "calls", None)
        if isinstance(calls, list):
            for c_idx, call in enumerate(calls):
                if not isinstance(call, Mapping):
                    continue
                for m_idx, msg in enumerate(call.get("messages") or ()):
                    if not isinstance(msg, Mapping):
                        continue
                    role = str(msg.get("role") or "")
                    content = msg.get("content")
                    m_path = f"llm_mole.client.calls[{c_idx}].messages[{m_idx}]"
                    if role == "user" and isinstance(content, str) and content.lstrip().startswith("{"):
                        try:
                            parsed_view = json.loads(content)
                        except json.JSONDecodeError:
                            violations.extend(_scan_string_violations(content, m_path, "content", secrets))
                        else:
                            views_checked += 1
                            violations.extend(
                                audit_view_isolation(parsed_view, path=m_path, known_secrets=secrets)
                            )
                    elif isinstance(content, str):
                        violations.extend(_scan_string_violations(content, m_path, "content", secrets))
        client = getattr(client, "inner", None)
    return violations, views_checked


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        cand = path / "mole_decisions.jsonl"
        if not cand.exists():
            raise FileNotFoundError(f"no mole_decisions.jsonl in {path}")
        path = cand
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def audit_isolation(
    target: Any,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> IsolationReport:
    secrets = _normalize_secrets(known_secrets)
    if isinstance(target, (str, Path)):
        p = Path(target)
        rows = _load_jsonl_records(p)
        if rows and ("strategy_json" in rows[0] or "rules" in rows[0] or "default" in rows[0]):
            all_viols: list[IsolationViolation] = []
            for row in rows:
                rep = audit_strategy_dsl_isolation(row, known_secrets=secrets)
                all_viols.extend(rep.violations)
            return _make_isolation_report(all_viols, views_checked=0)
        return audit_isolation(rows, known_secrets=secrets)

    if isinstance(target, MoleStrategy):
        return audit_strategy_dsl_isolation(target, known_secrets=secrets)

    if isinstance(target, LLMMole) or (hasattr(target, "decide") and hasattr(target, "log")):
        viols, count = _audit_llm_mole_internals(target, secrets)
        return _make_isolation_report(viols, views_checked=count)

    if isinstance(target, MoleView):
        viols = audit_view_isolation(target, path="mole_view", known_secrets=secrets)
        return _make_isolation_report(viols, views_checked=1)

    if isinstance(target, Mapping):
        if any(k in target for k in ("strategy_json", "strategy", "rules", "default")) and not _is_log_envelope(target):
            if "docs" not in target and "held_docs" not in target:
                return audit_strategy_dsl_isolation(target, known_secrets=secrets)
        viols, count = _audit_single_record(target, 0, secrets)
        return _make_isolation_report(viols, views_checked=count)

    if isinstance(target, Iterable) and not isinstance(target, (bytes, bytearray)):
        violations: list[IsolationViolation] = []
        views_checked = 0
        for idx, item in enumerate(target):
            v_list, count = _audit_single_record(item, idx, secrets)
            violations.extend(v_list)
            views_checked += count
        return _make_isolation_report(violations, views_checked=views_checked)

    viols = audit_view_isolation(target, path="mole_view", known_secrets=secrets)
    return _make_isolation_report(viols, views_checked=1)


def _clean_choice(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in {"none", "null"}:
        return None
    return s


def _extract_view_and_move(record: Any) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if isinstance(record, tuple) and len(record) == 2:
        view, move = record
        view_map = _extract_mapping(view)
        move_map = _extract_mapping(move) or {}
        return view_map, _clean_choice(move_map.get("leak")), _clean_choice(move_map.get("frame"))

    mapping = _extract_mapping(record)
    if mapping is None:
        return None, None, None

    view_obj = None
    for vk in ("mole_view", "view", "prompt_view"):
        if mapping.get(vk) is not None:
            view_obj = mapping[vk]
            break
    if view_obj is None and ("docs" in mapping or "held_docs" in mapping or "leakable" in mapping):
        view_map = mapping
    else:
        view_map = _extract_mapping(view_obj) if view_obj is not None else None

    move_obj = mapping.get("move")
    move_map = _extract_mapping(move_obj) if move_obj is not None else None
    leak_raw = mapping.get("leak") if "leak" in mapping else (move_map.get("leak") if move_map else None)
    frame_raw = mapping.get("frame") if "frame" in mapping else (move_map.get("frame") if move_map else None)
    return view_map, _clean_choice(leak_raw), _clean_choice(frame_raw)


def _extract_docs(view_map: Mapping[str, Any]) -> list[tuple[str, int | None]]:
    raw_docs = view_map.get("docs")
    if raw_docs is None:
        raw_docs = view_map.get("held_docs")
    out: list[tuple[str, int | None]] = []
    if isinstance(raw_docs, (list, tuple)):
        for doc in raw_docs:
            dm = _extract_mapping(doc)
            if dm is None:
                continue
            doc_id = str(dm.get("doc_id") or "").strip()
            rc_raw = dm.get("recipient_count")
            rc = int(rc_raw) if isinstance(rc_raw, (int, float)) and not isinstance(rc_raw, bool) else None
            if doc_id:
                out.append((doc_id, rc))
    if not out:
        leakable = view_map.get("leakable")
        if isinstance(leakable, (list, tuple)):
            for x in leakable:
                if x:
                    out.append((str(x), None))
    return out


def compute_deception_metrics(
    records: Any,
    *,
    low_recipient_threshold: int = DEFAULT_LOW_RECIPIENT_THRESHOLD,
) -> DeceptionMetrics:
    if isinstance(records, (str, Path)):
        items: Iterable[Any] = _load_jsonl_records(Path(records))
    elif isinstance(records, LLMMole) or (hasattr(records, "decide") and hasattr(records, "log")):
        decs = getattr(records, "decisions", None)
        items = decs if isinstance(decs, list) and decs else (getattr(records, "log", None) or ())
    else:
        items = records

    n_decisions = 0
    n_leak_opportunities = 0
    n_silent_decisions = 0
    n_leaks = 0
    n_frames = 0
    n_decoy_frames = 0
    n_peer_frames = 0
    n_low_recipient_opportunities = 0
    n_low_recipient_evaded = 0

    for rec in items:
        view_map, leak, frame = _extract_view_and_move(rec)
        n_decisions += 1
        if leak is not None:
            n_leaks += 1

        docs: list[tuple[str, int | None]] = []
        is_leak_opp = False
        decoy: str | None = None
        peers_set: set[str] | None = None

        if view_map is not None:
            docs = _extract_docs(view_map)
            can_leak = view_map.get("can_leak")
            is_leak_opp = bool(docs) and (can_leak is not False)
            raw_decoy = view_map.get("decoy")
            decoy = str(raw_decoy) if raw_decoy else None
            raw_peers = view_map.get("peers")
            if isinstance(raw_peers, (list, tuple)) and raw_peers:
                peers_set = {str(p) for p in raw_peers}
        else:
            is_leak_opp = True

        if is_leak_opp:
            n_leak_opportunities += 1
            if leak is None:
                n_silent_decisions += 1

        if frame is not None and (peers_set is None or frame in peers_set):
            n_frames += 1
            if decoy is not None and frame == decoy:
                n_decoy_frames += 1
            else:
                n_peer_frames += 1

        if view_map is not None and is_leak_opp:
            low_doc_ids = {
                doc_id
                for doc_id, rc in docs
                if rc is not None and rc <= low_recipient_threshold
            }
            has_low = bool(low_doc_ids)
            if not has_low and all(rc is None for _, rc in docs):
                recent_low = view_map.get("recent_low_recipient_docs")
                has_low = isinstance(recent_low, (int, float)) and recent_low > 0
            if has_low:
                n_low_recipient_opportunities += 1
                if leak is None or (low_doc_ids and leak not in low_doc_ids):
                    n_low_recipient_evaded += 1

    silence_rate = n_silent_decisions / n_leak_opportunities if n_leak_opportunities else 0.0
    framing_rate = n_frames / n_decisions if n_decisions else 0.0
    decoy_rate = n_decoy_frames / n_decisions if n_decisions else 0.0
    peer_rate = n_peer_frames / n_decisions if n_decisions else 0.0
    evasion_rate = (
        n_low_recipient_evaded / n_low_recipient_opportunities
        if n_low_recipient_opportunities
        else 0.0
    )
    return DeceptionMetrics(
        n_decisions=n_decisions,
        n_leak_opportunities=n_leak_opportunities,
        n_silent_decisions=n_silent_decisions,
        n_leaks=n_leaks,
        n_frames=n_frames,
        n_decoy_frames=n_decoy_frames,
        n_peer_frames=n_peer_frames,
        n_low_recipient_opportunities=n_low_recipient_opportunities,
        n_low_recipient_evaded=n_low_recipient_evaded,
        low_recipient_threshold=low_recipient_threshold,
        strategic_silence_rate=silence_rate,
        framing_rate=framing_rate,
        decoy_framing_rate=decoy_rate,
        peer_framing_rate=peer_rate,
        low_recipient_canary_evasion_rate=evasion_rate,
    )


class _TwoArgMoleRecorder:
    def __init__(self, inner: Any):
        self.inner = inner
        self.records: list[tuple[Any, dict[str, Any]]] = []

    def decide(self, view: Any, rng: Any) -> dict[str, Any]:
        move = self.inner.decide(view, rng)
        self.records.append((view, dict(move)))
        return move


class _OneArgMoleRecorder:
    def __init__(self, inner: Any):
        self.inner = inner
        self.records: list[tuple[Any, dict[str, Any]]] = []

    def decide(self, view: Any) -> dict[str, Any]:
        move = self.inner.decide(view)
        self.records.append((view, dict(move)))
        return move


def _make_recorder(mole_instance: Any) -> _TwoArgMoleRecorder | _OneArgMoleRecorder:
    if isinstance(mole_instance, MoleStrategy):
        return _TwoArgMoleRecorder(mole_instance)
    if isinstance(mole_instance, LLMMole):
        return _OneArgMoleRecorder(mole_instance)
    import inspect

    sig = inspect.signature(mole_instance.decide)
    pos_params = [
        p
        for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
    if has_varargs or len(pos_params) >= 2:
        return _TwoArgMoleRecorder(mole_instance)
    return _OneArgMoleRecorder(mole_instance)


def _strategy_seed_worker(args: tuple[str, int, dict[str, Any], tuple[str, ...]]) -> dict[str, Any]:
    tier, seed, strategy_json, secrets = args
    strat = MoleStrategy.from_json(strategy_json)
    rec = _TwoArgMoleRecorder(strat)
    env = Env(tier, seed, mole_strategy=rec)
    ep = run_episode(env, SolverPolicy(tier))
    viols: list[IsolationViolation] = []
    compact_records: list[dict[str, Any]] = []
    for step_idx, (view, move) in enumerate(rec.records):
        viols.extend(audit_view_isolation(view, path=f"seed[{seed}].step[{step_idx}]", known_secrets=secrets))
        vm = _extract_mapping(view) or {}
        docs_out = []
        for d in vm.get("docs") or ():
            dm = _extract_mapping(d) or {}
            docs_out.append({
                "doc_id": dm.get("doc_id"),
                "title": dm.get("title"),
                "recipient_count": dm.get("recipient_count"),
                "age_days": dm.get("age_days"),
            })
        compact_records.append({
            "mole_view": {
                "day": vm.get("day"),
                "docs": docs_out,
                "days_since_last_leak": vm.get("days_since_last_leak"),
                "i_am_restricted": vm.get("i_am_restricted"),
                "n_restricted_colleagues": vm.get("n_restricted_colleagues"),
                "recent_low_recipient_docs": vm.get("recent_low_recipient_docs"),
                "peers": list(vm.get("peers") or ()),
                "restricted_peers": list(vm.get("restricted_peers") or ()),
                "decoy": vm.get("decoy"),
                "can_leak": vm.get("can_leak"),
            },
            "leak": move.get("leak"),
            "frame": move.get("frame"),
        })
    return {
        "seed_ep": SeedSolvability(
            seed=seed,
            correct=bool(ep.correct),
            score=float(ep.score),
            accused=ep.accused,
            final_day=int(ep.final_day),
            end_reason=str(ep.end_reason),
        ),
        "views_checked": len(rec.records),
        "violations": viols,
        "records": compact_records,
    }


def _build_solvability_report(
    episodes: Sequence[SeedSolvability],
    *,
    tier: str,
    seeds: Sequence[int],
    min_accuracy: float,
) -> SolvabilityReport:
    if not episodes:
        return SolvabilityReport(
            passed=False,
            tier=tier,
            seeds=tuple(seeds),
            min_accuracy=min_accuracy,
            catch_accuracy=0.0,
            mean_score=0.0,
            mean_final_day=0.0,
            episodes=(),
        )
    acc = sum(1 for e in episodes if e.correct) / len(episodes)
    mean_sc = sum(e.score for e in episodes) / len(episodes)
    mean_day = sum(e.final_day for e in episodes) / len(episodes)
    return SolvabilityReport(
        passed=acc >= min_accuracy,
        tier=tier,
        seeds=tuple(seeds),
        min_accuracy=min_accuracy,
        catch_accuracy=acc,
        mean_score=mean_sc,
        mean_final_day=mean_day,
        episodes=tuple(episodes),
    )


def _instantiate_from_factory(factory: Any, seed: int) -> Any:
    try:
        return factory(seed)
    except TypeError:
        return factory()


def _run_live_evaluation(
    mole_or_factory: Any,
    *,
    tier: str,
    seeds: Sequence[int],
    min_accuracy: float,
    low_recipient_threshold: int,
    known_secrets: Sequence[str | bytes],
    workers: int,
) -> tuple[IsolationReport, DeceptionMetrics, SolvabilityReport]:
    secrets = _normalize_secrets(known_secrets)
    seed_list = [int(s) for s in seeds]

    if isinstance(mole_or_factory, MoleStrategy):
        dsl_iso = audit_strategy_dsl_isolation(mole_or_factory, known_secrets=secrets)
        strategy_json = mole_or_factory.to_json()
        tasks = [(tier, s, strategy_json, secrets) for s in seed_list]
        worker_outputs: list[dict[str, Any]] | None = None
        if workers > 1 and len(tasks) > 1:
            try:
                with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
                    worker_outputs = list(pool.map(_strategy_seed_worker, tasks))
            except (OSError, PermissionError):
                worker_outputs = None
        if worker_outputs is None:
            worker_outputs = [_strategy_seed_worker(t) for t in tasks]

        all_viols = list(dsl_iso.violations)
        views_checked = 0
        all_records: list[dict[str, Any]] = []
        seed_eps: list[SeedSolvability] = []
        for item in worker_outputs:
            seed_eps.append(item["seed_ep"])
            views_checked += int(item["views_checked"])
            all_viols.extend(item["violations"])
            all_records.extend(item["records"])

        iso_report = _make_isolation_report(all_viols, views_checked=views_checked)
        dec_metrics = compute_deception_metrics(all_records, low_recipient_threshold=low_recipient_threshold)
        sol_report = _build_solvability_report(seed_eps, tier=tier, seeds=seed_list, min_accuracy=min_accuracy)
        return iso_report, dec_metrics, sol_report

    all_viols = []
    views_checked = 0
    captured_pairs: list[tuple[Any, dict[str, Any]]] = []
    seed_eps = []
    inspected_instances: set[int] = set()

    for s in seed_list:
        mole_inst = (
            _instantiate_from_factory(mole_or_factory, s)
            if callable(mole_or_factory) and not hasattr(mole_or_factory, "decide")
            else mole_or_factory
        )
        recorder = _make_recorder(mole_inst)
        env = Env(tier, s, mole_strategy=recorder)
        ep = run_episode(env, SolverPolicy(tier))
        seed_eps.append(
            SeedSolvability(
                seed=s,
                correct=bool(ep.correct),
                score=float(ep.score),
                accused=ep.accused,
                final_day=int(ep.final_day),
                end_reason=str(ep.end_reason),
            )
        )
        for step_idx, (view, move) in enumerate(recorder.records):
            views_checked += 1
            all_viols.extend(
                audit_view_isolation(view, path=f"seed[{s}].step[{step_idx}]", known_secrets=secrets)
            )
            captured_pairs.append((view, move))
        if id(mole_inst) not in inspected_instances and (
            isinstance(mole_inst, LLMMole) or hasattr(mole_inst, "log")
        ):
            inspected_instances.add(id(mole_inst))
            m_viols, _ = _audit_llm_mole_internals(mole_inst, secrets)
            all_viols.extend(m_viols)

    iso_report = _make_isolation_report(all_viols, views_checked=views_checked)
    dec_metrics = compute_deception_metrics(captured_pairs, low_recipient_threshold=low_recipient_threshold)
    sol_report = _build_solvability_report(seed_eps, tier=tier, seeds=seed_list, min_accuracy=min_accuracy)
    return iso_report, dec_metrics, sol_report


def verify_solvability(
    mole: Any = DEFAULT_STRATEGY,
    *,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = CONFIRMATION_SEEDS,
    min_accuracy: float = MIN_SOLVER_ACCURACY,
    workers: int = 1,
) -> SolvabilityReport:
    target = mole
    if isinstance(target, Mapping):
        raw, _ = _unwrap_strategy_dict(target)
        target = MoleStrategy.from_json(raw)
    thresh = tier_params(tier).low_recipient_threshold
    _, _, sol = _run_live_evaluation(
        target,
        tier=tier,
        seeds=list(seeds),
        min_accuracy=min_accuracy,
        low_recipient_threshold=thresh,
        known_secrets=(),
        workers=workers,
    )
    return sol


def audit_strategy(
    strategy: MoleStrategy | Mapping[str, Any],
    *,
    name: str | None = None,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = CONFIRMATION_SEEDS,
    min_accuracy: float = MIN_SOLVER_ACCURACY,
    low_recipient_threshold: int | None = None,
    known_secrets: Sequence[str | bytes] = (),
    workers: int = 1,
) -> MoleAuditReport:
    thresh = (
        tier_params(tier).low_recipient_threshold
        if low_recipient_threshold is None
        else low_recipient_threshold
    )
    dsl_iso = audit_strategy_dsl_isolation(strategy, known_secrets=known_secrets)
    if isinstance(strategy, MoleStrategy):
        parsed = strategy
        resolved_name = name or strategy.name
    else:
        raw, outer = _unwrap_strategy_dict(strategy)
        rank_hint = f"rank{outer['rank']}" if outer and "rank" in outer else "custom"
        raw_name = raw.get("name") if isinstance(raw, Mapping) else None
        resolved_name = name or (str(raw_name) if raw_name and raw_name != "custom" else rank_hint)
        if not dsl_iso.passed:
            empty_dec = compute_deception_metrics((), low_recipient_threshold=thresh)
            return MoleAuditReport(
                name=resolved_name,
                kind="mole_strategy",
                passed=False,
                isolation=dsl_iso,
                deception=empty_dec,
                solvability=None,
            )
        parsed = MoleStrategy.from_json(dict(raw))

    if not dsl_iso.passed:
        empty_dec = compute_deception_metrics((), low_recipient_threshold=thresh)
        return MoleAuditReport(
            name=resolved_name,
            kind="mole_strategy",
            passed=False,
            isolation=dsl_iso,
            deception=empty_dec,
            solvability=None,
        )

    iso_report, dec_metrics, sol_report = _run_live_evaluation(
        parsed,
        tier=tier,
        seeds=list(seeds),
        min_accuracy=min_accuracy,
        low_recipient_threshold=thresh,
        known_secrets=known_secrets,
        workers=workers,
    )
    return MoleAuditReport(
        name=resolved_name,
        kind="mole_strategy",
        passed=iso_report.passed and sol_report.passed,
        isolation=iso_report,
        deception=dec_metrics,
        solvability=sol_report,
    )


def audit_llm_mole(
    mole_or_factory: Any,
    *,
    name: str | None = None,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = CONFIRMATION_SEEDS,
    min_accuracy: float = MIN_SOLVER_ACCURACY,
    run_solvability: bool = True,
    low_recipient_threshold: int | None = None,
    known_secrets: Sequence[str | bytes] = (),
) -> MoleAuditReport:
    thresh = (
        tier_params(tier).low_recipient_threshold
        if low_recipient_threshold is None
        else low_recipient_threshold
    )
    resolved_name = name or str(getattr(mole_or_factory, "name", "llm-mole"))
    if not run_solvability:
        iso_report = audit_isolation(mole_or_factory, known_secrets=known_secrets)
        dec_metrics = compute_deception_metrics(mole_or_factory, low_recipient_threshold=thresh)
        return MoleAuditReport(
            name=resolved_name,
            kind="llm_mole",
            passed=iso_report.passed,
            isolation=iso_report,
            deception=dec_metrics,
            solvability=None,
        )
    iso_report, dec_metrics, sol_report = _run_live_evaluation(
        mole_or_factory,
        tier=tier,
        seeds=list(seeds),
        min_accuracy=min_accuracy,
        low_recipient_threshold=thresh,
        known_secrets=known_secrets,
        workers=1,
    )
    return MoleAuditReport(
        name=resolved_name,
        kind="llm_mole",
        passed=iso_report.passed and sol_report.passed,
        isolation=iso_report,
        deception=dec_metrics,
        solvability=sol_report,
    )


def audit_decision_log(
    log_or_path: Any,
    *,
    name: str | None = None,
    low_recipient_threshold: int = DEFAULT_LOW_RECIPIENT_THRESHOLD,
    known_secrets: Sequence[str | bytes] = (),
    solvability: SolvabilityReport | None = None,
) -> MoleAuditReport:
    if isinstance(log_or_path, (str, Path)):
        p = Path(log_or_path)
        records = _load_jsonl_records(p)
        resolved_name = name or p.stem
    else:
        records = list(log_or_path)
        resolved_name = name or "decision_log"
    iso_report = audit_isolation(records, known_secrets=known_secrets)
    dec_metrics = compute_deception_metrics(records, low_recipient_threshold=low_recipient_threshold)
    passed = iso_report.passed and (solvability.passed if solvability is not None else True)
    return MoleAuditReport(
        name=resolved_name,
        kind="decision_log",
        passed=passed,
        isolation=iso_report,
        deception=dec_metrics,
        solvability=solvability,
    )


def audit_mole(
    target: Any,
    *,
    name: str | None = None,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = CONFIRMATION_SEEDS,
    min_accuracy: float = MIN_SOLVER_ACCURACY,
    low_recipient_threshold: int | None = None,
    known_secrets: Sequence[str | bytes] = (),
    workers: int = 1,
) -> MoleAuditReport:
    if isinstance(target, MoleStrategy):
        return audit_strategy(
            target,
            name=name,
            tier=tier,
            seeds=seeds,
            min_accuracy=min_accuracy,
            low_recipient_threshold=low_recipient_threshold,
            known_secrets=known_secrets,
            workers=workers,
        )
    if isinstance(target, (str, Path)):
        p = Path(target)
        rows = _load_jsonl_records(p)
        if rows and any(k in rows[0] for k in ("strategy_json", "strategy", "rules", "default")):
            return audit_strategy(
                rows[0],
                name=name or f"{p.stem}:rank{rows[0].get('rank', 1)}",
                tier=tier,
                seeds=seeds,
                min_accuracy=min_accuracy,
                low_recipient_threshold=low_recipient_threshold,
                known_secrets=known_secrets,
                workers=workers,
            )
        thresh = (
            DEFAULT_LOW_RECIPIENT_THRESHOLD
            if low_recipient_threshold is None
            else low_recipient_threshold
        )
        return audit_decision_log(
            rows,
            name=name or p.name,
            low_recipient_threshold=thresh,
            known_secrets=known_secrets,
        )
    if isinstance(target, Mapping):
        if any(k in target for k in ("strategy_json", "strategy", "rules", "default")) and not _is_log_envelope(target):
            if "docs" not in target and "held_docs" not in target:
                return audit_strategy(
                    target,
                    name=name,
                    tier=tier,
                    seeds=seeds,
                    min_accuracy=min_accuracy,
                    low_recipient_threshold=low_recipient_threshold,
                    known_secrets=known_secrets,
                    workers=workers,
                )
        thresh = (
            DEFAULT_LOW_RECIPIENT_THRESHOLD
            if low_recipient_threshold is None
            else low_recipient_threshold
        )
        return audit_decision_log(
            [target],
            name=name or "decision_record",
            low_recipient_threshold=thresh,
            known_secrets=known_secrets,
        )
    if isinstance(target, LLMMole) or callable(target) or hasattr(target, "decide"):
        return audit_llm_mole(
            target,
            name=name,
            tier=tier,
            seeds=seeds,
            min_accuracy=min_accuracy,
            low_recipient_threshold=low_recipient_threshold,
            known_secrets=known_secrets,
        )
    thresh = (
        DEFAULT_LOW_RECIPIENT_THRESHOLD
        if low_recipient_threshold is None
        else low_recipient_threshold
    )
    return audit_decision_log(
        target,
        name=name,
        low_recipient_threshold=thresh,
        known_secrets=known_secrets,
    )


def discover_hof_files(path_or_dir: str | Path = DEFAULT_FORGE_DIR) -> list[Path]:
    p = Path(path_or_dir)
    if not p.exists():
        raise FileNotFoundError(f"hall-of-fame path does not exist: {p}")
    if p.is_file():
        return [p]
    files = sorted(p.glob("**/hall_of_fame*.jsonl"))
    if not files:
        raise FileNotFoundError(f"no hall_of_fame*.jsonl files found under {p}")
    return files


def audit_forge_hof(
    path_or_dir: str | Path = DEFAULT_FORGE_DIR,
    *,
    tier: str = DEFAULT_TIER,
    seeds: Iterable[int] = CONFIRMATION_SEEDS,
    min_accuracy: float = MIN_SOLVER_ACCURACY,
    low_recipient_threshold: int | None = None,
    known_secrets: Sequence[str | bytes] = (),
    workers: int = 4,
) -> list[MoleAuditReport]:
    files = discover_hof_files(path_or_dir)
    seed_tuple = tuple(int(s) for s in seeds)
    reports: list[MoleAuditReport] = []
    for fpath in files:
        rows = _load_jsonl_records(fpath)
        for idx, row in enumerate(rows):
            rank = row.get("rank", idx + 1)
            label = f"{fpath.stem}:rank{rank}"
            reports.append(
                audit_strategy(
                    row,
                    name=label,
                    tier=tier,
                    seeds=seed_tuple,
                    min_accuracy=min_accuracy,
                    low_recipient_threshold=low_recipient_threshold,
                    known_secrets=known_secrets,
                    workers=workers,
                )
            )
    return reports


def format_table(reports: Sequence[MoleAuditReport]) -> str:
    header = (
        f"{'name':<28} {'kind':<14} {'iso':<5} {'silence':>7} "
        f"{'frame':>7} {'decoy':>7} {'peer':>7} {'evade':>7} {'acc':>7} {'pass':<5}"
    )
    lines = [header, "-" * len(header)]
    for rep in reports:
        iso_str = "ok" if rep.isolation.passed else "FAIL"
        acc_str = f"{rep.solvability.catch_accuracy:7.3f}" if rep.solvability is not None else "    n/a"
        pass_str = "PASS" if rep.passed else "FAIL"
        lines.append(
            f"{rep.name[:28]:<28} {rep.kind:<14} {iso_str:<5} "
            f"{rep.deception.strategic_silence_rate:7.3f} "
            f"{rep.deception.framing_rate:7.3f} "
            f"{rep.deception.decoy_framing_rate:7.3f} "
            f"{rep.deception.peer_framing_rate:7.3f} "
            f"{rep.deception.low_recipient_canary_evasion_rate:7.3f} "
            f"{acc_str} {pass_str:<5}"
        )
    return "\n".join(lines)


def _parse_seed_spec(spec: str) -> list[int]:
    spec = spec.strip()
    if spec == "confirm20":
        return list(CONFIRMATION_SEEDS)
    return parse_seeds(spec)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="canary.gemini.mole_audit")
    ap.add_argument("--hof", default=None, help="Hall-of-fame JSONL file or directory (default: data/forge)")
    ap.add_argument("--strategy", default=None, help="Strategy JSON string or JSON file path")
    ap.add_argument("--decision-log", default=None, help="Decision log JSONL file or adaptive mole run directory")
    ap.add_argument("--tier", default=DEFAULT_TIER, help="Tier for solvability audit (default: hard)")
    ap.add_argument("--seeds", default="5000-5019", help="Confirmation seed spec (default: 5000-5019)")
    ap.add_argument("--min-acc", type=float, default=MIN_SOLVER_ACCURACY, help="Minimum SolverPolicy catch accuracy")
    ap.add_argument("--low-recipient-threshold", type=int, default=None, help="Low-recipient threshold override")
    ap.add_argument("--workers", type=int, default=4, help="Parallel worker processes for strategy seeds")
    ap.add_argument("--out", default=None, help="Optional JSON output file path")
    ap.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    ap.add_argument("--strict", action="store_true", help="Exit with code 1 if any audited target fails")
    args = ap.parse_args(list(argv) if argv is not None else None)

    seeds = _parse_seed_spec(args.seeds)
    reports: list[MoleAuditReport] = []

    if args.strategy is not None:
        s_arg = args.strategy.strip()
        s_obj = json.loads(s_arg) if s_arg.startswith("{") else json.loads(Path(s_arg).read_text())
        reports.append(
            audit_strategy(
                s_obj,
                tier=args.tier,
                seeds=seeds,
                min_accuracy=args.min_acc,
                low_recipient_threshold=args.low_recipient_threshold,
                workers=args.workers,
            )
        )

    if args.decision_log is not None:
        thresh = (
            DEFAULT_LOW_RECIPIENT_THRESHOLD
            if args.low_recipient_threshold is None
            else args.low_recipient_threshold
        )
        reports.append(
            audit_decision_log(
                args.decision_log,
                low_recipient_threshold=thresh,
            )
        )

    if args.hof is not None or (args.strategy is None and args.decision_log is None):
        hof_target = args.hof if args.hof is not None else DEFAULT_FORGE_DIR
        reports.extend(
            audit_forge_hof(
                hof_target,
                tier=args.tier,
                seeds=seeds,
                min_accuracy=args.min_acc,
                low_recipient_threshold=args.low_recipient_threshold,
                workers=args.workers,
            )
        )

    payload = {
        "tier": args.tier,
        "seeds": seeds,
        "min_accuracy": args.min_acc,
        "all_passed": all(r.passed for r in reports),
        "reports": [r.to_dict() for r in reports],
    }

    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_table(reports))

    if args.strict and not payload["all_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
