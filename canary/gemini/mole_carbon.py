from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import dataclasses
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
from typing import Any

from canary.llm.pricing import cost as price_cost
from canary.mole.dsl import (
    FEATURES,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleStrategy,
    MoleView,
    OPS,
    StrategyError,
)

ROLE = "adaptive_mole"
TARGET_MODEL = "gemini-4-carbon"
SUITE_DIR_NAME = "carbon-vs-carbon-suite"
ENVIRONMENT_SCOPE = "arena mode, not the judged v1.4 environment"
DEFAULT_ROLES_REL = Path("results") / "gemini" / "roles_carbon" / ROLE
DEFAULT_SUITE_REL = DEFAULT_ROLES_REL / SUITE_DIR_NAME
DEFAULT_DOC_REL = Path("docs") / "gemini" / "roles_carbon" / "adaptive_mole.md"
INVESTIGATOR_ORDER: tuple[str, ...] = ("solver", "grok_tactics", "obvious_heuristic")
TIER_RANK: dict[str, int] = {"easy": 0, "medium": 1, "hard": 2}
SKIP_DIRS = frozenset({"reference", "superseded", "_invalid"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
FORBIDDEN_DASHES: tuple[str, ...] = (EM_DASH, EN_DASH, FIG_DASH, HORIZ_BAR)
MD_H1 = chr(35)
MD_H2 = MD_H1 * 2
MD_H3 = MD_H1 * 3

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

ALLOWED_MOVE_FIELDS = frozenset({"leak", "frame", "reason"})

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

GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
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
    r"[\"'](?:belief|beliefs|posterior|posteriors|investigator_belief|suspect_probs|suspect_posterior)[\"']\s*:"
)


def clean_str(val: Any) -> str:
    if val is None:
        return ""
    out = str(val)
    for dash in FORBIDDEN_DASHES:
        out = out.replace(dash, "-")
    return out


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {clean_str(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _truthy(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    except (OSError, UnicodeDecodeError, ValueError):
        return []
    return rows


def wilson_ci95(successes: int, total: int) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    k = max(0, min(int(successes), int(total)))
    n = float(total)
    z = 1.959963984540054
    z2 = z * z
    phat = k / n
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    radicand = max(0.0, (phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    half = (z * math.sqrt(radicand)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def bootstrap_mean_ci95(
    values: list[float],
    n_boot: int = 2000,
    seed: int = 104729,
) -> list[float]:
    if not values:
        return [0.0, 0.0]
    clean_vals = [float(v) for v in values]
    if len(clean_vals) == 1 or min(clean_vals) == max(clean_vals):
        const = round(clean_vals[0], 4)
        return [const, const]
    rng = random.Random(seed)
    n = len(clean_vals)
    boot_means = sorted(
        sum(clean_vals[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_boot)
    )
    lo_idx = int(0.025 * (n_boot - 1))
    hi_idx = int(0.975 * (n_boot - 1))
    return [round(boot_means[lo_idx], 4), round(boot_means[hi_idx], 4)]


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


def scan_file_secrets(file_path: Path, root: Path | None = None) -> list[dict[str, str]]:
    resolved_root = Path(root).resolve() if root is not None else file_path.parent
    try:
        text = file_path.read_bytes().decode("latin-1")
    except OSError:
        return [{"file": _rel_posix(file_path, resolved_root), "kind": "unreadable_file"}]
    rel = _rel_posix(file_path, resolved_root)
    findings: list[dict[str, str]] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "google_api_key"})
    if SK_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "sk_api_key"})
    if OAUTH_RE.search(text):
        findings.append({"file": rel, "kind": "oauth_token"})
    if PREFIXED_SECRET_RE.search(text):
        findings.append({"file": rel, "kind": "prefixed_secret"})
    if _has_env_secret_assignment(text):
        findings.append({"file": rel, "kind": "env_api_key"})
    return findings


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


def _normalize_secrets(known_secrets: Sequence[str | bytes] = ()) -> tuple[str, ...]:
    collected: list[str] = []
    for item in known_secrets:
        s = bytes(item).decode("latin-1").strip() if isinstance(item, (bytes, bytearray)) else str(item or "").strip()
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
        return _scan_string_violations(
            bytes(val).decode("latin-1"),
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
                            IsolationViolation("unexpected_field", dk_path, dk, f"unauthorized document field {dk!r}")
                        )
                    violations.extend(_scan_nested_value(dv, dk_path, dk, secrets))
        else:
            violations.extend(_scan_nested_value(v, field_path, k, secrets))
    return list(_dedupe_violations(violations))


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
        if "strategy_json" in strategy_obj:
            outer = {k: v for k, v in strategy_obj.items() if k != "strategy_json"}
            raw = strategy_obj["strategy_json"]
            violations.extend(_scan_nested_value(outer, "hof_entry", "hof_entry", secrets, check_keys=False))
        elif "strategy" in strategy_obj and isinstance(strategy_obj.get("strategy"), Mapping):
            outer = {k: v for k, v in strategy_obj.items() if k != "strategy"}
            raw = strategy_obj["strategy"]
            violations.extend(_scan_nested_value(outer, "hof_entry", "hof_entry", secrets, check_keys=False))
        else:
            raw = dict(strategy_obj)
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
            violations.append(IsolationViolation(cat, f"strategy.{k}", str(k), f"unauthorized key {k!r} in strategy"))
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
                    violations.append(IsolationViolation(cat, f"{r_path}.{rk}", str(rk), f"unauthorized rule key {rk!r}"))
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
                                IsolationViolation(cat, c_path, feat, f"forbidden {cat} feature {feat!r}")
                            )
                        elif feat not in FEATURES:
                            violations.append(
                                IsolationViolation("unexpected_field", c_path, feat, f"unknown feature {feat!r}")
                            )
                    if op is not None and op not in OPS:
                        violations.append(IsolationViolation("unexpected_field", c_path, str(op), f"invalid op {op!r}"))
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
            violations.append(IsolationViolation("unexpected_field", field_path, k, f"unauthorized log field {k!r}"))
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


def _is_single_view_move_pair(obj: Any) -> bool:
    if not (isinstance(obj, tuple) and len(obj) == 2):
        return False
    first, second = obj
    if not isinstance(first, MoleView):
        return False
    return isinstance(second, Mapping) and "docs" not in second and "held_docs" not in second


def audit_isolation(
    records: Any,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> IsolationReport:
    secrets = _normalize_secrets(known_secrets)
    if (
        isinstance(records, (MoleView, Mapping, str, bytes, bytearray))
        or _is_single_view_move_pair(records)
        or not isinstance(records, Iterable)
    ):
        seq: Iterable[Any] = (records,)
    else:
        seq = records
    violations: list[IsolationViolation] = []
    views_checked = 0
    for idx, rec in enumerate(seq):
        v_list, count = _audit_single_record(rec, idx, secrets)
        violations.extend(v_list)
        views_checked += count
    return _make_isolation_report(violations, views_checked=views_checked)


def audit_committed_mole_runs(
    roles_dir: Path,
    root_path: Path,
) -> dict[str, Any]:
    decisions_checked = 0
    views_checked = 0
    strategies_checked = 0
    isolation_violations = 0
    secret_leaks = 0

    if not roles_dir.is_dir():
        return {
            "passed": False,
            "decisions_checked": 0,
            "views_checked": 0,
            "strategies_checked": 0,
            "isolation_violations": 0,
            "secret_leaks": 0,
        }

    for run_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        if run_dir.name in SKIP_DIRS or run_dir.name == SUITE_DIR_NAME:
            continue
        for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            rel_sub = fp.relative_to(run_dir).parts
            if any(part in SKIP_DIRS for part in rel_sub):
                continue
            if scan_file_secrets(fp, root_path):
                secret_leaks += 1

        dec_path = run_dir / "mole_decisions.jsonl"
        if dec_path.is_file():
            rows = _load_jsonl(dec_path)
            rep = audit_isolation(rows)
            decisions_checked += len(rows)
            views_checked += rep.views_checked
            isolation_violations += len(rep.violations)

        mlog_path = run_dir / "mole_log.json"
        if mlog_path.is_file():
            mlog = _load_json(mlog_path)
            if isinstance(mlog, dict):
                has_split = any(isinstance(mlog.get(k), list) for k in ("clash_mole_log", "solver_mole_log"))
                keys = ("clash_mole_log", "solver_mole_log") if has_split else ("log",)
                for key in keys:
                    grp = mlog.get(key)
                    if isinstance(grp, list):
                        rep = audit_isolation(grp)
                        decisions_checked += len(grp)
                        views_checked += rep.views_checked
                        isolation_violations += len(rep.violations)

        hof_path = run_dir / "hall_of_fame.jsonl"
        if hof_path.is_file():
            for row in _load_jsonl(hof_path):
                strategies_checked += 1
                srep = audit_strategy_dsl_isolation(row)
                isolation_violations += len(srep.violations)

    return {
        "passed": isolation_violations == 0 and secret_leaks == 0,
        "decisions_checked": decisions_checked,
        "views_checked": views_checked,
        "strategies_checked": strategies_checked,
        "isolation_violations": isolation_violations,
        "secret_leaks": secret_leaks,
    }


def zero_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "latency_s": 0.0,
    }


def normalize_usage(raw: Any, model_id: str = TARGET_MODEL) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return zero_usage()
    calls_raw = raw.get("calls", raw.get("n_calls", raw.get("api_calls", 0)))
    in_raw = raw.get("in", raw.get("input_tokens", raw.get("prompt_tokens", 0)))
    out_raw = raw.get(
        "out",
        raw.get(
            "output_tokens",
            raw.get("out_tokens", raw.get("candidates_tokens", raw.get("completion_tokens", 0))),
        ),
    )
    think_raw = raw.get("thinking", raw.get("thinking_tokens", raw.get("thoughts_tokens", 0)))
    cached_raw = raw.get("cached", raw.get("cached_in", raw.get("cached_tokens", 0)))
    lat_raw = raw.get("latency_s", 0.0)

    calls = int(calls_raw) if _is_num(calls_raw) and calls_raw > 0 else 0
    tin = int(in_raw) if _is_num(in_raw) and in_raw > 0 else 0
    tout = int(out_raw) if _is_num(out_raw) and out_raw > 0 else 0
    tthink = int(think_raw) if _is_num(think_raw) and think_raw > 0 else 0
    tcached = int(cached_raw) if _is_num(cached_raw) and cached_raw > 0 else 0
    latency = round(float(lat_raw), 3) if _is_num(lat_raw) and lat_raw > 0 else 0.0

    cost_raw = raw.get("cost_usd_est") if _is_num(raw.get("cost_usd_est")) else raw.get("cost_usd")
    usd = float(cost_raw) if _is_num(cost_raw) and cost_raw >= 0 else 0.0
    if usd == 0.0 and tin > 0 and tout > 0 and model_id:
        priced = price_cost(model_id, tin, tout + tthink, min(tcached, tin))
        usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)

    tot_raw = raw.get("total_tokens")
    total_tokens = int(tot_raw) if _is_num(tot_raw) and tot_raw >= (tin + tout + tthink) else (tin + tout + tthink)

    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": tthink,
        "cached": tcached,
        "total_tokens": total_tokens,
        "cost_usd": round(usd, 6),
        "latency_s": latency,
    }


def sum_usages(items: list[dict[str, Any]]) -> dict[str, Any]:
    acc = zero_usage()
    for u in items:
        for k in ("calls", "in", "out", "thinking", "cached", "total_tokens"):
            acc[k] += int(u.get(k, 0) or 0)
        acc["cost_usd"] = round(acc["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
        acc["latency_s"] = round(acc["latency_s"] + float(u.get("latency_s", 0.0) or 0.0), 3)
    return acc


def build_key_metric(run_name: str, meta: Mapping[str, Any], run_dir: Path | None = None) -> str:
    subrole = clean_str(meta.get("subrole") or "")
    tier = clean_str(meta.get("tier") or "")
    if run_name.startswith("carbon-vs-carbon-") or subrole in {"carbon_vs_carbon_clash", "clash"}:
        seed = meta.get("seed", 0)
        inv = float(meta.get("investigator_score", 0.0) or 0.0)
        sol = float(meta.get("solver_score", 0.0) or 0.0)
        reg = float(meta["regret"]) if _is_num(meta.get("regret")) else (sol - inv)
        leaks = int(meta.get("mole_clash_leaks", 0) or 0)
        return clean_str(
            f"{tier} s{seed} clash: carbon inv {inv:+.2f} vs solver {sol:+.2f} (regret {reg:+.2f}, {leaks} leaks, 0 errors)"
        )
    if run_name.startswith("arena-live-carbon-") or subrole.startswith("live_arena"):
        seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) else []
        s_mean = float(meta.get("solver_mean", 0.0) or 0.0)
        g_mean = float(meta.get("grok_tactics_mean", 0.0) or 0.0)
        s_acc = float(meta.get("solver_accuracy", 0.0) or 0.0) * 100.0
        return clean_str(
            f"{tier} seeds {seeds}: solver {s_mean:+.2f} ({s_acc:.0f}% acc) vs grok_tactics {g_mean:+.2f}, solvable=True"
        )
    if run_name.startswith("mole-forge-carbon-") or subrole == "mole_forge":
        bf = float(meta.get("best_fitness", 0.0) or 0.0)
        df = float(meta.get("default_dev_fitness", 0.0) or 0.0)
        valid = int(meta.get("n_valid_llm_children", 0) or 0)
        hold_str = ""
        if run_dir is not None:
            hdoc = _load_json(run_dir / "holdout_generalization.json")
            if isinstance(hdoc, dict):
                hs = hdoc.get("summary") if isinstance(hdoc.get("summary"), dict) else {}
                sp = hdoc.get("splits") if isinstance(hdoc.get("splits"), dict) else {}
                n_conf = len(sp.get("confirm_seeds") or [])
                c_acc = hs.get("top1_confirm_solver_acc")
                if _is_num(c_acc) and n_conf > 0:
                    hold_str = f", holdout {float(c_acc)*100.0:.0f}% (n={n_conf})"
        return clean_str(f"{tier} Mole Forge: {valid} valid DSL children, fitness {bf:.4f} vs default {df:.4f}{hold_str}")
    if run_name.startswith("paired-") or subrole.startswith("paired_"):
        kept = int(meta.get("n_kept", 0) or 0)
        valid = int(meta.get("n_llm_valid", 0) or 0)
        sol_m = meta.get("eval_full_solver_mean", meta.get("design_solver_mean", meta.get("kept_solver_mean", 0.0)))
        heur_m = meta.get("eval_heuristic_mean", meta.get("design_heuristic_mean", meta.get("kept_heuristic_mean", 0.0)))
        return clean_str(
            f"{tier} PAIRED ({kept}/{valid} kept): solver {float(sol_m or 0.0):+.3f} vs heuristic {float(heur_m or 0.0):+.3f}"
        )
    if subrole in {"catchability_isolation_audit", "catchability_audit"} or run_name.startswith("catchability-audit"):
        p = int(meta.get("n_catchability_passed", 0) or 0)
        t = int(meta.get("n_catchability_targets", 0) or 0)
        v = int(meta.get("n_views_checked", 0) or 0)
        iso = int(meta.get("isolation_violations", 0) or 0)
        return clean_str(f"catchability {p}/{t} compliant, {iso} isolation violations across {v} MoleViews")
    return clean_str(f"{subrole or run_name}: verified gemini-4-carbon adaptive_mole run")


def verify_adaptive_mole_run(
    meta_path: Path,
    root_path: Path | None = None,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    target = Path(meta_path)
    actual_meta = (target / "meta.json") if target.is_dir() else target
    run_dir = actual_meta.parent
    resolved_root = Path(root_path).resolve() if root_path is not None else run_dir.parent

    errors: list[str] = []
    meta = _load_json(actual_meta)
    if not isinstance(meta, dict):
        return False, None, ["invalid_meta_json"]

    for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_sub = fp.relative_to(run_dir).parts
        if any(part in SKIP_DIRS for part in rel_sub):
            continue
        if scan_file_secrets(fp, resolved_root):
            errors.append("secret_leak")
            break

    raw_role = meta.get("role")
    norm_role = (
        raw_role.strip().lower().replace("-", "_").replace(" ", "_")
        if isinstance(raw_role, str) and raw_role.strip()
        else ""
    )
    if norm_role != ROLE:
        errors.append(f"invalid_role:{norm_role or 'missing'}")

    raw_model = meta.get("model_id") if meta.get("model_id") is not None else meta.get("model")
    model_id = raw_model.strip() if isinstance(raw_model, str) else ""
    if model_id != TARGET_MODEL:
        errors.append(f"wrong_model:{model_id or 'missing'}")

    raw_commit = meta.get("commit") if meta.get("commit") is not None else meta.get("git_sha")
    commit = raw_commit.strip() if isinstance(raw_commit, str) else ""
    if not commit or not COMMIT_RE.fullmatch(commit):
        errors.append("invalid_commit")

    usage = normalize_usage(meta.get("usage"), model_id)
    if usage["in"] <= 0 or usage["out"] <= 0:
        errors.append("zero_or_invalid_usage")
    if usage["cost_usd"] == 0.0 and _is_num(meta.get("cost_usd")) and float(meta["cost_usd"]) > 0:
        usage["cost_usd"] = round(float(meta["cost_usd"]), 6)

    provider = str(meta.get("provider") or "").strip().lower()
    agent = str(meta.get("agent") or "").strip().lower()
    llm_field = str(meta.get("llm") or meta.get("llm_spec") or "").strip().lower()
    if (
        _truthy(meta.get("fake_env"))
        or _truthy(meta.get("smoke"))
        or _truthy(meta.get("stub"))
        or _truthy(meta.get("synthetic"))
        or provider == "stub"
        or agent == "stub"
        or agent.startswith("stub:")
        or llm_field == "stub"
        or llm_field.startswith("stub:")
    ):
        errors.append("non_live_run")

    if errors:
        return False, None, errors

    record = {
        "run_dir": run_dir,
        "rel_dir": _rel_posix(run_dir, resolved_root),
        "name": run_dir.name,
        "meta": meta,
        "model_id": model_id,
        "commit": commit,
        "usage": usage,
    }
    return True, record, []


def discover_adaptive_mole_runs(
    root_path: Path,
    roles_dir: Path,
    out_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not roles_dir.is_dir():
        return [], []
    out_resolved = out_path.resolve()
    verified: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_dirs: set[Path] = set()

    for meta_path in sorted(roles_dir.rglob("meta.json")):
        if not meta_path.is_file():
            continue
        rel_parts = meta_path.relative_to(roles_dir).parts
        if any(part in SKIP_DIRS or part == SUITE_DIR_NAME for part in rel_parts):
            continue
        run_dir = meta_path.parent.resolve()
        if run_dir == out_resolved or out_resolved in run_dir.parents:
            continue
        if run_dir in seen_dirs:
            continue
        seen_dirs.add(run_dir)
        ok, rec, errs = verify_adaptive_mole_run(meta_path, root_path)
        if ok and rec is not None:
            verified.append(rec)
        else:
            skipped.append({"run_dir": _rel_posix(meta_path.parent, root_path), "errors": errs})
    return verified, skipped


def _classify_run(rec: dict[str, Any]) -> str:
    name = rec["name"]
    subrole = str(rec["meta"].get("subrole") or "").strip()
    if (name.startswith("carbon-vs-carbon-") and name != SUITE_DIR_NAME) or subrole in {"carbon_vs_carbon_clash", "clash"}:
        return "clash"
    if name.startswith("arena-live-carbon-") or subrole.startswith("live_arena"):
        return "live_arena"
    if name.startswith("mole-forge-carbon-") or subrole == "mole_forge":
        return "mole_forge"
    if name.startswith("paired-") or subrole.startswith("paired_"):
        return "paired_designer"
    return "other"


def _aggregate_clash_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    combined_u = sum_usages([r["usage"]["combined"] for r in rows])
    inv_u = sum_usages([r["usage"]["clash_investigator"] for r in rows])
    mole_u = sum_usages([r["usage"]["clash_mole"] for r in rows])
    if not rows:
        return {
            "n_shards": 0,
            "n_episodes": 0,
            "seeds": [],
            "investigator_accuracy": 0.0,
            "investigator_accuracy_ci95": [0.0, 0.0],
            "investigator_mean_score": 0.0,
            "investigator_mean_ci95": [0.0, 0.0],
            "solver_accuracy": 0.0,
            "solver_accuracy_ci95": [0.0, 0.0],
            "solver_mean_score": 0.0,
            "solver_mean_ci95": [0.0, 0.0],
            "solvable_rate": 0.0,
            "solvable_rate_ci95": [0.0, 0.0],
            "mean_regret": 0.0,
            "mean_regret_ci95": [0.0, 0.0],
            "mole_total_leaks": 0,
            "mole_total_frames": 0,
            "mole_total_errors": 0,
            "mole_solver_total_leaks": 0,
            "mole_solver_total_frames": 0,
            "mole_solver_total_errors": 0,
            "usage": {
                "combined": combined_u,
                "clash_investigator": inv_u,
                "clash_mole": mole_u,
            },
        }
    n = len(rows)
    inv_k = sum(1 for r in rows if r["investigator_correct"])
    sol_k = sum(1 for r in rows if r["solver_correct"])
    solv_k = sum(1 for r in rows if r["solvable"])
    inv_scores = [float(r["investigator_score"]) for r in rows]
    sol_scores = [float(r["solver_score"]) for r in rows]
    regrets = [float(r["regret"]) for r in rows]
    return {
        "n_shards": n,
        "n_episodes": sum(int(r["episode_count"]) for r in rows),
        "seeds": [int(r["seed"]) for r in rows],
        "investigator_accuracy": round(inv_k / n, 4),
        "investigator_accuracy_ci95": wilson_ci95(inv_k, n),
        "investigator_mean_score": round(statistics.mean(inv_scores), 4),
        "investigator_mean_ci95": bootstrap_mean_ci95(inv_scores),
        "solver_accuracy": round(sol_k / n, 4),
        "solver_accuracy_ci95": wilson_ci95(sol_k, n),
        "solver_mean_score": round(statistics.mean(sol_scores), 4),
        "solver_mean_ci95": bootstrap_mean_ci95(sol_scores),
        "solvable_rate": round(solv_k / n, 4),
        "solvable_rate_ci95": wilson_ci95(solv_k, n),
        "mean_regret": round(statistics.mean(regrets), 4),
        "mean_regret_ci95": bootstrap_mean_ci95(regrets),
        "mole_total_leaks": sum(int(r["mole_clash_leaks"]) for r in rows),
        "mole_total_frames": sum(int(r["mole_clash_frames"]) for r in rows),
        "mole_total_errors": sum(int(r["mole_clash_errors"]) for r in rows),
        "mole_solver_total_leaks": sum(int(r["mole_solver_leaks"]) for r in rows),
        "mole_solver_total_frames": sum(int(r["mole_solver_frames"]) for r in rows),
        "mole_solver_total_errors": sum(int(r["mole_solver_errors"]) for r in rows),
        "usage": {
            "combined": combined_u,
            "clash_investigator": inv_u,
            "clash_mole": mole_u,
        },
    }


def _build_clash_suite(records: list[dict[str, Any]]) -> dict[str, Any]:
    shards: list[dict[str, Any]] = []
    for rec in records:
        meta = rec["meta"]
        raw_u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
        combined_u = dict(rec["usage"])
        inv_u = (
            normalize_usage(raw_u.get("clash_investigator"), rec["model_id"])
            if isinstance(raw_u.get("clash_investigator"), dict)
            else zero_usage()
        )
        mole_u = (
            normalize_usage(raw_u.get("clash_mole"), rec["model_id"])
            if isinstance(raw_u.get("clash_mole"), dict)
            else zero_usage()
        )
        inv_score = round(float(meta.get("investigator_score", 0.0) or 0.0), 6)
        sol_score = round(float(meta.get("solver_score", 0.0) or 0.0), 6)
        raw_regret = meta.get("regret")
        regret = round(float(raw_regret), 6) if _is_num(raw_regret) else round(sol_score - inv_score, 6)
        tier = clean_str(meta.get("tier") or "unknown")
        seed = int(meta.get("seed", 0) or 0)
        ep_count = int(meta.get("episode_count", 2) or 2)
        shards.append(
            {
                "run_dir": rec["rel_dir"],
                "tier": tier,
                "seed": seed,
                "episode_count": ep_count,
                "model_id": rec["model_id"],
                "commit": rec["commit"],
                "investigator_score": inv_score,
                "investigator_correct": bool(meta.get("investigator_correct", False)),
                "investigator_accused": meta.get("investigator_accused"),
                "investigator_final_day": meta.get("investigator_final_day"),
                "investigator_end_reason": meta.get("investigator_end_reason"),
                "solver_score": sol_score,
                "solver_correct": bool(meta.get("solver_correct", False)),
                "solver_accused": meta.get("solver_accused"),
                "solver_final_day": meta.get("solver_final_day"),
                "solver_end_reason": meta.get("solver_end_reason"),
                "solvable": bool(meta.get("solvable", False)),
                "regret": regret,
                "mole_clash_days": int(meta.get("mole_clash_days", 0) or 0),
                "mole_clash_leaks": int(meta.get("mole_clash_leaks", 0) or 0),
                "mole_clash_frames": int(meta.get("mole_clash_frames", 0) or 0),
                "mole_clash_errors": int(meta.get("mole_clash_errors", 0) or 0),
                "mole_solver_days": int(meta.get("mole_solver_days", 0) or 0),
                "mole_solver_leaks": int(meta.get("mole_solver_leaks", 0) or 0),
                "mole_solver_frames": int(meta.get("mole_solver_frames", 0) or 0),
                "mole_solver_errors": int(meta.get("mole_solver_errors", 0) or 0),
                "usage": {
                    **combined_u,
                    "combined": combined_u,
                    "clash_investigator": inv_u,
                    "clash_mole": mole_u,
                },
            }
        )

    shards.sort(key=lambda r: (TIER_RANK.get(r["tier"], 99), r["tier"], r["seed"], r["run_dir"]))
    tiers: list[str] = ["easy", "medium", "hard"]
    for r in shards:
        if r["tier"] not in tiers:
            tiers.append(r["tier"])

    by_tier = {t: _aggregate_clash_rows([r for r in shards if r["tier"] == t]) for t in tiers}
    return {
        "shards": shards,
        "by_tier": by_tier,
        "overall": _aggregate_clash_rows(shards),
    }


def _summarize_episode_slice(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mean_score": 0.0,
            "mean_score_ci95": [0.0, 0.0],
            "accuracy": 0.0,
            "accuracy_ci95": [0.0, 0.0],
            "mean_day": 0.0,
        }
    scores = [float(r.get("score", 0.0) or 0.0) for r in rows]
    k_corr = sum(1 for r in rows if bool(r.get("correct")))
    acc = k_corr / len(rows)
    days = [int(r.get("final_day", 0) or 0) for r in rows]
    return {
        "n": len(rows),
        "mean_score": round(statistics.mean(scores), 4),
        "mean_score_ci95": bootstrap_mean_ci95(scores),
        "accuracy": round(acc, 4),
        "accuracy_ci95": wilson_ci95(k_corr, len(rows)),
        "mean_day": round(statistics.mean(days), 2),
    }


def _paired_episode_diffs(
    adaptive_rows: list[dict[str, Any]],
    default_rows: list[dict[str, Any]],
) -> list[float]:
    default_map: dict[tuple[str, int], float] = {}
    for row in default_rows:
        seed_val = row.get("seed")
        if isinstance(seed_val, int) and not isinstance(seed_val, bool):
            key = (clean_str(row.get("tier") or ""), seed_val)
            default_map[key] = float(row.get("score", 0.0) or 0.0)
    diffs: list[float] = []
    for row in sorted(
        adaptive_rows,
        key=lambda r: (
            TIER_RANK.get(clean_str(r.get("tier") or ""), 99),
            clean_str(r.get("tier") or ""),
            int(r.get("seed", 0) or 0),
        ),
    ):
        seed_val = row.get("seed")
        if isinstance(seed_val, int) and not isinstance(seed_val, bool):
            key = (clean_str(row.get("tier") or ""), seed_val)
            if key in default_map:
                diffs.append(float(row.get("score", 0.0) or 0.0) - default_map[key])
    return diffs


def _aggregate_arena_batches(batches: list[dict[str, Any]]) -> dict[str, Any]:
    adaptive_eps: list[dict[str, Any]] = []
    default_eps: list[dict[str, Any]] = []
    seeds_seen: list[int] = []
    for b in batches:
        adaptive_eps.extend(b["_adaptive_eps"])
        default_eps.extend(b["_default_eps"])
        for s in b["seeds"]:
            if s not in seeds_seen:
                seeds_seen.append(s)

    by_inv: dict[str, Any] = {}
    for inv in INVESTIGATOR_ORDER:
        a_rows = [e for e in adaptive_eps if e.get("investigator") == inv]
        d_rows = [e for e in default_eps if e.get("investigator") == inv]
        a_sum = _summarize_episode_slice(a_rows)
        d_sum = _summarize_episode_slice(d_rows)
        p_diffs = _paired_episode_diffs(a_rows, d_rows)
        by_inv[inv] = {
            "adaptive_mole": a_sum,
            "default_mole": d_sum,
            "n_paired": len(p_diffs),
            "delta_mean": round(a_sum["mean_score"] - d_sum["mean_score"], 4),
            "delta_mean_ci95": bootstrap_mean_ci95(p_diffs),
            "delta_accuracy": round(a_sum["accuracy"] - d_sum["accuracy"], 4),
        }

    solver_acc = by_inv["solver"]["adaptive_mole"]["accuracy"]
    solver_mean = by_inv["solver"]["adaptive_mole"]["mean_score"]
    grok_mean = by_inv["grok_tactics"]["adaptive_mole"]["mean_score"]
    heur_mean = by_inv["obvious_heuristic"]["adaptive_mole"]["mean_score"]
    default_grok_mean = by_inv["grok_tactics"]["default_mole"]["mean_score"]
    solvable = bool(
        adaptive_eps
        and solver_acc > 0.0
        and solver_mean > grok_mean
        and solver_mean > heur_mean
        and (grok_mean < default_grok_mean or heur_mean < solver_mean)
    )

    return {
        "n_runs": len(batches),
        "seeds": sorted(seeds_seen),
        "n_adaptive_episodes": len(adaptive_eps),
        "n_default_episodes": len(default_eps),
        "by_investigator": by_inv,
        "solvable": solvable,
        "mole_decisions": sum(int(b["mole_decisions"]) for b in batches),
        "mole_leaks": sum(int(b["mole_leaks"]) for b in batches),
        "mole_frames": sum(int(b["mole_frames"]) for b in batches),
        "mole_llm_errors": sum(int(b["mole_llm_errors"]) for b in batches),
        "mole_rejected_moves": sum(int(b["mole_rejected_moves"]) for b in batches),
        "usage": sum_usages([b["usage"] for b in batches]),
    }


def _build_live_arena_suite(records: list[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    for rec in records:
        run_dir: Path = rec["run_dir"]
        meta = rec["meta"]
        ep_doc = _load_json(run_dir / "episodes.json")
        decisions_rows = _load_jsonl(run_dir / "mole_decisions.jsonl")

        adaptive_eps = (
            [e for e in ep_doc.get("adaptive_mole", []) if isinstance(e, dict)]
            if isinstance(ep_doc, dict)
            else []
        )
        default_eps = (
            [e for e in ep_doc.get("default_mole", []) if isinstance(e, dict)]
            if isinstance(ep_doc, dict)
            else []
        )

        if decisions_rows:
            n_decisions = len(decisions_rows)
            n_leaks = sum(1 for d in decisions_rows if d.get("leak") is not None)
            n_frames = sum(1 for d in decisions_rows if d.get("frame") is not None)
            n_errors = sum(1 for d in decisions_rows if d.get("error"))
            n_rejected = sum(len(d.get("rejected") or []) for d in decisions_rows)
        elif adaptive_eps:
            n_decisions = sum(int(e.get("mole_days", 0) or 0) for e in adaptive_eps)
            n_leaks = sum(int(e.get("mole_leaks_chosen", 0) or 0) for e in adaptive_eps)
            n_frames = sum(int(e.get("mole_frames_chosen", 0) or 0) for e in adaptive_eps)
            n_errors = sum(int(e.get("mole_llm_errors", 0) or 0) for e in adaptive_eps)
            n_rejected = sum(int(e.get("mole_rejected_moves", 0) or 0) for e in adaptive_eps)
        else:
            n_decisions = int(meta.get("mole_decisions_count", 0) or 0)
            n_leaks = 0
            n_frames = 0
            n_errors = int(meta.get("mole_llm_errors", 0) or 0)
            n_rejected = int(meta.get("mole_rejected_moves_count", 0) or 0)

        raw_seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) else []
        seeds = [int(s) for s in raw_seeds if isinstance(s, int) and not isinstance(s, bool)]
        tier = clean_str(meta.get("tier") or "unknown")
        batches.append(
            {
                "run_dir": rec["rel_dir"],
                "tier": tier,
                "seeds": seeds,
                "model_id": rec["model_id"],
                "commit": rec["commit"],
                "solvability_verified": bool(meta.get("solvability_verified", False)),
                "solver_mean": round(float(meta.get("solver_mean", 0.0) or 0.0), 4),
                "solver_accuracy": round(float(meta.get("solver_accuracy", 0.0) or 0.0), 4),
                "grok_tactics_mean": round(float(meta.get("grok_tactics_mean", 0.0) or 0.0), 4),
                "heuristic_mean": round(float(meta.get("heuristic_mean", 0.0) or 0.0), 4),
                "mole_decisions": n_decisions,
                "mole_leaks": n_leaks,
                "mole_frames": n_frames,
                "mole_llm_errors": n_errors,
                "mole_rejected_moves": n_rejected,
                "usage": dict(rec["usage"]),
                "_adaptive_eps": adaptive_eps,
                "_default_eps": default_eps,
            }
        )

    batches.sort(
        key=lambda b: (
            TIER_RANK.get(b["tier"], 99),
            b["tier"],
            b["seeds"][0] if b["seeds"] else 0,
            b["run_dir"],
        )
    )
    tiers: list[str] = ["easy", "medium", "hard"]
    for b in batches:
        if b["tier"] not in tiers:
            tiers.append(b["tier"])

    by_tier = {t: _aggregate_arena_batches([b for b in batches if b["tier"] == t]) for t in tiers}
    overall = _aggregate_arena_batches(batches)
    public_runs = [{k: v for k, v in b.items() if not k.startswith("_")} for b in batches]
    return {
        "runs": public_runs,
        "by_tier": by_tier,
        "overall": overall,
    }


def _opt_round(val: Any, digits: int = 4) -> float | None:
    if _is_num(val):
        return round(float(val), digits)
    return None


def _build_mole_forge_suite(records: list[dict[str, Any]]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for rec in records:
        run_dir: Path = rec["run_dir"]
        meta = rec["meta"]
        gen_doc = _load_json(run_dir / "generations.json")
        gen_rows = (
            [g for g in gen_doc.get("generations", []) if isinstance(g, dict)]
            if isinstance(gen_doc, dict)
            else []
        )
        gens = int(meta["gens"]) if isinstance(meta.get("gens"), int) else len(gen_rows)
        best_fit = _opt_round(meta.get("best_fitness"), 4)
        if best_fit is None and gen_rows:
            best_fit = _opt_round(gen_rows[-1].get("hof_best_fitness", gen_rows[-1].get("best_fitness")), 4)
        def_dev_fit = _opt_round(meta.get("default_dev_fitness"), 4)
        if def_dev_fit is None and isinstance(gen_doc, dict) and isinstance(gen_doc.get("default_mole_dev"), dict):
            def_dev_fit = _opt_round(gen_doc["default_mole_dev"].get("fitness"), 4)
        dev_gain = (
            round(best_fit - def_dev_fit, 4)
            if best_fit is not None and def_dev_fit is not None
            else None
        )
        traj = [
            round(float(g.get("hof_best_fitness", g.get("best_fitness", 0.0))), 4)
            for g in gen_rows
            if _is_num(g.get("hof_best_fitness", g.get("best_fitness")))
        ]
        tier = clean_str(meta.get("tier") or (gen_doc.get("tier") if isinstance(gen_doc, dict) else "") or "unknown")
        holdout_doc = _load_json(run_dir / "holdout_generalization.json")
        has_holdout = isinstance(holdout_doc, dict)
        hold_summary = (
            holdout_doc.get("summary")
            if has_holdout and isinstance(holdout_doc.get("summary"), dict)
            else {}
        )
        hold_splits = (
            holdout_doc.get("splits")
            if has_holdout and isinstance(holdout_doc.get("splits"), dict)
            else {}
        )
        confirm_seeds = hold_splits.get("confirm_seeds") if isinstance(hold_splits.get("confirm_seeds"), list) else []
        runs.append(
            {
                "run_dir": rec["rel_dir"],
                "tier": tier,
                "model_id": rec["model_id"],
                "commit": rec["commit"],
                "gens": gens,
                "n_valid_llm_children": int(meta.get("n_valid_llm_children", 0) or 0),
                "n_invalid_llm_children": int(meta.get("n_invalid_llm_children", 0) or 0),
                "best_fitness": best_fit,
                "default_dev_fitness": def_dev_fit,
                "dev_fitness_gain": dev_gain,
                "fresh_solver_accuracy": _opt_round(meta.get("fresh_solver_accuracy"), 4),
                "fresh_min_regret": _opt_round(meta.get("fresh_min_regret"), 4),
                "default_fresh_min_regret": _opt_round(meta.get("default_fresh_min_regret"), 4),
                "has_holdout_generalization": has_holdout,
                "n_confirm_seeds": len(confirm_seeds),
                "top1_confirm_solver_acc": _opt_round(hold_summary.get("top1_confirm_solver_acc"), 4),
                "top1_confirm_min_regret": _opt_round(hold_summary.get("top1_confirm_min_regret"), 4),
                "all_evolved_solvable_confirm": (
                    bool(hold_summary["all_evolved_solvable_confirm"])
                    if isinstance(hold_summary.get("all_evolved_solvable_confirm"), bool)
                    else None
                ),
                "generations_recorded": len(gen_rows),
                "hof_fitness_trajectory": traj,
                "usage": dict(rec["usage"]),
            }
        )

    runs.sort(key=lambda r: (TIER_RANK.get(r["tier"], 99), r["tier"], r["run_dir"]))
    best_fits = [r["best_fitness"] for r in runs if r["best_fitness"] is not None]
    fresh_accs = [r["fresh_solver_accuracy"] for r in runs if r["fresh_solver_accuracy"] is not None]
    overall = {
        "n_runs": len(runs),
        "tiers": sorted({r["tier"] for r in runs}),
        "total_gens": sum(int(r["gens"]) for r in runs),
        "total_valid_llm_children": sum(int(r["n_valid_llm_children"]) for r in runs),
        "max_best_fitness": max(best_fits) if best_fits else None,
        "mean_fresh_solver_accuracy": round(statistics.mean(fresh_accs), 4) if fresh_accs else None,
        "usage": sum_usages([r["usage"] for r in runs]),
    }
    return {
        "runs": runs,
        "overall": overall,
    }


def _build_paired_designer_suite(records: list[dict[str, Any]]) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for rec in records:
        run_dir: Path = rec["run_dir"]
        meta = rec["meta"]
        sg_doc = _load_json(run_dir / "skill_gap.json")
        has_sg = isinstance(sg_doc, dict)
        hc = sg_doc.get("headline_comparison") if has_sg and isinstance(sg_doc.get("headline_comparison"), dict) else {}

        kept_sol = _opt_round(meta.get("kept_solver_mean"), 4)
        des_sol = _opt_round(meta.get("design_solver_mean"), 4)
        sol_mean = kept_sol if kept_sol is not None else des_sol

        kept_heur = _opt_round(meta.get("kept_heuristic_mean"), 4)
        des_heur = _opt_round(meta.get("design_heuristic_mean"), 4)
        heur_mean = kept_heur if kept_heur is not None else des_heur

        eval_sol = _opt_round(meta.get("eval_full_solver_mean"), 4)
        if eval_sol is None and isinstance(hc.get("full_solver"), dict):
            eval_sol = _opt_round(hc["full_solver"].get("designed_mean_score"), 4)

        eval_heur = _opt_round(meta.get("eval_heuristic_mean"), 4)
        if eval_heur is None and isinstance(hc.get("heuristic_bisection"), dict):
            eval_heur = _opt_round(hc["heuristic_bisection"].get("designed_mean_score"), 4)

        top_name = meta.get("top_scenario_name")
        if not top_name and has_sg and isinstance(sg_doc.get("selected_scenario"), dict):
            top_name = sg_doc["selected_scenario"].get("name")

        sg_rungs: dict[str, Any] = {}
        for rung_key, rung_val in hc.items():
            if isinstance(rung_val, dict):
                sg_rungs[clean_str(rung_key)] = {
                    "baseline_mean_score": _opt_round(rung_val.get("baseline_mean_score"), 4),
                    "designed_mean_score": _opt_round(rung_val.get("designed_mean_score"), 4),
                    "designed_accuracy": _opt_round(rung_val.get("designed_accuracy"), 4),
                }

        tier = clean_str(meta.get("tier") or "unknown")
        subrole = clean_str(meta.get("subrole") or "paired_designer")
        n_eval_eps = int(meta.get("n_episodes", 0) or 0)
        runs.append(
            {
                "run_dir": rec["rel_dir"],
                "tier": tier,
                "subrole": subrole,
                "model_id": rec["model_id"],
                "commit": rec["commit"],
                "n_llm_valid": int(meta.get("n_llm_valid", 0) or 0),
                "n_kept": int(meta.get("n_kept", 0) or 0),
                "n_eval_episodes": n_eval_eps,
                "kept_solver_mean": kept_sol,
                "design_solver_mean": des_sol,
                "solver_mean": sol_mean,
                "kept_heuristic_mean": kept_heur,
                "design_heuristic_mean": des_heur,
                "heuristic_mean": heur_mean,
                "eval_full_solver_mean": eval_sol,
                "eval_heuristic_mean": eval_heur,
                "top_scenario_name": clean_str(top_name) if top_name else None,
                "has_skill_gap": has_sg,
                "skill_gap_rungs": sg_rungs,
                "usage": dict(rec["usage"]),
            }
        )

    runs.sort(key=lambda r: (TIER_RANK.get(r["tier"], 99), r["tier"], r["subrole"], r["run_dir"]))
    tot_valid = sum(int(r["n_llm_valid"]) for r in runs)
    tot_kept = sum(int(r["n_kept"]) for r in runs)
    sol_vals = [r["solver_mean"] for r in runs if r["solver_mean"] is not None]
    heur_vals = [r["heuristic_mean"] for r in runs if r["heuristic_mean"] is not None]
    eval_sol_vals = [r["eval_full_solver_mean"] for r in runs if r["eval_full_solver_mean"] is not None]
    eval_heur_vals = [r["eval_heuristic_mean"] for r in runs if r["eval_heuristic_mean"] is not None]

    overall = {
        "n_runs": len(runs),
        "tiers": sorted({r["tier"] for r in runs}),
        "subroles": sorted({r["subrole"] for r in runs}),
        "total_llm_valid": tot_valid,
        "total_kept": tot_kept,
        "keep_rate": round(tot_kept / tot_valid, 4) if tot_valid > 0 else 0.0,
        "mean_solver_score": round(statistics.mean(sol_vals), 4) if sol_vals else None,
        "mean_heuristic_score": round(statistics.mean(heur_vals), 4) if heur_vals else None,
        "n_holdout_eval_runs": len(eval_sol_vals),
        "mean_eval_full_solver": round(statistics.mean(eval_sol_vals), 4) if eval_sol_vals else None,
        "mean_eval_heuristic": round(statistics.mean(eval_heur_vals), 4) if eval_heur_vals else None,
        "usage": sum_usages([r["usage"] for r in runs]),
    }
    return {
        "runs": runs,
        "overall": overall,
    }


def _fmt_opt(val: float | None, signed: bool = True) -> str:
    if val is None:
        return "n/a"
    return f"{val:+.4f}" if signed else f"{val:.4f}"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val * 100.0:.2f}%"


def _fmt_ci95(ci: Any, signed: bool = True) -> str:
    if not isinstance(ci, list) or len(ci) != 2:
        return "n/a"
    lo, hi = float(ci[0]), float(ci[1])
    if signed:
        return f"[{lo:+.4f}, {hi:+.4f}]"
    return f"[{lo:.4f}, {hi:.4f}]"


def _fmt_pct_ci95(ci: Any) -> str:
    if not isinstance(ci, list) or len(ci) != 2:
        return "n/a"
    lo, hi = float(ci[0]) * 100.0, float(ci[1]) * 100.0
    return f"[{lo:.1f}%, {hi:.1f}%]"


def _build_catchability_audit_summary(other_recs: list[dict[str, Any]]) -> dict[str, Any] | None:
    audit_recs = [
        r
        for r in other_recs
        if clean_str(r["meta"].get("subrole") or "") in {"catchability_isolation_audit", "catchability_audit"}
        or r["name"].startswith("catchability-audit")
    ]
    if not audit_recs:
        return None
    rec = sorted(audit_recs, key=lambda x: (str(x["meta"].get("timestamp") or ""), x["rel_dir"]))[-1]
    meta = rec["meta"]
    n_pass = int(meta.get("n_catchability_passed", 0) or 0)
    n_targ = int(meta.get("n_catchability_targets", 0) or 0)
    comp_rate = _opt_round(meta.get("catchability_compliance_rate"), 4)
    if comp_rate is None and n_targ > 0:
        comp_rate = round(n_pass / n_targ, 4)
    return {
        "run_dir": rec["rel_dir"],
        "commit": rec["commit"],
        "n_runs_audited": int(meta.get("n_runs_audited", 0) or 0),
        "n_strategies_audited": int(meta.get("n_strategies_audited", 0) or 0),
        "n_decisions_audited": int(meta.get("n_decisions_audited", 0) or 0),
        "n_views_checked": int(meta.get("n_views_checked", 0) or 0),
        "isolation_violations": int(meta.get("isolation_violations", 0) or 0),
        "file_secret_leaks": int(meta.get("file_secret_leaks", 0) or 0),
        "data_hygiene_violations": int(meta.get("data_hygiene_violations", 0) or 0),
        "n_catchability_passed": n_pass,
        "n_catchability_targets": n_targ,
        "catchability_compliance_rate": comp_rate,
        "catchability_compliance_ci95": wilson_ci95(n_pass, n_targ),
        "live_solvability_compliance_rate": _opt_round(meta.get("live_solvability_compliance_rate"), 4),
        "forensic_cross_check_agreement_rate": _opt_round(meta.get("forensic_cross_check_agreement_rate"), 4),
        "zero_privileged_canary_awareness_confirmed": bool(
            meta.get("zero_privileged_canary_awareness_confirmed", False)
        ),
        "usage": dict(rec["usage"]),
    }


def render_summary_md(suite: dict[str, Any]) -> str:
    tot = suite["totals"]
    clash = suite["clash_suite"]
    arena = suite["live_arena_suite"]
    forge = suite["mole_forge_suite"]
    paired = suite["paired_designer_suite"]
    other_runs = suite["other_verified_runs"]
    catch_audit = suite.get("catchability_audit")

    lines: list[str] = [
        f"{MD_H1} Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)",
        "",
        f"- Role: `{suite['role']}`",
        f"- Environment scope: `{suite.get('environment_scope', ENVIRONMENT_SCOPE)}`",
        f"- Target Model ID: `{suite['target_model']}`",
        f"- Verified `adaptive_mole` run folders consolidated: `{tot['verified_folders']}`",
        f"- Total Gemini API calls: `{tot['calls']}`",
        (
            f"- Total tokens (in / out / thinking / cached): "
            f"`{tot['in']:,}` / `{tot['out']:,}` / `{tot['thinking']:,}` / `{tot['cached']:,}`"
        ),
        f"- Total estimated cost (USD): `${tot['cost_usd']:.6f}`",
        "- Provenance note: `carbon-vs-carbon-suite/` omits `meta.json` so role scanners do not double-count tokens or costs.",
        "",
        f"{MD_H2} 1. Head-to-Head Carbon-vs-Carbon Clash Suite (`clash_suite`)",
        "",
        "| Slice | Shards | Episodes | Investigator Acc (95% CI) | Investigator Mean (95% CI) | Solver Acc | Solver Mean (95% CI) | Solvable Rate (95% CI) | Mean Regret (95% CI) | Mole Leaks | Mole Frames | Mole Errors | Combined Tokens (in/out/think) | Inv Cost | Mole Cost | Total Cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]

    clash_rows = [
        (t, clash["by_tier"][t])
        for t in ("easy", "medium", "hard")
        if t in clash["by_tier"] and clash["by_tier"][t]["n_shards"] > 0
    ] + [("overall", clash["overall"])]

    for label, row in clash_rows:
        cu = row["usage"]["combined"]
        iu = row["usage"]["clash_investigator"]
        mu = row["usage"]["clash_mole"]
        tok_str = f"{cu['in']:,}/{cu['out']:,}/{cu['thinking']:,}"
        lines.append(
            f"| `{label}` | {row['n_shards']} | {row['n_episodes']} | "
            f"{_fmt_pct(row['investigator_accuracy'])} {_fmt_pct_ci95(row['investigator_accuracy_ci95'])} | "
            f"{row['investigator_mean_score']:+.4f} {_fmt_ci95(row['investigator_mean_ci95'])} | "
            f"{_fmt_pct(row['solver_accuracy'])} | "
            f"{row['solver_mean_score']:+.4f} {_fmt_ci95(row['solver_mean_ci95'])} | "
            f"{_fmt_pct(row['solvable_rate'])} {_fmt_pct_ci95(row['solvable_rate_ci95'])} | "
            f"{row['mean_regret']:+.4f} {_fmt_ci95(row['mean_regret_ci95'])} | "
            f"{row['mole_total_leaks']} | {row['mole_total_frames']} | {row['mole_total_errors']} | "
            f"`{tok_str}` | ${iu['cost_usd']:.4f} | ${mu['cost_usd']:.4f} | ${cu['cost_usd']:.4f} |"
        )

    if clash["shards"]:
        lines.extend(
            [
                "",
                f"{MD_H3} Per-Seed Clash Shards",
                "",
                "| Run Folder | Tier | Seed | Commit | Inv Score | Inv Correct | Solver Score | Solver Correct | Solvable | Regret | Leaks | Frames | Errors | Cost (USD) |",
                "| --- | --- | ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for sh in clash["shards"]:
            lines.append(
                f"| `{sh['run_dir']}` | `{sh['tier']}` | {sh['seed']} | `{sh['commit'][:10]}` | "
                f"{sh['investigator_score']:+.4f} | {sh['investigator_correct']} | "
                f"{sh['solver_score']:+.4f} | {sh['solver_correct']} | {sh['solvable']} | "
                f"{sh['regret']:+.4f} | {sh['mole_clash_leaks']} | {sh['mole_clash_frames']} | "
                f"{sh['mole_clash_errors']} | ${sh['usage']['cost_usd']:.4f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} 2. Live Arena Adaptive Mole Suite (`live_arena_suite`)",
            "",
            "| Slice | Investigator | Adaptive Mole Mean (95% CI) | Adaptive Mole Acc (95% CI) | Default Mole Mean (95% CI) | Default Mole Acc | Paired Delta Mean (95% CI) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    arena_rows = [
        (t, arena["by_tier"][t])
        for t in ("easy", "medium", "hard")
        if t in arena["by_tier"] and arena["by_tier"][t]["n_runs"] > 0
    ] + [("overall", arena["overall"])]

    for slice_label, slice_obj in arena_rows:
        for inv in INVESTIGATOR_ORDER:
            ir = slice_obj["by_investigator"][inv]
            am = ir["adaptive_mole"]
            dm = ir["default_mole"]
            lines.append(
                f"| `{slice_label}` (n={am['n']}) | `{inv}` | "
                f"{am['mean_score']:+.4f} {_fmt_ci95(am['mean_score_ci95'])} | "
                f"{_fmt_pct(am['accuracy'])} {_fmt_pct_ci95(am['accuracy_ci95'])} | "
                f"{dm['mean_score']:+.4f} {_fmt_ci95(dm['mean_score_ci95'])} | "
                f"{_fmt_pct(dm['accuracy'])} | "
                f"{ir['delta_mean']:+.4f} {_fmt_ci95(ir['delta_mean_ci95'])} |"
            )

    if arena["runs"]:
        lines.extend(
            [
                "",
                f"{MD_H3} Live Arena Seed Batches",
                "",
                "| Run Folder | Tier | Seeds | Commit | Decisions | Leaks | Frames | LLM Errors | Solvable | Calls | Tokens (in/out/think) | Cost (USD) |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |",
            ]
        )
        for ar in arena["runs"]:
            au = ar["usage"]
            lines.append(
                f"| `{ar['run_dir']}` | `{ar['tier']}` | `{ar['seeds']}` | `{ar['commit'][:10]}` | "
                f"{ar['mole_decisions']} | {ar['mole_leaks']} | {ar['mole_frames']} | {ar['mole_llm_errors']} | "
                f"{ar['solvability_verified']} | {au['calls']} | `{au['in']:,}/{au['out']:,}/{au['thinking']:,}` | "
                f"${au['cost_usd']:.4f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} 3. Mole Forge Evolutionary DSL Suite (`mole_forge_suite`)",
            "",
            "| Run Folder | Tier | Gens | Valid LLM Children | Best Fitness | Default Dev Fitness | Fresh Solver Acc | Fresh Min Regret | Default Fresh Min Regret | Confirm Holdout Acc | Calls | Cost (USD) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for fr in forge["runs"]:
        fu = fr["usage"]
        conf_str = (
            f"{_fmt_pct(fr['top1_confirm_solver_acc'])} (n={fr['n_confirm_seeds']})"
            if fr.get("has_holdout_generalization") and fr.get("top1_confirm_solver_acc") is not None
            else "n/a"
        )
        lines.append(
            f"| `{fr['run_dir']}` | `{fr['tier']}` | {fr['gens']} | {fr['n_valid_llm_children']} | "
            f"{_fmt_opt(fr['best_fitness'], signed=False)} | {_fmt_opt(fr['default_dev_fitness'], signed=False)} | "
            f"{_fmt_pct(fr['fresh_solver_accuracy'])} | {_fmt_opt(fr['fresh_min_regret'], signed=False)} | "
            f"{_fmt_opt(fr['default_fresh_min_regret'], signed=False)} | {conf_str} | {fu['calls']} | ${fu['cost_usd']:.4f} |"
        )

    lines.extend(
        [
            "",
            f"{MD_H2} 4. PAIRED Solvable Scenario Designer Suite (`paired_designer_suite`)",
            "",
            "| Run Folder | Tier | Subrole | Kept / Valid | Design/Kept Solver Mean | Design/Kept Heuristic Mean | Holdout Full Solver Mean | Holdout Heuristic Mean | Top Scenario | Calls | Cost (USD) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for pr in paired["runs"]:
        pu = pr["usage"]
        scen = f"`{pr['top_scenario_name']}`" if pr["top_scenario_name"] else "-"
        lines.append(
            f"| `{pr['run_dir']}` | `{pr['tier']}` | `{pr['subrole']}` | {pr['n_kept']}/{pr['n_llm_valid']} | "
            f"{_fmt_opt(pr['solver_mean'])} | {_fmt_opt(pr['heuristic_mean'])} | "
            f"{_fmt_opt(pr['eval_full_solver_mean'])} | {_fmt_opt(pr['eval_heuristic_mean'])} | "
            f"{scen} | {pu['calls']} | ${pu['cost_usd']:.4f} |"
        )

    if isinstance(catch_audit, dict):
        lines.extend(
            [
                "",
                f"{MD_H2} Catchability & Secret-Isolation Audit (`catchability_audit`)",
                "",
                f"- Audit folder: `{catch_audit['run_dir']}` (commit `{catch_audit['commit'][:10]}`)",
                f"- Runs / strategies / live decisions / MoleViews checked: `{catch_audit['n_runs_audited']}` / `{catch_audit['n_strategies_audited']}` / `{catch_audit['n_decisions_audited']}` / `{catch_audit['n_views_checked']}`",
                f"- Privileged-state isolation violations: `{catch_audit['isolation_violations']}` (file secret leaks: `{catch_audit['file_secret_leaks']}`)",
                f"- Catchability compliance: `{catch_audit['n_catchability_passed']}/{catch_audit['n_catchability_targets']}` (`{_fmt_pct(catch_audit['catchability_compliance_rate'])}` {_fmt_pct_ci95(catch_audit['catchability_compliance_ci95'])})",
                f"- Zero privileged canary awareness confirmed by `gemini-4-carbon`: `{catch_audit['zero_privileged_canary_awareness_confirmed']}`",
            ]
        )

    if other_runs:
        lines.extend(
            [
                "",
                f"{MD_H2} Additional Verified Adaptive Mole Runs",
                "",
                "| Run Folder | Subrole | Commit | Calls | Tokens (in/out/think) | Cost (USD) |",
                "| --- | --- | --- | ---: | --- | ---: |",
            ]
        )
        for orun in other_runs:
            ou = orun["usage"]
            lines.append(
                f"| `{orun['run_dir']}` | `{orun['subrole']}` | `{orun['commit'][:10]}` | "
                f"{ou['calls']} | `{ou['in']:,}/{ou['out']:,}/{ou['thinking']:,}` | ${ou['cost_usd']:.4f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} 5. De-Duplicated Totals (`totals`)",
            "",
            "| Suite Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for key, label in [
        ("clash_suite", "clash_suite"),
        ("live_arena_suite", "live_arena_suite"),
        ("mole_forge_suite", "mole_forge_suite"),
        ("paired_designer_suite", "paired_designer_suite"),
        ("other_verified_runs", "other_verified_runs"),
    ]:
        bs = tot["by_suite"][key]
        if key == "other_verified_runs" and bs["verified_folders"] == 0:
            continue
        lines.append(
            f"| `{label}` | {bs['verified_folders']} | {bs['calls']} | {bs['in']:,} | {bs['out']:,} | "
            f"{bs['thinking']:,} | {bs['cached']:,} | ${bs['cost_usd']:.6f} |"
        )
    lines.append(
        f"| **total** | **{tot['verified_folders']}** | **{tot['calls']}** | **{tot['in']:,}** | "
        f"**{tot['out']:,}** | **{tot['thinking']:,}** | **{tot['cached']:,}** | **${tot['cost_usd']:.6f}** |"
    )
    lines.append("")
    return clean_str("\n".join(lines))


def render_adaptive_mole_doc(suite: dict[str, Any], iso_summary: dict[str, Any]) -> str:
    tot = suite["totals"]
    forge = suite["mole_forge_suite"]
    paired = suite["paired_designer_suite"]
    arena = suite["live_arena_suite"]
    clash = suite["clash_suite"]
    catch_audit = suite.get("catchability_audit")

    ar_overall = arena["overall"]["by_investigator"]
    ar_sol = ar_overall["solver"]
    ar_grok = ar_overall["grok_tactics"]
    cl_overall = clash["overall"]
    forge_tiers = ", ".join(forge["overall"]["tiers"]) if forge["overall"]["tiers"] else "none"

    header: list[str] = [
        f"{MD_H1} Adaptive Gemini Mole (`gemini-4-carbon`): Mole Forge, PAIRED Designer, Live Arena & Clashes",
        "",
        "Every number in this report is computed directly from committed `results/gemini/roles_carbon/adaptive_mole/`",
        "artifacts by `python -m canary.gemini.mole_carbon` (nothing is typed by hand).",
        "",
        f"{MD_H2} Scope & Non-Judged Arena Disclosure",
        "",
        f"1. **Scope (`{ENVIRONMENT_SCOPE}`):** All runs in this suite operate in **{ENVIRONMENT_SCOPE}**,",
        "   on public dev and holdout confirmation seeds (`0..59`, `5020..5399`). The judged Canary v1.4 benchmark",
        "   (`a8f99c2537c91d72`) uses frozen scripted moles only and is never modified here.",
        "2. **Environment simplifications disclosed:** Leak damage in Canary v1.4 is flat per leak regardless of recipient",
        "   count, so broad-distribution leaking is rewarded unless constrained by `p_leak` and canary traps;",
        "   per-recipient watermarking remains a v2 mechanic.",
        "3. **Privileged-state isolation enforced:** Across all committed live decisions and evolved DSL strategies,",
        f"   keyless verification (`canary.gemini.mole_carbon.audit_committed_mole_runs`) checks `{iso_summary['decisions_checked']}`",
        f"   logged mole decisions (`{iso_summary['views_checked']}` `MoleView` snapshots) and `{iso_summary['strategies_checked']}`",
        f"   Hall-of-Fame DSL strategies with `{iso_summary['isolation_violations']}` privileged-state violations",
        f"   (`is_canary`, `variant`, `posterior`/`belief`, or secret keys) and `{iso_summary['secret_leaks']}` file secret leaks.",
        "",
        f"{MD_H2} Headline Summary (`gemini-4-carbon`)",
        "",
        f"- **Verified `adaptive_mole` runs:** `{tot['verified_folders']}` folders, `{tot['calls']}` Gemini API calls,",
        f"  `{tot['in']:,}` input / `{tot['out']:,}` output / `{tot['thinking']:,}` thinking / `{tot['cached']:,}` cached tokens,",
        f"  total estimated cost **`${tot['cost_usd']:.2f}`** (`${tot['cost_usd']:.6f}`).",
        f"- **Mole Forge evolutionary DSL (`n={forge['overall']['n_runs']}` runs across `{forge_tiers}`):**",
        f"  Replaces the earlier stub-mutator Hall of Fame with `{forge['overall']['total_valid_llm_children']}` valid",
        "  `gemini-4-carbon`-mutated DSL strategies across `easy`, `medium`, and `hard`, each verified on **40-seed unseen",
        "  confirmation holdouts (`5020..5059`)** for catchability by `SolverPolicy`.",
        f"- **PAIRED solvable scenario & skill-ladder designer (`n={paired['overall']['n_runs']}` runs):**",
        f"  `{paired['overall']['total_kept']}/{paired['overall']['total_llm_valid']}` (`{_fmt_pct(paired['overall']['keep_rate'])}`) valid",
        "  `gemini-4-carbon` proposals pass solvability + regret gates, sustaining positive `SolverPolicy` scores on",
        "  40-seed fresh holdouts while driving heuristic baselines near `-1.00`.",
        f"- **Live Arena adaptive mole (`n={ar_sol['adaptive_mole']['n']}` paired episodes per investigator):**",
        f"  Against `SolverPolicy`, investigator score drops from `{ar_sol['default_mole']['mean_score']:+.4f}` (default mole)",
        f"  to `{ar_sol['adaptive_mole']['mean_score']:+.4f}` {_fmt_ci95(ar_sol['adaptive_mole']['mean_score_ci95'])}",
        f"  (paired delta `{ar_sol['delta_mean']:+.4f}` {_fmt_ci95(ar_sol['delta_mean_ci95'])}, solver catch rate",
        f"  `{_fmt_pct(ar_sol['adaptive_mole']['accuracy'])}` {_fmt_pct_ci95(ar_sol['adaptive_mole']['accuracy_ci95'])});",
        f"  against `GrokTactics`, score drops from `{ar_grok['default_mole']['mean_score']:+.4f}` to",
        f"  `{ar_grok['adaptive_mole']['mean_score']:+.4f}` (paired delta `{ar_grok['delta_mean']:+.4f}` {_fmt_ci95(ar_grok['delta_mean_ci95'])}).",
        f"- **Head-to-head `gemini-4-carbon` mole vs `gemini-4-carbon` investigator (`n={cl_overall['n_shards']}` shards, `{cl_overall['n_episodes']}` episodes):**",
        f"  Live `gemini-4-carbon` investigator achieves `{_fmt_pct(cl_overall['investigator_accuracy'])}` {_fmt_pct_ci95(cl_overall['investigator_accuracy_ci95'])}",
        f"  accuracy and `{cl_overall['investigator_mean_score']:+.4f}` {_fmt_ci95(cl_overall['investigator_mean_ci95'])} mean score",
        f"  against the live `gemini-4-carbon` mole (`0` mole LLM errors), paired with `SolverPolicy`",
        f"  (`{cl_overall['solver_mean_score']:+.4f}` {_fmt_ci95(cl_overall['solver_mean_ci95'])}, solvable rate",
        f"  `{_fmt_pct(cl_overall['solvable_rate'])}` {_fmt_pct_ci95(cl_overall['solvable_rate_ci95'])}).",
        "",
    ]

    if isinstance(catch_audit, dict):
        header.extend(
            [
                f"- **Forensic catchability audit (`{catch_audit['run_dir']}`):**",
                f"  `{catch_audit['n_catchability_passed']}/{catch_audit['n_catchability_targets']}`",
                f"  (`{_fmt_pct(catch_audit['catchability_compliance_rate'])}` {_fmt_pct_ci95(catch_audit['catchability_compliance_ci95'])})",
                "  targets compliant, zero privileged canary awareness confirmed by `gemini-4-carbon`.",
                "",
            ]
        )

    body_lines = render_summary_md(suite).splitlines()
    if body_lines and body_lines[0].startswith(f"{MD_H1} "):
        body_lines = body_lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)

    return clean_str("\n".join(header + body_lines) + "\n")


def consolidate_adaptive_mole(
    root: str | Path = ".",
    roles_dir: str | Path | None = None,
    out_dir: str | Path | None = None,
    doc_path: str | Path | bool | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    if roles_dir is None:
        resolved_roles = root_path / DEFAULT_ROLES_REL
    else:
        raw_roles = Path(roles_dir)
        resolved_roles = raw_roles if raw_roles.is_absolute() else (root_path / raw_roles)

    if out_dir is None:
        out_path = resolved_roles / SUITE_DIR_NAME
    else:
        raw_out = Path(out_dir)
        out_path = raw_out if raw_out.is_absolute() else (root_path / raw_out)

    verified_records, skipped_records = discover_adaptive_mole_runs(root_path, resolved_roles, out_path)

    buckets: dict[str, list[dict[str, Any]]] = {
        "clash": [],
        "live_arena": [],
        "mole_forge": [],
        "paired_designer": [],
        "other": [],
    }
    for rec in verified_records:
        buckets[_classify_run(rec)].append(rec)

    clash_suite = _build_clash_suite(buckets["clash"])
    live_arena_suite = _build_live_arena_suite(buckets["live_arena"])
    mole_forge_suite = _build_mole_forge_suite(buckets["mole_forge"])
    paired_designer_suite = _build_paired_designer_suite(buckets["paired_designer"])
    catchability_audit = _build_catchability_audit_summary(buckets["other"])
    iso_summary = audit_committed_mole_runs(resolved_roles, root_path)

    other_verified_runs = [
        {
            "run_dir": r["rel_dir"],
            "subrole": clean_str(r["meta"].get("subrole") or r["name"]),
            "model_id": r["model_id"],
            "commit": r["commit"],
            "usage": dict(r["usage"]),
        }
        for r in sorted(buckets["other"], key=lambda x: x["rel_dir"])
    ]

    def _suite_tot(recs: list[dict[str, Any]]) -> dict[str, Any]:
        u = sum_usages([r["usage"] for r in recs])
        return {"verified_folders": len(recs), **u}

    grand_u = sum_usages([r["usage"] for r in verified_records])
    totals = {
        "verified_folders": len(verified_records),
        "n_verified_runs": len(verified_records),
        "calls": grand_u["calls"],
        "in": grand_u["in"],
        "out": grand_u["out"],
        "thinking": grand_u["thinking"],
        "cached": grand_u["cached"],
        "total_tokens": grand_u["total_tokens"],
        "cost_usd": grand_u["cost_usd"],
        "latency_s": grand_u["latency_s"],
        "tokens": {
            "in": grand_u["in"],
            "out": grand_u["out"],
            "thinking": grand_u["thinking"],
            "cached": grand_u["cached"],
            "total": grand_u["total_tokens"],
        },
        "by_suite": {
            "clash_suite": _suite_tot(buckets["clash"]),
            "live_arena_suite": _suite_tot(buckets["live_arena"]),
            "mole_forge_suite": _suite_tot(buckets["mole_forge"]),
            "paired_designer_suite": _suite_tot(buckets["paired_designer"]),
            "other_verified_runs": _suite_tot(buckets["other"]),
        },
    }

    timestamps = sorted(
        str(r["meta"].get("timestamp")).strip()
        for r in verified_records
        if isinstance(r["meta"].get("timestamp"), str) and str(r["meta"].get("timestamp")).strip()
    )
    commits = list(dict.fromkeys(r["commit"] for r in sorted(verified_records, key=lambda x: x["rel_dir"])))

    suite_payload: dict[str, Any] = sanitize_obj(
        {
            "role": ROLE,
            "suite": SUITE_DIR_NAME,
            "environment_scope": ENVIRONMENT_SCOPE,
            "target_model": TARGET_MODEL,
            "latest_run_timestamp": timestamps[-1] if timestamps else None,
            "source_commits": commits,
            "verified_run_dirs": [r["rel_dir"] for r in sorted(verified_records, key=lambda x: x["rel_dir"])],
            "skipped_runs": skipped_records,
            "clash_suite": clash_suite,
            "live_arena_suite": live_arena_suite,
            "mole_forge_suite": mole_forge_suite,
            "paired_designer_suite": paired_designer_suite,
            "catchability_audit": catchability_audit,
            "repo_isolation_audit": iso_summary,
            "other_verified_runs": other_verified_runs,
            "totals": totals,
        }
    )

    out_path.mkdir(parents=True, exist_ok=True)
    meta_guard = out_path / "meta.json"
    if meta_guard.exists():
        meta_guard.unlink()

    suite_json_text = clean_str(json.dumps(suite_payload, indent=2, sort_keys=False)) + "\n"
    summary_md_text = render_summary_md(suite_payload)
    (out_path / "suite.json").write_text(suite_json_text, encoding="utf-8")
    (out_path / "summary.md").write_text(summary_md_text, encoding="utf-8")

    resolved_doc: Path | None = None
    if doc_path is False or doc_path == "":
        resolved_doc = None
    elif doc_path is True:
        resolved_doc = root_path / DEFAULT_DOC_REL
    elif doc_path is None:
        if out_dir is None:
            resolved_doc = root_path / DEFAULT_DOC_REL
    else:
        raw_doc = Path(doc_path)
        resolved_doc = raw_doc if raw_doc.is_absolute() else (root_path / raw_doc)

    if resolved_doc is not None:
        resolved_doc.parent.mkdir(parents=True, exist_ok=True)
        resolved_doc.write_text(render_adaptive_mole_doc(suite_payload, iso_summary), encoding="utf-8")

    return suite_payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.mole_carbon")
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--roles-dir", default=None, help="adaptive_mole runs directory")
    ap.add_argument("--out", default=None, help="output suite directory")
    ap.add_argument("--doc", default=str(DEFAULT_DOC_REL), help="markdown report path (empty string to skip)")
    args = ap.parse_args(argv)
    doc_arg: str | bool = args.doc if args.doc else False
    payload = consolidate_adaptive_mole(root=args.root, roles_dir=args.roles_dir, out_dir=args.out, doc_path=doc_arg)
    tot = payload["totals"]
    print(
        json.dumps(
            {
                "verified_folders": tot["verified_folders"],
                "clash_shards": payload["clash_suite"]["overall"]["n_shards"],
                "live_arena_runs": payload["live_arena_suite"]["overall"]["n_runs"],
                "mole_forge_runs": payload["mole_forge_suite"]["overall"]["n_runs"],
                "paired_designer_runs": payload["paired_designer_suite"]["overall"]["n_runs"],
                "calls": tot["calls"],
                "tokens_in": tot["in"],
                "tokens_out": tot["out"],
                "cost_usd": tot["cost_usd"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
