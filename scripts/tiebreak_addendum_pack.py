"""Deterministic Panel Fix E tiebreak addendum pack generator and offline verifier."""
from __future__ import annotations

import argparse
import ast
import glob
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

MD_H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

TRAIN_SEED_MIN = 100_000
TRAIN_SEED_MAX = 200_000
HELDOUT_SEED_MIN = 800_000
HELDOUT_SEED_MAX = 800_200
MIN_PAIRED_N = 30

CRITERION_NAMES: tuple[str, ...] = (
    "heldout_mean_gt_zero",
    "paired_delta_ci95_gt_zero",
    "train_eval_disjoint",
    "replay_and_zero_errors",
    "autonomous_inference",
)

CRITERIA_DEFINITIONS: dict[str, str] = {
    "heldout_mean_gt_zero": (
        "after.mean_score > 0.0 and after_ci95_low > 0.0 (from explicit after CI, "
        "after scores, nested held-out CI, or paired deltas under deterministic zero before)"
    ),
    "paired_delta_ci95_gt_zero": (
        "paired.ci95_low > 0.0 under identical non-placeholder world_secret_tag on "
        "HELDOUT_SEEDS [800000, 800200)"
    ),
    "train_eval_disjoint": (
        "train seed set strictly in [100000, 200000) and disjoint from held-out eval "
        "seed set in [800000, 800200)"
    ),
    "replay_and_zero_errors": (
        "n >= 30, replay_verified is True, and invalid_episodes == 0"
    ),
    "autonomous_inference": (
        "AST-verified zero canary.solver or canary.world imports or calls on inference paths"
    ),
}

README_PUBLISHED_BASELINE: tuple[dict[str, Any], ...] = (
    {
        "row_id": "base",
        "label": "base (untrained)",
        "architecture": "Open-weight LLM (Qwen2.5-1.5B)",
        "mean_score": 0.000,
        "ci95": None,
        "n": 36,
        "note": "cannot play: 3% valid tool calls; per-process world secret",
    },
    {
        "row_id": "v2",
        "label": "v2 (SFT on solver play)",
        "architecture": "Open-weight LLM (Qwen2.5-1.5B LoRA)",
        "mean_score": -0.457,
        "ci95": 0.086,
        "n": 172,
        "note": "two-sample; blind accusations under 4k header crowding",
    },
    {
        "row_id": "v3_4k",
        "label": "v3-4k (GRPO on environment reward, Verda H100)",
        "architecture": "Open-weight LLM (Qwen2.5-1.5B LoRA)",
        "mean_score": -0.147,
        "ci95": 0.063,
        "n": 180,
        "note": "two-sample; +0.310 +/- 0.107 vs v2, 100% valid calls",
    },
    {
        "row_id": "v3_8k_s2",
        "label": "v3-8k seed 2 (GRPO, 8k context, Verda H100 spot)",
        "architecture": "Open-weight LLM (Qwen2.5-1.5B LoRA)",
        "mean_score": -0.050,
        "ci95": 0.049,
        "n": 90,
        "note": "two-sample; 93% abstention, 95% CI [-0.099, -0.001] below 0",
    },
)

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

ERROR_EPISODE_KEYS: tuple[str, ...] = (
    "invalid_episodes",
    "error_episodes",
    "invalid_or_error_episodes",
    "invalid_episodes_counted_as_zero",
    "errors_counted_as_zero",
    "n_excluded",
)

SEED_RANGE_STR_RE = re.compile(r"^\s*(-?\d+)\s*(?:\.\.|-)\s*(-?\d+)\s*$")
PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _mean_ci95(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean_v = sum(xs) / n
    if n < 2:
        return mean_v, 0.0
    var = sum((x - mean_v) ** 2 for x in xs) / (n - 1)
    sd = math.sqrt(max(0.0, var))
    return mean_v, 1.96 * sd / math.sqrt(n)


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


def _expand_seed_spec(raw: Any, is_range_key: bool = False) -> tuple[list[int] | None, str | None]:
    if raw is None:
        return None, "missing seed specification"
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
            return None, "seed list is empty"
        if not all(_is_int(x) for x in raw):
            return None, "non-integer entry in seed list"
        ints = [int(x) for x in raw]
        if is_range_key and len(ints) == 2 and ints[0] <= ints[1] and ints[1] - ints[0] <= 250_000:
            return list(range(ints[0], ints[1] + 1)), None
        return ints, None
    if isinstance(raw, dict):
        if "seeds" in raw:
            return _expand_seed_spec(raw["seeds"], is_range_key=is_range_key)
        if "start" in raw and ("stop" in raw or "end" in raw):
            st = raw["start"]
            sp = raw.get("stop", raw.get("end"))
            if not (_is_int(st) and _is_int(sp)):
                return None, "seed range start/stop must be integers"
            if int(st) >= int(sp) or int(sp) - int(st) > 250_000:
                return None, f"invalid start/stop seed range [{st}, {sp})"
            return list(range(int(st), int(sp))), None
        if "min" in raw and "max" in raw:
            lo = raw["min"]
            hi = raw["max"]
            if not (_is_int(lo) and _is_int(hi)):
                return None, "seed min/max must be integers"
            if int(lo) > int(hi) or int(hi) - int(lo) > 250_000:
                return None, f"invalid min/max seed range [{lo}, {hi}]"
            return list(range(int(lo), int(hi) + 1)), None
    return None, f"unsupported seed specification {raw!r}"


def _extract_seeds_from_summary(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[list[int] | None, str | None, list[int] | None, str | None]:
    train_candidates: list[tuple[Any, bool]] = [
        (summary.get("train_seeds"), False),
        (after.get("train_seeds"), False),
        (summary.get("train_seed_range"), True),
        (after.get("train_seed_range"), True),
    ]
    train_seeds: list[int] | None = None
    train_err: str | None = "missing train_seeds"
    for cand, is_rng in train_candidates:
        if cand is not None:
            train_seeds, train_err = _expand_seed_spec(cand, is_range_key=is_rng)
            break

    eval_candidates: list[tuple[Any, bool]] = [
        (summary.get("eval_seeds"), False),
        (after.get("eval_seeds"), False),
        (before.get("eval_seeds"), False),
        (summary.get("heldout_seeds"), False),
        (summary.get("eval_seed_range"), True),
        (summary.get("heldout_seed_range"), True),
        (after.get("eval_seed_range"), True),
    ]
    eval_seeds: list[int] | None = None
    eval_err: str | None = "missing eval_seeds"
    for cand, is_rng in eval_candidates:
        if cand is not None:
            eval_seeds, eval_err = _expand_seed_spec(cand, is_range_key=is_rng)
            break

    return train_seeds, train_err, eval_seeds, eval_err


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
                        violations.append(f"{owner_label}: line {node.lineno} imports forbidden {alias.name}")
                        if alias.asname:
                            local_tainted[alias.asname] = reason
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                reason = _is_forbidden_module_name(mod)
                if reason is not None:
                    violations.append(f"{owner_label}: line {node.lineno} imports from forbidden {mod}")
                    for alias in node.names:
                        local_tainted[alias.asname or alias.name] = f"{mod}.{alias.name}"
                elif mod == "canary":
                    for alias in node.names:
                        if alias.name in ("world", "solver"):
                            violations.append(f"{owner_label}: line {node.lineno} imports canary.{alias.name}")
                            local_tainted[alias.asname or alias.name] = f"canary.{alias.name}"

        for node in ast.walk(root_node):
            if isinstance(node, ast.Name):
                if node.id in local_tainted:
                    violations.append(
                        f"{owner_label}: line {node.lineno} references {node.id} ({local_tainted[node.id]})"
                    )
                elif node.id in ("SolverPolicy", "generate_world", "set_world_secret"):
                    violations.append(f"{owner_label}: line {node.lineno} references forbidden symbol {node.id}")
            elif isinstance(node, ast.Attribute):
                dotted = _dotted_attr_name(node)
                if dotted is not None:
                    if dotted == "canary.world" or dotted.startswith("canary.world."):
                        violations.append(f"{owner_label}: line {node.lineno} accesses forbidden {dotted}")
                    elif dotted == "canary.solver" or dotted.startswith("canary.solver."):
                        violations.append(f"{owner_label}: line {node.lineno} accesses forbidden {dotted}")
                    else:
                        head = dotted.split(".", 1)[0]
                        if head in local_tainted and (
                            ".act" in dotted or ".belief" in dotted or local_tainted[head].startswith("canary.world")
                        ):
                            violations.append(
                                f"{owner_label}: line {node.lineno} accesses {dotted} via {local_tainted[head]}"
                            )
                if node.attr in ("_world", "generate_world", "set_world_secret"):
                    violations.append(f"{owner_label}: line {node.lineno} accesses private/world attribute .{node.attr}")
            elif isinstance(node, ast.Call):
                callee_dotted = _dotted_attr_name(node.func)
                if callee_dotted in ("__import__", "importlib.import_module", "import_module"):
                    for arg in node.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            sval = arg.value
                            if "canary.world" in sval or "canary.solver" in sval or "SolverPolicy" in sval:
                                violations.append(f"{owner_label}: line {node.lineno} dynamically imports {sval!r}")
                elif callee_dotted == "getattr" and len(node.args) >= 2:
                    attr_arg = node.args[1]
                    if isinstance(attr_arg, ast.Constant) and attr_arg.value in (
                        "_world",
                        "world",
                        "belief",
                        "SolverPolicy",
                        "generate_world",
                    ):
                        violations.append(f"{owner_label}: line {node.lineno} uses getattr(..., {attr_arg.value!r})")

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
                            violations.append(f"{owner_label}: line {node.lineno} calls .belief() at inference time")
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


_AST_AUDIT_CACHE: dict[tuple[str, int, int], tuple[list[str], list[str]]] = {}


def audit_inference_module_ast(rel_label: str, path: Path) -> tuple[list[str], list[str]]:
    try:
        st = path.stat()
        cache_key = (f"{rel_label}:{path.resolve()}", st.st_mtime_ns, st.st_size)
    except OSError as exc:
        return [f"{rel_label}: failed to stat AST module ({exc})"], []
    cached = _AST_AUDIT_CACHE.get(cache_key)
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
    if rel_label.endswith("compact_render.py"):
        errors.extend(_scan_ast_block_for_leaks(tree.body, tainted_top, rel_label))

    top_funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    top_classes: dict[str, ast.ClassDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            top_classes[node.name] = node

    policy_classes = [cls for cls in top_classes.values() if _is_inference_policy_class(cls)]
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

    if rel_label.endswith("eval_compact_hf.py") and "run_compact_eval" in top_funcs:
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
                    errors.append(f"{rel_label}:run_compact_eval: line {inner.lineno} calls {callee} directly")

    if not policy_classes and not rel_label.endswith("eval_compact_hf.py") and tainted_top:
        errors.append(
            f"{rel_label}: top-level solver/world imports {sorted(tainted_top.values())} without isolated Policy class"
        )

    _AST_AUDIT_CACHE[cache_key] = (list(errors), list(checked_classes))
    return errors, checked_classes


def classify_policy_track(summary: dict[str, Any], summary_path: str = "") -> dict[str, Any]:
    arch = summary.get("policy_architecture") if isinstance(summary.get("policy_architecture"), dict) else {}
    identity_parts = [
        str(summary.get("model") or ""),
        str(summary.get("policy") or ""),
        str(summary.get("agent") or ""),
        str(summary.get("run_id") or ""),
        str(arch.get("type") or ""),
        Path(summary_path).parent.name if summary_path else "",
    ]
    blob = " ".join(identity_parts).lower()

    if any(tok in blob for tok in ("empiricalbayes", "empirical_bayes", "empirical-bayes")):
        return {
            "track": "track_2",
            "track_label": "Track 2: Compact Parametric / Empirical-Bayes Policies",
            "family": "EmpiricalBayesPolicy",
            "subfamily": "compact_parametric",
            "architecture_label": "Non-LLM parametric (EmpiricalBayesPolicy)",
            "is_open_weight_llm": False,
        }

    if any(
        tok in blob
        for tok in (
            "compactlineardagger",
            "compact_linear_dagger",
            "compact-linear-dagger",
            "lineardagger",
            "linear_dagger",
            "linear-dagger",
        )
    ):
        return {
            "track": "track_2",
            "track_label": "Track 2: Compact Parametric / Empirical-Bayes Policies",
            "family": "CompactLinearDAggerPolicy",
            "subfamily": "compact_parametric",
            "architecture_label": "Non-LLM parametric (CompactLinearDAggerPolicy)",
            "is_open_weight_llm": False,
        }

    if any(
        tok in blob
        for tok in (
            "scalinglogistic",
            "scaling_logistic",
            "scaling-logistic",
            "compactlinearpolicy",
            "compact_linear_logistic_softmax",
            "tiebreak_scaling_calibration",
        )
    ) or (Path(summary_path).parent.name == "scaling" and "qwen" not in blob and "mlp" not in blob):
        return {
            "track": "track_2",
            "track_label": "Track 2: Compact Parametric / Empirical-Bayes Policies",
            "family": "ScalingLogisticPolicy",
            "subfamily": "compact_parametric",
            "architecture_label": "Non-LLM parametric (ScalingLogisticPolicy, 82 params)",
            "is_open_weight_llm": False,
        }

    if any(tok in blob for tok in ("tinymlp", "tiny_mlp", "tiny-mlp", "neural_mlp", "neural-mlp", "neuralmlp", "mlppolicy")):
        return {
            "track": "track_1",
            "track_label": "Track 1: Open-Weight LLM / Neural Policies",
            "family": "TinyMLP",
            "subfamily": "neural_mlp",
            "architecture_label": "Compact neural MLP (non-LLM)",
            "is_open_weight_llm": False,
        }

    if any(tok in blob for tok in ("qwen", "compact-hf", "compact_hf", "frugal_raw_dagger", "frugal-raw")):
        if "0.5b" in blob or "05b" in blob:
            fam = "Qwen2.5-0.5B"
        elif "1.5b" in blob or "15b" in blob:
            fam = "Qwen2.5-1.5B"
        else:
            fam = "Qwen2.5-1.5B"
        return {
            "track": "track_1",
            "track_label": "Track 1: Open-Weight LLM / Neural Policies",
            "family": fam,
            "subfamily": "open_weight_llm",
            "architecture_label": f"Open-weight LLM ({fam} LoRA)",
            "is_open_weight_llm": True,
        }

    return {
        "track": "unclassified",
        "track_label": "Unclassified Policy",
        "family": "UnknownPolicy",
        "subfamily": "unknown",
        "architecture_label": "Unclassified policy",
        "is_open_weight_llm": False,
    }


def _resolve_inference_modules(
    repo_root: Path,
    summary: dict[str, Any],
    summary_path: str,
    track_info: dict[str, Any],
) -> tuple[list[tuple[str, Path]], list[str]]:
    explicit_raw: list[str] = []
    if isinstance(summary.get("inference_modules"), list):
        explicit_raw.extend(str(x) for x in summary["inference_modules"] if str(x).strip())
    for single_k in ("inference_module", "policy_module"):
        val = summary.get(single_k)
        if isinstance(val, str) and val.strip():
            explicit_raw.append(val.strip())

    rel_candidates: list[str] = []
    if explicit_raw:
        rel_candidates.extend(explicit_raw)
    else:
        fam = track_info["family"]
        blob = " ".join([
            str(summary.get("run_id") or ""),
            str(summary.get("model") or ""),
            summary_path,
        ]).lower()
        if fam == "EmpiricalBayesPolicy":
            rel_candidates.append("train/empirical_bayes_policy.py")
        elif fam == "ScalingLogisticPolicy":
            rel_candidates.append("scripts/tiebreak_scaling_calibration.py")
        elif fam == "CompactLinearDAggerPolicy":
            if (repo_root / "train" / "compact_linear_dagger.py").is_file():
                rel_candidates.append("train/compact_linear_dagger.py")
            else:
                rel_candidates.append("scripts/tiebreak_scaling_calibration.py")
        elif fam == "TinyMLP":
            rel_candidates.append("train/neural_mlp_tiebreak.py")
        elif track_info["subfamily"] == "open_weight_llm":
            if ("raw" in blob or "frugal" in blob or "eval_hf" in blob) and "compact" not in blob:
                rel_candidates.append("train/eval_hf.py")
                if (repo_root / "train" / "frugal_raw_dagger.py").is_file():
                    rel_candidates.append("train/frugal_raw_dagger.py")
            else:
                rel_candidates.extend(["train/compact_render.py", "train/eval_compact_hf.py"])
                for opt_rel in ("train/compact_lora_sft.py", "train/qwen15b_compact_dagger.py"):
                    stem = Path(opt_rel).stem.lower()
                    if (repo_root / opt_rel).is_file() and (stem in blob or stem.replace("_", "-") in blob):
                        rel_candidates.append(opt_rel)

    resolved: list[tuple[str, Path]] = []
    errors: list[str] = []
    seen: set[Path] = set()
    for raw_p in rel_candidates:
        cand = Path(raw_p)
        full = cand.resolve() if cand.is_absolute() else (repo_root / cand).resolve()
        try:
            lbl = str(full.relative_to(repo_root.resolve()))
        except ValueError:
            lbl = str(cand)
        if not full.is_file():
            errors.append(f"missing inference module {lbl}")
            continue
        if full not in seen:
            seen.add(full)
            resolved.append((lbl, full))

    if not resolved and not errors:
        errors.append("no inference module resolved for policy")
    return resolved, errors


def _normalize_scaling_summary(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("schema") != "canary.tiebreak.scaling_calibration.v1":
        return None
    curve = raw.get("scaling_curve")
    if not isinstance(curve, list) or len(curve) < 2:
        return None
    c0 = next((c for c in curve if isinstance(c, dict) and c.get("n_train") == 0), None)
    trained_points = [c for c in curve if isinstance(c, dict) and _is_int(c.get("n_train")) and int(c["n_train"]) > 0]
    if c0 is None or not trained_points:
        return None
    c_max = max(trained_points, key=lambda c: int(c["n_train"]))

    m0 = c0.get("metrics") if isinstance(c0.get("metrics"), dict) else {}
    m_max = c_max.get("metrics") if isinstance(c_max.get("metrics"), dict) else {}
    counts0 = c0.get("counts") if isinstance(c0.get("counts"), dict) else {}
    counts_max = c_max.get("counts") if isinstance(c_max.get("counts"), dict) else {}

    n0 = m0.get("n")
    n_max = m_max.get("n")
    sha12 = str(raw.get("world_secret_sha256_12") or "").strip()
    secret_tag = f"sha256:{sha12}" if len(sha12) >= 6 else None

    b_rv = bool(c0.get("all_replay_verified") is True and c0.get("replay_verified") == n0)
    a_rv = bool(c_max.get("all_replay_verified") is True and c_max.get("replay_verified") == n_max)
    b_stall = int(counts0.get("protocol_or_cap_stall", 0)) if _is_int(counts0.get("protocol_or_cap_stall", 0)) else 1
    a_stall = (
        int(counts_max.get("protocol_or_cap_stall", 0))
        if _is_int(counts_max.get("protocol_or_cap_stall", 0))
        else 1
    )

    deterministic_zero_before = (
        _is_int(n0)
        and m0.get("mean_score") == 0.0
        and m0.get("ci95") == 0.0
        and m0.get("commit_count") == 0
        and counts0.get("calibrated_abstain") == n0
    )
    after_mean = float(m_max["mean_score"]) if _is_finite_num(m_max.get("mean_score")) else None
    after_hw = float(m_max["ci95"]) if _is_finite_num(m_max.get("ci95")) else None
    after_lo = round(after_mean - after_hw, 6) if (after_mean is not None and after_hw is not None) else None
    after_hi = round(after_mean + after_hw, 6) if (after_mean is not None and after_hw is not None) else None

    paired_block: dict[str, Any] = {}
    if deterministic_zero_before and after_mean is not None and after_lo is not None and after_hi is not None:
        paired_block = {
            "mean_delta": round(after_mean, 6),
            "ci95_low": after_lo,
            "ci95_high": after_hi,
        }

    n_params = (raw.get("policy_architecture") or {}).get("n_parameters", 82)
    return {
        "run_id": "scaling-logistic-v14",
        "model": f"ScalingLogisticPolicy (CompactLinearPolicy, {n_params} params, N_train={c_max['n_train']})",
        "tiers_version": str(raw.get("tiers_version") or "v1.4"),
        "tiers": list(raw.get("tiers") or ["easy", "medium", "hard"]),
        "n": n_max,
        "train_seed_range": raw.get("train_seed_range"),
        "eval_seed_range": raw.get("eval_seeds"),
        "replay_verified": bool(b_rv and a_rv),
        "invalid_episodes": b_stall + a_stall,
        "inference_module": "scripts/tiebreak_scaling_calibration.py",
        "before": {
            "n": n0,
            "mean_score": m0.get("mean_score"),
            "ci95": m0.get("ci95"),
            "commit_count": m0.get("commit_count"),
            "valid_call_rate": 1.0 if b_stall == 0 else None,
            "world_secret_tag": secret_tag,
            "replay_verified": b_rv,
            "invalid_episodes": b_stall,
            "deterministic": deterministic_zero_before,
        },
        "after": {
            "n": n_max,
            "mean_score": after_mean,
            "ci95": after_hw,
            "ci95_low": after_lo,
            "ci95_high": after_hi,
            "valid_call_rate": 1.0 if a_stall == 0 else None,
            "world_secret_tag": secret_tag,
            "replay_verified": a_rv,
            "invalid_episodes": a_stall,
        },
        "paired": paired_block,
        "notes": (
            f"Pure-NumPy {n_params}-parameter linear/logistic-softmax control trained on "
            f"N_train={c_max['n_train']} TRAIN_SEEDS episodes vs N_train=0 untrained policy."
        ),
    }


def _check_zero_error_episodes(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    explicit_zero_found = False

    for scope_name, obj in (("summary", summary), ("before", before), ("after", after)):
        for key in ERROR_EPISODE_KEYS:
            if key in obj:
                val = obj[key]
                if not _is_int(val) or int(val) != 0:
                    reasons.append(f"{scope_name}.{key}={val!r} (must be integer 0)")
                else:
                    explicit_zero_found = True

        end_reasons = obj.get("end_reasons")
        if isinstance(end_reasons, dict):
            for bad_reason in ("error", "invalid"):
                bad_cnt = end_reasons.get(bad_reason, 0)
                if not _is_int(bad_cnt) or int(bad_cnt) != 0:
                    reasons.append(f"{scope_name}.end_reasons[{bad_reason!r}]={bad_cnt!r} (must be 0)")
            if not reasons:
                explicit_zero_found = True

        eps = obj.get("episodes")
        if isinstance(eps, list):
            for idx, ep in enumerate(eps):
                if not isinstance(ep, dict):
                    reasons.append(f"{scope_name}.episodes[{idx}] is not a dict")
                    continue
                er = ep.get("end_reason")
                meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
                if er in ("error", "invalid") or ep.get("valid") is False or meta.get("valid") is False:
                    reasons.append(f"{scope_name}.episodes[{idx}] is invalid/error (end_reason={er!r})")

    if not explicit_zero_found:
        reasons.append("missing explicit zero invalid/error episode accounting (invalid_episodes=0)")

    return len(reasons) == 0, reasons


def _is_before_deterministic_constant(before: dict[str, Any]) -> tuple[bool, float | None]:
    b_scores = before.get("scores")
    if isinstance(b_scores, list) and b_scores and all(_is_finite_num(x) for x in b_scores):
        vals = [float(x) for x in b_scores]
        if max(vals) - min(vals) == 0.0:
            return True, vals[0]

    b_mean = float(before["mean_score"]) if _is_finite_num(before.get("mean_score")) else None
    if b_mean is None:
        return False, None

    if before.get("deterministic") is True:
        return True, b_mean
    for zero_hw_key in ("ci95", "score_ci95", "ci95_halfwidth", "std"):
        if _is_finite_num(before.get(zero_hw_key)) and float(before[zero_hw_key]) == 0.0:
            return True, b_mean
    if (
        _is_finite_num(before.get("ci95_low"))
        and _is_finite_num(before.get("ci95_high"))
        and float(before["ci95_low"]) == float(before["ci95_high"])
    ):
        return True, b_mean

    if b_mean == 0.0:
        for zero_acc_key in ("accuse_rate", "accused_rate", "accused_count", "commit_count"):
            if _is_finite_num(before.get(zero_acc_key)) and float(before[zero_acc_key]) == 0.0:
                return True, 0.0
        end_r = before.get("end_reasons")
        if isinstance(end_r, dict) and end_r.get("accused", 0) == 0:
            return True, 0.0

    return False, None


def _extract_after_score_and_ci(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    paired_mean_delta: float | None,
    paired_ci95_low: float | None,
    paired_ci95_high: float | None,
    paired_deltas: list[float] | None,
    expected_n: int | None,
) -> tuple[float | None, float | None, float | None, str, list[str]]:
    reasons: list[str] = []

    after_scores: list[float] | None = None
    if isinstance(after.get("scores"), list):
        raw_s = after["scores"]
        if raw_s and all(_is_finite_num(x) for x in raw_s):
            after_scores = [float(x) for x in raw_s]
        else:
            reasons.append("after.scores is empty or contains non-finite values")
    elif isinstance(after.get("episodes"), list) and after["episodes"]:
        ep_s = [ep.get("score") for ep in after["episodes"] if isinstance(ep, dict)]
        if len(ep_s) == len(after["episodes"]) and all(_is_finite_num(x) for x in ep_s):
            after_scores = [float(x) for x in ep_s]

    computed_mean: float | None = None
    computed_low: float | None = None
    computed_high: float | None = None
    if after_scores is not None:
        if expected_n is not None and len(after_scores) != expected_n:
            reasons.append(f"len(after.scores)={len(after_scores)} != n ({expected_n})")
        cm, chw = _mean_ci95(after_scores)
        computed_mean = round(cm, 6)
        computed_low = round(cm - chw, 6)
        computed_high = round(cm + chw, 6)

    reported_mean: float | None = None
    after_score_obj = after.get("score") if isinstance(after.get("score"), dict) else {}
    by_tier_all = ((after.get("by_tier") or {}).get("all")) if isinstance(after.get("by_tier"), dict) else {}
    if not isinstance(by_tier_all, dict):
        by_tier_all = {}

    for cand in (
        after.get("mean_score"),
        after_score_obj.get("mean"),
        by_tier_all.get("mean_score"),
        summary.get("after_mean_score"),
    ):
        if _is_finite_num(cand):
            reported_mean = float(cand)
            break

    mean_score = computed_mean if computed_mean is not None else reported_mean
    if computed_mean is not None and reported_mean is not None and abs(computed_mean - reported_mean) > 0.015:
        reasons.append(
            f"reported after.mean_score ({reported_mean:.4f}) disagrees with after.scores mean ({computed_mean:.4f})"
        )

    explicit_low: float | None = None
    explicit_high: float | None = None
    source = "missing"

    score_ci_list = after.get("score_ci", by_tier_all.get("score_ci"))
    for lo_cand, hi_cand, src_lbl in (
        (after.get("ci95_low"), after.get("ci95_high"), "explicit_after_ci95_low"),
        (after.get("score_ci_lo"), after.get("score_ci_hi"), "explicit_after_score_ci_lo"),
        (after.get("ci_low"), after.get("ci_high"), "explicit_after_ci_low"),
        (after_score_obj.get("ci95_low"), after_score_obj.get("ci95_high"), "explicit_after_score_dict"),
        (by_tier_all.get("score_ci_lo"), by_tier_all.get("score_ci_hi"), "explicit_after_by_tier_all"),
        (summary.get("after_ci95_low"), summary.get("after_ci95_high"), "explicit_summary_after_ci95_low"),
    ):
        if _is_finite_num(lo_cand):
            explicit_low = float(lo_cand)
            explicit_high = float(hi_cand) if _is_finite_num(hi_cand) else None
            source = src_lbl
            break

    if explicit_low is None and isinstance(score_ci_list, list) and len(score_ci_list) == 2:
        if _is_finite_num(score_ci_list[0]) and _is_finite_num(score_ci_list[1]):
            explicit_low = float(score_ci_list[0])
            explicit_high = float(score_ci_list[1])
            source = "explicit_after_score_ci_pair"

    if explicit_low is None and mean_score is not None:
        for hw_cand, src_lbl in (
            (after.get("ci95"), "after_ci95_halfwidth"),
            (after.get("score_ci95"), "after_score_ci95_halfwidth"),
            (after.get("ci95_halfwidth"), "after_ci95_halfwidth"),
            (after_score_obj.get("ci95_halfwidth"), "after_score_dict_halfwidth"),
            (by_tier_all.get("score_ci95"), "after_by_tier_halfwidth"),
            (summary.get("after_ci95"), "summary_after_ci95_halfwidth"),
        ):
            if _is_finite_num(hw_cand) and float(hw_cand) >= 0.0:
                hw = float(hw_cand)
                explicit_low = mean_score - hw
                explicit_high = mean_score + hw
                source = src_lbl
                break

    if explicit_low is None and mean_score is not None:
        heldout_overall = ((summary.get("heldout") or {}).get("overall")) if isinstance(summary.get("heldout"), dict) else None
        if isinstance(heldout_overall, dict):
            preferred_agent = str(after.get("agent") or after.get("variant") or "eb_experience_opt")
            candidates_ho: list[tuple[str, Any]] = []
            if preferred_agent in heldout_overall:
                candidates_ho.append((preferred_agent, heldout_overall[preferred_agent]))
            candidates_ho.extend((k, v) for k, v in heldout_overall.items() if k != preferred_agent)
            for ag_name, ag_obj in candidates_ho:
                if ag_name == "solver" or not isinstance(ag_obj, dict):
                    continue
                sc_obj = ag_obj.get("score")
                if isinstance(sc_obj, dict) and _is_finite_num(sc_obj.get("mean")) and _is_finite_num(sc_obj.get("ci95_low")):
                    if abs(float(sc_obj["mean"]) - mean_score) <= 1e-4 and (
                        expected_n is None or ag_obj.get("n") == expected_n
                    ):
                        explicit_low = float(sc_obj["ci95_low"])
                        explicit_high = float(sc_obj["ci95_high"]) if _is_finite_num(sc_obj.get("ci95_high")) else None
                        source = f"nested_heldout_overall:{ag_name}"
                        break

    if computed_low is None and explicit_low is None:
        b_scores_raw = before.get("scores")
        if (
            isinstance(b_scores_raw, list)
            and paired_deltas is not None
            and len(b_scores_raw) == len(paired_deltas)
            and len(b_scores_raw) > 0
            and all(_is_finite_num(x) for x in b_scores_raw)
        ):
            reconstructed = [float(b) + float(d) for b, d in zip(b_scores_raw, paired_deltas)]
            rm, rhw = _mean_ci95(reconstructed)
            computed_mean = computed_mean if computed_mean is not None else round(rm, 6)
            mean_score = mean_score if mean_score is not None else computed_mean
            computed_low = round(rm - rhw, 6)
            computed_high = round(rm + rhw, 6)
            source = "reconstructed_before_scores_plus_deltas"
        else:
            det_before, const_b = _is_before_deterministic_constant(before)
            if det_before and const_b is not None:
                if paired_deltas is not None and len(paired_deltas) > 0:
                    reconstructed = [const_b + d for d in paired_deltas]
                    rm, rhw = _mean_ci95(reconstructed)
                    mean_score = mean_score if mean_score is not None else round(rm, 6)
                    computed_low = round(rm - rhw, 6)
                    computed_high = round(rm + rhw, 6)
                    source = "paired_deltas_deterministic_before"
                elif paired_ci95_low is not None and paired_mean_delta is not None:
                    mean_score = mean_score if mean_score is not None else round(const_b + paired_mean_delta, 6)
                    explicit_low = round(const_b + paired_ci95_low, 6)
                    explicit_high = round(const_b + paired_ci95_high, 6) if paired_ci95_high is not None else None
                    source = "paired_ci95_deterministic_before"

    if computed_low is not None and explicit_low is not None:
        ci95_low: float | None = min(computed_low, explicit_low)
        ci95_high: float | None = computed_high if computed_high is not None else explicit_high
        source = f"min(after_scores,{source})"
    elif computed_low is not None:
        ci95_low = computed_low
        ci95_high = computed_high
        if source == "missing":
            source = "after_scores"
    else:
        ci95_low = explicit_low
        ci95_high = explicit_high

    if mean_score is None:
        reasons.append("missing after.mean_score")
    if ci95_low is None:
        reasons.append(
            "missing after_ci95_low (provide after.ci95_low, after.ci95, after.scores, or deterministic before with paired deltas)"
        )
    elif mean_score is not None and ci95_low > mean_score + 1e-7:
        reasons.append(f"invalid after CI: after_ci95_low ({ci95_low:.4f}) > after.mean_score ({mean_score:.4f})")

    return (
        round(mean_score, 6) if mean_score is not None else None,
        round(ci95_low, 6) if ci95_low is not None else None,
        round(ci95_high, 6) if ci95_high is not None else None,
        source,
        reasons,
    )


def _extract_paired_delta_and_ci(
    summary: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    expected_n: int | None,
) -> tuple[float | None, float | None, float | None, list[float] | None, list[str]]:
    reasons: list[str] = []
    paired = summary.get("paired") if isinstance(summary.get("paired"), dict) else {}

    deltas: list[float] | None = None
    if isinstance(summary.get("paired_deltas"), list):
        raw_d = summary["paired_deltas"]
        if raw_d and all(_is_finite_num(x) for x in raw_d):
            deltas = [float(x) for x in raw_d]
        else:
            reasons.append("paired_deltas is empty or contains non-finite values")
    elif isinstance(paired.get("deltas"), list):
        raw_d = paired["deltas"]
        if raw_d and all(_is_finite_num(x) for x in raw_d):
            deltas = [float(x) for x in raw_d]
        else:
            reasons.append("paired.deltas is empty or contains non-finite values")
    elif isinstance(before.get("scores"), list) and isinstance(after.get("scores"), list):
        b_s = before["scores"]
        a_s = after["scores"]
        if len(b_s) != len(a_s) or not b_s:
            reasons.append("before.scores and after.scores must be non-empty and equal length")
        elif not (all(_is_finite_num(x) for x in b_s) and all(_is_finite_num(x) for x in a_s)):
            reasons.append("before.scores or after.scores contain non-finite values")
        else:
            deltas = [float(a) - float(b) for b, a in zip(b_s, a_s)]

    computed_mean: float | None = None
    computed_low: float | None = None
    computed_high: float | None = None
    if deltas is not None:
        if expected_n is not None and len(deltas) != expected_n:
            reasons.append(f"len(paired.deltas)={len(deltas)} != n ({expected_n})")
        dm, dhw = _mean_ci95(deltas)
        computed_mean = round(dm, 6)
        computed_low = round(dm - dhw, 6)
        computed_high = round(dm + dhw, 6)

    reported_mean: float | None = None
    for cand in (
        paired.get("mean_delta"),
        paired.get("delta_mean"),
        paired.get("mean"),
        paired.get("mean_score_delta"),
        summary.get("paired_mean_delta"),
        summary.get("mean_delta"),
    ):
        if _is_finite_num(cand):
            reported_mean = float(cand)
            break

    if reported_mean is None and _is_finite_num(before.get("mean_score")) and _is_finite_num(after.get("mean_score")):
        reported_mean = float(after["mean_score"]) - float(before["mean_score"])

    reported_low: float | None = None
    reported_high: float | None = None
    for cand in (
        paired.get("ci95_low"),
        paired.get("score_delta_ci_lo"),
        paired.get("ci_low"),
        summary.get("paired_ci95_low"),
        summary.get("delta_ci95_low"),
    ):
        if _is_finite_num(cand):
            reported_low = float(cand)
            break

    for cand in (
        paired.get("ci95_high"),
        paired.get("score_delta_ci_hi"),
        paired.get("ci_high"),
        summary.get("paired_ci95_high"),
        summary.get("delta_ci95_high"),
    ):
        if _is_finite_num(cand):
            reported_high = float(cand)
            break

    if reported_low is None and reported_mean is not None:
        for hw_cand in (paired.get("ci95"), paired.get("score_delta_ci95")):
            if _is_finite_num(hw_cand) and float(hw_cand) >= 0.0:
                hw = float(hw_cand)
                reported_low = reported_mean - hw
                reported_high = reported_mean + hw
                break

    mean_delta = computed_mean if computed_mean is not None else reported_mean
    if computed_mean is not None and reported_mean is not None and abs(computed_mean - reported_mean) > 0.015:
        reasons.append(
            f"reported paired.mean_delta ({reported_mean:.4f}) disagrees with deltas mean ({computed_mean:.4f})"
        )

    if (
        mean_delta is not None
        and _is_finite_num(before.get("mean_score"))
        and _is_finite_num(after.get("mean_score"))
    ):
        diff_means = float(after["mean_score"]) - float(before["mean_score"])
        if abs(diff_means - mean_delta) > 0.015:
            reasons.append(
                f"after.mean_score - before.mean_score ({diff_means:.4f}) disagrees with mean_delta ({mean_delta:.4f})"
            )

    if computed_low is not None and reported_low is not None:
        ci95_low: float | None = min(computed_low, reported_low)
    elif computed_low is not None:
        ci95_low = computed_low
    else:
        ci95_low = reported_low

    ci95_high = computed_high if computed_high is not None else reported_high

    if mean_delta is None or ci95_low is None:
        reasons.append("missing paired.ci95_low or paired.deltas")
    elif ci95_low > mean_delta + 1e-7:
        reasons.append(f"invalid paired CI: ci95_low ({ci95_low:.4f}) > mean_delta ({mean_delta:.4f})")

    return (
        round(mean_delta, 6) if mean_delta is not None else None,
        round(ci95_low, 6) if ci95_low is not None else None,
        round(ci95_high, 6) if ci95_high is not None else None,
        deltas,
        reasons,
    )


def evaluate_run_summary(
    raw_summary: dict[str, Any],
    summary_path: str,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    normalized = _normalize_scaling_summary(raw_summary)
    summary = normalized if normalized is not None else raw_summary

    fallback_id = Path(summary_path).parent.name if summary_path else "unnamed_run"
    run_id = str(summary.get("run_id") or fallback_id)
    model = str(summary.get("model") or summary.get("policy") or summary.get("agent") or "unknown")
    tiers_version = str(summary.get("tiers_version") or "v1.4")
    raw_tiers = summary.get("tiers")
    if isinstance(raw_tiers, list) and raw_tiers:
        tiers = [str(t) for t in raw_tiers]
    elif isinstance(raw_tiers, str) and raw_tiers.strip():
        tiers = [t.strip() for t in raw_tiers.split(",") if t.strip()]
    else:
        tiers = ["easy", "medium", "hard"]

    before = summary.get("before") if isinstance(summary.get("before"), dict) else {}
    after = summary.get("after") if isinstance(summary.get("after"), dict) else {}
    track_info = classify_policy_track(summary, summary_path=summary_path)

    reasons: list[str] = []
    if track_info["track"] == "unclassified":
        reasons.append(f"classification: unrecognized policy family for model={model!r}")

    n_candidates: list[int] = []
    n_consistent = True
    for scope_name, raw_n in (("n", summary.get("n")), ("before.n", before.get("n")), ("after.n", after.get("n"))):
        if raw_n is not None:
            if not _is_int(raw_n):
                n_consistent = False
                reasons.append(f"replay_and_zero_errors: {scope_name} must be integer, got {raw_n!r}")
            else:
                n_candidates.append(int(raw_n))
    if len(set(n_candidates)) > 1:
        n_consistent = False
        reasons.append(f"replay_and_zero_errors: inconsistent n across summary/before/after: {n_candidates}")
    eff_n = n_candidates[0] if n_candidates else None

    train_seeds, train_err, eval_seeds, eval_err = _extract_seeds_from_summary(summary, before, after)

    c3_reasons: list[str] = []
    if train_err is not None or train_seeds is None:
        c3_reasons.append(f"invalid train_seeds ({train_err})")
    else:
        bad_train = [
            s
            for s in train_seeds
            if not (TRAIN_SEED_MIN <= s < TRAIN_SEED_MAX)
            or s not in TRAIN_SEEDS
            or s in DEV_SEEDS
            or s in HELDOUT_SEEDS
            or s in JUDGE_SEEDS
        ]
        if bad_train:
            c3_reasons.append(f"{len(bad_train)} train seed(s) outside [100000, 200000), sample={bad_train[:5]}")

    if eval_err is not None or eval_seeds is None:
        c3_reasons.append(f"invalid eval_seeds ({eval_err})")
    else:
        bad_eval = [
            s
            for s in eval_seeds
            if not (HELDOUT_SEED_MIN <= s < HELDOUT_SEED_MAX)
            or s not in HELDOUT_SEEDS
            or s in JUDGE_SEEDS
        ]
        if bad_eval:
            c3_reasons.append(
                f"{len(bad_eval)} eval seed(s) outside HELDOUT_SEEDS [800000, 800200), sample={bad_eval[:5]}"
            )

    if train_seeds is not None and eval_seeds is not None:
        overlap = sorted(set(train_seeds) & set(eval_seeds))
        if overlap:
            c3_reasons.append(f"train_seeds and eval_seeds overlap on {len(overlap)} seed(s), sample={overlap[:5]}")

    if "eval_seeds" in before and "eval_seeds" in after:
        b_ev, b_ev_err = _expand_seed_spec(before["eval_seeds"])
        a_ev, a_ev_err = _expand_seed_spec(after["eval_seeds"])
        if b_ev_err or a_ev_err or b_ev != a_ev:
            c3_reasons.append("before.eval_seeds != after.eval_seeds")

    c3_ok = len(c3_reasons) == 0
    for r in c3_reasons:
        reasons.append(f"train_eval_disjoint: {r}")

    raw_b_tag = (
        before.get("world_secret_tag")
        if "world_secret_tag" in before
        else before.get("world_secret_fingerprint", summary.get("before_world_secret_tag"))
    )
    raw_a_tag = (
        after.get("world_secret_tag")
        if "world_secret_tag" in after
        else after.get("world_secret_fingerprint", summary.get("after_world_secret_tag"))
    )
    if raw_b_tag is None and raw_a_tag is None and summary.get("paired") is True:
        shared_tag = summary.get("world_secret_tag")
        raw_b_tag = shared_tag
        raw_a_tag = shared_tag

    b_tag = _valid_secret_tag(raw_b_tag)
    a_tag = _valid_secret_tag(raw_a_tag)
    secret_paired = b_tag is not None and a_tag is not None and b_tag == a_tag

    paired_mean, paired_low, paired_high, paired_deltas, p_reasons = _extract_paired_delta_and_ci(
        summary, before, after, eff_n
    )
    c2_reasons: list[str] = []
    if eval_seeds is None or any(not (HELDOUT_SEED_MIN <= s < HELDOUT_SEED_MAX) for s in eval_seeds):
        c2_reasons.append("eval_seeds not strictly inside HELDOUT_SEEDS [800000, 800200)")
    if not secret_paired:
        c2_reasons.append(f"unpaired or invalid world_secret_tag (before={raw_b_tag!r}, after={raw_a_tag!r})")
    c2_reasons.extend(p_reasons)
    if paired_mean is None or paired_low is None or not (paired_mean > 0.0 and paired_low > 0.0):
        c2_reasons.append(f"paired ci95_low={paired_low!r}, mean_delta={paired_mean!r} (require > 0.0)")
    c2_ok = len(c2_reasons) == 0
    for r in c2_reasons:
        reasons.append(f"paired_delta_ci95_gt_zero: {r}")

    after_mean, after_low, after_high, after_ci_src, a_reasons = _extract_after_score_and_ci(
        summary=summary,
        before=before,
        after=after,
        paired_mean_delta=paired_mean,
        paired_ci95_low=paired_low,
        paired_ci95_high=paired_high,
        paired_deltas=paired_deltas,
        expected_n=eff_n,
    )
    c1_reasons: list[str] = list(a_reasons)
    if after_mean is None or after_mean <= 0.0:
        c1_reasons.append(f"after.mean_score={after_mean!r} <= 0.0")
    if after_low is None or after_low <= 0.0:
        c1_reasons.append(f"after_ci95_low={after_low!r} <= 0.0")
    c1_ok = len(c1_reasons) == 0
    for r in c1_reasons:
        reasons.append(f"heldout_mean_gt_zero: {r}")

    c4_reasons: list[str] = []
    if not n_consistent:
        c4_reasons.append("inconsistent sample size n")
    if eff_n is None or eff_n < MIN_PAIRED_N:
        c4_reasons.append(f"n={eff_n!r} < {MIN_PAIRED_N}")
    if eval_seeds is not None and eff_n is not None:
        max_unique_pairs = len(set(eval_seeds)) * max(1, len(tiers))
        if max_unique_pairs < MIN_PAIRED_N:
            c4_reasons.append(f"distinct (tier, seed) capacity {max_unique_pairs} < {MIN_PAIRED_N}")

    top_rv = summary.get("replay_verified")
    b_rv = before.get("replay_verified")
    a_rv = after.get("replay_verified")
    replay_ok = (top_rv is True and b_rv is not False and a_rv is not False) or (
        top_rv is None and b_rv is True and a_rv is True
    )
    if not replay_ok:
        c4_reasons.append(f"replay_verified is not strictly True (got {top_rv!r})")

    zero_err_ok, zero_err_reasons = _check_zero_error_episodes(summary, before, after)
    if not zero_err_ok:
        c4_reasons.extend(zero_err_reasons)
    c4_ok = len(c4_reasons) == 0
    for r in c4_reasons:
        reasons.append(f"replay_and_zero_errors: {r}")

    resolved_mods, mod_resolve_errs = _resolve_inference_modules(repo_root, summary, summary_path, track_info)
    c5_reasons: list[str] = list(mod_resolve_errs)
    checked_mod_labels: list[str] = []
    checked_policy_classes: list[str] = []
    for mod_lbl, mod_path in resolved_mods:
        checked_mod_labels.append(mod_lbl)
        m_errs, m_classes = audit_inference_module_ast(mod_lbl, mod_path)
        c5_reasons.extend(m_errs)
        checked_policy_classes.extend(m_classes)
    if resolved_mods and not checked_policy_classes:
        c5_reasons.append(f"no inference Policy class (reset+act) found in {checked_mod_labels}")
    c5_ok = len(c5_reasons) == 0
    for r in c5_reasons:
        reasons.append(f"autonomous_inference: {r}")

    criteria_map: dict[str, bool] = {
        "heldout_mean_gt_zero": c1_ok,
        "paired_delta_ci95_gt_zero": c2_ok,
        "train_eval_disjoint": c3_ok,
        "replay_and_zero_errors": c4_ok,
        "autonomous_inference": c5_ok,
    }
    failed_criteria = [name for name in CRITERION_NAMES if not criteria_map[name]]
    all_5_ok = len(failed_criteria) == 0 and track_info["track"] in ("track_1", "track_2")

    if all_5_ok:
        if track_info["track"] == "track_1" and track_info["is_open_weight_llm"]:
            verdict = "PROMOTED_ADDENDUM_READY"
        elif track_info["track"] == "track_1":
            verdict = "PROMOTED_TRACK1_NEURAL"
        else:
            verdict = "PASS_NON_LLM_CONTROL"
    else:
        verdict = "BAR_NOT_MET"

    before_mean = round(float(before["mean_score"]), 6) if _is_finite_num(before.get("mean_score")) else None
    before_valid = round(float(before["valid_call_rate"]), 4) if _is_finite_num(before.get("valid_call_rate")) else None
    after_valid = round(float(after["valid_call_rate"]), 4) if _is_finite_num(after.get("valid_call_rate")) else None

    rec: dict[str, Any] = {
        "run_id": run_id,
        "summary_path": summary_path,
        "track": track_info["track"],
        "track_label": track_info["track_label"],
        "family": track_info["family"],
        "subfamily": track_info["subfamily"],
        "architecture_label": track_info["architecture_label"],
        "is_open_weight_llm": track_info["is_open_weight_llm"],
        "model": model,
        "tiers_version": tiers_version,
        "tiers": tiers,
        "n": eff_n,
        "before_mean_score": before_mean,
        "after_mean_score": after_mean,
        "after_ci95_low": after_low,
        "after_ci95_high": after_high,
        "after_ci95_source": after_ci_src,
        "paired_mean_delta": paired_mean,
        "paired_ci95_low": paired_low,
        "paired_ci95_high": paired_high,
        "before_valid_call_rate": before_valid,
        "after_valid_call_rate": after_valid,
        "before_world_secret_tag": b_tag,
        "after_world_secret_tag": a_tag,
        "world_secret_paired": secret_paired,
        "replay_verified": bool(replay_ok),
        "zero_invalid_episodes": bool(zero_err_ok),
        "inference_modules_checked": checked_mod_labels,
        "inference_policy_classes": checked_policy_classes,
        "criteria": criteria_map,
        "criteria_passed_count": sum(1 for v in criteria_map.values() if v),
        "passed_panel_fix_e_bar": all_5_ok,
        "failed_criteria": failed_criteria,
        "verdict": verdict,
        "gates": {
            "reasons": reasons,
        },
        "notes": str(summary.get("notes") or summary.get("description") or "").replace(EM_DASH, "-").replace(EN_DASH, "-"),
    }
    if c3_ok and train_seeds and eval_seeds:
        rec["train_seed_range"] = f"{min(train_seeds)}..{max(train_seeds)}"
        rec["eval_seed_range"] = f"{min(eval_seeds)}..{max(eval_seeds)}"
    return rec


def discover_run_summaries(
    repo_root: Path = ROOT,
    summary_glob: str = "results/tiebreak/*/summary.json",
    extra_globs: list[str] | None = None,
    include_scaling_summary: bool = True,
) -> list[dict[str, Any]]:
    patterns: list[str] = []
    p_main = Path(summary_glob)
    patterns.append(str(p_main if p_main.is_absolute() else (repo_root / summary_glob)))
    for eg in extra_globs or []:
        if eg:
            p_eg = Path(eg)
            patterns.append(str(p_eg if p_eg.is_absolute() else (repo_root / eg)))

    matched_files: dict[Path, str] = {}
    covered_dirs: set[Path] = set()
    for pat in patterns:
        for hit in sorted(glob.glob(pat)):
            hp = Path(hit).resolve()
            if hp.is_file() and hp not in matched_files:
                try:
                    disp = str(hp.relative_to(repo_root.resolve()))
                except ValueError:
                    disp = str(hp)
                matched_files[hp] = disp
                covered_dirs.add(hp.parent)

    if include_scaling_summary and summary_glob == "results/tiebreak/*/summary.json":
        scaling_path = (repo_root / "results" / "tiebreak" / "scaling" / "scaling_summary.json").resolve()
        if scaling_path.is_file() and scaling_path.parent not in covered_dirs and scaling_path not in matched_files:
            matched_files[scaling_path] = str(scaling_path.relative_to(repo_root.resolve()))

    evaluated: list[dict[str, Any]] = []
    for hp in sorted(matched_files, key=lambda p: matched_files[p]):
        disp = matched_files[hp]
        raw = json.loads(hp.read_text(encoding="utf-8"))
        evaluated.append(evaluate_run_summary(raw, summary_path=disp, repo_root=repo_root))
    return evaluated


def build_addendum_readiness(
    repo_root: Path = ROOT,
    summary_glob: str = "results/tiebreak/*/summary.json",
    extra_globs: list[str] | None = None,
    include_scaling_summary: bool = True,
) -> dict[str, Any]:
    runs = discover_run_summaries(
        repo_root=repo_root,
        summary_glob=summary_glob,
        extra_globs=extra_globs,
        include_scaling_summary=include_scaling_summary,
    )

    track1_runs = [r for r in runs if r["track"] == "track_1"]
    track2_runs = [r for r in runs if r["track"] == "track_2"]
    unclassified_runs = [r for r in runs if r["track"] not in ("track_1", "track_2")]

    track1_passing = [r for r in track1_runs if r["passed_panel_fix_e_bar"]]
    track1_llm_passing = [r for r in track1_passing if r["is_open_weight_llm"]]
    track1_neural_passing = [r for r in track1_passing if not r["is_open_weight_llm"]]
    track2_passing = [r for r in track2_runs if r["passed_panel_fix_e_bar"]]

    if track1_llm_passing:
        llm_status = "PROMOTED_FOR_ADDENDUM"
        track1_overall = "PROMOTED_FOR_ADDENDUM"
        addendum_action = "APPEND_TO_README"
    elif track1_neural_passing:
        llm_status = "AWAITING_V100_COMPLETION"
        track1_overall = "PASS_NEURAL_MLP_AWAITING_V100_LLM"
        addendum_action = "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    else:
        llm_status = "AWAITING_V100_COMPLETION"
        track1_overall = "AWAITING_V100_COMPLETION"
        addendum_action = "DO_NOT_APPEND_YET"

    return {
        "schema": "canary.tiebreak.panel_fix_e_addendum.v1",
        "tiers_version": "v1.4",
        "panel_fix_e_rule": (
            "Per README.md and docs/agents/PANEL-0500.md (Fix E), a tiebreak run is added as a "
            "README addendum only if held-out mean_score > 0.0 with a 95% CI excluding 0.0 under "
            "one shared CANARY_WORLD_SECRET on HELDOUT_SEEDS [800000, 800200)."
        ),
        "dev_protocol_note": (
            "Headline frontier comparisons on dev 0..29 use a post-hoc locked set (not pre-registered); "
            "all tiebreak evaluations here use disjoint HELDOUT_SEEDS [800000, 800200)."
        ),
        "criteria_definitions": dict(CRITERIA_DEFINITIONS),
        "readiness_summary": {
            "discovered_runs_total": len(runs),
            "unclassified_runs_count": len(unclassified_runs),
            "track1_discovered_count": len(track1_runs),
            "track1_passing_count": len(track1_passing),
            "track1_llm_passing_count": len(track1_llm_passing),
            "track1_neural_mlp_passing_count": len(track1_neural_passing),
            "track1_failed_count": len(track1_runs) - len(track1_passing),
            "track1_llm_dagger_status": llm_status,
            "track1_overall_status": track1_overall,
            "readme_qwen_addendum_eligible": len(track1_llm_passing) > 0,
            "track1_any_passed": len(track1_passing) > 0,
            "readme_addendum_action": addendum_action,
            "promoted_track1_run_ids": [r["run_id"] for r in track1_passing],
            "promoted_track1_llm_run_ids": [r["run_id"] for r in track1_llm_passing],
            "track2_discovered_count": len(track2_runs),
            "track2_passing_count": len(track2_passing),
            "track2_passing_run_ids": [r["run_id"] for r in track2_passing],
            "track2_separation_policy": (
                "Compact parametric and empirical-Bayes policies are non-LLM CPU/closed-form "
                "upper-bound and ablation controls, strictly separated from Qwen2.5 LoRA."
            ),
        },
        "readme_published_baseline": [dict(row) for row in README_PUBLISHED_BASELINE],
        "track_1_runs": track1_runs,
        "track_2_runs": track2_runs,
        "unclassified_runs": unclassified_runs,
    }


def _fmt_after_score(run: dict[str, Any]) -> str:
    m = run.get("after_mean_score")
    lo = run.get("after_ci95_low")
    hi = run.get("after_ci95_high")
    if m is None:
        return "n/a"
    if lo is not None and hi is not None:
        hw = 0.5 * (hi - lo)
        return f"{m:+.3f} +/- {hw:.3f} [{lo:+.3f}, {hi:+.3f}]"
    if lo is not None:
        return f"{m:+.3f} (ci95_low {lo:+.3f})"
    return f"{m:+.3f}"


def _fmt_paired_delta(run: dict[str, Any]) -> str:
    d = run.get("paired_mean_delta")
    lo = run.get("paired_ci95_low")
    hi = run.get("paired_ci95_high")
    if d is None:
        return "n/a"
    if lo is not None and hi is not None:
        return f"{d:+.3f} [{lo:+.3f}, {hi:+.3f}]"
    if lo is not None:
        return f"{d:+.3f} (ci95_low {lo:+.3f})"
    return f"{d:+.3f}"


def _fmt_secret_short(run: dict[str, Any]) -> str:
    b = run.get("before_world_secret_tag")
    a = run.get("after_world_secret_tag")
    if run.get("world_secret_paired") and a:
        return f"paired ({a[:15]})"
    if b or a:
        return f"unpaired ({(b or 'none')[:10]} vs {(a or 'none')[:10]})"
    return "unpaired"


def render_addendum_markdown(readiness: dict[str, Any]) -> str:
    h1 = MD_H
    h2 = MD_H * 2

    rs = readiness["readiness_summary"]
    t1_runs = readiness["track_1_runs"]
    t2_runs = readiness["track_2_runs"]
    t1_passing = [r for r in t1_runs if r["passed_panel_fix_e_bar"]]
    t1_llm_passing = [r for r in t1_passing if r["is_open_weight_llm"]]
    t1_neural_passing = [r for r in t1_passing if not r["is_open_weight_llm"]]
    t2_passing = [r for r in t2_runs if r["passed_panel_fix_e_bar"]]

    lines: list[str] = [
        f"{h1} Panel Fix E Tiebreak Addendum Pack",
        "",
        "Deterministic readiness audit for `README.md` (`Tiebreak: a small model trained on Canary experience`) "
        "and `docs/agents/PANEL-0500.md` (`Fix E. Tiebreak`: added as an addendum only if held-out mean > 0 "
        "with a 95% CI excluding 0 under one shared `CANARY_WORLD_SECRET` on `HELDOUT_SEEDS`). "
        "Note on `README.md` frontier seeds: dev seeds `0..29` are `post-hoc locked` (not pre-registered); "
        "all tiebreak evaluations below strictly use disjoint `TRAIN_SEEDS [100000, 200000)` and "
        "`HELDOUT_SEEDS [800000, 800200)`.",
        "",
        f"- Track 1 Open-Weight LLM DAgger Status: `{rs['track1_llm_dagger_status']}`",
        f"- README Addendum Action: `{rs['readme_addendum_action']}`",
        f"- Track 1 Passing Runs (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` / `TinyMLP`): `{rs['track1_passing_count']} / {rs['track1_discovered_count']}`",
        f"- Track 2 Non-LLM Parametric Controls Passing 5/5 Criteria: `{rs['track2_passing_count']} / {rs['track2_discovered_count']}`",
        "",
        f"{h2} 1. Ready-to-Paste `README.md` Tiebreak Addendum (Track 1: Open-Weight LLM / Neural Policies)",
        "",
        "| Model / Run | Architecture | Held-Out Score +/- 95% CI | Paired Delta [95% CI] | n | World Secret | Panel Fix E Status |",
        "|---|---|---|---|---:|---|---|",
    ]

    for base_row in readiness["readme_published_baseline"]:
        if base_row["ci95"] is None:
            sc_txt = f"{base_row['mean_score']:.3f} ({base_row['note']})"
        else:
            sc_txt = f"{base_row['mean_score']:+.3f} +/- {base_row['ci95']:.3f}"
        lines.append(
            f"| {base_row['label']} | {base_row['architecture']} | {sc_txt} | two-sample / n/a | "
            f"{base_row['n']} | per-process (unpaired) | `PUBLISHED_BASELINE` |"
        )

    ordered_t1 = sorted(t1_runs, key=lambda r: (not r["passed_panel_fix_e_bar"], not r["is_open_weight_llm"], r["run_id"]))
    for r in ordered_t1:
        n_txt = str(r["n"]) if r["n"] is not None else "0"
        gate_badge = (
            f"`{r['verdict']}` (5/5)"
            if r["passed_panel_fix_e_bar"]
            else f"`BAR_NOT_MET` ({r['criteria_passed_count']}/5; failed: {','.join(r['failed_criteria'])})"
        )
        lines.append(
            f"| `{r['run_id']}` ({r['model']}) | {r['architecture_label']} | `{_fmt_after_score(r)}` | "
            f"`{_fmt_paired_delta(r)}` | {n_txt} | `{_fmt_secret_short(r)}` | {gate_badge} |"
        )

    if not t1_llm_passing:
        lines.append(
            "| DAgger round 1 (`Qwen2.5-1.5B` / `Qwen2.5-0.5B` LoRA, V100) | Open-weight LLM (LoRA) | "
            "pending V100 completion | pending paired eval | >=30 | shared `CANARY_WORLD_SECRET` | "
            "`AWAITING_V100_COMPLETION` |"
        )

    if t1_llm_passing:
        best_llm = max(t1_llm_passing, key=lambda r: float(r["after_mean_score"] or 0.0))
        bullet_1 = (
            f"**Panel Fix E Bar Met (`PROMOTED_FOR_ADDENDUM`)**: `{best_llm['run_id']}` ({best_llm['model']}) "
            f"reaches held-out score `{_fmt_after_score(best_llm)}` with paired gain "
            f"`{_fmt_paired_delta(best_llm)}` over `n={best_llm['n']}` replay-verified episodes under shared "
            f"world secret `{best_llm['after_world_secret_tag']}`, passing all 5 Panel Fix E gates."
        )
    elif t1_neural_passing:
        best_nn = max(t1_neural_passing, key=lambda r: float(r["after_mean_score"] or 0.0))
        bullet_1 = (
            f"**Open-Weight LLM DAgger Status (`AWAITING_V100_COMPLETION`)**: no `Qwen2.5` V100 LoRA run has "
            f"completed all 5 gates yet (so the `README.md` Qwen addendum stays withheld per `PANEL-0500.md`), "
            f"while Track 1 compact neural policy `{best_nn['run_id']}` ({best_nn['architecture_label']}) "
            f"passes 5/5 gates at `{_fmt_after_score(best_nn)}` (paired delta `{_fmt_paired_delta(best_nn)}`, `n={best_nn['n']}`)."
        )
    elif t1_runs:
        failed_ids = ", ".join(f"`{r['run_id']}`" for r in t1_runs)
        bullet_1 = (
            f"**Track 1 Status (`AWAITING_V100_COMPLETION` / Bar Not Met)**: `{len(t1_runs)}` Track 1 run(s) "
            f"({failed_ids}) were audited and `0/{len(t1_runs)}` passed all 5 Panel Fix E gates; per "
            f"`PANEL-0500.md`, no addendum is appended unless held-out mean and 95% CI strictly exceed `0.0`."
        )
    else:
        bullet_1 = (
            "**Track 1 LLM DAgger Status (`AWAITING_V100_COMPLETION`)**: `0` Track 1 `results/tiebreak/*/summary.json` "
            "runs have passed all 5 gates yet while V100 DAgger jobs run; per `PANEL-0500.md` Fix E, `README.md` "
            "keeps its honest negative Qwen2.5 table unchanged until a paired V100 run clears `0.0` with 95% CI > `0.0`."
        )

    bullet_2 = (
        "**Published Raw-Context Qwen2.5-1.5B Progression**: reward training fixed `v2`'s blind accusations "
        "(`v3-4k` `-0.147 +/- 0.063`, `n=180` vs `v2` `-0.457 +/- 0.086`, `n=172`; `+0.310 +/- 0.107` two-sample, "
        "`100%` valid tool calls) and `v3-8k seed 2` reached `-0.050 +/- 0.049` (`n=90`), but `2,842`-token prompt "
        "headers and off-policy states prevented positive held-out score without on-policy DAgger / compact working memory."
    )

    bullet_3 = (
        "**5-Criterion Panel Fix E Gate**: every candidate run is machine-checked for (1) `heldout_mean_gt_zero` "
        "(`after.mean_score > 0` and `after_ci95_low > 0`), (2) `paired_delta_ci95_gt_zero` under one shared "
        "`world_secret_tag` on `HELDOUT_SEEDS [800000, 800200)`, (3) `train_eval_disjoint` strictly inside "
        "`TRAIN_SEEDS [100000, 200000)`, (4) `replay_and_zero_errors` (`n >= 30`, `replay_verified = True`, "
        "`invalid_episodes = 0`), and (5) AST-verified `autonomous_inference` (`0` `canary.solver` / `canary.world` imports)."
    )

    if t2_passing:
        t2_parts = [
            f"`{r['run_id']}` (`{r['family']}`, held-out `{_fmt_after_score(r)}`, paired delta `{_fmt_paired_delta(r)}`, `n={r['n']}`)"
            for r in t2_passing
        ]
        bullet_4 = (
            f"**Track 2 Non-LLM Parametric Controls (Strictly Separated from Qwen LoRA)**: {'; '.join(t2_parts)} "
            "pass all 5 mathematical and AST-isolation criteria on CPU, establishing a clean non-LLM empirical-Bayes / "
            "parametric upper-bound control that is never conflated with open-weight Qwen2.5 LoRA."
        )
    else:
        bullet_4 = (
            "**Track 2 Non-LLM Parametric Controls (Strictly Separated from Qwen LoRA)**: compact parametric and "
            "empirical-Bayes runs are isolated in Section 3 below so non-LLM controls are never conflated with Qwen2.5 LoRA."
        )

    lines.extend([
        "",
        f"{h2} 2. Four-Bullet Addendum Summary",
        "",
        f"- {bullet_1}",
        f"- {bullet_2}",
        f"- {bullet_3}",
        f"- {bullet_4}",
        "",
        f"{h2} 3. Track 2 Non-LLM Parametric and Empirical-Bayes Controls (Not Conflated With Qwen2.5 LoRA)",
        "",
        "| Run ID | Policy Family (Non-LLM) | Held-Out Score +/- 95% CI | Paired Delta [95% CI] | n | Shared Secret | AST Audited Module(s) | Verdict |",
        "|---|---|---|---|---:|---|---|---|",
    ])

    if t2_runs:
        for r in t2_runs:
            mods_txt = ", ".join(r["inference_modules_checked"]) or "none"
            n_txt = str(r["n"]) if r["n"] is not None else "0"
            lines.append(
                f"| `{r['run_id']}` | `{r['family']}` (non-LLM control) | `{_fmt_after_score(r)}` | "
                f"`{_fmt_paired_delta(r)}` | {n_txt} | `{_fmt_secret_short(r)}` | `{mods_txt}` | `{r['verdict']}` |"
            )
    else:
        lines.append("| none | non-LLM control | n/a | n/a | 0 | n/a | n/a | `NONE_DISCOVERED` |")

    lines.extend([
        "",
        f"{h2} 4. Complete 5-Criterion Panel Fix E Audit Matrix",
        "",
        "| Run ID | Track | Family | C1 `heldout>0` | C2 `paired_ci>0` | C3 `disjoint_seeds` | C4 `replay_n>=30` | C5 `ast_isolated` | Passed | Verdict |",
        "|---|---|---|---|---|---|---|---|---:|---|",
    ])

    all_discovered = [*t1_runs, *t2_runs, *readiness["unclassified_runs"]]
    if all_discovered:
        for r in all_discovered:
            c = r["criteria"]
            b1 = "PASS" if c["heldout_mean_gt_zero"] else "FAIL"
            b2 = "PASS" if c["paired_delta_ci95_gt_zero"] else "FAIL"
            b3 = "PASS" if c["train_eval_disjoint"] else "FAIL"
            b4 = "PASS" if c["replay_and_zero_errors"] else "FAIL"
            b5 = "PASS" if c["autonomous_inference"] else "FAIL"
            lines.append(
                f"| `{r['run_id']}` | `{r['track']}` | `{r['family']}` | `{b1}` | `{b2}` | `{b3}` | `{b4}` | `{b5}` | "
                f"{r['criteria_passed_count']}/5 | `{r['verdict']}` |"
            )
    else:
        lines.append("| none | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0/5 | `NONE_DISCOVERED` |")

    lines.extend([
        "",
        f"{h2} 5. Offline Verification Commands",
        "",
        "```bash",
        "python scripts/tiebreak_addendum_pack.py",
        "python scripts/tiebreak_addendum_pack.py --check",
        "```",
        "",
    ])
    return "\n".join(lines)


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


def check_addendum_pack(
    readiness: dict[str, Any],
    md_text: str,
    out_json: Path,
    out_md: Path,
) -> list[str]:
    errors: list[str] = []
    rs = readiness["readiness_summary"]

    if rs["unclassified_runs_count"] != 0:
        bad_ids = [r["run_id"] for r in readiness["unclassified_runs"]]
        errors.append(f"unclassified tiebreak summary run(s) found: {bad_ids}")

    for t2 in readiness["track_2_runs"]:
        if t2["is_open_weight_llm"]:
            errors.append(f"Track 2 non-LLM run {t2['run_id']} illegally marked is_open_weight_llm=True")
        if t2["run_id"] in rs["promoted_track1_run_ids"] or t2["run_id"] in rs["promoted_track1_llm_run_ids"]:
            errors.append(f"Track 2 non-LLM run {t2['run_id']} leaked into promoted Track 1 list")

    expected_llm_ready = rs["track1_llm_passing_count"] > 0
    if rs["readme_qwen_addendum_eligible"] is not expected_llm_ready:
        errors.append("readme_qwen_addendum_eligible inconsistent with track1_llm_passing_count")

    if not expected_llm_ready and rs["track1_llm_dagger_status"] != "AWAITING_V100_COMPLETION":
        errors.append(
            f"expected track1_llm_dagger_status='AWAITING_V100_COMPLETION' when 0 LLM runs pass, got {rs['track1_llm_dagger_status']!r}"
        )
    if expected_llm_ready and rs["track1_llm_dagger_status"] != "PROMOTED_FOR_ADDENDUM":
        errors.append(
            f"expected track1_llm_dagger_status='PROMOTED_FOR_ADDENDUM' when >=1 LLM run passes, got {rs['track1_llm_dagger_status']!r}"
        )

    sec2_header = f"{MD_H * 2} 2. Four-Bullet Addendum Summary"
    sec3_header = f"{MD_H * 2} 3. Track 2 Non-LLM"
    if sec2_header not in md_text or sec3_header not in md_text:
        errors.append("markdown report missing Section 2 or Section 3 header")
    else:
        sec2_body = md_text.split(sec2_header, 1)[1].split(sec3_header, 1)[0]
        bullets = [ln for ln in sec2_body.splitlines() if ln.startswith("- ")]
        if len(bullets) != 4:
            errors.append(f"Section 2 must contain exactly 4 summary bullets, found {len(bullets)}")

    expected_json_str = json.dumps(readiness, indent=2) + "\n"
    if not out_json.is_file():
        errors.append(f"missing addendum readiness JSON: {out_json}")
    else:
        actual_json_str = out_json.read_text(encoding="utf-8")
        if actual_json_str != expected_json_str:
            errors.append(f"stale or modified addendum readiness JSON: {out_json}")

    if not out_md.is_file():
        errors.append(f"missing addendum Markdown report: {out_md}")
    else:
        actual_md_str = out_md.read_text(encoding="utf-8")
        if actual_md_str != md_text:
            errors.append(f"stale or modified addendum Markdown report: {out_md}")

    for label, text in (("json", expected_json_str), ("md", md_text)):
        if EM_DASH in text or EN_DASH in text:
            errors.append(f"em or en dash found in generated {label}")
        prereg_hits = _has_affirmative_prereg_0_29(text)
        if prereg_hits:
            errors.append(f"Panel Fix A violation in generated {label}: {prereg_hits[0]}")

    return errors


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generate and verify the Panel Fix E tiebreak addendum pack."
    )
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--summary-glob", default="results/tiebreak/*/summary.json")
    ap.add_argument("--extra-glob", action="append", default=[])
    ap.add_argument("--no-scaling-summary", action="store_true")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    out_json = (args.out_json or (repo_root / "results" / "tiebreak" / "addendum_readiness.json")).resolve()
    out_md = (args.out_md or (repo_root / "docs" / "reports" / "tiebreak_panel_e_addendum.md")).resolve()

    readiness = build_addendum_readiness(
        repo_root=repo_root,
        summary_glob=args.summary_glob,
        extra_globs=list(args.extra_glob),
        include_scaling_summary=not args.no_scaling_summary,
    )
    md_text = render_addendum_markdown(readiness)

    if args.check:
        errs = check_addendum_pack(readiness, md_text, out_json, out_md)
        if errs:
            for err in errs:
                print(f"[FAIL] {err}", file=sys.stderr)
            return 1
        print(
            json.dumps({
                "ok": True,
                "track1_llm_dagger_status": readiness["readiness_summary"]["track1_llm_dagger_status"],
                "track1_passing_count": readiness["readiness_summary"]["track1_passing_count"],
                "track2_passing_count": readiness["readiness_summary"]["track2_passing_count"],
                "readme_qwen_addendum_eligible": readiness["readiness_summary"]["readme_qwen_addendum_eligible"],
            })
        )
        return 0

    if readiness["readiness_summary"]["unclassified_runs_count"] != 0:
        bad_ids = [r["run_id"] for r in readiness["unclassified_runs"]]
        print(f"[FAIL] unclassified tiebreak summary run(s): {bad_ids}", file=sys.stderr)
        return 1

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(readiness, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(md_text, encoding="utf-8")

    post_errs = check_addendum_pack(readiness, md_text, out_json, out_md)
    if post_errs:
        for err in post_errs:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1

    print(
        json.dumps({
            "wrote_json": str(out_json),
            "wrote_md": str(out_md),
            "readiness_summary": readiness["readiness_summary"],
        })
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
