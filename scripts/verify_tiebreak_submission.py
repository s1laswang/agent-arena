"""Offline submission verifier and provenance gate for Canary tiebreak deliverables."""
from __future__ import annotations

import argparse
import ast
import io
import json
import math
import re
import subprocess
import sys
import time
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

TRAIN_SEED_MIN = 100_000
TRAIN_SEED_MAX = 200_000
HELDOUT_SEED_MIN = 800_000
HELDOUT_SEED_MAX = 800_200
DEV_SEED_MIN = 0
DEV_SEED_MAX = 10_000
JUDGE_SEED_MIN = 900_000
MIN_VERIFIED_N = 30
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_RUNTIME_SECONDS = 30.0

CHECK_NAMES: tuple[str, ...] = (
    "protected_and_frozen_paths",
    "ast_inference_isolation",
    "seed_and_secret_provenance",
    "claim_number_audit",
    "hygiene_and_panel_fix_a",
)

ALWAYS_FROZEN_EXACT: tuple[str, ...] = (
    "results/judge_episodes.jsonl",
)

FROZEN_SILAS_EXACT: tuple[str, ...] = (
    "README.md",
    "docs/SUBMISSION.md",
    "docs/reports/fr8.md",
    "docs/reports/gap.md",
    "docs/reports/CEO.md",
    "docs/reports/judge_sim.md",
    "docs/reports/number_audit.md",
    "docs/reports/verda-evidence.md",
    "docs/DIFFICULTY.md",
    "docs/CONTRACT.md",
    "docs/DEMO.md",
    "docs/EXPLOITS.md",
    "docs/HISTORY.md",
    "docs/PLAN.md",
    "docs/PLAN-95.md",
    "docs/agents/PANEL-0500.md",
    "fr8/verda/README.md",
    "results/judge_episodes.jsonl",
)

FROZEN_SILAS_PREFIXES: tuple[str, ...] = (
    "docs/gemini/",
)

REQUIRED_INFERENCE_MODULES: tuple[str, ...] = (
    "train/compact_render.py",
    "train/eval_compact_hf.py",
    "train/empirical_bayes_policy.py",
    "scripts/tiebreak_scaling_calibration.py",
)

OPTIONAL_INFERENCE_MODULES: tuple[str, ...] = (
    "train/neural_mlp_tiebreak.py",
    "train/compact_lora_sft.py",
    "train/qwen15b_compact_dagger.py",
    "train/frugal_raw_dagger.py",
    "train/compact_dagger_ablation.py",
    "train/qwen15b_dpo_dagger.py",
    "scripts/tiebreak_mcp_wire_parity.py",
    "scripts/tiebreak_harbor_shell_bridge.py",
    "scripts/tiebreak_multiseed_stability_audit.py",
    "scripts/tiebreak_learning_curve.py",
    "scripts/tiebreak_channel_ablation_audit.py",
    "scripts/tiebreak_canary_split_design_audit.py",
    "scripts/tiebreak_cross_tier_transfer_audit.py",
    "scripts/tiebreak_byzantine_stress_audit.py",
    "scripts/tiebreak_pareto_efficiency.py",
    "scripts/tiebreak_statistical_power_audit.py",
    "scripts/tiebreak_framing_decoy_audit.py",
    "scripts/tiebreak_selective_risk_coverage_audit.py",
    "scripts/tiebreak_restriction_containment_audit.py",
    "scripts/tiebreak_action_budget_horizon_audit.py",
    "scripts/tiebreak_compact_ensemble_gate.py",
    "scripts/tiebreak_representation_bottleneck_audit.py",
    "scripts/tiebreak_stopping_counterfactual_audit.py",
    "scripts/tiebreak_covariate_shift_audit.py",
)

MODULES_REQUIRING_POLICY_CLASS: frozenset[str] = frozenset({
    "train/compact_render.py",
    "train/empirical_bayes_policy.py",
    "scripts/tiebreak_scaling_calibration.py",
})

FORBIDDEN_WEIGHT_SUFFIXES: frozenset[str] = frozenset({
    ".safetensors",
    ".bin",
    ".pt",
    ".pth",
    ".ckpt",
})

FORBIDDEN_SECRET_PLACEHOLDERS: frozenset[str] = frozenset({
    "",
    "none",
    "null",
    "unset",
    "unpaired",
    "unknown",
    "missing",
    "todo",
    "na",
    "n/a",
    "random",
    "urandom",
    "os.urandom",
    "per_process",
    "per-process",
    "proc_secret",
    "ephemeral",
})

FORBIDDEN_SECRET_PREFIXES: tuple[str, ...] = (
    "unset",
    "unpaired",
    "proc:",
    "proc_",
    "per_process",
    "per-process",
    "random:",
    "random_",
    "urandom",
    "ephemeral",
)

TRAIN_SEED_KEYS: frozenset[str] = frozenset({
    "train_seeds",
    "train_seed_range",
    "stage1_seed_range",
    "stage2_seed_range",
    "stage3_seed_range",
    "sft_seed_range",
    "dpo_seed_range",
    "dagger_seed_range",
    "train_seed_start",
    "s1_train_seed_start",
    "train_seed_min",
    "train_seed_max",
})

HELDOUT_EVAL_SEED_KEYS: frozenset[str] = frozenset({
    "eval_seeds",
    "heldout_seeds",
    "eval_seed_range",
    "heldout_seed_range",
    "paired_seeds",
})

DEV_EVAL_SEED_KEYS: frozenset[str] = frozenset({
    "dev_eval_seeds",
    "dev_eval_seed_range",
})

TRAIN_PARENT_SCOPES: frozenset[str] = frozenset({
    "train",
    "training",
    "stage1",
    "stage2",
    "stage3",
    "sft",
    "dpo",
    "dagger",
})

HELDOUT_PARENT_SCOPES: frozenset[str] = frozenset({
    "heldout",
    "before",
    "after",
})

DEV_PARENT_SCOPES: frozenset[str] = frozenset({
    "dev",
    "dev_hard",
    "dev_eval",
})

SEED_RANGE_STR_RE = re.compile(r"^\s*(-?\d+)\s*(?:\.\.|-)\s*(-?\d+)\s*$")
TABLE_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")
FLOAT_TOKEN_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)


@dataclass
class CheckOutcome:
    name: str
    passed: bool
    summary: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _valid_secret_tag(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    low = s.lower()
    if len(s) < 6 or low in FORBIDDEN_SECRET_PLACEHOLDERS:
        return None
    if low.startswith(FORBIDDEN_SECRET_PREFIXES):
        return None
    return s


def load_protected_rules(protected_file: Path) -> tuple[list[str], list[str]]:
    exact: list[str] = []
    prefixes: list[str] = []
    for raw_line in protected_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        if line.endswith("/"):
            prefixes.append(line)
        else:
            exact.append(line)
    return exact, prefixes


def _matches_path_rule(rel_path: str, exact_rules: Iterable[str], prefix_rules: Iterable[str]) -> str | None:
    norm = rel_path.strip().removeprefix("./")
    for ex in exact_rules:
        if norm == ex:
            return ex
    for pref in prefix_rules:
        if norm.startswith(pref) or norm == pref.rstrip("/"):
            return pref
    return None


def _git_diff_paths(root: Path, base_ref: str) -> tuple[list[str], str | None, str | None]:
    default_base = base_ref in ("origin/justSilas", "justSilas")
    candidates = [base_ref]
    if base_ref == "origin/justSilas":
        candidates.append("justSilas")
    elif base_ref == "justSilas":
        candidates.append("origin/justSilas")
    resolved_ref: str | None = None
    diff_lines: list[str] = []
    last_err: str | None = None
    for ref in candidates:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{ref}...HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            resolved_ref = ref
            diff_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            break
        last_err = (proc.stderr or proc.stdout).strip() or f"git diff exited {proc.returncode}"

    if resolved_ref is None:
        if not default_base:
            return [], None, last_err
        head_proc = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if head_proc.returncode == 0:
            resolved_ref = "HEAD"
        else:
            return [], "offline_archive", None

    wt_proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if wt_proc.returncode == 0:
        wt_lines = [ln.strip() for ln in wt_proc.stdout.splitlines() if ln.strip()]
        seen = set(diff_lines)
        for p in wt_lines:
            if p not in seen:
                diff_lines.append(p)
                seen.add(p)
    return diff_lines, resolved_ref, None


def _current_git_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def check_protected_and_frozen_paths(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
    changed_paths: Iterable[str] | None = None,
    strict: bool = False,
) -> CheckOutcome:
    errors: list[str] = []
    warnings: list[str] = []
    protected_file = root / ".github" / "protected-paths.txt"
    if not protected_file.is_file():
        return CheckOutcome(
            name="protected_and_frozen_paths",
            passed=False,
            summary="missing .github/protected-paths.txt",
            errors=[f"missing required guard file: {protected_file}"],
        )

    prot_exact, prot_prefixes = load_protected_rules(protected_file)
    resolved_ref = "explicit_paths"
    branch_name = ""
    if changed_paths is None:
        branch_name = _current_git_branch(root)
        paths, git_ref, git_err = _git_diff_paths(root, base_ref)
        if git_err is not None or git_ref is None:
            errors.append(f"failed to diff against {base_ref}: {git_err}")
            paths = []
        else:
            resolved_ref = git_ref
    else:
        paths = [str(p).strip() for p in changed_paths if str(p).strip()]

    enforce_squad_frozen = (changed_paths is not None) or ("tiebreak" in branch_name.lower())
    active_frozen_exact: Iterable[str] = FROZEN_SILAS_EXACT if enforce_squad_frozen else ALWAYS_FROZEN_EXACT
    active_frozen_prefixes: Iterable[str] = FROZEN_SILAS_PREFIXES if enforce_squad_frozen else ()

    protected_hits: list[str] = []
    frozen_hits: list[str] = []
    for rel in paths:
        p_rule = _matches_path_rule(rel, prot_exact, prot_prefixes)
        if p_rule is not None:
            protected_hits.append(f"{rel} (matches protected rule {p_rule!r})")
        f_rule = _matches_path_rule(rel, active_frozen_exact, active_frozen_prefixes)
        if f_rule is not None:
            frozen_hits.append(f"{rel} (matches frozen Silas doc {f_rule!r})")

    if protected_hits:
        errors.extend(f"protected path touched: {hit}" for hit in protected_hits)
    if frozen_hits:
        errors.extend(f"frozen Silas doc touched: {hit}" for hit in frozen_hits)
    if strict and warnings:
        errors.extend(f"strict warning promoted: {w}" for w in warnings)

    passed = len(errors) == 0
    summary = (
        f"verified {len(paths)} changed path(s) vs {resolved_ref}: 0 protected, 0 frozen Silas docs"
        if passed
        else f"{len(protected_hits)} protected and {len(frozen_hits)} frozen path violation(s)"
    )
    return CheckOutcome(
        name="protected_and_frozen_paths",
        passed=passed,
        summary=summary,
        errors=errors,
        warnings=warnings,
        metrics={
            "base_ref": resolved_ref,
            "changed_count": len(paths),
            "protected_violations": len(protected_hits),
            "frozen_doc_violations": len(frozen_hits),
        },
    )


def _dotted_attr_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _is_forbidden_module_name(mod_name: str) -> str | None:
    if mod_name == "canary.world" or mod_name.startswith("canary.world."):
        return "canary.world"
    if mod_name == "canary.solver" or mod_name.startswith("canary.solver."):
        return "canary.solver"
    return None


def _collect_top_level_tainted_imports(tree: ast.Module) -> dict[str, str]:
    tainted: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                reason = _is_forbidden_module_name(alias.name)
                if reason is not None and alias.asname:
                    tainted[alias.asname] = reason
        elif isinstance(stmt, ast.ImportFrom):
            mod = stmt.module or ""
            reason = _is_forbidden_module_name(mod)
            if reason is not None:
                for alias in stmt.names:
                    bound = alias.asname or alias.name
                    tainted[bound] = f"{mod}.{alias.name}"
            elif mod == "canary":
                for alias in stmt.names:
                    if alias.name == "world":
                        tainted[alias.asname or "world"] = "canary.world"
                    elif alias.name == "solver":
                        tainted[alias.asname or "solver"] = "canary.solver"
    return tainted


def _scan_ast_block_for_leaks(
    nodes: Iterable[ast.AST],
    tainted_symbols: dict[str, str],
    owner_label: str,
    own_class_methods: set[str] | None = None,
) -> list[str]:
    violations: list[str] = []
    local_tainted = dict(tainted_symbols)

    for root_node in nodes:
        for node in ast.walk(root_node):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    reason = _is_forbidden_module_name(alias.name)
                    if reason is not None:
                        violations.append(
                            f"{owner_label}: line {node.lineno} imports forbidden {alias.name}"
                        )
                        if alias.asname:
                            local_tainted[alias.asname] = reason
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                reason = _is_forbidden_module_name(mod)
                if reason is not None:
                    violations.append(
                        f"{owner_label}: line {node.lineno} imports from forbidden {mod}"
                    )
                    for alias in node.names:
                        local_tainted[alias.asname or alias.name] = f"{mod}.{alias.name}"
                elif mod == "canary":
                    for alias in node.names:
                        if alias.name in ("world", "solver"):
                            violations.append(
                                f"{owner_label}: line {node.lineno} imports canary.{alias.name}"
                            )
                            local_tainted[alias.asname or alias.name] = f"canary.{alias.name}"

        for node in ast.walk(root_node):
            if isinstance(node, ast.Name):
                if node.id in local_tainted:
                    violations.append(
                        f"{owner_label}: line {node.lineno} references {node.id} ({local_tainted[node.id]})"
                    )
                elif node.id in ("SolverPolicy", "generate_world", "set_world_secret"):
                    violations.append(
                        f"{owner_label}: line {node.lineno} references forbidden symbol {node.id}"
                    )

            elif isinstance(node, ast.Attribute):
                dotted = _dotted_attr_name(node)
                if dotted is not None:
                    if dotted == "canary.world" or dotted.startswith("canary.world."):
                        violations.append(
                            f"{owner_label}: line {node.lineno} accesses forbidden {dotted}"
                        )
                    elif dotted == "canary.solver" or dotted.startswith("canary.solver."):
                        violations.append(
                            f"{owner_label}: line {node.lineno} accesses forbidden {dotted}"
                        )
                    else:
                        head = dotted.split(".", 1)[0]
                        if head in local_tainted and (
                            ".act" in dotted or ".belief" in dotted or local_tainted[head].startswith("canary.world")
                        ):
                            violations.append(
                                f"{owner_label}: line {node.lineno} accesses {dotted} via {local_tainted[head]}"
                            )
                if node.attr in ("_world", "generate_world", "set_world_secret"):
                    violations.append(
                        f"{owner_label}: line {node.lineno} accesses private/world attribute .{node.attr}"
                    )

            elif isinstance(node, ast.Call):
                callee_dotted = _dotted_attr_name(node.func)
                if callee_dotted in ("__import__", "importlib.import_module", "import_module"):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            sval = arg.value
                            if (
                                "canary.world" in sval
                                or "canary.solver" in sval
                                or "SolverPolicy" in sval
                            ):
                                violations.append(
                                    f"{owner_label}: line {node.lineno} dynamically imports {sval!r}"
                                )
                elif callee_dotted == "getattr" and len(node.args) >= 2:
                    attr_arg = node.args[1]
                    if isinstance(attr_arg, ast.Constant) and attr_arg.value in (
                        "_world",
                        "world",
                        "belief",
                        "SolverPolicy",
                        "generate_world",
                    ):
                        violations.append(
                            f"{owner_label}: line {node.lineno} uses getattr(..., {attr_arg.value!r})"
                        )

                if isinstance(node.func, ast.Attribute):
                    mname = node.func.attr
                    recv = node.func.value
                    is_self = isinstance(recv, ast.Name) and recv.id == "self"
                    is_super = (
                        isinstance(recv, ast.Call)
                        and isinstance(recv.func, ast.Name)
                        and recv.func.id == "super"
                    )
                    if mname == "belief":
                        if not (is_self and own_class_methods and "belief" in own_class_methods):
                            violations.append(
                                f"{owner_label}: line {node.lineno} calls .belief() at inference time"
                            )
                    elif mname == "act":
                        if not (is_self or is_super):
                            violations.append(
                                f"{owner_label}: line {node.lineno} delegates to external .act() at inference time"
                            )

    deduped: list[str] = []
    seen_v: set[str] = set()
    for v in violations:
        if v not in seen_v:
            deduped.append(v)
            seen_v.add(v)
    return deduped


def _is_inference_policy_class(cls_node: ast.ClassDef) -> bool:
    method_names = {
        n.name
        for n in cls_node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if "act" in method_names and ("reset" in method_names or cls_node.name.endswith("Policy")):
        return True
    if cls_node.name.endswith("Policy") and ("act" in method_names or "reset" in method_names):
        return True
    return False


_POLICY_AST_CACHE: dict[tuple[str, int, int], tuple[list[str], list[str]]] = {}


def _audit_policy_module_ast(rel_label: str, path: Path) -> tuple[list[str], list[str]]:
    try:
        st = path.stat()
        cache_key = (f"{rel_label}:{path.resolve()}", st.st_mtime_ns, st.st_size)
    except OSError as exc:
        return [f"{rel_label}: failed to stat AST ({exc})"], []
    cached = _POLICY_AST_CACHE.get(cache_key)
    if cached is not None:
        return list(cached[0]), list(cached[1])

    errors: list[str] = []
    checked_classes: list[str] = []
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"{rel_label}: failed to parse AST ({exc})"], []

    tainted_top = _collect_top_level_tainted_imports(tree)

    if rel_label == "train/compact_render.py":
        top_leaks = _scan_ast_block_for_leaks(tree.body, tainted_top, rel_label)
        errors.extend(top_leaks)

    top_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    top_classes: dict[str, ast.ClassDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            top_classes[node.name] = node

    policy_classes = [cls for cls in top_classes.values() if _is_inference_policy_class(cls)]
    if rel_label in MODULES_REQUIRING_POLICY_CLASS and not policy_classes:
        errors.append(f"{rel_label}: expected at least one inference Policy class with reset/act")

    for cls in policy_classes:
        checked_classes.append(f"{rel_label}:{cls.name}")
        cls_methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        non_method_nodes: list[ast.AST] = list(cls.bases) + list(cls.decorator_list)
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cls_methods[item.name] = item
            else:
                non_method_nodes.append(item)

        if "act" not in cls_methods:
            errors.append(f"{rel_label}:{cls.name}: missing act() method")
        if "reset" not in cls_methods:
            errors.append(f"{rel_label}:{cls.name}: missing reset() method")

        errors.extend(
            _scan_ast_block_for_leaks(
                non_method_nodes,
                tainted_top,
                f"{rel_label}:{cls.name}",
                own_class_methods=set(cls_methods),
            )
        )

        worklist: list[tuple[str, str, str]] = []
        visited: set[tuple[str, str, str]] = set()
        for entry_m in ("__init__", "reset", "act"):
            if entry_m in cls_methods:
                worklist.append(("method", cls.name, entry_m))

        while worklist:
            kind, scope_cls, fn_name = worklist.pop()
            if (kind, scope_cls, fn_name) in visited:
                continue
            visited.add((kind, scope_cls, fn_name))

            if kind == "method":
                target_cls = top_classes[scope_cls]
                m_map = {
                    n.name: n
                    for n in target_cls.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                fn_node = m_map[fn_name]
                label = f"{rel_label}:{scope_cls}.{fn_name}"
                own_methods = set(m_map)
            else:
                fn_node = top_funcs[fn_name]
                label = f"{rel_label}:{fn_name}"
                own_methods = None

            errors.extend(
                _scan_ast_block_for_leaks(
                    [fn_node],
                    tainted_top,
                    label,
                    own_class_methods=own_methods,
                )
            )

            for inner in ast.walk(fn_node):
                if (
                    kind == "method"
                    and isinstance(inner, ast.Attribute)
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id in ("self", scope_cls)
                ):
                    target_cls = top_classes[scope_cls]
                    for m_cand in target_cls.body:
                        if isinstance(m_cand, (ast.FunctionDef, ast.AsyncFunctionDef)) and m_cand.name == inner.attr:
                            worklist.append(("method", scope_cls, m_cand.name))
                elif isinstance(inner, ast.Name):
                    if inner.id in top_funcs:
                        worklist.append(("func", "", inner.id))
                    elif inner.id in top_classes and inner.id != cls.name:
                        helper_cls = top_classes[inner.id]
                        if not _is_inference_policy_class(helper_cls):
                            helper_non_methods = list(helper_cls.bases) + [
                                x for x in helper_cls.body if not isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                            ]
                            errors.extend(
                                _scan_ast_block_for_leaks(
                                    helper_non_methods,
                                    tainted_top,
                                    f"{rel_label}:{helper_cls.name}",
                                )
                            )
                            for h_item in helper_cls.body:
                                if isinstance(h_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    worklist.append(("method", helper_cls.name, h_item.name))

    companion_drivers = (
        "train/eval_compact_hf.py",
        "train/qwen15b_dpo_dagger.py",
        "train/qwen15b_compact_dagger.py",
        "train/compact_lora_sft.py",
        "train/frugal_raw_dagger.py",
    )
    if rel_label == "train/eval_compact_hf.py" and "run_compact_eval" in top_funcs:
        rce = top_funcs["run_compact_eval"]
        for inner in ast.walk(rce):
            if isinstance(inner, ast.Call):
                callee = _dotted_attr_name(inner.func) or ""
                if callee.endswith("CompactHFPolicy"):
                    arg_leaks = _scan_ast_block_for_leaks(
                        list(inner.args) + [kw.value for kw in inner.keywords],
                        tainted_top,
                        f"{rel_label}:run_compact_eval->CompactHFPolicy",
                    )
                    errors.extend(arg_leaks)
                elif callee.endswith((".belief", ".act")):
                    errors.append(
                        f"{rel_label}:run_compact_eval: line {inner.lineno} calls {callee} directly"
                    )
    elif not policy_classes and rel_label in companion_drivers:
        for fn_name, fn_node in top_funcs.items():
            for inner in ast.walk(fn_node):
                if isinstance(inner, ast.Call):
                    callee = _dotted_attr_name(inner.func) or ""
                    if callee.endswith(("CompactHFPolicy", "HFPolicy")):
                        arg_leaks = _scan_ast_block_for_leaks(
                            list(inner.args) + [kw.value for kw in inner.keywords],
                            tainted_top,
                            f"{rel_label}:{fn_name}->{callee}",
                        )
                        errors.extend(arg_leaks)

    _POLICY_AST_CACHE[cache_key] = (list(errors), list(checked_classes))
    return errors, checked_classes


def check_ast_inference_isolation(
    root: Path = ROOT,
    extra_paths: Iterable[Path] | None = None,
    strict: bool = False,
) -> CheckOutcome:
    errors: list[str] = []
    warnings: list[str] = []
    checked_modules: list[str] = []
    checked_classes: list[str] = []

    for rel in REQUIRED_INFERENCE_MODULES:
        p = root / rel
        if not p.is_file():
            errors.append(f"missing required inference module: {rel}")
            continue
        checked_modules.append(rel)
        mod_errs, mod_classes = _audit_policy_module_ast(rel, p)
        errors.extend(mod_errs)
        checked_classes.extend(mod_classes)

    for rel in OPTIONAL_INFERENCE_MODULES:
        p = root / rel
        if p.is_file():
            checked_modules.append(rel)
            mod_errs, mod_classes = _audit_policy_module_ast(rel, p)
            errors.extend(mod_errs)
            checked_classes.extend(mod_classes)

    if extra_paths is not None:
        for p in extra_paths:
            lbl = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            if not p.is_file():
                errors.append(f"missing extra inference module: {lbl}")
                continue
            checked_modules.append(lbl)
            mod_errs, mod_classes = _audit_policy_module_ast(lbl, p)
            errors.extend(mod_errs)
            checked_classes.extend(mod_classes)

    if strict and len(checked_classes) < 3:
        errors.append(f"expected >= 3 audited inference policy classes, found {len(checked_classes)}")

    passed = len(errors) == 0
    summary = (
        f"AST-audited {len(checked_modules)} module(s) and {len(checked_classes)} policy class(es); 0 world/solver inference leaks"
        if passed
        else f"{len(errors)} AST inference isolation violation(s)"
    )
    return CheckOutcome(
        name="ast_inference_isolation",
        passed=passed,
        summary=summary,
        errors=errors,
        warnings=warnings,
        metrics={
            "modules_checked": checked_modules,
            "policy_classes_checked": checked_classes,
        },
    )


def _expand_seed_spec(raw: Any, key_name: str = "") -> tuple[list[int] | None, str | None]:
    if _is_int(raw):
        return [int(raw)], None
    if isinstance(raw, str):
        m = SEED_RANGE_STR_RE.match(raw)
        if not m:
            return None, f"unrecognized seed range string {raw!r}"
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi or hi - lo > 250_000:
            return None, f"invalid seed range {raw!r}"
        return list(range(lo, hi + 1)), None
    if isinstance(raw, (list, tuple)):
        if not raw:
            return [], None
        if not all(_is_int(x) for x in raw):
            return None, f"non-integer entry in {key_name or 'seed list'}"
        ints = [int(x) for x in raw]
        if (
            len(ints) == 2
            and ints[0] <= ints[1]
            and (key_name.endswith("_range") or ints[1] - ints[0] > 1)
            and ints[1] - ints[0] <= 250_000
        ):
            return list(range(ints[0], ints[1] + 1)), None
        return ints, None
    if isinstance(raw, dict):
        if "seeds" in raw:
            return _expand_seed_spec(raw["seeds"], key_name)
        if "start" in raw and ("stop" in raw or "end" in raw):
            st = raw["start"]
            sp = raw.get("stop", raw.get("end"))
            if not (_is_int(st) and _is_int(sp)) or int(st) >= int(sp) or int(sp) - int(st) > 250_000:
                return None, f"invalid start/stop seed range {raw!r}"
            return list(range(int(st), int(sp))), None
        if "min" in raw and "max" in raw:
            lo, hi = raw["min"], raw["max"]
            if not (_is_int(lo) and _is_int(hi)) or int(lo) > int(hi) or int(hi) - int(lo) > 250_000:
                return None, f"invalid min/max seed range {raw!r}"
            return list(range(int(lo), int(hi) + 1)), None
    return None, f"unsupported seed specification {raw!r}"


def _walk_json_seeds(
    obj: Any,
    parent_key: str,
    rel_file: str,
    train_seeds: set[int],
    heldout_seeds: set[int],
    dev_seeds: set[int],
    all_seed_ints: set[int],
    errors: list[str],
) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if kl in ("strict_gates", "gates", "reasons", "notes", "mechanism", "impact", "fix_required"):
                continue
            if kl in TRAIN_SEED_KEYS or (kl in ("seed_range", "seeds") and parent_key in TRAIN_PARENT_SCOPES):
                parsed, err = _expand_seed_spec(v, kl)
                if err is not None or parsed is None:
                    errors.append(f"{rel_file}: invalid train seed spec at {k}: {err}")
                else:
                    train_seeds.update(parsed)
                    all_seed_ints.update(parsed)
            elif kl in DEV_EVAL_SEED_KEYS or (kl in ("eval_seed_range", "seed_range", "seeds") and parent_key in DEV_PARENT_SCOPES):
                parsed, err = _expand_seed_spec(v, kl)
                if err is not None or parsed is None:
                    errors.append(f"{rel_file}: invalid dev seed spec at {k}: {err}")
                else:
                    dev_seeds.update(parsed)
                    all_seed_ints.update(parsed)
            elif kl in HELDOUT_EVAL_SEED_KEYS or (kl in ("seed_range", "seeds") and parent_key in HELDOUT_PARENT_SCOPES):
                parsed, err = _expand_seed_spec(v, kl)
                if err is not None or parsed is None:
                    errors.append(f"{rel_file}: invalid heldout eval seed spec at {k}: {err}")
                else:
                    heldout_seeds.update(parsed)
                    all_seed_ints.update(parsed)
            elif "seed" in kl and kl not in ("seed_offset", "rng_seed", "n_seeds", "eval_seeds_per_tier", "train_seeds_unique_count"):
                if _is_int(v):
                    iv = int(v)
                    all_seed_ints.add(iv)
                    if parent_key in TRAIN_PARENT_SCOPES and kl == "seed":
                        train_seeds.add(iv)
                    elif parent_key in HELDOUT_PARENT_SCOPES and kl == "seed":
                        heldout_seeds.add(iv)
                    elif parent_key in DEV_PARENT_SCOPES and kl == "seed":
                        dev_seeds.add(iv)
                elif isinstance(v, str) and SEED_RANGE_STR_RE.match(v):
                    parsed, _ = _expand_seed_spec(v, kl)
                    if parsed:
                        all_seed_ints.update(parsed)
                elif isinstance(v, list) and v and all(_is_int(x) for x in v):
                    all_seed_ints.update(int(x) for x in v)

            next_parent = kl if kl in (TRAIN_PARENT_SCOPES | HELDOUT_PARENT_SCOPES | DEV_PARENT_SCOPES) else parent_key
            _walk_json_seeds(v, next_parent, rel_file, train_seeds, heldout_seeds, dev_seeds, all_seed_ints, errors)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_seeds(item, parent_key, rel_file, train_seeds, heldout_seeds, dev_seeds, all_seed_ints, errors)


def _recompute_paired_ci_low(deltas: list[float]) -> tuple[float, float]:
    n = len(deltas)
    mean_d = sum(deltas) / n
    if n < 2:
        return mean_d, mean_d
    var = sum((x - mean_d) ** 2 for x in deltas) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return mean_d, mean_d - half


def _audit_verified_ledger_entry(root: Path, entry: dict[str, Any], errors: list[str]) -> None:
    run_id = str(entry.get("run_id") or "unknown")
    n_val = entry.get("heldout_n", entry.get("n"))
    if not _is_int(n_val) or int(n_val) < MIN_VERIFIED_N:
        errors.append(f"ledger {run_id}: VERIFIED_IMPROVEMENT requires n >= {MIN_VERIFIED_N}, got {n_val!r}")

    b_tag = _valid_secret_tag(entry.get("before_world_secret_tag"))
    a_tag = _valid_secret_tag(entry.get("after_world_secret_tag"))
    if b_tag is None or a_tag is None:
        errors.append(
            f"ledger {run_id}: VERIFIED_IMPROVEMENT requires non-empty before/after world_secret_tag"
        )
    elif b_tag != a_tag:
        errors.append(
            f"ledger {run_id}: world_secret_tag mismatch between before ({b_tag!r}) and after ({a_tag!r})"
        )

    if entry.get("replay_verified") is not True:
        errors.append(f"ledger {run_id}: VERIFIED_IMPROVEMENT requires replay_verified == True")

    ci_low = entry.get("paired_ci95_low")
    if not _is_finite_num(ci_low) or float(ci_low) <= 0.0:
        errors.append(f"ledger {run_id}: VERIFIED_IMPROVEMENT requires paired_ci95_low > 0.0, got {ci_low!r}")

    gates = entry.get("gates")
    if not isinstance(gates, dict):
        errors.append(f"ledger {run_id}: missing gates object")
    else:
        for g_key in (
            "gate1_seed_hygiene",
            "gate2_paired_world_secret",
            "gate3_sample_and_replay",
            "gate4_paired_ci95_positive",
            "all_passed",
        ):
            if gates.get(g_key) is not True:
                errors.append(f"ledger {run_id}: {g_key} is not True")

    summary_rel = entry.get("summary_path")
    if isinstance(summary_rel, str) and summary_rel.strip():
        s_path = root / summary_rel
        if not s_path.is_file():
            errors.append(f"ledger {run_id}: backing summary_path {summary_rel!r} does not exist")
            return
        try:
            s_data = json.loads(s_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"ledger {run_id}: failed to parse {summary_rel}: {exc}")
            return

        before = s_data.get("before") if isinstance(s_data.get("before"), dict) else {}
        after = s_data.get("after") if isinstance(s_data.get("after"), dict) else {}
        paired = s_data.get("paired") if isinstance(s_data.get("paired"), dict) else {}

        sb_tag = _valid_secret_tag(before.get("world_secret_tag"))
        sa_tag = _valid_secret_tag(after.get("world_secret_tag"))
        if sb_tag is None or sa_tag is None or sb_tag != sa_tag:
            errors.append(f"{summary_rel}: unpaired or invalid before/after world_secret_tag")
        if s_data.get("replay_verified") is not True:
            errors.append(f"{summary_rel}: replay_verified is not True")
        for sc_lbl, sc_obj in (("summary", s_data), ("before", before), ("after", after)):
            if "invalid_episodes" in sc_obj and (not _is_int(sc_obj["invalid_episodes"]) or int(sc_obj["invalid_episodes"]) != 0):
                errors.append(f"{summary_rel}: {sc_lbl}.invalid_episodes must be 0")

        s_ci_low = paired.get("ci95_low", s_data.get("paired_ci95_low"))
        if not _is_finite_num(s_ci_low) or float(s_ci_low) <= 0.0:
            errors.append(f"{summary_rel}: paired ci95_low must be > 0.0, got {s_ci_low!r}")

        deltas = paired.get("deltas", s_data.get("paired_deltas"))
        if isinstance(deltas, list):
            if not deltas or not all(_is_finite_num(x) for x in deltas):
                errors.append(f"{summary_rel}: paired deltas empty or non-finite")
            else:
                if _is_int(n_val) and len(deltas) != int(n_val):
                    errors.append(f"{summary_rel}: len(deltas)={len(deltas)} != n={n_val}")
                _, recomp_low = _recompute_paired_ci_low([float(x) for x in deltas])
                if recomp_low <= 0.0:
                    errors.append(f"{summary_rel}: recomputed paired ci95_low={recomp_low:.6f} <= 0.0")


def check_seed_and_secret_provenance(root: Path = ROOT, strict: bool = False) -> CheckOutcome:
    errors: list[str] = []
    warnings: list[str] = []
    tiebreak_dir = root / "results" / "tiebreak"
    if not tiebreak_dir.is_dir():
        return CheckOutcome(
            name="seed_and_secret_provenance",
            passed=False,
            summary="missing results/tiebreak directory",
            errors=[f"missing directory: {tiebreak_dir}"],
        )

    json_files = sorted(tiebreak_dir.rglob("*.json"))
    if not json_files:
        return CheckOutcome(
            name="seed_and_secret_provenance",
            passed=False,
            summary="no JSON files under results/tiebreak",
            errors=["no JSON artifacts found under results/tiebreak"],
        )

    global_train: set[int] = set()
    global_heldout: set[int] = set()
    global_judge_leaks: set[int] = set()

    for jf in json_files:
        rel = str(jf.relative_to(root))
        try:
            payload = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: invalid JSON ({exc})")
            continue

        f_train: set[int] = set()
        f_heldout: set[int] = set()
        f_dev: set[int] = set()
        f_all_seeds: set[int] = set()
        _walk_json_seeds(payload, "", rel, f_train, f_heldout, f_dev, f_all_seeds, errors)

        bad_train = sorted(s for s in f_train if not (TRAIN_SEED_MIN <= s < TRAIN_SEED_MAX))
        if bad_train:
            errors.append(
                f"{rel}: {len(bad_train)} train_seed(s) outside [100000, 200000), sample={bad_train[:5]}"
            )

        bad_heldout = sorted(s for s in f_heldout if not (HELDOUT_SEED_MIN <= s < HELDOUT_SEED_MAX))
        if bad_heldout:
            errors.append(
                f"{rel}: {len(bad_heldout)} held-out eval_seed(s) outside [800000, 800200), sample={bad_heldout[:5]}"
            )

        bad_dev = sorted(s for s in f_dev if not (DEV_SEED_MIN <= s < DEV_SEED_MAX))
        if bad_dev:
            errors.append(
                f"{rel}: {len(bad_dev)} dev seed(s) outside DEV_SEEDS [0, 10000), sample={bad_dev[:5]}"
            )

        overlap = sorted(f_train & f_heldout)
        if overlap:
            errors.append(f"{rel}: train_seeds and eval_seeds overlap on {overlap[:5]}")

        judge_touched = sorted(s for s in (f_train | f_heldout | f_dev | f_all_seeds) if s >= JUDGE_SEED_MIN)
        if judge_touched:
            global_judge_leaks.update(judge_touched)
            errors.append(f"{rel}: JUDGE_SEEDS (900000+) touched: {judge_touched[:5]}")

        global_train.update(f_train)
        global_heldout.update(f_heldout)

    cross_overlap = sorted(global_train & global_heldout)
    if cross_overlap:
        errors.append(f"global train_seeds and held-out eval_seeds overlap: {cross_overlap[:5]}")

    ledger_path = tiebreak_dir / "experiment_ledger.json"
    verified_ids: list[str] = []
    if not ledger_path.is_file():
        errors.append("missing results/tiebreak/experiment_ledger.json")
    else:
        try:
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"results/tiebreak/experiment_ledger.json: invalid JSON ({exc})")
            ledger = {}

        runs = list(ledger.get("historical_runs") or []) + list(ledger.get("discovered_runs") or [])
        for entry in runs:
            if not isinstance(entry, dict):
                errors.append("experiment_ledger.json: non-dict run entry")
                continue
            status = entry.get("status")
            v_flag = entry.get("verified_improvement")
            if status == "VERIFIED_IMPROVEMENT" or v_flag is True:
                if status != "VERIFIED_IMPROVEMENT" or v_flag is not True:
                    errors.append(
                        f"ledger {entry.get('run_id')}: inconsistent status={status!r} vs verified_improvement={v_flag!r}"
                    )
                verified_ids.append(str(entry.get("run_id") or "unknown"))
                _audit_verified_ledger_entry(root, entry, errors)

        sc = ledger.get("summary_counts")
        if isinstance(sc, dict):
            if sc.get("verified_improvements") != len(verified_ids):
                errors.append(
                    f"experiment_ledger.json: summary_counts.verified_improvements={sc.get('verified_improvements')} != {len(verified_ids)}"
                )
            if list(sc.get("verified_run_ids") or []) != verified_ids:
                errors.append(
                    f"experiment_ledger.json: summary_counts.verified_run_ids={sc.get('verified_run_ids')} != {verified_ids}"
                )

    if strict and not verified_ids:
        warnings.append("zero VERIFIED_IMPROVEMENT runs present in experiment_ledger.json")
    if strict and warnings:
        errors.extend(f"strict warning promoted: {w}" for w in warnings)

    passed = len(errors) == 0
    summary = (
        f"scanned {len(json_files)} JSON artifact(s): {len(global_train)} train seeds in [100k,200k), "
        f"{len(global_heldout)} held-out seeds in [800k,800.2k), 0 judge seeds, {len(verified_ids)} verified run(s) valid"
        if passed
        else f"{len(errors)} seed/secret provenance violation(s)"
    )
    return CheckOutcome(
        name="seed_and_secret_provenance",
        passed=passed,
        summary=summary,
        errors=errors,
        warnings=warnings,
        metrics={
            "json_files_scanned": len(json_files),
            "unique_train_seeds": len(global_train),
            "unique_heldout_seeds": len(global_heldout),
            "judge_seed_leaks": len(global_judge_leaks),
            "verified_run_ids": verified_ids,
        },
    )


def _strip_md_code(cell: str) -> str:
    return cell.strip().replace("**", "").replace("`", "").strip()


def _parse_markdown_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    i = 0
    n = len(lines)
    while i + 1 < n:
        line = lines[i].strip()
        nxt = lines[i + 1].strip()
        if line.startswith("|") and line.endswith("|") and nxt.startswith("|") and nxt.endswith("|"):
            sep_cells = [c.strip() for c in nxt.strip("|").split("|")]
            if sep_cells and all(TABLE_SEP_CELL_RE.match(c) for c in sep_cells):
                headers = [_strip_md_code(c) for c in line.strip("|").split("|")]
                rows: list[list[str]] = []
                i += 2
                while i < n:
                    rline = lines[i].strip()
                    if not (rline.startswith("|") and rline.endswith("|")):
                        break
                    cells = [_strip_md_code(c) for c in rline.strip("|").split("|")]
                    rows.append(cells)
                    i += 1
                tables.append((headers, rows))
                continue
        i += 1
    return tables


def _extract_floats(text: str) -> list[float]:
    return [float(m.group(0)) for m in FLOAT_TOKEN_RE.finditer(text.replace(",", ""))]


def _approx_eq(a: float, b: float, tol: float = 0.002) -> bool:
    return abs(float(a) - float(b)) <= tol


def _audit_report_vs_ledger_and_forensics(root: Path, errors: list[str]) -> int:
    checked = 0
    report_path = root / "docs" / "reports" / "tiebreak_small_model.md"
    ledger_path = root / "results" / "tiebreak" / "experiment_ledger.json"
    forensics_path = root / "results" / "tiebreak" / "forensics_prior_runs.json"

    if not report_path.is_file():
        errors.append("missing docs/reports/tiebreak_small_model.md")
        return 0
    if not ledger_path.is_file():
        errors.append("missing results/tiebreak/experiment_ledger.json")
        return 0

    report_txt = report_path.read_text(encoding="utf-8")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    sc = ledger.get("summary_counts") or {}

    bullet_specs = (
        (r"Historical runs logged:\s*`?(\d+)`?", sc.get("historical_runs"), "historical_runs"),
        (r"Dynamically discovered squad runs:\s*`?(\d+)`?", sc.get("discovered_runs"), "discovered_runs"),
        (
            r"Verified improvements passing all 4 strict gates:\s*`?(\d+)`?",
            sc.get("verified_improvements"),
            "verified_improvements",
        ),
    )
    for pat, expected_val, lbl in bullet_specs:
        m = re.search(pat, report_txt)
        if not m:
            errors.append(f"tiebreak_small_model.md: missing summary count line for {lbl}")
        elif _is_int(expected_val) and int(m.group(1)) != int(expected_val):
            errors.append(
                f"tiebreak_small_model.md: {lbl} claims {m.group(1)} != ledger {expected_val}"
            )
        else:
            checked += 1

    tables = _parse_markdown_tables(report_txt)

    cal_ds = ledger.get("calibrated_v14_dataset") or {}
    cal_table = next((t for t in tables if len(t[0]) >= 11 and t[0][0].lower() == "split"), None)
    if cal_table is None:
        errors.append("tiebreak_small_model.md: missing Canonical Calibrated v1.4 Dataset table")
    else:
        for row in cal_table[1]:
            if len(row) < 11:
                continue
            split_cell, tier_cell = row[0].lower(), row[1].lower()
            split_key = "train" if "train" in split_cell else ("val" if "val" in split_cell else "")
            if not split_key or split_key not in cal_ds:
                continue
            split_obj = cal_ds[split_key]
            if tier_cell in ("easy", "medium", "hard"):
                src_obj = (split_obj.get("tiers") or {}).get(tier_cell) or {}
                exp_nat_ep = src_obj.get("natural_episodes")
            else:
                src_obj = split_obj
                tiers_map = split_obj.get("tiers") or {}
                exp_nat_ep = sum(int(v.get("natural_episodes", 0)) for v in tiers_map.values())

            int_pairs = (
                (row[2], exp_nat_ep, "natural_episodes"),
                (row[3], src_obj.get("correct_accusations"), "correct_accusations"),
                (row[4], src_obj.get("natural_abstentions"), "natural_abstentions"),
                (row[5], src_obj.get("augmented_abstentions"), "augmented_abstentions"),
                (row[6], src_obj.get("rejected_wrong_accusations"), "rejected_wrong_accusations"),
                (row[7], src_obj.get("sft_records_written"), "sft_records_written"),
                (row[8], src_obj.get("dpo_pairs"), "dpo_pairs"),
            )
            for cell_txt, exp_int, field_lbl in int_pairs:
                if _is_int(exp_int):
                    if int(cell_txt) != int(exp_int):
                        errors.append(
                            f"tiebreak_small_model.md dataset {split_key}/{tier_cell} {field_lbl}: {cell_txt} != {exp_int}"
                        )
                    else:
                        checked += 1
            for cell_txt, exp_flt, field_lbl in (
                (row[9], src_obj.get("mean_top_p_at_accuse"), "mean_top_p_at_accuse"),
                (row[10], src_obj.get("mean_top_p_at_abstain"), "mean_top_p_at_abstain"),
            ):
                if _is_finite_num(exp_flt):
                    if not _approx_eq(float(cell_txt), float(exp_flt), 0.001):
                        errors.append(
                            f"tiebreak_small_model.md dataset {split_key}/{tier_cell} {field_lbl}: {cell_txt} != {exp_flt}"
                        )
                    else:
                        checked += 1

    for split_key, mf_name in (("train", "cal_v14_train_manifest.json"), ("val", "cal_v14_val_manifest.json")):
        mf_path = root / "results" / "tiebreak" / mf_name
        if mf_path.is_file() and split_key in cal_ds:
            mf = json.loads(mf_path.read_text(encoding="utf-8"))
            for k_cmp in ("sft_records_written", "dpo_pairs", "correct_accusations", "augmented_abstentions"):
                if mf.get(k_cmp) != cal_ds[split_key].get(k_cmp):
                    errors.append(
                        f"{mf_name}: {k_cmp}={mf.get(k_cmp)} disagrees with experiment_ledger.json ({cal_ds[split_key].get(k_cmp)})"
                    )
                else:
                    checked += 1

    run_table = next((t for t in tables if len(t[0]) >= 8 and t[0][0].lower() == "run id"), None)
    all_runs = list(ledger.get("historical_runs") or []) + list(ledger.get("discovered_runs") or [])
    runs_by_id = {str(r.get("run_id")): r for r in all_runs if isinstance(r, dict)}
    if run_table is None:
        errors.append("tiebreak_small_model.md: missing Complete Tiebreaker Experiment Ledger table")
    else:
        seen_ids: set[str] = set()
        for row in run_table[1]:
            if len(row) < 8:
                continue
            rid = row[0]
            seen_ids.add(rid)
            if rid not in runs_by_id:
                errors.append(f"tiebreak_small_model.md: table row {rid!r} missing from experiment_ledger.json")
                continue
            entry = runs_by_id[rid]
            if int(row[3]) != int(entry.get("heldout_n", -1)):
                errors.append(
                    f"tiebreak_small_model.md {rid}: heldout_n {row[3]} != ledger {entry.get('heldout_n')}"
                )
            else:
                checked += 1

            if row[7] != str(entry.get("status")):
                errors.append(
                    f"tiebreak_small_model.md {rid}: status {row[7]!r} != ledger {entry.get('status')!r}"
                )
            else:
                checked += 1

            score_nums = _extract_floats(row[4])
            if _is_finite_num(entry.get("before_mean_score")) and _is_finite_num(entry.get("after_mean_score")):
                if len(score_nums) < 2 or not (
                    _approx_eq(score_nums[0], float(entry["before_mean_score"]), 0.002)
                    and _approx_eq(score_nums[1], float(entry["after_mean_score"]), 0.002)
                ):
                    errors.append(
                        f"tiebreak_small_model.md {rid}: score cell {row[4]!r} disagrees with ledger "
                        f"{entry.get('before_mean_score')} -> {entry.get('after_mean_score')}"
                    )
                else:
                    checked += 2
                if _is_finite_num(entry.get("paired_ci95_low")) and "delta" in row[4]:
                    if len(score_nums) < 5 or not (
                        _approx_eq(score_nums[2], float(entry["paired_mean_delta"]), 0.002)
                        and _approx_eq(score_nums[3], float(entry["paired_ci95_low"]), 0.002)
                        and _approx_eq(score_nums[4], float(entry["paired_ci95_high"]), 0.002)
                    ):
                        errors.append(
                            f"tiebreak_small_model.md {rid}: delta/CI in {row[4]!r} disagrees with ledger"
                        )
                    else:
                        checked += 3

            vc_nums = _extract_floats(row[5])
            if _is_finite_num(entry.get("before_valid_call_rate")) and _is_finite_num(entry.get("after_valid_call_rate")):
                if len(vc_nums) < 2 or not (
                    _approx_eq(vc_nums[0], float(entry["before_valid_call_rate"]), 0.015)
                    and _approx_eq(vc_nums[1], float(entry["after_valid_call_rate"]), 0.015)
                ):
                    errors.append(
                        f"tiebreak_small_model.md {rid}: valid call rate {row[5]!r} disagrees with ledger"
                    )
                else:
                    checked += 2

        missing_ids = sorted(set(runs_by_id) - seen_ids)
        if missing_ids:
            errors.append(f"tiebreak_small_model.md: missing ledger run(s) in table: {missing_ids}")

    if forensics_path.is_file():
        forensics = json.loads(forensics_path.read_text(encoding="utf-8"))
        wm = (forensics.get("ws4_v2_root_cause") or {}).get("window_model") or {}
        for f_key in ("header_tokens", "max_len_tokens", "body_budget_tokens"):
            f_val = wm.get(f_key)
            if _is_int(f_val):
                formatted = f"{int(f_val):,}"
                if formatted not in report_txt and str(int(f_val)) not in report_txt:
                    errors.append(
                        f"tiebreak_small_model.md: forensic {f_key}={f_val} missing from diagnosis text"
                    )
                else:
                    checked += 1
        sec_audit = forensics.get("unpaired_secret_audit") or {}
        for s_key in ("eval_44411_base_sha256", "eval_44412_v2_sha256"):
            sha = sec_audit.get(s_key)
            if isinstance(sha, str) and sha:
                if sha not in report_txt and sha[:8] not in report_txt:
                    errors.append(f"tiebreak_small_model.md: forensic secret {sha} missing from report")
                else:
                    checked += 1

    forensics_md = root / "results" / "tiebreak" / "forensics_prior_runs.md"
    if forensics_md.is_file() and forensics_path.is_file():
        f_txt = forensics_md.read_text(encoding="utf-8")
        forensics = json.loads(forensics_path.read_text(encoding="utf-8"))
        rc_all = (forensics.get("ws4_v2_root_cause") or {}).get("overall") or {}
        for num_k, den_k in (
            ("below_breakeven_count", "accused_episodes"),
            ("p_le_005_count", "accused_episodes"),
            ("accused_is_argmax_count", "accused_episodes"),
        ):
            if _is_int(rc_all.get(num_k)) and _is_int(rc_all.get(den_k)):
                tok = f"{rc_all[num_k]}/{rc_all[den_k]}"
                if tok not in f_txt:
                    errors.append(f"forensics_prior_runs.md: missing ratio {tok} for {num_k}")
                else:
                    checked += 1

    return checked


def _audit_scaling_table(table_path: Path, summary_path: Path, errors: list[str]) -> int:
    checked = 0
    md_txt = table_path.read_text(encoding="utf-8")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tables = _parse_markdown_tables(md_txt)
    if len(tables) < 4:
        errors.append(f"{table_path.name}: expected 4 markdown tables in scaling report, found {len(tables)}")
        return 0

    sha12 = str(summary.get("world_secret_sha256_12") or "")
    if sha12 and sha12 not in md_txt:
        errors.append(f"scaling/table.md: missing world_secret_sha256_12 {sha12!r}")
    else:
        checked += 1

    curve_by_key: dict[str, dict[str, Any]] = {
        str(int(r["n_train"])): r for r in (summary.get("scaling_curve") or [])
    }
    if isinstance(summary.get("solver_reference"), dict):
        curve_by_key["solver (ref)"] = summary["solver_reference"]

    for row in tables[0][1]:
        key = row[0]
        if key not in curve_by_key:
            errors.append(f"scaling/table.md Part A: unexpected row {key!r}")
            continue
        ref = curve_by_key[key]
        m = ref["metrics"]
        sc_nums = _extract_floats(row[2])
        if int(row[1]) != int(m["n"]):
            errors.append(f"scaling/table.md Part A {key}: n_eval {row[1]} != {m['n']}")
        elif len(sc_nums) < 2 or not (
            _approx_eq(sc_nums[0], m["mean_score"], 0.002) and _approx_eq(sc_nums[1], m["ci95"], 0.002)
        ):
            errors.append(f"scaling/table.md Part A {key}: score/CI {row[2]!r} disagrees with scaling_summary.json")
        elif not _approx_eq(float(row[3]), m["luck_adjusted_ev"], 0.002):
            errors.append(f"scaling/table.md Part A {key}: luck-adj EV {row[3]} != {m['luck_adjusted_ev']}")
        elif not _approx_eq(float(row[4]), m["accuracy"], 0.002):
            errors.append(f"scaling/table.md Part A {key}: accuracy {row[4]} != {m['accuracy']}")
        elif row[10] != f"{ref['replay_verified']}/{m['n']}":
            errors.append(f"scaling/table.md Part A {key}: replay cell {row[10]!r} mismatch")
        else:
            checked += 5

    for row in tables[1][1]:
        key = row[0]
        if key not in curve_by_key:
            errors.append(f"scaling/table.md Part A by_tier: unexpected row {key!r}")
            continue
        bt = curve_by_key[key].get("by_tier") or {}
        for t_idx, tier_name in enumerate(("easy", "medium", "hard")):
            tm = (bt.get(tier_name) or {}).get("metrics") or {}
            sc_nums = _extract_floats(row[1 + t_idx])
            if len(sc_nums) < 2 or not (
                _approx_eq(sc_nums[0], tm["mean_score"], 0.002)
                and _approx_eq(sc_nums[1], tm["ci95"], 0.002)
            ):
                errors.append(f"scaling/table.md Part A by_tier {key}/{tier_name}: score mismatch")
            elif not _approx_eq(float(row[4 + t_idx]), tm["accuracy"], 0.012):
                errors.append(f"scaling/table.md Part A by_tier {key}/{tier_name}: accuracy mismatch")
            else:
                checked += 2
        hm = (bt.get("hard") or {}).get("metrics") or {}
        if not _approx_eq(float(row[7]), hm["luck_adjusted_ev"], 0.002):
            errors.append(f"scaling/table.md Part A by_tier {key}/hard: luck-adj EV mismatch")
        else:
            checked += 1

    cat_keys = (
        "calibrated_win",
        "lucky_win",
        "unlucky_noise_loss",
        "premature_gamble_loss",
        "horizon_gamble_loss",
        "calibrated_abstain",
        "missed_commit_abstain",
        "protocol_or_cap_stall",
    )
    for row in tables[2][1]:
        key = row[0]
        if key not in curve_by_key:
            continue
        counts = curve_by_key[key]["counts"]
        for idx, ck in enumerate(cat_keys, start=1):
            if int(row[idx]) != int(counts[ck]):
                errors.append(f"scaling/table.md taxonomy {key} {ck}: {row[idx]} != {counts[ck]}")
            else:
                checked += 1

    cross_map = {(r["agent"], r["tier"]): r for r in (summary.get("cross_model_v14") or [])}
    for row in tables[3][1]:
        ck = (row[0], row[1])
        if ck not in cross_map:
            errors.append(f"scaling/table.md cross-model: unknown row {ck}")
            continue
        ref = cross_map[ck]
        m = ref["metrics"]
        sc_nums = _extract_floats(row[3])
        if int(row[2]) != int(ref["n"]):
            errors.append(f"scaling/table.md cross-model {ck}: n {row[2]} != {ref['n']}")
        elif len(sc_nums) < 2 or not (
            _approx_eq(sc_nums[0], m["mean_score"], 0.002) and _approx_eq(sc_nums[1], m["ci95"], 0.002)
        ):
            errors.append(f"scaling/table.md cross-model {ck}: score/CI {row[3]!r} mismatch")
        elif not _approx_eq(float(row[4]), m["luck_adjusted_ev"], 0.002):
            errors.append(f"scaling/table.md cross-model {ck}: luck-adj EV {row[4]} != {m['luck_adjusted_ev']}")
        else:
            checked += 3
        for idx, cat in enumerate(cat_keys, start=5):
            if int(row[idx]) != int(ref["counts"][cat]):
                errors.append(f"scaling/table.md cross-model {ck} {cat}: {row[idx]} != {ref['counts'][cat]}")
            else:
                checked += 1

    return checked


def _audit_empirical_bayes_table(table_path: Path, summary_path: Path, errors: list[str]) -> int:
    checked = 0
    md_txt = table_path.read_text(encoding="utf-8")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tables = _parse_markdown_tables(md_txt)
    if len(tables) < 5:
        errors.append(f"empirical_bayes/table.md: expected >= 5 markdown tables, found {len(tables)}")
        return 0

    tot_rep = summary.get("total_episodes_replayed")
    if _is_int(tot_rep):
        if str(tot_rep) not in md_txt:
            errors.append(f"empirical_bayes/table.md: missing total_episodes_replayed={tot_rep}")
        else:
            checked += 1

    params = summary.get("parameters") or {}
    heldout_main = summary.get("heldout") or {}
    heldout_n90 = summary.get("heldout_n90") or {}
    dev_agents = (summary.get("dev_hard") or {}).get("agents") or {}
    search_ledger = ((summary.get("training") or {}).get("stage3") or {}).get("search_ledger") or []

    for headers, rows in tables:
        if not headers or not rows:
            continue
        col_idx = {h.strip(): i for i, h in enumerate(headers)}

        if "w_canary_hit" in col_idx:
            for row in rows:
                st = row[0]
                if st not in params:
                    errors.append(f"empirical_bayes/table.md params: unknown stage {st!r}")
                    continue
                p = params[st]
                for pk in ("w_canary_hit", "w_canary_miss", "w_doc_hit", "w_after_hours", "w_evasive", "w_angry_msg"):
                    idx = col_idx[pk]
                    if not _approx_eq(float(row[idx]), float(p[pk]), 0.002):
                        errors.append(f"empirical_bayes/table.md {st}.{pk}: {row[idx]} != {p[pk]}")
                    else:
                        checked += 1
        elif headers[0] == "Tier" and "n" in col_idx and "Score [95% Bootstrap CI]" in col_idx:
            n_col = col_idx["n"]
            sc_col = col_idx["Score [95% Bootstrap CI]"]
            for row in rows:
                tier, ag = row[0], row[1]
                row_n = int(row[n_col])
                bt_src = (
                    (heldout_n90.get("by_tier") or {})
                    if (row_n == 30 and heldout_n90 and heldout_main.get("n_per_tier") != 30)
                    else (heldout_main.get("by_tier") or {})
                )
                ref = (bt_src.get(tier) or {}).get(ag)
                if not isinstance(ref, dict):
                    errors.append(f"empirical_bayes/table.md by_tier: missing ({tier}, {ag}) for n={row_n}")
                    continue
                sc_nums = _extract_floats(row[sc_col])
                if row_n != int(ref["n"]) or len(sc_nums) < 3 or not _approx_eq(sc_nums[0], ref["score"]["mean"], 0.002):
                    errors.append(f"empirical_bayes/table.md by_tier ({tier}, {ag}): cell {row[sc_col]!r} mismatch")
                else:
                    checked += 2
        elif headers[0] == "Scope" and "Comparison (After - Before)" in col_idx:
            sd_col = col_idx["Score Delta [95% CI]"]
            ed_col = col_idx["Luck-Adjusted EV Delta [95% CI]"]
            for row in rows:
                scope_cell, cmp_cell = row[0], row[1]
                cmp_key = cmp_cell.replace(" - ", "_minus_").strip()
                use_n90 = scope_cell.startswith("subset") or (
                    "(n=30)" in scope_cell and bool(heldout_n90) and heldout_main.get("n_per_tier") != 30
                )
                p_deltas = (heldout_n90 if use_n90 else heldout_main).get("paired_deltas") or {}
                if scope_cell.startswith(("overall", "subset")):
                    ref_d = (p_deltas.get("overall") or {}).get(cmp_key)
                else:
                    tier_name = scope_cell.split()[0].strip()
                    ref_d = ((p_deltas.get("by_tier") or {}).get(tier_name) or {}).get(cmp_key)
                if not isinstance(ref_d, dict):
                    errors.append(f"empirical_bayes/table.md paired_deltas: missing ({scope_cell}, {cmp_key})")
                    continue
                sd_nums = _extract_floats(row[sd_col])
                ed_nums = _extract_floats(row[ed_col])
                if len(sd_nums) < 3 or not (
                    _approx_eq(sd_nums[0], ref_d["score_delta"]["mean"], 0.002)
                    and _approx_eq(sd_nums[1], ref_d["score_delta"]["ci95_low"], 0.002)
                    and _approx_eq(sd_nums[2], ref_d["score_delta"]["ci95_high"], 0.002)
                ):
                    errors.append(f"empirical_bayes/table.md paired_deltas ({scope_cell}, {cmp_cell}): score delta mismatch")
                elif len(ed_nums) < 3 or not _approx_eq(ed_nums[0], ref_d["luck_adjusted_delta"]["mean"], 0.002):
                    errors.append(f"empirical_bayes/table.md paired_deltas ({scope_cell}, {cmp_cell}): EV delta mismatch")
                else:
                    checked += 4
        elif headers[0] == "Phase" and "Train Mean Score" in col_idx:
            sc_col = col_idx["Train Mean Score"]
            if len(rows) != len(search_ledger):
                errors.append(f"empirical_bayes/table.md stage3 search_ledger: {len(rows)} rows != {len(search_ledger)}")
            else:
                for row, sref in zip(rows, search_ledger):
                    if row[0] != sref["phase"] or not _approx_eq(float(row[sc_col]), sref["mean_score"], 0.002):
                        errors.append(f"empirical_bayes/table.md stage3 search_ledger {row[0]}: score mismatch")
                    else:
                        checked += 2
        elif headers[0].startswith(("Agent", "Stage")) and "n" in col_idx and "Score [95% Bootstrap CI]" in col_idx:
            n_col = col_idx["n"]
            sc_col = col_idx["Score [95% Bootstrap CI]"]
            ev_col = col_idx["Luck-Adjusted EV [95% CI]"]
            acc_col = col_idx["Accuracy"]
            sample_n = int(rows[0][n_col])
            if sample_n == 30 and dev_agents:
                src_map = dev_agents
                scope_tag = "dev_hard"
            elif sample_n == 90 and heldout_n90 and heldout_main.get("n_total_per_agent") != 90:
                src_map = heldout_n90.get("overall") or {}
                scope_tag = "heldout_n90"
            else:
                src_map = heldout_main.get("overall") or {}
                scope_tag = "overall"
            for row in rows:
                ag = row[0]
                if ag not in src_map:
                    errors.append(f"empirical_bayes/table.md {scope_tag}: unknown agent {ag!r}")
                    continue
                ref = src_map[ag]
                sc_nums = _extract_floats(row[sc_col])
                ev_nums = _extract_floats(row[ev_col])
                if int(row[n_col]) != int(ref["n"]):
                    errors.append(f"empirical_bayes/table.md {scope_tag} {ag}: n {row[n_col]} != {ref['n']}")
                elif len(sc_nums) < 3 or not (
                    _approx_eq(sc_nums[0], ref["score"]["mean"], 0.002)
                    and _approx_eq(sc_nums[1], ref["score"]["ci95_low"], 0.002)
                    and _approx_eq(sc_nums[2], ref["score"]["ci95_high"], 0.002)
                ):
                    errors.append(f"empirical_bayes/table.md {scope_tag} {ag}: score cell {row[sc_col]!r} mismatch")
                elif len(ev_nums) < 3 or not (
                    _approx_eq(ev_nums[0], ref["luck_adjusted_ev"]["mean"], 0.002)
                    and _approx_eq(ev_nums[1], ref["luck_adjusted_ev"]["ci95_low"], 0.002)
                    and _approx_eq(ev_nums[2], ref["luck_adjusted_ev"]["ci95_high"], 0.002)
                ):
                    errors.append(f"empirical_bayes/table.md {scope_tag} {ag}: EV cell {row[ev_col]!r} mismatch")
                elif not _approx_eq(float(row[acc_col]), ref["accuracy"], 0.002):
                    errors.append(f"empirical_bayes/table.md {scope_tag} {ag}: accuracy {row[acc_col]} != {ref['accuracy']}")
                else:
                    checked += 7

    return checked


def _audit_generic_summary_table(table_path: Path, summary_path: Path, errors: list[str]) -> int:
    checked = 0
    md_txt = table_path.read_text(encoding="utf-8")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    all_floats = _extract_floats(md_txt)
    before = summary.get("before") if isinstance(summary.get("before"), dict) else {}
    after = summary.get("after") if isinstance(summary.get("after"), dict) else {}
    paired = summary.get("paired") if isinstance(summary.get("paired"), dict) else {}

    for lbl, val in (
        ("before.mean_score", before.get("mean_score")),
        ("after.mean_score", after.get("mean_score")),
        ("paired.mean_delta", paired.get("mean_delta", summary.get("paired_mean_delta"))),
        ("paired.ci95_low", paired.get("ci95_low", summary.get("paired_ci95_low"))),
    ):
        if _is_finite_num(val):
            target = float(val)
            if not any(_approx_eq(x, target, 0.002) for x in all_floats):
                errors.append(
                    f"{table_path.name}: {lbl}={target:.4f} from {summary_path.name} not found in markdown table"
                )
            else:
                checked += 1
    return checked


def check_claim_number_audit(root: Path = ROOT, strict: bool = False) -> CheckOutcome:
    errors: list[str] = []
    warnings: list[str] = []
    claims_checked = _audit_report_vs_ledger_and_forensics(root, errors)

    tiebreak_dir = root / "results" / "tiebreak"
    table_files = sorted(tiebreak_dir.rglob("table.md")) if tiebreak_dir.is_dir() else []
    if not table_files:
        errors.append("no results/tiebreak/**/table.md files found")

    for tf in table_files:
        rel = str(tf.relative_to(root))
        parent = tf.parent
        if parent.name == "scaling" and (parent / "scaling_summary.json").is_file():
            claims_checked += _audit_scaling_table(tf, parent / "scaling_summary.json", errors)
        elif parent.name == "empirical_bayes" and (parent / "summary.json").is_file():
            claims_checked += _audit_empirical_bayes_table(tf, parent / "summary.json", errors)
        else:
            candidates = sorted(
                p for p in parent.glob("*.json") if p.name == "summary.json" or p.name.endswith("_summary.json")
            )
            if not candidates:
                msg = f"{rel}: missing backing summary.json in {parent.relative_to(root)}"
                if strict:
                    errors.append(msg)
                else:
                    errors.append(msg)
            else:
                claims_checked += _audit_generic_summary_table(tf, candidates[0], errors)

    passed = len(errors) == 0
    summary = (
        f"cross-checked {claims_checked} numeric claim(s) across tiebreak_small_model.md and {len(table_files)} table.md file(s)"
        if passed
        else f"{len(errors)} numeric claim mismatch(es) across markdown reports and JSON artifacts"
    )
    return CheckOutcome(
        name="claim_number_audit",
        passed=passed,
        summary=summary,
        errors=errors,
        warnings=warnings,
        metrics={
            "claims_checked": claims_checked,
            "table_files_checked": [str(t.relative_to(root)) for t in table_files],
        },
    )


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not PREREG_RE.search(raw_line):
            continue
        if not SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = NEGATED_PREREG_RE.sub("", raw_line)
        if PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


def _git_tracked_under(root: Path, rel_dirs: tuple[str, ...]) -> list[str] | None:
    proc = subprocess.run(
        ["git", "ls-files", "--", *rel_dirs],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def check_hygiene_and_panel_fix_a(
    root: Path = ROOT,
    tracked_paths: Iterable[str] | None = None,
    strict: bool = False,
) -> CheckOutcome:
    errors: list[str] = []
    warnings: list[str] = []

    md_targets: list[Path] = []
    report_md = root / "docs" / "reports" / "tiebreak_small_model.md"
    if report_md.is_file():
        md_targets.append(report_md)
    else:
        errors.append("missing docs/reports/tiebreak_small_model.md")

    for opt_md_name in ("tiebreak_vs_frontier.md", "tiebreak_panel_e_addendum.md"):
        opt_md = root / "docs" / "reports" / opt_md_name
        if opt_md.is_file():
            md_targets.append(opt_md)

    tiebreak_dir = root / "results" / "tiebreak"
    if tiebreak_dir.is_dir():
        md_targets.extend(sorted(tiebreak_dir.rglob("*.md")))

    json_targets = sorted(tiebreak_dir.rglob("*.json")) if tiebreak_dir.is_dir() else []

    em_dash_hits = 0
    prereg_hits = 0
    for md_file in md_targets:
        rel = str(md_file.relative_to(root))
        txt = md_file.read_text(encoding="utf-8")
        cnt_em = txt.count(EM_DASH)
        if cnt_em > 0:
            em_dash_hits += cnt_em
            errors.append(f"{rel}: contains {cnt_em} em dash(es) (\\u2014)")
        cnt_en = txt.count(EN_DASH)
        if cnt_en > 0:
            warnings.append(f"{rel}: contains {cnt_en} en dash(es) (\\u2013)")
        bad_lines = _has_affirmative_prereg_0_29(txt)
        for bl in bad_lines:
            prereg_hits += 1
            errors.append(f"{rel}: Panel Fix A violation (pre-registered claim on seeds 0-29) at {bl}")

    for jf in json_targets:
        rel = str(jf.relative_to(root))
        txt = jf.read_text(encoding="utf-8")
        bad_lines = _has_affirmative_prereg_0_29(txt)
        for bl in bad_lines:
            prereg_hits += 1
            errors.append(f"{rel}: Panel Fix A violation (pre-registered claim on seeds 0-29) at {bl}")

    scan_dirs = ("results/tiebreak", "train")
    candidate_rel_paths: set[str] = set()
    if tracked_paths is not None:
        for p in tracked_paths:
            sp = str(p).strip().removeprefix("./")
            if sp.startswith(("results/tiebreak/", "train/")):
                candidate_rel_paths.add(sp)
    else:
        git_listed = _git_tracked_under(root, scan_dirs)
        if git_listed is not None:
            candidate_rel_paths.update(git_listed)

    for d_rel in scan_dirs:
        d_path = root / d_rel
        if d_path.is_dir():
            for f in d_path.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    candidate_rel_paths.add(str(f.relative_to(root)))

    weight_violations = 0
    size_violations = 0
    for rel in sorted(candidate_rel_paths):
        fpath = root / rel
        suf = Path(rel).suffix.lower()
        if suf in FORBIDDEN_WEIGHT_SUFFIXES:
            weight_violations += 1
            errors.append(f"{rel}: forbidden model weight artifact ({suf})")
        if fpath.is_file():
            sz = fpath.stat().st_size
            if sz > MAX_FILE_BYTES:
                size_violations += 1
                errors.append(f"{rel}: oversized file ({sz} bytes > {MAX_FILE_BYTES} bytes)")

    owned_py = (
        root / "scripts" / "verify_tiebreak_submission.py",
        root / "scripts" / "tiebreak_scaling_calibration.py",
        root / "scripts" / "tiebreak_addendum_pack.py",
        root / "scripts" / "tiebreak_vs_frontier_comparison.py",
        root / "tests" / "test_verify_tiebreak_submission.py",
        root / "tests" / "test_tiebreak_scaling_calibration.py",
        root / "tests" / "test_tiebreak_addendum_pack.py",
        root / "tests" / "test_tiebreak_vs_frontier.py",
    )
    for py_path in owned_py:
        if py_path.is_file():
            src = py_path.read_text(encoding="utf-8")
            rel = str(py_path.relative_to(root))
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
            if any(t.type == tokenize.COMMENT for t in toks) or HASH_CHAR in src:
                errors.append(f"{rel}: contains Python comment token or hash character")
            if EM_DASH in src:
                errors.append(f"{rel}: contains em dash")

    if strict and warnings:
        errors.extend(f"strict warning promoted: {w}" for w in warnings)

    passed = len(errors) == 0
    summary = (
        f"verified {len(md_targets)} markdown doc(s) and {len(candidate_rel_paths)} tiebreak/train file(s): "
        "0 em dashes, 0 seeds 0-29 pre-reg claims, 0 weights or >5MB files"
        if passed
        else f"{len(errors)} hygiene / Panel Fix A violation(s)"
    )
    return CheckOutcome(
        name="hygiene_and_panel_fix_a",
        passed=passed,
        summary=summary,
        errors=errors,
        warnings=warnings,
        metrics={
            "markdown_files_checked": len(md_targets),
            "files_scanned_for_weights_and_size": len(candidate_rel_paths),
            "em_dash_hits": em_dash_hits,
            "prereg_0_29_hits": prereg_hits,
            "weight_violations": weight_violations,
            "size_violations": size_violations,
        },
    )


def run_all_checks(
    root: Path = ROOT,
    base_ref: str = "origin/justSilas",
    strict: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    outcomes = [
        check_protected_and_frozen_paths(root=root, base_ref=base_ref, strict=strict),
        check_ast_inference_isolation(root=root, strict=strict),
        check_seed_and_secret_provenance(root=root, strict=strict),
        check_claim_number_audit(root=root, strict=strict),
        check_hygiene_and_panel_fix_a(root=root, strict=strict),
    ]
    elapsed = round(time.perf_counter() - t0, 4)
    runtime_ok = elapsed <= MAX_RUNTIME_SECONDS
    global_errors: list[str] = []
    if strict and not runtime_ok:
        global_errors.append(
            f"verifier runtime {elapsed:.4f}s exceeded {MAX_RUNTIME_SECONDS:.1f}s offline budget"
        )

    all_passed = all(o.passed for o in outcomes) and len(global_errors) == 0
    return {
        "schema": "canary.tiebreak.submission_gate.v1",
        "passed": all_passed,
        "strict": strict,
        "base_ref": base_ref,
        "elapsed_seconds": elapsed,
        "checks_passed": sum(1 for o in outcomes if o.passed),
        "checks_total": len(outcomes),
        "global_errors": global_errors,
        "checks": {o.name: o.to_dict() for o in outcomes},
    }


def format_human_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    mode = "STRICT" if report["strict"] else "STANDARD"
    verdict = "PASS" if report["passed"] else "FAIL"
    lines.append(
        f"TIEBREAK SUBMISSION GATE [{mode}]: {verdict} "
        f"({report['checks_passed']}/{report['checks_total']} checks in {report['elapsed_seconds']:.3f}s)"
    )
    for name in CHECK_NAMES:
        chk = report["checks"][name]
        tag = "PASS" if chk["passed"] else "FAIL"
        lines.append(f"  [{tag}] {name}: {chk['summary']}")
        for err in chk["errors"]:
            lines.append(f"         ERROR: {err}")
        for warn in chk["warnings"]:
            lines.append(f"         WARN:  {warn}")
    for g_err in report.get("global_errors") or []:
        lines.append(f"  [FAIL] runtime_budget: {g_err}")
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Offline judge-grade submission verifier and provenance gate for Canary tiebreak."
    )
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON verdict.")
    ap.add_argument("--strict", action="store_true", help="Promote warnings and runtime budget to hard failures.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root directory.")
    ap.add_argument("--base-ref", default="origin/justSilas", help="Base git ref for protected/frozen diff check.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = run_all_checks(root=args.root.resolve(), base_ref=args.base_ref, strict=args.strict)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human_report(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
